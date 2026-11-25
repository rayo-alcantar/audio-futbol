"""Competition JSON and stadium directory loader."""

from __future__ import annotations

import json
from typing import Any

from audiofutbol.data.csv_loader import (
    create_generic_team,
    load_club_players,
    select_squad,
)
from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS, ClubCompetitionSpec
from audiofutbol.domain.models import Team
from audiofutbol.domain.text import normalize_text
from audiofutbol.engine.paths import AppPaths

LIBERTADORES_SOUTH = "libertadores_sur"


class StadiumDirectory:
    """Resolves (stadium, city) for clubs and national teams."""

    def __init__(self, paths: AppPaths) -> None:
        self._national: dict[str, tuple[str, str]] = {}
        self._load_national(paths)

    def _load_national(self, paths: AppPaths) -> None:
        target = paths.competitions_dir / "estadios_selecciones.json"
        if not target.is_file():
            return
        try:
            with target.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            for name, val in data.get("selecciones", {}).items():
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    self._national[normalize_text(name).strip()] = (
                        str(val[0]),
                        str(val[1]),
                    )
        except Exception:
            pass

    def venue_for(self, team: Team) -> tuple[str, str] | None:
        if team.stadium:
            return team.stadium, team.city
        return self._national.get(normalize_text(team.name).strip())


def team_from_entry(entry: dict[str, Any], real_clubs: dict[str, dict[str, Any]]) -> Team:
    """Build a club `Team` from a competition JSON entry (real squad if the CSV has one)."""
    squad_map = real_clubs.get(normalize_text(entry["nombre"]).strip()) or real_clubs.get(
        normalize_text(entry["id"]).strip()
    )
    level = int(entry.get("nivel", 72))
    if squad_map and len(squad_map) >= 11:
        squad = select_squad(squad_map.values())
        return Team(
            name=entry["nombre"],
            players=squad,
            team_id=entry["id"],
            country=entry.get("pais", ""),
            stadium=entry.get("estadio"),
            city=entry.get("ciudad", ""),
            group=entry.get("grupo"),
            level=level,
            is_real_squad=True,
        )
    team = create_generic_team(entry["nombre"], level)
    team.team_id = entry["id"]
    team.country = entry.get("pais", "")
    team.stadium = entry.get("estadio")
    team.city = entry.get("ciudad", "")
    team.group = entry.get("grupo")
    team.is_real_squad = False
    return team


def load_competition_data(
    paths: AppPaths, json_filename: str
) -> tuple[dict[str, Any] | None, dict[str, Team] | None]:
    """Read `competiciones/<json_filename>` and instantiate club `Team` objects."""
    target = paths.competitions_dir / json_filename
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None, None

    real_clubs = load_club_players(paths)
    teams_by_id: dict[str, Team] = {}
    for entry in data.get("equipos", []):
        teams_by_id[entry["id"]] = team_from_entry(entry, real_clubs)

    return data, teams_by_id


def load_registered_club_field(
    paths: AppPaths, key: str
) -> tuple[ClubCompetitionSpec, dict[str, Any], dict[str, Team]]:
    """Resolve a registered field once, whether launching or creating a preview."""
    if key == LIBERTADORES_SOUTH:
        spec = CLUB_COMPETITIONS["libertadores"]
        filename = "libertadores_2026.json"
    else:
        spec = CLUB_COMPETITIONS[key]
        filename = spec.json_filename
    data, teams = load_competition_data(paths, filename)
    if data is None or not teams:
        raise ValueError(f"No encontré el archivo {filename} en la carpeta competiciones.")
    return spec, data, teams
