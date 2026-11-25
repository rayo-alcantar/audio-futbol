"""Situation-based color commentary. Its randomness never affects the match."""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from string import Formatter
from typing import Callable

from audiofutbol.domain.match.commentary_lines import COMMENTARY_LINES
from audiofutbol.domain.match.state import MatchState
from audiofutbol.domain.models import Player

Section = str | tuple[str, tuple[int, ...]]

# Lines that explicitly mention points, rather than just describing the result.
_POINTS_LINES = {
    ("1.2", 0), ("3.1", 0), ("3.2", 0), ("3.3", 0), ("3.3", 2),
    ("4.1", 3), ("7.1", 4), ("9.1", 1),
}
_FORMATTER = Formatter()


@dataclass(frozen=True)
class CommentaryContext:
    """Verified fixture facts; missing detail never becomes an invented name."""

    home_index: int | None = 0
    stadium: str = ""
    city: str = ""
    for_points: bool = False
    home_leading: bool = False
    home_unbeaten: bool = False
    home_winning: bool = False


class MatchCommentary:
    """Select nonrepeating lines at match phases and occasional live incidents."""

    def __init__(
        self,
        state: MatchState,
        speak: Callable[[str], None],
        context: CommentaryContext | None,
        rng: random.Random | None = None,
    ) -> None:
        self.state = state
        self.speak = speak
        self.context = context
        self.rng = rng if rng is not None else random.Random()
        self.used: set[tuple[str, int]] = set()
        self.last_live_minute = -8
        self.late_events: set[str] = set()
        self.clear_misses: set[int] = set()
        self.turnovers: set[int] = set()

    def _say(
        self,
        *sections: Section,
        player: Player | None = None,
        live: bool = False,
        chance: float = 1.0,
    ) -> bool:
        ctx, st = self.context, self.state
        if ctx is None or st.muted or st.abandoned or st.suspended_match:
            return False
        minute = st.minute()
        if live and minute - self.last_live_minute < 8:
            return False
        if chance < 1.0 and self.rng.random() >= chance:
            return False
        home = ctx.home_index
        values = {
            "local": st.team_name(home) if home is not None else "",
            "visitante": st.team_name(1 - home) if home is not None else "",
            "estadio": ctx.stadium,
            "ciudad": ctx.city,
            "dt": "el entrenador" if home is not None else "",
            "arbitro": "el árbitro",
            "jugador": player.name if player is not None else "",
        }
        choices: list[tuple[tuple[str, int], str]] = []
        for section in sections:
            key, indices = (section, None) if isinstance(section, str) else section
            lines = COMMENTARY_LINES[key]
            for idx in range(len(lines)) if indices is None else indices:
                identity = key, idx
                if identity in self.used or (identity in _POINTS_LINES and not ctx.for_points):
                    continue
                template = lines[idx]
                fields = (name for _, name, _, _ in _FORMATTER.parse(template) if name)
                if all(values.get(name) for name in fields):
                    choices.append((identity, template))
        if not choices:
            return False
        identity, template = self.rng.choice(choices)
        self.used.add(identity)
        if live:
            self.last_live_minute = minute
        if template.startswith("{dt},"):
            values["dt"] = "Entrenador"
        elif template.startswith("{arbitro},"):
            values["arbitro"] = "Árbitro"
        line = template.format_map(values)
        line = re.sub(r"\ba el (árbitro|entrenador)\b", r"al \1", line)
        line = re.sub(r"\bde el (árbitro|entrenador)\b", r"del \1", line)
        line = re.sub(r"(^|[.!?¿¡] )el (árbitro|entrenador)\b", r"\1El \2", line)
        self.speak(line)
        return True

    def introduction(self) -> None:
        ctx = self.context
        if ctx is None or ctx.home_index is None:
            return
        options: list[Section] = []
        if ctx.home_unbeaten:
            options.append("1.1")
        if ctx.home_leading:
            options.append("1.2")
        if ctx.home_winning:
            options.append("1.3")
        if self.state.attendance and self.state.attendance[1] >= 1.1:
            options.append("1.4")
        self._say(*options)

    def kickoff(self) -> None:
        self._say("1.5")

    def halftime(self) -> None:
        st = self.state
        ctx = self.context
        if ctx is None:
            return
        home = ctx.home_index
        options: list[Section] = ["2.2"]
        if st.goals == [0, 0]:
            options.append(("2.5", (0, 1, 2) if st.weather.key == "lluvia" else (0, 1)))
        if sum(st.fouls) >= 8 or sum(st.yellow_cards) >= 3 or sum(st.red_cards):
            indices = (0, 1, 2, 3) if any(st.yellow_cards) else (0, 2, 3)
            options.append(("2.3", indices))
        if home is not None:
            margin = st.goals[home] - st.goals[1 - home]
            if st.shots[home] <= 1 and st.shots[1 - home] >= 3:
                options.append(("2.1", (1, 3)))
            if home == 0 and any(st.flank_goals.values()):
                options.append(("2.1", (2,)))
            if margin > 0:
                options.extend([("2.1", (4,)), ("2.4", (0, 1))])
            elif margin < 0:
                options.extend([("2.1", (0,)), ("2.4", (2, 3, 4))])
            else:
                options.append(("2.4", (1,)))
        self._say(*options)

    def late_match(self) -> None:
        st = self.state
        home = self.context.home_index if self.context is not None else None
        if st.minute() < 65:
            return
        if st.goals == [0, 0] and "goalless" not in self.late_events:
            options: tuple[Section, ...] = (("4.2", (0, 2)), ("10.5", (2, 3)))
            if not any(st.shots):
                options += (("4.2", (1,)), ("10.5", (0, 1)))
            if self._say(*options, live=True):
                self.late_events.add("goalless")
        elif (
            home is not None
            and st.goals[home] < st.goals[1 - home]
            and "trailing" not in self.late_events
        ):
            if self._say("7.2", live=True):
                self.late_events.add("trailing")

    def goal(self, team: int, player: Player, kind: str | None, wonder: bool) -> None:
        st = self.state
        home = self.context.home_index if self.context is not None else None
        options: list[Section] = [("10.3", (4,))]
        if wonder:
            options.append(("10.3", (2,)))
        if kind in ("gol olímpico", "de chilena"):
            options.append(("10.1", (1, 2)))
        if kind == "de penal":
            options.append(("10.1", (3,)))
        if home == team:
            options.extend([("9.3", (0, 1, 2) if wonder else (1, 2)), ("10.3", (0, 3, 5))])
            if wonder or kind == "de penal":
                options.append(("10.3", (1,)))
        elif home is not None and st.goals[team] > st.goals[home] and st.goals[team] >= 2:
            options.extend(["7.3", ("8.5", (0, 1, 2))])
            if st.goalkeeper(home) is not None:
                options.append(("8.5", (3, 4)))
        self._say(*options, player=player, live=True, chance=0.70)

    def missed_chance(self, player: Player, *, high: bool, open_goal: bool) -> None:
        options: list[Section] = [("6.1", (0, 3, 4)), ("10.1", (0,)), ("10.2", (0, 3, 4))]
        if high:
            options.extend([("6.1", (1,)), ("8.3", (8,))])
        if player.position == "DEL":
            options.append(("8.3", (6,)))
        if open_goal:
            options.append(("6.1", (2,)))
        if id(player) in self.clear_misses:
            options.extend([("6.1", (5,)), ("8.3", (2, 9, 10)), ("10.2", (2, 7))])
        self.clear_misses.add(id(player))
        self._say(*options, player=player, live=True, chance=0.55)

    def turnover(
        self, player: Player, *, intercepted_pass: bool = False,
        dribble: bool = False, carry: bool = False,
    ) -> None:
        options: list[Section] = [("6.2", (1, 3)), ("8.3", (7,)), ("10.2", (1,))]
        if intercepted_pass:
            options.extend([("6.2", (0,)), ("10.2", (5,))])
        if dribble:
            options.append(("6.2", (4,)))
        if carry:
            options.extend([("8.3", (1, 4, 5, 11)), ("10.2", (6,))])
        if id(player) in self.turnovers:
            options.extend([("8.3", (3, 9, 10)), ("10.2", (2, 7))])
        self.turnovers.add(id(player))
        self._say(*options, player=player, live=True, chance=0.25)

    def handling_error(self, player: Player) -> None:
        self._say(("6.2", (2,)), ("8.3", (0,)), ("10.1", (1,)), player=player, live=True, chance=0.45)

    def card(self, player: Player, *, yellow: bool) -> None:
        self._say(("6.3", (0, 1) if yellow else (0, 2)), player=player, live=True, chance=0.40)

    def missed_handball(self) -> None:
        self._say(
            ("5.1", (0, 1, 2, 3, 4, 5, 6, 7, 9, 10)), ("8.2", (0, 1, 4, 5, 8, 9)),
            ("10.4", (0, 1, 2)), live=True,
        )

    def overturned_goal(self) -> None:
        self._say(("8.2", (2, 3, 7)), ("5.1", (8,)), ("10.4", (0, 3)), live=True, chance=0.55)

    def uncarded_contact(self) -> None:
        self._say(("5.1", (11,)), ("8.2", (6,)), ("10.4", (3,)), live=True, chance=0.20)

    def penalty_miss(self, player: Player, outcome: str) -> None:
        indices = (2, 3)
        if outcome == "parada":
            indices += (0,)
        elif outcome == "fuera":
            indices += (1,)
        self._say(("8.6", indices), player=player, live=True, chance=0.80)

    def full_time(self) -> None:
        st, ctx = self.state, self.context
        if ctx is None:
            return
        home = ctx.home_index
        margin = st.goals[home] - st.goals[1 - home] if home is not None else 0
        options: list[Section] = [("10.6", (0, 2)), ("3.4", (3,))]
        if st.goals == [0, 0] and st.penalties is None:
            options = ["4.1", "8.1"]
        elif home is not None and margin >= 3:
            options = ["9.2", ("10.6", (1,))]
        elif home is not None and margin > 0:
            options = ["3.1", "9.1", ("3.4", (0,))]
        elif home is not None and margin < 0:
            options = ["3.2", "7.1", "8.4", ("3.4", (1,)), ("10.6", (3, 4))]
            if margin <= -3:
                options.append("7.4")
        elif st.goals[0] == st.goals[1] and st.penalties is None:
            options.append("3.3")
        if sum(st.fouls) >= 12 and sum(st.goals) > 0:
            options.append(("3.4", (2,)))
        if not self._say(*options):
            self._say(("10.6", (0, 2)), ("3.4", (3,)))
