"""Load and injuries persist as calendar dates without touching tournament suspensions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from random import Random

from audiofutbol.domain.models import MatchResult, Player, Team

WARNING_LOAD = 28


@dataclass
class Condition:
    day: int
    load: float = 0.
    recovery: int = 0


@dataclass
class CareerFitness:
    records: dict[str, dict[str, Condition]] = field(default_factory=dict)

    def load(self, team: Team, player: Player, day: int) -> float:
        condition = self.records.get(team.name, {}).get(player.name)
        return max(0., condition.load - 9 * max(0, day - condition.day)) if condition else 0.

    def is_injured(self, team: Team, player: Player, day: int) -> bool:
        condition = self.records.get(team.name, {}).get(player.name)
        return condition is not None and condition.recovery > day

    def available_on(self, team: Team, player: Player) -> int | None:
        condition = self.records.get(team.name, {}).get(player.name)
        return condition.recovery if condition else None

    def prepare(self, team: Team, day: int) -> dict[str, float]:
        for player in team.players:
            player.medically_unavailable = self.is_injured(team, player, day)
        return {p.name: self.load(team, p, day) for p in team.players}

    def move_player(self, previous: Team, next_: Team, name: str) -> None:
        source = self.records.get(previous.name, {})
        if condition := source.pop(name, None):
            self.records.setdefault(next_.name, {})[name] = condition

    def post_match(self, team: Team, result: MatchResult, side: int, day: int) -> list[str]:
        if result.abandoned:
            return []
        seen = {p.name: p for p in team.players}
        records = self.records.setdefault(team.name, {})
        for name, minutes in result.minutes[side].items():
            if name in seen:
                old = records.get(name)
                effort = .40 if seen[name].position == "POR" else .62
                records[name] = Condition(day, min(100., self.load(team, seen[name], day) + minutes * effort),
                                          old.recovery if old else 0)
        notices = []
        for name in result.injuries[side]:
            if name not in seen:
                continue
            condition = records.setdefault(name, Condition(day))
            rng = Random(f"injury:{team.team_id}:{name}:{day}")
            severity = rng.random()
            days = rng.randint(3, 8) if severity < .65 else rng.randint(10, 20) if severity < .95 else rng.randint(28, 48)
            condition.recovery = max(condition.recovery, day + days)
            notices.append(f"Parte médico. {name}: baja estimada de {days} días.")
        # Keep the save bounded to relevant, recent playing time.
        self.records[team.name] = {
            name: c for name, c in records.items() if name in seen and (c.recovery > day or day - c.day < 14)
        }
        return notices

    def to_dict(self) -> dict:
        return {team: {name: asdict(c) for name, c in players.items()} for team, players in self.records.items()}

    @classmethod
    def from_dict(cls, raw: dict) -> CareerFitness:
        return cls({team: {name: Condition(**c) for name, c in players.items()} for team, players in raw.items()})
