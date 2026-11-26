"""Balanced world league calendar and lightweight background tables."""

from __future__ import annotations

from random import Random
from typing import Any

from audiofutbol.domain.competitions.career_simulation import expected_goals, poisson, profile, quick_match
from audiofutbol.domain.competitions.career_squad import season_copy
from audiofutbol.domain.competitions.career_world_catalog import WorldLeagueSpec
from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.competitions.scheduling import build_circle_schedule
from audiofutbol.domain.models import MatchResult, Team


def _schedule(teams: list[Team], legs: int, rng: Random) -> list[list[tuple[Team, Team]]]:
    bye = Team("", [])
    field = [*teams, bye] if len(teams) % 2 else teams
    rounds = [
        [(a, b) for a, b in day if a is not bye and b is not bye]
        for day in build_circle_schedule(field, len(field) - 1, rng)
    ]
    if legs == 2:
        rounds += [[(away, home) for home, away in day] for day in rounds.copy()]
    return rounds


class WorldLeague(ClubTournament):
    """World career uses regular tables, with two turns by default and true byes."""

    LEAGUE_PHASE_LABEL = "la liga"

    def __init__(
        self, spec: WorldLeagueSpec, teams: list[Team], user: Team, year: int, *, restore: bool = False,
    ) -> None:
        self._init_club_base(teams, user)
        self.KEY, self.TITLE, self.year = spec.key, spec.title, year
        self.groups = [self.teams]
        if not restore:
            rng = Random(f"calendar:{year}:{spec.key}")
            self.tiebreaker_rnd = {t.name: rng.random() for t in teams}
            self.schedule = _schedule(self.teams, spec.legs, rng)
            self.rounds_count = len(self.schedule)
            self.qualify_count = 0
            self.steps = [("liga", i) for i in range(self.rounds_count)]
            self._prepare_step()

    @property
    def yellow_limit(self) -> int:
        return 3 if self.KEY.startswith("world:brasil:") else 5

    def match_kwargs(self, idx: int, first_team: Team) -> dict[str, Any]:
        return {"home_index": 0 if first_team is self.pairs[idx][0] else 1, "yellow_card_limit": self.yellow_limit}

    def phase_name(self) -> str:
        return f"Jornada {self.step_idx + 1} de {self.rounds_count}"

    def position_text(self) -> str:
        place, row = self.user_position()
        return f"{self.user_team.name}, puesto {place} de {len(self.teams)}, {row['pts']} puntos."

    def close_step(self) -> str:
        if self.step_idx + 1 == self.rounds_count:
            order = self.standings()
            self.ranking = {team.name: place for place, team in enumerate(order, 1)}
            self.champion, self.runner_up = order[:2]
            return f"{self.champion.name} gana {self.TITLE}."
        self.step_idx += 1
        self._prepare_step()
        return ""

    @classmethod
    def start(cls, spec: WorldLeagueSpec, clubs: dict[str, Team], user: str, year: int) -> WorldLeague:
        teams = [season_copy(clubs[name]) for name in spec.club_names]
        return cls(spec, teams, next(team for team in teams if team.name == user), year)

    @classmethod
    def restore(cls, spec: WorldLeagueSpec, data: dict[str, Any], year: int) -> WorldLeague:
        teams = [Team.from_dict(t) for t in data["teams"]]
        by_name = {t.name: t for t in teams}
        if set(by_name) != set(spec.club_names) or len(teams) != len(by_name):
            raise ValueError("Incompatible world league save.")
        inst = cls(spec, teams, by_name[data["user_team"]], year, restore=True)
        inst._restore_common(data, by_name)
        return inst


def recent_form(draw: ClubTournament, team: Team) -> float:
    recent = []
    for _, a, b, ga, gb, _ in reversed(draw.history):
        if team is a or team is b:
            margin = ga - gb if team is a else gb - ga
            recent.append(3 if margin > 0 else 1 if margin == 0 else 0)
            if len(recent) == 5:
                break
    return sum(recent) / len(recent) - 1.35 if recent else 0.


def simulate_fixture(
    draw: ClubTournament, index: int, year: int, controlled: Team | None, **options,
) -> MatchResult:
    a, b = draw.pairs[index]
    rng = Random(f"match:{draw.KEY}:{year}:{draw.step_idx}:{a.team_id}:{b.team_id}")
    match_rules = draw.match_kwargs(index, a)
    yellow_limit = match_rules.get("yellow_card_limit", 5)
    neutral = draw.step_type() == "unico" and getattr(draw, "is_neutral", lambda: True)()
    result = quick_match(a, b, rng, (recent_form(draw, a), recent_form(draw, b)), yellow_limit,
                         controlled, neutral=neutral, **options)
    if draw.is_knockout() and "table_advantage" not in match_rules:
        first = match_rules.get("first_leg", (0, 0))
        if result.goals[0] + first[0] == result.goals[1] + first[1]:
            result.penalties = rng.choice(((5, 4), (4, 5), (4, 3), (3, 4)))
    draw.register_result(index, a, result)
    return result


def background_table(spec: WorldLeagueSpec, clubs: dict[str, Team], year: int) -> list[tuple[str, int]]:
    """Use the same score model without individual events for off-screen leagues."""
    rng = Random(f"background:{year}:{spec.key}")
    teams = [clubs[name] for name in spec.club_names]
    profiles = {team.name: profile(team, team.lineup(ignore_suspensions=True)) for team in teams}
    rows = {team.name: [0, 0, 0, rng.random()] for team in teams}
    for round_ in _schedule(teams, spec.legs, rng):
        for a, b in round_:
            x, y = rows[a.name], rows[b.name]
            rate_a, rate_b = expected_goals(profiles[a.name], profiles[b.name])
            ga, gb = poisson(rng, rate_a), poisson(rng, rate_b)
            x[0] += 3 if ga > gb else (ga == gb)
            y[0] += 3 if gb > ga else (ga == gb)
            x[1], y[1], x[2], y[2] = x[1] + ga - gb, y[1] + gb - ga, x[2] + ga, y[2] + gb
    return [(name, int(rows[name][0])) for name in sorted(rows, key=rows.get, reverse=True)]
