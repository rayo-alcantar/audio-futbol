"""Transfer conversations advance on simulated dates, never wall-clock time."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from random import Random
from typing import TYPE_CHECKING

from audiofutbol.domain.competitions.career_recruitment import demands, spending_ceiling
from audiofutbol.domain.competitions.career_squad import can_release, can_sign, club_key
from audiofutbol.domain.models import Player, Team

if TYPE_CHECKING:
    from audiofutbol.domain.competitions.world_career import WorldCareer

OPEN = frozenset(("pending", "counter", "offered", "agreed"))
MAX_ROUNDS = 3


@dataclass
class TransferTalk:
    id: int
    club: str
    seller: str
    buyer: str
    player: str
    amount: int
    expires: int
    response_due: int = 0
    rounds: int = 0
    state: str = "pending"
    reason: str = ""

    @property
    def buying(self) -> bool:
        return self.club == self.buyer


@dataclass
class TransferDesk:
    talks: list[TransferTalk] = field(default_factory=list)
    next_id: int = 1
    offered_windows: set[str] = field(default_factory=set)

    def for_club(self, name: str) -> list[TransferTalk]:
        return [talk for talk in self.talks if talk.club == name]

    def _finish(self, career: WorldCareer, talk: TransferTalk, state: str, reason: str) -> None:
        talk.state, talk.reason = state, reason
        career.notify(f"Fichajes. {talk.player}: {reason}")

    def _check(self, career: WorldCareer, talk: TransferTalk) -> tuple[Team, Team, Player]:
        if not career.employed or talk.club != career.managed or talk not in self.talks:
            raise ValueError("Esta negociación no corresponde a tu club actual.")
        seller, buyer = career.clubs[talk.seller], career.clubs[talk.buyer]
        player = next((p for p in seller.players if p.name == talk.player), None)
        if (player is None or not can_release(seller, player)
                or not can_sign(buyer, player.name) or career.fitness.is_injured(seller, player, career.elapsed)):
            raise ValueError("El jugador no está disponible para este traspaso.")
        return seller, buyer, player

    def _deadline(self, career: WorldCareer) -> int:
        career._check_window()
        last_day = 299 if career.finished else (26 if career.day <= 26 else 156)
        return career.elapsed + last_day - career.day

    def _add(
        self, career: WorldCareer, seller: Team, buyer: Team, player: Player, amount: int, state: str,
    ) -> TransferTalk:
        if len([t for t in self.for_club(career.managed) if t.state in OPEN]) >= 8:
            raise ValueError("Ya tienes ocho negociaciones abiertas.")
        if any(t.player == player.name and t.seller == seller.name and t.state in OPEN
               for t in self.for_club(career.managed)):
            raise ValueError("Ya hay una negociación abierta por este jugador.")
        deadline = min(self._deadline(career), career.elapsed + (7 if state == "pending" else 5))
        talk = TransferTalk(self.next_id, career.managed, seller.name, buyer.name, player.name,
                            amount, deadline, career.elapsed + 2 if state == "pending" else 0, 1, state)
        self._check_squads(career, seller, buyer, player)
        if state == "pending" and talk.response_due > deadline:
            raise ValueError("No hay tiempo para responder antes del cierre de la ventana.")
        self.next_id += 1
        self.talks = [*self.talks[-199:], talk]
        return talk

    @staticmethod
    def _check_squads(career: WorldCareer, seller: Team, buyer: Team, player: Player) -> None:
        if (not can_release(seller, player) or not can_sign(buyer, player.name)
                or career.fitness.is_injured(seller, player, career.elapsed)):
            raise ValueError("El traspaso no es viable por plantilla o lesión.")

    def bid(self, career: WorldCareer, seller: Team, player: Player, amount: int) -> TransferTalk:
        if seller is career.club or career.clubs.get(seller.name) is not seller:
            raise ValueError("El vendedor debe ser otro club.")
        if not 0 < amount <= career.market.balance:
            raise ValueError("La oferta debe estar dentro de tu presupuesto.")
        return self._add(career, seller, career.club, player, amount, "pending")

    def counter(self, career: WorldCareer, talk: TransferTalk, amount: int) -> None:
        career._check_window()
        self._check(career, talk)
        if talk.state not in ("offered", "counter") or talk.rounds >= MAX_ROUNDS:
            raise ValueError("No queda margen para otra contraoferta.")
        if (talk.buying and not 0 < amount <= career.market.balance
                or not talk.buying and not 0 < amount <= 2_000_000_000):
            raise ValueError("El importe no es válido para esa contraoferta.")
        reply = career.elapsed + 2
        if reply > talk.expires:
            raise ValueError("No hay tiempo para otra respuesta antes del vencimiento.")
        talk.amount, talk.response_due, talk.state, talk.rounds = amount, reply, "pending", talk.rounds + 1

    def close(self, career: WorldCareer, talk: TransferTalk) -> None:
        career._check_window()
        if talk.state not in ("offered", "counter", "agreed") or career.elapsed > talk.expires:
            raise ValueError("La oferta ya no se puede cerrar.")
        seller, buyer, player = self._check(career, talk)
        career.market.transfer(user=career.club, seller=seller, buyer=buyer, player=player,
                               fee=talk.amount, year=career.year, day=career.day)
        career.fitness.move_player(seller, buyer, player.name)
        career.refresh_clubs(seller, buyer)
        self._finish(career, talk, "closed", f"traspaso confirmado entre {seller.name} y {buyer.name}.")

    def withdraw(self, career: WorldCareer, talk: TransferTalk) -> None:
        if talk not in self.talks or talk.club != career.managed or talk.state not in OPEN:
            raise ValueError("No hay una oferta abierta para retirar.")
        self._finish(career, talk, "withdrawn", "la negociación se retiró sin mover dinero.")

    def _respond(self, career: WorldCareer, talk: TransferTalk) -> None:
        try:
            seller, buyer, player = self._check(career, talk)
        except ValueError as exc:
            self._finish(career, talk, "rejected", str(exc))
            return
        if talk.buying:
            limit = demands(player, seller, buyer, career.year)
            if talk.amount >= limit:
                self._finish(career, talk, "agreed", f"{seller.name} acepta tu oferta; falta tu confirmación.")
            elif talk.amount >= limit * (.73 + .03 * talk.rounds):
                talk.amount = round(limit * .96)
                self._finish(career, talk, "counter", f"{seller.name} envió una contraoferta.")
            else:
                self._finish(career, talk, "rejected", f"{seller.name} considera que el importe es demasiado bajo.")
        else:
            funds = career.market.club_funds[club_key(buyer.name)]
            limit = spending_ceiling(player, buyer, funds, career.year)
            if 0 < talk.amount <= limit:
                self._finish(career, talk, "agreed", f"{buyer.name} acepta tu contraoferta; falta tu confirmación.")
            elif talk.amount <= limit * 1.28 and limit > 0:
                talk.amount = limit
                self._finish(career, talk, "counter", f"{buyer.name} hizo su última propuesta.")
            else:
                self._finish(career, talk, "rejected", f"{buyer.name} no pagará ese importe.")

    def tick(self, career: WorldCareer) -> None:
        for talk in self.for_club(career.managed):
            if talk.state not in OPEN:
                continue
            if not career.employed or career.elapsed > talk.expires or not career.window:
                self._finish(career, talk, "expired", "venció la oferta; no se movió dinero.")
            elif talk.state == "pending" and talk.response_due <= career.elapsed:
                self._respond(career, talk)
        if not career.employed or career.window is None:
            return
        block = f"{career.year}:{career.window}:{career.managed}:{career.day // 7}"
        if block in self.offered_windows:
            return
        self.offered_windows.add(block)
        self._make_offer(career, Random(block))

    def _make_offer(self, career: WorldCareer, rng: Random) -> None:
        # Domestic clubs know the league well; interest still needs a real squad need and budget.
        country = career.leagues[career.division].country
        candidates = [t for t in career.clubs.values() if t is not career.club and t.country == country]
        players = rng.sample(career.club.players, len(career.club.players))
        for player in players:
            if (not can_release(career.club, player)
                    or career.fitness.is_injured(career.club, player, career.elapsed)):
                continue
            pool = []
            for buyer in candidates:
                cap = spending_ceiling(player, buyer, career.market.club_funds[club_key(buyer.name)], career.year)
                if cap >= demands(player, career.club, buyer, career.year) * .62 and can_sign(buyer, player.name):
                    pool.append((buyer, cap))
            if not pool:
                continue
            buyer, cap = max(pool, key=lambda t: t[1])
            try:
                talk = self._add(career, career.club, buyer, player, int(cap * rng.uniform(.77, .87)), "offered")
            except ValueError:
                continue
            career.notify(f"Fichajes. {buyer.name} ofrece por {talk.player}; puedes responder en Negociaciones.")
            return

    def to_dict(self) -> dict:
        return {"talks": [asdict(t) for t in self.talks], "next_id": self.next_id,
                "offered_windows": sorted(self.offered_windows)}

    @classmethod
    def from_dict(cls, data: dict) -> TransferDesk:
        return cls([TransferTalk(**t) for t in data.get("talks", [])], data.get("next_id", 1),
                   set(data.get("offered_windows", [])))
