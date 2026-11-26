"""Listeners can inspect career match logs, availability and situational changes."""

from __future__ import annotations

from collections.abc import Callable

from audiofutbol.domain.competitions.career_core import FIRST_YEAR, SEASON_DAYS, career_date
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.domain.match.conditional_changes import CONDITIONS, ConditionalChange
from audiofutbol.domain.models import POSITION_NAMES_ES
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.career_management import open_menu
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
    def add() -> None:
        if len(career.changes) >= 3:
            ctx.ui.speak("Solo puedes guardar tres reglas. Elimina alguna antes de añadir otra.")
            return
        starters = career.club.lineup(ignore_suspensions=True)
        label = lambda p: f"{p.name}, {POSITION_NAMES_ES[p.position]}, media {p.overall}"
        outgoing = _pick(ctx, "¿Quién sale? Once actual", [label(p) for p in starters])
        if outgoing is None:
            return
        out = starters[outgoing]
        bench = [p for p in career.club.players if p not in starters and (p.position == "POR") == (out.position == "POR")]
        if not bench:
            ctx.ui.speak("No hay suplentes compatibles.")
            return
        incoming = _pick(ctx, "¿Quién entra? Suplentes", [label(p) for p in bench])
        if incoming is None:
            return
        minutes = [45, 55, 60, 65, 70, 75, 80, 85]
        minute = _pick(ctx, "A partir de qué minuto", [f"Minuto {n}" for n in minutes])
        if minute is None:
            return
        options = list(CONDITIONS)
        condition = _pick(ctx, "En qué situación", list(CONDITIONS.values()))
        if condition is None:
            return
        rule = ConditionalChange(minutes[minute], options[condition], out.name, bench[incoming].name)
        if ctx.ui.confirm(f"¿Guardar esta regla? {rule.describe()}"):
            career.set_changes([*career.changes, rule])
            ctx.ui.speak("Cambio programado guardado.")
            changed()

    def remove() -> None:
        entries = career.changes
        index = _pick(ctx, "Elige la regla que quieres quitar", [r.describe() for r in entries])
        if index is not None and ctx.ui.confirm(f"¿Quitar esta regla? {entries[index].describe()}"):
            career.set_changes([r for i, r in enumerate(entries) if i != index])
            ctx.ui.speak("Regla quitada.")
            changed()

    while True:
        selected = open_menu(ctx, f"Cambios por situación. {len(career.changes)} de 3 configurados", [
            ("Leer reglas guardadas", lambda: ctx.ui.reader(
                "Reglas", [r.describe() for r in career.changes] or ["No hay cambios programados."])),
            ("Programar cambio", add),
            ("Quitar una regla", remove),
        ])
        if selected is None:
            return
