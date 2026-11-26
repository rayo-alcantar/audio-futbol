"""A portable world career whose manager, club budgets and divisions survive seasons."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from random import Random
from typing import Any, ClassVar

from audiofutbol.domain.competitions.career_academy import CareerAcademy
from audiofutbol.domain.competitions.career_core import FIRST_YEAR, SEASON_DAYS, CareerMessage, CareerRound, ManagerCareer
from audiofutbol.domain.competitions.career_fitness import WARNING_LOAD, CareerFitness
from audiofutbol.domain.competitions.career_manager_profile import ManagerProfile
from audiofutbol.domain.competitions.career_market import CareerMarket, LedgerEntry
from audiofutbol.domain.competitions.career_match_log import MatchLog, build_match_log
from audiofutbol.domain.competitions.career_squad import club_key, season_copy
from audiofutbol.domain.competitions.career_transfer_desk import OPEN, TransferDesk
from audiofutbol.domain.competitions.career_world_catalog import ClubSeed, DivisionLink, WorldLeagueSpec
from audiofutbol.domain.competitions.career_world_draws import (
    A, B, C, bracket_order, brazilian_qualifiers, encode_draw, restore_draw, start_draws,
)
from audiofutbol.domain.competitions.career_world_league import WorldLeague, background_table, simulate_fixture
from audiofutbol.domain.competitions.career_world_market import budget_for, open_world_budget, recruit
from audiofutbol.domain.competitions.career_world_season import apply_promotions
from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.match.conditional_changes import CONDITIONS, ConditionalChange
from audiofutbol.domain.match.ports import MatchSettings
from audiofutbol.domain.models import MatchResult, Player, Team


@dataclass(frozen=True)
class WorldSeasonRecord:
    year: int
    club: str
    league: str
    place: int
    league_points: int
    objective: int
    champion: bool
    manager_employed: bool


@dataclass(frozen=True)
class JobOffer:
    league: str
    club: str
    required_points: int


@dataclass
class WorldCareer(ManagerCareer):
    KEY: ClassVar[str] = "carrera_dt_mundial"
    TITLE: ClassVar[str] = "Carrera mundial de DT"
    SCHEMA: ClassVar[int] = 1

    leagues: dict[str, WorldLeagueSpec] = field(default_factory=dict)
    links: list[DivisionLink] = field(default_factory=list)
    stock: dict[str, ClubSeed] = field(default_factory=dict)
    coach: ManagerProfile = field(default_factory=ManagerProfile)
    touched: set[str] = field(default_factory=set)
    closed_seasons: list[WorldSeasonRecord] = field(default_factory=list)
    world_tables: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    academies: dict[str, CareerAcademy] = field(default_factory=dict)
    club_ledgers: dict[str, list[LedgerEntry]] = field(default_factory=dict)
    processed_windows: set[str] = field(default_factory=set)
    board_target: int = 1
    fitness: CareerFitness = field(default_factory=CareerFitness)
    negotiations: TransferDesk = field(default_factory=TransferDesk)
    match_logs: list[MatchLog] = field(default_factory=list)
    substitution_plans: dict[str, list[ConditionalChange]] = field(default_factory=dict)

    @classmethod
    def start(
        cls, leagues: dict[str, WorldLeagueSpec], links: list[DivisionLink], stock: dict[str, ClubSeed],
        rosters: dict[str, Team], division: str, managed: str, name: str,
    ) -> WorldCareer:
        clubs = {n: seed.generate() for n, seed in stock.items()} | {n: season_copy(t) for n, t in rosters.items()}
        draws = start_draws(leagues, clubs, division, managed, FIRST_YEAR)
        career = cls(managed, division, clubs, draws, open_world_budget(clubs[managed], clubs, FIRST_YEAR),
                     leagues=dict(leagues), links=list(links), stock=dict(stock),
                     coach=ManagerProfile(name=name or "Dirección técnica"))
        career._appoint()
        return career

    @property
    def league(self) -> ClubTournament:
        return self.draws[self.division]

    @property
    def employed(self) -> bool:
        return self.coach.unemployed_since is None

    @property
    def currency(self) -> str:
        return "euros"

    @property
    def objective(self) -> int:
        return self.board_target

    def _appoint(self) -> None:
        n = len(self.league.teams)
        ranking = sorted(self.leagues[self.division].club_names, key=lambda name: -self.clubs[name].strength())
        self.board_target = min(n, max(1, ranking.index(self.managed) + 2))
        if self.day > 0:
            current, _ = self.league.user_position()
            self.board_target = min(n, max(self.board_target, current - 2))
        self.coach.appoint(self.year, self.day, self.managed, self.league.TITLE)
        self.notify(f"{self.managed} te contrató. La directiva espera terminar entre los {self.objective} primeros.")

    def resign(self, *, dismissed: bool = False) -> None:
        if not self.employed:
            raise ValueError("Actualmente no diriges ningún club.")
        reason = "Destitución" if dismissed else "Dimisión"
        self._close_club_talks()
        self.coach.leave(self.year, self.day, self.elapsed, self.managed, self.league.TITLE, reason)
        self.notify(f"{reason} en {self.managed}. Conservas tu historial y tus puntos de entrenador.")

    def round_day(self, tournament: ClubTournament, step: int | None = None) -> int:
        index = tournament.step_idx if step is None else step
        if tournament.KEY in (A, B) and not isinstance(tournament, WorldLeague):
            return 5 + 7 * index
        if tournament.KEY == C and len(self.draws) > 1:
            return 5 + 14 * index
        if tournament.KEY == "copa_do_brasil":
            return 9 + 28 * index
        if tournament.KEY in ("libertadores", "sudamericana"):
            return 13 + 21 * index
        midpoint = max(1, (tournament.rounds_count - 1) // 2)
        if index <= midpoint:
            return 5 + 136 * index // midpoint
        return 141 + 140 * (index - midpoint) // max(1, tournament.rounds_count - 1 - midpoint)

    def refresh_clubs(self, *clubs: Team) -> None:
        super().refresh_clubs(*clubs)
        self.touched.update(team.name for team in clubs)
        for team in clubs:
            if plans := self.substitution_plans.get(team.name):
                names = {p.name for p in team.players}
                self.substitution_plans[team.name] = [r for r in plans if r.incoming in names and r.outgoing in names]

    @property
    def changes(self) -> list[ConditionalChange]:
        return self.substitution_plans.get(self.managed, [])

    def set_changes(self, entries: list[ConditionalChange]) -> None:
        roster = {p.name: p for p in self.club.players}
        if not self.employed or len(entries) > 3 or any(
            r.outgoing == r.incoming or r.outgoing not in roster or r.incoming not in roster
            or r.condition not in CONDITIONS or not 1 <= r.minute < 90
            or (roster[r.outgoing].position == "POR") != (roster[r.incoming].position == "POR")
            for r in entries
        ):
            raise ValueError("Revisa los jugadores y el límite de tres cambios programados.")
        self.substitution_plans[self.managed] = sorted(entries, key=lambda r: r.minute)

    def _close_club_talks(self) -> None:
        for talk in self.negotiations.for_club(self.managed):
            if talk.state in OPEN:
                self.negotiations.withdraw(self, talk)

    def _advance_day(self, day: int) -> None:
        if not self.day <= day < SEASON_DAYS:
            raise ValueError("La fecha está fuera de la temporada.")
        for value in range(self.day + 1, day + 1):
            super()._advance_day(value)
            self.negotiations.tick(self)

    def wait_days(self, days: int, *, stop_on_news: bool = False) -> int:
        """Advance clock events, without skipping or completing a fixture."""
        before = self.day
        agenda = self.agenda()
        limit = min(agenda[0].day if agenda else SEASON_DAYS - 1, self.day + max(0, days))
        while self.day < limit:
            previous = self.inbox[-1:]  # List is capped, so a count cannot detect every new message.
            self._advance_day(self.day + 1)
            if stop_on_news and self.inbox[-1:] != previous:
                break
        return self.day - before

    def lineup_alerts(self, fixture: CareerRound) -> list[str]:
        day = self.elapsed + fixture.day - self.day
        alerts = []
        suspended = {p.name for p in fixture.tournament.user_team.players if p.suspended_matches > 0}
        for player in self.club.lineup(ignore_suspensions=True):
            if self.fitness.is_injured(self.club, player, day):
                alerts.append(f"{player.name} está lesionado y no estará disponible.")
            elif player.name in suspended:
                alerts.append(f"{player.name} está sancionado en esta competición.")
            else:
                load = self.fitness.load(self.club, player, day)
                if load >= WARNING_LOAD:
                    alerts.append(f"{player.name}: cansancio {round(load)} de 100. Considera darle descanso.")
        return alerts

    def health_for_fixture(self, home: Team, away: Team) -> tuple[dict[str, float], dict[str, float]]:
        return self.fitness.prepare(home, self.elapsed), self.fitness.prepare(away, self.elapsed)

    def record_match(self, draw: ClubTournament, sides: tuple[Team, Team], result: MatchResult, simulated: bool) -> None:
        managed = self.employed and any(team.name == self.managed for team in sides)
        for index, team in enumerate(sides):
            notices = self.fitness.post_match(team, result, index, self.elapsed)
            if managed and team.name == self.managed:
                for notice in notices:
                    self.notify(notice)
        if managed:
            log = build_match_log(self.year, self.day, f"{draw.TITLE}. {draw.phase_name()}",
                                  sides, result, simulated=simulated)
            self.match_logs = [*self.match_logs[-199:], log]

    def sale_offer(self, player: Player) -> tuple[Team, int] | None:
        spec = self.leagues[self.division]
        names = dict.fromkeys(n for league in self.leagues.values() if league.country == spec.country
                              for n in league.club_names)
        domestic = [self.clubs[name] for name in names]
        return self.market.offer_for_sale(player, self.club, domestic)

    def prepare_round(self, fixture: CareerRound) -> None:
        super().prepare_round(fixture)
        if self.window and (key := f"{self.year}:{self.division}:{self.window}") not in self.processed_windows:
            self.processed_windows.add(key)
            field = [self.clubs[n] for n in self.leagues[self.division].club_names]
            deals = recruit(self.market, field, self.managed, Random(key),
                            eligible=lambda team, p: not self.fitness.is_injured(team, p, self.elapsed))
            for buyer, seller, player, _ in deals:
                self.fitness.move_player(seller, buyer, player)
                self.refresh_clubs(buyer, seller)
                self.notify(f"Mercado: {player} pasó de {seller.name} a {buyer.name}.")

    def _simulate_round(self, tournament: ClubTournament, settings: MatchSettings) -> None:
        controlled = tournament.user_team if self.employed and tournament.user_team.name == self.managed else None
        for i in range(len(tournament.pairs)):
            if i not in tournament.completed:
                sides = tournament.pairs[i]
                result = simulate_fixture(tournament, i, self.year, controlled, fatigue=self.health_for_fixture(*sides),
                                          changes=self.changes if any(t is controlled for t in sides) else None)
                self.record_match(tournament, sides, result, simulated=True)

    def _manager_result(self, fixture: CareerRound, goals_for: int, goals_against: int) -> None:
        home, away = fixture.tournament.pairs[fixture.user_index]
        local = home is fixture.tournament.user_team
        rival = away if local else home
        expectation = max(.22, min(.78, .52 + (self.club.strength() - rival.strength()) * .018 + (.055 if local else -.055)))
        if self.coach.result(goals_for, goals_against, expectation):
            self.resign(dismissed=True)

    def season_record(self) -> WorldSeasonRecord:
        if not self.finished:
            raise ValueError("Aún quedan jornadas pendientes.")
        place, row = self.league.user_position()
        return WorldSeasonRecord(self.year, self.managed, self.league.TITLE, place, row["pts"],
                                 self.objective, self.league.champion is self.league.user_team, self.employed)

    def job_offers(self, league_key: str) -> list[JobOffer]:
        if not self.finished and (self.employed or league_key != self.division):
            return []
        if not self.finished and self.elapsed - self.coach.unemployed_since < 14:
            return []
        league = self.leagues[league_key]
        ranks = {n: place for place, (n, _) in enumerate(self.world_tables.get(league_key, []), 1)}
        if league_key == self.division:
            ranks = {team.name: place for place, team in enumerate(self.league.standings(), 1)}
        offers = []
        for name in league.club_names:
            if name == self.managed:
                continue
            table_pressure = ranks.get(name, 0) > len(league.club_names) * .65
            if not self.finished and not table_pressure:
                continue
            required = max(0, int((self.clubs[name].strength() - 70) * 24) - 45 * int(table_pressure))
            if self.coach.points >= required:
                offers.append(JobOffer(league_key, name, required))
        return sorted(offers, key=lambda o: (-o.required_points, o.club))

    def _switch_account(self, name: str) -> None:
        old, new = club_key(self.managed), club_key(name)
        self.market.club_funds[old] = self.market.balance
        self.market.balance = self.market.club_funds.pop(new)
        self.club_ledgers[old] = self.market.ledger
        self.market.ledger = self.club_ledgers.pop(new, [])
        self.academies[old] = self.academy
        self.academy = self.academies.pop(new, CareerAcademy())
        self.managed = name

    def accept_job(self, offer: JobOffer) -> None:
        if offer not in self.job_offers(offer.league):
            raise ValueError("Esa oferta no está disponible para tu entrenador.")
        if self.finished:
            self.new_season(offer)
            return
        self._switch_account(offer.club)
        for draw in self.draws.values():
            if team := next((t for t in draw.teams if t.name == self.managed), None):
                draw.user_team = team
                draw.user_eliminated = bool(
                    draw.champion is None and draw.step_type() != "liga" and draw.step_idx
                    and not any(team is t for pair in draw.pairs for t in pair)
                )
        self._appoint()

    def new_season(self, offer: JobOffer | None = None) -> WorldSeasonRecord:
        record = self.season_record()
        if offer is not None and offer not in self.job_offers(offer.league):
            raise ValueError("Esa oferta ya no está disponible.")
        tables = {
            key: ([(t.name, self.league.table[t.name]["pts"]) for t in self.league.standings()]
                  if key == self.division else background_table(spec, self.clubs, self.year))
            for key, spec in self.leagues.items()
        }
        movements = dict(tables)
        if B in movements:
            movements[B] = bracket_order(tables[B], self.draws.get(B), self.clubs, self.year)
        next_leagues = apply_promotions(self.leagues, self.links, movements)
        name, origin = (offer.club, offer.league) if offer else (self.managed, self.division)
        legal = {origin} | {x.upper for x in self.links if x.lower == origin} | {
            x.lower for x in self.links if x.upper == origin
        }
        division = next(key for key, spec in next_leagues.items() if key in legal and name in spec.club_names)
        qualifiers = brazilian_qualifiers(tables[A], self.draws.get("copa_do_brasil")) if A in tables else None
        draws = start_draws(next_leagues, self.clubs, division, name, self.year + 1, qualifiers)
        league = draws[division]
        if self.employed:
            minimum_games = max(1, min(4, self.league.rounds_count // 4))
            if min(self.coach.tenure_matches, self.coach.season_matches) >= minimum_games:
                self.coach.complete_season(record.place <= record.objective, record.champion)
            if offer is not None:
                self.coach.leave(self.year, self.day, self.elapsed, self.managed, self.league.TITLE, "Cambio de club")
        if offer is not None:
            self._close_club_talks()
            self._switch_account(name)
        self.year, self.day = self.year + 1, 0
        self.negotiations.offered_windows.clear()
        self.fitness.records = {team: live for team, records in self.fitness.records.items() if (
            live := {n: c for n, c in records.items() if c.recovery > self.elapsed or self.elapsed - c.day < 14}
        )}
        self.coach.season_matches = 0
        self.closed_seasons.append(record)
        self.world_tables, self.leagues = tables, next_leagues
        self.division, self.draws = division, draws
        self.negotiations.tick(self)
        self.processed_windows.clear()
        if offer is not None:
            self._appoint()
        elif self.employed:
            rank = sorted(league.teams, key=lambda t: -t.strength()).index(league.user_team)
            self.board_target = min(len(league.teams), rank + 3)
        if self.employed:
            grant = budget_for(self.club) // 4
            self.market.post(self.year, self.day, "Presupuesto de la nueva temporada", grant)
            self.notify(f"Temporada {self.year}: {self.league.TITLE}. La directiva abonó un nuevo presupuesto.")
        for key, funds in self.market.club_funds.items():
            self.market.club_funds[key] = funds + max(200_000, funds // 10)
        for message in self.academy.advance(self.year, self.elapsed):
            self.notify(message)
        return record

    def _club_snapshots(self) -> list[dict[str, Any]]:
        return [t.to_dict() for name, t in self.clubs.items() if name not in self.stock or name in self.touched]

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "draws": [encode_draw(draw) for draw in self.draws.values()],
            "leagues": [spec.to_dict() for spec in self.leagues.values()],
            "links": [asdict(x) for x in self.links], "stock": [asdict(x) for x in self.stock.values()],
            "coach": self.coach.to_dict(), "closed_seasons": [asdict(x) for x in self.closed_seasons],
            "world_tables": {key: [list(row) for row in table] for key, table in self.world_tables.items()},
            "academies": {k: v.to_dict() for k, v in self.academies.items()},
            "club_ledgers": {k: [asdict(x) for x in v] for k, v in self.club_ledgers.items()},
            "processed_windows": sorted(self.processed_windows), "board_target": self.board_target,
            "fitness": self.fitness.to_dict(), "negotiations": self.negotiations.to_dict(),
            "match_logs": [asdict(log) for log in self.match_logs],
            "substitution_plans": {name: [asdict(r) for r in rules] for name, rules in self.substitution_plans.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldCareer:
        if data.get("career_schema") != cls.SCHEMA:
            raise ValueError("Unknown world career save schema.")
        leagues = {spec.key: spec for spec in map(WorldLeagueSpec.from_dict, data["leagues"])}
        stock = {seed.name: seed for seed in (ClubSeed(**row) for row in data["stock"])}
        edits = {team.name: team for team in map(Team.from_dict, data["clubs"])}
        clubs = {n: seed.generate() for n, seed in stock.items() if n not in edits} | edits
        division, name, year, day = (data[k] for k in ("division", "managed", "year", "day"))
        if not FIRST_YEAR <= year < 9999 or not 0 <= day < SEASON_DAYS or name not in clubs:
            raise ValueError("Invalid world career date or club.")
        if any(not set(spec.club_names) <= clubs.keys() for spec in leagues.values()):
            raise ValueError("Invalid world career participants.")
        draws = {raw["type"]: restore_draw(raw, leagues, year) for raw in data["draws"]}
        if division not in draws or draws[division].user_team.name != name or not 1 <= len(draws) <= 3:
            raise ValueError("Invalid active world career league.")
        market = CareerMarket.from_dict(data["market"])
        if market.balance < 0 or market.club_funds.keys() != {club_key(n) for n in clubs if n != name}:
            raise ValueError("Invalid world career budgets.")
        return cls(
            name, division, clubs, draws, market, CareerAcademy.from_dict(data["academy"]), year, day,
            inbox=[CareerMessage(**m) for m in data["inbox"]], unread=data["unread"],
            leagues=leagues, links=[DivisionLink(**x) for x in data["links"]], stock=stock,
            coach=ManagerProfile.from_dict(data["coach"]), touched=set(edits),
            closed_seasons=[WorldSeasonRecord(**r) for r in data["closed_seasons"]],
            world_tables={key: [tuple(row) for row in table] for key, table in data["world_tables"].items()},
            academies={k: CareerAcademy.from_dict(v) for k, v in data["academies"].items()},
            club_ledgers={k: [LedgerEntry(**x) for x in v] for k, v in data["club_ledgers"].items()},
            processed_windows=set(data["processed_windows"]), board_target=data["board_target"],
            fitness=CareerFitness.from_dict(data.get("fitness", {})),
            negotiations=TransferDesk.from_dict(data.get("negotiations", {})),
            match_logs=[MatchLog(**row) for row in data.get("match_logs", [])][-200:],
            substitution_plans={name: [ConditionalChange(**r) for r in rules]
                                for name, rules in data.get("substitution_plans", {}).items()},
        )
