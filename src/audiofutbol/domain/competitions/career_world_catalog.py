"""Snapshotable definitions for the world career and its synthetic fallback squads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from random import Random

from audiofutbol.domain.models import Player, Team

_NAMES = {
    "Europa": (
        "Luca Hugo Martin Alex Daniel Leon Marco Adam Elias Noah Emil Victor Jan Leo".split(),
        "Martin Costa Moreau Novak Rossi Silva Müller Ivanov Eriksen López Vidal Sousa Pereira".split(),
    ),
    "Sudamérica": (
        "Mateo Gabriel Thiago Lucas Santiago Nicolás Matías Tomás Martín João Bruno Enzo".split(),
        "Silva Pereira Acosta Sosa García Ribeiro Gómez Torres Rocha Rojas Romero Díaz Ortiz".split(),
    ),
    "África": (
        "Amadou Youssef Karim Samuel Idrissa Musa Ali Emmanuel Omar David Mohamed Ibrahim".split(),
        "Diallo Mensah Diop Traoré Kamara Koné Owusu Ndiaye Sarr Hassan Coulibaly Abdi".split(),
    ),
    "Asia": (
        "Haru Ren Ali Amir Jun Tao Jun-ho Omar Arjun Riku Yuto Sami Tariq Hyun".split(),
        "Kim Lee Sato Wang Park Tanaka Nguyen Khan Suzuki Hassan Singh Yamamoto Ahmed".split(),
    ),
    "other": (
        "Alex James Daniel Luis Noah Samuel Leo Gabriel David Benjamin Mateo Hugo Ryan".split(),
        "Brown García Campbell Rivera Wilson Taylor Pérez Green Lewis Torres Collins Díaz".split(),
    ),
}


@dataclass(frozen=True)
class ClubSeed:
    key: str
    name: str
    country: str
    region: str
    rating: int
    stadium: str | None = None
    city: str = ""

    def generate(self) -> Team:
        rng = Random(f"world-squad-v1:{self.key}")
        first, last = _NAMES.get(self.region, _NAMES["other"])
        names = iter(rng.sample([f"{a} {b}" for a in first for b in last], 23))
        players = []
        for position, total, first_team in (("POR", 3, 1), ("DEF", 8, 4), ("MED", 7, 3), ("DEL", 5, 3)):
            for i in range(total):
                offset = rng.randint(-5, 4) if i < first_team else rng.randint(-12, -5)
                players.append(Player(next(names), position, max(39, min(97, self.rating + offset)), len(players) + 1))
        return Team(self.name, players, team_id=self.key, country=self.country,
                    stadium=self.stadium, city=self.city, level=self.rating)


@dataclass(frozen=True)
class WorldLeagueSpec:
    key: str
    title: str
    country: str
    region: str
    club_names: tuple[str, ...]
    legs: int = 2
    edition: str = ""

    def with_clubs(self, names: list[str]) -> WorldLeagueSpec:
        return replace(self, club_names=tuple(names))

    def to_dict(self) -> dict:
        return {**asdict(self), "club_names": list(self.club_names)}

    @classmethod
    def from_dict(cls, data: dict) -> WorldLeagueSpec:
        return cls(**{**data, "club_names": tuple(data["club_names"])})


@dataclass(frozen=True)
class DivisionLink:
    upper: str
    lower: str
    places: int
