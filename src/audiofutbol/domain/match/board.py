"""Pure domain 2D tactical formation board views, spatial pan, and card/quality labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from audiofutbol.domain.formations import (
    group_of,
    role_text,
    scheme_rows,
    scheme_slot_codes,
    side_of,
)
from audiofutbol.domain.models import Player

if TYPE_CHECKING:  # pragma: no cover
    from audiofutbol.domain.match.state import MatchState

MIN_STARTING_PLAYERS = 8

_SIDE_SORT = {"izquierda": 0, "centro": 1, "derecha": 2}


@dataclass(frozen=True)
class FormationSlotView:
    """Single slot inside a tactical formation row for 2D audio/visual rendering."""

    slot_id: str
    label: str
    short_label: str
    pan: float
    occupied: bool = True
    is_action: bool = False


@dataclass(frozen=True)
class FormationRowView:
    """Horizontal tactical line (e.g., Portería, Zona defensiva, Mediocampo, Delantera)."""

    name: str
    slots: tuple[FormationSlotView, ...]
    pitch_ratio: float
    is_action_row: bool = False


def slot_pan(col: int, count: int) -> float:
    """Return stereo pan in [-1.0, +1.0] for column `col` of `count` slots."""
    if count <= 1:
        return 0.0
    if count == 2:
        return -0.55 if col == 0 else 0.55
    return max(-1.0, min(1.0, -1.0 + 2.0 * col / (count - 1)))


def format_quality(value: float) -> str:
    """Format average overall rating cleanly for Spanish speech synthesis."""
    if value <= 0.0:
        return "0"
    return f"{value:.1f}".replace(".", ",")


def yellow_card_badge(
    player: Player, match_yellows: int = 0, in_match: bool = False, *, limit: int = 2
) -> str:
    """Return Spanish yellow-card status suffix for prematch or live menus."""
    if in_match:
        if match_yellows > 0:
            suffix = ", sancionado para el próximo partido" if player.suspended_matches > 0 else ""
            return f", con amarilla en el partido{suffix}"
    count = player.yellow_cards
    if not count:
        return ""
    label = "amarilla" if count == 1 else "amarillas"
    if in_match:
        label += " acumulada" if count == 1 else " acumuladas"
    warning = " (a una de sanción)" if count == limit - 1 else ""
    return f", {count} {label}{warning}"


def build_prematch_board_rows(
    state: MatchState,
    team_idx: int = 0,
    include_accept: bool = True,
    swap_source_idx: int | None = None,
) -> list[FormationRowView]:
    """Build 2D tactical board rows for prematch lineup editing (including empty slots)."""
    scheme = state.scheme[team_idx]
    rows_spec = scheme_rows(scheme)
    slots = list(state.board_slots[team_idx])
    codes = scheme_slot_codes(scheme)
    if len(slots) != len(codes):
        state.sync_board_slots(team_idx)
        slots = list(state.board_slots[team_idx])

    out: list[FormationRowView] = []
    tactical_den = max(1, len(rows_spec) - 1)
    cursor = 0
    for row_idx, (row_name, row_codes) in enumerate(rows_spec):
        pitch_ratio = row_idx / tactical_den
        count = len(row_codes)
        row_slots: list[FormationSlotView] = []
        for col, code in enumerate(row_codes):
            slot_idx = cursor
            cursor += 1
            player = slots[slot_idx] if slot_idx < len(slots) else None
            pan = slot_pan(col, count)
            role_lbl = role_text(code).capitalize()
            if player is not None:
                badge = yellow_card_badge(player, limit=state.yellow_card_limit)
                fit_val = state.slot_fit(player)
                fit_note = ", fuera de puesto" if fit_val < 0.7 else ""
                swap_note = (
                    ", seleccionado para intercambiar"
                    if swap_source_idx == slot_idx
                    else ""
                )
                label = (
                    f"{role_lbl}: {player.name}, calidad {player.overall}"
                    f"{badge}{fit_note}{swap_note}"
                )
                card_tag = " [TA]" if player.yellow_cards > 0 else ""
                short_label = f"{code}: {player.name} ({player.overall}){card_tag}"
                occupied = True
            else:
                label = f"{role_lbl}: vacío"
                short_label = f"{code}: Vacío"
                occupied = False
            row_slots.append(
                FormationSlotView(
                    slot_id=f"slot:{slot_idx}",
                    label=label,
                    short_label=short_label,
                    pan=pan,
                    occupied=occupied,
                )
            )
        out.append(
            FormationRowView(
                name=row_name,
                slots=tuple(row_slots),
                pitch_ratio=pitch_ratio,
            )
        )

    if include_accept:
        filled = sum(1 for p in slots if p is not None)
        avg_txt = format_quality(state.lineup_average_quality(team_idx, include_fatigue=False))
        if filled < MIN_STARTING_PLAYERS:
            accept_label = (
                f"Aceptar alineación, faltan jugadores: {filled} de {MIN_STARTING_PLAYERS} mínimo, "
                f"calidad media {avg_txt}"
            )
        else:
            accept_label = (
                f"Aceptar alineación, {filled} de 11 jugadores, calidad media {avg_txt}"
            )
        out.append(
            FormationRowView(
                name="Confirmar",
                slots=(
                    FormationSlotView(
                        slot_id="action:accept",
                        label=accept_label,
                        short_label="Aceptar",
                        pan=0.0,
                        occupied=True,
                        is_action=True,
                    ),
                ),
                pitch_ratio=1.0,
                is_action_row=True,
            )
        )
    return out


def build_live_board_rows(
    state: MatchState,
    team_idx: int = 0,
    action_label: str = "Cancelar",
    exclude_gk: bool = False,
    include_fatigue: bool = True,
    swap_source_player: Player | None = None,
) -> list[FormationRowView]:
    """Build 2D tactical board rows from active on-pitch players (live subs/moves)."""
    scheme = state.scheme[team_idx]
    rows_spec = scheme_rows(scheme)
    on_pitch = list(state.xi[team_idx])
    used: set[int] = set()

    # Preserve board_slots ordering first when players are still on pitch in matching roles.
    row_players: list[list[Player]] = [[] for _ in rows_spec]
    board = state.board_slots[team_idx]
    codes = scheme_slot_codes(scheme)
    slot_cursor = 0
    row_ranges: list[tuple[int, int]] = []
    for _rname, rcodes in rows_spec:
        start = slot_cursor
        slot_cursor += len(rcodes)
        row_ranges.append((start, slot_cursor))

    for r_idx, ((_rname, rcodes), (start, end)) in enumerate(zip(rows_spec, row_ranges)):
        if r_idx == 0 and exclude_gk:
            continue
        for offset, code in enumerate(rcodes):
            b_idx = start + offset
            candidate = board[b_idx] if b_idx < len(board) else None
            if (
                candidate is not None
                and candidate in on_pitch
                and id(candidate) not in used
                and state.slot.get(id(candidate)) == code
            ):
                row_players[r_idx].append(candidate)
                used.add(id(candidate))
                continue
            found = next(
                (
                    p
                    for p in on_pitch
                    if id(p) not in used and state.slot.get(id(p)) == code
                ),
                None,
            )
            if found is not None:
                row_players[r_idx].append(found)
                used.add(id(found))

    # Place any remaining on-pitch players (e.g. extra forward from substitution) into matching line.
    def target_row_for(player: Player) -> int:
        grp = state.player_role(player)
        if grp == "POR":
            return 0
        if grp == "DEF":
            return 1 if len(rows_spec) > 1 else 0
        if grp == "DEL":
            return len(rows_spec) - 1
        # MED: prefer the last midfield row (between DEF and DEL)
        mid_rows = [
            idx
            for idx, (_n, rcodes) in enumerate(rows_spec)
            if any(group_of(c) == "MED" for c in rcodes)
        ]
        return mid_rows[-1] if mid_rows else max(0, len(rows_spec) - 2)

    extras = [p for p in on_pitch if id(p) not in used]
    extras.sort(key=lambda p: _SIDE_SORT.get(side_of(state.slot_code(p)), 1))
    for p in extras:
        if exclude_gk and state.player_role(p) == "POR":
            continue
        row_players[target_row_for(p)].append(p)
        used.add(id(p))

    non_empty_rows = [
        (r_idx, rows_spec[r_idx][0], plist)
        for r_idx, plist in enumerate(row_players)
        if plist and not (exclude_gk and r_idx == 0)
    ]

    tactical_den = max(1, len(rows_spec) - 1)
    out: list[FormationRowView] = []
    for r_idx, row_name, plist in non_empty_rows:
        pitch_ratio = r_idx / tactical_den
        count = len(plist)
        r_slots: list[FormationSlotView] = []
        for col, player in enumerate(plist):
            pan = slot_pan(col, count)
            eff = int(round(state.effective_overall(player)))
            role_lbl = state.slot_text(player).capitalize()
            fatigue_txt = ""
            if include_fatigue:
                fat = int(round(state.fatigue.get(id(player), 0.0)))
                fatigue_txt = f", cansancio {fat} por ciento"
                if id(player) in state.injured:
                    fatigue_txt += ", lesionado"
            badge = yellow_card_badge(
                player, state.match_yellows.get(id(player), 0), in_match=True,
                limit=state.yellow_card_limit,
            )
            swap_note = (
                ", seleccionado para intercambiar"
                if swap_source_player is player
                else ""
            )
            label = (
                f"{role_lbl}: {player.name}, calidad efectiva {eff}"
                f"{fatigue_txt}{badge}{swap_note}"
            )
            code = state.slot_code(player)
            card_tag = (
                " [TA]"
                if (state.match_yellows.get(id(player), 0) > 0 or player.yellow_cards > 0)
                else ""
            )
            short_label = f"{code}: {player.name} ({eff}){card_tag}"
            r_slots.append(
                FormationSlotView(
                    slot_id=f"player:{id(player)}",
                    label=label,
                    short_label=short_label,
                    pan=pan,
                    occupied=True,
                )
            )
        out.append(
            FormationRowView(
                name=row_name,
                slots=tuple(r_slots),
                pitch_ratio=pitch_ratio,
            )
        )

    out.append(
        FormationRowView(
            name="Acciones",
            slots=(
                FormationSlotView(
                    slot_id="action:cancel",
                    label=action_label,
                    short_label="Volver",
                    pan=0.0,
                    occupied=True,
                    is_action=True,
                ),
            ),
            pitch_ratio=1.0,
            is_action_row=True,
        )
    )
    return out
