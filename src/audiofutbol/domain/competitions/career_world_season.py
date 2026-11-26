"""Simultaneous promotion and relegation between linked world divisions."""

from __future__ import annotations

from audiofutbol.domain.competitions.career_world_catalog import DivisionLink, WorldLeagueSpec


def apply_promotions(
    leagues: dict[str, WorldLeagueSpec],
    links: list[DivisionLink],
    tables: dict[str, list[tuple[str, int]]],
) -> dict[str, WorldLeagueSpec]:
    leaving: dict[str, set[str]] = {key: set() for key in leagues}
    arriving: dict[str, list[str]] = {key: [] for key in leagues}
    for link in links:
        upper, lower, places = link.upper, link.lower, link.places
        up = [name for name, _ in tables[lower][:places]]
        down = [name for name, _ in tables[upper][-places:]]
        if set(down) & leaving[upper] or set(up) & leaving[lower]:
            raise ValueError("Los cupos de ascenso y descenso se superponen.")
        leaving[upper].update(down)
        leaving[lower].update(up)
        arriving[upper].extend(up)
        arriving[lower].extend(down)
    return {
        key: spec.with_clubs([n for n in spec.club_names if n not in leaving[key]] + arriving[key])
        for key, spec in leagues.items()
    }
