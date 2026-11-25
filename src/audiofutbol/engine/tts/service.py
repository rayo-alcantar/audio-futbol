"""Chain-of-responsibility speech service with navigable history and HUD callback."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Callable, Iterable

from audiofutbol.engine.tts.base import SpeechBackend
from audiofutbol.engine.tts.nvda import NvdaDllBackend
from audiofutbol.engine.tts.sapi import Sapi5Backend


class SpeechService:
    """Routes speech through prioritized backends (NVDA DLL -> SAPI5) without console I/O."""

    def __init__(
        self,
        backends: list[SpeechBackend],
        braille_enabled: bool = True,
        history_size: int = 300,
    ) -> None:
        self._backends = list(backends)
        self.braille_enabled = braille_enabled
        self._history: deque[str] = deque(maxlen=history_size)
        self._cursor: int = -1
        self._last_message = ""
        self._listeners: list[Callable[[str, bool], None]] = []

    def add_listener(self, listener: Callable[[str, bool], None]) -> None:
        """Subscribe a listener (e.g., HUD caption renderer) to spoken messages."""
        self._listeners.append(listener)

    @property
    def last_message(self) -> str:
        return self._last_message

    @property
    def history(self) -> list[str]:
        return list(self._history)

    @property
    def history_cursor(self) -> int:
        return self._cursor

    @property
    def backends(self) -> list[SpeechBackend]:
        return list(self._backends)

    def active_backend_name(self) -> str:
        for backend in self._backends:
            if backend.is_available():
                return backend.name
        return "Sin motor de voz activo"

    def nvda_status_summary(self) -> str:
        for backend in self._backends:
            if isinstance(backend, NvdaDllBackend):
                if backend.is_available():
                    return f"NVDA activo mediante {backend.dll_path.name if backend.dll_path else 'DLL'}."
                if backend.is_dll_loaded():
                    return (
                        f"DLL de NVDA cargada ({backend.dll_path.name if backend.dll_path else ''}), "
                        f"pero NVDA no está abierto. Usando {self.active_backend_name()}."
                    )
                return f"DLL de NVDA no cargada: {backend.error} Usando {self.active_backend_name()}."
        return f"Motor de voz activo: {self.active_backend_name()}."

    def _emit(self, message: str, interrupt: bool) -> bool:
        """Send text to listeners and active TTS/Braille backend without mutating history."""
        for listener in self._listeners:
            try:
                listener(message, interrupt)
            except Exception:
                pass

        for backend in self._backends:
            try:
                if backend.is_available() and backend.speak(message, interrupt=interrupt):
                    if self.braille_enabled:
                        backend.braille(message)
                    return True
            except Exception:
                continue
        return False

    def speak(self, text: str, interrupt: bool = False, *, record: bool = True) -> bool:
        """Speak text; transient focus announcements remain repeatable but out of history."""
        message = str(text)
        if not message:
            return False
        self._last_message = message
        if record:
            self._history.append(message)
            self._cursor = len(self._history) - 1
        elif self._cursor == len(self._history) - 1:
            # From menu focus, the first comma should read the newest saved message.
            self._cursor = len(self._history)
        return self._emit(message, interrupt=interrupt)

    def repeat_last(self) -> bool:
        """Repeat the most recent spoken message without adding a duplicate to history."""
        if not self._last_message:
            return False
        return self._emit(self._last_message, interrupt=True)

    # ------------------------------------------------------- History Navigation
    def history_prev(self) -> bool:
        """Move to the previous message in speech history (comma key)."""
        if not self._history:
            return self._emit("Historial vacío.", interrupt=True)
        self._cursor = max(0, self._cursor - 1)
        return self._emit(self._history[self._cursor], interrupt=True)

    def history_next(self) -> bool:
        """Move to the next message in speech history (period key)."""
        if not self._history:
            return self._emit("Historial vacío.", interrupt=True)
        self._cursor = min(self._cursor + 1, len(self._history) - 1)
        return self._emit(self._history[self._cursor], interrupt=True)

    def history_first(self) -> bool:
        """Jump to the oldest message in speech history (Shift + comma)."""
        if not self._history:
            return self._emit("Historial vacío.", interrupt=True)
        self._cursor = 0
        return self._emit(self._history[0], interrupt=True)

    def history_last(self) -> bool:
        """Jump to the newest message in speech history (Shift + period)."""
        if not self._history:
            return self._emit("Historial vacío.", interrupt=True)
        self._cursor = len(self._history) - 1
        return self._emit(self._history[self._cursor], interrupt=True)

    def silence(self) -> None:
        """Cancel speech on every available backend."""
        for backend in self._backends:
            try:
                if backend.is_available():
                    backend.cancel()
            except Exception:
                pass


def create_default_speech_service(
    dll_search_dirs: Iterable[Path],
    braille_enabled: bool = True,
) -> SpeechService:
    """Build the default Windows-ready speech chain: NVDA DLL first, SAPI5 fallback."""
    nvda = NvdaDllBackend(dll_search_dirs)
    sapi = Sapi5Backend()
    return SpeechService([nvda, sapi], braille_enabled=braille_enabled)
