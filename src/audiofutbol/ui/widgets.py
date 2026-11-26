"""Accessible audio-first UI widgets (menu, reader, confirm, recap) with visual HUD."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

import pygame

from audiofutbol.domain.formations import preferred_role_text
from audiofutbol.domain.match.board import FormationRowView
from audiofutbol.domain.models import POSITION_ORDER, Team
from audiofutbol.domain.text import normalize_text
from audiofutbol.engine.audio import AudioEngine
from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.engine.window import GameWindow


KEY_NAME_TO_PYGAME: dict[str, int] = {
    "a": pygame.K_a,
    "b": pygame.K_b,
    "c": pygame.K_c,
    "d": pygame.K_d,
    "e": pygame.K_e,
    "f": pygame.K_f,
    "g": pygame.K_g,
    "h": pygame.K_h,
    "i": pygame.K_i,
    "l": pygame.K_l,
    "m": pygame.K_m,
    "n": pygame.K_n,
    "p": pygame.K_p,
    "q": pygame.K_q,
    "r": pygame.K_r,
    "s": pygame.K_s,
    "t": pygame.K_t,
    "v": pygame.K_v,
    "x": pygame.K_x,
    "1": pygame.K_1,
    "2": pygame.K_2,
    "3": pygame.K_3,
    "4": pygame.K_4,
    "5": pygame.K_5,
    "6": pygame.K_6,
    "7": pygame.K_7,
    "f1": pygame.K_F1,
}


def map_shortcut_keys(
    named: dict[str, Callable[[], str | None]] | None
) -> dict[int, Callable[[], str | None]]:
    if not named:
        return {}
    out: dict[int, Callable[[], str | None]] = {}
    for key_name, fn in named.items():
        code = KEY_NAME_TO_PYGAME.get(key_name.lower())
        if code is not None:
            out[code] = fn
    return out


def map_quick_keys(named: dict[str, int] | None) -> dict[int, int]:
    if not named:
        return {}
    out: dict[int, int] = {}
    for key_name, index in named.items():
        code = KEY_NAME_TO_PYGAME.get(key_name.lower())
        if code is not None:
            out[code] = index
    return out


class AudioUI:
    """Renders menus, readers, confirmations, and recaps via TTS + SFX + Pygame HUD."""

    def __init__(
        self, speech: SpeechService, audio: AudioEngine, window: GameWindow
    ) -> None:
        self.speech = speech
        self.audio = audio
        self.window = window
        self._navigation_shortcuts: dict[int, Callable[[], str | None]] = {}

    @contextmanager
    def navigation_shortcuts(self, shortcuts: dict[int, Callable[[], str | None]]):
        """Install temporary non-text navigation bindings without changing global keys."""
        previous = self._navigation_shortcuts
        self._navigation_shortcuts = shortcuts
        try:
            yield
        finally:
            self._navigation_shortcuts = previous

    def speak(self, text: str, interrupt: bool = False) -> None:
        self.speech.speak(text, interrupt=interrupt)

    def _speak_focus(self, text: str, interrupt: bool = False) -> None:
        self.speech.speak(text, interrupt=interrupt, record=False)

    def play_jingle(self, name: str, ms: int, volume: float = 1.0) -> None:
        if not self.audio.config.musica or not self.audio.ok:
            return
        self.audio.play_theme(name, loop=False, volume=volume)
        self.window.pause(ms)
        self.audio.stop_music(1200)

    def menu(
        self,
        title: str,
        options: list[str],
        shortcuts: dict[int, Callable[[], str | None]] | None = None,
        initial_index: int = 0,
        adjust: Callable[[int, int], str | None] | None = None,
        quick_keys: dict[int, int] | None = None,
    ) -> int | None:
        """Accessible keyboard menu with arrows, Home/End, PageUp/Down, letter-jump, Esc."""
        shortcuts = {**self._navigation_shortcuts, **(shortcuts or {})}
        items = list(options)
        total = len(items)
        if total == 0:
            return None
        idx = max(0, min(initial_index, total - 1))

        self.window.set_view(title, items=items, selected_index=idx)
        self._speak_focus(f"{title}. {items[idx]}, {idx + 1} de {total}")

        while True:
            key, ch = self.window.wait_key()
            if key == pygame.K_DOWN:
                idx = (idx + 1) % total
            elif key == pygame.K_UP:
                idx = (idx - 1) % total
            elif key == pygame.K_HOME:
                idx = 0
            elif key == pygame.K_END:
                idx = total - 1
            elif key == pygame.K_PAGEDOWN:
                idx = min(total - 1, idx + 10)
            elif key == pygame.K_PAGEUP:
                idx = max(0, idx - 10)
            elif key in (pygame.K_LEFT, pygame.K_RIGHT) and adjust is not None:
                updated = adjust(idx, 1 if key == pygame.K_RIGHT else -1)
                if updated:
                    items[idx] = updated
                    self.window.set_view(title, items=items, selected_index=idx)
                    self._speak_focus(updated, interrupt=True)
                continue
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.audio.play_sfx("aceptar")
                return idx
            elif key == pygame.K_ESCAPE:
                self.audio.play_sfx("volver")
                return None
            elif quick_keys and key in quick_keys and quick_keys[key] < total:
                self.audio.play_sfx("aceptar")
                return quick_keys[key]
            elif key in shortcuts:
                res = shortcuts[key]()
                if res == "releer":
                    self.window.set_view(title, items=items, selected_index=idx)
                    self._speak_focus(
                        f"{title}. {items[idx]}, {idx + 1} de {total}", interrupt=True
                    )
                continue
            elif ch and ch.isalpha() and total > 5:
                needle = normalize_text(ch)
                for step in range(1, total + 1):
                    cand = (idx + step) % total
                    if normalize_text(items[cand]).startswith(needle):
                        idx = cand
                        break
                else:
                    continue
            else:
                continue

            self.audio.play_sfx("mover")
            self.window.set_view(title, items=items, selected_index=idx)
            self._speak_focus(f"{items[idx]}, {idx + 1} de {total}", interrupt=True)

    def formation_board(
        self,
        title: str,
        rows: list[FormationRowView],
        status_line: str = "",
        shortcuts: dict[int, Callable[[], str | None]] | None = None,
        initial_slot_id: str | None = None,
        allow_remove: bool = False,
        allow_swap_key: bool = False,
    ) -> tuple[str, str] | None:
        """Interactive 2D tactical formation board with spatial stereo chimes and line cues."""
        if not rows:
            return None
        shortcuts = {**self._navigation_shortcuts, **(shortcuts or {})}
        row_idx = 0
        col_idx = 0 if len(rows[0].slots) == 1 else -1
        if initial_slot_id is not None:
            for r_i, r in enumerate(rows):
                for c_i, s in enumerate(r.slots):
                    if s.slot_id == initial_slot_id:
                        row_idx, col_idx = r_i, c_i
                        break

        board_hud_rows = [
            (r.name, [s.short_label for s in r.slots], r.is_action_row) for r in rows
        ]
        hints = ["Arriba/Abajo: líneas", "Izq/Der: puestos", "Enter: elegir"]
        if allow_swap_key:
            hints.append("Espacio: intercambiar")
        if allow_remove:
            hints.append("Supr: quitar")
        if pygame.K_i in shortcuts:
            hints.append("I: resumen")
        hints.append("Esc: volver")
        footer = " | ".join(hints)

        def announce(is_initial: bool = False) -> None:
            row = rows[row_idx]
            self.window.set_board_view(
                title,
                board_hud_rows,
                (row_idx, col_idx),
                status_line=status_line or None,
                footer_hint=footer,
            )
            prefix = f"{title}. " if is_initial else ""
            if col_idx == -1:
                if not is_initial:
                    self.audio.play_sfx("mover")
                total_slots = len(row.slots)
                occ = sum(1 for s in row.slots if s.occupied)
                occ_txt = f", {occ} ocupadas" if occ < total_slots else ""
                self._speak_focus(
                    f"{prefix}{row.name}, {total_slots} posiciones{occ_txt}",
                    interrupt=not is_initial,
                )
                return

            slot = row.slots[col_idx]
            if row.is_action_row:
                if not is_initial:
                    self.audio.play_sfx("mover")
                self._speak_focus(f"{prefix}{slot.label}", interrupt=not is_initial)
                return

            is_line_end = len(row.slots) > 1 and col_idx == len(row.slots) - 1
            self.audio.play_board_ting(
                pan=slot.pan,
                pitch_ratio=row.pitch_ratio,
                is_line_end=is_line_end,
            )
            if len(row.slots) == 1 or is_initial:
                msg = f"{prefix}{row.name}. {slot.label}"
            else:
                msg = slot.label
            self._speak_focus(msg, interrupt=not is_initial)

        announce(is_initial=True)

        while True:
            key, _ = self.window.wait_key()
            row = rows[row_idx]
            if key == pygame.K_DOWN:
                if row_idx < len(rows) - 1:
                    row_idx += 1
                    col_idx = 0 if len(rows[row_idx].slots) == 1 else -1
                    announce()
                else:
                    self.audio.play_board_edge(0.0)
                    self._speak_focus("Fin del esquema.", interrupt=True)
            elif key == pygame.K_UP:
                if row_idx > 0:
                    row_idx -= 1
                    col_idx = 0 if len(rows[row_idx].slots) == 1 else -1
                    announce()
                else:
                    self.audio.play_board_edge(0.0)
                    self._speak_focus("Inicio del esquema.", interrupt=True)
            elif key == pygame.K_RIGHT:
                if len(row.slots) == 1:
                    self.audio.play_board_edge(0.0)
                    self._speak_focus(
                        f"Única posición en {row.name}. {row.slots[0].label}",
                        interrupt=True,
                    )
                elif col_idx == -1:
                    col_idx = 0
                    announce()
                elif col_idx < len(row.slots) - 1:
                    col_idx += 1
                    announce()
                else:
                    self.audio.play_board_edge(1.0)
                    self._speak_focus(f"Fin de {row.name.lower()}.", interrupt=True)
            elif key == pygame.K_LEFT:
                if len(row.slots) == 1:
                    self.audio.play_board_edge(0.0)
                    self._speak_focus(
                        f"Única posición en {row.name}. {row.slots[0].label}",
                        interrupt=True,
                    )
                elif col_idx == -1:
                    col_idx = len(row.slots) - 1
                    announce()
                elif col_idx > 0:
                    col_idx -= 1
                    announce()
                else:
                    self.audio.play_board_edge(-1.0)
                    self._speak_focus(f"Inicio de {row.name.lower()}.", interrupt=True)
            elif key == pygame.K_HOME and len(row.slots) > 1:
                col_idx = 0
                announce()
            elif key == pygame.K_END and len(row.slots) > 1:
                col_idx = len(row.slots) - 1
                announce()
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if col_idx == -1:
                    col_idx = 0
                    announce()
                else:
                    self.audio.play_sfx("aceptar")
                    return ("select", row.slots[col_idx].slot_id)
            elif (
                allow_remove
                and key in (pygame.K_DELETE, pygame.K_BACKSPACE)
                and col_idx >= 0
                and not row.is_action_row
                and row.slots[col_idx].occupied
            ):
                self.audio.play_sfx("volver")
                return ("remove", row.slots[col_idx].slot_id)
            elif (
                allow_swap_key
                and key == pygame.K_SPACE
                and col_idx >= 0
                and not row.is_action_row
            ):
                self.audio.play_sfx("mover")
                return ("swap", row.slots[col_idx].slot_id)
            elif key == pygame.K_ESCAPE:
                self.audio.play_sfx("volver")
                return None
            elif key in shortcuts:
                res = shortcuts[key]()
                if res == "releer":
                    announce()

    def reader(self, title: str, lines: list[str]) -> None:
        """Read a list of lines interactively with arrow keys. Escape/Backspace exits."""
        items = list(lines) or ["Sin datos"]
        total = len(items)
        idx = 0
        self.window.set_view(title, items=items, selected_index=idx)
        self.speech.speak(
            f"{title}. {total} líneas. Flechas para leer, Escape para volver. {items[0]}"
        )
        while True:
            key, _ = self.window.wait_key()
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.audio.play_sfx("volver")
                return
            if key in self._navigation_shortcuts:
                self._navigation_shortcuts[key]()
                continue
            if key == pygame.K_DOWN:
                idx = min(total - 1, idx + 1)
            elif key == pygame.K_UP:
                idx = max(0, idx - 1)
            elif key == pygame.K_HOME:
                idx = 0
            elif key == pygame.K_END:
                idx = total - 1
            elif key == pygame.K_PAGEDOWN:
                idx = min(total - 1, idx + 10)
            elif key == pygame.K_PAGEUP:
                idx = max(0, idx - 10)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                pass
            else:
                continue
            self.window.set_view(title, items=items, selected_index=idx)
            self.speech.speak(f"{items[idx]}, {idx + 1} de {total}", interrupt=True)

    def confirm(self, question: str) -> bool:
        return self.menu(question, ["No", "Sí"]) == 1

    @staticmethod
    def _split_summary_sections(lines: list[str]) -> list[tuple[int, list[str]]]:
        """Partition summary/recap lines into (start_index, section_lines) blocks.

        Sections follow the logical structure:
        1) Goles / Marcador (header + scorers)
        2) Jugadas destacadas (highlights, when present)
        3) Estadísticas del partido
        """
        if not lines:
            return []

        stats_idx: int | None = None
        for i, line in enumerate(lines):
            if line.startswith("Estadísticas del partido") or line.startswith(
                "Posesión del balón:"
            ):
                stats_idx = i
                break

        if stats_idx is None or stats_idx <= 0:
            return [(0, list(lines))]

        pre_stats = lines[:stats_idx]
        stats_lines = lines[stats_idx:]

        # Find where plays/highlights begin after the score/goals header
        plays_idx: int | None = None
        for i, line in enumerate(pre_stats):
            if i == 0:
                continue
            if line.startswith(("Global:", "Goles:", "No hubo goles.")):
                continue
            plays_idx = i
            break

        sections: list[tuple[int, list[str]]] = []
        if plays_idx is not None and plays_idx > 0:
            sections.append((0, pre_stats[:plays_idx]))
            sections.append((plays_idx, pre_stats[plays_idx:]))
        else:
            sections.append((0, pre_stats))
        sections.append((stats_idx, stats_lines))
        return sections

    def _stream_sectioned_lines(
        self, title: str, intro: str, cancel_msg: str, lines: list[str]
    ) -> str:
        """Stream lines grouped by sections (goals, plays, stats).

        - Space jumps immediately to the next section while continuing TTS narration.
        - Escape cancels the remaining stream and announces `cancel_msg`.
        Returns 'completed' or 'cancelled'.
        """
        self.window.set_view(title, items=lines, selected_index=0)
        self.speech.speak(intro)
        act = self.window.wait_or_skip_action(2500)
        if act == "escape":
            self.speech.speak(cancel_msg, interrupt=True)
            return "cancelled"

        sections = self._split_summary_sections(lines)
        for sec_idx, (start_idx, sec_lines) in enumerate(sections):
            interrupt_next = act == "space" or sec_idx > 0
            act = None
            for offset, line in enumerate(sec_lines):
                idx = start_idx + offset
                self.window.set_view(title, items=lines, selected_index=idx)
                self.speech.speak(line, interrupt=(interrupt_next and offset == 0))
                act = self.window.wait_or_skip_action(700 + 50 * len(line))
                if act == "escape":
                    self.speech.speak(cancel_msg, interrupt=True)
                    return "cancelled"
                if act == "space":
                    # Jump to the next section (or finish stream if on the last section)
                    break
        return "completed"

    def stream_summary(self, title: str, lines: list[str]) -> None:
        """Speak summary lines by sections; Space jumps section, Escape cancels to menu."""
        self._stream_sectioned_lines(
            title,
            f"{title}. Espacio para saltar de sección, Escape para cancelar.",
            "Resumen cancelado.",
            lines,
        )

    def recap(self, lines: list[str]) -> None:
        """Post-match highlight stream with section skip and guaranteed post-recap menu."""
        play_stream = True
        while True:
            if play_stream:
                self._stream_sectioned_lines(
                    "Recuento del partido",
                    "Recuento de lo más destacado del partido. Espacio salta entre goles, jugadas y estadísticas. Escape cancela la narración.",
                    "Recuento cancelado.",
                    lines,
                )
            choice = self.menu(
                "Fin del recuento",
                ["Continuar", "Repetir el recuento", "Leer línea por línea"],
            )
            if choice == 1:
                play_stream = True
                continue
            if choice == 2:
                self.reader("Recuento del partido", lines)
                play_stream = False
                continue
            return

    def choose_team(
        self, title: str, teams: list[Team], exclude: Team | None = None
    ) -> Team | None:
        pool = [t for t in teams if t is not exclude]
        idx = self.menu(title, [t.name for t in pool])
        return None if idx is None else pool[idx]


def squad_lines(team: Team) -> list[str]:
    """Format a team's full squad sorted by position and overall rating."""
    xi = team.lineup(team.scheme)
    lines: list[str] = []
    for p in sorted(
        team.players, key=lambda pl: (POSITION_ORDER.get(pl.position, 9), -pl.overall)
    ):
        role = "titular" if p in xi else "suplente"
        extra = ""
        if p.suspended_matches > 0:
            extra += ", sancionado"
        if p.yellow_cards:
            extra += f", {p.yellow_cards} amarilla"
        if p.goals:
            extra += f", {p.goals} goles"
        if p.assists:
            extra += f", {p.assists} pases de gol"
        lines.append(
            f"{p.name}, {preferred_role_text(p)}, calidad {p.overall}, {role}{extra}"
        )
    return lines
