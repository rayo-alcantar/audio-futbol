"""Persistent manager career assembled from the current competition engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.career_academy import CareerAcademy
from audiofutbol.domain.competitions.career_brazil_rules import (
    CAREER_DRAWS, CONTINENTAL_TYPES, LEAGUES, NATIONAL_CUP, League,
    continental_qualifiers, fixture_day, next_divisions, start_continental, start_domestic,
)
from audiofutbol.domain.competitions.career_market import CareerMarket
from audiofutbol.domain.competitions.career_squad import club_key, season_copy
from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.models import Team

from audiofutbol.domain.competitions.career_core import (
    FIRST_YEAR, SEASON_DAYS, CareerMessage, ManagerCareer, SeasonRecord,
)

ContinentalField = tuple[dict[str, Any], list[Team]]


@dataclass
class BrazilianCareer(ManagerCareer):
    """Aggregate: clubs own recruitment; draws own competition-local match data."""

    KEY: ClassVar[str] = "carrera_dt_brasil"
    TITLE: ClassVar[str] = "Carrera de DT en Brasil"
    SCHEMA: ClassVar[int] = 1

    @classmethod
    def start(
        cls, first: list[Team], second: list[Team], managed: str,
    ) -> BrazilianCareer:
        clubs = {club.name: season_copy(club) for club in [*first, *second]}
        if managed not in clubs:
            raise ValueError("El club elegido no participa en la carrera.")
        division = BrasileiraoA.KEY if any(t.name == managed for t in first) else BrasileiraoB.KEY
        draws = start_domestic(first, second, managed)
        career = cls(managed, division, clubs, draws, CareerMarket.start(clubs[managed], list(clubs.values())))
        career.notify(f"Empieza tu carrera con {managed}. La ventana de fichajes inicial está abierta.")
        career.notify(f"La directiva espera terminar entre los {career.objective} primeros de la liga.")
        return career

    @property
    def league(self) -> League:
        league = self.draws[self.division]
        assert isinstance(league, (BrasileiraoA, BrasileiraoB))
        return league

    @property
    def objective(self) -> int:
        return 6 if self.division == BrasileiraoB.KEY else (6 if self.club.level >= 78 else 12)

    def round_day(self, tournament: ClubTournament, step: int | None = None) -> int:
        return fixture_day(tournament, step)

    def season_record(self) -> SeasonRecord:
        if not self.finished:
            raise ValueError("Aún quedan competiciones pendientes.")
        first, second = self.draws[BrasileiraoA.KEY], self.draws[BrasileiraoB.KEY]
        cup = self.draws[NATIONAL_CUP]
        a, _ = next_divisions(first, second)
        qualifiers = continental_qualifiers(first, cup)
        return SeasonRecord(
            self.year, self.division, self.league.user_position()[0], self.objective,
            BrasileiraoA.KEY if self.managed in a else BrasileiraoB.KEY,
            next((key for key, names in qualifiers.items() if self.managed in names), None),
            [t.TITLE for t in self.draws.values() if t.champion and t.champion.name == self.managed],
        )

    def new_season(self, field: ContinentalField | None = None) -> SeasonRecord:
        record = self.season_record()
        first, second = self.draws[BrasileiraoA.KEY], self.draws[BrasileiraoB.KEY]
        a, b = next_divisions(first, second)
        draws = start_domestic([self.clubs[n] for n in a], [self.clubs[n] for n in b], self.managed)
        if key := record.qualified_for:
            if field is None:
                raise ValueError("No se pudieron cargar los participantes de la copa continental.")
            qualifiers = continental_qualifiers(first, self.draws[NATIONAL_CUP])
            draws[key] = start_continental(key, self.clubs, qualifiers[key], self.managed, *field)
        # Commit the rollover only after every new draw has been built successfully.
        self.history.append(record)
        self.year += 1
        self.day = 0
        self.draws = draws
        self.division = record.next_division
        self.notify(f"Temporada {self.year}: jugarás en la {self.league.TITLE}.")
        if record.qualified_for:
            self.notify(f"Clasificaste a la {self.draws[record.qualified_for].TITLE}.")
        for message in self.academy.advance(self.year, self.elapsed):
            self.notify(message)
        return record

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrazilianCareer:
        if data.get("career_schema") != cls.SCHEMA:
            raise ValueError("Unknown career save schema.")
        clubs = {t.name: t for t in map(Team.from_dict, data["clubs"])}
        draws = {raw["type"]: CAREER_DRAWS[raw["type"]].from_dict(raw) for raw in data["draws"]}
        managed, division, year, day = (data[key] for key in ("managed", "division", "year", "day"))
        if (
            not FIRST_YEAR <= year < 9999 or not 0 <= day < SEASON_DAYS
            or len({club_key(n) for n in clubs}) != 40
            or not {*LEAGUES, NATIONAL_CUP} <= draws.keys()
            or len(draws.keys() & CONTINENTAL_TYPES.keys()) > 1
            or division not in LEAGUES or managed not in clubs or draws[division].user_team.name != managed
        ):
            raise ValueError("Invalid career state.")
        market = CareerMarket.from_dict(data["market"])
        if market.balance < 0 or market.club_funds.keys() != {club_key(n) for n in clubs if n != managed}:
            raise ValueError("Invalid career budget.")
        return cls(
            managed, division, clubs, draws, market, CareerAcademy.from_dict(data["academy"]), year, day,
            [SeasonRecord(**x) for x in data["history"]], [CareerMessage(**x) for x in data["inbox"]],
            min(len(data["inbox"]), max(0, data["unread"])),
        )
