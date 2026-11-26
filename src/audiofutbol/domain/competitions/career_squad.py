"""Career-only squad operations; competition statistics remain on their own copies."""

from __future__ import annotations

from dataclasses import replace

from audiofutbol.domain.models import Player, Team
from audiofutbol.domain.text import normalize_text

MAX_SQUAD = 35
MIN_SQUAD = 16
DEPTH = {"POR": 2, "DEF": 4, "MED": 3, "DEL": 2}


def club_key(name: str) -> str:
    return normalize_text(name).strip()


def can_release(team: Team, player: Player) -> bool:
    return (
        any(p is player for p in team.players)
        and len(team.players) > MIN_SQUAD
        and sum(p.position == player.position for p in team.players) > DEPTH[player.position]
    )


def can_sign(team: Team, name: str) -> bool:
    return len(team.players) < MAX_SQUAD and all(club_key(p.name) != club_key(name) for p in team.players)


def clean_player(player: Player, number: int | None = None) -> Player:
    return replace(
        player, number=player.number if number is None else number,
        goals=0, assists=0, yellow_cards=0, suspended_matches=0, medically_unavailable=False,
    )


def sign_player(team: Team, player: Player) -> Player:
    if not can_sign(team, player.name):
        raise ValueError("La plantilla está llena o ya tiene un jugador con ese nombre.")
    used = {p.number for p in team.players}
    number = player.number
    if number not in range(1, 100) or number in used:
        number = next(n for n in range(1, 100) if n not in used)
    signed = clean_player(player, number)
    team.players.append(signed)
    return signed


def copy_tactics(source: Team, target: Team) -> None:
    names = {p.name for p in target.players}
    target.scheme = source.scheme
    target.mentality = source.mentality
    target.lineup_names = [n for n in source.lineup_names or [] if n in names] or None
    target.positions = {n: pos for n, pos in source.positions.items() if n in names}
    target.takers = {kind: n for kind, n in source.takers.items() if n in names}


def refresh_squad(source: Team, target: Team) -> None:
    """Keep the receiving competition's player identities, tallies and sanctions."""
    existing = {p.name: p for p in target.players}
    players = []
    for player in source.players:
        local = existing.get(player.name)
        if local is None:
            local = clean_player(player)
        local.overall, local.number = player.overall, player.number
        players.append(local)
    target.players = players
    copy_tactics(source, target)


def season_copy(team: Team) -> Team:
    copied = replace(team, players=[clean_player(p) for p in team.players], group=None)
    copy_tactics(team, copied)
    return copied
