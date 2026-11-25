"""Friendly / single knockout match flow."""

from __future__ import annotations

from audiofutbol.domain.match.commentary import CommentaryContext
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.models import Team, format_result_text
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.match_scene import PygameMatchIO


def run_friendly_match(ctx: GameContext) -> None:
    pool = sorted(
        ctx.national_teams + ctx.extra_national_teams, key=lambda t: -t.strength()
    )
    user_team = ctx.ui.choose_team("Elige tu selección", pool)
    if user_team is None:
        return
    rival = ctx.ui.choose_team(
        "Elige a tu rival", pool, exclude=user_team
    )
    if rival is None:
        return
    mode = ctx.ui.menu(
        "Tipo de partido",
        [
            "Amistoso, puede terminar en empate",
            "Eliminatoria, con tiempo extra y penales",
        ],
    )
    if mode is None:
        return

    play_friendly(ctx, user_team, rival, knockout=(mode == 1))


def play_friendly(ctx: GameContext, user_team: Team, rival: Team, *, knockout: bool = False) -> None:
    """Run a match on independent copies, including when previewing a draft."""
    user_team, rival = (Team.from_dict(team.to_dict()) for team in (user_team, rival))
    venue_pair = ctx.stadiums.venue_for(user_team)
    venue = f"{venue_pair[0]}, ciudad de {venue_pair[1]}" if venue_pair else None
    stadium, city = venue_pair or ("", "")

    ctx.audio.stop_music()
    engine = MatchEngine(
        user_team=user_team,
        rival_team=rival,
        io=PygameMatchIO(ctx),
        settings=ctx.match_settings(),
        knockout=knockout,
        title="Amistoso",
        stadium=venue,
        commentary_context=CommentaryContext(stadium=stadium, city=city),
    )
    result = engine.play()
    ctx.window.update_status("")
    ctx.audio.play_menu_music()

    g0, g1 = result.goals
    if not engine.state.abandoned:
        ctx.ui.recap(engine.state.recap_lines())
    ctx.ui.speak(
        "Resultado final: "
        + format_result_text(user_team, rival, g0, g1, result.penalties)
    )
