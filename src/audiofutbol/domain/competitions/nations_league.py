"""Nations League competition model (and shared base for club tournaments)."""

from __future__ import annotations

import random
from typing import Any, Callable

from audiofutbol.domain.competitions.scheduling import (
    build_circle_schedule,
    build_realistic_home_away_schedule,
)
from audiofutbol.domain.competitions.world_cup import fair_play_for_order
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.match.ports import HeadlessMatchIO, MatchSettings
from audiofutbol.domain.models import MatchResult, Team, format_result_text


VenueLookup = Callable[[Team], tuple[str, str] | None]


class NationsLeague:
    """League phase (half-season round-robin) followed by two-legged knockout & neutral final."""

    KEY = "liga"
    TITLE = "Liga de Naciones"
    UNIT_LABEL = "selección"
    LEAGUE_PHASE_LABEL = "la fase de liga"
    FINAL_VENUE: tuple[str, str] = ("MetLife Stadium", "East Rutherford")
    ROUND_NAMES: dict[Any, str] = {
        32: "Dieciseisavos de final",
        16: "Octavos de final",
        8: "Cuartos de final",
        4: "Semifinales",
        2: "La gran final",
    }

    def __init__(
        self,
        teams: list[Team],
        user_team: Team,
        away_goals_rule: bool = True,
        _skip_init: bool = False,
    ) -> None:
        self.teams: list[Team] = list(teams)
        self.user_team: Team = user_team
        self.away_goals_rule: bool = away_goals_rule
        n = len(self.teams)
        self.rounds_count: int = max(1, n // 2)
        p = 2
        while p * 2 <= n * 2 / 3.0:
            p *= 2
        self.qualify_count: int = p
        self.user_eliminated: bool = False
        self.tiebreaker_rnd: dict[str, float] = {
            t.name: random.random() for t in self.teams
        }
        self.table: dict[str, dict[str, int]] = {
            t.name: {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "fp": 0}
            for t in self.teams
        }
        self.history: list[tuple[str, Team, Team, int, int, tuple[int, int] | None]] = []
        self.aggregates: dict[int, tuple[Team, int, Team, int]] = {}
        self.schedule: list[list[tuple[Team, Team]]] = []
        self.steps: list[tuple[str, Any]] = []
        self.step_idx: int = 0
        self.ties: list[dict[str, Any]] = []
        self.ranking: dict[str, int] = {}
        self.qualified: list[Team] = []
        self.pairs: list[tuple[Team, Team]] = []
        self.completed: dict[int, dict[str, Any]] = {}
        self.champion: Team | None = None
        self.runner_up: Team | None = None
        self.final_venue: tuple[str, str] = self.FINAL_VENUE
        self.groups: list[list[Team]] | None = None

        if not _skip_init:
            self.schedule = self._generate_schedule()
            knockout_sizes: list[int] = []
            t = self.qualify_count
            while t >= 2:
                knockout_sizes.append(t)
                t //= 2
            self.steps = [("liga", k) for k in range(self.rounds_count)]
            for size in knockout_sizes:
                if size == 2:
                    self.steps.append(("unico", 2))
                else:
                    self.steps.append(("ida", size))
                    self.steps.append(("vuelta", size))
            self._prepare_step()

    def _generate_schedule(self) -> list[list[tuple[Team, Team]]]:
        try:
            cal = build_realistic_home_away_schedule(self.teams, self.rounds_count)
        except Exception:
            cal = None
        if cal:
            return cal
        return build_circle_schedule(self.teams, self.rounds_count)

    # ------------------------------------------------------- Steps & Phases
    def step_type(self) -> str:
        return self.steps[self.step_idx][0]

    def final_summary_lines(self) -> list[str]:
        """Return any competition-specific outcomes beyond champion and runner-up."""
        return []

    def phase_name(self) -> str:
        kind, data = self.steps[self.step_idx]
        if kind == "liga":
            return f"Liga, jornada {data + 1} de {self.rounds_count}"
        if kind == "unico":
            return self.ROUND_NAMES[data]
        leg = "ida" if kind == "ida" else "vuelta"
        return f"{self.ROUND_NAMES[data]}, partido de {leg}"

    def is_knockout(self) -> bool:
        return self.step_type() in ("vuelta", "unico")

    def _prepare_step(self) -> None:
        kind, data = self.steps[self.step_idx]
        self.completed = {}
        if kind == "liga":
            self.pairs = list(self.schedule[data])
        elif kind in ("ida", "unico"):
            self.pairs = [(c["x"], c["y"]) for c in self.ties]
        else:
            self.pairs = [(c["y"], c["x"]) for c in self.ties]

    # ------------------------------------------------------- Standings & Tables
    def _sort_key(self, team: Team) -> tuple[int, int, int, int, float]:
        row = self.table[team.name]
        return (
            -row["pts"],
            -(row["gf"] - row["gc"]),
            -row["gf"],
            row.get("fp", 0),
            self.tiebreaker_rnd[team.name],
        )

    def standings(self) -> list[Team]:
        return sorted(self.teams, key=self._sort_key)

    def user_position(self) -> tuple[int, dict[str, int]]:
        order = self.standings()
        return order.index(self.user_team) + 1, self.table[self.user_team.name]

    def position_text(self) -> str:
        pos, row = self.user_position()
        zone = (
            "Estás en zona de clasificación."
            if pos <= self.qualify_count
            else f"Estás fuera de la zona de clasificación, que son los {self.qualify_count} primeros."
        )
        return (
            f"{self.user_team.name} va en el puesto {pos} de {len(self.teams)}, "
            f"con {row['pts']} puntos en {row['pj']} partidos, "
            f"diferencia de goles {row['gf'] - row['gc']:+d}. {zone}"
        )

    def table_lines(self) -> list[str]:
        out: list[str] = []
        finished = self.step_type() != "liga"
        for idx, team in enumerate(self.standings()):
            row = self.table[team.name]
            if idx < self.qualify_count:
                status = "Clasificado" if finished else "En zona de clasificación"
            else:
                status = "Eliminado" if finished else "Fuera de la zona"
            mine = ". Es tu selección" if team is self.user_team else ""
            out.append(
                f"{idx + 1}. {team.name}, {row['pts']} puntos, {row['pj']} jugados, "
                f"{row['g']} ganados, {row['e']} empatados, {row['p']} perdidos, "
                f"goles {row['gf']} a {row['gc']}, diferencia {row['gf'] - row['gc']:+d}, "
                f"fair play {row.get('fp', 0)}. De local {row.get('lpts', 0)} puntos, "
                f"de visitante {row.get('vpts', 0)} puntos. {status}{mine}"
            )
        return out

    def _add_league_stats(
        self, a: Team, b: Team, ga: int, gb: int, fpa: int, fpb: int
    ) -> None:
        for team, gf, gc, fp, side in ((a, ga, gb, fpa, "l"), (b, gb, ga, fpb, "v")):
            row = self.table[team.name]
            row["fp"] = row.get("fp", 0) + fp
            row["pj"] += 1
            row["gf"] += gf
            row["gc"] += gc
            row[side + "j"] = row.get(side + "j", 0) + 1
            row[side + "gf"] = row.get(side + "gf", 0) + gf
            row[side + "gc"] = row.get(side + "gc", 0) + gc
            if gf > gc:
                row["g"] += 1
                row["pts"] += 3
                row[side + "g"] = row.get(side + "g", 0) + 1
                row[side + "pts"] = row.get(side + "pts", 0) + 3
            elif gf == gc:
                row["e"] += 1
                row["pts"] += 1
                row[side + "e"] = row.get(side + "e", 0) + 1
                row[side + "pts"] = row.get(side + "pts", 0) + 1
            else:
                row["p"] += 1
                row[side + "p"] = row.get(side + "p", 0) + 1

    @staticmethod
    def _side_stats(row: dict[str, int], side: str) -> tuple[int, int, int, int, int, int, int]:
        return (
            row.get(side + "j", 0),
            row.get(side + "g", 0),
            row.get(side + "e", 0),
            row.get(side + "p", 0),
            row.get(side + "gf", 0),
            row.get(side + "gc", 0),
            row.get(side + "pts", 0),
        )

    def home_away_summary(self) -> str:
        row = self.table[self.user_team.name]
        lj, _, _, _, _, _, lp = self._side_stats(row, "l")
        vj, _, _, _, _, _, vp = self._side_stats(row, "v")
        return (
            f" De local: {lp} puntos en {lj} partidos. "
            f"De visitante: {vp} puntos en {vj} partidos."
        )

    def _table_groups(self) -> list[list[Team]]:
        return self.groups or [self.teams]

    def side_table_lines(self, side: str) -> list[str]:
        label = "local" if side == "l" else "visitante"
        groups = self._table_groups()

        def key(team: Team) -> tuple[int, int, int, float]:
            _, _, _, _, gf, gc, pts = self._side_stats(self.table[team.name], side)
            return (-pts, -(gf - gc), -gf, self.tiebreaker_rnd[team.name])

        out: list[str] = []
        for grp in groups:
            if len(groups) > 1 and grp[0].group:
                out.append(f"Grupo {grp[0].group}.")
            for idx, team in enumerate(sorted(grp, key=key)):
                j, w, d, l, gf, gc, pts = self._side_stats(self.table[team.name], side)
                mine = f". Es tu {self.UNIT_LABEL}" if team is self.user_team else ""
                out.append(
                    f"{idx + 1}. {team.name}, {pts} puntos de {label}, {j} jugados, "
                    f"{w} ganados, {d} empatados, {l} perdidos, goles {gf} a {gc}, "
                    f"diferencia {gf - gc:+d}{mine}"
                )
        return out

    def venue_streak(self) -> tuple[str, int] | None:
        kind, data = self.steps[self.step_idx]
        if kind != "liga":
            return None
        seq: list[str] = []
        for r in range(data + 1):
            for a, b in self.schedule[r]:
                if a is self.user_team:
                    seq.append("l")
                    break
                if b is self.user_team:
                    seq.append("v")
                    break
        if not seq:
            return None
        count = 1
        while count < len(seq) and seq[-1 - count] == seq[-1]:
            count += 1
        return seq[-1], count

    def streak_text(self) -> str:
        st = self.venue_streak()
        if not st or st[1] < 2:
            return ""
        ordinal = {2: "segundo", 3: "tercer", 4: "cuarto"}.get(
            st[1], f"partido número {st[1]}"
        )
        side = "local" if st[0] == "l" else "visitante"
        return f". Es tu {ordinal} partido seguido de {side}"

    def _round_label(self, round_idx: int) -> str:
        prev = self.step_idx
        try:
            self.step_idx = round_idx
            return self.phase_name()
        finally:
            self.step_idx = prev

    def calendar_lines(self, venue_lookup: VenueLookup) -> list[str]:
        out: list[str] = []
        for r, matches in enumerate(self.schedule):
            label = (
                self._round_label(r)
                if r < len(self.steps) and self.steps[r][0] == "liga"
                else f"Jornada {r + 1}"
            )
            pair = next((p for p in matches if self.user_team in p), None)
            if pair is None:
                out.append(f"Jornada {r + 1}. Descansas.")
                continue
            a, b = pair
            is_home = a is self.user_team
            rival = b if is_home else a
            venue = venue_lookup(a)
            place = f", en {venue[0]}, ciudad de {venue[1]}" if venue else ""
            score: tuple[int, int] | None = None
            for ph, x, y, gx, gy, _ in self.history:
                if ph == label and x is a and y is b:
                    score = (gx, gy)
            side = "local" if is_home else "visitante"
            text = f"Jornada {r + 1}. De {side} contra {rival.name}{place}."
            if score is not None:
                text += f" Resultado: {a.name} {score[0]}, {b.name} {score[1]}."
            else:
                text += " Pendiente."
            out.append(text)
        return out

    # ------------------------------------------------------- Knockout Ties
    @staticmethod
    def _seeding_order(n: int) -> list[int]:
        order = [1]
        while len(order) < n:
            m = len(order) * 2
            expanded: list[int] = []
            for seed in order:
                expanded.extend([seed, m + 1 - seed])
            order = expanded
        return order

    @staticmethod
    def _make_tie(lower_seed: Team, higher_seed: Team) -> dict[str, Any]:
        return {
            "x": lower_seed,
            "y": higher_seed,
            "r1": None,
            "r2": None,
            "pen": None,
            "forzado": None,
        }

    def _build_initial_ties(self, qualified: list[Team]) -> list[dict[str, Any]]:
        order = self._seeding_order(len(qualified))
        return [
            self._make_tie(qualified[order[k + 1] - 1], qualified[order[k] - 1])
            for k in range(0, len(order), 2)
        ]

    def _next_round_ties(self, winners: list[Team]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for k in range(0, len(winners), 2):
            a, b = winners[k], winners[k + 1]
            if self.ranking[a.name] < self.ranking[b.name]:
                out.append(self._make_tie(b, a))
            else:
                out.append(self._make_tie(a, b))
        return out

    def _record_aggregate(self, tie: dict[str, Any]) -> None:
        gx, gy = self.tie_aggregate(tie)
        self.aggregates[len(self.history) - 1] = (tie["y"], gy, tie["x"], gx)

    def tie_aggregate(self, tie: dict[str, Any]) -> tuple[int, int]:
        if tie["r2"] is None:
            return tie["r1"]
        return tie["r1"][0] + tie["r2"][0], tie["r1"][1] + tie["r2"][1]

    def tie_winner(self, tie: dict[str, Any]) -> Team:
        if tie["forzado"] is not None:
            return tie["forzado"]
        gx, gy = self.tie_aggregate(tie)
        if gx != gy:
            return tie["x"] if gx > gy else tie["y"]
        if self.away_goals_rule and tie["r2"] is not None:
            vx, vy = tie["r2"][0], tie["r1"][1]
            if vx != vy:
                return tie["x"] if vx > vy else tie["y"]
        if tie["pen"]:
            return tie["x"] if tie["pen"][0] > tie["pen"][1] else tie["y"]
        return random.choice((tie["x"], tie["y"]))

    def tie_loser(self, tie: dict[str, Any]) -> Team:
        winner = self.tie_winner(tie)
        return tie["y"] if winner is tie["x"] else tie["x"]

    def tie_reason(self, tie: dict[str, Any]) -> str:
        gx, gy = self.tie_aggregate(tie)
        if tie["forzado"] is not None:
            return "por abandono"
        if gx != gy:
            return "por el resultado" if tie["r2"] is None else "por el global"
        if self.away_goals_rule and tie["r2"] is not None and tie["r2"][0] != tie["r1"][1]:
            return "por el gol de visitante"
        return "en los penales"

    # ------------------------------------------------------- Match Execution
    def user_match_index(self) -> int | None:
        if self.user_eliminated:
            return None
        for idx, (a, b) in enumerate(self.pairs):
            if self.user_team in (a, b) and idx not in self.completed:
                return idx
        return None

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        if self.step_type() != "vuelta":
            return {}
        a, _ = self.pairs[idx]
        tie = self.ties[idx]
        r1 = tie["r1"]
        first_leg = (r1[1], r1[0]) if first_team is tie["y"] else (r1[0], r1[1])
        return {
            "first_leg": first_leg,
            "home_index": 0 if a is first_team else 1,
            "away_goals_rule": self.away_goals_rule,
        }

    def register_result(
        self, idx: int, first_team: Team, res: MatchResult
    ) -> tuple[int, int, tuple[int, int] | None]:
        kind, _ = self.steps[self.step_idx]
        a, b = self.pairs[idx]
        g0, g1 = res.goals
        ga, gb = (g0, g1) if first_team is a else (g1, g0)
        fpa, fpb = fair_play_for_order(res, first_team is a)
        pen = res.penalties
        if pen and first_team is not a:
            pen = (pen[1], pen[0])
        self.completed[idx] = {"ga": ga, "gb": gb, "pen": pen}
        self.history.append((self.phase_name(), a, b, ga, gb, pen))
        if kind == "liga":
            self._add_league_stats(a, b, ga, gb, fpa, fpb)
        elif kind in ("ida", "unico"):
            tie = self.ties[idx]
            tie["r1"] = (ga, gb)
            if kind == "unico":
                if pen:
                    tie["pen"] = pen
                if res.abandoned:
                    tie["forzado"] = b if first_team is a else a
        else:
            tie = self.ties[idx]
            tie["r2"] = (gb, ga)
            self._record_aggregate(tie)
            if pen:
                tie["pen"] = (pen[1], pen[0])
            if res.abandoned:
                tie["forzado"] = b if first_team is a else a
        return ga, gb, pen

    def simulate_remaining(self, settings: MatchSettings | None = None) -> None:
        for idx, (a, b) in enumerate(self.pairs):
            if idx in self.completed:
                continue
            extra = self.match_kwargs(idx, a)
            engine = MatchEngine(
                a,
                b,
                io=HeadlessMatchIO(),
                settings=settings or MatchSettings(),
                knockout=self.is_knockout(),
                auto=True,
                **extra,
            )
            self.register_result(idx, a, engine.play())

    def close_step(self) -> str:
        kind, data = self.steps[self.step_idx]
        notice = ""
        if kind == "liga":
            if data == self.rounds_count - 1:
                order = self.standings()
                self.ranking = {t.name: k + 1 for k, t in enumerate(order)}
                self.qualified = order[: self.qualify_count]
                self.ties = self._build_initial_ties(self.qualified)
                pos = self.ranking[self.user_team.name]
                if self.user_team in self.qualified:
                    notice = (
                        f"Terminó la fase de liga. {self.user_team.name} termina en el puesto "
                        f"{pos} y pasa a {self.ROUND_NAMES[self.qualify_count].lower()}."
                    )
                else:
                    self.user_eliminated = True
                    notice = (
                        f"Terminó la fase de liga. {self.user_team.name} termina en el puesto "
                        f"{pos} y queda eliminada."
                    )
        elif kind == "unico":
            tie = self.ties[0]
            self.champion, self.runner_up = self.tie_winner(tie), self.tie_loser(tie)
            return f"{self.champion.name} es el campeón de la {self.TITLE}."
        elif kind == "vuelta":
            winners = [self.tie_winner(c) for c in self.ties]
            losers = [self.tie_loser(c) for c in self.ties]
            if data == 2:
                self.champion, self.runner_up = winners[0], losers[0]
                return f"{self.champion.name} es el campeón de la {self.TITLE}."
            if self.user_team in losers:
                self.user_eliminated = True
                notice = f"{self.user_team.name} queda eliminada."
            elif not self.user_eliminated:
                notice = f"{self.user_team.name} pasa a la siguiente ronda."
            self.ties = self._next_round_ties(winners)
            if data == 4:
                notice = (
                    f"{notice} La final se juega en {self.final_venue[0]}, "
                    f"ciudad de {self.final_venue[1]}, en campo neutral."
                ).strip()
        self.step_idx += 1
        self._prepare_step()
        return notice

    # ------------------------------------------------------- Venues & Queries
    def venue(self, idx: int, venue_lookup: VenueLookup) -> tuple[str, str] | None:
        if self.step_type() == "unico":
            return self.final_venue
        return venue_lookup(self.pairs[idx][0])

    def venue_text(self, idx: int, venue_lookup: VenueLookup) -> str | None:
        v = self.venue(idx, venue_lookup)
        if not v:
            return None
        text = f"{v[0]}, ciudad de {v[1]}"
        if self.step_type() == "unico":
            text += ", en campo neutral"
        return text

    def ties_lines(self) -> list[str]:
        out: list[str] = []
        is_single = self.step_type() == "unico"
        for tie in self.ties:
            x, y = tie["x"], tie["y"]
            t = f"{x.name} contra {y.name}."
            if is_single:
                if tie["r1"]:
                    t += f" Resultado: {x.name} {tie['r1'][0]}, {y.name} {tie['r1'][1]}."
                    if tie["pen"]:
                        t += f" Penales: {tie['pen'][0]} a {tie['pen'][1]}."
                    t += f" Gana {self.tie_winner(tie).name}."
                else:
                    t += " Partido pendiente, en campo neutral."
            else:
                if tie["r1"]:
                    t += f" Ida: {x.name} {tie['r1'][0]}, {y.name} {tie['r1'][1]}."
                else:
                    t += " Ida pendiente."
                if tie["r2"]:
                    t += f" Vuelta: {y.name} {tie['r2'][1]}, {x.name} {tie['r2'][0]}."
                    gx, gy = self.tie_aggregate(tie)
                    t += (
                        f" Global: {x.name} {gx}, {y.name} {gy}. "
                        f"Pasa {self.tie_winner(tie).name} {self.tie_reason(tie)}."
                    )
                else:
                    t += " Vuelta pendiente."
            if self.user_team in (x, y):
                t += " Es tu cruce."
            out.append(t)
        return out

    def results_lines(self, phase: str | None = None) -> list[str]:
        target = phase or self.phase_name()
        out: list[str] = []
        for idx, (ph, a, b, ga, gb, pen) in enumerate(self.history):
            if ph == target:
                line = format_result_text(a, b, ga, gb, pen)
                if idx in self.aggregates:
                    ea, gea, eb, geb = self.aggregates[idx]
                    line += f". Global de la llave: {ea.name} {gea}, {eb.name} {geb}"
                out.append(line)
        return out

    def top_assists(self, limit: int = 15) -> list[str]:
        entries = [
            (p.assists, p.name, t.name)
            for t in self.teams
            for p in t.players
            if p.assists > 0
        ]
        entries.sort(key=lambda item: (-item[0], item[1]))
        return [
            f"{idx + 1}. {name}, de {team}, {n} pase{'' if n == 1 else 's'} de gol"
            for idx, (n, name, team) in enumerate(entries[:limit])
        ]

    def top_scorers(self, limit: int = 15) -> list[str]:
        entries = [
            (p.goals, p.name, t.name)
            for t in self.teams
            for p in t.players
            if p.goals > 0
        ]
        entries.sort(key=lambda item: (-item[0], item[1]))
        return [
            f"{idx + 1}. {name}, de {team}, {goals} gol{'' if goals == 1 else 'es'}"
            for idx, (goals, name, team) in enumerate(entries[:limit])
        ]

    # ------------------------------------------------------- Safe JSON serialization
    def _serialize_tie(self, tie: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "x": tie["x"].name,
            "y": tie["y"].name,
            "r1": list(tie["r1"]) if tie["r1"] is not None else None,
            "r2": list(tie["r2"]) if tie["r2"] is not None else None,
            "pen": list(tie["pen"]) if tie["pen"] is not None else None,
            "forzado": tie["forzado"].name if tie["forzado"] is not None else None,
        }
        if "pot" in tie:
            out["pot"] = tie["pot"]
        if "fin" in tie:
            out["fin"] = tie["fin"]
        return out

    @staticmethod
    def _deserialize_tie(raw: dict[str, Any], by_name: dict[str, Team]) -> dict[str, Any]:
        tie: dict[str, Any] = {
            "x": by_name[raw["x"]],
            "y": by_name[raw["y"]],
            "r1": tuple(raw["r1"]) if raw["r1"] is not None else None,
            "r2": tuple(raw["r2"]) if raw["r2"] is not None else None,
            "pen": tuple(raw["pen"]) if raw["pen"] is not None else None,
            "forzado": by_name[raw["forzado"]] if raw["forzado"] is not None else None,
        }
        if "pot" in raw:
            tie["pot"] = raw["pot"]
        if "fin" in raw:
            tie["fin"] = bool(raw["fin"])
        return tie

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.KEY,
            "teams": [t.to_dict() for t in self.teams],
            "user_team": self.user_team.name,
            "away_goals_rule": self.away_goals_rule,
            "rounds_count": self.rounds_count,
            "qualify_count": self.qualify_count,
            "user_eliminated": self.user_eliminated,
            "tiebreaker_rnd": self.tiebreaker_rnd,
            "table": self.table,
            "history": [
                [ph, a.name, b.name, ga, gb, list(pen) if pen else None]
                for ph, a, b, ga, gb, pen in self.history
            ],
            "aggregates": {
                str(k): [ea.name, gea, eb.name, geb]
                for k, (ea, gea, eb, geb) in self.aggregates.items()
            },
            "schedule": [
                [[a.name, b.name] for a, b in rnd] for rnd in self.schedule
            ],
            "steps": [list(s) for s in self.steps],
            "step_idx": self.step_idx,
            "ties": [self._serialize_tie(c) for c in self.ties],
            "ranking": self.ranking,
            "qualified": [t.name for t in self.qualified],
            "pairs": [[a.name, b.name] for a, b in self.pairs],
            "completed": {
                str(k): {
                    "ga": v["ga"],
                    "gb": v["gb"],
                    "pen": list(v["pen"]) if v["pen"] else None,
                }
                for k, v in self.completed.items()
            },
            "champion": self.champion.name if self.champion else None,
            "runner_up": self.runner_up.name if self.runner_up else None,
            "final_venue": list(self.final_venue),
            "groups": [[t.name for t in g] for g in self.groups]
            if self.groups is not None
            else None,
        }

    def _restore_common(self, data: dict[str, Any], by_name: dict[str, Team]) -> None:
        self.away_goals_rule = bool(data["away_goals_rule"])
        self.rounds_count = int(data["rounds_count"])
        self.qualify_count = int(data["qualify_count"])
        self.user_eliminated = bool(data["user_eliminated"])
        self.tiebreaker_rnd = {k: float(v) for k, v in data["tiebreaker_rnd"].items()}
        self.table = data["table"]
        self.history = [
            (ph, by_name[a], by_name[b], int(ga), int(gb), tuple(pen) if pen else None)
            for ph, a, b, ga, gb, pen in data["history"]
        ]
        self.aggregates = {
            int(k): (by_name[v[0]], int(v[1]), by_name[v[2]], int(v[3]))
            for k, v in data.get("aggregates", {}).items()
        }
        self.schedule = [
            [(by_name[a], by_name[b]) for a, b in rnd] for rnd in data["schedule"]
        ]
        self.steps = [(str(s[0]), s[1]) for s in data["steps"]]
        self.step_idx = int(data["step_idx"])
        self.ties = [self._deserialize_tie(c, by_name) for c in data["ties"]]
        self.ranking = {k: int(v) for k, v in data["ranking"].items()}
        self.qualified = [by_name[n] for n in data["qualified"]]
        self.pairs = [(by_name[a], by_name[b]) for a, b in data["pairs"]]
        self.completed = {
            int(k): {
                "ga": int(v["ga"]),
                "gb": int(v["gb"]),
                "pen": tuple(v["pen"]) if v["pen"] else None,
            }
            for k, v in data["completed"].items()
        }
        self.champion = by_name[data["champion"]] if data.get("champion") else None
        self.runner_up = by_name[data["runner_up"]] if data.get("runner_up") else None
        if data.get("final_venue"):
            self.final_venue = (str(data["final_venue"][0]), str(data["final_venue"][1]))
        if data.get("groups") is not None:
            self.groups = [[by_name[n] for n in g] for g in data["groups"]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NationsLeague:
        teams = [Team.from_dict(t) for t in data["teams"]]
        by_name = {t.name: t for t in teams}
        inst = cls(teams, by_name[data["user_team"]], _skip_init=True)
        inst._restore_common(data, by_name)
        return inst
