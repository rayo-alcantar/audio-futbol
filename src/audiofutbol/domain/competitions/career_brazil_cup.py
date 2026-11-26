"""Domestic knockout cup adapted from the contribution for the current engine."""

from __future__ import annotations

import random
from typing import Any

from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.models import Team


class CopaDoBrasil(ClubTournament):
    KEY = "copa_do_brasil"
    TITLE = "Copa do Brasil"
    FINAL_VENUE = ("Mané Garrincha", "Brasilia")
    ROUND_NAMES = {
        40: "Ronda preliminar", 60: "Ronda preliminar", 32: "Dieciseisavos de final", 16: "Octavos de final",
        8: "Cuartos de final", 4: "Semifinales", 2: "Final",
    }
    NO_EXTRA_TIME = True

    def __init__(self, teams: list[Team], user_team: Team, _skip_init: bool = False) -> None:
        self._init_club_base(teams, user_team)
        self.groups = [self.teams]
        if not _skip_init:
            if len(teams) not in (40, 60):
                raise ValueError("La Copa do Brasil necesita 40 o 60 clubes.")
            self.steps = [("unico", len(teams)), ("unico", 32)]
            for count in (16, 8, 4):
                self.steps.extend([("ida", count), ("vuelta", count)])
            self.steps.append(("unico", 2))
            self.ties = self._draw(self.teams[64 - len(self.teams):])
            self._prepare_step()

    def _draw(self, teams: list[Team]) -> list[dict[str, Any]]:
        entrants = random.sample(teams, len(teams))
        return [self._make_tie(a, b) for a, b in zip(entrants[::2], entrants[1::2])]

    def close_step(self) -> str:
        kind, count = self.steps[self.step_idx]
        if count == 2:
            return self._finish_final()
        notice = ""
        if kind != "ida":
            winners = self._winners()
            if not self.user_eliminated and any(self.user_team is t for pair in self.pairs for t in pair):
                notice = self._round_notice(self._losers())
            if self.step_idx == 0:
                winners += self.teams[:64 - len(self.teams)]
            self.ties = self._draw(winners)
        self.step_idx += 1
        self._prepare_step()
        return notice

    def is_neutral(self) -> bool:
        return self.steps[self.step_idx][1] == 2

    def venue(self, idx, venue_lookup):
        if self.is_neutral():
            return super().venue(idx, venue_lookup)
        return venue_lookup(self.pairs[idx][0])

    def venue_text(self, idx, venue_lookup):
        if self.is_neutral():
            return super().venue_text(idx, venue_lookup)
        venue = self.venue(idx, venue_lookup)
        return f"{venue[0]}, ciudad de {venue[1]}" if venue else None

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        home = None if self.is_neutral() else (0 if first_team is self.pairs[idx][0] else 1)
        return {**super().match_kwargs(idx, first_team), "no_extra_time": True, "home_index": home}
