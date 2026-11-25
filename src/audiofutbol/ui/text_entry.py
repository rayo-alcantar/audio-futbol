"""Keyboard-first text editing for the creation tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from audiofutbol.ui.widgets import AudioUI


def _read_all(value: str, cursor: int) -> str:
    return f"{value or 'Vacío'}. Posición {cursor + 1} de {len(value) + 1}."


def text_entry(ui: AudioUI, label: str, initial: str = "", *, max_length: int = 100) -> str | None:
    """Return the accepted text; Escape discards just the current field."""
    value = initial[:max_length]
    cursor = len(value)
    selected = False
    previous_footer, previous_status = ui.window.hud.footer_hint, ui.window.hud.status_line
    hint = "Enter: aceptar | Escape: cancelar | F1: leer campo | Ctrl+A: seleccionar | Ctrl+V: pegar"

    def speak(message: str) -> None:
        ui.speech.speak(message, interrupt=True, record=False)

    def render() -> None:
        ui.window.set_view(label, items=[value or "Campo vacío"],
                           status_line=f"Posición {cursor + 1} de {len(value) + 1}",
                           footer_hint=hint)

    def insert(text: str) -> None:
        nonlocal value, cursor, selected
        clean = "".join(char for char in text if char.isprintable())
        start, end = (0, len(value)) if selected else (cursor, cursor)
        part = clean[:max_length - len(value) + end - start]
        if not part:
            if clean:
                speak("Llegaste al límite de caracteres.")
            return
        value = value[:start] + part + value[end:]
        cursor = start + len(part)
        selected = False
        speak("Espacio" if part == " " else part)

    render()
    speak(f"{label}. {_read_all(value, cursor)} Enter para aceptar, Escape para cancelar, F1 para leer el campo.")
    pygame.key.start_text_input()
    try:
        while True:
            event = ui.window.wait_text_event()
            if event.type == pygame.TEXTINPUT:
                insert(event.text)
            else:
                key, mods = event.key, getattr(event, "mod", 0)
                if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return value.strip()
                if key == pygame.K_ESCAPE:
                    return None
                if key == pygame.K_F1:
                    speak(_read_all(value, cursor))
                elif mods & pygame.KMOD_CTRL and key == pygame.K_a:
                    selected = bool(value)
                    speak("Texto seleccionado." if selected else "Campo vacío.")
                elif mods & pygame.KMOD_CTRL and key == pygame.K_v:
                    try:
                        paste = pygame.scrap.get_text() or ""
                    except (AttributeError, pygame.error):
                        paste = ""
                    if paste:
                        insert(paste)
                    else:
                        speak("No hay texto en el portapapeles.")
                elif key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                    if selected:
                        value, cursor, selected = "", 0, False
                        speak("Texto borrado.")
                    else:
                        index = cursor - 1 if key == pygame.K_BACKSPACE else cursor
                        if 0 <= index < len(value):
                            speak(f"Borrado: {value[index] if value[index] != ' ' else 'espacio'}.")
                            value = value[:index] + value[index + 1:]
                            cursor = index
                elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_HOME, pygame.K_END):
                    selected = False
                    if key == pygame.K_HOME:
                        cursor = 0
                    elif key == pygame.K_END:
                        cursor = len(value)
                    else:
                        cursor = min(len(value), max(0, cursor + (1 if key == pygame.K_RIGHT else -1)))
                    speak(("Espacio" if value[cursor] == " " else value[cursor]) if cursor < len(value) else "Fin del campo.")
            render()
    finally:
        pygame.key.stop_text_input()
        ui.window.hud.footer_hint, ui.window.hud.status_line = previous_footer, previous_status
