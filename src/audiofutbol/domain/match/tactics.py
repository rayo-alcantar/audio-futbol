"""User and AI tactics: prematch preparation, live tactical menu, schemes, slots, and takers."""

from __future__ import annotations

from typing import Callable

from audiofutbol.domain.formations import (
    MENTALITY_DESC,
    MENTALITY_NAMES,
    SCHEME_DESC,
    SCHEME_ORDER,
    SCHEMES,
    family_of,
    fit,
    fit_text,
    group_of,
    preferred_role_text,
    role_text,
    scheme_slot_codes,
)
from audiofutbol.domain.match.board import (
    MIN_STARTING_PLAYERS,
    FormationRowView,
    FormationSlotView,
    build_live_board_rows,
    build_prematch_board_rows,
    format_quality,
    yellow_card_badge,
)
from audiofutbol.domain.match.ports import MatchIO
from audiofutbol.domain.match.state import MatchState
from audiofutbol.domain.models import POSITION_ORDER, Player, Team

ShortcutsFn = Callable[[], "dict[str, Callable[[], str | None]]"]

_LINE_LABELS = {
    3: ["Defensa", "Mediocampo", "Ataque"],
    4: ["Defensa", "Primera línea de medio", "Segunda línea de medio", "Ataque"],
}


class TacticsManager:
    """Manages prematch preparation, live tactical menus, and late-game AI scheme shifts."""

    def __init__(
        self,
        state: MatchState,
        io: MatchIO,
        shortcuts_fn: ShortcutsFn,
        speak: Callable[[str], None],
    ) -> None:
        self.state = state
        self.io = io
        self._shortcuts = shortcuts_fn
        self._say = speak

    def _menu(
        self,
        title: str,
        options: list[str],
        initial: int = 0,
        prematch: bool = False,
    ) -> int | None:
        # Exclude 'x' to prevent recursive tactical menus, and exclude live-only actions prematch.
        blocked = {"x", "c", "h"} if prematch else {"x"}
        shortcuts = {k: v for k, v in self._shortcuts().items() if k not in blocked}
        return self.io.choose(
            title, options, shortcuts=shortcuts, initial_index=initial
        )

    def _lines(self, title: str, lines: list[str]) -> None:
        self.io.read_lines(title, lines)

    def _tell(self, text: str) -> None:
        self.io.speak(text, interrupt=True)

    def _team(self, idx: int) -> Team:
        return self.state.teams[idx]

    # ---------------------------------------------------------- Readable Views
    def formation_lines(self, idx: int) -> list[str]:
        st = self.state
        scheme = st.scheme[idx]
        sizes = [int(x) for x in scheme.split("-")]
        codes = list(SCHEMES[scheme])
        labels = _LINE_LABELS.get(len(sizes), [f"Línea {k + 1}" for k in range(len(sizes))])
        used: set[int] = set()
        out: list[str] = []
        gk = next((p for p in st.xi[idx] if st.slot.get(id(p)) == "POR"), None)
        if gk is not None:
            out.append(f"Portero: {gk.name}")
        start = 0
        for n, label in zip(sizes, labels):
            parts = []
            for code in codes[start : start + n]:
                p = next(
                    (x for x in st.xi[idx] if st.slot.get(id(x)) == code and id(x) not in used),
                    None,
                )
                if p is not None:
                    used.add(id(p))
                    parts.append(f"{role_text(code)}, {p.name}")
            start += n
            out.append(f"{label}: {'; '.join(parts)}")
        others = [
            x for x in st.xi[idx] if id(x) not in used and st.slot.get(id(x)) != "POR"
        ]
        if others:
            out.append("Sin puesto fijo: " + ", ".join(x.name for x in others))
        return out

    def lineup_lines(self) -> list[str]:
        st = self.state
        avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=True))
        out = [
            f"Esquema {st.scheme_label(0)}. Mentalidad {MENTALITY_NAMES[st.mentality(0)]}. "
            f"Calidad media {avg_txt}."
        ]
        out += self.formation_lines(0)
        out.append(
            f"Cambios hechos: {st.substitutions_used[0]}. "
            f"{self._subs_text()}."
        )
        return out

    def _subs_text(self) -> str:
        limit = self.state.max_substitutions
        if limit is None:
            return "Cambios ilimitados"
        left = max(0, limit - self.state.substitutions_used[0])
        return "Ya no te quedan cambios" if left == 0 else f"Te quedan {left} cambio{'' if left == 1 else 's'}"

    def bench_lines(self) -> list[str]:
        st = self.state
        on = {id(p) for p in st.xi[0]}
        out = []
        for p in sorted(
            self._team(0).players, key=lambda q: (POSITION_ORDER[q.position], -q.overall)
        ):
            if id(p) in on:
                continue
            extra = ""
            if p.suspended_matches > 0:
                extra = ", sancionado"
            elif id(p) in st.subbed_off[0]:
                extra = ", ya salió del partido"
            else:
                extra = yellow_card_badge(p, limit=st.yellow_card_limit)
            out.append(f"{p.name}, {preferred_role_text(p)}, calidad {p.overall}{extra}")
        return out or ["No tienes suplentes."]

    def performance_lines(self) -> list[str]:
        st = self.state
        return [
            f"{p.name}, {st.slot_text(p)}: {st.note_text(p)}, cansancio "
            f"{int(round(st.fatigue.get(id(p), 0.0)))} por ciento"
            + (", lesionado" if id(p) in st.injured else "")
            for p in st.xi[0]
        ]

    def flank_lines(self) -> list[str]:
        st = self.state
        out = []
        for side in ("izquierda", "derecha"):
            n, g = st.flank_attacks[side], st.flank_goals[side]
            text = (
                f"Por tu banda {side} te han llegado {n} {'vez' if n == 1 else 'veces'} "
                f"y has recibido {g} gol{'' if g == 1 else 'es'}"
            )
            d = st.flank_defender(side)
            if d is not None:
                text += (
                    f". Defiende {d.name}, {st.slot_text(d)}, rendimiento {st.note_text(d)}, "
                    f"cansancio {int(round(st.fatigue.get(id(d), 0.0)))} por ciento"
                )
            out.append(text)
        return out

    def rival_lines(self) -> list[str]:
        st = self.state
        out = [
            f"El rival, {st.team_name(1)}, juega con {st.scheme_label(1)}. "
            f"Su mentalidad es {MENTALITY_NAMES[st.mentality(1)]}.",
            "Las posiciones están vistas desde su lado: su banda derecha es tu banda izquierda.",
        ]
        return out + self.formation_lines(1)

    # ------------------------------------------------------------ Core Mutations
    def apply_scheme(
        self,
        idx: int,
        new: str,
        persist: bool = False,
        keep_current_xi: bool = False,
    ) -> None:
        st = self.state
        team = self._team(idx)
        for p in st.xi[idx]:
            st.slot.pop(id(p), None)
            st.fit.pop(id(p), None)
            st.position_overrides.pop(id(p), None)
        st.scheme[idx] = new
        if persist:
            team.scheme = new
            team.positions = {}
            if not keep_current_xi:
                st.xi[idx] = team.lineup(new)
            team.lineup_names = [p.name for p in st.xi[idx]]
        st.assign_slots(idx, use_fixed=persist and not keep_current_xi)
        st.sort_lineup(idx)
        if persist and keep_current_xi and idx == 0:
            self._save_positions()
        st.ratings[idx] = st.compute_ratings(idx)
        if idx == 0:
            self.io.update_hud(st.hud_status())

    def _save_positions(self) -> None:
        st = self.state
        self._team(0).positions = {
            p.name: st.slot[id(p)]
            for p in st.xi[0]
            if st.slot.get(id(p)) not in (None, "POR")
        }

    def _swap(self, a: Player, b: Player, persist: bool) -> None:
        st = self.state
        ca, cb = st.slot.get(id(a)), st.slot.get(id(b))
        if not ca or not cb or "POR" in (ca, cb):
            return
        st.slot[id(a)], st.slot[id(b)] = cb, ca
        st.fit[id(a)], st.fit[id(b)] = fit(a, cb), fit(b, ca)
        st.sync_roles(0)
        st.sort_lineup(0)
        st.ratings[0] = st.compute_ratings(0)
        if persist:
            self._save_positions()
        self.io.update_hud(st.hud_status())
        self._tell(
            f"{a.name} pasa a jugar de {role_text(cb)}, y {fit_text(st.fit[id(a)])}. "
            f"{b.name} pasa a jugar de {role_text(ca)}, y {fit_text(st.fit[id(b)])}."
        )

    def _wide_pairs(self, families: tuple[str, ...]) -> tuple[list[Player], list[Player]]:
        st = self.state
        left = [
            p for p in st.xi[0]
            if family_of(st.slot_code(p)) in families and st.side_from_user(0, p) == "izquierda"
        ]
        right = [
            p for p in st.xi[0]
            if family_of(st.slot_code(p)) in families and st.side_from_user(0, p) == "derecha"
        ]
        return left, right

    # ---------------------------------------------------------------- Submenus
    def _scheme_menu(self, prematch: bool) -> None:
        st = self.state
        ops = [
            f"{s}. {SCHEME_DESC[s]}{'. Es el que tienes' if s == st.scheme[0] else ''}"
            for s in SCHEME_ORDER
        ]
        ops.append("Volver")
        start = SCHEME_ORDER.index(st.scheme[0]) if st.scheme[0] in SCHEME_ORDER else 0
        k = self._menu(
            f"Esquemas. Tu esquema es {st.scheme[0]}. El rival juega con {st.scheme_label(1)}",
            ops,
            start,
            prematch=prematch,
        )
        if k is None or k >= len(SCHEME_ORDER) or SCHEME_ORDER[k] == st.scheme[0]:
            return
        new = SCHEME_ORDER[k]
        if prematch:
            if self.io.confirm(
                "¿Deseas limpiar tu alineación y colocar los jugadores manualmente?"
            ):
                st.clear_lineup(0, new_scheme=new, persist=True)
                self.io.update_hud(st.hud_status())
                self._tell(
                    f"Esquema {new}. Alineación limpia. Coloca al menos "
                    f"{MIN_STARTING_PLAYERS} jugadores para poder empezar el partido."
                )
                self._lineup_board()
                return
            self.apply_scheme(0, new, persist=True, keep_current_xi=True)
            avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
            self._tell(
                f"Esquema {new}. Tus jugadores se reacomodaron al nuevo esquema. "
                f"Calidad media {avg_txt}. " + ". ".join(self.formation_lines(0))
            )
            return
        self.apply_scheme(0, new, persist=False)
        st.lost_seconds += 20
        self._tell(f"Esquema {new}. " + ". ".join(self.formation_lines(0)))

    def _mentality_menu(self, prematch: bool) -> None:
        st = self.state
        ops = [f"{MENTALITY_NAMES[m].capitalize()}. {MENTALITY_DESC[m]}" for m in (-2, -1, 0, 1, 2)]
        ops.append("Volver")
        k = self._menu(
            f"Mentalidad. Ahora es {MENTALITY_NAMES[st.mentality(0)]}",
            ops,
            st.mentality(0) + 2,
            prematch=prematch,
        )
        if k is None or k > 4:
            return
        st.set_mentality(0, k - 2)
        if prematch:
            self._team(0).mentality = k - 2
        self.io.update_hud(st.hud_status())
        self._tell(f"Mentalidad {MENTALITY_NAMES[st.mentality(0)]}.")

    def _move_menu(self, persist: bool) -> None:
        st = self.state
        if persist:
            self._move_menu_prematch()
            return
        swap_player: Player | None = None
        last_slot_id: str | None = None
        while True:
            field = [p for p in st.xi[0] if st.slot.get(id(p)) not in (None, "POR")]
            if len(field) < 2:
                self._tell("No hay jugadores que mover.")
                return
            rows = build_live_board_rows(
                st,
                0,
                action_label="Terminar",
                exclude_gk=True,
                include_fatigue=True,
                swap_source_player=swap_player,
            )
            title = (
                f"Mover jugadores. Elige con quién intercambiar a {swap_player.name}"
                if swap_player is not None
                else "Mover jugadores en el esquema. Elige al primero para intercambiar"
            )
            res = self.io.choose_formation(
                title,
                rows,
                status_line=self._board_status_line(include_fatigue=True),
                shortcuts={"i": lambda: self._announce_board_summary(include_fatigue=True)},
                initial_slot_id=last_slot_id,
                allow_remove=False,
                allow_swap_key=False,
            )
            if res is None:
                if swap_player is not None:
                    swap_player = None
                    self._tell("Intercambio cancelado.")
                    continue
                return
            _action, slot_id = res
            if slot_id == "action:cancel":
                return
            last_slot_id = slot_id
            if not slot_id.startswith("player:"):
                continue
            pid = int(slot_id.split(":", 1)[1])
            picked = next((p for p in field if id(p) == pid), None)
            if picked is None:
                continue
            if swap_player is None:
                swap_player = picked
                self._tell(
                    f"Seleccionado {picked.name}, {st.slot_text(picked)}. "
                    "Ahora elige con quién intercambia su puesto."
                )
            elif swap_player is picked:
                swap_player = None
                self._tell("Selección cancelada.")
            else:
                self._swap(swap_player, picked, persist=False)
                swap_player = None

    def _move_menu_prematch(self) -> None:
        st = self.state
        swap_idx: int | None = None
        last_slot_id: str | None = None
        while True:
            rows = build_prematch_board_rows(
                st, 0, include_accept=False, swap_source_idx=swap_idx
            )
            rows.append(
                FormationRowView(
                    name="Acciones",
                    slots=(
                        FormationSlotView(
                            slot_id="action:cancel",
                            label="Terminar",
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
            codes = scheme_slot_codes(st.scheme[0])
            slots = list(st.board_slots[0])
            title = (
                f"Mover jugadores. Elige con quién intercambiar a {slots[swap_idx].name}"
                if swap_idx is not None and slots[swap_idx] is not None
                else "Mover jugadores en el esquema. Elige un jugador"
            )
            res = self.io.choose_formation(
                title,
                rows,
                status_line=self._board_status_line(include_fatigue=False),
                shortcuts={"i": lambda: self._announce_board_summary(include_fatigue=False)},
                initial_slot_id=last_slot_id,
                allow_remove=False,
                allow_swap_key=False,
            )
            if res is None:
                if swap_idx is not None:
                    swap_idx = None
                    self._tell("Intercambio cancelado.")
                    continue
                return
            _action, slot_id = res
            if slot_id == "action:cancel":
                return
            last_slot_id = slot_id
            if not slot_id.startswith("slot:"):
                continue
            idx = int(slot_id.split(":", 1)[1])
            if idx == 0:
                self._tell("El portero no se intercambia con jugadores de campo.")
                continue
            if swap_idx is None:
                if slots[idx] is None:
                    self._tell("Esa posición está vacía. Usa Alineación en el esquema para colocar un jugador.")
                    continue
                swap_idx = idx
                self._tell(
                    f"Seleccionado {slots[idx].name} ({role_text(codes[idx])}). "
                    "Elige otro puesto para intercambiar o moverlo."
                )
            elif swap_idx == idx:
                swap_idx = None
                self._tell("Selección cancelada.")
            else:
                self._swap_board_slots(swap_idx, idx)
                swap_idx = None

    def _swap_sides(self, families: tuple[str, ...], persist: bool) -> None:
        left, right = self._wide_pairs(families)
        if not left or not right:
            self._tell("No tienes jugadores de ese tipo en las dos bandas.")
            return
        for a, b in zip(left, right):
            self._swap(a, b, persist)

    def _takers_menu(self, prematch: bool = False) -> None:
        st = self.state
        team = self._team(0)
        kinds = [("penal", "Penales"), ("libre", "Tiros libres peligrosos"), ("corner", "Tiros de esquina")]
        pos = 0
        while True:
            ops = []
            for kind, name in kinds:
                p, _ = st.designated_taker(0, kind)
                who = "elegido por ti" if st.takers[0].get(kind) is p else "elegido por el juego"
                ops.append(f"{name}: {p.name}, {who}")
            ops.append("Volver")
            k = self._menu(
                "Cobradores fijos. Elige un tipo para cambiarlo",
                ops,
                pos,
                prematch=prematch,
            )
            if k is None or k >= len(kinds):
                return
            pos = k
            kind, name = kinds[k]
            cands = sorted(
                (p for p in st.xi[0] if st.slot.get(id(p)) != "POR" and id(p) not in st.injured),
                key=lambda p: -p.overall,
            )
            k2 = self._menu(
                f"{name}. ¿Quién los cobra siempre?",
                ["Que lo elija el juego, el mejor disponible"]
                + [f"{p.name}, {st.slot_text(p)}, calidad {p.overall}" for p in cands],
                prematch=prematch,
            )
            if k2 is None:
                continue
            if k2 == 0:
                st.takers[0].pop(kind, None)
                st.taker_auto[0].pop(kind, None)
                team.takers.pop(kind, None)
                self._tell(f"{name}: los elegirá el juego.")
            else:
                chosen = cands[k2 - 1]
                st.takers[0][kind] = chosen
                team.takers[kind] = chosen.name
                self._tell(f"{name.lower()} cobrará siempre: {chosen.name}.")

    def _board_status_line(self, include_fatigue: bool = False) -> str:
        st = self.state
        avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=include_fatigue))
        return f"Esquema {st.scheme[0]} | {len(st.xi[0])}/11 jugadores | Calidad media: {avg_txt}"

    def _announce_board_summary(self, include_fatigue: bool = False) -> None:
        st = self.state
        avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=include_fatigue))
        line_avgs = st.lineup_line_averages(0)
        line_names = {"POR": "Portería", "DEF": "Defensa", "MED": "Medio", "DEL": "Ataque"}
        parts = [f"{line_names[k]} {format_quality(v)}" for k, v in line_avgs.items()]
        lines_txt = (". Por líneas: " + ", ".join(parts)) if parts else ""
        warned = [
            p.name
            for p in st.xi[0]
            if p.yellow_cards > 0 or st.match_yellows.get(id(p), 0) > 0
        ]
        warn_txt = (
            f". Con tarjeta amarilla: {', '.join(warned)}" if warned else ". Sin jugadores apercibidos"
        )
        self._tell(
            f"Esquema {st.scheme[0]}, {len(st.xi[0])} de 11 jugadores. "
            f"Calidad media {avg_txt}{lines_txt}{warn_txt}."
        )

    def _swap_board_slots(self, idx_a: int, idx_b: int) -> None:
        st = self.state
        slots = list(st.board_slots[0])
        codes = scheme_slot_codes(st.scheme[0])
        a, b = slots[idx_a], slots[idx_b]
        slots[idx_a], slots[idx_b] = b, a
        st.apply_board_slots(0, slots, persist=True)
        self.io.update_hud(st.hud_status())
        avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
        if a is not None and b is not None:
            self._tell(
                f"{a.name} pasa a {role_text(codes[idx_b])}, y {fit_text(st.slot_fit(a))}. "
                f"{b.name} pasa a {role_text(codes[idx_a])}, y {fit_text(st.slot_fit(b))}. "
                f"Calidad media {avg_txt}."
            )
        elif a is not None:
            self._tell(
                f"{a.name} pasa a {role_text(codes[idx_b])}, y {fit_text(st.slot_fit(a))}. "
                f"Calidad media {avg_txt}."
            )

    def _pick_bench_for_slot(self, slot_idx: int) -> bool:
        st = self.state
        team = self._team(0)
        codes = scheme_slot_codes(st.scheme[0])
        code = codes[slot_idx]
        target_group = group_of(code)
        on_pitch = {id(p) for p in st.xi[0]}
        eligible_pool = [
            p
            for p in team.players
            if id(p) not in on_pitch
            and p.suspended_matches <= 0
            and id(p) not in st.excluded_suspended[0]
            and id(p) not in st.subbed_off[0]
        ]
        if slot_idx == 0:
            gks = [p for p in eligible_pool if p.position == "POR"]
            bench = sorted(gks or eligible_pool, key=lambda p: -p.overall)
        else:
            outfield = [p for p in eligible_pool if p.position != "POR"]
            bench = sorted(
                outfield,
                key=lambda p: (
                    -fit(p, code),
                    p.position != target_group,
                    -p.overall,
                ),
            )
        if not bench:
            self._tell("No tienes jugadores disponibles en el banquillo para ese puesto.")
            return False

        current = st.board_slots[0][slot_idx]
        first_opt = (
            f"Dejar a {current.name} en este puesto"
            if current is not None
            else "Dejar el puesto vacío"
        )
        ops = [first_opt]
        for p in bench:
            badge = yellow_card_badge(p, limit=st.yellow_card_limit)
            if slot_idx == 0:
                fit_note = "" if p.position == "POR" else ", fuera de puesto"
            else:
                fit_note = "" if fit(p, code) >= 0.7 else ", fuera de puesto"
            ops.append(
                f"{p.name}, {preferred_role_text(p)}, calidad {p.overall}{badge}{fit_note}"
            )
        k = self._menu(
            f"{role_text(code).capitalize()}. ¿A quién colocas aquí?",
            ops,
            prematch=True,
        )
        if not k:
            return False
        chosen = bench[k - 1]
        slots = list(st.board_slots[0])
        slots[slot_idx] = chosen
        st.apply_board_slots(0, slots, persist=True)
        self.io.update_hud(st.hud_status())
        avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
        self._tell(
            f"{chosen.name} queda como {role_text(code)}. "
            f"{fit_text(st.slot_fit(chosen)).capitalize()}. "
            f"{len(st.xi[0])} de 11 jugadores, calidad media {avg_txt}."
        )
        return True

    def _lineup_board(self) -> None:
        """Interactive 2D spatial board for placing, removing, and moving starters."""
        st = self.state
        last_slot_id: str | None = None
        swap_source_idx: int | None = None
        while True:
            rows = build_prematch_board_rows(
                st,
                0,
                include_accept=True,
                swap_source_idx=swap_source_idx,
            )
            title = (
                f"Alineación {st.scheme[0]} — elige destino para intercambiar"
                if swap_source_idx is not None
                else f"Alineación {st.scheme[0]}"
            )
            res = self.io.choose_formation(
                title,
                rows,
                status_line=self._board_status_line(include_fatigue=False),
                shortcuts={"i": lambda: self._announce_board_summary(include_fatigue=False)},
                initial_slot_id=last_slot_id,
                allow_remove=True,
                allow_swap_key=True,
            )
            if res is None:
                if swap_source_idx is not None:
                    swap_source_idx = None
                    self._tell("Intercambio cancelado.")
                    continue
                return
            action, slot_id = res
            last_slot_id = slot_id

            if slot_id == "action:accept":
                filled = len(st.xi[0])
                avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
                if filled < MIN_STARTING_PLAYERS:
                    self._tell(
                        f"No puedes iniciar el partido con {filled} jugadores. "
                        f"Debes colocar al menos {MIN_STARTING_PLAYERS} jugadores en la alineación."
                    )
                    continue
                if filled < 11:
                    if st.board_slots[0][0] is None:
                        q = (
                            f"Aviso: no colocaste portero y tienes {filled} de 11 jugadores, "
                            f"calidad media {avg_txt}. ¿Confirmas esta alineación?"
                        )
                    else:
                        q = (
                            f"Tienes {filled} de 11 jugadores colocados, calidad media {avg_txt}. "
                            "¿Confirmas esta alineación?"
                        )
                    if not self.io.confirm(q):
                        continue
                self._tell(
                    f"Alineación confirmada. {st.scheme[0]}, {filled} jugadores, calidad media {avg_txt}."
                )
                return

            if not slot_id.startswith("slot:"):
                continue
            idx = int(slot_id.split(":", 1)[1])
            slots = list(st.board_slots[0])
            codes = scheme_slot_codes(st.scheme[0])

            if action == "remove":
                removed = slots[idx]
                if removed is None:
                    continue
                slots[idx] = None
                st.apply_board_slots(0, slots, persist=True)
                self.io.update_hud(st.hud_status())
                avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
                self._tell(
                    f"Quitaste a {removed.name} de {role_text(codes[idx])}. "
                    f"Quedan {len(st.xi[0])} jugadores, calidad media {avg_txt}."
                )
                continue

            if action == "swap":
                if idx == 0:
                    self._tell(
                        "El portero no se intercambia con jugadores de campo; "
                        "pulsa Enter para cambiarlo desde el banquillo."
                    )
                    continue
                if swap_source_idx is None:
                    if slots[idx] is None:
                        self._tell("Ese puesto está vacío. Pulsa Enter para colocar un jugador.")
                        continue
                    swap_source_idx = idx
                    self._tell(
                        f"Seleccionado {slots[idx].name} para intercambiar. "
                        "Muévete a otro puesto y pulsa Espacio o Enter."
                    )
                elif swap_source_idx == idx:
                    swap_source_idx = None
                    self._tell("Intercambio cancelado.")
                else:
                    self._swap_board_slots(swap_source_idx, idx)
                    swap_source_idx = None
                continue

            # action == "select"
            if swap_source_idx is not None:
                if idx == 0:
                    self._tell("El portero no se intercambia con jugadores de campo.")
                elif swap_source_idx == idx:
                    swap_source_idx = None
                    self._tell("Intercambio cancelado.")
                else:
                    self._swap_board_slots(swap_source_idx, idx)
                    swap_source_idx = None
                continue

            occupant = slots[idx]
            if occupant is None:
                self._pick_bench_for_slot(idx)
                continue

            slot_ops = ["Cambiar por un jugador del banquillo"]
            slot_acts = ["bench"]
            if idx != 0:
                slot_ops.append("Intercambiar posición en el esquema")
                slot_acts.append("swap")
            slot_ops.extend(["Quitar del once", "Cancelar"])
            slot_acts.extend(["remove", "cancel"])
            badge = yellow_card_badge(occupant, limit=st.yellow_card_limit)
            choice = self._menu(
                f"{role_text(codes[idx]).capitalize()}: {occupant.name}, calidad {occupant.overall}{badge}",
                slot_ops,
                prematch=True,
            )
            if choice is None:
                continue
            picked_act = slot_acts[choice]
            if picked_act == "bench":
                self._pick_bench_for_slot(idx)
            elif picked_act == "swap":
                swap_source_idx = idx
                self._tell(
                    f"Seleccionado {occupant.name} para intercambiar. "
                    "Elige el puesto de destino en el esquema."
                )
            elif picked_act == "remove":
                slots[idx] = None
                st.apply_board_slots(0, slots, persist=True)
                self.io.update_hud(st.hud_status())
                avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
                self._tell(
                    f"Quitaste a {occupant.name} de {role_text(codes[idx])}. "
                    f"Quedan {len(st.xi[0])} jugadores, calidad media {avg_txt}."
                )

    def _squad_menu(self) -> None:
        """Before kickoff: edit lineup on the 2D tactical formation board."""
        self._lineup_board()

    # ------------------------------------------------------------------ Menus
    def menu(self, prematch: bool = False) -> None:
        """Open prematch preparation (`prematch=True`) or live tactical menu."""
        st = self.state
        pos = 0
        nones = 0
        while True:
            ops: list[str] = []
            acts: list[str] = []

            def add(act: str, text: str) -> None:
                acts.append(act)
                ops.append(text)

            if prematch:
                avg_txt = format_quality(st.lineup_average_quality(0, include_fatigue=False))
                add("start", f"Empezar el partido ({len(st.xi[0])} jugadores, calidad media {avg_txt})")
            add("scheme", f"Esquema: {st.scheme_label(0)}. Cambiar el esquema")
            add("lineup", "Leer mi once con las posiciones")
            if prematch:
                add(
                    "squad",
                    f"Alineación en el esquema: poner, quitar y mover jugadores ({len(st.xi[0])} de 11)",
                )
                add("bench", "Leer el banquillo")
            if all(self._wide_pairs(("LAT",))):
                add("lat", "Cambiar de banda a mis laterales o carrileros")
            if all(self._wide_pairs(("EXT",))) or all(self._wide_pairs(("ALA",))):
                add("ext", "Cambiar de banda a mis extremos o volantes")
            add("move", "Mover a un jugador a otra posición")
            add("takers", "Cobradores: penales, tiros libres y córners")
            add("mental", f"Mentalidad: {MENTALITY_NAMES[st.mentality(0)]}")
            if not prematch:
                add("perf", "Rendimiento de mis jugadores")
                add("flanks", "Por dónde me atacan")
            add("rival", "Ver el esquema y el once del rival")
            if not prematch:
                add("back", "Volver al partido")
            title = (
                "Preparación del partido"
                if prematch
                else "Táctica. Escape para volver al partido"
            )
            k = self._menu(title, ops, min(pos, len(ops) - 1), prematch=prematch)
            if k is None:
                nones += 1
                if not prematch:
                    return
                if nones >= 3:
                    if len(st.xi[0]) < MIN_STARTING_PLAYERS:
                        self._tell(
                            f"No puedes iniciar el partido con {len(st.xi[0])} jugadores. "
                            f"Debes colocar al menos {MIN_STARTING_PLAYERS} jugadores."
                        )
                        nones = 0
                        continue
                    return
                continue
            nones = 0
            pos = k
            act = acts[k]
            if act == "start":
                if len(st.xi[0]) < MIN_STARTING_PLAYERS:
                    self._tell(
                        f"No puedes iniciar el partido con {len(st.xi[0])} jugadores. "
                        f"Debes colocar al menos {MIN_STARTING_PLAYERS} jugadores."
                    )
                    self._lineup_board()
                    continue
                return
            if act == "back":
                return
            if act == "scheme":
                self._scheme_menu(prematch)
            elif act == "lineup":
                self._lines("Tu once y sus posiciones", self.lineup_lines())
            elif act == "squad":
                self._squad_menu()
            elif act == "bench":
                self._lines("Tu banquillo", self.bench_lines())
            elif act == "lat":
                self._swap_sides(("LAT",), prematch)
            elif act == "ext":
                self._swap_sides(("EXT", "ALA"), prematch)
            elif act == "move":
                self._move_menu(prematch)
            elif act == "takers":
                self._takers_menu(prematch=prematch)
            elif act == "mental":
                self._mentality_menu(prematch)
            elif act == "perf":
                self._lines("Rendimiento de tus jugadores", self.performance_lines())
            elif act == "flanks":
                self._lines("Por dónde te atacan", self.flank_lines())
            elif act == "rival":
                self._lines("Tu rival", self.rival_lines())
            if not prematch:
                st.lost_seconds += 10

    def prematch_menu(self) -> None:
        self.menu(prematch=True)

    def in_match_menu(self) -> None:
        self.menu(prematch=False)

    # --------------------------------------------------------------- AI Tactics
    def ai_adjust(self, idx: int) -> None:
        """Adjust AI (or simulated user team) mentality and scheme after 60 minutes."""
        st = self.state
        if idx == 0 and not st.auto:
            return
        minute = st.minute()
        if minute < 60 or st.turn % (5 * st.factor) != 0 or minute == st.last_tactic_minute[idx]:
            return
        st.last_tactic_minute[idx] = minute
        diff = st.goals[idx] - st.goals[1 - idx]
        name = st.team_name(idx)
        if diff < 0:
            if st.mentality(idx) >= 2:
                return
            st.set_mentality(idx, st.mentality(idx) + 1)
            new = None
            if (
                minute >= 70
                and st.scheme[idx] not in ("3-4-3", "4-3-3", "3-5-2")
                and st.roll(0.7)
            ):
                new = st.rng.choice(("3-4-3", "4-3-3", "3-5-2"))
                self.apply_scheme(idx, new)
            self._announce(f"{name} se vuelca al ataque{f' y cambia a un {new}' if new else ''}.")
        elif diff > 0 and minute >= 70:
            if st.mentality(idx) <= -2:
                return
            st.set_mentality(idx, st.mentality(idx) - 1)
            new = None
            if (
                minute >= 75
                and st.scheme[idx] not in ("5-4-1", "5-3-2", "4-5-1")
                and st.roll(0.6)
            ):
                new = st.rng.choice(("5-4-1", "5-3-2", "4-5-1"))
                self.apply_scheme(idx, new)
            self._announce(
                f"{name} se cierra atrás para defender el resultado"
                f"{f' y pasa a un {new}' if new else ''}."
            )

    def _announce(self, text: str) -> None:
        if not self.state.muted:
            self._say(text)
