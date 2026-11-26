"""Shared career calendar, finance, squad and save behavior."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, ClassVar

from audiofutbol.domain.competitions.career_academy import SCOUT_COST, CareerAcademy, Prospect
from audiofutbol.domain.competitions.career_market import CareerMarket, negotiate
from audiofutbol.domain.competitions.career_squad import copy_tactics, refresh_squad
from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.match.ports import MatchSettings
from audiofutbol.domain.models import Player, Team, format_result_text

FIRST_YEAR = 2026
SEASON_DAYS = 300
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


def career_date(year: int, day: int) -> str:
    current = date(year, 1, 15) + timedelta(days=day)
    return f"{current.day} de {MONTHS[current.month - 1]} de {current.year}"


@dataclass(frozen=True)
class CareerRound:
    day: int
    tournament: ClubTournament
    user_index: int | None
    step: int

    @property
    def neutral(self) -> bool:
        return self.tournament.step_type() == "unico" and getattr(self.tournament, "is_neutral", lambda: True)()

    def fixture_text(self) -> str:
        if self.user_index is None:
            return f"{self.tournament.TITLE}, {self.tournament.phase_name()}"
        home, away = self.tournament.pairs[self.user_index]
        local = home is self.tournament.user_team
        side = "en campo neutral" if self.neutral else ("de local" if local else "de visitante")
        return f"{self.tournament.TITLE}, contra {(away if local else home).name}, {side}"


@dataclass(frozen=True)
class CareerMessage:
    year: int
    day: int
    text: str


@dataclass(frozen=True)
class SeasonRecord:
    year: int
    division: str
    place: int
    objective: int
    next_division: str
    qualified_for: str | None
    trophies: list[str]


@dataclass
class ManagerCareer:
    """Shared manager career behavior; each competition policy owns its calendar and draw formats."""

    KEY: ClassVar[str]
    TITLE: ClassVar[str]
    SCHEMA: ClassVar[int]

    managed: str
    division: str
    clubs: dict[str, Team]
    draws: dict[str, ClubTournament]
    market: CareerMarket
    academy: CareerAcademy = field(default_factory=CareerAcademy)
    year: int = FIRST_YEAR
    day: int = 0
    history: list[SeasonRecord] = field(default_factory=list)
    inbox: list[CareerMessage] = field(default_factory=list)
    unread: int = 0

    @property
    def club(self) -> Team:
        return self.clubs[self.managed]

    @property
    def league(self) -> ClubTournament:
        return self.draws[self.division]

    @property
    def employed(self) -> bool:
        return True

    @property
    def currency(self) -> str:
        return "reales"

    def round_day(self, tournament: ClubTournament, step: int | None = None) -> int:
        raise NotImplementedError

    def _simulate_round(self, tournament: ClubTournament, settings: MatchSettings) -> None:
        tournament.simulate_remaining(settings)

    def _manager_result(self, fixture: CareerRound, goals_for: int, goals_against: int) -> None:
        pass

    def _prize(self, tournament: ClubTournament) -> int:
        return 2_500_000 if tournament.KEY == self.division else 4_000_000

    @property
    def elapsed(self) -> int:
        return (self.year - FIRST_YEAR) * SEASON_DAYS + self.day

    @property
    def finished(self) -> bool:
        return all(t.champion is not None for t in self.draws.values())

    @property
    def window(self) -> str | None:
        if self.finished:
            return "entre temporadas"
        if self.day <= 26:
            return "inicial"
        if 135 <= self.day <= 156:
            return "de mitad de temporada"
        return None

    def notify(self, text: str) -> None:
        self.inbox.append(CareerMessage(self.year, self.day, text))
        self.inbox = self.inbox[-100:]
        self.unread = min(len(self.inbox), self.unread + 1)

    def agenda(self) -> list[CareerRound]:
        rounds = [
            CareerRound(self.round_day(t), t,
                        t.user_match_index() if self.employed and t.user_team.name == self.managed else None,
                        t.step_idx)
            for t in self.draws.values() if t.champion is None
        ]
        return sorted(rounds, key=lambda r: (r.day, r.user_index is None, r.tournament.KEY))

    def _advance_day(self, day: int) -> None:
        window = self.window
        self.day = day
        if self.window != window and self.window is not None:
            self.notify(f"Abrió la ventana de fichajes {self.window}.")
        for message in self.academy.advance(self.year, self.elapsed):
            self.notify(message)

    def prepare_round(self, fixture: CareerRound) -> None:
        if self.agenda()[:1] != [fixture]:
            raise ValueError("El partido seleccionado ya no es el próximo del calendario.")
        self._advance_day(fixture.day)

    def finish_round(self, fixture: CareerRound, settings: MatchSettings) -> list[str]:
        """Finish the prepared round; use any manually registered user result first."""
        tournament = fixture.tournament
        if (self.draws.get(tournament.KEY) is not tournament or tournament.champion is not None
                or tournament.step_idx != fixture.step or self.day != fixture.day):
            raise ValueError("La jornada ya no está pendiente.")
        self._simulate_round(tournament, settings)
        messages = []
        if fixture.user_index is not None:
            home, away = tournament.pairs[fixture.user_index]
            result = tournament.completed[fixture.user_index]
            messages.append("Resultado: " + format_result_text(home, away, result["ga"], result["gb"], result["pen"]))
            if home is tournament.user_team and not fixture.neutral:
                revenue = 150_000 + self.club.level * 2_500
                self.market.post(self.year, self.day, f"Taquilla contra {away.name}", revenue)
            copy_tactics(tournament.user_team, self.club)
            self.refresh_clubs(self.club)
            local = home is tournament.user_team
            ga, gb = result["ga"], result["gb"]
            self._manager_result(fixture, ga if local else gb, gb if local else ga)
        notice = tournament.close_step()
        if notice and (self.employed or fixture.user_index is not None) and tournament.user_team.name == self.managed:
            messages.append(notice)
            self.notify(notice)
        if (self.employed and tournament.champion is tournament.user_team
                and tournament.user_team.name == self.managed):
            prize = self._prize(tournament)
            self.market.post(self.year, self.day, f"Premio por ganar {tournament.TITLE}", prize)
            self.notify(f"Ganaste {tournament.TITLE}. El premio se abonó al presupuesto.")
        if self.finished:
            self.notify("La temporada terminó. Abrió el mercado entre temporadas." if self.employed else
                        "La temporada terminó. Puedes buscar un puesto en otras ligas desde Oficina.")
            messages.append("Terminó la temporada. Puedes consultar el balance o iniciar la siguiente.")
        return messages

    def refresh_clubs(self, *clubs: Team) -> None:
        by_name = {club.name: club for club in clubs}
        for draw in self.draws.values():
            if draw.champion is None:
                for team in draw.teams:
                    if team.name in by_name:
                        refresh_squad(by_name[team.name], team)
        for club in clubs:
            copy_tactics(club, club)

    def _check_window(self) -> None:
        if not self.employed:
            raise ValueError("Necesitas dirigir un club para gestionar su mercado.")
        if self.window is None:
            raise ValueError("El mercado está cerrado. Abre al inicio, a mitad de temporada y entre temporadas.")

    def buy(self, seller: Team, player: Player, bid: int, *, accept_counter: bool = False) -> tuple[str, int]:
        self._check_window()
        if self.clubs.get(seller.name) is not seller or seller is self.club:
            raise ValueError("El jugador no pertenece a otro club del mercado.")
        status, fee = negotiate(player, bid)
        if status == "rejected" or (status == "counter" and not accept_counter):
            return status, fee
        self.market.transfer(user=self.club, seller=seller, buyer=self.club, player=player,
                             fee=fee, year=self.year, day=self.day)
        self.refresh_clubs(seller, self.club)
        self.notify(f"{player.name} se incorporó a {self.club.name} desde {seller.name}.")
        return "accepted", fee

    def sell(self, player: Player) -> tuple[Team, int]:
        self._check_window()
        offer = self.sale_offer(player)
        if offer is None:
            raise ValueError("Ya no hay una oferta válida para este jugador.")
        buyer, fee = offer
        self.market.transfer(user=self.club, seller=self.club, buyer=buyer, player=player,
                             fee=fee, year=self.year, day=self.day)
        self.refresh_clubs(self.club, buyer)
        self.notify(f"{player.name} fue traspasado a {buyer.name}.")
        return buyer, fee

    def sale_offer(self, player: Player) -> tuple[Team, int] | None:
        return self.market.offer_for_sale(player, self.club, list(self.clubs.values()))

    def scout(self) -> list[Prospect]:
        if not self.employed:
            raise ValueError("Necesitas dirigir un club para gestionar la cantera.")
        players = self.academy.scout(self.club, self.year, self.elapsed, self.market.balance)
        self.market.post(self.year, self.day, "Informe de ojeo juvenil", -SCOUT_COST)
        self.notify(f"El ojeador encontró {len(players)} juveniles. Ya puedes consultar el informe en Cantera.")
        return players

    def promote(self, prospect: Prospect) -> Player:
        if not self.employed:
            raise ValueError("Necesitas dirigir un club para gestionar la cantera.")
        player = self.academy.promote(self.club, prospect, self.year)
        self.refresh_clubs(self.club)
        self.notify(f"{player.name} subió desde la cantera al primer equipo.")
        return player

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.KEY, "career_schema": self.SCHEMA,
            "managed": self.managed, "division": self.division, "year": self.year, "day": self.day,
            "clubs": self._club_snapshots(),
            "draws": [t.to_dict() for t in self.draws.values()],
            "market": self.market.to_dict(), "academy": self.academy.to_dict(),
            "history": [asdict(record) for record in self.history],
            "inbox": [asdict(message) for message in self.inbox], "unread": self.unread,
        }

    def _club_snapshots(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.clubs.values()]
