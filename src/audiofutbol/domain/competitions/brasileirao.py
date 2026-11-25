"""Brazilian Série A and Série B formats for the 2026 season."""

from __future__ import annotations

from itertools import groupby
from typing import Any

from audiofutbol.domain.competitions.club_tournaments import DoubleRoundRobin
from audiofutbol.domain.models import MatchResult, Team


class _Brasileirao(DoubleRoundRobin):
    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        return {**super().match_kwargs(idx, first_team), "yellow_card_limit": 3}

    def register_result(
        self, idx: int, first_team: Team, res: MatchResult
    ) -> tuple[int, int, tuple[int, int] | None]:
        if self.step_type() == "liga":
            a, b = self.pairs[idx]
            order = (0, 1) if first_team is a else (1, 0)
            for team, side in zip((a, b), order):
                row = self.table[team.name]
                row["red_cards"] = row.get("red_cards", 0) + res.red_cards[side]
                row["yellow_cards"] = row.get("yellow_cards", 0) + res.yellow_cards[side]
        return super().register_result(idx, first_team, res)

    def _league_key(self, team: Team) -> tuple[int, int, int, int]:
        row = self.table[team.name]
        return -row["pts"], -row["g"], row["gc"] - row["gf"], -row["gf"]

    def _discipline_key(self, team: Team) -> tuple[int, int, float]:
        row = self.table[team.name]
        return row.get("red_cards", 0), row.get("yellow_cards", 0), self.tiebreaker_rnd[team.name]

    def _head_to_head(self, a: Team, b: Team) -> int:
        # The first two meetings are the league fixtures, even after the Série B playoff.
        margins = [
            ga - gb if home is a else gb - ga
            for _, home, away, ga, gb, _ in self.history
            if (home is a and away is b) or (home is b and away is a)
        ][:2]
        # In two fixtures, a points advantage always implies an aggregate advantage.
        return sum(margins) if len(margins) == 2 else 0

    def _sort_group(self, grp: list[Team]) -> list[Team]:
        order: list[Team] = []
        for _, group in groupby(sorted(grp, key=self._league_key), self._league_key):
            tied = list(group)
            if len(tied) == 2 and (margin := self._head_to_head(*tied)):
                order.extend(tied if margin > 0 else reversed(tied))
            else:
                order.extend(sorted(tied, key=self._discipline_key))
        return order


class BrasileiraoA(_Brasileirao):
    """Série A: champion by league table, continental zones and four relegations."""

    KEY = "brasileirao_a"
    TITLE = "Série A del Brasileirão"

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 4:
            return "Zona de Libertadores, fase de grupos"
        if rank == 5:
            return "Zona de Libertadores, fase preliminar"
        if rank <= 11:
            return "Zona de Copa Sudamericana"
        if rank > len(self.teams) - 4:
            return "Desciende a la Série B" if finished else "Zona de descenso"
        return ""

    def final_summary_lines(self) -> list[str]:
        if self.champion is None:
            return []
        clubs = [team.name for team in self.standings()]
        return [
            f"Zona base de Libertadores, fase de grupos: {', '.join(clubs[:4])}.",
            f"Zona base de Libertadores, fase preliminar: {clubs[4]}.",
            f"Zona base de Copa Sudamericana: {', '.join(clubs[5:11])}.",
            f"Descenso a la Série B: {', '.join(clubs[-4:])}.",
        ]


class BrasileiraoB(_Brasileirao):
    """Série B: two direct promotions and two two-legged promotion playoffs."""

    KEY = "brasileirao_b"
    TITLE = "Série B del Brasileirão"
    LEAGUE_PHASE_LABEL = "la fase regular"
    ROUND_NAMES = {"ascenso": "Repechaje de ascenso"}

    def __init__(
        self,
        data: dict[str, Any] | None,
        teams_by_id: dict[str, Team],
        user_team: Team,
        _skip_init: bool = False,
    ) -> None:
        super().__init__(data, teams_by_id, user_team, _skip_init)
        self.qualify_count = 4
        if not _skip_init:
            self.steps.extend([("ida", "ascenso"), ("vuelta", "ascenso")])

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank <= 2:
            return "Asciende a la Série A" if finished else "Zona de ascenso directo"
        if rank <= 6:
            if self.champion is not None:
                team = next(t for t in self.teams if self.ranking[t.name] == rank)
                if any(team is self.tie_winner(tie) for tie in self.ties):
                    return "Asciende a la Série A por repechaje"
                return "No asciende"
            return "Juega el repechaje" if finished else "Zona de repechaje de ascenso"
        if rank > len(self.teams) - 4:
            return "Desciende a la Série C" if finished else "Zona de descenso"
        return ""

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        kwargs = super().match_kwargs(idx, first_team)
        if self.step_type() == "vuelta":
            # In two games, the points comparison gives the same winner as the
            # aggregate, followed by the better-ranked team when both are tied.
            kwargs["no_extra_time"] = True
        return kwargs

    def close_step(self) -> str:
        kind, data = self.steps[self.step_idx]
        if kind == "liga":
            if data < self.rounds_count - 1:
                return super().close_step()
            order = self.standings()
            self.ranking = {team.name: rank for rank, team in enumerate(order, start=1)}
            self.qualified = order[2:6]
            self.ties = [self._make_tie(order[5], order[2]), self._make_tie(order[4], order[3])]
            for team in self.qualified:
                for player in team.players:
                    player.yellow_cards = 0
            notice = (
                f"Terminó la fase regular. {order[0].name} es campeón. "
                f"{order[0].name} y {order[1].name} ascienden directamente a la Série A. "
                f"{self.user_team.name} termina en el puesto {self.ranking[self.user_team.name]}. "
                "Empieza el repechaje de ascenso."
            )
        elif kind == "ida":
            notice = "Se jugará la vuelta del repechaje de ascenso."
        else:
            order = self.standings()
            self.champion, self.runner_up = order[0], order[1]
            return ""
        self.step_idx += 1
        self._prepare_step()
        return notice

    def final_summary_lines(self) -> list[str]:
        if self.champion is None or self.runner_up is None:
            return []
        winners = [self.tie_winner(tie).name for tie in self.ties]
        relegated = [team.name for team in self.standings()[-4:]]
        return [
            f"Ascenso directo a la Série A: {self.champion.name} y {self.runner_up.name}.",
            f"Ascenso por repechaje: {' y '.join(winners)}.",
            f"Descenso a la Série C: {', '.join(relegated)}.",
        ]
