"""Main menu scene (New Game, Saved Games, Options, Exit)."""

from __future__ import annotations

from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS
from audiofutbol.scenes.base import GameContext, Scene
from audiofutbol.scenes.creation import run_creation_menu
from audiofutbol.scenes.friendly import run_friendly_match
from audiofutbol.scenes.league_hub import (
    continue_saved_league,
    start_custom_cup,
    start_new_club_competition,
    start_new_nations_league,
)
from audiofutbol.scenes.options import run_options_menu
from audiofutbol.scenes.updater_scene import check_updates_on_startup_if_ready
from audiofutbol.scenes.world_cup_hub import continue_world_cup, start_new_world_cup
from audiofutbol.version import APP_NAME, VERSION


def _start_brasileirao(ctx: GameContext) -> None:
    divisions = [CLUB_COMPETITIONS[key] for key in ("brasileirao_a", "brasileirao_b")]
    choice = ctx.ui.menu(
        "Brasileirão. Elige la división", [spec.menu_label for spec in divisions] + ["Volver"]
    )
    if choice is not None and choice < len(divisions):
        start_new_club_competition(ctx, divisions[choice].key)


class MainMenuScene:
    """Root navigation scene."""

    def run(self, ctx: GameContext) -> Scene | None:
        ctx.audio.play_menu_music()
        ctx.ui.speak(f"Bienvenido a {APP_NAME}, versión {VERSION}.")
        source_txt = (
            "desde tu base de datos" if ctx.loaded_from_csv else "de ejemplo"
        )
        ctx.ui.speak(f"Se han cargado {len(ctx.national_teams)} selecciones {source_txt}.")
        check_updates_on_startup_if_ready(ctx)

        new_game_entries = [
            ("Mundial", lambda: start_new_world_cup(ctx)),
            ("Liga de Naciones", lambda: start_new_nations_league(ctx)),
            ("Liga de Campeones", lambda: start_new_club_competition(ctx, "champions")),
            ("Copa Libertadores", lambda: start_new_club_competition(ctx, "libertadores")),
            ("Copa Sudamericana", lambda: start_new_club_competition(ctx, "sudamericana")),
            ("Copa Interamericana", lambda: start_new_club_competition(ctx, "interamericana")),
            ("Liga MX", lambda: start_new_club_competition(ctx, "ligamx")),
            ("Premier League", lambda: start_new_club_competition(ctx, "premier")),
            ("LaLiga", lambda: start_new_club_competition(ctx, "laliga")),
            ("Liga 1 de Perú", lambda: start_new_club_competition(ctx, "liga1")),
            ("Liga Profesional Argentina", lambda: start_new_club_competition(ctx, "liga_argentina")),
            ("Brasileirão", lambda: _start_brasileirao(ctx)),
            ("Copa de clubes personalizada", lambda: start_custom_cup(ctx)),
            ("Partido amistoso", lambda: run_friendly_match(ctx)),
        ]

        while True:
            if ctx.config.musica and not ctx.audio.is_music_playing():
                ctx.audio.play_menu_music()
            choice = ctx.ui.menu(
                "Menú principal",
                ["Nuevo juego", "Partidas guardadas", "Crear", "Opciones", "Salir"],
            )
            if choice is None or choice == 4:
                ctx.ui.speak("Hasta luego.", interrupt=True)
                ctx.window.pause(600)
                return None

            if choice == 0:
                sub = ctx.ui.menu(
                    "Nuevo juego. Elige la competición",
                    [label for label, _ in new_game_entries] + ["Volver"],
                )
                if sub is not None and sub < len(new_game_entries):
                    new_game_entries[sub][1]()
            elif choice == 1:
                saved = ctx.saves.list_saved_slots()
                if not saved:
                    ctx.ui.speak("No hay partidas guardadas todavía.")
                    continue
                labels = [
                    f"Continuar {name} guardado"
                    if name == "Mundial"
                    else f"Continuar {name} guardada"
                    for _, name in saved
                ] + ["Volver"]
                sub = ctx.ui.menu("Partidas guardadas. Elige cuál continuar", labels)
                if sub is not None and sub < len(saved):
                    slot_key = saved[sub][0]
                    if slot_key == "mundial":
                        continue_world_cup(ctx)
                    else:
                        continue_saved_league(ctx, slot_key)
            elif choice == 2:
                run_creation_menu(ctx)
            elif choice == 3:
                run_options_menu(ctx)
