"""Career search filters and transfer valuations independent of the screen."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from audiofutbol.domain.competitions.career_core import FIRST_YEAR
from audiofutbol.domain.competitions.career_market import transfer_value
from audiofutbol.domain.competitions.career_squad import DEPTH, MIN_SQUAD, club_key
from audiofutbol.domain.models import Player, Team


def player_age(player: Player, year: int) -> tuple[int, bool]:
    if player.birth_year is not None:
        return year - player.birth_year, False
    rng = Random(f"career-age-v1:{club_key(player.name)}:{player.position}")
    start = round(rng.triangular(18, 36, 25)) + int(player.position == "POR")
    return start + year - FIRST_YEAR, True


def estimate_price(player: Player, year: int) -> int:
    age, _ = player_age(player, year)
    if age <= 22:
        factor = 1.18
    elif age <= 28:
        factor = 1.0
    else:
        factor = max(.36, 1 - .075 * (age - 28))
    return max(80_000, round(transfer_value(player) * factor / 10_000) * 10_000)


def demands(player: Player, seller: Team, buyer: Team, year: int) -> int:
    position = [p.overall for p in seller.players if p.position == player.position]
    group_depth = len(position) - DEPTH[player.position]
    role = .13 if player.overall >= max(position) else .0
    rivalry = .07 if seller.country and seller.country == buyer.country else .0
    funds = .07 if buyer.level >= seller.level + 7 else .0
    return round(estimate_price(player, year) * (1 + role + rivalry + funds + (.14 if group_depth <= 1 else 0)))


def spending_ceiling(player: Player, buyer: Team, funds: int, year: int) -> int:
    position = sorted((p.overall for p in buyer.players if p.position == player.position), reverse=True)
    target = DEPTH[player.position]
    benchmark = position[min(target - 1, len(position) - 1)] if position else 44
    need = max(-.25, min(.37, (player.overall - benchmark) * .038 + (.12 if len(position) < target else 0)))
    return min(int(funds * .65), int(estimate_price(player, year) * (1.04 + need)))


@dataclass(frozen=True)
class RecruitmentFilter:
    name: str = ""
    club: str = ""
    league: str | None = None
    position: str | None = None
    min_age: int = 15
    max_age: int = 99
    min_overall: int = 1
    max_overall: int = 99
    affordable: bool = False


def search_players(career, filters: RecruitmentFilter) -> list[tuple[Team, Player, int]]:
    if filters.league is not None:
        names = career.leagues[filters.league].club_names
    else:
        names = career.clubs
    name, club = club_key(filters.name), club_key(filters.club)
    taken = {club_key(p.name) for p in career.club.players}
    candidates = []
    for seller_name in names:
        seller = career.clubs[seller_name]
        if seller is career.club or len(seller.players) <= MIN_SQUAD or club not in club_key(seller.name):
            continue
        depth = {k: sum(p.position == k for p in seller.players) for k in DEPTH}
        for player in seller.players:
            if ((filters.position and player.position != filters.position)
                    or not filters.min_overall <= player.overall <= filters.max_overall
                    or depth[player.position] <= DEPTH[player.position]):
                continue
            label = club_key(player.name)
            if label in taken or name not in label:
                continue
            if (filters.min_age, filters.max_age) != (15, 99):
                age, _ = player_age(player, career.year)
                if not filters.min_age <= age <= filters.max_age:
                    continue
            fee = demands(player, seller, career.club, career.year)
            if not filters.affordable or fee <= career.market.balance:
                candidates.append((seller, player, fee))
    candidates.sort(key=lambda row: (-row[1].overall, row[2], row[1].name, row[0].name))
    return candidates
