"""Negotiation and an auditable budget for the manager career."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from audiofutbol.domain.competitions.career_squad import can_release, can_sign, club_key, sign_player
from audiofutbol.domain.models import Player, Team


def starting_budget(team: Team) -> int:
    return round(12_000_000 * max(.35, min(4.0, 1.09 ** (team.level - 72))))


def transfer_value(player: Player) -> int:
    rating = max(0, player.overall - 48)
    elite = max(0, player.overall - 78)
    return max(150_000, round((rating ** 2 * 4_000 + elite ** 3 * 18_000) / 10_000) * 10_000)


def negotiate(player: Player, bid: int) -> tuple[str, int]:
    asking = transfer_value(player)
    if bid * 100 >= asking * 95:
        return "accepted", bid
    if bid * 100 >= asking * 72:
        return "counter", asking * 94 // 100
    return "rejected", 0


@dataclass(frozen=True)
class LedgerEntry:
    year: int
    day: int
    reason: str
    amount: int
    balance: int


@dataclass
class CareerMarket:
    balance: int
    club_funds: dict[str, int]
    ledger: list[LedgerEntry] = field(default_factory=list)

    @classmethod
    def start(cls, club: Team, clubs: list[Team]) -> CareerMarket:
        return cls(starting_budget(club), {
            club_key(t.name): starting_budget(t) for t in clubs if t is not club
        })

    def post(self, year: int, day: int, reason: str, amount: int) -> None:
        if self.balance + amount < 0:
            raise ValueError("El presupuesto no alcanza para esta operación.")
        self.balance += amount
        self.ledger.append(LedgerEntry(year, day, reason, amount, self.balance))

    def offer_for_sale(self, player: Player, seller: Team, clubs: list[Team]) -> tuple[Team, int] | None:
        if not can_release(seller, player):
            return None
        price = transfer_value(player) * 85 // 100
        buyers = [
            t for t in clubs if t is not seller and can_sign(t, player.name)
            and self.club_funds[club_key(t.name)] >= price
        ]
        if not buyers:
            return None
        buyer = min(buyers, key=lambda t: (
            sum(p.position == player.position for p in t.players), club_key(t.name),
        ))
        return buyer, price

    def transfer(
        self, *, user: Team, seller: Team, buyer: Team, player: Player,
        fee: int, year: int, day: int,
    ) -> Player:
        buying = buyer is user
        other = seller if buying else buyer
        key = club_key(other.name)
        funds = self.balance if buying else self.club_funds[key]
        if fee <= 0 or fee > funds:
            raise ValueError("El comprador no tiene presupuesto suficiente.")
        if not can_release(seller, player):
            raise ValueError("El club no puede liberar al jugador sin debilitar su plantilla.")
        signed = sign_player(buyer, player)
        seller.players = [p for p in seller.players if p is not player]
        self.club_funds[key] += fee if buying else -fee
        reason = f"Fichaje de {player.name} desde {seller.name}" if buying else f"Venta de {player.name} a {buyer.name}"
        self.post(year, day, reason, -fee if buying else fee)
        return signed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CareerMarket:
        return cls(data["balance"], dict(data["club_funds"]), [LedgerEntry(**x) for x in data["ledger"]])
