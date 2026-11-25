"""Flexible CSV/TSV player database loader and fallback generic squad generator."""

from __future__ import annotations

from collections.abc import Iterable
import csv
import io
from pathlib import Path
import random

from audiofutbol.domain.formations import puesto_from_text
from audiofutbol.domain.models import Player, Team
from audiofutbol.domain.text import normalize_text, tokenize
from audiofutbol.engine.paths import AppPaths

FIRST_NAMES: tuple[str, ...] = (
    "Mateo", "Santiago", "Diego", "Lucas", "Daniel", "Pablo", "Andrés", "Javier",
    "Sergio", "Marco", "Bruno", "Hugo", "Iván", "Rafael", "Tomás", "Álvaro",
    "Nicolás", "Gabriel", "Emilio", "Joaquín", "Adrián", "Leandro", "Mario", "Óscar",
)

LAST_NAMES: tuple[str, ...] = (
    "Ríos", "Vega", "Salazar", "Montes", "Cabrera", "Duarte", "Ferrer", "Ibarra",
    "Lozano", "Medina", "Navarro", "Ortega", "Paredes", "Quiroga", "Rojas", "Soto",
    "Torres", "Uribe", "Valdés", "Zamora", "Bermúdez", "Cordero", "Delgado",
    "Escobar", "Fuentes", "Galindo", "Herrera", "Inzunza", "Jiménez", "Kramer",
)

FALLBACK_NATIONAL_TEAMS: tuple[tuple[str, int], ...] = (
    ("Argentina", 86), ("Francia", 86), ("Brasil", 85), ("España", 85), ("Inglaterra", 84),
    ("Portugal", 83), ("Países Bajos", 83), ("Alemania", 83), ("Italia", 82), ("Bélgica", 80),
    ("Croacia", 80), ("Uruguay", 80), ("Colombia", 79), ("México", 78), ("Marruecos", 78),
    ("Estados Unidos", 77), ("Japón", 77), ("Senegal", 76), ("Suiza", 76), ("Dinamarca", 76),
    ("Corea del Sur", 75), ("Ecuador", 74), ("Irán", 74), ("Serbia", 74), ("Polonia", 74),
    ("Australia", 73), ("Gales", 72), ("Camerún", 72), ("Canadá", 72), ("Túnez", 71),
    ("Ghana", 71), ("Costa Rica", 70),
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "equipo": (
        "equipo", "seleccion", "pais", "team", "country", "nation", "nationality",
        "nationality_name", "nacionalidad", "club",
    ),
    "nombre": ("jugador", "nombre", "name", "player", "short_name", "long_name"),
    "pos": ("posicion", "pos", "position", "positions", "player_positions"),
    "ovr": (
        "calidad", "media", "overall", "ovr", "rating", "valoracion", "general",
        "overall_rating",
    ),
    "num": ("numero", "dorsal", "number", "kit_number", "shirt"),
    "ataque": ("ataque", "attack", "atk"),
    "defensa": ("defensa", "defense", "defending", "dfn"),
    "pase": ("pase", "passing", "pas", "pass"),
    "porteria": ("porteria", "portero", "goalkeeping"),
    "puesto": ("puesto", "puesto_concreto", "role", "rol"),
}

POSITION_ALIASES: dict[str, tuple[str, ...]] = {
    "POR": ("por", "gk", "portero", "arquero", "goalkeeper", "keeper", "p"),
    "DEF": (
        "def", "defensa", "cb", "lb", "rb", "lwb", "rwb", "defender", "dfc",
        "li", "ld", "lateral", "central",
    ),
    "MED": (
        "med", "medio", "mc", "cm", "cdm", "cam", "lm", "rm", "mid", "midfielder",
        "mcd", "mco", "volante", "mediocampista", "centrocampista", "mi", "md",
    ),
    "DEL": (
        "del", "delantero", "fw", "st", "cf", "lw", "rw", "ss", "striker",
        "forward", "extremo", "dc", "ei", "ed", "winger", "atacante",
    ),
}


def create_generic_team(name: str, level: int) -> Team:
    """Deterministically generate a balanced 23-player squad for `name`."""
    rng = random.Random(name)
    plan = (("POR", 3), ("DEF", 8), ("MED", 7), ("DEL", 5))
    starters_by_pos = {"POR": 1, "DEF": 4, "MED": 3, "DEL": 3}
    players: list[Player] = []
    used_names: set[str] = set()
    shirt = 1
    for pos, count in plan:
        for k in range(count):
            while True:
                full_name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                if full_name not in used_names:
                    used_names.add(full_name)
                    break
            is_starter = k < starters_by_pos[pos]
            ovr = (
                level + rng.randint(-4, 5)
                if is_starter
                else level - rng.randint(5, 12)
            )
            players.append(Player(full_name, pos, max(40, min(97, ovr)), shirt))
            shirt += 1
    return Team(name=name, players=players, level=level, is_real_squad=False)


def parse_position(raw: str) -> str:
    for token in tokenize(raw):
        for code, aliases in POSITION_ALIASES.items():
            if token in aliases:
                return code
    return "MED"


def _parse_float(row: dict[str, str], col: str | None, default: float) -> float:
    if not col:
        return default
    try:
        return float(str(row.get(col) or "").replace(",", "."))
    except ValueError:
        return default


def _compute_overall(pos: str, atk: float, dfn: float, pas: float, gk: float) -> float:
    if pos == "POR":
        return gk
    if pos == "DEF":
        return 0.75 * dfn + 0.25 * pas
    if pos == "MED":
        return 0.45 * pas + 0.30 * atk + 0.25 * dfn
    return 0.80 * atk + 0.20 * pas


def read_squad_csv(path: Path) -> list[tuple[str, str, str, int, int]]:
    """Read a CSV/TSV file and return tuples of (team, player, position, overall, number)."""
    return [(team, p.name, p.position, p.overall, p.number) for team, p in _read_players(path)]


def _read_players(path: Path) -> list[tuple[str, Player]]:
    """Keep the concrete role attached to its row, not shared by player name."""
    text: str | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return []

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fieldnames = reader.fieldnames or []
    normalized_cols = {
        normalize_text(c).strip().replace(" ", "_"): c for c in fieldnames if c
    }

    def find_col(key: str) -> str | None:
        for alias in COLUMN_ALIASES[key]:
            if alias in normalized_cols:
                return normalized_cols[alias]
        return None

    c_eq = find_col("equipo")
    c_nom = find_col("nombre")
    c_pos = find_col("pos")
    c_ovr = find_col("ovr")
    c_num = find_col("num")
    c_atk = find_col("ataque")
    c_dfn = find_col("defensa")
    c_pas = find_col("pase")
    c_por = find_col("porteria")
    c_pue = find_col("puesto")
    if not c_nom:
        return []

    default_team = path.stem.replace("_", " ")
    rows: list[tuple[str, Player]] = []
    for row in reader:
        player_name = (row.get(c_nom) or "").strip()
        if not player_name:
            continue
        team_name = (row.get(c_eq) or "").strip() if c_eq else default_team
        if not team_name:
            team_name = default_team
        pos = parse_position(row.get(c_pos) or "") if c_pos else "MED"
        if not c_ovr and (c_atk or c_dfn or c_pas or c_por):
            ovr = _compute_overall(
                pos,
                _parse_float(row, c_atk, 50.0),
                _parse_float(row, c_dfn, 50.0),
                _parse_float(row, c_pas, 50.0),
                _parse_float(row, c_por, 55.0),
            )
        else:
            ovr = _parse_float(row, c_ovr, 70.0)
        if ovr <= 10:
            ovr *= 10
        overall = int(round(max(30, min(99, ovr))))
        concrete = puesto_from_text(row.get(c_pue) or "") if c_pue else None
        if not concrete and c_pos:
            concrete = puesto_from_text(row.get(c_pos) or "")
        try:
            shirt = int(float(row.get(c_num) or 0)) if c_num else 0
        except ValueError:
            shirt = 0
        rows.append((team_name, Player(player_name, pos, overall, shirt, puesto=concrete or "")))
    return rows


def select_squad(
    players: Iterable[Player],
    max_size: int = 30,
    min_goalkeepers: int = 2,
) -> list[Player]:
    """Return top `max_size` players by overall while preserving at least `min_goalkeepers`."""
    ordered = sorted(players, key=lambda p: (-p.overall, p.name))
    if len(ordered) <= max_size:
        return ordered
    selected = list(ordered[:max_size])
    gks_in = sum(1 for p in selected if p.position == "POR")
    if gks_in < min_goalkeepers:
        extra_gks = [p for p in ordered[max_size:] if p.position == "POR"][
            : min_goalkeepers - gks_in
        ]
        for gk in extra_gks:
            for idx in range(len(selected) - 1, -1, -1):
                if selected[idx].position != "POR":
                    selected[idx] = gk
                    break
        selected.sort(key=lambda p: (-p.overall, p.name))
    return selected


def load_national_teams(paths: AppPaths) -> tuple[list[Team], bool]:
    """Load national teams from `datos/*.csv`; fallback to 32 generated teams if < 8."""
    grouped: dict[str, dict[str, Player]] = {}
    if paths.data_dir.is_dir():
        for entry in sorted(paths.data_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() in (".csv", ".tsv"):
                try:
                    for eq, player in _read_players(entry):
                        grouped.setdefault(eq, {})[player.name] = player
                except Exception:
                    continue

    teams: list[Team] = []
    for name, player_map in grouped.items():
        squad = select_squad(player_map.values())
        if len(squad) >= 11:
            teams.append(Team(name=name, players=squad, is_real_squad=True))

    if len(teams) >= 8:
        return sorted(teams, key=lambda t: -t.strength()), True
    return [create_generic_team(n, lvl) for n, lvl in FALLBACK_NATIONAL_TEAMS], False


def load_extra_national_teams(paths: AppPaths) -> list[Team]:
    """Load additional national teams from `datos/otras_selecciones/*.csv`.

    These teams are NOT part of the 48-team World Cup / Nations League pool; they are
    available for friendlies and custom national tournaments (e.g. Peru, Italy).
    """
    grouped: dict[str, dict[str, Player]] = {}
    if paths.extra_nations_dir.is_dir():
        for entry in sorted(paths.extra_nations_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() in (".csv", ".tsv"):
                try:
                    for eq, player in _read_players(entry):
                        grouped.setdefault(eq, {})[player.name] = player
                except Exception:
                    continue
    teams: list[Team] = []
    for name, player_map in grouped.items():
        squad = select_squad(player_map.values())
        if len(squad) >= 11:
            teams.append(Team(name=name, players=squad, is_real_squad=True))
    return sorted(teams, key=lambda t: t.name)


def load_club_players(paths: AppPaths) -> dict[str, dict[str, Player]]:
    """Load club squads from `datos/clubes/*.csv`, keyed by normalized club name."""
    clubs: dict[str, dict[str, Player]] = {}
    if paths.clubs_dir.is_dir():
        for entry in sorted(paths.clubs_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() in (".csv", ".tsv"):
                try:
                    for eq, player in _read_players(entry):
                        clubs.setdefault(normalize_text(eq).strip(), {})[player.name] = player
                except Exception:
                    continue
    return clubs
