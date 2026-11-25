"""Club tournaments and shared league and cup formats."""

from __future__ import annotations

import random
from typing import Any

from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.scheduling import group_schedule_patterns
from audiofutbol.domain.models import Team


class ClubTournament(NationsLeague):
    """Base for club tournaments sharing NationsLeague standings/knockout mechanics."""

    KEY = "clubes"
    TITLE = "Torneo de clubes"
    UNIT_LABEL = "equipo"
    NO_EXTRA_TIME = False
    ROUND_NAMES: dict[Any, str] = {}

    def _init_club_base(self, teams: list[Team], user_team: Team) -> None:
        super().__init__(teams, user_team, away_goals_rule=False, _skip_init=True)
        self.final_venue = self.FINAL_VENUE

    def phase_name(self) -> str:
        kind, data = self.steps[self.step_idx]
        if kind == "liga":
            phase_label = self.LEAGUE_PHASE_LABEL.replace("la ", "", 1).capitalize()
            return f"{phase_label}, jornada {data + 1} de {self.rounds_count}"
        name = self.ROUND_NAMES[data]
        if kind == "unico":
            return name
        leg = "ida" if kind == "ida" else "vuelta"
        return f"{name}, partido de {leg}"

    def group_of(self, team: Team) -> list[Team]:
        assert self.groups is not None
        for grp in self.groups:
            if team in grp:
                return grp
        return self.groups[0]

    def _sort_group(self, grp: list[Team]) -> list[Team]:
        return sorted(grp, key=self._sort_key)

    def standings(self) -> list[Team]:
        assert self.groups is not None
        out: list[Team] = []
        for grp in self.groups:
            out.extend(self._sort_group(grp))
        return out

    def user_position(self) -> tuple[int, dict[str, int]]:
        order = self._sort_group(self.group_of(self.user_team))
        return order.index(self.user_team) + 1, self.table[self.user_team.name]

    def zone_label(self, rank: int, finished: bool) -> str:
        return ""

    def table_lines(self) -> list[str]:
        assert self.groups is not None
        out: list[str] = []
        finished = self.step_type() != "liga" or self.champion is not None
        for grp in self.groups:
            if len(self.groups) > 1 and grp[0].group:
                out.append(f"Grupo {grp[0].group}.")
            for idx, team in enumerate(self._sort_group(grp)):
                row = self.table[team.name]
                mine = ". Es tu equipo" if team is self.user_team else ""
                out.append(
                    f"{idx + 1}. {team.name}, {row['pts']} puntos, {row['pj']} jugados, "
                    f"{row['g']} ganados, {row['e']} empatados, {row['p']} perdidos, "
                    f"goles {row['gf']} a {row['gc']}, diferencia {row['gf'] - row['gc']:+d}, "
                    f"fair play {row.get('fp', 0)}. De local {row.get('lpts', 0)} puntos, "
                    f"de visitante {row.get('vpts', 0)} puntos. "
                    f"{self.zone_label(idx + 1, finished)}{mine}"
                )
        return out

    def _winners(self) -> list[Team]:
        return [self.tie_winner(c) for c in self.ties]

    def _losers(self) -> list[Team]:
        return [self.tie_loser(c) for c in self.ties]

    def _round_notice(self, losers: list[Team]) -> str:
        if self.user_team in losers:
            self.user_eliminated = True
            return f"{self.user_team.name} queda eliminado."
        if not self.user_eliminated:
            return f"{self.user_team.name} pasa a la siguiente ronda."
        return ""

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        kwargs = super().match_kwargs(idx, first_team)
        if kwargs:
            kwargs["no_extra_time"] = self.NO_EXTRA_TIME
        return kwargs

    def _finish_final(self) -> str:
        tie = self.ties[0]
        self.champion = self.tie_winner(tie)
        self.runner_up = self.tie_loser(tie)
        return f"{self.champion.name} es el campeón de la {self.TITLE}."


class ChampionsLeague(ClubTournament):
    """UEFA Champions League 2026-27: 36 clubs, 8-match league phase, playoff, KO, final."""

    KEY = "champions"
    TITLE = "Liga de Campeones de la UEFA"
    LEAGUE_PHASE_LABEL = "la fase de liga"
    FINAL_VENUE = ("Riyadh Air Metropolitano", "Madrid")
    ROUND_NAMES = {
        "po": "Play-off de eliminación",
        16: "Octavos de final",
        8: "Cuartos de final",
        4: "Semifinales",
        2: "La gran final",
    }

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        self._init_club_base(list(teams_by_id.values()), user_team)
        self.groups = [self.teams]
        self.rounds_count = 8
        self.qualify_count = 24
        self.direct_qualifiers: list[Team] = []
        if not _skip_init and data is not None:
            phase = [f for f in data["fases"] if f["id"] == "fase_liga"][0]
            self.schedule = [
                [
                    (teams_by_id[p["local"]], teams_by_id[p["visitante"]])
                    for p in rnd["partidos"]
                ]
                for rnd in sorted(phase["jornadas"], key=lambda j: j["numero"])
            ]
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            for rnd_key in ("po", 16, 8, 4):
                self.steps.append(("ida", rnd_key))
                self.steps.append(("vuelta", rnd_key))
            self.steps.append(("unico", 2))
            self._prepare_step()

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 8:
            return "Clasificado directo a octavos" if finished else "En zona de octavos directos"
        if rank <= 24:
            return "Juega el play-off" if finished else "En zona de play-off"
        return "Eliminado" if finished else "Fuera de la zona"

    def position_text(self) -> str:
        rank, row = self.user_position()
        if rank <= 8:
            zone = "Estás en zona de octavos de final directos."
        elif rank <= 24:
            zone = "Estás en zona de play-off. Los 8 primeros pasan directo a octavos."
        else:
            zone = "Estás fuera de la zona de clasificación. Hay que llegar al puesto 24."
        return (
            f"{self.user_team.name} va en el puesto {rank} de {len(self.teams)}, "
            f"con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}. {zone}"
        )

    def _playoff_ties(self, po: list[Team]) -> list[dict[str, Any]]:
        pots = [
            (po[0:2], po[14:16]),
            (po[2:4], po[12:14]),
            (po[4:6], po[10:12]),
            (po[6:8], po[8:10]),
        ]
        out: list[dict[str, Any]] = []
        for pot_idx, (seeded, unseeded) in enumerate(pots):
            pool = list(unseeded)
            random.shuffle(pool)
            for s, u in zip(seeded, pool):
                tie = self._make_tie(u, s)
                tie["pot"] = pot_idx
                out.append(tie)
        return out

    def _round_of_16_ties(self, winners: list[Team]) -> list[dict[str, Any]]:
        by_pot: dict[int, list[Team]] = {}
        for tie, winner in zip(self.ties, winners):
            by_pot.setdefault(int(tie["pot"]), []).append(winner)
        d = self.direct_qualifiers
        brackets: dict[int, list[dict[str, Any]]] = {}
        for pot_idx, pair in ((3, d[0:2]), (2, d[2:4]), (1, d[4:6]), (0, d[6:8])):
            w = list(by_pot[pot_idx])
            random.shuffle(w)
            brackets[pot_idx] = [self._make_tie(w[0], pair[0]), self._make_tie(w[1], pair[1])]
        return [
            brackets[3][0], brackets[0][0], brackets[2][0], brackets[1][0],
            brackets[1][1], brackets[2][1], brackets[0][1], brackets[3][1],
        ]

    def close_step(self) -> str:
        kind, data = self.steps[self.step_idx]
        notice = ""
        if kind == "liga":
            if data == self.rounds_count - 1:
                order = self.standings()
                self.ranking = {t.name: k + 1 for k, t in enumerate(order)}
                self.direct_qualifiers = order[:8]
                self.qualified = order[:24]
                self.ties = self._playoff_ties(order[8:24])
                pos = self.ranking[self.user_team.name]
                if self.user_team in self.direct_qualifiers:
                    notice = (
                        f"Terminó la fase de liga. {self.user_team.name} termina en el puesto "
                        f"{pos} y pasa directo a octavos de final."
                    )
                elif self.user_team in order[8:24]:
                    notice = (
                        f"Terminó la fase de liga. {self.user_team.name} termina en el puesto "
                        f"{pos} y juega el play-off de eliminación."
                    )
                else:
                    self.user_eliminated = True
                    notice = (
                        f"Terminó la fase de liga. {self.user_team.name} termina en el puesto "
                        f"{pos} y queda eliminado."
                    )
        elif kind == "vuelta":
            winners, losers = self._winners(), self._losers()
            if data == "po":
                if self.user_team in losers:
                    self.user_eliminated = True
                    notice = f"{self.user_team.name} queda eliminado en el play-off."
                elif not self.user_eliminated:
                    notice = f"{self.user_team.name} pasa a octavos de final."
                self.ties = self._round_of_16_ties(winners)
            else:
                notice = self._round_notice(losers)
                self.ties = self._next_round_ties(winners)
                if data == 4:
                    notice = (
                        f"{notice} La final se juega en {self.final_venue[0]}, "
                        f"ciudad de {self.final_venue[1]}, en campo neutral."
                    ).strip()
        elif kind == "unico":
            return self._finish_final()
        self.step_idx += 1
        self._prepare_step()
        return notice

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["direct_qualifiers"] = [t.name for t in self.direct_qualifiers]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChampionsLeague:
        teams = [Team.from_dict(t) for t in data["teams"]]
        by_name = {t.name: t for t in teams}
        inst = cls(None, {t.team_id or t.name: t for t in teams}, by_name[data["user_team"]], _skip_init=True)
        inst._restore_common(data, by_name)
        inst.direct_qualifiers = [by_name[n] for n in data.get("direct_qualifiers", [])]
        return inst


class GroupCup(ClubTournament):
    """Club cup with 4-team double round-robin groups, two-legged KO (no ET), neutral final."""

    KEY = "copa_grupos"
    TITLE = "Copa de clubes"
    LEAGUE_PHASE_LABEL = "la fase de grupos"
    NO_EXTRA_TIME = True
    FINAL_VENUE = ("Estadio Centenario", "Montevideo")
    ROUND_NAMES = {
        32: "Dieciseisavos de final",
        16: "Octavos de final",
        8: "Cuartos de final",
        4: "Semifinales",
        2: "La gran final",
    }

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        self._init_club_base(list(teams_by_id.values()), user_team)
        if not _skip_init:
            if data and data.get("sede_final"):
                self.final_venue = (str(data["sede_final"][0]), str(data["sede_final"][1]))
            if any(t.group is None for t in self.teams):
                self._draw_groups()
            grouped: dict[str, list[Team]] = {}
            for team in self.teams:
                grouped.setdefault(team.group or "A", []).append(team)
            self.groups = [grouped[k] for k in sorted(grouped)]
            self.rounds_count = 6
            self.qualify_count = 2 * len(self.groups)
            self.schedule = self._build_group_schedule()
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            t = self.qualify_count
            while t >= 4:
                self.steps.append(("ida", t))
                self.steps.append(("vuelta", t))
                t //= 2
            self.steps.append(("unico", 2))
            self._prepare_step()

    def _draw_groups(self) -> None:
        pool = list(self.teams)
        g_count = len(pool) // 4
        random.shuffle(pool)
        pool.sort(key=lambda t: -t.level)
        pots = [pool[i * g_count : (i + 1) * g_count] for i in range(4)]
        best: list[list[Team]] = []
        best_penalty: int | None = None
        for _ in range(400):
            groups: list[list[Team]] = [[] for _ in range(g_count)]
            for pot in pots:
                shuffled = list(pot)
                random.shuffle(shuffled)
                for grp, team in zip(groups, shuffled):
                    grp.append(team)
            penalty = 0
            for grp in groups:
                counts: dict[str, int] = {}
                for team in grp:
                    counts[team.country] = counts.get(team.country, 0) + 1
                penalty += sum(v * (v - 1) // 2 for v in counts.values())
            if best_penalty is None or penalty < best_penalty:
                best, best_penalty = groups, penalty
        for idx, grp in enumerate(best):
            for team in grp:
                team.group = chr(65 + idx)

    def _build_group_schedule(self) -> list[list[tuple[Team, Team]]]:
        assert self.groups is not None
        rounds: list[list[tuple[Team, Team]]] = [[] for _ in range(6)]
        patterns = group_schedule_patterns()
        for grp in self.groups:
            sampled = random.sample(grp, 4)
            pat = random.choice(patterns)
            for r_idx, pairs in enumerate(pat):
                rounds[r_idx].extend((sampled[h], sampled[v]) for h, v in pairs)
        return rounds

    def _first_ko_round_name(self) -> str:
        return self.ROUND_NAMES.get(self.qualify_count, "la siguiente fase").lower()

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 2:
            return (
                f"Clasificado a {self._first_ko_round_name()}"
                if finished
                else "En zona de clasificación"
            )
        return "Eliminado" if finished else "Fuera de la zona"

    def position_text(self) -> str:
        rank, row = self.user_position()
        zone = (
            "Estás en zona de clasificación."
            if rank <= 2
            else "Estás fuera de la zona de clasificación, que son los dos primeros."
        )
        return (
            f"{self.user_team.name} va en el puesto {rank} de 4 en el grupo {self.user_team.group}, "
            f"con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}. {zone}"
        )

    def _pair_first_ko(self, winners: list[Team], runners_up: list[Team]) -> list[dict[str, Any]]:
        g_count = len(winners)
        ws, rr = list(winners), list(runners_up)
        random.shuffle(ws)
        for _ in range(300):
            random.shuffle(rr)
            if all(w.group != r.group for w, r in zip(ws, rr)):
                break
        ties = [self._make_tie(r, w) for w, r in zip(ws, rr)]
        order: list[int] = []
        for k in range(g_count // 2):
            order.extend([k, g_count - 1 - k])
        if g_count % 2:
            order.append(g_count // 2)
        return [ties[i] for i in order]

    def close_step(self) -> str:
        assert self.groups is not None
        kind, data = self.steps[self.step_idx]
        notice = ""
        if kind == "liga":
            if data == self.rounds_count - 1:
                g_count = len(self.groups)
                firsts, seconds = [], []
                for grp in self.groups:
                    ranked = self._sort_group(grp)
                    firsts.append(ranked[0])
                    seconds.append(ranked[1])
                firsts.sort(key=self._sort_key)
                seconds.sort(key=self._sort_key)
                self.ranking = {}
                for k, t in enumerate(firsts):
                    self.ranking[t.name] = k + 1
                for k, t in enumerate(seconds):
                    self.ranking[t.name] = g_count + 1 + k
                rest = sorted(
                    (t for t in self.teams if t.name not in self.ranking),
                    key=self._sort_key,
                )
                for k, t in enumerate(rest):
                    self.ranking[t.name] = 2 * g_count + 1 + k
                self.qualified = firsts + seconds
                self.ties = self._pair_first_ko(firsts, seconds)
                grp = self.group_of(self.user_team)
                pos = self._sort_group(grp).index(self.user_team) + 1
                if self.user_team in self.qualified:
                    place_txt = "primero" if pos == 1 else "segundo"
                    notice = (
                        f"Terminó la fase de grupos. {self.user_team.name} termina {place_txt} "
                        f"del grupo {self.user_team.group} y pasa a {self._first_ko_round_name()}."
                    )
                else:
                    self.user_eliminated = True
                    notice = (
                        f"Terminó la fase de grupos. {self.user_team.name} termina en el puesto "
                        f"{pos} del grupo {self.user_team.group} y queda eliminado."
                    )
        elif kind == "vuelta":
            winners, losers = self._winners(), self._losers()
            if data == 8:
                winners = [winners[0], winners[3], winners[1], winners[2]]
            notice = self._round_notice(losers)
            self.ties = self._next_round_ties(winners)
            if data == 4:
                notice = (
                    f"{notice} La final se juega en {self.final_venue[0]}, "
                    f"ciudad de {self.final_venue[1]}, en campo neutral."
                ).strip()
        elif kind == "unico":
            return self._finish_final()
        self.step_idx += 1
        self._prepare_step()
        return notice

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupCup:
        teams = [Team.from_dict(t) for t in data["teams"]]
        by_name = {t.name: t for t in teams}
        inst = cls(None, {t.team_id or t.name: t for t in teams}, by_name[data["user_team"]], _skip_init=True)
        inst._restore_common(data, by_name)
        return inst


class CopaLibertadores(GroupCup):
    KEY = "libertadores"
    TITLE = "Copa Libertadores"
    FINAL_VENUE = ("Estadio Centenario", "Montevideo")


class CopaSudamericana(GroupCup):
    KEY = "sudamericana"
    TITLE = "Copa Sudamericana"
    FINAL_VENUE = ("Estadio Defensores del Chaco", "Asunción")


class CopaInteramericana(GroupCup):
    KEY = "interamericana"
    TITLE = "Copa Interamericana"
    FINAL_VENUE = ("Hard Rock Stadium", "Miami")


class CopaPersonalizada(GroupCup):
    KEY = "copa_personalizada"
    TITLE = "Copa personalizada"
    FINAL_VENUE = ("Wembley Stadium", "Londres")


class LigaMX(ClubTournament):
    """Liga MX Apertura 2026: 18 clubs, 17 rounds, 8-team Liguilla with table-seed advantage."""

    KEY = "ligamx"
    TITLE = "Liga MX"
    LEAGUE_PHASE_LABEL = "la fase regular"
    ROUND_NAMES = {
        8: "Cuartos de final de la liguilla",
        4: "Semifinales de la liguilla",
        2: "La gran final",
    }

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        self._init_club_base(list(teams_by_id.values()), user_team)
        self.groups = [self.teams]
        self.rounds_count = len(self.teams) - 1
        self.qualify_count = 8
        if not _skip_init:
            self.schedule = self._build_mx_schedule()
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            for rnd_size in (8, 4, 2):
                self.steps.append(("ida", rnd_size))
                self.steps.append(("vuelta", rnd_size))
            self._prepare_step()

    def _build_mx_schedule(self) -> list[list[tuple[Team, Team]]]:
        best: list[list[tuple[Team, Team]]] = []
        best_score: tuple[int, int] | None = None
        for _ in range(120):
            eq = list(self.teams)
            random.shuffle(eq)
            n = len(eq)
            rot = eq[1:]
            idx_map = {t.name: i for i, t in enumerate(rot)}
            cal: list[list[tuple[Team, Team]]] = []
            for _r in range(n - 1):
                row = [eq[0]] + rot
                pairs: list[tuple[Team, Team]] = []
                for k in range(n // 2):
                    a, b = row[k], row[n - 1 - k]
                    if k == 0:
                        if idx_map[b.name] % 2 == 1:
                            a, b = b, a
                    else:
                        u, v = idx_map[a.name], idx_map[b.name]
                        if ((u + v) % 2 == 0) != (u < v):
                            a, b = b, a
                    pairs.append((a, b))
                cal.append(pairs)
                rot = [rot[-1]] + rot[:-1]
            worst, breaks = 0, 0
            for t in eq:
                seq = []
                for pairs in cal:
                    for a, b in pairs:
                        if a is t:
                            seq.append("l")
                        elif b is t:
                            seq.append("v")
                run = 1
                for x in range(1, len(seq)):
                    run = run + 1 if seq[x] == seq[x - 1] else 1
                    worst = max(worst, run)
                    if run >= 3:
                        breaks += 1
            score = (worst, breaks)
            if best_score is None or score < best_score:
                best, best_score = cal, score
        for pairs in best:
            random.shuffle(pairs)
        return best

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 8:
            return "Clasificado a la liguilla" if finished else "En zona de liguilla"
        return "Fuera de la liguilla" if finished else "Fuera de la zona"

    def position_text(self) -> str:
        rank, row = self.user_position()
        zone = (
            "Estás en zona de liguilla."
            if rank <= 8
            else "Estás fuera de la zona de liguilla. Hay que llegar al puesto 8."
        )
        return (
            f"{self.user_team.name} va en el puesto {rank} de {len(self.teams)}, "
            f"con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}. {zone}"
        )

    def _next_round_ties(self, winners: list[Team]) -> list[dict[str, Any]]:
        ranked = sorted(winners, key=lambda t: self.ranking[t.name])
        n = len(ranked)
        return [self._make_tie(ranked[n - 1 - k], ranked[k]) for k in range(n // 2)]

    def tie_winner(self, tie: dict[str, Any]) -> Team:
        if tie["forzado"] is not None:
            return tie["forzado"]
        gx, gy = self.tie_aggregate(tie)
        if gx != gy:
            return tie["x"] if gx > gy else tie["y"]
        if tie.get("fin"):
            if tie["pen"]:
                return tie["x"] if tie["pen"][0] > tie["pen"][1] else tie["y"]
            return random.choice((tie["x"], tie["y"]))
        return tie["y"]

    def tie_reason(self, tie: dict[str, Any]) -> str:
        if tie["forzado"] is not None:
            return "por abandono"
        gx, gy = self.tie_aggregate(tie)
        if gx != gy:
            return "por el global"
        if tie.get("fin"):
            return "en los penales"
        return "por estar mejor ubicado en la tabla"

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        kwargs = NationsLeague.match_kwargs(self, idx, first_team)
        if kwargs:
            kwargs["no_extra_time"] = False
            tie = self.ties[idx]
            if not tie.get("fin"):
                kwargs["table_advantage"] = 0 if first_team is tie["y"] else 1
        return kwargs

    def close_step(self) -> str:
        kind, data = self.steps[self.step_idx]
        notice = ""
        if kind == "liga":
            if data == self.rounds_count - 1:
                order = self.standings()
                self.ranking = {t.name: k + 1 for k, t in enumerate(order)}
                self.qualified = order[:8]
                self.ties = self._build_initial_ties(self.qualified)
                pos = self.ranking[self.user_team.name]
                if self.user_team in self.qualified:
                    notice = (
                        f"Terminó la fase regular. {self.user_team.name} termina en el puesto "
                        f"{pos} y pasa directo a los cuartos de final de la liguilla."
                    )
                else:
                    self.user_eliminated = True
                    notice = (
                        f"Terminó la fase regular. {self.user_team.name} termina en el puesto "
                        f"{pos} y queda fuera de la liguilla."
                    )
        elif kind == "vuelta":
            winners, losers = self._winners(), self._losers()
            if data == 2:
                return self._finish_final()
            notice = self._round_notice(losers)
            self.ties = self._next_round_ties(winners)
            if data == 4:
                for tie in self.ties:
                    tie["fin"] = True
                notice = f"{notice} Empieza la final a ida y vuelta.".strip()
        self.step_idx += 1
        self._prepare_step()
        return notice

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LigaMX:
        teams = [Team.from_dict(t) for t in data["teams"]]
        by_name = {t.name: t for t in teams}
        inst = cls(None, {t.team_id or t.name: t for t in teams}, by_name[data["user_team"]], _skip_init=True)
        inst._restore_common(data, by_name)
        return inst


class DoubleRoundRobin(LigaMX):
    """Shared league schedule with a return match for every pairing."""

    LEAGUE_PHASE_LABEL = "la temporada"
    ROUND_NAMES: dict[Any, str] = {}

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        self._init_club_base(list(teams_by_id.values()), user_team)
        self.groups = [self.teams]
        self.rounds_count = 2 * (len(self.teams) - 1)
        self.qualify_count = 0
        if not _skip_init:
            first_half = self._build_mx_schedule()
            second_half = [[(b, a) for a, b in rnd] for rnd in first_half]
            self.schedule = first_half + second_half
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            self._prepare_step()

    def phase_name(self) -> str:
        kind, data = self.steps[self.step_idx]
        if kind != "liga":
            return super().phase_name()
        return f"Jornada {data + 1} de {self.rounds_count}"

    def position_text(self) -> str:
        rank, row = self.user_position()
        zone = self.zone_label(rank, False)
        zone_txt = f" {zone}." if zone else ""
        return (
            f"{self.user_team.name} va en el puesto {rank} de {len(self.teams)}, "
            f"con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}.{zone_txt}"
        )

    def close_step(self) -> str:
        _, data = self.steps[self.step_idx]
        if data == self.rounds_count - 1:
            order = self.standings()
            self.ranking = {t.name: k + 1 for k, t in enumerate(order)}
            self.champion, self.runner_up = order[0], order[1]
            pos = self.ranking[self.user_team.name]
            return (
                f"Terminó la temporada. {self.user_team.name} termina en el puesto {pos}. "
                f"{self.champion.name} es el campeón de la {self.TITLE}."
            )
        self.step_idx += 1
        self._prepare_step()
        return ""


class PremierLeague(DoubleRoundRobin):
    """Premier League 2026-27: 20 clubs, 38 matchdays, no playoffs."""

    KEY = "premier"
    TITLE = "Premier League"

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 5:
            return "Zona de Liga de Campeones"
        if rank <= 7:
            return "Zona de Liga Europa y Conference"
        if rank > len(self.teams) - 3:
            return "Zona de descenso"
        return ""


class LigaArgentina(DoubleRoundRobin):
    """Liga Profesional Argentina: 20 clubs, double round-robin (38 matchdays), no playoffs."""

    KEY = "liga_argentina"
    TITLE = "Liga Profesional Argentina"

    def zone_label(self, rank: int, finished: bool) -> str:
        n = len(self.teams)
        if rank <= 4:
            return "Zona de Copa Libertadores"
        if rank <= 9:
            return "Zona de Copa Sudamericana"
        if rank > n - 2:
            return "Zona de descenso"
        return ""


class Liga1Peru(LigaMX):
    """Liga 1 de Perú 2026: 18 clubs, Apertura (17) + Clausura (17, local/visita invertidos),
    tabla acumulada y playoffs por el título entre ganadores de torneo y mejores del acumulado."""

    KEY = "liga1"
    TITLE = "Liga 1 de Perú"
    LEAGUE_PHASE_LABEL = "la fase regular"
    ROUND_NAMES: dict[Any, str] = {
        4: "Semifinales del playoff por el título",
        2: "Final del campeonato",
    }

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        self._init_club_base(list(teams_by_id.values()), user_team)
        self.groups = [self.teams]
        self.rounds_count = 2 * (len(self.teams) - 1)
        self.qualify_count = 4
        self.apertura_winner: str | None = None
        self.clausura_winner: str | None = None
        self.apertura_snapshot: dict[str, dict[str, int]] = {}
        self.bye_team: str | None = None
        if not _skip_init:
            first_half = self._build_mx_schedule()
            second_half = [[(b, a) for a, b in rnd] for rnd in first_half]
            self.schedule = first_half + second_half
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            self._prepare_step()

    def phase_name(self) -> str:
        kind, data = self.steps[self.step_idx]
        if kind == "liga":
            half = self.rounds_count // 2
            if data < half:
                return f"Torneo Apertura, fecha {data + 1} de {half}"
            return f"Torneo Clausura, fecha {data - half + 1} de {half}"
        name = self.ROUND_NAMES[data]
        leg = "ida" if kind == "ida" else "vuelta"
        return f"{name}, partido de {leg}"

    def zone_label(self, rank: int, finished: bool) -> str:
        n = len(self.teams)
        if rank <= 2:
            return "Zona de playoff y Copa Libertadores"
        if rank <= 6:
            return "Zona de Copa Sudamericana"
        if rank > n - 2:
            return "Zona de descenso"
        return ""

    def position_text(self) -> str:
        rank, row = self.user_position()
        zone = self.zone_label(rank, False)
        zone_txt = f" {zone}." if zone else ""
        return (
            f"{self.user_team.name} va en el puesto {rank} de {len(self.teams)} "
            f"en la tabla acumulada, con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}.{zone_txt}"
        )

    def _clausura_order(self) -> list[Team]:
        snap = self.apertura_snapshot

        def key(team: Team) -> tuple[int, int, int, int, float]:
            row, base = self.table[team.name], snap[team.name]
            pts = row["pts"] - base["pts"]
            gf = row["gf"] - base["gf"]
            gc = row["gc"] - base["gc"]
            return (-pts, -(gf - gc), -gf, row.get("fp", 0), self.tiebreaker_rnd[team.name])

        return sorted(self.teams, key=key)

    def _by_name(self, name: str) -> Team:
        return next(t for t in self.teams if t.name == name)

    def _fin_tie(self, a: Team, b: Team) -> dict[str, Any]:
        """Two-legged tie: better aggregate-table team plays the second leg at home."""
        lower, higher = (a, b) if self.ranking[a.name] > self.ranking[b.name] else (b, a)
        tie = self._make_tie(lower, higher)
        tie["fin"] = True
        return tie

    def _begin_playoffs(self, agg: list[Team]) -> str:
        """Decide the playoff bracket once the 34 matchdays are over."""
        ap = self._by_name(self.apertura_winner or agg[0].name)
        cl = self._by_name(self.clausura_winner or agg[0].name)
        user = self.user_team

        if ap.name == cl.name:
            self.champion = ap
            self.runner_up = agg[1] if agg[0].name == ap.name else agg[0]
            return (
                f"Terminó la fase regular. {ap.name} ganó el Apertura y el Clausura y es "
                f"el campeón de la {self.TITLE} sin necesidad de playoffs."
            )

        winners = [w for w in (ap, cl) if self.ranking[w.name] <= 8]
        top2 = {t.name for t in agg[:2]}
        non_winners = [t for t in agg if t.name not in (ap.name, cl.name)]
        bye = [w for w in winners if w.name in top2]
        sizes: list[int]

        if len(bye) == 2:
            self.ties = [self._fin_tie(ap, cl)]
            sizes = [2]
            text = "Los dos ganadores de torneo también lideran el acumulado y van directo a la final."
        elif len(bye) == 1:
            bye_team = bye[0]
            other = [w for w in winners if w.name != bye_team.name]
            opp_pool = non_winners[:2]
            first = opp_pool[0]
            second = other[0] if other else opp_pool[1]
            self.bye_team = bye_team.name
            self.ties = [self._fin_tie(first, second)]
            sizes = [4, 2]
            text = f"{bye_team.name} pasa directo a la final. Hay una semifinal."
        else:
            qual = list(winners)
            for t in non_winners:
                if len(qual) >= 4:
                    break
                qual.append(t)
            qual.sort(key=lambda t: self.ranking[t.name])
            self.ties = [self._fin_tie(qual[3], qual[0]), self._fin_tie(qual[2], qual[1])]
            sizes = [4, 2]
            text = "Hay dos semifinales a ida y vuelta."

        for size in sizes:
            self.steps.append(("ida", size))
            self.steps.append(("vuelta", size))

        in_playoff = {t.name for tie in self.ties for t in (tie["x"], tie["y"])}
        if self.bye_team:
            in_playoff.add(self.bye_team)
        if user.name not in in_playoff:
            self.user_eliminated = True
            tail = f"{user.name} queda fuera de los playoffs por el título."
        else:
            tail = f"{user.name} está en los playoffs por el título."
        return (
            f"Terminó la fase regular. {ap.name} ganó el Apertura y {cl.name} el Clausura. "
            f"{text} {tail}"
        )

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        kwargs = NationsLeague.match_kwargs(self, idx, first_team)
        if kwargs:
            kwargs["no_extra_time"] = False
        return kwargs

    def _next_round_ties(self, winners: list[Team]) -> list[dict[str, Any]]:
        contenders = list(winners)
        if self.bye_team:
            contenders.append(self._by_name(self.bye_team))
        a, b = contenders[0], contenders[1]
        return [self._fin_tie(a, b)]

    def close_step(self) -> str:
        kind, data = self.steps[self.step_idx]
        notice = ""
        half = self.rounds_count // 2
        if kind == "liga":
            if data == half - 1:
                order = self.standings()
                self.apertura_winner = order[0].name
                self.apertura_snapshot = {k: dict(v) for k, v in self.table.items()}
                pos = order.index(self.user_team) + 1
                notice = (
                    f"Terminó el Torneo Apertura. {order[0].name} es el campeón del Apertura. "
                    f"{self.user_team.name} lo termina en el puesto {pos}. "
                    "Empieza el Clausura con los mismos rivales y las localías invertidas."
                )
            elif data == self.rounds_count - 1:
                agg = self.standings()
                self.ranking = {t.name: k + 1 for k, t in enumerate(agg)}
                self.clausura_winner = self._clausura_order()[0].name
                notice = self._begin_playoffs(agg)
                if self.champion is not None:
                    return notice
        elif kind == "vuelta":
            winners, losers = self._winners(), self._losers()
            if data == 2:
                return self._finish_final()
            notice = self._round_notice(losers)
            self.ties = self._next_round_ties(winners)
            notice = f"{notice} Empieza la final a ida y vuelta.".strip()
        self.step_idx += 1
        self._prepare_step()
        return notice

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update(
            {
                "apertura_winner": self.apertura_winner,
                "clausura_winner": self.clausura_winner,
                "apertura_snapshot": self.apertura_snapshot,
                "bye_team": self.bye_team,
            }
        )
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Liga1Peru:
        inst = super().from_dict(data)
        inst.apertura_winner = data.get("apertura_winner")
        inst.clausura_winner = data.get("clausura_winner")
        inst.apertura_snapshot = data.get("apertura_snapshot", {})
        inst.bye_team = data.get("bye_team")
        return inst
