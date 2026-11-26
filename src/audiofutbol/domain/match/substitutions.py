"""Substitutions (with natural vs cover-role choice and GK protection), fatigue, injuries, time-wasting."""

from __future__ import annotations

from typing import Callable

from audiofutbol.domain.formations import (
    DEFAULT_ROLE_BY_GROUP,
    fit,
    group_of,
    preferred_role,
    preferred_role_text,
)
from audiofutbol.domain.match.board import (
    build_live_board_rows,
    format_quality,
    yellow_card_badge,
)
from audiofutbol.domain.match.conditional_change_menu import edit_change_plan
from audiofutbol.domain.match.conditional_changes import ConditionalChange
from audiofutbol.domain.match.ports import MatchIO
from audiofutbol.domain.match.state import MatchState
from audiofutbol.domain.models import POSITION_NAMES_ES, Player


class SubstitutionManager:
    """Manages squad fatigue, injuries, manual/AI substitutions, and time-wasting."""

    def __init__(
        self,
        state: MatchState,
        io: MatchIO,
        crowd_react: Callable[[str, float], None],
        give_card: Callable[[int, Player, str, str | None], None],
    ) -> None:
        self.state = state
        self.io = io
        self._crowd_react = crowd_react
        self._give_card = give_card
        self.planned: list[ConditionalChange] = []

    def _speak(self, text: str, interrupt: bool = False) -> None:
        if not self.state.muted:
            self.io.speak(text, interrupt=interrupt)

    def _sfx(self, event: str) -> None:
        if not self.state.muted:
            self.io.play_sfx(event)

    def bench(self, team_idx: int) -> list[Player]:
        on_pitch = {id(p) for p in self.state.xi[team_idx]}
        return [
            p
            for p in self.state.teams[team_idx].players
            if id(p) not in on_pitch
            and id(p) not in self.state.subbed_off[team_idx]
            and id(p) not in self.state.excluded_suspended[team_idx]
            and p.available and id(p) not in self.state.injured
        ]

    def eligible_replacements(self, team_idx: int, out_player: Player) -> list[Player]:
        """Return valid bench replacements for `out_player`.

        Prevents subbing a backup goalkeeper in for an outfield player while a
        goalkeeper is already on the pitch. When replacing a goalkeeper, or when
        the team currently has no goalkeeper on the pitch, prioritizes backup
        goalkeepers first.
        """
        bench_players = self.bench(team_idx)
        out_role = self.state.player_role(out_player)
        has_gk_on_pitch = any(
            self.state.player_role(p) == "POR" for p in self.state.xi[team_idx]
        )
        if out_role != "POR" and has_gk_on_pitch:
            outfield = [p for p in bench_players if p.position != "POR"]
            return sorted(
                outfield, key=lambda p: (p.position != out_role, -p.overall)
            )
        if not has_gk_on_pitch:
            return sorted(
                bench_players,
                key=lambda p: (p.position != "POR", p.position != out_role, -p.overall),
            )
        return sorted(
            bench_players, key=lambda p: (p.position != "POR", -p.overall)
        )

    def remaining_subs(self, team_idx: int, human: bool = False) -> int | None:
        limit = (
            self.state.max_substitutions
            if (human and team_idx == 0)
            else 5 + self.state.extra_time_sub_bonus
        )
        if limit is None:
            return None
        return max(0, limit - self.state.substitutions_used[team_idx])

    def player_status_text(self, player: Player) -> str:
        fatigue_pct = int(round(self.state.fatigue.get(id(player), 0.0)))
        role = self.state.player_role(player)
        pos_txt = self.state.slot_text(player)
        if role != player.position:
            pos_txt += f" (natural: {POSITION_NAMES_ES[player.position]})"
        text = (
            f"{player.name}, {pos_txt}, calidad efectiva {int(round(self.state.effective_overall(player)))}, "
            f"cansancio {fatigue_pct} por ciento"
        )
        if id(player) in self.state.injured:
            text += ", lesionado"
        text += yellow_card_badge(
            player, self.state.match_yellows.get(id(player), 0), in_match=True,
            limit=self.state.yellow_card_limit,
        )
        return text

    def remaining_subs_text(self, team_idx: int = 0, human: bool = True) -> str:
        rem = self.remaining_subs(team_idx, human=human)
        if rem is None:
            return "Cambios ilimitados"
        if rem == 0:
            return "Ya no te quedan cambios"
        suffix = "" if rem == 1 else "s"
        return f"Te quedan {rem} cambio{suffix}"

    def apply_substitution(
        self,
        team_idx: int,
        out_player: Player,
        in_player: Player,
        play_as_position: str | None = None,
    ) -> None:
        idx = self.state.xi[team_idx].index(out_player)
        self.state.xi[team_idx][idx] = in_player
        self.state.subbed_off[team_idx].add(id(out_player))
        self.state.position_overrides.pop(id(out_player), None)
        if play_as_position and play_as_position != in_player.position:
            self.state.position_overrides[id(in_player)] = play_as_position
        else:
            self.state.position_overrides.pop(id(in_player), None)

        self.state.substitutions_used[team_idx] += 1
        self.state.lost_seconds += 25
        self.state.fatigue.setdefault(id(in_player), 0.0)
        if self.state.ball_carrier is out_player:
            self.state.ball_carrier = in_player

        has_natural_gk = any(
            p.position == "POR" and self.state.player_role(p) == "POR"
            for p in self.state.xi[team_idx]
        )
        self.state.gk_penalty[team_idx] = 0 if has_natural_gk else -25
        self._assign_incoming_slot(team_idx, out_player, in_player)
        self.state.sort_lineup(team_idx)
        self.state.sync_board_slots(team_idx)
        self.state.ratings[team_idx] = self.state.compute_ratings(team_idx)
        self._sfx("cambio")
        self.io.update_hud(self.state.hud_status())

    def _assign_incoming_slot(
        self, team_idx: int, out_player: Player, in_player: Player
    ) -> None:
        """Inherit outgoing player's slot on the same line, or use incoming natural slot."""
        st = self.state
        out_slot = st.slot.pop(id(out_player), None)
        st.fit.pop(id(out_player), None)
        group = st.player_role(in_player)
        if group == "POR":
            slot = "POR"
        elif out_slot and group_of(out_slot) == group and group_of(out_slot) != "POR":
            slot = out_slot
        else:
            natural = preferred_role(in_player)
            slot = natural if group_of(natural) == group else DEFAULT_ROLE_BY_GROUP[group]
        st.slot[id(in_player)] = slot
        st.fit[id(in_player)] = (
            fit(in_player, slot)
            if slot != "POR"
            else (1.0 if in_player.position == "POR" else 0.3)
        )
        st.sync_roles(team_idx)

    def read_lineup(self) -> None:
        avg_txt = format_quality(self.state.lineup_average_quality(0, include_fatigue=True))
        lines = [f"{self.state.formation_text(0)}. Calidad media {avg_txt}."]
        lines.extend(self.player_status_text(p) for p in self.state.xi[0])
        lines.append(
            f"Cambios hechos: {self.state.substitutions_used[0]}. "
            f"{self.remaining_subs_text(0)}."
        )
        self.io.read_lines("Tu alineación en el campo", lines)

    def _preview_formation_code(self, out_player: Player, in_player: Player, as_role: str) -> str:
        c = self.state.formation_counts(0)
        old_role = self.state.player_role(out_player)
        c[old_role] = max(0, c.get(old_role, 0) - 1)
        c[as_role] = c.get(as_role, 0) + 1
        return f"{c['DEF']}-{c['MED']}-{c['DEL']}"

    def open_substitution_menu(self, forced_out: Player | None = None) -> bool:
        rem = self.remaining_subs(0, human=True)
        if rem is not None and rem <= 0:
            self.io.speak(
                f"Ya hiciste tus {self.state.max_substitutions} cambios. No puedes cambiar más.",
                interrupt=True,
            )
            return False
        if not self.bench(0):
            self.io.speak("No tienes suplentes disponibles.", interrupt=True)
            return False

        last_slot_id: str | None = None
        while True:
            if forced_out is not None:
                out_player = forced_out
            else:
                rows = build_live_board_rows(
                    self.state, 0, action_label="Cancelar cambio", include_fatigue=True
                )
                avg_txt = format_quality(
                    self.state.lineup_average_quality(0, include_fatigue=True)
                )
                res = self.io.choose_formation(
                    f"Cambios. {self.state.formation_text(0)}. {self.remaining_subs_text(0)}. ¿Quién sale?",
                    rows,
                    status_line=f"{self.state.formation_text(0)} | Calidad media: {avg_txt}",
                    initial_slot_id=last_slot_id,
                    allow_remove=False,
                    allow_swap_key=False,
                )
                if res is None:
                    return False
                _action, slot_id = res
                if slot_id == "action:cancel" or not slot_id.startswith("player:"):
                    return False
                last_slot_id = slot_id
                pid = int(slot_id.split(":", 1)[1])
                out_player = next((p for p in self.state.xi[0] if id(p) == pid), None)
                if out_player is None:
                    continue

            candidates = self.eligible_replacements(0, out_player)
            if not candidates:
                self.io.speak(
                    "No tienes suplentes de campo disponibles para ese cambio. "
                    "Un portero suplente no puede entrar como jugador de campo.",
                    interrupt=True,
                )
                if forced_out is not None:
                    return False
                continue

            idx_in = self.io.choose(
                f"Sale {out_player.name}. ¿Quién entra?",
                [
                    f"{p.name}, {preferred_role_text(p)}, calidad {p.overall}"
                    f"{yellow_card_badge(p, limit=self.state.yellow_card_limit)}"
                    for p in candidates
                ],
            )
            if idx_in is None:
                if forced_out is not None:
                    return False
                continue

            in_player = candidates[idx_in]
            out_role = self.state.player_role(out_player)
            chosen_role = in_player.position

            # Ask tactical role if natural positions differ on outfield players
            if out_role != "POR" and in_player.position == "POR":
                chosen_role = "POR"
            elif out_role != "POR" and in_player.position != out_role:
                natural_code = self._preview_formation_code(out_player, in_player, in_player.position)
                cover_code = self._preview_formation_code(out_player, in_player, out_role)
                role_choice = self.io.choose(
                    f"{in_player.name} es {POSITION_NAMES_ES[in_player.position]}, "
                    f"pero sale {out_player.name} que jugaba de {POSITION_NAMES_ES[out_role]}. "
                    "¿Dónde lo colocas?",
                    [
                        f"En su posición natural ({POSITION_NAMES_ES[in_player.position]}): cambia el dibujo a {natural_code}, rinde al 100 por ciento",
                        f"En la posición de {out_player.name} ({POSITION_NAMES_ES[out_role]}): mantiene el dibujo {cover_code}, rinde algo menos fuera de puesto",
                    ],
                )
                if role_choice is None:
                    if forced_out is not None:
                        return False
                    continue
                chosen_role = in_player.position if role_choice == 0 else out_role
            elif out_role == "POR" and in_player.position != "POR":
                chosen_role = "POR"

            role_desc = (
                f"como {POSITION_NAMES_ES[chosen_role]}"
                if chosen_role != in_player.position
                else f"en su posición natural de {POSITION_NAMES_ES[in_player.position]}"
            )
            if self.io.confirm(
                f"Sale {out_player.name} y entra {in_player.name} {role_desc}. ¿Confirmas el cambio?"
            ):
                self.apply_substitution(0, out_player, in_player, play_as_position=chosen_role)
                msg = (
                    f"Cambio hecho. Sale {out_player.name}, entra {in_player.name} {role_desc}. "
                    f"Dibujo actual {self.state.formation_code(0)}. {self.remaining_subs_text(0)}."
                )
                if out_role == "POR" and in_player.position != "POR":
                    msg += " Cuidado, te quedas sin portero natural."
                self.io.speak(msg)
                return True

    def handle_goalkeeper_sent_off(self, team_idx: int) -> None:
        """Prompt user (or AI) to sacrifice an outfield player for a backup GK on red card."""
        backup_gks = sorted(
            (p for p in self.bench(team_idx) if p.position == "POR"),
            key=lambda p: -p.overall,
        )
        is_human = team_idx == 0 and not self.state.auto
        rem = self.remaining_subs(team_idx, human=is_human)
        has_subs = rem is None or rem > 0

        if not has_subs or not backup_gks or not self.state.xi[team_idx]:
            self.state.gk_penalty[team_idx] = -25
            self.state.ratings[team_idx] = self.state.compute_ratings(team_idx)
            self.io.update_hud(self.state.hud_status())
            if is_human:
                if not has_subs:
                    self._speak(
                        "El portero se va expulsado y ya no te quedan cambios. Un jugador de campo se pone los guantes."
                    )
                else:
                    self._speak(
                        "El portero se va expulsado y no tienes otro portero disponible en el banquillo. Un jugador de campo se pone los guantes."
                    )
            else:
                self._speak(
                    f"El portero de {self.state.team_name(team_idx)} se va expulsado y un jugador de campo se pone los guantes."
                )
            return

        if is_human:
            self.io.speak(
                "¡Te quedaste sin portero! Tienes portero suplente en el banquillo. "
                "Elige qué jugador de campo sale para que entre el portero suplente."
            )
            while True:
                rows = build_live_board_rows(
                    self.state,
                    0,
                    action_label="No meter al portero suplente",
                    exclude_gk=True,
                    include_fatigue=True,
                )
                res = self.io.choose_formation(
                    f"Expulsión del portero. {self.remaining_subs_text(0)}. "
                    "¿Qué jugador de campo sale para que entre el portero suplente?",
                    rows,
                    status_line=f"{self.state.formation_text(0)} | Elige al jugador que sale",
                )
                out_player: Player | None = None
                if res is not None:
                    _act, slot_id = res
                    if slot_id.startswith("player:"):
                        pid = int(slot_id.split(":", 1)[1])
                        out_player = next((p for p in self.state.xi[0] if id(p) == pid), None)
                if out_player is None:
                    if self.io.confirm(
                        "¿Seguro que no quieres meter al portero suplente? Un jugador de campo tendrá que ponerse los guantes."
                    ):
                        self.state.gk_penalty[0] = -25
                        self.state.ratings[0] = self.state.compute_ratings(0)
                        self.io.update_hud(self.state.hud_status())
                        self.io.speak(
                            "No realizas el cambio. Un jugador de campo se pone los guantes."
                        )
                        return
                    continue

                if len(backup_gks) == 1:
                    in_gk = backup_gks[0]
                else:
                    idx_gk = self.io.choose(
                        f"Sale {out_player.name}. ¿Qué portero suplente entra?",
                        [
                            f"{p.name}, portero, calidad {p.overall}"
                            for p in backup_gks
                        ],
                    )
                    if idx_gk is None:
                        continue
                    in_gk = backup_gks[idx_gk]

                if self.io.confirm(
                    f"Sale {out_player.name} y entra el portero {in_gk.name}. ¿Confirmas el cambio?"
                ):
                    self.apply_substitution(0, out_player, in_gk, play_as_position="POR")
                    self.io.speak(
                        f"Cambio de portero realizado. Sale {out_player.name}, entra {in_gk.name}. "
                        f"Dibujo actual {self.state.formation_code(0)}. {self.remaining_subs_text(0)}."
                    )
                    return

        in_gk = backup_gks[0]
        sacrifice_priority = {"DEL": 0, "MED": 1, "DEF": 2, "POR": 3}
        out_player = min(
            self.state.xi[team_idx],
            key=lambda p: (
                sacrifice_priority.get(self.state.player_role(p), 2),
                self.state.effective_overall(p),
            ),
        )
        self.apply_substitution(team_idx, out_player, in_gk, play_as_position="POR")
        self._speak(
            f"Tras la expulsión del portero, {self.state.team_name(team_idx)} realiza un cambio: "
            f"sale {out_player.name} y entra el portero suplente {in_gk.name}."
        )

    def request_substitution(self) -> str | None:
        """Handle pressing C: open immediately on dead ball or notify 4th official."""
        if self.state.in_penalty_shootout:
            self.io.speak(
                "No se pueden hacer cambios durante la tanda de penales.",
                interrupt=True,
            )
            return None
        rem = self.remaining_subs(0, human=True)
        if rem is not None and rem <= 0:
            self.io.speak(
                f"Ya hiciste tus {self.state.max_substitutions} cambios. No puedes cambiar más.",
                interrupt=True,
            )
            return None
        if not self.bench(0):
            self.io.speak("No tienes suplentes disponibles.", interrupt=True)
            return None

        if not self.state.ball_in_play:
            self.state.pending_substitution = False
            self.open_substitution_menu()
            self.io.update_hud(self.state.hud_status())
            return "releer"

        if self.state.pending_substitution:
            if self.io.confirm(
                "Ya le avisaste al cuarto árbitro para hacer un cambio en la próxima detención del juego. "
                "¿Quieres cancelar el aviso?"
            ):
                self.state.pending_substitution = False
                self.io.update_hud(self.state.hud_status())
                self.io.speak("Aviso al cuarto árbitro cancelado.", interrupt=True)
            else:
                self.io.speak(
                    "Se mantiene el aviso al cuarto árbitro. El cambio se realizará en cuanto se detenga el juego.",
                    interrupt=True,
                )
            return "releer"

        self.state.pending_substitution = True
        self.io.update_hud(self.state.hud_status())
        self.io.speak(
            "Le avisas al cuarto árbitro que harás un cambio. "
            "Se realizará automáticamente en la próxima detención del juego.",
            interrupt=True,
        )
        return None

    def edit_plan(self) -> None:
        st = self.state
        self.planned = edit_change_plan(
            self.io, st.xi[0], self.bench(0), self.planned,
            minute=st.minute(), role_for=st.player_role,
        )

    def record_unexecuted_plan(self) -> None:
        for rule in self.planned:
            self.state.add_highlight(
                f"Cambio programado no ejecutado: {rule.outgoing} por {rule.incoming}. "
                "No se cumplió la condición o no había jugadores o cambios disponibles."
            )

    def apply_planned(self, *, only_player: Player | None = None) -> bool:
        st = self.state
        if not self.planned or st.abandoned or st.suspended_match or st.in_penalty_shootout:
            return False
        changed = False
        rules = sorted(self.planned, key=lambda rule: (rule.condition != "injured", rule.minute))
        for rule in rules:
            rem = self.remaining_subs(0, human=True)
            if rem is not None and rem <= 0:
                break
            players = rule.players(st.xi[0], self.bench(0))
            if players is None:
                continue
            out, incoming = players
            if only_player is not None and out is not only_player:
                continue
            if not rule.matches(st.minute(), st.goals[0] - st.goals[1], st.fatigue.get(id(out), 0.),
                                injured=id(out) in st.injured,
                                red_card_advantage=st.red_cards[1] - st.red_cards[0]):
                continue
            role = st.player_role(out)
            if (role == "POR") != (incoming.position == "POR"):
                continue
            self.apply_substitution(0, out, incoming, play_as_position=role)
            self.planned.remove(rule)
            why = " por lesión" if id(out) in st.injured else ""
            text = f"Cambio programado{why}: sale {out.name}, entra {incoming.name}."
            st.add_highlight(text)
            self._speak(text)
            changed = True
        return changed

    def process_pending_substitution(self, reason: str | None = None) -> bool:
        """Execute a queued substitution when play stops (dead ball, foul, out of bounds)."""
        if not self.state.pending_substitution or self.state.auto:
            return self.apply_planned()
        if (
            self.state.abandoned
            or self.state.suspended_match
            or self.state.in_penalty_shootout
        ):
            return False

        self.state.pending_substitution = False
        self.io.update_hud(self.state.hud_status())
        rem = self.remaining_subs(0, human=True)
        if (rem is not None and rem <= 0) or not self.bench(0):
            self.io.speak(
                "El juego se detuvo, pero ya no tienes cambios ni suplentes disponibles."
            )
            return False

        if reason:
            self.io.speak(
                f"Se detiene el juego por {reason}. "
                "El cuarto árbitro levanta el tablero electrónico para tu cambio."
            )
        else:
            self.io.speak(
                "Se detiene el juego. El cuarto árbitro levanta el tablero electrónico para tu cambio."
            )

        prev_in_play = self.state.ball_in_play
        self.state.ball_in_play = False
        try:
            done = self.open_substitution_menu()
        finally:
            self.state.ball_in_play = prev_in_play

        if not done:
            self.io.speak("No hiciste el cambio. Se reanuda el juego.")
        return self.apply_planned() or done

    def ai_substitutions(self, team_idx: int) -> None:
        if team_idx == 0 and not self.state.auto:
            return
        rem = self.remaining_subs(team_idx)
        if (rem is not None and rem <= 0) or not self.state.xi[team_idx]:
            return
        candidates = [
            p
            for p in self.state.xi[team_idx]
            if id(p) in self.state.injured
            or (
                self.state.turn >= 20 * self.state.factor
                and self.state.fatigue.get(id(p), 0.0) >= 68
            )
        ]
        if not candidates:
            return
        out_player = max(
            candidates,
            key=lambda p: (id(p) in self.state.injured, self.state.fatigue.get(id(p), 0.0)),
        )
        if id(out_player) not in self.state.injured and not self.state.roll(
            0.25 / self.state.factor
        ):
            return
        replacements = self.eligible_replacements(team_idx, out_player)
        if not replacements:
            return
        out_role = self.state.player_role(out_player)
        same_pos = [p for p in replacements if p.position == out_role]
        if not same_pos and out_role == "POR" and id(out_player) not in self.state.injured:
            return
        pool = same_pos or replacements
        in_player = max(pool, key=lambda p: p.overall)
        play_as = "POR" if out_role == "POR" else in_player.position
        self.apply_substitution(team_idx, out_player, in_player, play_as_position=play_as)
        self._speak(
            f"Cambio en {self.state.team_name(team_idx)}: sale {out_player.name}, entra {in_player.name}."
        )

    def check_injuries(self) -> None:
        for team_idx in (0, 1):
            if not self.state.xi[team_idx] or not self.state.roll(
                0.006 / self.state.factor
            ):
                continue
            weights = [
                1.0 + self.state.fatigue.get(id(p), 0.0) / 40.0
                for p in self.state.xi[team_idx]
            ]
            player = self.state.rng.choices(self.state.xi[team_idx], weights=weights)[0]
            if id(player) in self.state.injured:
                continue
            self.state.injured.add(id(player))
            self.state.lost_seconds += 60
            self._sfx("silbato")
            self._speak(
                f"¡{player.name}, de {self.state.team_name(team_idx)}, "
                "se queda tendido en el campo! Parece una lesión."
            )
            self.state.add_highlight(
                f"Se lesiona {player.name}, de {self.state.team_name(team_idx)}."
            )
            self.state.ratings[team_idx] = self.state.compute_ratings(team_idx)
            self._replace_injured(team_idx, player)
            self.process_pending_substitution("la lesión")

    def _replace_injured(self, team_idx: int, player: Player) -> None:
        if team_idx == 0 and self.apply_planned(only_player=player):
            return
        if team_idx or self.state.auto:
            self.ai_substitutions(team_idx)
            return
        rem = self.remaining_subs(0, human=True)
        if (rem is None or rem > 0) and self.eligible_replacements(0, player):
            self.io.speak("Elige quién entra por el jugador lesionado.")
            if self.open_substitution_menu(forced_out=player):
                return
        self._speak(f"{player.name} seguirá jugando lesionado y rendirá mucho menos.")

    def apply_turn_fatigue(self) -> None:
        rates = {"POR": 0.5, "DEF": 2.0, "MED": 2.6, "DEL": 2.3}
        user_stamina_mult = float(self.state.tactic_profile().get("stamina", 1.0))
        for team_idx in (0, 1):
            mult = user_stamina_mult if team_idx == 0 else 1.0
            for player in self.state.xi[team_idx]:
                pid = id(player)
                role = self.state.player_role(player)
                delta = (
                    rates.get(role, 2.0)
                    * mult
                    * self.state.rng.uniform(0.8, 1.2)
                    / self.state.factor
                )
                self.state.fatigue[pid] = min(100.0, self.state.fatigue.get(pid, 0.0) + delta)

        if not self.state.muted:
            for player in self.state.xi[0]:
                pid = id(player)
                if (
                    self.state.fatigue.get(pid, 0.0) >= 75
                    and pid not in self.state.fatigue_warned
                    and pid not in self.state.injured
                    and self.state.turn - self.state.last_fatigue_warn_turn
                    >= 4 * self.state.factor
                ):
                    self.state.fatigue_warned.add(pid)
                    self.state.last_fatigue_warn_turn = self.state.turn
                    self._speak(
                        f"{player.name}, de tu equipo, está muy cansado. Puedes pedir su cambio con la tecla C."
                    )
                    break

    def _time_waste_phrase(self, player: Player) -> str:
        if self.state.player_role(player) == "POR":
            return self.state.rng.choice(
                [
                    "tarda una eternidad en sacar de meta",
                    "se queda con el balón en las manos y no lo suelta",
                    "se agacha a atarse los botines antes de sacar",
                ]
            )
        return self.state.rng.choice(
            [
                "retrasa el saque a propósito",
                "se tira al suelo y pide atención médica",
                "camina despacio a buscar el balón",
                "se queda discutiendo con el árbitro",
                "coloca el balón una y otra vez antes del saque",
            ]
        )

    def waste_time(self, team_idx: int = 0) -> bool:
        if self.state.suspended_match or self.state.abandoned:
            return False
        if self.state.last_time_waste_turn.get(team_idx) == self.state.turn:
            if team_idx == 0:
                self.io.speak(
                    "Ya hiciste tiempo en esta jugada. Espera a la siguiente.",
                    interrupt=True,
                )
            return False

        self.state.last_time_waste_turn[team_idx] = self.state.turn
        player = self.state.pick_player(
            team_idx, {"POR": 1.2, "DEF": 3.0, "MED": 2.5, "DEL": 1.0}
        )
        secs = self.state.rng.choice((20, 30, 40))
        self.state.lost_seconds += secs
        self.state.wasted_seconds += secs
        times = self.state.time_waste_by_player.get(id(player), 0)
        self.state.time_waste_by_player[id(player)] = times + 1
        self.state.time_waste_by_team[team_idx] += 1

        for teammate in self.state.xi[team_idx]:
            pid = id(teammate)
            if pid in self.state.fatigue:
                self.state.fatigue[pid] = max(0.0, self.state.fatigue[pid] - 4.0)

        self._sfx("silbato")
        self._speak(
            f"¡Pausa! {player.name}, de {self.state.team_name(team_idx)}, "
            f"hace tiempo: {self._time_waste_phrase(player)}."
        )
        if team_idx == 1:
            self._crowd_react("abucheo", 1.4)
        if team_idx == 0 and self.state.goals[0] < self.state.goals[1]:
            self._speak("Ojo: vas perdiendo, y perder tiempo no te ayuda.")

        prob_yellow = min(
            0.9,
            (0.12 if times == 0 else 0.75)
            + 0.06 * max(0, self.state.time_waste_by_team[team_idx] - 2),
        )
        if self.state.roll(prob_yellow):
            self._speak("El árbitro se acerca y lo amonesta por perder tiempo.")
            self._give_card(team_idx, player, "amarilla", "por perder tiempo")
        elif times == 0:
            self._speak("El árbitro le llama la atención y le pide que juegue.")
        else:
            self._speak("El árbitro le advierte otra vez: la próxima será tarjeta.")
        return True

    def ai_waste_time(self) -> None:
        if (
            self.state.suspended_match
            or self.state.total_turns <= 0
            or self.state.turn < 0.65 * self.state.total_turns
        ):
            return
        score = (
            self.state.aggregate()
            if self.state.first_leg is not None
            else self.state.goals
        )
        teams_to_check = (1,) if not self.state.auto else (0, 1)
        for team_idx in teams_to_check:
            if score[team_idx] > score[1 - team_idx] and self.state.roll(
                0.05 / self.state.factor
            ):
                self._speak(f"Minuto {self.state.minute()}.")
                self.waste_time(team_idx)
