"""Local creation library and portable data-only contribution packages."""

from __future__ import annotations

from dataclasses import asdict, replace
import csv
import ctypes
import io
import json
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from audiofutbol.domain.creations import (
    SCHEMA_VERSION, Draft, Placement, SquadPlayer, TeamDraft, TeamRef, TournamentDraft,
    new_id, team_key,
)
from audiofutbol.domain.formations import ROLES, preferred_role, puesto_from_text
from audiofutbol.domain.models import Team
from audiofutbol.engine.updater import GITHUB_REPO
from audiofutbol.version import VERSION

_MANIFEST = "aporte.json"
_MAX_PACKAGE = 2 * 1024 * 1024
_MAX_LIBRARY = 12 * _MAX_PACKAGE


def catalogue_ref(team: Team) -> TeamRef:
    return TeamRef(f"catalogo:{team_key(team.name)}", team.name)


def _items(data: dict, key: str, maximum: int) -> list:
    values = data.pop(key, [])
    if not isinstance(values, list) or len(values) > maximum:
        raise ValueError(f"El campo {key} no es válido.")
    return values


def _decode(raw: dict, *, ready: bool = False) -> Draft:
    try:
        if not isinstance(raw, dict) or not isinstance(raw.get("contenido"), dict):
            raise ValueError("La estructura del borrador no es válida.")
        data = raw["contenido"].copy()
        if raw["tipo"] == "equipo":
            players = tuple(SquadPlayer(**item) for item in _items(data, "players", 30))
            placements = tuple(Placement(**item) for item in _items(data, "placements", 40))
            draft: Draft = TeamDraft(**data, players=players, placements=placements)
        elif raw["tipo"] == "torneo":
            teams = tuple(TeamRef(**item) for item in _items(data, "teams", 64))
            draft = TournamentDraft(**data, teams=teams)
        else:
            raise ValueError("El paquete no contiene un equipo ni un torneo.")
        if "id" not in data:
            raise ValueError("Falta la identidad del borrador.")
        if errors := draft.issues(ready=ready):
            raise ValueError(errors[0])
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError("La estructura del borrador no es válida.") from exc
    return draft


def _encode(draft: Draft) -> dict:
    return {"tipo": "equipo" if isinstance(draft, TeamDraft) else "torneo", "contenido": asdict(draft)}


def _decode_json(blob: bytes) -> dict:
    try:
        data = json.loads(blob.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("No pude leer el archivo de datos en UTF-8.") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != SCHEMA_VERSION:
        raise ValueError("Esta versión del formato de creaciones no es compatible.")
    return data


def _read_limited(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        blob = handle.read(size + 1)
    if len(blob) > size:
        raise ValueError("El archivo supera el tamaño admitido.")
    return blob


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".creacion-", suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
    try:
        write(temp)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class CreationLibrary:
    """One atomic local library, separate from competition save slots."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.drafts: dict[str, Draft] = {}
        if path.exists():
            data = _decode_json(_read_limited(path, _MAX_LIBRARY))
            for draft in map(_decode, _items(data, "borradores", 1000)):
                if draft.id in self.drafts:
                    raise ValueError("Hay dos borradores con el mismo identificador.")
                self.drafts[draft.id] = draft

    def _save(self, drafts: dict[str, Draft]) -> None:
        if len(drafts) > 1000:
            raise ValueError("La biblioteca de creaciones está llena.")
        blob = json.dumps({"version": SCHEMA_VERSION, "borradores": list(map(_encode, drafts.values()))},
                          ensure_ascii=False, indent=2).encode("utf-8")
        if len(blob) > _MAX_LIBRARY:
            raise ValueError("La biblioteca de creaciones está llena.")
        _atomic_write(self.path, lambda path: path.write_bytes(blob))
        self.drafts = drafts

    def save(self, draft: Draft) -> None:
        if errors := draft.issues(ready=False):
            raise ValueError(errors[0])
        self._save({**self.drafts, draft.id: draft})

    def remove(self, draft: Draft) -> None:
        if isinstance(draft, TeamDraft) and any(isinstance(other, TournamentDraft) and
                any(ref.key == draft.ref.key for ref in other.teams) for other in self.drafts.values()):
            raise ValueError("Este equipo forma parte de un torneo. Quítalo de ese torneo antes de borrar el equipo.")
        self._save({key: value for key, value in self.drafts.items() if key != draft.id})

    def custom_teams(self) -> dict[str, TeamDraft]:
        return {draft.ref.key: draft for draft in self.drafts.values() if isinstance(draft, TeamDraft)}

    def import_package(self, path: Path) -> Draft:
        draft, teams = read_package(path)
        cloned = {team.ref.key: replace(team, id=new_id()) for team in teams}
        if isinstance(draft, TournamentDraft):
            refs = tuple(cloned[ref.key].ref if ref.key in cloned else ref for ref in draft.teams)
            copy = replace(draft, id=new_id(), teams=refs)
        else:
            copy = replace(draft, id=new_id())
        imported = {team.id: team for team in cloned.values()}
        self._save({**self.drafts, **imported, copy.id: copy})
        return copy


def resolve_tournament(
    draft: TournamentDraft, catalogue: dict[str, Team], custom: dict[str, TeamDraft],
) -> list[Team]:
    if errors := draft.issues():
        raise ValueError(errors[0])
    resolved = []
    for ref in draft.teams:
        if ref.key in custom and custom[ref.key].kind == draft.kind:
            try:
                team = custom[ref.key].as_team()
            except ValueError as exc:
                raise ValueError(f"{ref.name}: {exc}") from exc
        elif ref.key in catalogue:
            team = catalogue[ref.key]
        else:
            raise ValueError(f"No está disponible {ref.name}. Revisa los participantes de este torneo.")
        resolved.append(team)
    if len({team_key(team.name) for team in resolved}) != len(resolved):
        raise ValueError("Hay participantes con el mismo nombre. Revisa la lista de equipos.")
    return resolved


def export_package(draft: Draft, custom: dict[str, TeamDraft], destination: Path) -> Path:
    if errors := draft.issues():
        raise ValueError(errors[0])
    embedded = []
    if isinstance(draft, TournamentDraft):
        for ref in draft.teams:
            if ref.key.startswith("borrador:"):
                team = custom.get(ref.key)
                if team is None or team.kind != draft.kind or team.issues():
                    raise ValueError(f"No se puede incorporar un plantel válido para {ref.name}.")
                embedded.append(_encode(team))
    data = {"version": SCHEMA_VERSION, "version_juego": VERSION, **_encode(draft), "equipos_propios": embedded}
    blob = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(blob) > _MAX_PACKAGE:
        raise ValueError("El aporte supera el tamaño máximo.")
    slug = re.sub(r"[^a-z0-9]+", "-", team_key(draft.name)).strip("-")[:50] or "creacion"
    path = destination / f"AudioFutbol-{slug}-{new_id()[:10]}.zip"

    def write(temp: Path) -> None:
        with ZipFile(temp, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(_MANIFEST, blob)
            archive.writestr("LEEME.txt",
                "Aporte para AudioFútbol.\n"
                "En el juego: Menú principal, Crear, Importar un aporte ZIP.\n"
                "Se abre como borrador y no modifica el catálogo ni las competiciones oficiales.\n"
                "Comparte este ZIP completo para que se pueda probar y revisar.\n")
    _atomic_write(path, write)
    return path


def read_package(path: Path) -> tuple[Draft, tuple[TeamDraft, ...]]:
    if path.stat().st_size > _MAX_PACKAGE:
        raise ValueError("El ZIP supera el tamaño máximo.")
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) - {_MANIFEST, "LEEME.txt"} or _MANIFEST not in names:
                raise ValueError("El ZIP no contiene un aporte de AudioFútbol en el formato esperado.")
            entry = archive.getinfo(_MANIFEST)
            if entry.file_size > _MAX_PACKAGE:
                raise ValueError("Los datos del aporte superan el tamaño máximo.")
            with archive.open(entry) as stream:
                blob = stream.read(_MAX_PACKAGE + 1)
            if len(blob) > _MAX_PACKAGE:
                raise ValueError("Los datos del aporte superan el tamaño máximo.")
            data = _decode_json(blob)
    except (BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("No pude leer el ZIP del aporte.") from exc
    draft = _decode(data, ready=True)
    teams: list[TeamDraft] = []
    for entry in _items(data, "equipos_propios", 64):
        team = _decode(entry, ready=True)
        if not isinstance(team, TeamDraft) or not isinstance(draft, TournamentDraft) or team.kind != draft.kind:
            raise ValueError("El ZIP incluye un plantel que no corresponde al aporte.")
        teams.append(team)
    keys = {team.ref.key for team in teams}
    required = {ref.key for ref in draft.teams if ref.key.startswith("borrador:")} if isinstance(draft, TournamentDraft) else set()
    if keys != required or len(keys) != len(teams):
        raise ValueError("Los planteles incluidos no coinciden con los participantes.")
    return draft, tuple(teams)


def downloads_folder() -> Path:
    """Resolve the Windows Downloads known folder, including redirected paths."""
    if sys.platform == "win32":
        try:
            folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(
                UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le
            )
            result = ctypes.c_wchar_p()
            lookup = ctypes.windll.shell32.SHGetKnownFolderPath
            lookup.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
            lookup.restype = ctypes.c_long
            try:
                if lookup(ctypes.byref(folder_id), 0, None, ctypes.byref(result)) == 0 and result.value:
                    return Path(result.value)
            finally:
                if result:
                    ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))
        except (AttributeError, OSError):
            pass
    return Path.home() / "Downloads"


def issue_url(draft: Draft, filename: str) -> str:
    noun = "Equipo" if isinstance(draft, TeamDraft) else "Torneo"
    query = urlencode({"title": f"Aporte de {noun.lower()}: {draft.name}",
                      "body": f"Tipo: {noun}\n\nNombre: {draft.name}\n\n"
                              f"Adjunta aquí el archivo {filename}.\n\n"
                              "Describe qué aportas y cómo lo probaste.\n"})
    return f"https://github.com/{GITHUB_REPO}/issues/new?{query}"


def squad_from_team(team: Team) -> tuple[SquadPlayer, ...]:
    """Copy an existing squad without copying suspensions, goals or other match state."""
    occupied: set[int] = set()
    players = []
    for player in team.players:
        number = player.number
        if not 1 <= number <= 99 or number in occupied:
            number = next(n for n in range(1, 100) if n not in occupied)
        occupied.add(number)
        role = preferred_role(type(player).from_dict(player.to_dict()))
        players.append(SquadPlayer(player.name, number, role, player.overall))
    return tuple(players)


def read_roster_csv(path: Path, team_name: str) -> tuple[SquadPlayer, ...]:
    """Read one team's roster using the repository's documented CSV columns."""
    try:
        data = _read_limited(path, 256 * 1024).decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("Guarda el CSV en codificación UTF-8.") from exc
    try:
        dialect = csv.Sniffer().sniff(data[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = csv.DictReader(io.StringIO(data), dialect=dialect)
    lookup = {k.strip().lower(): k for k in rows.fieldnames or []}
    if not set(lookup) >= {"numero", "calidad"} or not ({"jugador", "nombre"} & lookup.keys()) or not ({"posicion", "puesto"} & lookup.keys()):
        raise ValueError("El CSV necesita jugador, numero, calidad y posicion o puesto.")
    out = []
    for row in rows:
        if len(out) >= 30:
            raise ValueError("El CSV de un plantel debe tener como máximo 30 jugadores.")
        def field(key: str) -> str:
            return (row.get(lookup.get(key, "")) or "").strip()
        if field("equipo") and team_key(field("equipo")) != team_key(team_name):
            raise ValueError(f"La fila {rows.line_num} pertenece a {field('equipo')}, no a {team_name}.")
        position = field("posicion").upper()
        concrete = field("puesto") or {"POR": "POR", "DEF": "CE", "MED": "MC", "DEL": "DC"}.get(position, position)
        role = puesto_from_text(concrete)
        if role and position in ("POR", "DEF", "MED", "DEL") and ROLES[role][1] != position:
            raise ValueError(f"El puesto y la posición no coinciden en la fila {rows.line_num}.")
        try:
            player = SquadPlayer(field("jugador") or field("nombre"), int(field("numero")), role or "", int(field("calidad")))
        except ValueError as exc:
            raise ValueError(f"Revisa el dorsal o la calidad en la fila {rows.line_num}.") from exc
        if errors := player.issues():
            raise ValueError(f"Fila {rows.line_num}: {errors[0]}")
        out.append(player)
    if not out:
        raise ValueError("El CSV no contiene jugadores.")
    return tuple(out)
