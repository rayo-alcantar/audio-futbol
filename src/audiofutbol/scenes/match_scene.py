"""Pygame/TTS MatchIO adapter and tournament match runner."""

from __future__ import annotations

from typing import Any, Callable

from audiofutbol.domain.competitions.attendance import calculate_attendance
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.match.board import FormationRowView
from audiofutbol.domain.match.commentary import CommentaryContext
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.models import format_result_text
from audiofutbol.scenes.base import GameContext
from audiofutbol.ui.widgets import map_quick_keys, map_shortcut_keys


class PygameMatchIO:
    """Adapts MatchEngine port calls to SpeechService, AudioEngine, and GameWindow."""

    def __init__(self, ctx: GameContext) -> None:
        self.ctx = ctx

    def speak(self, text: str, interrupt: bool = False) -> None:
        self.ctx.speech.speak(text, interrupt=interrupt)

    def play_sfx(
        self, event: str, pan: float | None = None, volume: float = 1.0
    ) -> None:
        self.ctx.audio.play_sfx(event, pan=pan, volume=volume)

    def start_crowd(self, attendance_factor: float) -> None:
        self.ctx.audio.start_crowd_ambience(attendance_factor)

    def stop_crowd(self) -> None:
        self.ctx.audio.stop_crowd_ambience()

    def play_theme(self, name: str, loop: bool = False, volume: float = 1.0) -> None:
        self.ctx.audio.play_theme(name, loop=loop, volume=volume)

    def play_menu_music(self) -> None:
        self.ctx.audio.play_menu_music()

    def stop_music(self, fade_ms: int = 1200) -> None:
        self.ctx.audio.stop_music(fade_ms)

    def play_jingle(self, name: str, ms: int, volume: float = 1.0) -> None:
        self.ctx.ui.play_jingle(name, ms, volume=volume)

    def pause(self, ms: int) -> None:
        self.ctx.window.pause(ms)

    def choose(
        self,
        title: str,
        options: list[str],
        shortcuts: dict[str, Callable[[], str | None]] | None = None,
        quick_keys: dict[str, int] | None = None,
        initial_index: int = 0,
    ) -> int | None:
        return self.ctx.ui.menu(
            title,
            options,
            shortcuts=map_shortcut_keys(shortcuts),
            initial_index=initial_index,
            quick_keys=map_quick_keys(quick_keys),
        )

    def choose_formation(
        self,
        title: str,
        rows: list[FormationRowView],
        status_line: str = "",
        shortcuts: dict[str, Callable[[], str | None]] | None = None,
        initial_slot_id: str | None = None,
        allow_remove: bool = False,
        allow_swap_key: bool = False,
    ) -> tuple[str, str] | None:
        return self.ctx.ui.formation_board(
            title,
            rows,
            status_line=status_line,
            shortcuts=map_shortcut_keys(shortcuts),
            initial_slot_id=initial_slot_id,
            allow_remove=allow_remove,
            allow_swap_key=allow_swap_key,
        )

    def confirm(self, question: str) -> bool:
        return self.ctx.ui.confirm(question)

    def read_lines(self, title: str, lines: list[str]) -> None:
        self.ctx.ui.reader(title, lines)

    def read_summary_stream(self, title: str, lines: list[str]) -> None:
        self.ctx.ui.stream_summary(title, lines)

    def update_hud(self, status_line: str) -> None:
        self.ctx.window.update_status(status_line)


def _commentary_context(ctx: GameContext, tournament: Any, idx: int) -> CommentaryContext:
    if isinstance(tournament, WorldCup):
        group_stage = tournament.phases[tournament.phase_idx][1] == "g"
        return CommentaryContext(home_index=None, for_points=group_stage)
    if not isinstance(tournament, NationsLeague):
        return CommentaryContext(home_index=None)

    home, _ = tournament.pairs[idx]
    home_index = 0 if home is tournament.user_team else 1
    stadium, city = tournament.venue(idx, ctx.stadiums.venue_for) or ("", "")
    stage = tournament.step_type()
    if stage == "unico" and getattr(tournament, "is_neutral", lambda: True)():
        return CommentaryContext(home_index=None, stadium=stadium, city=city)

    recent: list[int] = []
    for _, a, b, ga, gb, _ in reversed(tournament.history):
        if a is home or b is home:
            recent.append(ga - gb if a is home else gb - ga)
            if len(recent) == 3:
                break
    ordered = tournament.standings() if stage == "liga" else []
    group = next((g for g in tournament.groups or [] if home in g), None)
    leader = next((t for t in ordered if group is None or t in group), None)
    return CommentaryContext(
        home_index=home_index,
        stadium=stadium,
        city=city,
        for_points=stage == "liga",
        home_leading=leader is home and tournament.table[home.name]["pj"] > 0,
        home_unbeaten=len(recent) == 3 and min(recent) >= 0 and sum(g > 0 for g in recent) >= 2,
        home_winning=len(recent) == 3 and min(recent) > 0,
    )


def run_tournament_match(ctx: GameContext, tournament: Any, simulate: bool) -> None:
    """Play or simulate the user's current match in any competition and register it."""
    idx = tournament.user_match_index()
    if idx is None:
        return
    a, b = tournament.pairs[idx]
    rival = b if a is tournament.user_team else a
    extra = (
        tournament.match_kwargs(idx, tournament.user_team)
        if hasattr(tournament, "match_kwargs")
        else {}
    )
    venue = (
        tournament.venue_text(idx, ctx.stadiums.venue_for)
        if hasattr(tournament, "venue_text")
        else None
    )
    attendance = calculate_attendance(tournament, idx) if venue else None

    engine = MatchEngine(
        user_team=tournament.user_team,
        rival_team=rival,
        io=PygameMatchIO(ctx),
        settings=ctx.match_settings(),
        knockout=tournament.is_knockout(),
        auto=simulate,
        title=tournament.phase_name(),
        max_substitutions=5,
        stadium=venue,
        attendance=attendance,
        commentary_context=None if simulate else _commentary_context(ctx, tournament, idx),
        **extra,
    )
    if simulate:
        ctx.ui.speak(f"Simulando {tournament.user_team.name} contra {rival.name}.")
    else:
        ctx.audio.stop_music()

    result = engine.play()
    ga, gb, pen = tournament.register_result(idx, tournament.user_team, result)
    ctx.window.update_status("")
    if not simulate:
        ctx.audio.play_menu_music()

    showed_recap = False
    if not simulate and not engine.state.abandoned:
        ctx.ui.recap(engine.state.recap_lines())
        showed_recap = True

    ctx.ui.speak("Resultado: " + format_result_text(a, b, ga, gb, pen))
    if engine.state.first_leg is not None and not engine.state.abandoned:
        agg = engine.state.aggregate()
        ctx.ui.speak(
            f"Global de la llave: {engine.state.team_name(0)} {agg[0]}, "
            f"{engine.state.team_name(1)} {agg[1]}."
        )
    if result.scorers and not showed_recap:
        goals_txt = ". ".join(
            f"{p.name}, de {team.name}, minuto {m}" for team, p, m in result.scorers
        )
        ctx.ui.speak(f"Goles: {goals_txt}")
