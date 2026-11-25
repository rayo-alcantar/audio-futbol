"""VAR (Video Assistant Referee) review subsystem."""

from __future__ import annotations

from typing import Callable

from audiofutbol.domain.match.ports import MatchIO
from audiofutbol.domain.match.state import MatchState
from audiofutbol.domain.models import Player


class VarSystem:
    """Handles VAR checks for goals, red cards, penalties, and missed handballs."""

    def __init__(
        self,
        state: MatchState,
        io: MatchIO,
        crowd_react: Callable[[str, float], None],
    ) -> None:
        self.state = state
        self.io = io
        self._crowd_react = crowd_react

    def _speak(self, text: str) -> None:
        if not self.state.muted:
            self.io.speak(text)

    def _sfx(self, event: str) -> None:
        if not self.state.muted:
            self.io.play_sfx(event)

    def _begin_review(self, subject: str) -> None:
        self._sfx("var")
        self.state.lost_seconds += 75
        self._speak(
            f"¡Atención! El árbitro se lleva la mano al oído: el VAR revisa {subject}."
        )
        if not self.state.muted:
            self.io.pause(1800)
        self._speak("Revisión en curso.")
        if not self.state.muted:
            self.io.pause(1500)

    def _finish_review(self, text: str, overturned: bool = False) -> None:
        self._sfx("var_anulado" if overturned else "var_confirmado")
        self.state.var_log.append((self.state.minute(), text))
        self.state.add_highlight(f"VAR: {text}")
        self._speak(text)

    def review_goal(
        self, team_idx: int, scorer: Player, goal_type: str | None = None
    ) -> None:
        self._begin_review(
            f"el gol de {scorer.name}, de {self.state.team_name(team_idx)}"
        )
        if self.state.roll(0.30):
            if goal_type in ("de tiro libre", "gol olímpico", "de penal"):
                reason = "una falta en el área sobre la defensa"
            else:
                reason = self.state.rng.choices(
                    [
                        "fuera de juego",
                        "una falta previa sobre un defensa",
                        "una mano previa de un atacante",
                    ],
                    [55, 25, 20],
                )[0]
            self.state.goals[team_idx] -= 1
            scorer.goals -= 1
            if self.state.scorers and self.state.scorers[-1][1] is scorer:
                self.state.scorers.pop()
            assist = self.state.last_assist
            if (
                assist is not None
                and self.state.assist_log
                and self.state.assist_log[-1][1] is assist
            ):
                assist.assists = max(0, assist.assists - 1)
                self.state.assist_log.pop()
            self.state.last_assist = None
            if team_idx == 1 and self.state.last_flank is not None:
                side = self.state.last_flank[0]
                self.state.flank_goals[side] = max(0, self.state.flank_goals[side] - 1)
            if self.state.highlights:
                self.state.highlights.pop()
            self._finish_review(
                f"Gol anulado por el VAR por {reason}. Se queda en "
                f"{self.state.team_name(0)} {self.state.goals[0]}, "
                f"{self.state.team_name(1)} {self.state.goals[1]}.",
                overturned=True,
            )
            self._crowd_react("abucheo" if team_idx == 0 else "ovacion", 1.8)
            self.io.update_hud(self.state.hud_status())
        else:
            self._finish_review(
                f"El VAR confirma el gol de {scorer.name}, de "
                f"{self.state.team_name(team_idx)}. El gol es válido."
            )
        self.state.set_possession(1 - team_idx, 1, lane=0)

    def review_red_card(self, offender_team: int, player: Player) -> str:
        if not self.state.settings.var_enabled or not self.state.roll(0.35):
            return "roja"
        self._begin_review(
            f"la tarjeta roja a {player.name}, de {self.state.team_name(offender_team)}"
        )
        if self.state.roll(0.30):
            self._finish_review(
                "El árbitro revisa la jugada en el monitor y rebaja la roja a tarjeta amarilla."
            )
            return "amarilla"
        self._finish_review(
            "El árbitro revisa la jugada en el monitor y confirma la tarjeta roja."
        )
        return "roja"

    def review_penalty(
        self,
        offender_team: int,
        taker_team: int,
        on_free_kick: Callable[[int], None],
        on_penalty: Callable[[int], None],
    ) -> None:
        if self.state.settings.var_enabled and self.state.roll(0.20):
            self._begin_review(
                f"el penal señalado contra {self.state.team_name(offender_team)}"
            )
            if self.state.roll(0.40):
                if self.state.roll(0.60):
                    self._finish_review(
                        "Penal anulado por el VAR: la falta fue fuera del área. "
                        f"Tiro libre peligroso para {self.state.team_name(taker_team)}."
                    )
                    on_free_kick(taker_team)
                else:
                    self._finish_review(
                        "Penal anulado por el VAR: no hubo contacto. "
                        f"Se reanuda con balón a tierra para {self.state.team_name(offender_team)}."
                    )
                    self.state.set_possession(offender_team, 1)
                return
            self._finish_review("El VAR confirma el penal.")
        on_penalty(taker_team)

    def review_missed_handball(
        self,
        attacking_team: int,
        on_penalty: Callable[[int], None],
        on_confirmed: Callable[[], None] | None = None,
    ) -> None:
        defending_team = 1 - attacking_team
        self._begin_review(
            f"una posible mano dentro del área de {self.state.team_name(defending_team)}"
        )
        if self.state.roll(0.70):
            self.state.set_possession(attacking_team, 3)
            self._finish_review(
                f"El VAR detecta mano en el área. ¡Penal para {self.state.team_name(attacking_team)}!"
            )
            if on_confirmed is not None:
                on_confirmed()
            on_penalty(attacking_team)
        else:
            self._finish_review("El VAR no encuentra infracción. Sigue el juego.")
            self.state.set_possession(defending_team, 1)
