"""Run community definitions through the existing match and competition primitives."""

from __future__ import annotations

import random

from audiofutbol.domain.competitions.brasileirao import BrasileiraoB
from audiofutbol.domain.competitions.club_tournaments import (
    ChampionsLeague, ClubTournament, Liga1Peru, LigaMX,
)
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.scheduling import build_circle_schedule
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.creations import TournamentDraft, team_key
from audiofutbol.domain.models import Team


def _round_robin(teams: list[Team]) -> list[list[tuple[Team, Team]]]:
    if len(teams) % 2 == 0:
        return build_circle_schedule(teams, len(teams) - 1)
    bye = Team("", [])
    fixtures = build_circle_schedule([*teams, bye], len(teams))
    return [[(a, b) for a, b in day if a is not bye and b is not bye] for day in fixtures]


class CreatedTournament(ClubTournament):
    """Composable calendar, qualification and knockout stages for local previews."""

    LEAGUE_PHASE_LABEL = "la fase de clasificación"
    ROUND_NAMES = {
        64: "Ronda de 64", 32: "Dieciseisavos de final", 16: "Octavos de final",
        8: "Cuartos de final", 4: "Semifinales", 2: "Final",
    }

    def __init__(self, draft: TournamentDraft, teams: list[Team], user: Team) -> None:
        self._init_club_base(teams, user)
        self.TITLE = draft.name
        self.draft = draft
        self.away_goals_rule = draft.away_goals
        self.final_venue = (draft.stadium, draft.city)
        if draft.format == "grupos":
            pool = random.sample(self.teams, len(self.teams))
            self.groups = [pool[i:i+4] for i in range(0, len(pool), 4)]
            for i, group in enumerate(self.groups):
                for team in group:
                    team.group = chr(ord("A") + i)
        else:
            self.groups = [self.teams]
        self.rounds_count = 0
        self.qualify_count = (
            len(self.teams) // 2 if draft.format == "grupos"
            else draft.advance if draft.format == "liguilla"
            else len(self.teams) if draft.format == "eliminacion" else 0
        )

        if draft.format != "eliminacion":
            first = [_round_robin(group) for group in self.groups]
            self.schedule = [[pair for fixtures in row for pair in fixtures] for row in zip(*first)]
            if draft.rounds == 2:
                self.schedule += [[(away, home) for home, away in day] for day in self.schedule]
            self.rounds_count = len(self.schedule)
            self.steps = [("liga", i) for i in range(self.rounds_count)]
        else:
            seeded = random.sample(self.teams, len(self.teams))
            self.ranking = {t.name: i for i, t in enumerate(seeded, start=1)}
            self.ties = self._build_initial_ties(seeded)

        stage = self.qualify_count
        while stage >= 2:
            legs = draft.final_legs if stage == 2 else draft.knockout_legs
            self.steps.extend([("ida", stage), ("vuelta", stage)] if legs == 2 else [("unico", stage)])
            stage //= 2
        self._prepare_step()

    def zone_label(self, rank: int, finished: bool) -> str:
        places = 2 if self.draft.format == "grupos" else self.draft.advance
        if places and rank <= places:
            return "Clasificado" if finished else "En zona de clasificación"
        return ""

    def position_text(self) -> str:
        rank, row = self.user_position()
        label = self.zone_label(rank, False)
        group = f" del grupo {self.user_team.group}" if self.user_team.group else ""
        return f"{self.user_team.name}, puesto {rank}{group}, {row['pts']} puntos. {label}"

    def is_neutral(self) -> bool:
        return self.steps[self.step_idx] == ("unico", 2) and bool(self.final_venue[0])

    def venue(self, idx, venue_lookup):
        if self.is_neutral():
            return self.final_venue
        return venue_lookup(self.pairs[idx][0])

    def venue_text(self, idx, venue_lookup):
        pair = self.venue(idx, venue_lookup)
        if not pair:
            return None
        return f"{pair[0]}, ciudad de {pair[1]}" + (", en campo neutral" if self.is_neutral() else "")

    def close_step(self) -> str:
        kind, size = self.steps[self.step_idx]
        notice = ""
        if kind == "liga" and self.step_idx + 1 == self.rounds_count:
            ordered = self.standings()
            if not self.qualify_count:
                self.champion, self.runner_up = ordered[:2]
                return f"{self.champion.name} es campeón de {self.TITLE}."
            if self.draft.format == "grupos":
                assert self.groups is not None
                ranked = [self._sort_group(group) for group in self.groups]
                first, second = [group[0] for group in ranked], [group[1] for group in ranked]
                self.ties = [self._make_tie(second[idx ^ 1], team) for idx, team in enumerate(first)]
                self.qualified = first + second
            else:
                self.qualified = ordered[:self.qualify_count]
                self.ties = self._build_initial_ties(self.qualified)
            self.ranking = {team.name: i for i, team in enumerate(self.qualified, start=1)}
            self.user_eliminated = self.user_team not in self.qualified
            notice = (
                f"{self.user_team.name} queda fuera de las eliminatorias." if self.user_eliminated
                else f"{self.user_team.name} pasa a las eliminatorias."
            )
        elif kind in ("unico", "vuelta"):
            winners = [self.tie_winner(tie) for tie in self.ties]
            losers = [tie["y"] if winner is tie["x"] else tie["x"] for winner, tie in zip(winners, self.ties)]
            if size == 2:
                self.champion, self.runner_up = winners[0], losers[0]
                return f"{self.champion.name} es campeón de {self.TITLE}."
            notice = self._round_notice(losers)
            self.ties = self._next_round_ties(winners)
        self.step_idx += 1
        self._prepare_step()
        return notice


def build_created_tournament(
    draft: TournamentDraft, teams: list[Team], user_index: int, *, uefa_schedule: dict | None = None,
) -> NationsLeague | WorldCup:
    if errors := draft.issues():
        raise ValueError(errors[0])
    if len(teams) != draft.team_count or not 0 <= user_index < len(teams):
        raise ValueError("No se pudieron cargar todos los participantes.")
    if len({team_key(team.name) for team in teams}) != len(teams):
        raise ValueError("Dos participantes tienen el mismo nombre. Edita la selección de equipos.")
    copies = [Team.from_dict(team.to_dict()) for team in teams]
    ids = {f"cupo_{i}": team for i, team in enumerate(copies, start=1)}
    for key, team in ids.items():
        team.team_id, team.group = key, None
    user = copies[user_index]

    if draft.format == "mundial":
        instance = WorldCup(copies, user)
    elif draft.format == "naciones":
        instance = NationsLeague(copies, user, away_goals_rule=draft.away_goals)
    elif draft.format == "fase_uefa":
        if not uefa_schedule:
            raise ValueError("Falta el calendario base de la Liga de Campeones.")
        # Use the shipped fixture pattern, replacing slot identities, not editing the file.
        base_ids = [entry["id"] for entry in uefa_schedule["equipos"]]
        if len(base_ids) != len(copies) or len(set(base_ids)) != len(base_ids):
            raise ValueError("El calendario base no coincide con la cantidad de participantes.")
        instance = ChampionsLeague(uefa_schedule, dict(zip(base_ids, copies)), user)
    elif draft.format in ("liguilla_mx", "apertura", "ascenso"):
        cls = {"liguilla_mx": LigaMX, "apertura": Liga1Peru, "ascenso": BrasileiraoB}[draft.format]
        instance = cls(None, ids, user)
    else:
        return CreatedTournament(draft, copies, user)
    instance.TITLE = draft.name
    if draft.stadium and isinstance(instance, NationsLeague):
        instance.final_venue = (draft.stadium, draft.city)
    return instance
