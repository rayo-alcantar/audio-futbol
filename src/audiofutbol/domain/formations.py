"""Tactical formations, concrete pitch roles, and Hungarian role assignment.

Thin layer over the engine's four core position lines (POR, DEF, MED, DEL): each scheme
distributes ten outfield slots (fullbacks, wingbacks, center-backs, holding midfielder,
central midfielders, wide midfielders, attacking midfielder, wingers, strikers). Each
player has a preferred concrete role (from the CSV `puesto` column, the known-player
registry, or a stable name hash) and performs slightly below peak when played out of role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable
import random
import zlib

from audiofutbol.domain.text import normalize_text, tokenize

if TYPE_CHECKING:  # pragma: no cover
    from audiofutbol.domain.models import Player

DEFAULT_SCHEME = "4-3-3"

# code: (Spanish label, core line group, flank side, role family)
ROLES: dict[str, tuple[str, str, str, str]] = {
    "POR": ("portero", "POR", "centro", "POR"),
    "LI": ("lateral izquierdo", "DEF", "izquierda", "LAT"),
    "LD": ("lateral derecho", "DEF", "derecha", "LAT"),
    "CAI": ("carrilero izquierdo", "DEF", "izquierda", "LAT"),
    "CAD": ("carrilero derecho", "DEF", "derecha", "LAT"),
    "CEI": ("central izquierdo", "DEF", "izquierda", "CEN"),
    "CE": ("central", "DEF", "centro", "CEN"),
    "CED": ("central derecho", "DEF", "derecha", "CEN"),
    "MCD": ("mediocentro defensivo", "MED", "centro", "MCD"),
    "MC": ("mediocampista", "MED", "centro", "MC"),
    "MI": ("interior izquierdo", "MED", "izquierda", "MC"),
    "MDR": ("interior derecho", "MED", "derecha", "MC"),
    "VI": ("volante izquierdo", "MED", "izquierda", "ALA"),
    "VD": ("volante derecho", "MED", "derecha", "ALA"),
    "MP": ("mediapunta", "MED", "centro", "MP"),
    "EI": ("extremo izquierdo", "DEL", "izquierda", "EXT"),
    "ED": ("extremo derecho", "DEL", "derecha", "EXT"),
    "DC": ("delantero centro", "DEL", "centro", "DC"),
    "SD": ("segundo delantero", "DEL", "centro", "DC"),
}

# Ten outfield slots per tactical scheme, ordered left-to-right from defense to attack.
SCHEMES: dict[str, list[str]] = {
    "4-3-3": ["LI", "CEI", "CED", "LD", "MI", "MCD", "MDR", "EI", "DC", "ED"],
    "4-4-2": ["LI", "CEI", "CED", "LD", "VI", "MC", "MC", "VD", "DC", "SD"],
    "4-2-3-1": ["LI", "CEI", "CED", "LD", "MCD", "MC", "VI", "MP", "VD", "DC"],
    "4-5-1": ["LI", "CEI", "CED", "LD", "VI", "MC", "MCD", "MC", "VD", "DC"],
    "4-1-4-1": ["LI", "CEI", "CED", "LD", "MCD", "VI", "MC", "MC", "VD", "DC"],
    "3-5-2": ["CEI", "CE", "CED", "CAI", "MC", "MCD", "MC", "CAD", "DC", "SD"],
    "3-4-3": ["CEI", "CE", "CED", "CAI", "MC", "MC", "CAD", "EI", "DC", "ED"],
    "5-3-2": ["CAI", "CEI", "CE", "CED", "CAD", "MC", "MCD", "MC", "DC", "SD"],
    "5-4-1": ["CAI", "CEI", "CE", "CED", "CAD", "VI", "MCD", "MC", "VD", "DC"],
}
SCHEME_ROWS: dict[str, list[tuple[str, list[str]]]] = {
    "4-3-3": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["LI", "CEI", "CED", "LD"]),
        ("Mediocampo", ["MI", "MCD", "MDR"]),
        ("Delantera", ["EI", "DC", "ED"]),
    ],
    "4-4-2": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["LI", "CEI", "CED", "LD"]),
        ("Mediocampo", ["VI", "MC", "MC", "VD"]),
        ("Delantera", ["DC", "SD"]),
    ],
    "4-2-3-1": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["LI", "CEI", "CED", "LD"]),
        ("Mediocampo defensivo", ["MCD", "MC"]),
        ("Mediocampo ofensivo", ["VI", "MP", "VD"]),
        ("Delantera", ["DC"]),
    ],
    "4-5-1": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["LI", "CEI", "CED", "LD"]),
        ("Mediocampo", ["VI", "MC", "MCD", "MC", "VD"]),
        ("Delantera", ["DC"]),
    ],
    "4-1-4-1": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["LI", "CEI", "CED", "LD"]),
        ("Mediocentro defensivo", ["MCD"]),
        ("Mediocampo", ["VI", "MC", "MC", "VD"]),
        ("Delantera", ["DC"]),
    ],
    "3-5-2": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["CEI", "CE", "CED"]),
        ("Mediocampo", ["CAI", "MC", "MCD", "MC", "CAD"]),
        ("Delantera", ["DC", "SD"]),
    ],
    "3-4-3": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["CEI", "CE", "CED"]),
        ("Mediocampo", ["CAI", "MC", "MC", "CAD"]),
        ("Delantera", ["EI", "DC", "ED"]),
    ],
    "5-3-2": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["CAI", "CEI", "CE", "CED", "CAD"]),
        ("Mediocampo", ["MC", "MCD", "MC"]),
        ("Delantera", ["DC", "SD"]),
    ],
    "5-4-1": [
        ("Portería", ["POR"]),
        ("Zona defensiva", ["CAI", "CEI", "CE", "CED", "CAD"]),
        ("Mediocampo", ["VI", "MCD", "MC", "VD"]),
        ("Delantera", ["DC"]),
    ],
}
SCHEME_ORDER: list[str] = [
    "4-3-3", "4-4-2", "4-2-3-1", "4-5-1", "4-1-4-1", "3-5-2", "3-4-3", "5-3-2", "5-4-1",
]
SCHEME_DESC: dict[str, str] = {
    "4-3-3": "Ofensivo y equilibrado. Cuatro defensas, un pivote, dos interiores y tres delanteros",
    "4-4-2": "Clásico y equilibrado. Dos líneas de cuatro y dos delanteros",
    "4-2-3-1": "Equilibrado. Dos pivotes, tres mediapuntas y un solo delantero",
    "4-5-1": "Prudente. Cinco mediocampistas y un solo delantero",
    "4-1-4-1": "Defensivo con control del medio. Un pivote, cuatro mediocampistas y un delantero",
    "3-5-2": "Ofensivo por las bandas. Tres centrales, dos carrileros, tres medios y dos delanteros",
    "3-4-3": (
        "Muy ofensivo. Tres centrales, dos carrileros, dos medios y tres delanteros. "
        "Deja espacios atrás"
    ),
    "5-3-2": (
        "Defensivo, con línea de cinco. Tres centrales, dos carrileros, tres medios "
        "y dos delanteros"
    ),
    "5-4-1": "Muy defensivo, con línea de cinco y un solo delantero, para cuidar el resultado",
}
# Subtle style modifier (att, mid, dfn) layered on top of line-count shape bonuses.
SCHEME_STYLE: dict[str, tuple[float, float, float]] = {
    "4-3-3": (1.0, 0.0, -0.5),
    "4-4-2": (0.0, 0.5, 0.0),
    "4-2-3-1": (0.5, 1.0, 0.5),
    "4-5-1": (-1.0, 1.5, 0.5),
    "4-1-4-1": (-0.5, 1.0, 1.0),
    "3-5-2": (0.5, 1.5, -1.0),
    "3-4-3": (1.5, 0.0, -1.5),
    "5-3-2": (-0.5, -0.5, 1.5),
    "5-4-1": (-1.5, 0.0, 2.0),
}

MENTALITY_NAMES: dict[int, str] = {
    -2: "muy defensiva",
    -1: "defensiva",
    0: "equilibrada",
    1: "ofensiva",
    2: "muy ofensiva",
}
MENTALITY_DESC: dict[int, str] = {
    -2: "Te cierras atrás y casi no atacas",
    -1: "Priorizas defender",
    0: "Equilibrio entre ataque y defensa",
    1: "Presionas más y sacrificas algo de defensa",
    2: "Todo al ataque. Dejas muchos espacios atrás",
}
# Maps five-level mentality (-2..+2) to TACTIC_PROFILES keys.
MENTALITY_TACTIC: dict[int, str] = {
    -2: "muy_defensivo",
    -1: "defensivo",
    0: "equilibrado",
    1: "ofensivo",
    2: "muy_ofensivo",
}
TACTIC_MENTALITY: dict[str, int] = {v: k for k, v in MENTALITY_TACTIC.items()}

DEFAULT_ROLE_BY_GROUP: dict[str, str] = {"POR": "POR", "DEF": "CE", "MED": "MC", "DEL": "DC"}

_KNOWN_BY_ROLE: dict[str, list[str]] = {
    "LD": ["Achraf Hakimi", "Aaron Wan-Bissaka", "Dani Carvajal", "Denzel Dumfries", "Diogo Dalot",
           "Kyle Walker", "Trent Alexander-Arnold", "Reece James", "Jeremie Frimpong", "Nahuel Molina",
           "Gonzalo Montiel", "Pedro Porro", "Matty Cash", "Sergiño Dest", "Joe Scally", "Nélson Semedo",
           "Yan Couto", "Danilo", "Wesley", "Malo Gusto", "Conor Bradley", "Ridle Baku", "Josip Stanišić",
           "Josip Juranović", "Giovanni Di Lorenzo", "Marcos Rocha", "Fagner", "Matheuzinho",
           "Santiago Arias", "Jhon Narváez", "Daniel Muñoz", "Kevin Álvarez", "Jorge Sánchez",
           "Ruben Aguilar", "Ramin Rezaeian", "Yukinari Sugawara", "Seol Young-woo", "Mert Müldür",
           "Zeki Çelik", "Alistair Johnston", "Nathan Patterson", "Aaron Hickey", "Shurandy Sambo",
           "Lazaros Rota", "Silvan Widmer", "Stefan Lainer", "Youcef Atal", "Yahia Attiyat Allah",
           "Thomas Meunier", "Timothy Castagne", "Anthony Ralston", "Tariq Lamptey",
           "Ignace Van der Brempt", "Julian Ryerson", "Jordan Lotomba", "Michael Amir Murillo",
           "Héctor Bellerín", "Aitor Ruibal", "Lewis Miller", "Mauro Júnior", "Khuliso Mudau",
           "Mohamed Hany", "Tiago Santos", "Martim Fernandes", "Guela Doué", "Agustín Giay",
           "Ángelo Preciado", "Zakaria El Ouahdi", "Josha Vagnoman", "Ben White", "Tino Livramento"],
    "LI": ["Alphonso Davies", "Theo Hernández", "Andrew Robertson", "Andy Robertson", "Alex Sandro",
           "Lucas Digne", "Marcos Acuña", "Nicolás Tagliafico", "Federico Dimarco",
           "Leonardo Spinazzola", "Alejandro Grimaldo", "Alejandro Balde", "Marc Cucurella",
           "Ferland Mendy", "Nuno Mendes", "Antonee Robinson", "Luke Shaw", "Milos Kerkez",
           "Rayan Aït-Nouri", "Ian Maatsen", "David Raum", "Maximilian Mittelstädt",
           "Pervis Estupiñán", "Johan Mojica", "Joaquín Piquerez", "Matías Viña", "Ricardo Mangas",
           "Renê", "Ayrton Lucas", "Carlos Augusto", "Angeliño", "Sergi Cardona", "Álvaro Carreras",
           "Gerardo Arteaga", "Jesús Gallardo", "Mateo Chávez", "Cristian Borja",
           "Gabriel Gudmundsson", "David Jurásek", "Borna Sosa", "Ali Maâloul", "Ramy Bensebaini",
           "Yuto Nagatomo", "Kim Moon-hwan", "Ludwig Augustinsson", "Fredrik Bjørkan",
           "Liberato Cacace", "Jayden Oosterwolde", "Junior Firpo", "Sead Kolašinac",
           "Alberto Moreno", "Maxim De Cuyper", "Ismail Jakobs", "Filip Mladenović",
           "Ricardo Rodríguez", "Kieran Tierney", "Lucas Hernández", "Arthur Theate",
           "Ahmed Fatouh", "Aubrey Modiba", "Ali Abdi", "Nathaniel Brown", "Alfonso Pedraza",
           "Lautaro Blanco", "Joaquín Seys", "Richie Laryea"],
    "CE": ["Marquinhos", "Gabriel Magalhães", "Éder Militão", "Bremer", "Cristian Romero",
           "Lisandro Martínez", "Nicolás Otamendi", "William Saliba", "Dayot Upamecano",
           "Ibrahima Konaté", "Virgil van Dijk", "Rúben Dias", "John Stones", "Manuel Akanji",
           "Antonio Rüdiger", "Jonathan Tah", "Nico Schlotterbeck", "Alessandro Bastoni",
           "Milan Škriniar", "Matthijs de Ligt", "Kim Min-jae", "Ronald Araújo", "Pau Cubarsí",
           "Aymeric Laporte", "Harry Maguire", "Marc Guéhi", "Sergio Ramos", "Thiago Silva",
           "Kalidou Koulibaly", "Nathan Aké", "Stefan de Vrij", "Josip Šutalo", "Francesco Acerbi",
           "Gianluca Mancini", "Leny Yoro", "Castello Lukeba", "Dean Huijsen", "Jhon Lucumí",
           "Davinson Sánchez", "Dávinson Sánchez", "Yerry Mina", "Piero Hincapié", "Willian Pacho",
           "Evan Ndicka", "Robin Le Normand", "Pau Torres", "Eric García", "Mario Hermoso",
           "Fabian Schär", "Willi Orbán", "Jan Bednarek", "César Montes", "Johan Vásquez",
           "Jesús Orozco", "Israel Reyes", "Víctor Guzmán", "Gustavo Gómez", "Leonardo Balerdi",
           "Facundo Medina", "Roger Ibañez",
           "Leo Pereira", "Léo Pereira", "Léo Ortiz", "Gonçalo Inácio", "António Silva",
           "Joško Gvardiol", "Ozan Kabak", "Merih Demiral", "Abdülkerim Bardakcı", "Micky van de Ven",
           "Diego Llorente", "Kevin Danso", "Ousmane Diomande", "Ezri Konsa", "Joe Gomez",
           "Dani Vivian", "Jurriën Timber", "Mohammed Salisu", "Nayef Aguerd", "Chancel Mbemba"],
    "MCD": ["Rodri", "Declan Rice", "Aurélien Tchouaméni", "Martín Zubimendi", "Moisés Caicedo",
            "Casemiro", "Stanislav Lobotka", "Boubacar Kamara", "Morten Hjulmand", "Xaver Schlager",
            "Thomas Partey", "Nicolas Seiwald", "Amadou Onana", "Aleksandar Pavlović",
            "André-Frank Zambo Anguissa", "Granit Xhaka", "Joshua Kimmich", "Pablo Barrios",
            "Manu Koné", "Richard Ríos", "Leandro Paredes", "Mateo Kovačić", "Angelo Stiller",
            "Leon Goretzka", "Kobbie Mainoo", "Ryan Gravenberch", "Eduardo Camavinga",
            "Edson Álvarez", "Érik Lira", "Luis Romo"],
    "MC": ["Álvaro Fidalgo", "Obed Vargas", "Luis Chávez", "Erick Sánchez"],
    "MP": ["Jamal Musiala", "Florian Wirtz", "Martin Ødegaard", "Bruno Fernandes", "Cole Palmer",
           "Phil Foden", "Arda Güler", "Dani Olmo", "Pedro Gonçalves", "Giorgian De Arrascaeta",
           "Eberechi Eze", "Xavi Simons", "Rayan Cherki", "Isco", "Marco Asensio", "Raphael Veiga",
           "Brahim Díaz", "Lee Kang-in", "Kevin De Bruyne", "Pedri", "Bernardo Silva",
           "Hakan Çalhanoğlu", "Dominik Szoboszlai", "Vitinha", "Gavi",
           "Orbelín Pineda", "Gilberto Mora", "Brian Gutiérrez"],
    "VD": ["Michael Olise", "Leroy Sané", "Mohammed Kudus", "Ángel Di María", "Morgan Rogers"],
    "VI": ["Chris Führich", "Dejan Kulusevski"],
    "ED": ["Lamine Yamal", "Ousmane Dembélé", "Mohamed Salah", "Bukayo Saka", "Raphinha",
           "Lionel Messi", "Désiré Doué", "Riyad Mahrez", "Serge Gnabry", "Pedro Neto", "Antony",
           "Savinho", "Estevão", "Francisco Trincão", "Bryan Mbeumo", "Amad Diallo", "Rodrygo",
           "Yeremy Pino", "Jérémy Doku", "Giuliano Simeone", "Roberto Alvarado"],
    "EI": ["Vinícius Júnior", "Vinícius Jr", "Khvicha Kvaratskhelia", "Luis Díaz", "Rafael Leão",
           "Son Heung-min", "Cody Gakpo", "Bradley Barcola", "Gabriel Martinelli", "Marcus Rashford",
           "Nico Williams", "Anthony Gordon", "Kenan Yıldız", "Crysencio Summerville",
           "Leandro Trossard", "Karim Adeyemi", "David Neres", "Noa Lang", "Yan Diomande",
           "Antonio Nusa", "Sadio Mané", "Christian Pulisic",
           "Alexis Vega", "Julián Quiñones", "César Huerta"],
    "DC": ["Kylian Mbappé", "Erling Haaland", "Harry Kane", "Lautaro Martínez", "Robert Lewandowski",
           "Julián Álvarez", "Alexander Isak", "Victor Osimhen", "Viktor Gyökeres",
           "Cristiano Ronaldo", "Serhou Guirassy", "Marcus Thuram", "Darwin Núñez",
           "Santiago Giménez", "Romelu Lukaku", "Ollie Watkins", "Patrik Schick", "Jonathan David",
           "Benjamin Šeško", "Mauro Icardi", "Luis Suárez", "Ivan Toney", "Mikel Oyarzabal",
           "Matheus Cunha", "Kai Havertz", "Hugo Ekitiké", "Nick Woltemade", "Loïs Openda",
           "Artem Dovbyk", "Youssef En-Nesyri", "Mehdi Taremi", "Endrick", "Yuri Alberto",
           "Raúl Jiménez", "Armando González", "Guillermo Martínez", "Henry Martín"],
}

KNOWN_PUESTOS: dict[str, str] = {}
for _code, _names in _KNOWN_BY_ROLE.items():
    for _name in _names:
        KNOWN_PUESTOS[normalize_text(_name).strip()] = _code

_CSV_TABLE: dict[str, str] = {
    "por": "POR", "gk": "POR", "portero": "POR", "arquero": "POR",
    "li": "LI", "lti": "LI", "lb": "LI", "lwb": "LI", "lateralizquierdo": "LI",
    "ld": "LD", "ldd": "LD", "rb": "LD", "rwb": "LD", "lateralderecho": "LD",
    "dfc": "CE", "cb": "CE", "ce": "CE", "central": "CE",
    "mcd": "MCD", "cdm": "MCD", "pivote": "MCD",
    "mc": "MC", "cm": "MC", "mco": "MP", "cam": "MP", "mp": "MP", "mediapunta": "MP",
    "mi": "VI", "lm": "VI", "vi": "VI", "md": "VD", "rm": "VD", "vd": "VD",
    "ei": "EI", "lw": "EI", "ed": "ED", "rw": "ED",
    "dc": "DC", "st": "DC", "cf": "DC", "sd": "SD", "ss": "SD",
}


def puesto_from_text(text: str) -> str | None:
    """Parse a concrete tactical role code (LI, LD, CE, MCD, EI, ...) from text, or None."""
    for token in tokenize(text):
        if token in _CSV_TABLE:
            return _CSV_TABLE[token]
    return None


def group_of(code: str) -> str:
    """Return the base position line (POR, DEF, MED, DEL) for a role code."""
    return ROLES[code][1]


def role_text(code: str) -> str:
    """Return the Spanish display name for a concrete role code."""
    return ROLES[code][0]


def side_of(code: str) -> str:
    """Return the pitch side (`izquierda`, `centro`, `derecha`) for a role code."""
    return ROLES[code][2]


def family_of(code: str) -> str:
    """Return the tactical role family (LAT, CEN, MCD, MC, ALA, MP, EXT, DC, POR)."""
    return ROLES[code][3]


def stable_hash(text: str) -> int:
    """Deterministic unsigned 32-bit hash for reproducible non-random tie-breaking."""
    return zlib.crc32(normalize_text(text).encode("utf-8")) & 0xFFFFFFFF


def preferred_role(player: Player) -> str:
    """Return and cache `player`'s preferred concrete role code."""
    code = getattr(player, "puesto", "") or ""
    if code in ROLES and ROLES[code][1] == player.position:
        return code
    key = normalize_text(player.name).strip()
    found = KNOWN_PUESTOS.get(key)
    if found is not None and ROLES[found][1] != player.position:
        found = None
    if found is None:
        h = stable_hash(player.name)
        if player.position == "POR":
            found = "POR"
        elif player.position == "DEF":
            found = ("LI" if (h >> 8) % 2 == 0 else "LD") if h % 100 < 34 else "CE"
        elif player.position == "MED":
            r = h % 100
            found = "MCD" if r < 26 else ("MP" if r < 42 else "MC")
        else:
            r = h % 100
            found = ("EI" if (h >> 8) % 2 == 0 else "ED") if r < 38 else "DC"
    player.puesto = found
    return found


def preferred_role_text(player: Player) -> str:
    """Return the Spanish display label of `player`'s preferred role."""
    return ROLES[preferred_role(player)][0]


def fit(player: Player, code: str) -> float:
    """Return tactical fit score in (0.0 .. 1.0] for `player` playing role `code`."""
    own = preferred_role(player)
    if own == code:
        return 1.0
    r_own, r_new = ROLES[own], ROLES[code]
    if r_own[3] == r_new[3]:
        if r_own[3] in ("LAT", "EXT", "ALA"):
            return 1.0 if r_own[2] == r_new[2] else 0.7
        return 1.0
    if r_own[1] == r_new[1]:
        return 0.55
    return 0.3


def fit_multiplier(value: float) -> float:
    """Translate tactical fit score into an effective-overall multiplier."""
    if value >= 0.95:
        return 1.0
    if value >= 0.7:
        return 0.98
    if value >= 0.55:
        return 0.97
    return 0.90


def fit_text(value: float) -> str:
    """Return Spanish explanation of how well a player fits the assigned role."""
    if value >= 0.95:
        return "juega en su puesto natural"
    if value >= 0.7:
        return "se adapta bien a ese puesto"
    return "juega fuera de su puesto y rendirá algo menos"


def scheme_counts(scheme: str) -> dict[str, int]:
    """Return per-line player counts (POR, DEF, MED, DEL) for a scheme."""
    counts = {"POR": 1, "DEF": 0, "MED": 0, "DEL": 0}
    for code in SCHEMES.get(scheme, SCHEMES[DEFAULT_SCHEME]):
        counts[ROLES[code][1]] += 1
    return counts


def scheme_rows(scheme: str) -> list[tuple[str, list[str]]]:
    """Return left-to-right tactical rows from goalkeeper to forwards for `scheme`."""
    rows = SCHEME_ROWS.get(scheme) or SCHEME_ROWS[DEFAULT_SCHEME]
    return [(label, list(codes)) for label, codes in rows]


def scheme_slot_codes(scheme: str) -> list[str]:
    """Return all 11 slot codes (`POR` + 10 outfield) in row-major order."""
    return ["POR"] + list(SCHEMES.get(scheme) or SCHEMES[DEFAULT_SCHEME])


def scheme_from_roles(codes: Iterable[str]) -> str:
    """Compute a `DEF-MED-DEL` formation code from a sequence of role codes."""
    c = {"DEF": 0, "MED": 0, "DEL": 0}
    for code in codes:
        grp = ROLES[code][1]
        if grp in c:
            c[grp] += 1
    return f"{c['DEF']}-{c['MED']}-{c['DEL']}"


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost bipartite assignment (Hungarian algorithm)."""
    n = len(cost)
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [0] * n
    for j in range(1, n + 1):
        result[p[j] - 1] = j - 1
    return result


def assign_roles(
    xi: list[Player],
    scheme: str,
    fixed: dict[str, str] | None = None,
    goalkeeper: Player | None = None,
) -> tuple[dict[int, str], dict[int, float]]:
    """Assign `scheme` slots across `xi`, honoring `fixed` player->role overrides."""
    codes = list(SCHEMES.get(scheme) or SCHEMES[DEFAULT_SCHEME])
    roles: dict[int, str] = {}
    fits: dict[int, float] = {}
    field: list[Player] = []
    gk = goalkeeper
    if gk is None:
        gk = next((p for p in xi if p.position == "POR"), None)
    for p in xi:
        if p is gk:
            roles[id(p)] = "POR"
            fits[id(p)] = 1.0 if p.position == "POR" else 0.3
        else:
            field.append(p)
    free = list(range(len(codes)))
    rest: list[Player] = []
    for p in field:
        wanted = (fixed or {}).get(p.name)
        slot = next((k for k in free if codes[k] == wanted), None) if wanted else None
        if slot is None:
            rest.append(p)
        else:
            roles[id(p)] = wanted  # type: ignore[assignment]
            free.remove(slot)
    if rest and free:
        n = max(len(rest), len(free))
        cost: list[list[float]] = []
        for a in range(n):
            row: list[float] = []
            for b in range(n):
                if a < len(rest) and b < len(free):
                    row.append(-fit(rest[a], codes[free[b]]) * 1000.0 - rest[a].overall * 0.01)
                else:
                    row.append(0.0)
            cost.append(row)
        for a, b in enumerate(_hungarian(cost)):
            if a < len(rest) and b < len(free):
                roles[id(rest[a])] = codes[free[b]]
    for p in field:
        roles.setdefault(id(p), DEFAULT_ROLE_BY_GROUP.get(p.position, "MC"))
        fits[id(p)] = fit(p, roles[id(p)])
    return roles, fits


def choose_ai_scheme(own_strength: float, rival_strength: float, rng: random.Random) -> str:
    """Choose an AI scheme based on relative team strength."""
    diff = own_strength - rival_strength
    if diff >= 4:
        options = ["4-3-3", "4-3-3", "3-4-3", "4-2-3-1", "3-5-2"]
    elif diff <= -4:
        options = ["5-4-1", "5-3-2", "4-5-1", "4-1-4-1"]
    else:
        options = ["4-4-2", "4-2-3-1", "4-3-3", "4-1-4-1", "3-5-2", "4-5-1"]
    return rng.choice(options)
