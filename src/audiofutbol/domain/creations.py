"""Versioned, declarative data for community team and tournament creations."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from uuid import uuid4

from audiofutbol.domain.formations import ROLES
from audiofutbol.domain.models import Player, Team
from audiofutbol.domain.text import normalize_text

SCHEMA_VERSION = 1
KINDS = ("club", "seleccion")
POSITION_MINIMUMS = {"POR": 2, "DEF": 3, "MED": 2, "DEL": 1}
POSITION_LABELS = {"POR": "Porteros", "DEF": "Defensas", "MED": "Mediocampistas", "DEL": "Delanteros"}


def new_id() -> str:
    return uuid4().hex


def valid_id(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def team_key(name: str) -> str:
    return " ".join(normalize_text(name).split())


def _text(value: str, maximum: int, *, required: bool = False) -> bool:
    return (
        isinstance(value, str) and len(value) <= maximum and (not required or bool(value.strip()))
        and all(c.isprintable() or c == " " for c in value)
    )


@dataclass(frozen=True)
class FormatSpec:
    key: str
    label: str
    sizes: tuple[int, ...]
    club_only: bool = False
    nation_only: bool = False

    def supports(self, kind: str) -> bool:
        return not (self.club_only and kind != "club" or self.nation_only and kind != "seleccion")


FORMATS = {item.key: item for item in (
    FormatSpec("liga", "Liga, campeón por tabla", tuple(range(2, 65))),
    FormatSpec("liguilla", "Liga con eliminatorias por el título", tuple(range(3, 65))),
    FormatSpec("grupos", "Grupos de cuatro y eliminatorias", (8, 16, 32, 64)),
    FormatSpec("eliminacion", "Eliminación directa", (2, 4, 8, 16, 32, 64)),
    FormatSpec("mundial", "Formato del Mundial, con tercer puesto", (8, 16, 32, 48), nation_only=True),
    FormatSpec("naciones", "Formato de la Liga de Naciones", (8, 16, 32, 48), nation_only=True),
    FormatSpec("fase_uefa", "Fase de liga y repesca, formato de la Liga de Campeones", (36,), club_only=True),
    FormatSpec("liguilla_mx", "Apertura con liguilla, formato de Liga MX", (18,), club_only=True),
    FormatSpec("apertura", "Apertura y Clausura, formato de Liga 1 de Perú", (18,), club_only=True),
    FormatSpec("ascenso", "Liga con repechaje de ascenso, formato de Série B", (20,), club_only=True),
)}


@dataclass(frozen=True)
class SquadPlayer:
    name: str
    number: int
    role: str
    overall: int

    def issues(self) -> list[str]:
        label = self.name.strip() if isinstance(self.name, str) else ""
        prefix = label or "Jugador sin nombre"
        errors = []
        if not _text(self.name, 100, required=True):
            errors.append("Escribe un nombre de jugador válido.")
        if type(self.number) is not int or not 1 <= self.number <= 99:
            errors.append(f"{prefix}: el dorsal debe estar entre 1 y 99.")
        if not isinstance(self.role, str) or self.role not in ROLES:
            errors.append(f"{prefix}: el puesto no es válido.")
        if type(self.overall) is not int or not 30 <= self.overall <= 99:
            errors.append(f"{prefix}: la calidad debe estar entre 30 y 99.")
        return errors

    def player(self) -> Player:
        return Player(self.name, ROLES[self.role][1], self.overall, self.number, puesto=self.role)


@dataclass(frozen=True)
class TeamRef:
    """Stable lookup key and human-readable fallback for a missing entry."""

    key: str
    name: str


@dataclass(frozen=True)
class Placement:
    """Proposed replacement in an official competition, never applied globally."""

    competition: str
    replace_id: str
    replace_name: str


@dataclass(frozen=True)
class TeamDraft:
    name: str
    kind: str
    country: str
    id: str = field(default_factory=new_id)
    stadium: str = ""
    city: str = ""
    source: str = ""
    original: str = ""
    players: tuple[SquadPlayer, ...] = ()
    placements: tuple[Placement, ...] = ()

    def issues(self, *, ready: bool = True) -> list[str]:
        errors: list[str] = []
        if not valid_id(self.id) or self.kind not in KINDS:
            errors.append("La identidad o el tipo de equipo no son válidos.")
        for label, value, limit, required in (
            ("Nombre", self.name, 90, True), ("País", self.country, 70, True),
            ("Estadio", self.stadium, 120, False), ("Ciudad", self.city, 90, False),
            ("Fuente o nota", self.source, 300, False), ("Equipo original", self.original, 110, False),
        ):
            if not _text(value, limit, required=required):
                errors.append(f"{label}: revisa el texto.")
        if bool(self.stadium) != bool(self.city):
            errors.append("Indica el estadio y su ciudad, o deja ambos vacíos.")
        if self.original and self.original != f"catalogo:{team_key(self.name)}":
            errors.append("Una actualización debe conservar el nombre del equipo original.")
        if len(self.players) > 30:
            errors.append("Un plantel admite hasta 30 jugadores.")
        names: set[str] = set()
        numbers: set[int] = set()
        lines = dict.fromkeys(POSITION_MINIMUMS, 0)
        for player in self.players:
            if issues := player.issues():
                errors.extend(issues)
                continue
            key = team_key(player.name)
            if key in names:
                errors.append(f"El nombre {player.name} está repetido.")
            if player.number in numbers:
                errors.append(f"El dorsal {player.number} está repetido.")
            names.add(key)
            numbers.add(player.number)
            lines[ROLES[player.role][1]] += 1
        if ready:
            if len(names) < 12:
                errors.append(f"Faltan jugadores: tienes {len(names)} y necesitas al menos 12.")
            if sum(lines.values()) - lines["POR"] < 10:
                errors.append("Se necesitan 10 jugadores de campo para no usar al portero suplente en el once.")
            for position, minimum in POSITION_MINIMUMS.items():
                if lines[position] < minimum:
                    errors.append(f"{POSITION_LABELS[position]}: se necesitan al menos {minimum}.")
        codes: set[str] = set()
        for placement in self.placements:
            if not all(_text(s, 110, required=True) for s in (placement.competition, placement.replace_id, placement.replace_name)):
                errors.append("Hay una propuesta de participación incompleta.")
            if placement.competition in codes:
                errors.append("Solo puedes proponer un cupo por competición.")
            codes.add(placement.competition)
        return errors

    @property
    def ref(self) -> TeamRef:
        return TeamRef(f"borrador:{self.id}", self.name)

    def as_team(self) -> Team:
        if errors := self.issues():
            raise ValueError(errors[0])
        players = [item.player() for item in self.players]
        top = sorted((p.overall for p in players), reverse=True)[:11]
        return Team(self.name, players, team_id=self.id, country=self.country,
                    stadium=self.stadium or None, city=self.city,
                    level=round(sum(top) / 11), is_real_squad=True)


@dataclass(frozen=True)
class TournamentDraft:
    name: str
    kind: str
    format: str
    team_count: int
    id: str = field(default_factory=new_id)
    rounds: int = 2
    advance: int = 0
    knockout_legs: int = 1
    final_legs: int = 1
    away_goals: bool = False
    stadium: str = ""
    city: str = ""
    source: str = ""
    teams: tuple[TeamRef, ...] = ()

    def issues(self, *, ready: bool = True) -> list[str]:
        errors: list[str] = []
        if not valid_id(self.id) or self.kind not in KINDS or not _text(self.name, 90, required=True):
            errors.append("Revisa el nombre y el tipo de torneo.")
        spec = FORMATS.get(self.format)
        if spec is None or not spec.supports(self.kind) or type(self.team_count) is not int or self.team_count not in spec.sizes:
            errors.append("La cantidad de participantes no es válida para este formato.")
        if self.format == "liguilla" and self.advance not in playoff_sizes(self.team_count):
            errors.append("La cantidad de clasificados a eliminatorias no es válida.")
        if any(type(n) is not int or n not in (1, 2) for n in (self.rounds, self.knockout_legs, self.final_legs)):
            errors.append("El número de vueltas o partidos por cruce no es válido.")
        if type(self.away_goals) is not bool or type(self.advance) is not int:
            errors.append("Revisa las reglas de las eliminatorias.")
        if not (_text(self.stadium, 120) and _text(self.city, 90) and _text(self.source, 300)):
            errors.append("Revisa los datos de la sede o la fuente.")
        if bool(self.stadium) != bool(self.city):
            errors.append("Indica el estadio de la final y su ciudad, o deja ambos vacíos.")
        if self.stadium and not (self.format == "fase_uefa" or
                self.format in ("liguilla", "grupos", "eliminacion") and self.final_legs == 1):
            errors.append("Este formato no admite una sede neutral personalizada.")
        keys: set[str] = set()
        names: set[str] = set()
        for ref in self.teams:
            if not _text(ref.key, 140, required=True) or not _text(ref.name, 110, required=True):
                errors.append("Hay un participante sin identidad válida.")
                continue
            if not (ref.key == f"catalogo:{team_key(ref.name)}" or
                    ref.key.startswith("borrador:") and valid_id(ref.key.split(":", 1)[1])):
                errors.append(f"La referencia a {ref.name} no es válida.")
            if ref.key in keys or team_key(ref.name) in names:
                errors.append(f"{ref.name} está repetido.")
            keys.add(ref.key)
            names.add(team_key(ref.name))
        if type(self.team_count) is int and (len(self.teams) > self.team_count or ready and len(self.teams) != self.team_count):
            errors.append(f"Selecciona {self.team_count} participantes. Tienes {len(self.teams)}.")
        return errors


def playoff_sizes(team_count: int) -> tuple[int, ...]:
    return tuple(n for n in (2, 4, 8, 16, 32) if type(team_count) is int and n < team_count)


Draft = TeamDraft | TournamentDraft
