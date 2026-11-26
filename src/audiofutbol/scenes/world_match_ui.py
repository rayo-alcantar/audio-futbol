"""Listeners can inspect career match logs, availability and situational changes."""

from __future__ import annotations

from collections.abc import Callable

from audiofutbol.domain.competitions.career_core import FIRST_YEAR, SEASON_DAYS, career_date
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.domain.match.conditional_change_menu import edit_change_plan
from audiofutbol.domain.models import POSITION_NAMES_ES
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.match_scene import PygameMatchIO
from audiofutbol.scenes.world_career_ui import _pick


def read_match_logs(ctx: GameContext, career: WorldCareer) -> None:
    logs = list(reversed(career.match_logs))
    if not logs:
        ctx.ui.speak("No hay bitácoras registradas todavía. Juega o simula un partido.")
        return
    while True:
        pick = _pick(ctx, "Bitácoras del DT, de la más reciente a la más antigua", [
            f"{career_date(log.year, log.day)}. {'Simulado' if log.simulated else 'Jugado'}. {log.score}"
            for log in logs
        ])
        if pick is None:
            return
        log = logs[pick]
        ctx.ui.reader(f"Bitácora. {log.title}", log.lines)


def read_fitness(ctx: GameContext, career: WorldCareer) -> None:
    next_match = next((f for f in career.agenda() if f.user_index is not None), None)
    day = career.elapsed + (next_match.day - career.day if next_match else 0)
    title = "Parte médico y carga para el próximo partido" if next_match else "Parte médico y carga actual"
    lines = []
    for p in sorted(career.club.players, key=lambda pl: (
        not career.fitness.is_injured(career.club, pl, day), -career.fitness.load(career.club, pl, day),
        pl.name,
    )):
        status = f"cansancio {round(career.fitness.load(career.club, p, day))} de 100"
        if career.fitness.is_injured(career.club, p, day):
            recovery = career.fitness.available_on(career.club, p)
            year, date_ = divmod(recovery, SEASON_DAYS)
            status = f"baja hasta el {career_date(year + FIRST_YEAR, date_)}"
        lines.append(f"{p.name}, {POSITION_NAMES_ES[p.position]}: {status}.")
    ctx.ui.reader(title, lines)


def run_change_plans(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    starters = career.club.lineup(ignore_suspensions=True)
    bench = [p for p in career.club.players if p not in starters]
    plan = edit_change_plan(PygameMatchIO(ctx), starters, bench, career.changes)
    if plan != career.changes:
        career.set_changes(plan)
        changed()
