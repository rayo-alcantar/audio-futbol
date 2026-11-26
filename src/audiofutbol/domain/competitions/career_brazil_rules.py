"""Competition adapters and promotion/qualification rules for the Brazil career."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.career_brazil_cup import CopaDoBrasil
from audiofutbol.domain.competitions.career_squad import club_key, season_copy
from audiofutbol.domain.competitions.club_tournaments import ClubTournament, CopaLibertadores, CopaSudamericana
from audiofutbol.domain.models import Team

League = BrasileiraoA | BrasileiraoB
LEAGUES = (BrasileiraoA.KEY, BrasileiraoB.KEY)
NATIONAL_CUP = CopaDoBrasil.KEY
CONTINENTAL_TYPES = {CopaLibertadores.KEY: CopaLibertadores, CopaSudamericana.KEY: CopaSudamericana}


class CareerSerieB(BrasileiraoB):
    """Reuse the promotion playoff without presenting an unavailable Série C."""

    def zone_label(self, rank: int, finished: bool) -> str:
        if rank > len(self.teams) - 4:
            return ""
        return super().zone_label(rank, finished)

    def final_summary_lines(self) -> list[str]:
        return super().final_summary_lines()[:-1]


CAREER_DRAWS = {
    BrasileiraoA.KEY: BrasileiraoA, BrasileiraoB.KEY: CareerSerieB,
    NATIONAL_CUP: CopaDoBrasil, **CONTINENTAL_TYPES,
}

# Distinct weekdays avoid overlapping user fixtures; both divisions run in parallel.
_FIXTURE_DAYS = {
    BrasileiraoA.KEY: (5, 7), BrasileiraoB.KEY: (5, 7),
    NATIONAL_CUP: (9, 28), CopaLibertadores.KEY: (13, 21), CopaSudamericana.KEY: (13, 21),
}


def fixture_day(tournament: ClubTournament, step: int | None = None) -> int:
    start, interval = _FIXTURE_DAYS[tournament.KEY]
    return start + interval * (tournament.step_idx if step is None else step)


def _field(clubs: Sequence[Team], managed: str) -> tuple[list[Team], Team]:
    copies = [season_copy(t) for t in clubs]
    return copies, next((team for team in copies if team.name == managed), copies[0])


def start_domestic(
    first: Sequence[Team], second: Sequence[Team], managed: str,
) -> dict[str, ClubTournament]:
    if len(first) != 20 or len(second) != 20 or len({club_key(t.name) for t in (*first, *second)}) != 40:
        raise ValueError("La carrera necesita 20 clubes distintos por división y ninguno repetido.")
    a, user_a = _field(first, managed)
    b, user_b = _field(second, managed)
    cup, user_cup = _field([*first, *second], managed)
    return {
        BrasileiraoA.KEY: BrasileiraoA(None, {t.name: t for t in a}, user_a),
        BrasileiraoB.KEY: CareerSerieB(None, {t.name: t for t in b}, user_b),
        NATIONAL_CUP: CopaDoBrasil(cup, user_cup),
    }


def next_divisions(first: BrasileiraoA, second: BrasileiraoB) -> tuple[list[str], list[str]]:
    a, b = first.standings(), second.standings()
    promoted = [*b[:2], *(second.tie_winner(tie) for tie in second.ties)]
    moving = {team.name for team in promoted}
    # The contribution has two divisions here; the Série C boundary is closed.
    return ([t.name for t in [*a[:-4], *promoted]],
            [t.name for t in b if t.name not in moving] + [t.name for t in a[-4:]])


def continental_qualifiers(first: BrasileiraoA, cup: CopaDoBrasil) -> dict[str, list[str]]:
    order = [t.name for t in first.standings()]
    libertadores = order[:5]
    if cup.champion and cup.champion.name not in libertadores:
        libertadores.append(cup.champion.name)
    return {
        CopaLibertadores.KEY: libertadores,
        CopaSudamericana.KEY: [name for name in order if name not in libertadores][:6],
    }


def start_continental(
    key: str, clubs: Mapping[str, Team], qualifiers: list[str], managed: str,
    data: dict[str, Any], base: Sequence[Team],
) -> ClubTournament:
    selected = [clubs[name] for name in qualifiers]
    seen = {club_key(team.name) for team in selected}
    domestic = {club_key(name) for name in clubs}
    for team in base:
        norm = club_key(team.name)
        country = club_key(team.country)
        if (norm not in seen and norm not in domestic and country != "brasil"
                and (key != CopaLibertadores.KEY or country != "mexico")):
            selected.append(team)
            seen.add(norm)
        if len(selected) == 32:
            break
    if len(selected) != 32:
        raise ValueError("No hay 32 clubes distintos para armar la copa continental.")
    field, user = _field(selected, managed)
    return CONTINENTAL_TYPES[key](data, {t.name: t for t in field}, user)
