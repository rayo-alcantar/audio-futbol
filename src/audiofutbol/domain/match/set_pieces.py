"""Set pieces, shots, goals, duels, aerial play, fouls, cards, and shootouts."""

from __future__ import annotations

from typing import Callable

from audiofutbol.domain.formations import stable_hash
from audiofutbol.domain.match.commentary import MatchCommentary
from audiofutbol.domain.match.ports import MatchIO
from audiofutbol.domain.match.state import PENALTY_DIRECTIONS, ZONES_OWN, MatchState
from audiofutbol.domain.match.var import VarSystem
from audiofutbol.domain.models import Player

NO_ASSIST_GOAL_TYPES = frozenset(
    {"de penal", "de tiro libre", "gol olímpico", "de contrarremate"}
)
NO_VAR_GOAL_TYPES = frozenset({"de penal", "de tiro libre", "gol olímpico"})


class SetPieceResolver:
    """Resolves shots, goals, fouls, cards, corners, free kicks, penalties, and restarts."""

    def __init__(
        self,
        state: MatchState,
        io: MatchIO,
        var: VarSystem,
        choose_fn: Callable[..., int],
        crowd_react: Callable[[str, float], None],
        commentary: MatchCommentary | None = None,
    ) -> None:
        self.state = state
        self.io = io
        self.var = var
        self._choose = choose_fn
        self._crowd_react = crowd_react
        self.commentary = commentary
        self.on_goalkeeper_sent_off: Callable[[int], None] | None = None
        self.on_stoppage: Callable[[str | None], bool] | None = None

    def _notify_stoppage(self, reason: str) -> None:
        if self.on_stoppage is not None:
            self.on_stoppage(reason)

    def _speak(self, text: str) -> None:
        if not self.state.muted:
            self.io.speak(text)

    def _sfx(self, event: str, pan: float | None = None) -> None:
        if not self.state.muted:
            self.io.play_sfx(event, pan=pan)

    def _announce_shots(self, team_idx: int) -> None:
        if self.state.settings.shot_notice_enabled:
            self._speak(self.state.shots_text(team_idx))

    def _announce_scoreboard(self) -> None:
        self._speak(self.state.scoreboard_text())
        self.io.update_hud(self.state.hud_status())

    # ------------------------------------------------------- Goalkeeper 1v1
    def goalkeeper_duel(self, att_idx: int, striker: Player | None = None) -> tuple[bool, float]:
        def_idx = 1 - att_idx
        gk = self.state.goalkeeper(def_idx)
        if gk is None:
            return False, 1.0
        striker = striker or self.state.pick_player(
            att_idx, {"DEL": 5.0, "MED": 2.0, "DEF": 0.3, "POR": 0.0}
        )
        self._speak(f"¡{striker.name} se queda solo frente al portero {gk.name}!")
        roll = self.state.rng.random()

        if roll < 0.03:
            self.state.fouls[def_idx] += 1
            self._sfx("falta")
            self.state.lost_seconds += 5
            self._crowd_react("abucheo" if def_idx == 0 else "ovacion", 1.8)
            if self.state.roll(0.5):
                self._speak(
                    f"¡El portero {gk.name} sale desesperado y derriba a {striker.name} dentro del área!"
                )
            else:
                self._speak(
                    f"¡El portero {gk.name} sale a cortar y se lleva por delante a {striker.name}! "
                    "El árbitro señala falta."
                )
            r = self.state.rng.random()
            if r < 0.15:
                self.give_card(def_idx, gk, self.var.review_red_card(def_idx, gk))
            elif r < 0.65:
                self.give_card(def_idx, gk, "amarilla")
            self.state.add_highlight(
                f"Penal por derribo del portero {gk.name}, de {self.state.team_name(def_idx)}, sobre {striker.name}."
            )
            if self.state.suspended_match:
                return True, 1.0
            self.state.set_possession(att_idx, 3)
            self._notify_stoppage("la falta en el área")
            self.var.review_penalty(def_idx, att_idx, self.free_kick, self.penalty)
            return True, 1.0

        if roll < 0.095:
            self._speak(
                f"El portero {gk.name} sale muy lejos de su área para cortar el pase."
            )
            if self.state.roll(0.62 + (self.state.rating(def_idx, "gk") - 70) / 100.0 * 0.5):
                self._sfx("parada")
                if self.state.roll(0.5):
                    self._speak("Llega primero y despeja de pie, lejos del área.")
                else:
                    self._speak(
                        f"Se adelanta a {striker.name} y despeja de cabeza, fuera del área."
                    )
                if self.state.roll(0.4):
                    self.state.add_highlight(
                        f"El portero {gk.name}, de {self.state.team_name(def_idx)}, sale lejos del área y corta el pase de peligro."
                    )
                self.state.set_possession(def_idx, 1, carrier=gk)
                return True, 1.0
            self._speak(f"¡Llega tarde y {striker.name} lo supera! El arco queda vacío.")
            return False, 3.0

        if roll < 0.30:
            if self.state.roll(0.5):
                self._speak(
                    f"El portero {gk.name} sale a achicar el ángulo y {striker.name} se queda con poco espacio."
                )
            else:
                self._speak(
                    f"{striker.name} se planta ante el portero, que sale a su encuentro y cierra el ángulo."
                )
            return False, 0.78

        return False, 1.0

    # ------------------------------------------------------- Aerial & Rebounds
    def defensive_header(self, def_idx: int, att_idx: int, from_corner: bool = False) -> None:
        defender = self.state.pick_player(
            def_idx, {"DEF": 6.0, "MED": 1.3, "DEL": 0.4, "POR": 0.0}
        )
        self._sfx("cabezazo", self.state.rng.uniform(-0.6, 0.6))
        phrase = self.state.rng.choice(
            [
                "¡Cabezazo defensivo de %s! Despeja el centro.",
                "%s se eleva por encima de todos y despeja de cabeza.",
                "¡%s cabecea con fuerza y aleja el peligro!",
            ]
        )
        self._speak(phrase % defender.name)
        if self.state.roll(0.25):
            self.state.add_highlight(
                f"Cabezazo defensivo de {defender.name}, de {self.state.team_name(def_idx)}, que evita el peligro."
            )
        if self.state.can_chain_corner(att_idx, from_corner) and self.state.roll(0.22):
            self._speak("El despeje sale por la línea de fondo.")
            self.corner(att_idx, consecutive=from_corner)
        else:
            self.state.set_possession(def_idx, 1, carrier=defender)

    def aerial_defense(
        self, att_idx: int, label: str, from_corner: bool = False
    ) -> tuple[str, float]:
        def_idx = 1 - att_idx
        diff = (self.state.rating(def_idx, "dfn") - self.state.rating(att_idx, "att")) / 100.0
        gk = self.state.goalkeeper(def_idx)

        if def_idx == 0:
            choice = self._choose(
                f"{label} del rival. ¿Cómo defiendes?",
                [
                    "Despejar de cabeza con los centrales",
                    "Que el portero salga a atrapar el balón",
                    "Marcar de cerca a los rematadores",
                ],
                [45, 30, 25],
                None,
            )
            if self.state.abandoned:
                return "sigue", 1.0
        else:
            choice = self.state.rng.choices((0, 1, 2), weights=[50, 28, 22])[0]

        if choice == 1 and gk is None:
            choice = 0

        if choice == 0:
            if self.state.roll(0.42 + diff * 0.55):
                self.defensive_header(def_idx, att_idx, from_corner)
                return "despeje", 1.0
            return "sigue", 1.0

        if choice == 1 and gk is not None:
            if self.state.roll(0.40 + (self.state.rating(def_idx, "gk") - 70) / 100.0 * 0.6):
                self._sfx("parada")
                phrase = self.state.rng.choice(
                    [
                        "El portero %s sale con decisión y atrapa el balón en el aire.",
                        "El portero %s sale a los puños y despeja el balón.",
                    ]
                )
                self._speak(phrase % gk.name)
                self.state.set_possession(def_idx, 1, carrier=gk)
                return "portero", 1.0
            if self.state.roll(0.25):
                self._speak(
                    f"¡El portero {gk.name} sale en falso y no llega! La portería queda desprotegida."
                )
                return "sigue", 1.35
            self._speak(f"El portero {gk.name} sale pero no alcanza el balón.")
            return "sigue", 1.10

        if def_idx == 0:
            self._speak("Marcas de cerca a los rematadores.")
        if self.state.roll(0.12 + diff * 0.3):
            self.defensive_header(def_idx, att_idx, from_corner)
            return "despeje", 1.0
        return "sigue", 0.75

    def rebound(
        self, att_idx: int, depth: int = 0, from_corner: bool = False, zone: int = 3
    ) -> None:
        def_idx = 1 - att_idx
        self._sfx("balon", self.state.rng.uniform(-0.8, 0.8))
        if zone >= 3:
            self._speak(
                self.state.rng.choice(
                    [
                        "¡Rebote! El balón queda suelto en el área.",
                        "¡Rebote! Todos van por el balón dentro del área.",
                        "¡Balón dividido! Queda muerto en el área.",
                    ]
                )
            )
        else:
            self._speak("¡Rebote! El balón queda suelto en la frontal del área.")

        win_prob = 0.36 + (
            self.state.rating(att_idx, "att") - self.state.rating(def_idx, "dfn")
        ) / 100.0 * 0.5
        if depth >= 2 or not self.state.roll(win_prob):
            defender = self.state.pick_player(
                def_idx, {"DEF": 6.0, "MED": 1.3, "DEL": 0.3, "POR": 0.0}
            )
            phrase = self.state.rng.choice(
                [
                    "%s se anticipa y despeja el rebote.",
                    "%s llega primero y manda el balón lejos.",
                    "%s se tira al suelo y despeja el rebote.",
                ]
            )
            self._speak(phrase % defender.name)
            if self.state.can_chain_corner(att_idx, from_corner) and self.state.roll(0.20):
                self._speak("El despeje sale por la línea de fondo.")
                self.corner(att_idx, consecutive=from_corner)
            else:
                self.state.set_possession(def_idx, 1, carrier=defender)
            return

        shooter = self.state.pick_player(
            att_idx, {"DEL": 5.0, "MED": 2.2, "DEF": 0.8, "POR": 0.0}
        )
        if zone >= 3 and self.state.roll(0.10):
            self.shot(
                att_idx,
                3,
                mult=0.55,
                bicycle=True,
                rebound=True,
                depth=depth + 1,
                from_corner=from_corner,
            )
        else:
            self.shot(
                att_idx,
                zone,
                mult=0.85,
                rebound=True,
                depth=depth + 1,
                shooter=shooter,
                from_corner=from_corner,
            )

    # ------------------------------------------------------- Shots & Goals
    def olympic_goal(self, att_idx: int, taker: Player) -> str:
        def_idx = 1 - att_idx
        self.state.shots[att_idx] += 1
        self._speak(
            f"¡{taker.name} va a intentar el gol olímpico! Cobra el córner directo a la portería."
        )
        self._sfx("corner", self.state.rng.uniform(-0.8, 0.8))

        p = 0.03 * (taker.overall / 75.0) ** 2
        p *= 1 + (self.state.rating(att_idx, "att") - self.state.rating(def_idx, "dfn")) / 100.0
        p *= 1 - (self.state.rating(def_idx, "gk") - 70) / 100.0 * 1.2
        p *= self.state.goal_factor
        if self.state.roll(p):
            self.state.shots_on_target[att_idx] += 1
            self.score_goal(att_idx, taker, wonder_goal=True, goal_type="gol olímpico")
            self._announce_shots(att_idx)
            return "gol"

        roll = self.state.rng.random()
        if roll < 0.30:
            self.state.shots_on_target[att_idx] += 1
            self.state.shots_saved[att_idx] += 1
            self.state.saves[def_idx] += 1
            self._sfx("parada")
            self._speak("El portero se estira y ataja el balón con esfuerzo.")
            self._announce_shots(att_idx)
            if self.state.roll(0.20):
                self.rebound(att_idx, 1, False)
            else:
                self.state.set_possession(def_idx, 1)
        elif roll < 0.42:
            self.state.shots_post[att_idx] += 1
            self._sfx("poste")
            self._speak("¡Poste! El balón da en el poste, por centímetros.")
            self.state.add_highlight(
                f"Casi gol olímpico de {taker.name}, de {self.state.team_name(att_idx)}: el balón da en el poste."
            )
            self._announce_shots(att_idx)
            if self.state.roll(0.35):
                self.rebound(att_idx, 1, False)
            else:
                self.state.set_possession(def_idx, 1)
        elif roll < 0.60:
            self.state.shots_off_target[att_idx] += 1
            self._sfx("casi")
            self._speak("El balón se cuela rozando el travesaño y sale por encima.")
            self._announce_shots(att_idx)
            self.goal_kick(def_idx)
        else:
            self.state.shots_off_target[att_idx] += 1
            self._sfx("casi")
            self._speak("El balón se va directo por la línea de fondo.")
            self._announce_shots(att_idx)
            self.goal_kick(def_idx)
        return "fallo"

    def shot(
        self,
        att_idx: int,
        zone: int,
        mult: float = 1.0,
        header: bool = False,
        corner_ok: bool = True,
        free_kick: bool = False,
        rebound: bool = False,
        depth: int = 0,
        goal_type: str | None = None,
        bicycle: bool = False,
        shooter: Player | None = None,
        from_corner: bool = False,
    ) -> str:
        def_idx = 1 - att_idx
        gk_factor = 1.0
        if zone == 3 and not (header or free_kick or rebound or bicycle):
            shooter = shooter or self.state.pick_scorer(att_idx, header=False)
            ended, gk_factor = self.goalkeeper_duel(att_idx, shooter)
            if ended:
                return "fallo"

        taker = shooter or (
            self.state.pick_bicycle_taker(att_idx)
            if bicycle
            else self.state.pick_scorer(att_idx, header=header)
        )
        self.state.shots[att_idx] += 1
        base = {0: 0.004, 1: 0.012, 2: 0.070, 3: 0.26}[zone]

        # Meaningful individual finishing quality (non-linear: 90 OVR >> 70 OVR)
        eff_taker = self.state.effective_overall(taker)
        player_factor = max(0.62, min(1.55, (eff_taker / 74.0) ** 1.65))

        # Positional specialty bonus
        role = self.state.player_role(taker)
        if header:
            role_factor = 1.12 if role in ("DEF", "DEL") else 0.94
        elif zone >= 3:
            role_factor = {"DEL": 1.12, "MED": 1.00, "DEF": 0.84, "POR": 0.50}.get(role, 1.0)
        else:
            role_factor = {"MED": 1.10, "DEL": 1.04, "DEF": 0.85, "POR": 0.45}.get(role, 1.0)

        angle_factor = 1.0
        if not (header or free_kick or bicycle or rebound):
            angle_factor = 1.08 if self.state.lane == 0 else 0.90

        space_factor = 1.0
        if att_idx == 0 and self.state.space_bonus > 0:
            space_factor = 1.0 + self.state.space_bonus * 1.15
            self.state.space_bonus = 0.0

        # Real goalkeeper individual quality vs shot
        gk = self.state.goalkeeper(def_idx)
        gk_eff = (
            self.state.effective_overall(gk) + self.state.gk_penalty[def_idx]
            if gk is not None
            else 50.0 + self.state.gk_penalty[def_idx]
        )
        gk_resistance = max(0.55, min(1.38, 1.0 - (gk_eff - 74.0) / 68.0))

        team_edge = 1.0 + (
            self.state.rating(att_idx, "att") - self.state.rating(def_idx, "dfn")
        ) / 100.0 * 1.5

        # Emotional context: confidence sharpens finishing; anxiety/frustration causes rush
        mood = self.state.mood_state[att_idx]
        mood_mod = {
            "euforico": 1.07,
            "confiado": 1.04,
            "sereno": 1.00,
            "ansioso": 0.95,
            "frustrado": 0.93,
            "caliente": 0.94,
        }.get(mood, 1.0)
        variance_mod = self.state.rng.uniform(0.92, 1.09)

        p = (
            base
            * mult
            * player_factor
            * role_factor
            * angle_factor
            * space_factor
            * mood_mod
            * variance_mod
            * self.state.weather.shot_skid_mod
            * max(0.55, team_edge)
            * gk_resistance
            * self.state.goal_factor
            * gk_factor
        )

        sfx_kind = "chilena" if bicycle else ("cabezazo" if header else "balon")
        self._sfx(sfx_kind, self.state.stereo_pan(0.18))
        if bicycle:
            self._speak(f"¡{taker.name} se eleva de espaldas al arco e intenta una chilena!")
        elif rebound:
            phrase = self.state.rng.choice(
                [
                    "¡Contrarremate de %s!",
                    "%s aprovecha el rebote y dispara de nuevo.",
                ]
            )
            self._speak(phrase % taker.name)
        else:
            verb = "remata de cabeza" if header else "dispara"
            self._speak(f"{taker.name} {verb}.")

        if bicycle:
            resolved_type = "de chilena"
        elif goal_type:
            resolved_type = goal_type
        elif rebound:
            resolved_type = "de contrarremate"
        elif header:
            resolved_type = "de cabeza"
        else:
            resolved_type = None

        allow_corner = corner_ok and self.state.can_chain_corner(att_idx, from_corner)
        if self.state.roll(p):
            self.state.shots_on_target[att_idx] += 1
            self.state.drought_turns[att_idx] = 0
            wonder = bicycle or (
                (not header)
                and (
                    (zone <= 2 and self.state.roll(0.40))
                    or (zone == 3 and self.state.roll(0.10))
                )
            )
            self.score_goal(att_idx, taker, wonder_goal=wonder, goal_type=resolved_type)
            self._announce_shots(att_idx)
            return "gol"

        roll = self.state.rng.random()
        if roll < 0.38:
            self.state.shots_on_target[att_idx] += 1
            self.state.shots_saved[att_idx] += 1
            self.state.drought_turns[att_idx] = 0
            self.state.saves[def_idx] += 1
            self.state.shift_morale(def_idx, 0.8)
            self.state.shift_momentum(-1.4 if att_idx == 0 else 1.8)
            self._sfx("parada", self.state.stereo_pan(0.15))
            gk = self.state.goalkeeper(def_idx)
            self._speak(
                f"El portero {gk.name} ataja el disparo."
                if gk
                else "El portero ataja el disparo."
            )
            if zone >= 3:
                self.state.add_highlight(
                    f"Gran atajada del portero de {self.state.team_name(def_idx)} al remate de {taker.name}."
                )
            self._announce_shots(att_idx)
            spill_prob = (0.20 if header else 0.17) * self.state.weather.gk_spill_mod
            if zone >= 2 and depth < 2 and self.state.roll(spill_prob):
                self._speak("¡El portero no logra retener el balón!")
                if gk is not None and self.commentary is not None:
                    self.commentary.handling_error(gk)
                self.rebound(att_idx, depth, from_corner, min(zone, 3))
            elif self.state.roll(0.22) and allow_corner:
                self.corner(att_idx, consecutive=from_corner)
            else:
                self.state.set_possession(def_idx, 1)
        elif roll < 0.55:
            self.state.shots_post[att_idx] += 1
            self._sfx("poste", self.state.stereo_pan(0.15))
            self.state.shift_momentum(0.8 if att_idx == 0 else -0.8)
            self._speak("¡Poste!")
            self.state.add_highlight(
                f"Poste de {taker.name}, de {self.state.team_name(att_idx)}."
            )
            self._announce_shots(att_idx)
            if zone >= 2 and depth < 2 and self.state.roll(0.32):
                self._speak("¡El balón vuelve al área!")
                self.rebound(att_idx, depth, from_corner, min(zone, 3))
            elif self.state.roll(0.4) and allow_corner:
                self.corner(att_idx, consecutive=from_corner)
            else:
                self.state.set_possession(def_idx, 1)
        elif roll < 0.82:
            self.state.shots_off_target[att_idx] += 1
            self._sfx("casi")
            q = self.state.rng.random()
            if q < 0.45:
                self._speak("¡El balón sale por encima del travesaño!")
            elif q < 0.70:
                self._speak("El disparo sale rozando el poste, por fuera.")
                if zone >= 2:
                    self.state.add_highlight(
                        f"Por poco: el disparo de {taker.name}, de {self.state.team_name(att_idx)}, roza el poste."
                    )
            else:
                self._speak("El disparo se va fuera.")
            self._announce_shots(att_idx)
            if zone == 3 and self.commentary is not None:
                self.commentary.missed_chance(taker, high=q < 0.45, open_goal=gk is None)
            self.goal_kick(def_idx)
        else:
            self.state.shots_blocked[att_idx] += 1
            self.state.blocks[def_idx] += 1
            blocker = self.state.pick_player(
                def_idx, {"DEF": 5.0, "MED": 2.0, "DEL": 0.2, "POR": 0.0}
            )
            self._speak(f"{blocker.name} se cruza a tiempo y bloquea el disparo.")
            self._announce_shots(att_idx)
            if zone >= 1 and self.state.roll(0.04):
                self._sfx("silbato")
                self.foul(def_idx, zone, "mano")
            elif (
                zone >= 3
                and self.state.settings.var_enabled
                and self.state.roll(0.035)
            ):
                self.var.review_missed_handball(
                    att_idx,
                    self.penalty,
                    on_confirmed=self.commentary.missed_handball if self.commentary else None,
                )
            elif zone >= 2 and depth < 2 and self.state.roll(0.18):
                self._speak("El balón queda suelto tras el bloqueo.")
                self.rebound(att_idx, depth, from_corner, min(zone, 3))
            elif allow_corner:
                self.corner(att_idx, consecutive=from_corner)
            else:
                self.state.set_possession(def_idx, 1, carrier=blocker)
        return "fallo"

    def score_goal(
        self,
        team_idx: int,
        scorer: Player,
        wonder_goal: bool = False,
        goal_type: str | None = None,
    ) -> None:
        self.state.lost_seconds += 30
        self.state.goals[team_idx] += 1
        goal_count = self.state.goals[team_idx]
        scorer.goals += 1
        self.state.scorers.append((team_idx, scorer, self.state.minute()))
        self.state.note(scorer, 3)

        assistant: Player | None = None
        if goal_type in NO_ASSIST_GOAL_TYPES:
            self.state.last_pass = None
        else:
            assistant = self.state.pick_assistant(team_idx, scorer)
        self.state.last_assist = assistant
        if assistant is not None:
            assistant.assists += 1
            self.state.assist_log.append((team_idx, assistant, self.state.minute()))
            self.state.note(assistant, 2)
        assist_txt = f" Asistencia de {assistant.name}." if assistant is not None else ""

        last_flank = self.state.last_flank
        if team_idx == 1 and last_flank is not None and last_flank[1] == self.state.turn:
            self.state.flank_goals[last_flank[0]] += 1
            self.state.note(self.state.flank_defender(last_flank[0]), -2)

        suffix = f", {goal_type}" if goal_type else ""
        label = "Golazo" if wonder_goal else "Gol"
        self.state.add_highlight(
            f"{label} de {scorer.name}, de {self.state.team_name(team_idx)}{suffix}.{assist_txt} "
            f"{self.state.team_name(0)} {self.state.goals[0]}, "
            f"{self.state.team_name(1)} {self.state.goals[1]}."
        )
        if team_idx == 0:
            self._sfx("gol")
            self._crowd_react("ovacion", 1.1)
        else:
            self._crowd_react("abucheo", 1.1)
        if wonder_goal and goal_type == "gol olímpico":
            self._speak(
                f"¡Goooool! ¡GOL OLÍMPICO de {scorer.name}, de {self.state.team_name(team_idx)}! "
                f"El balón entra directo desde el saque de esquina. Minuto {self.state.minute()}."
            )
        elif wonder_goal:
            self._speak(
                f"¡Goooool! ¡Qué golazo de {scorer.name}, de {self.state.team_name(team_idx)}{suffix}! "
                f"Minuto {self.state.minute()}.{assist_txt}"
            )
        else:
            self._speak(
                f"¡Goooool! {scorer.name}, de {self.state.team_name(team_idx)}{suffix}. "
                f"Minuto {self.state.minute()}.{assist_txt}"
            )
        self._announce_scoreboard()
        self.state.shift_momentum(3.5 if team_idx == 0 else -3.5)
        self.state.set_possession(1 - team_idx, 1, lane=0)
        if (
            goal_type not in NO_VAR_GOAL_TYPES
            and self.state.settings.var_enabled
            and not self.state.suspended_match
            and self.state.roll(0.12)
        ):
            self.var.review_goal(team_idx, scorer, goal_type=goal_type)
        if self.commentary is not None:
            if self.state.goals[team_idx] == goal_count:
                self.commentary.goal(team_idx, scorer, goal_type, wonder_goal)
            else:
                self.commentary.overturned_goal()
        self._notify_stoppage("la reanudación tras el gol")

    # ------------------------------------------------------- Cross, Corner, Restarts
    def cross(
        self, att_idx: int, mult: float = 1.0, crosser: Player | None = None
    ) -> None:
        def_idx = 1 - att_idx
        side_name = {-1: "izquierda", 1: "derecha"}.get(self.state.lane)
        player = crosser or (
            self.state.flank_player(att_idx, side_name) if side_name else None
        ) or self.state.pick_player(
            att_idx, {"MED": 3.0, "DEL": 2.0, "DEF": 1.0, "POR": 0.0}
        )
        self.state.record_pass(att_idx, player)
        wing_bonus = 1.12 if self.state.lane != 0 else 0.94
        if side_name:
            wing_bonus += self.state.flank_edge(att_idx, side_name)
        if att_idx == 0 and self.state.space_bonus > 0:
            wing_bonus += self.state.space_bonus * 0.8
            self.state.space_bonus = 0.0
        self._sfx("balon", self.state.stereo_pan(0.10))
        self._speak(f"{player.name} manda un centro al área {self.state.lane_text()}.")
        outcome, factor = self.aerial_defense(att_idx, "Centro")
        if outcome != "sigue" or self.state.abandoned:
            return
        p = (
            (0.46 + (self.state.rating(att_idx, "att") - self.state.rating(def_idx, "dfn")) / 100.0 * 0.45)
            * wing_bonus
            * self.state.weather.cross_mod
        )
        if self.state.roll(p):
            self.state.lane = 0
            if self.state.roll(0.05):
                self.shot(att_idx, 3, mult=0.50 * mult, bicycle=True)
            else:
                self.shot(att_idx, 3, mult=0.54 * mult * factor, header=True)
        elif self.state.roll(0.28):
            self.corner(att_idx)
        else:
            self._speak("La defensa despeja el centro.")
            if att_idx == 1 and side_name:
                self.state.note(self.state.flank_defender(side_name), 1)
            self.state.set_possession(def_idx, 1)

    def corner(self, att_idx: int, consecutive: bool = False) -> None:
        if consecutive and self.state.corner_streak[0] == att_idx:
            self.state.corner_streak[1] += 1
        else:
            self.state.corner_streak = [att_idx, 1]
        count = self.state.corner_streak[1]
        self.state.corners[att_idx] += 1
        self._sfx("corner")
        if count == 1:
            self._speak(f"Saque de esquina para {self.state.team_name(att_idx)}.")
        else:
            ordinal = {2: "Segundo", 3: "Tercer", 4: "Cuarto"}.get(count, "Otro")
            self._speak(
                f"¡{ordinal} saque de esquina consecutivo para {self.state.team_name(att_idx)}!"
            )
            if count == 3:
                self.state.add_highlight(
                    f"Tres saques de esquina seguidos para {self.state.team_name(att_idx)}."
                )

        self._notify_stoppage("el tiro de esquina")

        taker, notice = self.state.designated_taker(att_idx, "corner")
        if notice:
            self._speak(notice)
        self._speak(f"Lo cobra {taker.name}.")
        if att_idx == 0:
            choice = self._choose(
                "¿Cómo sacas el córner?",
                [
                    "Centro al primer palo",
                    "Centro al segundo palo",
                    "Saque corto",
                    "Intentar el gol olímpico",
                ],
                [33, 42, 18, 7],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return
            if taker not in self.state.xi[0]:
                taker, _ = self.state.designated_taker(0, "corner")
        else:
            choice = self.state.rng.choice((0, 1, 1, 2))
            if self.state.roll(0.006):
                choice = 3

        if choice == 3:
            self.olympic_goal(att_idx, taker)
            return
        self.state.record_pass(att_idx, taker)
        if choice == 2:
            self._speak(
                f"Saque corto, {self.state.team_name(att_idx)} mantiene la posesión."
            )
            self.state.set_possession(att_idx, 2, carrier=taker)
            return

        self._sfx("balon")
        post = "primer" if choice == 0 else "segundo"
        self._speak(f"{taker.name} manda el centro al {post} palo.")
        outcome, factor = self.aerial_defense(att_idx, "Córner", from_corner=True)
        if outcome != "sigue" or self.state.abandoned:
            return
        if self.state.roll(0.06):
            self.shot(att_idx, 3, mult=0.50, bicycle=True, from_corner=True)
        else:
            mult = (0.66 if choice == 1 else 0.60) * factor
            self.shot(att_idx, 3, mult=mult, header=True, from_corner=True)

    def throw_in(self) -> None:
        team_idx = self.state.rng.choice((0, 1))
        side = self.state.rng.choice((-1, 1))
        zone = self.state.rng.choice((1, 1, 2))
        self._sfx("balon", side * 0.8)
        wing = "izquierda" if side < 0 else "derecha"
        self._speak(
            f"El balón sale por la banda {wing}. Saque de banda para "
            f"{self.state.team_name(team_idx)}."
        )
        self._notify_stoppage("el saque de banda")
        taker = self.state.pick_player(
            team_idx, {"DEF": 3.0, "MED": 3.0, "DEL": 1.0, "POR": 0.0}
        )
        self._speak(f"Lo saca {taker.name}.")
        self.state.set_possession(team_idx, zone, lane=side, carrier=taker)
        if team_idx == 0:
            choice = self._choose(
                "¿Cómo sacas de banda?",
                [
                    "Saque corto al compañero más cercano",
                    "Saque largo hacia adelante",
                ],
                [70, 30],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return
            if taker not in self.state.xi[0]:
                taker = self.state.pick_player(
                    0, {"DEF": 3.0, "MED": 3.0, "DEL": 1.0, "POR": 0.0}
                )
            if choice == 0:
                rec = self.state.pick_receiver(0, "corto", exclude=taker)
                self.state.ball_carrier = rec
                self._sfx("balon")
                self._speak(f"Saque corto para {rec.name}, mantienes la posesión.")
            elif self.state.roll(0.45):
                self.state.zone = min(3, zone + 1)
                rec = self.state.pick_receiver(0, "corto", exclude=taker)
                self.state.ball_carrier = rec
                self._sfx("balon")
                self._speak(
                    f"El saque largo llega a {rec.name}. Ahora {ZONES_OWN[self.state.zone]}."
                )
            else:
                self._sfx("balon")
                self._speak("El rival despeja el saque largo.")
                self.state.set_possession(1, 1)
        else:
            self._speak(
                f"Saque corto y {self.state.team_name(1)} conserva el balón."
            )

    def goal_kick(self, team_idx: int) -> None:
        self._sfx("balon")
        self._speak(f"Saque de meta para {self.state.team_name(team_idx)}.")
        self._notify_stoppage("el saque de meta")
        gk = self.state.goalkeeper(team_idx)
        who = gk.name if gk else "el portero"
        if team_idx == 0:
            choice = self._choose(
                "¿Cómo sacas de meta?",
                ["Salida corta jugando desde atrás", "Saque largo al delantero"],
                [65, 35],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                self.state.set_possession(0, 1)
                return
            gk = self.state.goalkeeper(0)
            who = gk.name if gk else "el portero"
            if choice == 0:
                self.state.set_possession(0, 0, carrier=gk)
                rec = self.state.pick_player(
                    0, {"DEF": 5.0, "MED": 2.0, "DEL": 0.2, "POR": 0.0}, exclude=gk
                )
                self._speak(
                    f"{who} saca de meta en corto para {rec.name}, {ZONES_OWN[0]}."
                )
                self.state.zone = 0
                self.state.ball_carrier = rec
            elif self.state.roll(0.5):
                self.state.set_possession(0, 2)
                rec = self.state.pick_receiver(0, "filtrado", exclude=gk)
                self.state.ball_carrier = rec
                self._speak(
                    f"{who} saca largo y {rec.name} controla el balón en campo rival."
                )
            else:
                self._speak(
                    f"{who} saca largo, pero la defensa rival gana el balón."
                )
                self.state.set_possession(1, 1)
        else:
            self.state.set_possession(1, 1)
            name = self.state.team_name(1)
            self._speak(f"{name} saca de meta y {name} se queda con el balón.")

    # ------------------------------------------------------- Free Kicks & Penalties
    def free_kick(self, att_idx: int) -> None:
        def_idx = 1 - att_idx
        taker, notice = self.state.designated_taker(att_idx, "libre")
        if notice:
            self._speak(notice)
        self._speak(
            f"Tiro libre peligroso para {self.state.team_name(att_idx)}. Lo cobra {taker.name}."
        )
        dist = self.state.rng.randint(1, 14)
        side = self.state.rng.choice(
            ("por el centro", "ligeramente a la izquierda", "ligeramente a la derecha")
        )
        plural = "" if dist == 1 else "s"
        self._speak(
            f"La falta es a {dist} metro{plural} fuera del área, {side}, "
            f"a unos {dist + 16} metros del arco."
        )
        if att_idx == 1:
            self._crowd_react("abucheo", 1.5)
            wall_size = 3 + self._choose(
                "Tiro libre del rival. ¿Cuántos jugadores pones en la barrera?",
                ["Tres jugadores", "Cuatro jugadores", "Cinco jugadores"],
                [25, 50, 25],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return
        else:
            wall_size = self.state.rng.choices((3, 4, 5), weights=[25, 50, 25])[0]

        wall_label = {3: "Tres", 4: "Cuatro", 5: "Cinco"}[wall_size]
        self._speak(
            f"El árbitro marca los nueve metros. {wall_label} jugadores de "
            f"{self.state.team_name(def_idx)} se acomodan en la barrera."
        )
        if self.state.roll(0.20):
            self._speak(
                "La barrera avanza unos pasos y el árbitro la hace retroceder."
            )

        if att_idx == 0:
            choice = self._choose(
                "¿Qué haces con el tiro libre?",
                [
                    "Disparo por encima de la barrera",
                    "Disparo rasante por un costado",
                    "Centro al área",
                    "Pase corto",
                ],
                [16, 9, 45, 30],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return
            if taker not in self.state.xi[0]:
                taker, _ = self.state.designated_taker(0, "libre")
        else:
            choice = self.state.rng.choices((0, 1, 2, 3), weights=[16, 9, 45, 30])[0]

        if choice in (0, 1):
            self._direct_free_kick(att_idx, taker, choice, wall_size, dist)
        elif choice == 2:
            self.cross(att_idx, crosser=taker)
        else:
            rec = self.state.pick_receiver(att_idx, "corto", exclude=taker)
            self.state.record_pass(att_idx, taker)
            self._speak("Pase corto, se mantiene la posesión.")
            self.state.set_possession(att_idx, 2, carrier=rec)

    def _direct_free_kick(
        self, att_idx: int, taker: Player, style: int, wall_size: int, dist: int = 8
    ) -> None:
        def_idx = 1 - att_idx
        self._sfx("silbato")
        self._sfx("balon", self.state.rng.uniform(-0.8, 0.8))
        if style == 0:
            self._speak(f"{taker.name} levanta el balón por encima de la barrera.")
            block_prob = 0.05 + 0.035 * wall_size
        else:
            self._speak(
                f"{taker.name} dispara rasante, buscando el hueco junto a la barrera."
            )
            block_prob = 0.10 + 0.05 * wall_size

        if self.state.roll(block_prob):
            self.state.shots[att_idx] += 1
            self.state.shots_blocked[att_idx] += 1
            self.state.blocks[def_idx] += 1
            self._sfx("barrera")
            self._speak("¡El balón da en la barrera!")
            self._announce_shots(att_idx)
            if self.state.roll(0.35):
                self.rebound(att_idx, 1, False, 2)
            elif self.state.roll(0.22) and self.state.can_chain_corner(att_idx, False):
                self.corner(att_idx)
            else:
                self.state.set_possession(def_idx, 1)
            return

        mult = (
            1.4
            * {3: 1.08, 4: 1.0, 5: 0.93}[wall_size]
            * (1.12 if style == 0 else 0.92)
        )
        mult *= 1.12 if dist <= 4 else (0.88 if dist >= 10 else 1.0)
        self.shot(
            att_idx,
            2,
            mult=mult,
            free_kick=True,
            shooter=taker,
            goal_type="de tiro libre",
        )

    def penalty(self, att_idx: int) -> None:
        self._sfx("penal")
        self.state.lost_seconds += 40
        if att_idx == 1:
            self._crowd_react("abucheo", 2.0)
        self._notify_stoppage("el penal")
        taker, notice = self.state.designated_taker(att_idx, "penal")
        if notice:
            self._speak(notice)
        self._speak(
            f"¡Penal para {self.state.team_name(att_idx)}! Va a lanzar {taker.name}."
        )
        outcome = self.take_penalty_kick(att_idx, taker)
        if not self.state.abandoned:
            self.state.shots[att_idx] += 1
            if outcome == "gol":
                self.state.shots_on_target[att_idx] += 1
            elif outcome == "parada":
                self.state.shots_on_target[att_idx] += 1
                self.state.shots_saved[att_idx] += 1
                self.state.saves[1 - att_idx] += 1
            elif outcome == "poste":
                self.state.shots_post[att_idx] += 1
            else:
                self.state.shots_off_target[att_idx] += 1
        if outcome == "gol":
            self.score_goal(att_idx, taker, goal_type="de penal")
        else:
            reason = {
                "parada": "lo detiene el portero",
                "poste": "da en el poste",
            }.get(outcome, "se va fuera")
            self.state.add_highlight(
                f"Penal fallado por {taker.name}, de {self.state.team_name(att_idx)}: {reason}."
            )
            self.state.set_possession(1 - att_idx, 1)

    @staticmethod
    def preferred_side(player: Player) -> int:
        """Deterministic preferred penalty direction (-1 left, +1 right)."""
        return -1 if stable_hash(player.name) % 2 == 0 else 1

    def take_penalty_kick(self, att_idx: int, taker: Player | None = None) -> str:
        pref = self.preferred_side(taker) if taker is not None else 0
        if att_idx == 0:
            choice = self._choose(
                "¿Hacia dónde tiras? Izquierda y derecha son las de tus altavoces",
                ["A la izquierda", "Al centro", "A la derecha"],
                [44, 12, 44],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return "fuera"
            shot_dir = choice - 1
            dive_dir = self.state.rng.choices((-1, 0, 1), weights=[44, 12, 44])[0]
        else:
            if taker is not None and not self.state.auto:
                self._speak(
                    f"Informe del entrenador de porteros: {taker.name} suele tirar "
                    f"{PENALTY_DIRECTIONS[pref + 1]}."
                )
            choice = self._choose(
                "Eres el portero. ¿Hacia dónde te lanzas?",
                ["A la izquierda", "Te quedas en el centro", "A la derecha"],
                [44, 12, 44],
                None,
                dead_ball=True,
            )
            if self.state.abandoned:
                return "fuera"
            dive_dir = choice - 1
            if taker is not None:
                shot_dir = (
                    pref
                    if self.state.roll(0.55)
                    else self.state.rng.choice([d for d in (-1, 0, 1) if d != pref])
                )
            else:
                shot_dir = self.state.rng.choices((-1, 0, 1), weights=[44, 12, 44])[0]

        self._sfx("silbato")
        self._sfx("balon", shot_dir * 0.9)
        def_idx = 1 - att_idx
        miss = 0.06
        if taker is not None:
            miss += max(0.0, 72 - taker.overall) / 100.0 * 0.18
            if self.state.player_role(taker) == "POR":
                miss += 0.05
        if self.state.roll(miss):
            if self.state.roll(0.35):
                self._sfx("poste")
                self._speak("¡El balón da en el poste!")
                if taker is not None and self.commentary is not None:
                    self.commentary.penalty_miss(taker, "poste")
                return "poste"
            self._sfx("casi")
            self._speak("El penal se va fuera.")
            if taker is not None and self.commentary is not None:
                self.commentary.penalty_miss(taker, "fuera")
            return "fuera"
        if dive_dir == shot_dir and self.state.roll(
            0.60 + (self.state.rating(def_idx, "gk") - 70) / 100.0 * 0.4
        ):
            self._sfx("parada")
            self._speak(
                f"¡El portero adivina y detiene el penal {PENALTY_DIRECTIONS[shot_dir + 1]}!"
            )
            if taker is not None and self.commentary is not None:
                self.commentary.penalty_miss(taker, "parada")
            return "parada"
        return "gol"

    # ------------------------------------------------------- One-by-One Shootout
    def _shooter_text(self, player: Player) -> str:
        return f"{player.name}, {self.state.slot_text(player)}, calidad {player.overall}"

    def _trim_shootout_squad(
        self, idx: int, eligible: list[list[Player]], excess: int, human: bool
    ) -> None:
        team = self.state.team_name(idx)
        plural = "" if excess == 1 else "es"
        self._speak(
            f"{team} terminó el partido con más jugadores que su rival. Para la tanda, "
            f"{excess} jugador{plural} de {team} no lanza{'' if excess == 1 else 'n'}, "
            "para igualar el número."
        )
        for _ in range(excess):
            if idx == 0 and human and not self.state.abandoned:
                k = self._choose(
                    f"Debes dejar fuera de la tanda a {excess} jugador{plural} más. "
                    "¿A quién dejas fuera?",
                    [self._shooter_text(p) for p in eligible[0]],
                    None,
                    None,
                    dead_ball=True,
                )
                left_out = eligible[0].pop(k)
            else:
                pool = [p for p in eligible[idx] if self.state.player_role(p) != "POR"] or list(
                    eligible[idx]
                )
                left_out = min(pool, key=lambda p: p.overall)
                eligible[idx].remove(left_out)
            self._speak(f"{left_out.name} no lanzará en la tanda.")
            excess -= 1
            plural = "" if excess == 1 else "es"

    def penalty_shootout(self) -> None:
        """Run a one-by-one shootout where no player repeats until every eligible teammate kicks."""
        self.state.pending_substitution = False
        self.state.in_penalty_shootout = True
        try:
            self._speak("Se decide en la tanda de penales.")
            self._sfx("penal")
            if not self.state.muted:
                self.io.play_theme("musica_penales", loop=True, volume=0.4)
            human = not self.state.auto and not self.state.abandoned

            eligible = [list(self.state.xi[0]), list(self.state.xi[1])]
            size = min(len(eligible[0]), len(eligible[1]))
            for idx in (0, 1):
                if len(eligible[idx]) > size:
                    self._trim_shootout_squad(idx, eligible, len(eligible[idx]) - size, human)

            self.state.shootout_lines = []
            score = [0, 0]
            taken = [0, 0]
            pending = [list(eligible[0]), list(eligible[1])]

            def best_five(idx: int) -> list[Player]:
                field = sorted(
                    (p for p in eligible[idx] if self.state.player_role(p) != "POR"),
                    key=lambda p: -(p.overall + self.state.rng.random() * 4),
                )
                keepers = [p for p in eligible[idx] if self.state.player_role(p) == "POR"]
                return field + keepers

            assigned = [best_five(0)[:5], best_five(1)[:5]]

            first = self.state.rng.choice((0, 1))
            self._speak(
                f"El árbitro lanza la moneda. Empieza lanzando {self.state.team_name(first)}."
            )
            self._speak(
                "Regla uno a uno: cada jugador lanza una sola vez, y nadie repite "
                "hasta que hayan lanzado todos los demás."
            )
            if human:
                k = self._choose(
                    "Tanda de penales. ¿Cómo eliges a tus primeros cinco lanzadores?",
                    [
                        "Que el juego elija a mis cinco mejores lanzadores",
                        "Elegirlos yo, uno por uno",
                    ],
                    None,
                    None,
                    dead_ball=True,
                )
                if k == 1 and not self.state.abandoned:
                    free = list(eligible[0])
                    chosen: list[Player] = []
                    while len(chosen) < min(5, len(eligible[0])):
                        cands = sorted(free, key=lambda p: -p.overall)
                        r = self._choose(
                            f"Lanzador número {len(chosen) + 1} de 5. Elige a quién lanza",
                            [self._shooter_text(p) for p in cands],
                            None,
                            None,
                            dead_ball=True,
                        )
                        pick = cands[r]
                        chosen.append(pick)
                        free.remove(pick)
                    assigned[0] = chosen
                    self._speak("Orden de lanzadores: " + ", ".join(p.name for p in chosen) + ".")
                else:
                    self._speak(
                        "Tus lanzadores serán: " + ", ".join(p.name for p in assigned[0]) + "."
                    )

            def next_shooter(idx: int) -> Player:
                number = taken[idx] + 1
                if number <= 5 and number <= len(assigned[idx]):
                    shooter = assigned[idx][number - 1]
                    if shooter in pending[idx]:
                        pending[idx].remove(shooter)
                    return shooter
                if not pending[idx]:
                    pending[idx] = list(eligible[idx])
                    self._speak(
                        f"Ya lanzaron todos los jugadores de {self.state.team_name(idx)}. "
                        "Empieza un nuevo ciclo uno a uno."
                    )
                if idx == 0 and human and not self.state.abandoned:
                    cands = sorted(pending[0], key=lambda p: -p.overall)
                    k = self._choose(
                        f"Muerte súbita. Penal número {number} de tu equipo. "
                        "Estos jugadores aún no han lanzado",
                        ["Al azar entre los que aún no han lanzado"]
                        + [self._shooter_text(p) for p in cands],
                        None,
                        None,
                        dead_ball=True,
                    )
                    shooter = self.state.rng.choice(cands) if k == 0 else cands[k - 1]
                else:
                    shooter = self.state.rng.choice(pending[idx])
                pending[idx].remove(shooter)
                return shooter

            round_num = 0
            decided = False
            while not decided and not self.state.abandoned:
                if round_num == 5:
                    self._speak(
                        "Siguen igualados. Empieza la muerte súbita: si un equipo marca y el "
                        "otro falla en la misma ronda, se acaba."
                    )
                for idx in (first, 1 - first):
                    shooter = next_shooter(idx)
                    self._speak(
                        f"Penal número {taken[idx] + 1} de {self.state.team_name(idx)}. "
                        f"Lanza {shooter.name}, {self.state.slot_text(shooter)}."
                    )
                    outcome = self.take_penalty_kick(idx, shooter)
                    if self.state.abandoned:
                        break
                    taken[idx] += 1
                    if outcome == "gol":
                        score[idx] += 1
                        self._sfx("gol")
                        self._speak(
                            f"¡Gol! {self.state.team_name(0)} {score[0]}, "
                            f"{self.state.team_name(1)} {score[1]}."
                        )
                        self.state.shootout_lines.append(
                            f"{shooter.name}, de {self.state.team_name(idx)}: gol."
                        )
                    else:
                        why = {"parada": "lo ataja el portero", "poste": "da en el poste"}.get(
                            outcome, "se va fuera"
                        )
                        self._speak(
                            f"Penal fallado. {self.state.team_name(0)} {score[0]}, "
                            f"{self.state.team_name(1)} {score[1]}."
                        )
                        self.state.shootout_lines.append(
                            f"{shooter.name}, de {self.state.team_name(idx)}: fallado, {why}."
                        )
                    rem0, rem1 = max(0, 5 - taken[0]), max(0, 5 - taken[1])
                    if min(taken) < 5 or max(taken) <= 5:
                        if score[0] > score[1] + rem1 or score[1] > score[0] + rem0:
                            decided = True
                    elif taken[0] == taken[1] and score[0] != score[1]:
                        decided = True
                    if decided:
                        break
                round_num += 1

            if not self.state.muted:
                self.io.stop_music(800)
            self.state.penalties = (score[0], score[1])
            self.state.shootout_lines.append(
                f"Tanda: {self.state.team_name(0)} {score[0]}, {self.state.team_name(1)} {score[1]}."
            )
        finally:
            self.state.in_penalty_shootout = False

    # ------------------------------------------------------- Fouls & Cards
    def foul(self, offender_team: int, zone_receiver: int, foul_type: str = "normal") -> None:
        receiver_team = 1 - offender_team
        self.state.fouls[offender_team] += 1
        heat_gain = {"normal": 7.5, "mano": 4.0, "tactica": 11.0, "barrida": 13.5}.get(
            foul_type, 7.5
        )
        self.state.add_tension(heat_gain)
        self.state.shift_morale(receiver_team, -0.4)
        offender = self.state.pick_player(
            offender_team, {"DEF": 3.0, "MED": 2.5, "DEL": 1.0, "POR": 0.02}
        )
        victim = self.state.pick_player(
            receiver_team, {"DEL": 3.2, "MED": 3.2, "DEF": 1.4, "POR": 0.0}
        )
        self._sfx("falta")
        self.state.lost_seconds += 5
        if offender_team == 0:
            self._crowd_react("abucheo", 1.8)
        else:
            self._crowd_react("ovacion", 1.5)

        offender_club = self.state.team_name(offender_team)
        aggr = self.state.aggression_level()
        hard_contact = foul_type == "barrida"
        if foul_type == "mano":
            phrase = self.state.rng.choice(
                [
                    "¡Mano de %s, de %s! El balón le golpea en el brazo y el árbitro lo sanciona.",
                    "El árbitro señala mano de %s, de %s. Tenía el brazo separado del cuerpo.",
                    "¡Mano de %s, de %s! Corta la jugada con el brazo y es falta.",
                ]
            )
            self._speak(phrase % (offender.name, offender_club))
        elif foul_type == "barrida":
            if aggr >= 0.55:
                self._speak(
                    f"¡Entrada durísima a ras de piso de {offender.name}, de {offender_club}, sobre {victim.name}! Falta."
                )
            else:
                self._speak(f"¡Barrida de {offender.name}, de {offender_club}, y llega tarde! Falta.")
        elif foul_type == "tactica":
            self._speak(f"{offender.name}, de {offender_club}, corta la jugada con una falta táctica.")
        elif aggr >= 0.50 and self.state.roll(0.55):
            hard_contact = True
            hard_phrase = self.state.rng.choice(
                [
                    "¡Entrada muy fuerte de %s, de %s! El partido se pone áspero.",
                    "¡Falta dura de %s, de %s! Va con demasiada vehemencia a la disputa.",
                    "¡Infracción agresiva de %s, de %s! El árbitro pita de inmediato.",
                ]
            )
            self._speak(hard_phrase % (offender.name, offender_club))
        else:
            self._speak(f"Falta de {offender.name}, de {offender_club}.")

        prob_y, prob_r = {
            "normal": (0.28, 0.005),
            "barrida": (0.36, 0.05),
            "tactica": (0.62, 0.015),
            "mano": (0.30, 0.01),
        }[foul_type]
        if zone_receiver >= 3:
            prob_y, prob_r = prob_y + 0.12, prob_r + 0.03
        if foul_type != "mano" and aggr >= 0.35:
            prob_y = min(0.82, prob_y + aggr * 0.22)
            prob_r = min(0.14, prob_r + max(0.0, aggr - 0.35) * 0.055)

        roll = self.state.rng.random()
        card = None
        if roll < prob_r:
            card = self.var.review_red_card(offender_team, offender)
        elif roll < prob_r + prob_y:
            card = "amarilla"
        if card:
            self.give_card(offender_team, offender, card)
        if hard_contact and self.commentary is not None:
            if card:
                self.commentary.card(offender, yellow=card == "amarilla")
            else:
                self.commentary.uncarded_contact()

        # When match is heated, players can square up / push each other after a foul
        if (
            not self.state.suspended_match
            and foul_type != "mano"
            and aggr >= 0.55
            and self.state.roll(0.24)
        ):
            self._speak(
                f"¡{victim.name} y {offender.name} se encaran tras la entrada! "
                "Llegan varios jugadores a empujarse y el árbitro interviene para calmar los ánimos."
            )
            self.state.lost_seconds += 15
            if (
                aggr >= 0.75
                and self.state.match_yellows.get(id(victim), 0) == 0
                and self.state.roll(0.16)
            ):
                self.give_card(receiver_team, victim, "amarilla", "por protestar y empujar")

        self.state.set_possession(receiver_team, zone_receiver)
        if self.state.suspended_match:
            return
        self._notify_stoppage("la falta")
        if zone_receiver >= 3:
            self.var.review_penalty(offender_team, receiver_team, self.free_kick, self.penalty)
        elif zone_receiver == 2:
            self.free_kick(receiver_team)
        else:
            self._speak(f"Saque de falta para {self.state.team_name(receiver_team)}.")

    def give_card(
        self,
        team_idx: int,
        player: Player,
        level: str,
        reason: str | None = None,
    ) -> None:
        self._sfx("tarjeta" if level == "amarilla" else "tarjeta_roja")
        self.state.lost_seconds += 20
        self.state.add_tension(6.0 if level == "amarilla" else 14.0)
        self.state.shift_morale(team_idx, -0.6 if level == "amarilla" else -2.2)
        club = self.state.team_name(team_idx)
        suffix = f" {reason}" if reason else ""
        if level == "amarilla":
            self.state.yellow_cards[team_idx] += 1
            count = self.state.match_yellows.get(id(player), 0) + 1
            self.state.match_yellows[id(player)] = count
            if count >= 2:
                self.state.fair_play[team_idx] += 2
                self.state.cards_log.append(
                    (team_idx, player.name, "segunda amarilla", self.state.minute())
                )
                self.state.add_highlight(
                    f"Expulsado {player.name}, de {club}, por doble amarilla."
                )
                self._speak(
                    f"Segunda amarilla para {player.name}, de {club}{suffix}. ¡Es expulsado!"
                )
                self._send_off(team_idx, player)
                return

            self.state.fair_play[team_idx] += 1
            self.state.cards_log.append(
                (team_idx, player.name, "amarilla" + suffix, self.state.minute())
            )
            self.state.add_highlight(
                f"Tarjeta amarilla para {player.name}, de {club}{suffix}."
            )
            self._speak(f"Tarjeta amarilla para {player.name}, de {club}{suffix}.")
            player.yellow_cards += 1
            if player.yellow_cards >= self.state.yellow_card_limit:
                player.yellow_cards = 0
                player.suspended_matches += 1
                limit = "dos" if self.state.yellow_card_limit == 2 else "tres"
                self._speak(f"Acumula {limit} amarillas y se perderá el próximo partido.")
        else:
            self.state.fair_play[team_idx] += 4
            self.state.cards_log.append(
                (team_idx, player.name, "roja", self.state.minute())
            )
            self.state.add_highlight(
                f"Tarjeta roja directa para {player.name}, de {club}."
            )
            self._speak(f"¡Tarjeta roja directa para {player.name}, de {club}!")
            self._send_off(team_idx, player)

    def _send_off(self, team_idx: int, player: Player) -> None:
        self._sfx("abucheo" if team_idx == 1 else "casi")
        was_gk = self.state.player_role(player) == "POR" or player.position == "POR"
        player.suspended_matches = max(player.suspended_matches, 1)
        self.state.subbed_off[team_idx].add(id(player))
        self.state.position_overrides.pop(id(player), None)
        self.state.slot.pop(id(player), None)
        self.state.fit.pop(id(player), None)
        if player in self.state.xi[team_idx]:
            self.state.xi[team_idx].remove(player)
        self.state.sync_board_slots(team_idx)
        if self.state.ball_carrier is player:
            self.state.ball_carrier = None
        self.state.red_cards[team_idx] += 1
        self.state.ratings[team_idx] = self.state.compute_ratings(team_idx)
        remaining = len(self.state.xi[team_idx])
        self._speak(
            f"{self.state.team_name(team_idx)} se queda con {remaining} jugadores."
        )
        if remaining < 7 and not self.state.suspended_match:
            self.state.suspended_match = True
            winner = 1 - team_idx
            self.state.goals[winner] = max(
                self.state.goals[winner], self.state.goals[team_idx] + 3
            )
            self._sfx("silbato")
            self._speak(
                f"{self.state.team_name(team_idx)} tiene menos de siete jugadores. "
                f"El árbitro suspende el partido y da la victoria a {self.state.team_name(winner)}."
            )
            return
        if was_gk and self.state.goalkeeper(team_idx) is None:
            if self.on_goalkeeper_sent_off is not None:
                self.on_goalkeeper_sent_off(team_idx)
            else:
                self.state.gk_penalty[team_idx] = -25
                self.state.ratings[team_idx] = self.state.compute_ratings(team_idx)
                self._speak(
                    "El portero se va expulsado, un jugador de campo se pone los guantes."
                )
