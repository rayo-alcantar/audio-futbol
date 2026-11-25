"""Accessible no-console Pygame window with high-contrast HUD and event loop."""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame

from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.version import APP_NAME, VERSION


BG_COLOR = (12, 18, 30)
PANEL_COLOR = (22, 32, 52)
STATUS_BG = (28, 44, 72)
ACCENT_COLOR = (255, 208, 64)
TEXT_COLOR = (240, 245, 255)
MUTED_COLOR = (165, 180, 205)
SELECTED_BG = (38, 68, 120)
BORDER_COLOR = (65, 95, 145)


class QuitRequested(Exception):
    """Raised when the user closes the game window cleanly."""


@dataclass
class HudState:
    """Current visual representation mirrored from the audio interface."""

    screen_title: str = f"{APP_NAME} {VERSION}"
    status_line: str = ""
    last_spoken: str = ""
    items: list[str] = field(default_factory=list)
    selected_index: int = 0
    board_rows: list[tuple[str, list[str], bool]] | None = None
    board_cursor: tuple[int, int] = (0, 0)
    footer_hint: str = (
        "Flechas: navegar | Enter: elegir | Esc: volver | ,/.: historial | F1: ayuda | F2: repetir | Ctrl: callar"
    )


class GameWindow:
    """Owns the Pygame display surface, rendering, and keyboard event polling."""

    def __init__(
        self,
        speech: SpeechService,
        width: int = 860,
        height: int = 520,
        headless: bool = False,
    ) -> None:
        self.speech = speech
        self.width = width
        self.height = height
        self.headless = headless
        self.hud = HudState()
        self._surface: pygame.Surface | None = None
        self._font_title: pygame.font.Font | None = None
        self._font_body: pygame.font.Font | None = None
        self._font_small: pygame.font.Font | None = None
        self._initialized = False

        self.speech.add_listener(self._on_speech)

    def _on_speech(self, message: str, _interrupt: bool) -> None:
        self.hud.last_spoken = message
        self.render()

    def open(self) -> None:
        if self._initialized:
            return
        if not pygame.get_init():
            pygame.init()
        if not self.headless:
            self._surface = pygame.display.set_mode(
                (self.width, self.height), pygame.RESIZABLE
            )
            pygame.display.set_caption(f"{APP_NAME} {VERSION}")
            pygame.font.init()
            self._font_title = pygame.font.SysFont("segoeui,arial,dejavusans", 26, bold=True)
            self._font_body = pygame.font.SysFont("segoeui,arial,dejavusans", 20)
            self._font_small = pygame.font.SysFont("segoeui,arial,dejavusans", 15)
        self._initialized = True
        self.render()

    def close(self) -> None:
        if self._initialized:
            try:
                pygame.quit()
            except Exception:
                pass
            self._initialized = False
            self._surface = None

    def set_view(
        self,
        title: str,
        items: list[str] | None = None,
        selected_index: int = 0,
        status_line: str | None = None,
        footer_hint: str | None = None,
    ) -> None:
        self.hud.screen_title = title
        self.hud.board_rows = None
        if items is not None:
            self.hud.items = list(items)
        self.hud.selected_index = selected_index
        if status_line is not None:
            self.hud.status_line = status_line
        if footer_hint is not None:
            self.hud.footer_hint = footer_hint
        self.render()

    def set_board_view(
        self,
        title: str,
        rows: list[tuple[str, list[str], bool]],
        cursor: tuple[int, int],
        status_line: str | None = None,
        footer_hint: str | None = None,
    ) -> None:
        self.hud.screen_title = title
        self.hud.board_rows = list(rows)
        self.hud.board_cursor = cursor
        self.hud.items = []
        if status_line is not None:
            self.hud.status_line = status_line
        if footer_hint is not None:
            self.hud.footer_hint = footer_hint
        self.render()

    def update_status(self, status_line: str) -> None:
        self.hud.status_line = status_line
        self.render()

    def _wrap_text(
        self, font: pygame.font.Font, text: str, max_width: int
    ) -> list[str]:
        words = str(text).split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def render(self) -> None:
        if self.headless or self._surface is None:
            return
        if not self._font_title or not self._font_body or not self._font_small:
            return

        w, h = self._surface.get_size()
        pad = 20
        content_w = max(200, w - pad * 2)
        self._surface.fill(BG_COLOR)

        y = pad
        # Header title + active TTS backend badge
        title_surf = self._font_title.render(self.hud.screen_title, True, ACCENT_COLOR)
        self._surface.blit(title_surf, (pad, y))
        badge_text = f"TTS: {self.speech.active_backend_name()}"
        badge_surf = self._font_small.render(badge_text, True, MUTED_COLOR)
        self._surface.blit(badge_surf, (max(pad, w - pad - badge_surf.get_width()), y + 8))
        y += title_surf.get_height() + 8

        if self.hud.status_line:
            status_text = self.hud.status_line
            while len(status_text) > 10 and self._font_small.size(status_text)[0] > content_w - 20:
                status_text = status_text[:-4] + "..."
            status_rect = pygame.Rect(pad, y, content_w, 28)
            pygame.draw.rect(self._surface, STATUS_BG, status_rect, border_radius=6)
            pygame.draw.rect(self._surface, BORDER_COLOR, status_rect, width=1, border_radius=6)
            status_surf = self._font_small.render(status_text, True, TEXT_COLOR)
            self._surface.blit(status_surf, (pad + 10, y + 5))
            y += 36

        # Last spoken narration panel
        caption_lines = self._wrap_text(
            self._font_body,
            self.hud.last_spoken or "AudioFútbol listo.",
            content_w - 24,
        )[:4]
        panel_h = max(62, len(caption_lines) * 26 + 22)
        panel_rect = pygame.Rect(pad, y, content_w, panel_h)
        pygame.draw.rect(self._surface, PANEL_COLOR, panel_rect, border_radius=8)
        pygame.draw.rect(self._surface, BORDER_COLOR, panel_rect, width=2, border_radius=8)
        cy = y + 10
        for line in caption_lines:
            surf = self._font_body.render(line, True, TEXT_COLOR)
            self._surface.blit(surf, (pad + 12, cy))
            cy += 26
        y += panel_h + 12

        # Visible 2D formation board OR menu / reader items
        footer_h = 34
        if self.hud.board_rows:
            self._render_board_panel(pad, y, content_w, h - footer_h - pad)
        elif self.hud.items:
            total = len(self.hud.items)
            sel = max(0, min(self.hud.selected_index, total - 1))
            counter_surf = self._font_small.render(
                f"Opción {sel + 1} de {total}", True, MUTED_COLOR
            )
            self._surface.blit(
                counter_surf, (max(pad, w - pad - counter_surf.get_width()), y)
            )
            y += counter_surf.get_height() + 4
            available_h = max(40, h - y - footer_h - pad)
            row_h = 32
            max_rows = max(1, available_h // row_h)
            start = max(0, min(sel - max_rows // 2, total - max_rows))
            end = min(total, start + max_rows)
            for idx in range(start, end):
                item_rect = pygame.Rect(pad, y, content_w, row_h - 4)
                is_sel = idx == sel
                if is_sel:
                    pygame.draw.rect(self._surface, SELECTED_BG, item_rect, border_radius=6)
                    pygame.draw.rect(self._surface, ACCENT_COLOR, item_rect, width=2, border_radius=6)
                prefix = "> " if is_sel else "  "
                label = f"{prefix}{idx + 1}. {self.hud.items[idx]}"
                # Truncate gracefully if very long
                while len(label) > 10 and self._font_body.size(label)[0] > content_w - 16:
                    label = label[:-4] + "..."
                color = ACCENT_COLOR if is_sel else TEXT_COLOR
                surf = self._font_body.render(label, True, color)
                self._surface.blit(surf, (pad + 8, y + 3))
                y += row_h

        # Footer shortcuts
        footer_text = self.hud.footer_hint
        while len(footer_text) > 10 and self._font_small.size(footer_text)[0] > content_w:
            footer_text = footer_text[:-4] + "..."
        footer_surf = self._font_small.render(footer_text, True, MUTED_COLOR)
        self._surface.blit(footer_surf, (pad, h - footer_h + 6))

        pygame.display.flip()

    def _render_board_panel(
        self, x: int, top_y: int, width: int, bottom_y: int
    ) -> None:
        """Render a high-contrast 2D tactical pitch layout for formation editing."""
        assert self._surface is not None
        assert self._font_body is not None and self._font_small is not None
        rows = self.hud.board_rows or []
        if not rows:
            return
        avail_h = max(80, bottom_y - top_y)
        pitch_rect = pygame.Rect(x, top_y, width, avail_h)
        pygame.draw.rect(self._surface, (16, 42, 32), pitch_rect, border_radius=10)
        pygame.draw.rect(self._surface, BORDER_COLOR, pitch_rect, width=2, border_radius=10)

        n_rows = len(rows)
        row_gap = 6
        inner_pad = 10
        row_h = max(36, (avail_h - inner_pad * 2 - row_gap * (n_rows - 1)) // n_rows)
        cur_r, cur_c = self.hud.board_cursor

        for r_idx, (row_name, labels, is_action) in enumerate(rows):
            ry = top_y + inner_pad + r_idx * (row_h + row_gap)
            is_cur_row = r_idx == cur_r
            if is_cur_row and cur_c == -1:
                band = pygame.Rect(x + 6, ry - 2, width - 12, row_h + 4)
                pygame.draw.rect(self._surface, SELECTED_BG, band, border_radius=8)
                pygame.draw.rect(self._surface, ACCENT_COLOR, band, width=2, border_radius=8)

            hdr_w = min(160, max(100, width // 5))
            hdr_surf = self._font_small.render(row_name, True, ACCENT_COLOR if is_cur_row else MUTED_COLOR)
            self._surface.blit(hdr_surf, (x + 14, ry + max(4, (row_h - hdr_surf.get_height()) // 2)))

            slots_x = x + hdr_w + 14
            slots_w = max(80, width - hdr_w - 28)
            n_cols = max(1, len(labels))
            col_gap = 8
            card_w = max(54, (slots_w - col_gap * (n_cols - 1)) // n_cols)
            for c_idx, lbl in enumerate(labels):
                cx = slots_x + c_idx * (card_w + col_gap)
                card_rect = pygame.Rect(cx, ry + 2, card_w, row_h - 4)
                is_sel = is_cur_row and c_idx == cur_c
                bg = SELECTED_BG if is_sel else ((40, 56, 82) if is_action else PANEL_COLOR)
                border = ACCENT_COLOR if is_sel else BORDER_COLOR
                pygame.draw.rect(self._surface, bg, card_rect, border_radius=6)
                pygame.draw.rect(self._surface, border, card_rect, width=2 if is_sel else 1, border_radius=6)
                txt = lbl
                while len(txt) > 4 and self._font_small.size(txt)[0] > card_w - 10:
                    txt = txt[:-4] + "..."
                surf = self._font_small.render(txt, True, ACCENT_COLOR if is_sel else TEXT_COLOR)
                tx = cx + max(4, (card_w - surf.get_width()) // 2)
                ty = ry + 2 + max(2, (row_h - 4 - surf.get_height()) // 2)
                self._surface.blit(surf, (tx, ty))

    def _handle_system_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            raise QuitRequested()
        if event.type in (pygame.VIDEORESIZE, pygame.VIDEOEXPOSE):
            self.render()

    def _handle_global_keydown(self, event: pygame.event.Event) -> bool:
        """Handle universal accessibility shortcuts available on every screen.

        Returns True if the event was consumed globally.
        """
        key = event.key
        if key in (pygame.K_LCTRL, pygame.K_RCTRL):
            self.speech.silence()
            return True
        if key == pygame.K_F2:
            self.speech.repeat_last()
            return True
        if key in (pygame.K_COMMA, pygame.K_PERIOD):
            mods = getattr(event, "mod", 0)
            try:
                mods |= pygame.key.get_mods()
            except Exception:
                pass
            shift_held = bool(mods & pygame.KMOD_SHIFT)
            if key == pygame.K_COMMA:
                if shift_held:
                    self.speech.history_first()
                else:
                    self.speech.history_prev()
            else:
                if shift_held:
                    self.speech.history_last()
                else:
                    self.speech.history_next()
            return True
        return False

    def wait_key(self) -> tuple[int, str]:
        """Block cleanly until a gameplay keypress arrives, keeping window responsive."""
        while True:
            for event in pygame.event.get():
                self._handle_system_event(event)
                if event.type == pygame.KEYDOWN:
                    if self._handle_global_keydown(event):
                        continue
                    return event.key, getattr(event, "unicode", "")
            pygame.time.wait(15)

    def wait_text_event(self) -> pygame.event.Event:
        """Read editing keys and IME text without intercepting decimal punctuation."""
        while True:
            # Poll one event at a time so KEYDOWN does not drop TEXTINPUT in the same batch.
            event = pygame.event.poll()
            self._handle_system_event(event)
            if event.type == pygame.TEXTINPUT:
                return event
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_F2):
                    self._handle_global_keydown(event)
                else:
                    return event
            if event.type == pygame.NOEVENT:
                pygame.time.wait(15)

    def pause(self, ms: int) -> None:
        """Wait `ms` milliseconds while pumping window events."""
        if self.headless or ms <= 0:
            return
        deadline = pygame.time.get_ticks() + ms
        while pygame.time.get_ticks() < deadline:
            for event in pygame.event.get():
                self._handle_system_event(event)
                if event.type == pygame.KEYDOWN:
                    self._handle_global_keydown(event)
            pygame.time.wait(15)

    def wait_or_skip_action(self, ms: int) -> str | None:
        """Wait `ms` ms; return 'escape' on Esc, 'space' on Space, or None on timeout."""
        if self.headless or ms <= 0:
            return None
        deadline = pygame.time.get_ticks() + ms
        while pygame.time.get_ticks() < deadline:
            for event in pygame.event.get():
                self._handle_system_event(event)
                if event.type == pygame.KEYDOWN:
                    if self._handle_global_keydown(event):
                        continue
                    if event.key == pygame.K_ESCAPE:
                        return "escape"
                    if event.key == pygame.K_SPACE:
                        return "space"
            pygame.time.wait(15)
        return None
