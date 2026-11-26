"""Load the audited world data without changing the ordinary game club catalogue."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import logging

from audiofutbol.data.club_pool import build_club_pool
from audiofutbol.data.creations import CreationLibrary, catalogue_ref, resolve_tournament
from audiofutbol.domain.competitions.career_squad import club_key, season_copy
from audiofutbol.domain.competitions.career_world_catalog import ClubSeed, DivisionLink, WorldLeagueSpec
from audiofutbol.domain.creations import TournamentDraft
from audiofutbol.domain.models import Team
from audiofutbol.engine.paths import AppPaths

logger = logging.getLogger(__name__)
_CLUB_SUFFIXES = {"fc", "cf", "sc", "ac", "afc", "cd"}


@dataclass
class WorldCatalogue:
    leagues: dict[str, WorldLeagueSpec]
    links: list[DivisionLink]
    stock: dict[str, ClubSeed]
    rosters: dict[str, Team]

    def selectable(self, key: str) -> list[Team]:
        return [self.rosters[name] if name in self.rosters else self.stock[name].generate()
                for name in self.leagues[key].club_names]


def _alias(name: str) -> str:
    return " ".join(w for w in club_key(name).replace(".", "").split() if w not in _CLUB_SUFFIXES)


def load_world_catalogue(paths: AppPaths, *, custom: bool = True) -> WorldCatalogue:
    root = paths.competitions_dir / "carrera"
    try:
        systems = json.loads((root / "ligas.json").read_text(encoding="utf-8"))
        entries = {e["id"]: e for e in json.loads((root / "clubes.json").read_text(encoding="utf-8"))}
        return _assemble(paths, systems, entries, custom=custom)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("No se pudo leer un catálogo mundial de carrera válido.") from exc


def _assemble(paths: AppPaths, systems: list, entries: dict, *, custom: bool) -> WorldCatalogue:
    catalogue = build_club_pool(paths)
    exact = {club_key(t.name): t for t in catalogue if t.is_real_squad}
    aliases: dict[tuple[str, str], list[Team]] = {}
    for team in exact.values():
        aliases.setdefault((club_key(team.country), _alias(team.name)), []).append(team)
    duplicated = Counter(club_key(t["nombre"]) for t in entries.values())
    regions = {s["name"]: s["region"] for s in systems}
    names: dict[str, str] = {}
    used_names: set[str] = set()
    seeds: dict[str, ClubSeed] = {}
    rosters: dict[str, Team] = {}
    stock_by_roster: dict[str, str] = {}
    for uid, entry in entries.items():
        name, country = entry["nombre"], entry["pais"]
        if duplicated[club_key(name)] > 1:
            name = f"{name} ({country})"
        if club_key(name) in used_names:
            name = f"{name}, {uid.replace('_', ' ')}"
        used_names.add(club_key(name))
        names[uid] = name
        team = exact.get(club_key(entry["nombre"])) or exact.get(club_key(entry.get("squad_alias", "")))
        if team and team.country and club_key(team.country) != club_key(country):
            team = None
        if team is None:
            options = aliases.get((club_key(country), _alias(entry["nombre"])), [])
            team = options[0] if len(options) == 1 else None
        seed = ClubSeed(uid, name, country, regions.get(country, ""), int(entry["nivel"]),
                        entry.get("estadio"), entry.get("ciudad", ""))
        if team is None or len(team.players) < 11:
            seeds[name] = seed
        else:
            roster = season_copy(team)
            roster.name, roster.team_id, roster.country = name, uid, country
            roster.stadium, roster.city = (team.stadium or seed.stadium), (team.city or seed.city)
            rosters[name] = roster
            stock_by_roster[club_key(team.name)] = name

    leagues: dict[str, WorldLeagueSpec] = {}
    links: list[DivisionLink] = []
    for system in systems:
        country, region = system["name"], system["region"]
        slug = club_key(country).replace(" ", "_")
        stack = []
        for tier, item in enumerate(system["leagues"], start=1):
            key = f"world:{slug}:{tier}"
            field = tuple(names[uid] for uid in item["participants"])
            if len(field) < 4 or len(field) != len(set(field)):
                raise ValueError("Invalid league field.")
            stack.append(key)
            leagues[key] = WorldLeagueSpec(key, item["name"], country, region, field, 1 + item["format"], item["season"])
        for index, places in enumerate(system["promotion_places"]):
            if places and index + 1 < len(stack):
                links.append(DivisionLink(stack[index], stack[index + 1], int(places)))
    if custom:
        _add_creation_leagues(paths, catalogue, leagues, seeds, rosters, stock_by_roster)
    return WorldCatalogue(leagues, links, seeds, rosters)


def _add_creation_leagues(paths, catalogue, leagues, seeds, rosters, known) -> None:
    try:
        library = CreationLibrary(paths.saves_dir / "creaciones" / "biblioteca.json")
    except (OSError, ValueError):
        logger.warning("Could not open creation library for the world career.")
        return
    references = {catalogue_ref(team).key: team for team in catalogue}
    drafts = library.custom_teams()
    draft_ids = {draft.id for draft in drafts.values()}
    used = {club_key(n) for n in [*seeds, *rosters]}
    for draft in library.drafts.values():
        if not isinstance(draft, TournamentDraft) or draft.kind != "club" or draft.format != "liga":
            continue
        try:
            field = resolve_tournament(draft, references, drafts)
        except ValueError:
            continue
        participants = []
        for team in field:
            normalized = club_key(team.name)
            identity = team.team_id if team.team_id in draft_ids else normalized
            name = known.get(identity)
            if not name:
                name = team.name
                if normalized in used:
                    name = f"{name} (Creaciones)"
                if club_key(name) in used:
                    name += f" {team.team_id[:8]}"
                used.add(club_key(name))
                rosters[name] = season_copy(team)
                rosters[name].name = name
                known[identity] = name
            participants.append(name)
        if len(participants) != len(set(participants)):
            continue
        key = f"creation:{draft.id}"
        leagues[key] = WorldLeagueSpec(key, draft.name, "Ligas del Creador", "Creaciones",
                                       tuple(participants), draft.rounds)
