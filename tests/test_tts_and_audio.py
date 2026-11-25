"""Tests for TTS backends (NVDA DLL, SAPI5 fallback, SpeechService), AudioEngine, and GameConfig."""

from __future__ import annotations

from pathlib import Path
import sys

from audiofutbol.engine.audio import (
    AudioEngine,
    MASTER_MUSIC_HEADROOM,
    MASTER_SFX_HEADROOM,
    SOUND_ALIASES,
    perceptual_gain,
)
from audiofutbol.engine.config import GameConfig
from audiofutbol.engine.paths import AppPaths
from audiofutbol.engine.tts.base import NullSpeechBackend
from audiofutbol.engine.tts.nvda import NvdaDllBackend
from audiofutbol.engine.tts.sapi import Sapi5Backend
from audiofutbol.engine.tts.service import SpeechService


class _FakeUnavailableBackend:
    name = "FakeUnavailable"

    def is_available(self) -> bool:
        return False

    def speak(self, text: str, interrupt: bool = False) -> bool:
        return False

    def braille(self, text: str) -> bool:
        return False

    def cancel(self) -> None:
        pass


def test_nvda_dll_loads_from_lib_on_windows() -> None:
    paths = AppPaths.detect()
    nvda = NvdaDllBackend(paths.dll_search_dirs())
    if sys.platform == "win32":
        assert nvda.is_dll_loaded() is True
        assert nvda.dll_path is not None
        assert nvda.dll_path.is_file()
        assert nvda.error == ""


def test_sapi5_initializes_on_windows() -> None:
    sapi = Sapi5Backend()
    if sys.platform == "win32":
        assert sapi.is_available() is True
        assert sapi.error == ""


def test_speech_service_chain_history_and_listener() -> None:
    primary = _FakeUnavailableBackend()
    fallback = NullSpeechBackend()
    service = SpeechService([primary, fallback], braille_enabled=True)

    observed: list[tuple[str, bool]] = []
    service.add_listener(lambda msg, intr: observed.append((msg, intr)))

    assert service.active_backend_name() == fallback.name
    assert service.speak("Gol de Argentina", interrupt=False) is True
    assert service.last_message == "Gol de Argentina"
    assert fallback.spoken == [("Gol de Argentina", False)]
    assert fallback.brailled == ["Gol de Argentina"]
    assert observed == [("Gol de Argentina", False)]

    assert service.repeat_last() is True
    assert fallback.spoken[-1] == ("Gol de Argentina", True)

    service.silence()
    assert fallback.cancel_count == 1


def test_speech_service_history_navigation_and_no_pollution() -> None:
    backend = NullSpeechBackend()
    service = SpeechService([backend])

    # Empty history
    assert service.history_prev() is True
    assert backend.spoken[-1] == ("Historial vacío.", True)
    assert service.history == []

    service.speak("Uno")
    service.speak("Dos")
    service.speak("Tres")
    assert service.history == ["Uno", "Dos", "Tres"]
    assert service.history_cursor == 2

    # Comma -> previous
    service.history_prev()
    assert service.history_cursor == 1
    assert backend.spoken[-1] == ("Dos", True)

    # Shift + Comma -> first
    service.history_first()
    assert service.history_cursor == 0
    assert backend.spoken[-1] == ("Uno", True)

    # Boundary at start
    service.history_prev()
    assert service.history_cursor == 0
    assert backend.spoken[-1] == ("Uno", True)

    # Period -> next
    service.history_next()
    assert service.history_cursor == 1
    assert backend.spoken[-1] == ("Dos", True)

    # Shift + Period -> last
    service.history_last()
    assert service.history_cursor == 2
    assert backend.spoken[-1] == ("Tres", True)

    # Boundary at end
    service.history_next()
    assert service.history_cursor == 2
    assert backend.spoken[-1] == ("Tres", True)

    # Navigation never pollutes history
    assert service.history == ["Uno", "Dos", "Tres"]

    # New speech resets cursor to newest
    service.history_first()
    service.speak("Cuatro")
    assert service.history == ["Uno", "Dos", "Tres", "Cuatro"]
    assert service.history_cursor == 3


def test_menu_speech_keeps_braille_repeat_and_the_full_history_capacity() -> None:
    backend = NullSpeechBackend()
    service = SpeechService([backend], history_size=2)
    service.speak("Gol")
    service.speak("Descanso")
    for index in range(40):
        service.speak(f"Opción {index}", record=False)
    assert service.history == ["Gol", "Descanso"]
    assert backend.brailled[-1] == "Opción 39"
    assert service.repeat_last() is True
    assert backend.spoken[-1] == ("Opción 39", True)
    service.history_prev()
    assert backend.spoken[-1] == ("Descanso", True)
    service.history_prev()
    assert backend.spoken[-1] == ("Gol", True)


def test_audio_engine_indexes_all_normalized_events() -> None:
    paths = AppPaths.detect()
    cfg = GameConfig()
    audio = AudioEngine(paths, cfg, init_mixer=False)
    assert len(audio.files) >= 30
    for event in SOUND_ALIASES:
        assert len(audio.candidates(event)) >= 1, f"Missing sound mapping for event: {event}"
    assert (paths.music_dir / "musica_menu.ogg").is_file()
    for theme in ("musica_versus", "musica_victoria", "musica_derrota", "musica_penales", "musica_fanfarria"):
        assert (paths.themes_dir / f"{theme}.ogg").is_file()


def test_perceptual_volume_curve_is_gentle_at_low_levels() -> None:
    assert perceptual_gain(0.0, 1.0, MASTER_SFX_HEADROOM) == 0.0
    low_sfx = perceptual_gain(0.10, 0.65, MASTER_SFX_HEADROOM)
    mid_sfx = perceptual_gain(0.50, 0.65, MASTER_SFX_HEADROOM)
    high_sfx = perceptual_gain(1.00, 1.00, MASTER_SFX_HEADROOM)
    assert low_sfx < 0.005  # 10% must be genuinely soft, never deafening
    assert low_sfx < mid_sfx < high_sfx <= MASTER_SFX_HEADROOM
    assert perceptual_gain(0.10, 0.65, MASTER_MUSIC_HEADROOM) < 0.004


def test_config_roundtrip_and_clamping(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg = GameConfig(vol_maestro=1.4, vol_musica=1.5, vol_efectos=-0.2, turno_seg=45, var=False, braille=False)
    assert cfg.save(cfg_file) is True

    loaded = GameConfig.load(cfg_file)
    assert loaded.vol_maestro == 1.0
    assert loaded.vol_musica == 1.0
    assert loaded.vol_efectos == 0.0
    assert loaded.turno_seg == 60
    assert loaded.var is False
    assert loaded.braille is False


def test_config_load_recovers_from_corrupted_field_types(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"vol_maestro": "invalid", "vol_musica": null, "turno_seg": "bad", "var": 0, "braille": 1}',
        encoding="utf-8",
    )

    loaded = GameConfig.load(cfg_file)
    assert loaded.vol_maestro == 0.65
    assert loaded.vol_musica == 0.35
    assert loaded.turno_seg == 60
    assert loaded.var is False
    assert loaded.braille is True


def test_goal_and_reaction_sfx_stay_audible_when_ambience_is_low() -> None:
    from unittest.mock import MagicMock

    paths = AppPaths.detect()
    cfg = GameConfig(vol_maestro=0.65, vol_efectos=0.40, vol_ambiente=0.05)
    audio = AudioEngine(paths, cfg, init_mixer=False)
    audio.ok = True
    audio._pygame = MagicMock()
    mock_channel = MagicMock()
    mock_sound = MagicMock()
    mock_sound.play.return_value = mock_channel
    audio._load_sound = MagicMock(return_value=mock_sound)  # type: ignore[method-assign]

    audio.play_sfx("gol")
    gol_left, gol_right = mock_channel.set_volume.call_args[0]
    assert gol_left == gol_right
    assert gol_left > 0.015

    mock_channel.set_volume.reset_mock()
    audio.play_sfx("ovacion")
    ov_left, _ = mock_channel.set_volume.call_args[0]
    assert ov_left > 0.012

    mock_channel.set_volume.reset_mock()
    audio.play_sfx("tribuna")
    trib_left, _ = mock_channel.set_volume.call_args[0]
    assert trib_left < 0.001


def test_board_ting_and_edge_use_equal_power_stereo_pan_and_perceptual_gain() -> None:
    from unittest.mock import MagicMock

    paths = AppPaths.detect()
    cfg = GameConfig(vol_maestro=0.80, vol_efectos=0.50)
    audio = AudioEngine(paths, cfg, init_mixer=False)
    audio.ok = True
    audio._pygame = MagicMock()
    audio._pygame.mixer.get_init.return_value = (44100, -16, 2)

    built_buffers: list[bytes] = []

    def fake_sound(buffer: bytes):
        built_buffers.append(buffer)
        snd = MagicMock()
        snd.play.return_value = MagicMock()
        return snd

    audio._pygame.mixer.Sound.side_effect = fake_sound

    ch_left = audio.play_board_ting(pan=-1.0, pitch_ratio=0.0, is_line_end=False)
    l_vol, r_vol = ch_left.set_volume.call_args[0]
    assert l_vol > 0.0 and r_vol == 0.0 or r_vol < 1e-6

    ch_center = audio.play_board_ting(pan=0.0, pitch_ratio=0.5, is_line_end=False)
    cl_vol, cr_vol = ch_center.set_volume.call_args[0]
    assert abs(cl_vol - cr_vol) < 1e-6

    ch_end = audio.play_board_ting(pan=1.0, pitch_ratio=1.0, is_line_end=True)
    el_vol, er_vol = ch_end.set_volume.call_args[0]
    assert el_vol < 1e-6 and er_vol > 0.0
    assert len(built_buffers[-1]) > len(built_buffers[0])

    ch_edge = audio.play_board_edge(pan=1.0)
    edge_l, edge_r = ch_edge.set_volume.call_args[0]
    assert edge_l < 1e-6 and abs(edge_r - er_vol) < 1e-6


def test_play_menu_music_falls_back_to_bytesio_when_path_load_fails(tmp_path: Path) -> None:
    import io
    from unittest.mock import MagicMock

    music_dir = tmp_path / "musica"
    music_dir.mkdir()
    track = music_dir / "musica_menu.ogg"
    track.write_bytes(b"OggS-fake-menu-track")

    paths = AppPaths(tmp_path)
    cfg = GameConfig(musica=True, vol_maestro=0.6, vol_musica=1.0)
    audio = AudioEngine(paths, cfg, init_mixer=False)
    audio.ok = True
    audio._pygame = MagicMock()
    music = audio._pygame.mixer.music

    load_targets: list[object] = []

    def fake_load(target, **_kwargs):  # type: ignore[no-untyped-def]
        load_targets.append(target)
        if isinstance(target, str):
            raise RuntimeError("SDL path load failed")

    music.load.side_effect = fake_load
    music.get_busy.return_value = True

    audio.play_menu_music()

    assert len(load_targets) == 2
    assert isinstance(load_targets[0], str)
    assert isinstance(load_targets[1], io.BytesIO)
    assert audio._music_stream is load_targets[1]
    music.play.assert_called_once_with(-1)
    assert audio.is_music_playing() is True


def test_ensure_mixer_retries_fallback_and_respects_headless_flag(
    tmp_path: Path, caplog
) -> None:
    import logging
    from unittest.mock import MagicMock

    paths = AppPaths(tmp_path)
    cfg = GameConfig(musica=True)
    audio = AudioEngine(paths, cfg, init_mixer=False)
    assert audio.ok is False
    audio.play_menu_music()
    assert audio.ok is False  # init_mixer=False stays inert without ensure_mixer()

    fake_pg = MagicMock()
    fake_pg.mixer.get_init.side_effect = [None, (44100, -16, 2)]
    attempts = {"n": 0}

    def fake_init(**_kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("default buffer failed")

    fake_pg.mixer.init.side_effect = fake_init
    audio._pygame = fake_pg

    assert audio.ensure_mixer() is True
    assert audio.ok is True
    assert attempts["n"] == 2
    fake_pg.mixer.set_num_channels.assert_called_once_with(32)

    # When every attempt fails, ensure_mixer logs a warning and returns False
    audio2 = AudioEngine(paths, cfg, init_mixer=False)
    broken_pg = MagicMock()
    broken_pg.mixer.get_init.return_value = None
    broken_pg.mixer.init.side_effect = RuntimeError("no audio device")
    audio2._pygame = broken_pg

    with caplog.at_level(logging.WARNING, logger="audiofutbol"):
        assert audio2.ensure_mixer() is False
    assert audio2.ok is False
    assert any("Failed to initialize audio mixer" in rec.message for rec in caplog.records)


def test_is_music_playing_mirrors_mixer_busy(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    audio = AudioEngine(AppPaths(tmp_path), GameConfig(), init_mixer=False)
    assert audio.is_music_playing() is False

    audio.ok = True
    audio._pygame = MagicMock()
    audio._pygame.mixer.music.get_busy.return_value = 1
    assert audio.is_music_playing() is True

    audio._pygame.mixer.music.get_busy.return_value = 0
    assert audio.is_music_playing() is False


def test_app_run_opens_window_before_initializing_mixer(tmp_path: Path, monkeypatch) -> None:
    from audiofutbol.app import AudioFutbolApp
    from audiofutbol.scenes.main_menu import MainMenuScene

    events: list[str] = []
    app = AudioFutbolApp(base_dir=tmp_path, headless=False)
    # Mark non-headless only for call-order spy; avoid opening a real SDL window
    app.window.headless = True
    app.config.buscar_actualizaciones_al_iniciar = False

    monkeypatch.setattr(app.window, "open", lambda: events.append("window.open"))
    monkeypatch.setattr(app.window, "close", lambda: events.append("window.close"))
    monkeypatch.setattr(
        app.audio, "ensure_mixer", lambda force_reinit=False: events.append("audio.ensure_mixer") or True
    )
    monkeypatch.setattr(MainMenuScene, "run", lambda self, ctx: None)

    assert app.run() == 0
    assert events.index("window.open") < events.index("audio.ensure_mixer")



