"""Tests for accessible UI widgets, headless GameWindow, and zero-console-dependency guarantee."""

from __future__ import annotations

import ast

import pygame

from audiofutbol.domain.match.board import FormationRowView, FormationSlotView
from audiofutbol.engine.audio import AudioEngine
from audiofutbol.engine.config import GameConfig
from audiofutbol.engine.paths import AppPaths
from audiofutbol.engine.tts.base import NullSpeechBackend
from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.engine.window import GameWindow
from audiofutbol.ui.widgets import AudioUI


def test_no_print_or_input_calls_in_package() -> None:
    """Guarantee zero console stdout/stdin dependency across the entire package."""
    src_root = AppPaths.detect().base_dir / "src" / "audiofutbol"
    offenders: list[str] = []
    for py_file in src_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("print", "input"):
                    offenders.append(f"{py_file.name}:{node.lineno} calls {node.func.id}()")
    assert offenders == []


def test_audio_menu_navigation_and_selection() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)
    audio = AudioEngine(AppPaths.detect(), GameConfig(), init_mixer=False)
    ui = AudioUI(speech, audio, window)

    keys = iter([(pygame.K_DOWN, ""), (pygame.K_RETURN, "\r")])
    window.wait_key = lambda: next(keys)  # type: ignore[method-assign]

    speech.speak("Última jugada")
    selected = ui.menu("Menú de prueba", ["Uno", "Dos", "Tres"])
    assert selected == 1
    assert any("Menú de prueba" in msg for msg, _ in backend.spoken)
    assert any("Dos, 2 de 3" in msg for msg, _ in backend.spoken)
    assert window.hud.selected_index == 1
    assert speech.history == ["Última jugada"]


def test_audio_reader_navigation_and_escape() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)
    audio = AudioEngine(AppPaths.detect(), GameConfig(), init_mixer=False)
    ui = AudioUI(speech, audio, window)

    keys = iter([(pygame.K_DOWN, ""), (pygame.K_ESCAPE, "")])
    window.wait_key = lambda: next(keys)  # type: ignore[method-assign]

    ui.reader("Tabla", ["Linea 1", "Linea 2"])
    assert any("Linea 2, 2 de 2" in msg for msg, _ in backend.spoken)


def test_global_history_shortcuts_in_game_window() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)

    speech.speak("Mensaje 1")
    speech.speak("Mensaje 2")
    speech.speak("Mensaje 3")

    ev_prev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_COMMA, mod=0, unicode=",")
    ev_next = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PERIOD, mod=0, unicode=".")
    ev_first = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_COMMA, mod=pygame.KMOD_SHIFT, unicode=";")
    ev_last = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PERIOD, mod=pygame.KMOD_SHIFT, unicode=":")

    assert window._handle_global_keydown(ev_prev) is True
    assert backend.spoken[-1] == ("Mensaje 2", True)

    assert window._handle_global_keydown(ev_first) is True
    assert backend.spoken[-1] == ("Mensaje 1", True)

    assert window._handle_global_keydown(ev_next) is True
    assert backend.spoken[-1] == ("Mensaje 2", True)

    assert window._handle_global_keydown(ev_last) is True
    assert backend.spoken[-1] == ("Mensaje 3", True)


def test_recap_space_skips_between_sections_and_always_opens_menu() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)
    audio = AudioEngine(AppPaths.detect(), GameConfig(), init_mixer=False)
    ui = AudioUI(speech, audio, window)

    lines = [
        "Resultado final: Argentina 2, Francia 1",
        "Global: Argentina 3, Francia 2",
        "Minuto 14. Gol de Messi, de Argentina.",
        "Minuto 52. Poste de Mbappé, de Francia.",
        "Estadísticas del partido.",
        "Posesión del balón: Argentina 55 por ciento, Francia 45 por ciento.",
        "Tiros: Argentina 8, 5 a puerta. Francia 6, 3 a puerta.",
    ]

    # Wait sequence:
    # 1) intro -> None (let goals section start)
    # 2) first line of goals -> 'space' (jump to plays section)
    # 3) first line of plays -> 'space' (jump to stats section)
    # 4) first line of stats -> 'space' (finish stream and open menu)
    actions = iter([None, "space", "space", "space"])
    window.wait_or_skip_action = lambda _ms: next(actions, None)  # type: ignore[method-assign]
    window.wait_key = lambda: (pygame.K_RETURN, "\r")  # type: ignore[method-assign]

    ui.recap(lines)
    spoken_msgs = [msg for msg, _ in backend.spoken]

    # First line of each section was narrated, while skipped lines inside sections were omitted
    assert "Resultado final: Argentina 2, Francia 1" in spoken_msgs
    assert "Global: Argentina 3, Francia 2" not in spoken_msgs
    assert "Minuto 14. Gol de Messi, de Argentina." in spoken_msgs
    assert "Minuto 52. Poste de Mbappé, de Francia." not in spoken_msgs
    assert "Estadísticas del partido." in spoken_msgs
    assert "Posesión del balón: Argentina 55 por ciento, Francia 45 por ciento." not in spoken_msgs
    # Menu "Fin del recuento" is always presented
    assert any("Fin del recuento" in msg for msg in spoken_msgs)


def test_recap_escape_cancels_narration_but_still_shows_post_recap_menu() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)
    audio = AudioEngine(AppPaths.detect(), GameConfig(), init_mixer=False)
    ui = AudioUI(speech, audio, window)

    lines = [
        "Resultado final: España 1, Italia 0",
        "Minuto 70. Gol de Morata, de España.",
        "Estadísticas del partido.",
        "Posesión del balón: España 60 por ciento, Italia 40 por ciento.",
    ]

    # Press Escape immediately on the first line
    actions = iter([None, "escape"])
    window.wait_or_skip_action = lambda _ms: next(actions, None)  # type: ignore[method-assign]
    window.wait_key = lambda: (pygame.K_RETURN, "\r")  # type: ignore[method-assign]

    ui.recap(lines)
    spoken_msgs = [msg for msg, _ in backend.spoken]

    assert "Recuento cancelado." in spoken_msgs
    assert "Minuto 70. Gol de Morata, de España." not in spoken_msgs
    assert any("Fin del recuento" in msg for msg in spoken_msgs)


def test_formation_board_navigation_audio_cues_and_boundaries() -> None:
    backend = NullSpeechBackend()
    speech = SpeechService([backend])
    window = GameWindow(speech, headless=True)
    audio = AudioEngine(AppPaths.detect(), GameConfig(), init_mixer=False)

    ting_calls: list[tuple[float, float, bool]] = []
    edge_calls: list[float] = []
    audio.play_board_ting = lambda pan=0.0, pitch_ratio=0.0, is_line_end=False: ting_calls.append(  # type: ignore[method-assign]
        (round(pan, 2), round(pitch_ratio, 2), is_line_end)
    )
    audio.play_board_edge = lambda pan=0.0: edge_calls.append(round(pan, 2))  # type: ignore[method-assign]

    ui = AudioUI(speech, audio, window)
    rows = [
        FormationRowView(
            name="Portería",
            pitch_ratio=0.0,
            slots=(FormationSlotView("slot:0", "Portero: Dibu Martínez", "POR: Dibu", 0.0),),
        ),
        FormationRowView(
            name="Zona defensiva",
            pitch_ratio=0.33,
            slots=(
                FormationSlotView("slot:1", "Lateral izquierdo: Tagliafico", "LI: Tagliafico", -1.0),
                FormationSlotView("slot:2", "Central izquierdo: Lisandro", "CEI: Lisandro", -0.33),
                FormationSlotView("slot:3", "Central derecho: Romero", "CED: Romero", 0.33),
                FormationSlotView("slot:4", "Lateral derecho: Molina", "LD: Molina", 1.0),
            ),
        ),
        FormationRowView(
            name="Confirmar",
            pitch_ratio=1.0,
            is_action_row=True,
            slots=(FormationSlotView("action:accept", "Aceptar alineación", "Aceptar", 0.0, is_action=True),),
        ),
    ]

    keys = iter(
        [
            (pygame.K_DOWN, ""),   # enter Zona defensiva header
            (pygame.K_RIGHT, ""),  # LI (-1.0)
            (pygame.K_RIGHT, ""),  # CEI (-0.33)
            (pygame.K_RIGHT, ""),  # CED (+0.33)
            (pygame.K_RIGHT, ""),  # LD (+1.0, line_end=True)
            (pygame.K_RIGHT, ""),  # past right edge -> boundary beep
            (pygame.K_DOWN, ""),   # Confirmar / Aceptar
            (pygame.K_RETURN, "\r"),
        ]
    )
    window.wait_key = lambda: next(keys)  # type: ignore[method-assign]

    result = ui.formation_board("Alineación 4-3-3", rows)
    assert result == ("select", "action:accept")
    assert ting_calls == [
        (0.0, 0.0, False),
        (-1.0, 0.33, False),
        (-0.33, 0.33, False),
        (0.33, 0.33, False),
        (1.0, 0.33, True),
    ]
    assert edge_calls == [1.0]
    spoken_msgs = [msg for msg, _ in backend.spoken]
    assert any("Zona defensiva, 4 posiciones" in m for m in spoken_msgs)
    assert any("Fin de zona defensiva." in m for m in spoken_msgs)
    assert speech.history == []


