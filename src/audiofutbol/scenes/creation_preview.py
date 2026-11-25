"""Interruptible batch simulation for creation previews."""

from __future__ import annotations

from collections.abc import Callable

from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.scenes.base import GameContext


def simulate_preview(
    ctx: GameContext, tournament: NationsLeague | WorldCup, *, stage_only: bool = False,
) -> str:
    if isinstance(tournament, NationsLeague):
        advance: Callable[[], str] = tournament.close_step
    else:
        advance = tournament.close_phase
    ctx.ui.speak("Simulando la prueba. Pulsa Escape para detenerla al terminar la jornada actual.")
    count = 0
    notice = ""
    while tournament.champion is None:
        if stage_only and isinstance(tournament, NationsLeague) and tournament.step_type() != "liga":
            break
        tournament.simulate_remaining(ctx.match_settings())
        notice = advance()
        count += 1
        if tournament.champion is not None:
            break
        if count % 4 == 0:
            ctx.ui.speak(f"{count} jornadas o rondas simuladas. {tournament.phase_name()}.")
        if ctx.window.wait_or_skip_action(20) == "escape":
            ctx.ui.speak("Simulación detenida. Puedes seguir jugando desde aquí o cerrar la prueba.")
            break
    return notice
