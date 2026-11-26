"""Competition registry and deserialization factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.club_tournaments import (
    ChampionsLeague,
    CopaInteramericana,
    CopaLibertadores,
    CopaPersonalizada,
    CopaSudamericana,
    LaLiga,
    Liga1Peru,
    LigaArgentina,
    LigaMX,
    PremierLeague,
)
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup


@dataclass(frozen=True)
class ClubCompetitionSpec:
    """Metadata describing a club competition JSON and class."""

    key: str
    title: str
    menu_label: str
    json_filename: str
    cls: type[Any]
    intro_text: str


CLUB_COMPETITIONS: dict[str, ClubCompetitionSpec] = {
    "champions": ClubCompetitionSpec(
        key="champions",
        title="Liga de Campeones de la UEFA",
        menu_label="Liga de Campeones",
        json_filename="champions_2026_27.json",
        cls=ChampionsLeague,
        intro_text=(
            "Liga de Campeones con 36 clubes. Cada club juega 8 partidos en la fase de liga. "
            "Los 8 primeros pasan directo a octavos y del puesto 9 al 24 juegan un play-off."
        ),
    ),
    "libertadores": ClubCompetitionSpec(
        key="libertadores",
        title="Copa Libertadores",
        menu_label="Copa Libertadores",
        json_filename="libertadores_mx_2026.json",
        cls=CopaLibertadores,
        intro_text=(
            "Copa Libertadores con 32 clubes en 8 grupos de 4. Pasan los dos primeros de cada grupo. "
            "No hay gol de visitante ni tiempo extra hasta la final."
        ),
    ),
    "sudamericana": ClubCompetitionSpec(
        key="sudamericana",
        title="Copa Sudamericana",
        menu_label="Copa Sudamericana",
        json_filename="sudamericana_2026.json",
        cls=CopaSudamericana,
        intro_text=(
            "Copa Sudamericana con 32 clubes en 8 grupos de 4: 28 sudamericanos y 4 mexicanos. "
            "Pasan los dos primeros de cada grupo. No hay gol de visitante ni tiempo extra hasta la final."
        ),
    ),
    "interamericana": ClubCompetitionSpec(
        key="interamericana",
        title="Copa Interamericana",
        menu_label="Copa Interamericana",
        json_filename="interamericana_2026.json",
        cls=CopaInteramericana,
        intro_text=(
            "Copa Interamericana con 64 clubes de toda América en 16 grupos de 4, sorteados ahora con cuatro bombos. "
            "Pasan los dos primeros de cada grupo a dieciseisavos de final. "
            "No hay gol de visitante ni tiempo extra hasta la final."
        ),
    ),
    "ligamx": ClubCompetitionSpec(
        key="ligamx",
        title="Liga MX",
        menu_label="Liga MX",
        json_filename="ligamx_apertura_2026.json",
        cls=LigaMX,
        intro_text=(
            "Liga MX Apertura 2026 con 18 clubes. Son 17 jornadas de todos contra todos. "
            "Los 8 primeros pasan directo a la liguilla, sin play-in: cuartos, semifinales y final a ida y vuelta. "
            "Si el global se empata en cuartos o semifinales, pasa el mejor ubicado en la tabla."
        ),
    ),
    "premier": ClubCompetitionSpec(
        key="premier",
        title="Premier League",
        menu_label="Premier League",
        json_filename="premier_league_2026_27.json",
        cls=PremierLeague,
        intro_text=(
            "Premier League 2026-27 con 20 clubes. Son 38 jornadas, todos contra todos "
            "a ida y vuelta. No hay playoffs: el que termina primero es el campeón. "
            "Los tres últimos descienden."
        ),
    ),
    "laliga": ClubCompetitionSpec(
        key="laliga",
        title="LaLiga",
        menu_label="LaLiga",
        json_filename="laliga_2026_27.json",
        cls=LaLiga,
        intro_text=(
            "LaLiga 2026-27 con 20 clubes. Son 38 jornadas, todos contra todos "
            "a ida y vuelta. No hay playoffs: el que termina primero es el campeón. "
            "Los cuatro primeros van a la Liga de Campeones y los tres últimos descienden."
        ),
    ),
    "liga1": ClubCompetitionSpec(
        key="liga1",
        title="Liga 1 de Perú",
        menu_label="Liga 1 de Perú",
        json_filename="liga1_peru_2026.json",
        cls=Liga1Peru,
        intro_text=(
            "Liga 1 de Perú 2026 con 18 clubes. Se juegan dos torneos cortos de 17 fechas, "
            "el Apertura y el Clausura. Si un mismo club gana los dos, es campeón. "
            "Si no, juegan playoffs a ida y vuelta los dos ganadores y los mejores de la "
            "tabla acumulada. Los dos últimos del acumulado descienden."
        ),
    ),
    "liga_argentina": ClubCompetitionSpec(
        key="liga_argentina",
        title="Liga Profesional Argentina",
        menu_label="Liga Profesional Argentina",
        json_filename="liga_argentina_2025.json",
        cls=LigaArgentina,
        intro_text=(
            "Liga Profesional Argentina con 20 clubes. Son 38 jornadas, todos contra todos "
            "a ida y vuelta. No hay playoffs: el que termina primero es el campeón. "
            "Los cuatro primeros clasifican a la Libertadores, del quinto al noveno a la "
            "Sudamericana y los dos últimos descienden."
        ),
    ),
    BrasileiraoA.KEY: ClubCompetitionSpec(
        key=BrasileiraoA.KEY,
        title=BrasileiraoA.TITLE,
        menu_label="Brasileirão Série A 2026",
        json_filename="brasileirao_a_2026.json",
        cls=BrasileiraoA,
        intro_text=(
            "Brasileirão Série A 2026 con 20 clubes, 38 jornadas de ida y vuelta y un "
            "calendario generado por el juego. El primero es campeón y los cuatro últimos "
            "descienden. La tabla indica las zonas base de Libertadores y Sudamericana."
        ),
    ),
    BrasileiraoB.KEY: ClubCompetitionSpec(
        key=BrasileiraoB.KEY,
        title=BrasileiraoB.TITLE,
        menu_label="Brasileirão Série B 2026",
        json_filename="brasileirao_b_2026.json",
        cls=BrasileiraoB,
        intro_text=(
            "Brasileirão Série B 2026 con 20 clubes y un calendario generado de 38 jornadas. "
            "El primero es campeón. Los dos primeros ascienden directamente. "
            "El tercero juega contra el sexto, y el cuarto contra el quinto, a ida y vuelta. "
            "Si el global se empata, asciende el mejor ubicado en la tabla. "
            "Los cuatro últimos descienden."
        ),
    ),
}

SAVE_SLOTS: tuple[tuple[str, str], ...] = (
    ("mundial", "Mundial"),
    ("liga", "Liga de Naciones"),
    ("champions", "Liga de Campeones"),
    ("libertadores", "Copa Libertadores"),
    ("sudamericana", "Copa Sudamericana"),
    ("interamericana", "Copa Interamericana"),
    ("ligamx", "Liga MX"),
    ("premier", "Premier League"),
    ("laliga", "LaLiga"),
    ("liga1", "Liga 1 de Perú"),
    ("liga_argentina", "Liga Profesional Argentina"),
    (BrasileiraoA.KEY, CLUB_COMPETITIONS[BrasileiraoA.KEY].menu_label),
    (BrasileiraoB.KEY, CLUB_COMPETITIONS[BrasileiraoB.KEY].menu_label),
    ("copa_personalizada", "Copa personalizada"),
)

_CLASS_BY_TYPE: dict[str, type[Any]] = {
    "mundial": WorldCup,
    "liga": NationsLeague,
    "champions": ChampionsLeague,
    "libertadores": CopaLibertadores,
    "sudamericana": CopaSudamericana,
    "interamericana": CopaInteramericana,
    "ligamx": LigaMX,
    "premier": PremierLeague,
    "laliga": LaLiga,
    "liga1": Liga1Peru,
    "liga_argentina": LigaArgentina,
    BrasileiraoA.KEY: BrasileiraoA,
    BrasileiraoB.KEY: BrasileiraoB,
    "copa_personalizada": CopaPersonalizada,
}


def deserialize_competition(data: dict[str, Any]) -> Any:
    """Reconstruct a competition instance from a saved JSON dictionary."""
    comp_type = str(data.get("type", ""))
    cls = _CLASS_BY_TYPE.get(comp_type)
    if cls is None:
        raise ValueError(f"Unknown saved competition type: {comp_type!r}")
    return cls.from_dict(data)
