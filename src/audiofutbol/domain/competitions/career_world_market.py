"""World career finances and capacity-aware computer recruitment."""

from __future__ import annotations

from collections.abc import Callable
from random import Random

from audiofutbol.domain.competitions.career_market import CareerMarket, starting_budget, transfer_value
from audiofutbol.domain.competitions.career_squad import DEPTH, can_release, can_sign, club_key, sign_player
from audiofutbol.domain.models import Player, Team


def budget_for(team: Team) -> int:
    lift = 1.25 if team.level >= 80 else .78 if team.level < 65 else 1.
    return int(starting_budget(team) * lift)


def open_world_budget(club: Team, clubs: dict[str, Team], year: int) -> CareerMarket:
    other = {club_key(t.name): budget_for(t) for t in clubs.values() if t is not club}
    market = CareerMarket(0, other)
    market.post(year, 0, "Presupuesto inicial de la directiva", budget_for(club))
    return market


def _coverage(team: Team, position: str) -> float:
    ratings = sorted((p.overall for p in team.players if p.position == position), reverse=True)
    target = DEPTH[position]
    return (sum(ratings[:target]) + max(0, target - len(ratings)) * 42) / target


def recruit(
    market: CareerMarket, field: list[Team], protected_club: str, rng: Random,
    eligible: Callable[[Team, Player], bool] | None = None,
) -> list[tuple[Team, Team, str, int]]:
    """Make at most three transfers between funded NPC clubs, based on squad needs."""
    pool = [team for team in field if team.name != protected_club]
    deals = []
    used = set()
    for buyer in rng.sample(pool, len(pool)):
        if buyer.name in used:
            continue
        key = club_key(buyer.name)
        position = min(DEPTH, key=lambda p: _coverage(buyer, p))
        minimum = _coverage(buyer, position) + 1
        choices = []
        for seller in pool:
            if seller is buyer or seller.name in used:
                continue
            for player in seller.players:
                if (player.position != position or player.overall < minimum
                        or (eligible is not None and not eligible(seller, player))
                        or not can_release(seller, player) or not can_sign(buyer, player.name)):
                    continue
                price = transfer_value(player)
                if price <= market.club_funds[key] * .45:
                    choices.append((seller, player, price))
        if not choices:
            continue
        seller, player, price = max(choices, key=lambda item: (item[1].overall - item[2] / 2_000_000, -item[2]))
        sign_player(buyer, player)
        seller.players = [p for p in seller.players if p is not player]
        market.club_funds[key] -= price
        market.club_funds[club_key(seller.name)] += price
        used.update((buyer.name, seller.name))
        deals.append((buyer, seller, player.name, price))
        if len(deals) == 3:
            break
    return deals
