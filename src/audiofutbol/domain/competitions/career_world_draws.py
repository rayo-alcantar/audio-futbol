"""World career draw formats, including the Brazilian pyramid and cups."""

from __future__ import annotations

from random import Random

from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.career_brazil_cup import CopaDoBrasil
from audiofutbol.domain.competitions.career_brazil_rules import CONTINENTAL_TYPES
from audiofutbol.domain.competitions.career_simulation import expected_goals, poisson, profile
from audiofutbol.domain.competitions.career_squad import club_key, season_copy
from audiofutbol.domain.competitions.career_world_catalog import WorldLeagueSpec
from audiofutbol.domain.competitions.career_world_league import WorldLeague
from audiofutbol.domain.competitions.club_tournaments import ClubTournament
from audiofutbol.domain.models import Team

A, B, C = (f"world:brasil:{i}" for i in (1, 2, 3))
BRAZIL = (A, B, C)
_NATIVE = {A: BrasileiraoA, B: BrasileiraoB}
_CUPS = {CopaDoBrasil.KEY: CopaDoBrasil, **CONTINENTAL_TYPES}
_SOUTH = {"argentina", "bolivia", "chile", "colombia", "ecuador", "paraguay",
          "peru", "uruguay", "venezuela"}


def start_draws(
    leagues: dict[str, WorldLeagueSpec], clubs: dict[str, Team], division: str, name: str, year: int,
    continental: dict[str, list[str]] | None = None,
) -> dict[str, ClubTournament]:
    spec = leagues[division]
    if division in _NATIVE:
        field = {n: season_copy(clubs[n]) for n in spec.club_names}
        league = _NATIVE[division](None, field, field[name])
        league.KEY, league.TITLE = division, spec.title
    else:
        league = WorldLeague.start(spec, clubs, name, year)
    draws = {division: league}
    if division not in BRAZIL or not all(key in leagues for key in BRAZIL):
        return draws
    teams = [season_copy(clubs[n]) for key in BRAZIL for n in leagues[key].club_names]
    cup = CopaDoBrasil(teams, next(t for t in teams if t.name == name))
    draws[cup.KEY] = cup
    for key, qualifiers in (continental or {}).items():
        if name not in qualifiers:
            continue
        external = list(dict.fromkeys(n for s in leagues.values() if club_key(s.country) in _SOUTH
                                      for n in s.club_names if club_key(clubs[n].country) in _SOUTH))
        rng = Random(f"continental:{year}:{key}")
        rng.shuffle(external)
        external.sort(key=lambda n: -(clubs[n].level + rng.uniform(-6, 6)))
        names = [*qualifiers, *external][:32]
        if len(names) == 32:
            field = {n: season_copy(clubs[n]) for n in names}
            draws[key] = CONTINENTAL_TYPES[key](None, field, field[name])
    return draws


def encode_draw(draw: ClubTournament) -> dict:
    raw = draw.to_dict()
    if isinstance(draw, (BrasileiraoA, BrasileiraoB)):
        raw["native_brazil"] = True
    return raw


def restore_draw(raw: dict, leagues: dict[str, WorldLeagueSpec], year: int) -> ClubTournament:
    key = raw["type"]
    if key in _CUPS:
        return _CUPS[key].from_dict(raw)
    spec = leagues[key]
    if raw.get("native_brazil"):
        draw = _NATIVE[key].from_dict(raw)
        if {t.name for t in draw.teams} != set(spec.club_names):
            raise ValueError("Invalid Brazilian league participants.")
        draw.KEY, draw.TITLE = key, spec.title
        return draw
    return WorldLeague.restore(spec, raw, year)


def bracket_order(
    table: list[tuple[str, int]], draw: ClubTournament | None, clubs: dict[str, Team], year: int,
) -> list[tuple[str, int]]:
    if len(table) < 6:
        return table
    if isinstance(draw, BrasileiraoB) and draw.ties:
        promoted = {draw.tie_winner(tie).name for tie in draw.ties}
    else:
        rng = Random(f"série-b-playoffs:{year}")
        promoted = set()
        for higher, lower in ((2, 5), (3, 4)):
            a, b = (clubs[table[i][0]] for i in (higher, lower))
            ap, bp = profile(a, a.lineup(ignore_suspensions=True)), profile(b, b.lineup(ignore_suspensions=True))
            ga, gb = expected_goals(ap, bp)
            gbr, gar = expected_goals(bp, ap)
            promoted.add(b.name if poisson(rng, gb + gbr) > poisson(rng, ga + gar) else a.name)
    return table[:2] + [row for row in table[2:6] if row[0] in promoted] + [
        row for row in table[2:] if row[0] not in promoted
    ]


def brazilian_qualifiers(table: list[tuple[str, int]], cup: ClubTournament | None) -> dict[str, list[str]]:
    order = [name for name, _ in table]
    first = order[:5]
    if cup is not None and cup.champion is not None and cup.champion.name not in first:
        first.append(cup.champion.name)
    return {"libertadores": first, "sudamericana": [n for n in order if n not in first][:6]}
