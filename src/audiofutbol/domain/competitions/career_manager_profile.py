"""Persistent manager reputation and employment history, independent of club points."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Appointment:
    year: int
    day: int
    club: str
    league: str
    event: str


@dataclass
class ManagerProfile:
    name: str = "Dirección técnica"
    points: int = 0
    confidence: int = 65
    wins: int = 0
    draws: int = 0
    losses: int = 0
    titles: int = 0
    tenure_matches: int = 0
    season_matches: int = 0
    unemployed_since: int | None = None
    appointments: list[Appointment] = field(default_factory=list)

    @property
    def reputation(self) -> str:
        for minimum, label in ((650, "élite"), (350, "reconocido"), (150, "consolidado"), (55, "en ascenso")):
            if self.points >= minimum:
                return label
        return "emergente"

    def appoint(self, year: int, day: int, club: str, league: str) -> None:
        self.confidence, self.tenure_matches, self.unemployed_since = 65, 0, None
        self.appointments.append(Appointment(year, day, club, league, "Contratación"))

    def leave(self, year: int, day: int, elapsed: int, club: str, league: str, reason: str) -> None:
        self.unemployed_since = elapsed
        self.appointments.append(Appointment(year, day, club, league, reason))

    def result(self, ga: int, gb: int, expected: float) -> bool:
        outcome = 1.0 if ga > gb else .5 if ga == gb else 0.
        self.wins += int(ga > gb)
        self.draws += int(ga == gb)
        self.losses += int(ga < gb)
        self.tenure_matches += 1
        self.season_matches += 1
        self.points += (7 + int(expected < .42) * 3) if ga > gb else (2 if ga == gb else 0)
        shift = round(13 * (outcome - expected))
        self.confidence = max(0, min(100, self.confidence + shift))
        return self.tenure_matches >= 8 and self.confidence <= 10

    def complete_season(self, meets_objective: bool, champion: bool) -> None:
        self.points += 28 * int(meets_objective) + 60 * int(champion)
        self.titles += int(champion)
        self.confidence = max(0, min(100, self.confidence + (9 if meets_objective else -13)))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ManagerProfile:
        return cls(**{**data, "appointments": [Appointment(**r) for r in data["appointments"]]})
