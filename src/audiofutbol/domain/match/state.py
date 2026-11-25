"""Mutable state, 2D spatial field, role overrides, weather/tactic physics, momentum, ratings, and stats."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from audiofutbol.domain.formations import (
    DEFAULT_ROLE_BY_GROUP,
    DEFAULT_SCHEME,
    MENTALITY_NAMES,
    MENTALITY_TACTIC,
    ROLES,
    SCHEME_STYLE,
    SCHEMES,
    assign_roles,
    choose_ai_scheme,
    family_of,
    fit,
    fit_multiplier,
    group_of,
    role_text,
    scheme_counts,
    scheme_slot_codes,
    side_of,
)
from audiofutbol.domain.match.ports import MatchSettings
from audiofutbol.domain.models import POSITION_ORDER, MatchResult, Player, Team

ZONES_OWN: dict[int, str] = {
    0: "en tu área",
    1: "en tu campo",
    2: "en campo rival",
    3: "en el área rival",
}

ZONES_RIVAL: dict[int, str] = {
    0: "en su propia área",
    1: "en su campo",
    2: "en tu campo, cerca de tu área",
    3: "¡dentro de tu área!",
}

LANES_ES: dict[int, str] = {
    -1: "por la banda izquierda",
    0: "por el centro",
    1: "por la banda derecha",
}

LANE_SIDE_NAME: dict[int, str] = {
    -1: "izquierda",
    0: "central",
    1: "derecha",
}

PENALTY_DIRECTIONS: tuple[str, ...] = ("a la izquierda", "al centro", "a la derecha")

_ADJACENT_ROLES: set[frozenset[str]] = {
    frozenset(("DEF", "MED")),
    frozenset(("MED", "DEL")),
}


@dataclass(frozen=True)
class WeatherProfile:
    """Match weather conditions with tangible physical effects on gameplay."""

    key: str
    name_es: str
    announcement: str
    shot_skid_mod: float = 1.0
    gk_spill_mod: float = 1.0
    slide_foul_mod: float = 1.0
    long_pass_mod: float = 1.0
    cross_mod: float = 1.0


WEATHER_PROFILES: tuple[WeatherProfile, ...] = (
    WeatherProfile(
        key="despejado",
        name_es="despejado",
        announcement="El cielo está despejado y el césped en perfectas condiciones.",
    ),
    WeatherProfile(
        key="nublado",
        name_es="fresco y nublado",
        announcement="Noche fresca y césped rápido, ideal para un partido intenso.",
        shot_skid_mod=1.03,
    ),
    WeatherProfile(
        key="lluvia",
        name_es="lluvia",
        announcement=(
            "Llueve sobre el estadio: el balón corre más rápido en tiros rasantes, "
            "el portero puede dar más rebotes y las barridas son más resbaladizas."
        ),
        shot_skid_mod=1.08,
        gk_spill_mod=1.35,
        slide_foul_mod=1.22,
        long_pass_mod=0.95,
    ),
    WeatherProfile(
        key="viento",
        name_es="viento fuerte",
        announcement=(
            "Sopla viento fuerte en el estadio: los centros y pases largos "
            "pueden ser más impredecibles."
        ),
        long_pass_mod=0.90,
        cross_mod=0.92,
    ),
)

TACTICS_ORDER: tuple[str, ...] = ("equilibrado", "ofensivo", "defensivo")

RIVAL_STYLES: tuple[dict[str, Any], ...] = (
    {
        "key": "posesion",
        "label": "juego de posesión y toque",
        "weights": {"shot": -4, "cross": -3, "dribble": 4, "through": 10, "one_two": 12, "switch": 8},
    },
    {
        "key": "directo",
        "label": "juego directo y centros al área",
        "weights": {"shot": 8, "cross": 14, "dribble": -3, "through": 2, "one_two": -4, "switch": 6},
    },
    {
        "key": "transicion",
        "label": "transiciones rápidas y contragolpe",
        "weights": {"shot": 6, "cross": 4, "dribble": 10, "through": 12, "one_two": 6, "switch": 4},
    },
    {
        "key": "equilibrado",
        "label": "juego equilibrado",
        "weights": {"shot": 0, "cross": 0, "dribble": 0, "through": 0, "one_two": 0, "switch": 0},
    },
)

MOOD_LABELS_ES: dict[str, str] = {
    "euforico": "eufórico y lleno de confianza",
    "confiado": "confiado",
    "sereno": "sereno y concentrado",
    "ansioso": "ansioso por el resultado",
    "frustrado": "frustrado e impaciente",
    "caliente": "muy caliente y agresivo",
}

TACTIC_PROFILES: dict[str, dict[str, Any]] = {
    "muy_defensivo": {
        "label": "Muy defensivo",
        "desc": "Muy defensivo: te cierras atrás, el bloque es casi impasable pero casi no atacas.",
        "att": -5.0,
        "mid": -2.0,
        "dfn": 7.5,
        "stamina": 0.80,
        "behind_risk": -0.14,
        "block_bonus": 0.12,
    },
    "muy_ofensivo": {
        "label": "Muy ofensivo",
        "desc": "Muy ofensivo: todo al ataque, dejas muchos espacios atrás.",
        "att": 7.0,
        "mid": 3.5,
        "dfn": -6.5,
        "stamina": 1.30,
        "behind_risk": 0.20,
        "block_bonus": -0.09,
    },
    "equilibrado": {
        "label": "Equilibrado",
        "desc": "Equilibrado: balance entre ataque y orden defensivo.",
        "att": 0.0,
        "mid": 0.0,
        "dfn": 0.0,
        "stamina": 1.0,
        "behind_risk": 0.0,
        "block_bonus": 0.0,
    },
    "ofensivo": {
        "label": "Ofensivo",
        "desc": "Ofensivo: más llegada y remate, pero dejas más espacios atrás.",
        "att": 4.5,
        "mid": 2.0,
        "dfn": -4.0,
        "stamina": 1.18,
        "behind_risk": 0.12,
        "block_bonus": -0.05,
    },
    "defensivo": {
        "label": "Defensivo",
        "desc": "Defensivo: bloque mucho más sólido y mejor contraataque, menos posesión arriba.",
        "att": -3.0,
        "mid": -1.0,
        "dfn": 5.0,
        "stamina": 0.88,
        "behind_risk": -0.08,
        "block_bonus": 0.08,
    },
}


def prob(p: float, rng: random.Random | None = None) -> bool:
    """Clamped Bernoulli trial matching AudioFútbol tuning (0.0 .. 0.97)."""
    r = rng.random() if rng is not None else random.random()
    return r < max(0.0, min(0.97, p))


class MatchState:
    """Encapsulates all runtime state of a single football match."""

    def __init__(
        self,
        user_team: Team,
        rival_team: Team,
        settings: MatchSettings,
        knockout: bool = False,
        auto: bool = False,
        title: str = "Partido",
        max_substitutions: int | None = None,
        first_leg: tuple[int, int] | None = None,
        home_index: int | None = None,
        away_goals_rule: bool = True,
        no_extra_time: bool = False,
        stadium: str | None = None,
        table_advantage: int | None = None,
        attendance: tuple[str, float] | None = None,
        rng: random.Random | None = None,
        yellow_card_limit: int = 2,
    ) -> None:
        self.rng = rng or random.Random()
        self.settings = settings
        self.yellow_card_limit = yellow_card_limit
        self.teams: list[Team] = [user_team, rival_team]
        self.attendance = attendance
        self.table_advantage = table_advantage
        self.first_leg = first_leg
        self.home_index = home_index
        self.away_goals_rule = away_goals_rule
        self.no_extra_time = no_extra_time
        self.stadium = stadium
        self.title = title

        # Weather & Tactical state
        self.weather: WeatherProfile = self.rng.choices(
            WEATHER_PROFILES, weights=[48, 22, 18, 12]
        )[0]
        self.tactics: list[str] = [
            MENTALITY_TACTIC.get(max(-2, min(2, int(t.mentality))), "equilibrado")
            for t in self.teams
        ]
        self.rival_style: dict[str, Any] = self.rng.choice(RIVAL_STYLES)
        self.momentum: float = 0.0  # -10 (rival dominates) .. +10 (user dominates)
        self.morale: list[float] = [0.0, 0.0]  # -10 (shaken/frustrated) .. +10 (confident/inspired)
        self.mood_state: list[str] = ["sereno", "sereno"]
        self.tension: float = 0.0  # 0 .. 100 match friction / heat from accumulated fouls & cards
        self.tension_stage_announced: int = 0  # 0=calm, 1=heated (>=35), 2=boiling (>=65)
        self.block_solidity: int = 0  # 0..3 accumulated when holding block cleanly
        self.space_bonus: float = 0.0  # bonus on next user attack (counter / switch play)
        self.rival_attack_turns: int = 0  # tracks consecutive rival turns in our half
        self.drought_turns: list[int] = [0, 0]  # turns without shots on target
        self.final_stretch_announced: bool = False

        self.highlights: list[tuple[int, str]] = []
        self.max_substitutions = max_substitutions
        self.extra_time_sub_bonus: int = 0
        self.substitutions_used: list[int] = [0, 0]
        self.subbed_off: list[set[int]] = [set(), set()]
        self.position_overrides: dict[int, str] = {}  # id(player) -> assigned role if playing out of position
        self.pending_substitution: bool = False
        self.ball_in_play: bool = True
        self.in_penalty_shootout: bool = False
        self.fatigue: dict[int, float] = {}
        self.injured: set[int] = set()
        self.fatigue_warned: set[int] = set()
        self.last_fatigue_warn_turn: int = -9
        self.excluded_suspended: list[set[int]] = [
            {id(p) for p in team.players if p.suspended_matches > 0}
            for team in self.teams
        ]
        self.scheme: list[str] = [
            self._initial_scheme(0, auto),
            self._initial_scheme(1, auto),
        ]
        self.xi: list[list[Player]] = [
            self.teams[i].lineup(self.scheme[i]) for i in (0, 1)
        ]
        self.slot: dict[int, str] = {}
        self.fit: dict[int, float] = {}
        self.board_slots: list[list[Player | None]] = [[None] * 11, [None] * 11]
        self.assign_slots(0)
        self.assign_slots(1)
        self.sort_lineup(0)
        self.sort_lineup(1)
        self.takers: list[dict[str, Player]] = [
            self._resolve_takers(0),
            self._resolve_takers(1),
        ]
        self.taker_auto: list[dict[str, Player]] = [{}, {}]
        self.last_pass: tuple[int, Player, int] | None = None
        self.assist_log: list[tuple[int, Player, int]] = []
        self.last_assist: Player | None = None
        self.flank_attacks: dict[str, int] = {"izquierda": 0, "derecha": 0}
        self.flank_goals: dict[str, int] = {"izquierda": 0, "derecha": 0}
        self.last_flank: tuple[str, int] | None = None
        self.perf: dict[int, int] = {}
        self.last_tactic_minute: list[int] = [-1, -1]
        self.shootout_lines: list[str] = []
        self.player_form: dict[int, float] = {
            id(p): self.rng.uniform(-2.0, 2.0)
            for team in self.teams
            for p in team.players
        }
        self.ratings: list[dict[str, float]] = [
            self.compute_ratings(0),
            self.compute_ratings(1),
        ]

        self.goals: list[int] = [0, 0]
        self.red_cards: list[int] = [0, 0]
        self.yellow_cards: list[int] = [0, 0]
        self.gk_penalty: list[int] = [0, 0]
        self.shots: list[int] = [0, 0]
        self.shots_on_target: list[int] = [0, 0]
        self.shots_post: list[int] = [0, 0]
        self.shots_saved: list[int] = [0, 0]
        self.shots_off_target: list[int] = [0, 0]
        self.shots_blocked: list[int] = [0, 0]
        self.saves: list[int] = [0, 0]
        self.interceptions: list[int] = [0, 0]
        self.blocks: list[int] = [0, 0]
        self.dribbles_won: list[int] = [0, 0]
        self.corner_streak: list[Any] = [None, 0]
        self.match_yellows: dict[int, int] = {}
        self.scorers: list[tuple[int, Player, int]] = []
        self.cards_log: list[tuple[int, str, str, int]] = []

        self.turn: int = 0
        self.possession: int = 0
        self.zone: int = 1
        self.lane: int = 0  # -1 left wing, 0 center, +1 right wing
        self.ball_carrier: Player | None = None
        self.knockout = knockout
        self.auto = auto
        self.muted = auto
        self.abandoned = False
        self.suspended_match = False
        self.penalties: tuple[int, int] | None = None

        seg = 120 if auto else settings.turn_seconds
        self.turn_seconds = seg if seg in (120, 60, 30) else 60
        self.factor = 120 // self.turn_seconds
        self.goal_factor = {1: 1.15, 2: 0.62, 4: 0.38}[self.factor]
        self.total_turns = 45 * self.factor
        self.halftime_turn = 22 * self.factor

        self.lost_seconds: float = 0.0
        self.wasted_seconds: float = 0.0
        self.time_waste_by_player: dict[int, int] = {}
        self.time_waste_by_team: list[int] = [0, 0]
        self.last_time_waste_turn: dict[int, int] = {}
        self.var_log: list[tuple[int, str]] = []
        self.corners: list[int] = [0, 0]
        self.fouls: list[int] = [0, 0]
        self.possession_turns: list[int] = [0, 0]
        self.fair_play: list[int] = [0, 0]
        self.halftime_snapshot: dict[str, Any] | None = None
        self.last_bicycle_taker: dict[int, Player] = {}

    def grant_extra_time_substitution(self) -> bool:
        """Grant one additional substitution to both teams upon entering extra time (idempotent)."""
        if self.extra_time_sub_bonus > 0:
            return False
        self.extra_time_sub_bonus = 1
        if self.max_substitutions is not None:
            self.max_substitutions += 1
        return True

    def roll(self, p: float) -> bool:
        return prob(p, self.rng)

    def team_name(self, team_idx: int) -> str:
        return self.teams[team_idx].name

    def minute(self) -> int:
        return int(self.turn * self.turn_seconds / 60)

    def lane_text(self) -> str:
        return LANES_ES[self.lane]

    def stereo_pan(self, jitter: float = 0.12) -> float:
        base = self.lane * 0.70
        return max(-0.95, min(0.95, base + self.rng.uniform(-jitter, jitter)))

    def shift_momentum(self, delta: float) -> None:
        self.momentum = max(-10.0, min(10.0, self.momentum + delta))
        self.shift_morale(0, delta * 0.45)
        self.shift_morale(1, -delta * 0.45)

    def shift_morale(self, team_idx: int, delta: float) -> None:
        self.morale[team_idx] = max(-10.0, min(10.0, self.morale[team_idx] + delta))
        self.update_moods()

    def add_tension(self, delta: float) -> None:
        """Increase or cool down match friction/aggressiveness (clamped 0..100)."""
        self.tension = max(0.0, min(100.0, self.tension + delta))
        self.update_moods()

    def aggression_level(self) -> float:
        """Normalized 0.0 .. 1.0 match aggressiveness factor from fouls and tension."""
        foul_pressure = min(40.0, sum(self.fouls) * 2.5)
        raw = max(self.tension, foul_pressure)
        return max(0.0, min(1.0, raw / 100.0))

    def tension_summary(self) -> str:
        if self.tension >= 65:
            return "El partido está caldeado y muy agresivo por las reiteradas faltas."
        if self.tension >= 35:
            return "El juego se está poniendo físico y con roces constantes."
        return "El partido se juega con deportividad."

    def update_moods(self) -> None:
        """Recompute emotional state for both teams based on morale, score, clock, and tension."""
        progress = (
            self.turn / float(self.total_turns) if self.total_turns > 0 else 0.0
        )
        score = (
            self.aggregate() if self.first_leg is not None else self.goals
        )
        for idx in (0, 1):
            diff = score[idx] - score[1 - idx]
            m = self.morale[idx]
            if self.tension >= 65 and (m <= 1.0 or self.fouls[idx] >= 5):
                self.mood_state[idx] = "caliente"
            elif m >= 4.5 or (diff >= 2 and m >= 1.5):
                self.mood_state[idx] = "euforico"
            elif m >= 1.8 or (diff == 1 and m >= 0.0):
                self.mood_state[idx] = "confiado"
            elif diff < 0 and progress >= 0.68:
                self.mood_state[idx] = "ansioso"
            elif m <= -2.8 or (diff < 0 and self.drought_turns[idx] >= 4):
                self.mood_state[idx] = "frustrado"
            else:
                self.mood_state[idx] = "sereno"

    def mood_label(self, team_idx: int) -> str:
        self.update_moods()
        return MOOD_LABELS_ES.get(self.mood_state[team_idx], "sereno y concentrado")

    def mood_summary(self) -> str:
        self.update_moods()
        return (
            f"Ánimo de {self.team_name(0)}: {self.mood_label(0)}. "
            f"Ánimo de {self.team_name(1)}: {self.mood_label(1)}."
        )

    def decay_momentum(self) -> None:
        self.momentum *= 0.90
        self.morale[0] *= 0.94
        self.morale[1] *= 0.94
        self.tension = max(0.0, self.tension - 0.85)
        self.update_moods()

    def momentum_summary(self) -> str:
        if self.momentum >= 3.5:
            return f"{self.team_name(0)} domina el ritmo y empuja con fuerza."
        if self.momentum <= -3.5:
            return f"{self.team_name(1)} está crecido y controla el impulso del partido."
        return "El partido está parejo y disputado."

    def context_lines(self, subs_text: str) -> list[str]:
        """Return structured status lines for the live match context reader (key N)."""
        pending = " Cambio pedido al cuarto árbitro." if self.pending_substitution else ""
        lines = [
            f"Minuto {self.minute()}. Marcador: {self.scoreboard_text()}.",
            (
                f"Tu equipo ({self.team_name(0)}): esquema {self.scheme_label(0)}, "
                f"mentalidad {MENTALITY_NAMES[self.mentality(0)]}, "
                f"ánimo {self.mood_label(0)}. {subs_text}.{pending}"
            ),
            (
                f"Rival ({self.team_name(1)}): esquema {self.scheme_label(1)}, "
                f"mentalidad {MENTALITY_NAMES[self.mentality(1)]}, "
                f"{self.rival_style['label']}, ánimo {self.mood_label(1)}."
            ),
        ]
        sol = (
            f" Solidez del bloque nivel {self.block_solidity} de 3."
            if self.block_solidity > 0
            else ""
        )
        space = (
            " Tienes espacios abiertos tras descolocar al rival."
            if self.space_bonus > 0
            else ""
        )
        lines.append(
            f"Ritmo y campo: el juego está {self.lane_text()}. "
            f"{self.momentum_summary()}{sol}{space}"
        )
        lines.append(f"Clima y ambiente: {self.weather.name_es}. {self.tension_summary()}")
        if self.flank_attacks["izquierda"] > 0 or self.flank_attacks["derecha"] > 0:
            lines.append(
                f"Llegadas rivales por banda: {self.flank_attacks['izquierda']} por tu izquierda "
                f"({self.flank_goals['izquierda']} goles) y {self.flank_attacks['derecha']} por tu derecha "
                f"({self.flank_goals['derecha']} goles)."
            )
        return lines

    @property
    def tactic(self) -> str:
        """Active tactical mentality key for the user's team."""
        return self.tactics[0]

    @tactic.setter
    def tactic(self, value: str) -> None:
        self.tactics[0] = value

    @property
    def rival_tactic(self) -> str:
        """Active tactical mentality key for the rival team."""
        return self.tactics[1]

    @rival_tactic.setter
    def rival_tactic(self, value: str) -> None:
        self.tactics[1] = value

    def cycle_tactic(self) -> str:
        idx = TACTICS_ORDER.index(self.tactic) if self.tactic in TACTICS_ORDER else 0
        self.tactic = TACTICS_ORDER[(idx + 1) % len(TACTICS_ORDER)]
        self.refresh_ratings()
        return TACTIC_PROFILES[self.tactic]["desc"]

    def tactic_profile(self, team_idx: int = 0) -> dict[str, Any]:
        return TACTIC_PROFILES[self.tactics[team_idx]]

    def mentality(self, team_idx: int) -> int:
        for value, key in MENTALITY_TACTIC.items():
            if key == self.tactics[team_idx]:
                return value
        return 0

    def set_mentality(self, team_idx: int, value: int) -> None:
        value = max(-2, min(2, value))
        self.tactics[team_idx] = MENTALITY_TACTIC[value]
        self.ratings[team_idx] = self.compute_ratings(team_idx)

    # ---------------------------------------------------- Schemes & Slots
    def _initial_scheme(self, idx: int, auto: bool) -> str:
        team = self.teams[idx]
        if team.scheme in SCHEMES:
            return str(team.scheme)
        if idx == 0 and not auto:
            return DEFAULT_SCHEME
        other = self.teams[1 - idx]
        return choose_ai_scheme(team.strength(), other.strength(), self.rng)

    def assign_slots(self, idx: int, use_fixed: bool = True) -> None:
        """Assign concrete scheme slots across the eleven players of team `idx`."""
        team = self.teams[idx]
        has_slots = any(id(p) in self.slot for p in self.xi[idx])
        gk = self.goalkeeper(idx) if has_slots else None
        fixed = team.positions if (use_fixed and team.positions) else None
        roles, fits = assign_roles(self.xi[idx], self.scheme[idx], fixed, goalkeeper=gk)
        for p in self.xi[idx]:
            self.slot.pop(id(p), None)
        self.slot.update(roles)
        self.fit.update(fits)
        self.sync_roles(idx)
        self.sort_lineup(idx)
        self.sync_board_slots(idx)

    def sync_board_slots(self, idx: int) -> None:
        """Align `board_slots[idx]` (length 11) with active XI and concrete slot codes."""
        codes = scheme_slot_codes(self.scheme[idx])
        on_pitch = list(self.xi[idx])
        prev = self.board_slots[idx] if len(self.board_slots[idx]) == len(codes) else [None] * len(codes)
        new_slots: list[Player | None] = [None] * len(codes)
        used: set[int] = set()
        for i, code in enumerate(codes):
            cand = prev[i]
            if (
                cand is not None
                and cand in on_pitch
                and id(cand) not in used
                and self.slot.get(id(cand)) == code
            ):
                new_slots[i] = cand
                used.add(id(cand))
        for i, code in enumerate(codes):
            if new_slots[i] is not None:
                continue
            match = next(
                (p for p in on_pitch if id(p) not in used and self.slot.get(id(p)) == code),
                None,
            )
            if match is not None:
                new_slots[i] = match
                used.add(id(match))
        self.board_slots[idx] = new_slots

    def apply_board_slots(
        self, idx: int, slots: list[Player | None], persist: bool = False
    ) -> None:
        """Rebuild XI, concrete roles, fits, and ratings from 11 tactical board slots."""
        codes = scheme_slot_codes(self.scheme[idx])
        padded = (list(slots) + [None] * len(codes))[: len(codes)]
        self.board_slots[idx] = list(padded)
        old_xi = list(self.xi[idx])
        for p in old_xi:
            self.slot.pop(id(p), None)
            self.fit.pop(id(p), None)
            self.position_overrides.pop(id(p), None)

        new_xi: list[Player] = []
        for code, player in zip(codes, padded):
            if player is None or player in new_xi:
                continue
            new_xi.append(player)
            self.slot[id(player)] = code
            self.fit[id(player)] = (
                (1.0 if player.position == "POR" else 0.3)
                if code == "POR"
                else fit(player, code)
            )
        self.xi[idx] = new_xi
        has_natural_gk = (
            padded[0] is not None and padded[0].position == "POR"
        ) or any(
            p.position == "POR" and self.slot.get(id(p)) == "POR" for p in new_xi
        )
        self.gk_penalty[idx] = 0 if has_natural_gk else -25
        self.sync_roles(idx)
        self.sort_lineup(idx)
        self.ratings[idx] = self.compute_ratings(idx)
        if persist:
            team = self.teams[idx]
            team.scheme = self.scheme[idx]
            team.lineup_names = [p.name for p in self.xi[idx]]
            team.positions = {
                p.name: code
                for code, p in zip(codes, padded)
                if p is not None and code != "POR"
            }

    def clear_lineup(
        self, idx: int, new_scheme: str | None = None, persist: bool = True
    ) -> None:
        """Clear all starters for team `idx`, optionally switching to `new_scheme`."""
        if new_scheme is not None:
            self.scheme[idx] = new_scheme
        self.apply_board_slots(idx, [None] * 11, persist=persist)

    def lineup_average_quality(
        self, team_idx: int = 0, include_fatigue: bool = False
    ) -> float:
        """Return average quality of currently placed players in `xi[team_idx]`."""
        xi = self.xi[team_idx]
        if not xi:
            return 0.0
        if include_fatigue:
            return sum(self.effective_overall(p) for p in xi) / float(len(xi))
        total = 0.0
        for p in xi:
            val = float(p.overall) * self.out_of_position_factor(p)
            if self.player_role(p) == p.position:
                val *= fit_multiplier(self.fit.get(id(p), 1.0))
            total += val
        return total / float(len(xi))

    def lineup_line_averages(self, team_idx: int = 0) -> dict[str, float]:
        """Return prematch average quality per occupied core position line."""
        out: dict[str, float] = {}
        for grp in ("POR", "DEF", "MED", "DEL"):
            players = [p for p in self.xi[team_idx] if self.player_role(p) == grp]
            if not players:
                continue
            vals = []
            for p in players:
                val = float(p.overall) * self.out_of_position_factor(p)
                if self.player_role(p) == p.position:
                    val *= fit_multiplier(self.fit.get(id(p), 1.0))
                vals.append(val)
            out[grp] = sum(vals) / float(len(vals))
        return out

    def sync_roles(self, idx: int) -> None:
        """Keep `position_overrides` synchronized with concrete tactical slots."""
        for p in self.xi[idx]:
            code = self.slot.get(id(p))
            if code is None:
                continue
            group = group_of(code)
            if group != p.position:
                self.position_overrides[id(p)] = group
            else:
                self.position_overrides.pop(id(p), None)

    def slot_code(self, player: Player) -> str:
        code = self.slot.get(id(player))
        if code:
            return code
        return DEFAULT_ROLE_BY_GROUP.get(self.player_role(player), "MC")

    def slot_text(self, player: Player) -> str:
        return role_text(self.slot_code(player))

    def slot_fit(self, player: Player) -> float:
        return self.fit.get(id(player), 1.0)

    def scheme_label(self, idx: int) -> str:
        """Return scheme name, or actual DEF-MED-DEL shape if modified by substitutions."""
        label = self.scheme[idx]
        want = scheme_counts(label)
        cur = self.formation_counts(idx)
        if all(want[k] == cur.get(k, 0) for k in ("POR", "DEF", "MED", "DEL")):
            return label
        return f"{cur['DEF']}-{cur['MED']}-{cur['DEL']}"

    def shape_counts(self, idx: int) -> dict[str, float]:
        """Compute line counts for rating bonuses (wingbacks split 70/30 DEF/MED)."""
        c = {"POR": 0.0, "DEF": 0.0, "MED": 0.0, "DEL": 0.0}
        for p in self.xi[idx]:
            code = self.slot.get(id(p))
            role = self.player_role(p)
            if code in ("CAI", "CAD") and role == "DEF":
                c["DEF"] += 0.7
                c["MED"] += 0.3
            else:
                c[role] = c.get(role, 0.0) + 1.0
        return c

    # ------------------------------------------------------------- Fixed Takers
    def _resolve_takers(self, idx: int) -> dict[str, Player]:
        team = self.teams[idx]
        by_name = {p.name: p for p in team.players}
        out: dict[str, Player] = {}
        for kind, name in (team.takers or {}).items():
            p = by_name.get(name)
            if p is not None:
                out[kind] = p
        return out

    def taker_order(self, idx: int, kind: str) -> list[Player]:
        pool = [
            p
            for p in self.xi[idx]
            if self.player_role(p) != "POR" and id(p) not in self.injured
        ] or list(self.xi[idx])

        def pts(p: Player) -> float:
            grp = self.player_role(p)
            if kind == "penal":
                return p.overall + {"DEL": 3.0, "MED": 2.0, "DEF": -4.0}.get(grp, 0.0)
            if kind == "libre":
                return p.overall + {"MED": 3.0, "DEL": 2.0, "DEF": -3.0}.get(grp, 0.0)
            wide = 1.5 if family_of(self.slot_code(p)) in ("ALA", "EXT", "LAT") else 0.0
            return p.overall + {"MED": 4.0, "DEL": 0.5, "DEF": -4.0}.get(grp, 0.0) + wide

        return sorted(pool, key=lambda p: -pts(p))

    def designated_taker(self, idx: int, kind: str) -> tuple[Player, str | None]:
        """Return fixed set-piece taker or consistent fallback plus optional notice."""
        fixed = self.takers[idx].get(kind)
        if fixed is not None and fixed in self.xi[idx] and id(fixed) not in self.injured:
            return fixed, None
        auto = self.taker_auto[idx].get(kind)
        notice: str | None = None
        if auto is None or auto not in self.xi[idx] or id(auto) in self.injured:
            auto = self.taker_order(idx, kind)[0]
            self.taker_auto[idx][kind] = auto
            if fixed is not None and idx == 0:
                notice = f"{fixed.name}, tu cobrador habitual, no está en el campo."
        return auto, notice

    # ------------------------------------------------------------------ Flanks
    def side_from_user(self, idx: int, player: Player) -> str:
        """Return player's flank side from the user's perspective (rival sides mirror)."""
        side = side_of(self.slot_code(player))
        if idx == 1 and side != "centro":
            return "derecha" if side == "izquierda" else "izquierda"
        return side

    def flank_player(
        self, idx: int, side: str, families: tuple[str, ...] = ("LAT", "EXT", "ALA")
    ) -> Player | None:
        pool = [
            p
            for p in self.xi[idx]
            if self.side_from_user(idx, p) == side
            and family_of(self.slot_code(p)) in families
        ]
        if not pool:
            return None
        weights = [(self.effective_overall(p) / 70.0) ** 2 for p in pool]
        return self.rng.choices(pool, weights=weights)[0]

    def flank_defender(self, side: str) -> Player | None:
        pool = [
            p
            for p in self.xi[0]
            if self.side_from_user(0, p) == side and family_of(self.slot_code(p)) == "LAT"
        ]
        if not pool:
            pool = [
                p
                for p in self.xi[0]
                if self.side_from_user(0, p) == side
                and family_of(self.slot_code(p)) in ("CEN", "ALA")
            ]
        return pool[0] if pool else None

    def _flank_quality(self, idx: int, side: str, fams: tuple[str, ...]) -> float | None:
        vals = [
            self.effective_overall(p)
            for p in self.xi[idx]
            if self.side_from_user(idx, p) == side and family_of(self.slot_code(p)) in fams
        ]
        return sum(vals) / len(vals) if vals else None

    def flank_edge(self, idx: int, side: str) -> float:
        """Return flank attack-vs-defense edge in [-0.12 .. +0.12]."""
        att = self._flank_quality(idx, side, ("LAT", "EXT", "ALA"))
        dfn = self._flank_quality(1 - idx, side, ("LAT", "CEN", "ALA"))
        if att is None or dfn is None:
            return 0.0
        return max(-0.12, min(0.12, (att - dfn) / 100.0 * 0.6))

    # ------------------------------------------------------- Performance & Assists
    def note(self, player: Player | None, points: int) -> None:
        if player is not None:
            self.perf[id(player)] = self.perf.get(id(player), 0) + points

    def note_text(self, player: Player) -> str:
        if id(player) not in self.perf:
            return "sin acciones destacadas"
        n = self.perf[id(player)]
        return "excelente" if n >= 4 else "bien" if n >= 2 else "regular" if n >= 0 else "flojo"

    def record_pass(self, team_idx: int, passer: Player | None) -> None:
        """Track most recent passer for goal assist attribution."""
        if passer is not None:
            self.last_pass = (team_idx, passer, self.turn)

    def pick_assistant(self, team_idx: int, scorer: Player) -> Player | None:
        """Return recent passer or weighted midfield/flank creator for a scored goal."""
        lp = self.last_pass
        self.last_pass = None
        if (
            lp is not None
            and lp[0] == team_idx
            and self.turn - lp[2] <= 1
            and lp[1] is not scorer
            and lp[1] in self.xi[team_idx]
        ):
            return lp[1]
        if not self.roll(0.55):
            return None
        pool = [
            p for p in self.xi[team_idx] if p is not scorer and self.player_role(p) != "POR"
        ]
        if not pool:
            return None
        weights = []
        for p in pool:
            w = {"MED": 3.0, "DEF": 0.8, "DEL": 2.2}.get(self.player_role(p), 1.0)
            if family_of(self.slot_code(p)) in ("MP", "LAT", "EXT", "ALA"):
                w *= 1.3
            weights.append(w * (p.overall / 70.0) ** 2)
        return self.rng.choices(pool, weights=weights)[0]

    # ------------------------------------------------------- Role & Formation
    def sort_lineup(self, team_idx: int) -> None:
        """Keep on-pitch players ordered by active tactical role (POR -> DEF -> MED -> DEL)."""
        self.xi[team_idx].sort(
            key=lambda p: POSITION_ORDER.get(self.player_role(p), 99)
        )

    def player_role(self, player: Player) -> str:
        """Current tactical position on the pitch (override if playing out of position)."""
        return self.position_overrides.get(id(player), player.position)

    def out_of_position_factor(self, player: Player) -> float:
        assigned = self.player_role(player)
        if assigned == player.position:
            return 1.0
        if "POR" in (assigned, player.position):
            return 0.58
        if frozenset((assigned, player.position)) in _ADJACENT_ROLES:
            return 0.88
        return 0.76

    def formation_counts(self, team_idx: int) -> dict[str, int]:
        counts = {"POR": 0, "DEF": 0, "MED": 0, "DEL": 0}
        for p in self.xi[team_idx]:
            role = self.player_role(p)
            counts[role] = counts.get(role, 0) + 1
        return counts

    def formation_code(self, team_idx: int) -> str:
        c = self.formation_counts(team_idx)
        return f"{c['DEF']}-{c['MED']}-{c['DEL']}"

    def formation_text(self, team_idx: int) -> str:
        return f"Esquema {self.scheme_label(team_idx)}"

    def effective_overall(self, player: Player) -> float:
        base_ovr = player.overall + self.player_form.get(id(player), 0.0)
        val = (
            base_ovr
            * self.out_of_position_factor(player)
            * (1.0 - 0.14 * self.fatigue.get(id(player), 0.0) / 100.0)
        )
        if self.player_role(player) == player.position:
            val *= fit_multiplier(self.fit.get(id(player), 1.0))
        if id(player) in self.injured:
            val *= 0.6
        return val

    def compute_ratings(self, team_idx: int) -> dict[str, float]:
        xi = self.xi[team_idx]

        def avg(role: str) -> float:
            vals = [self.effective_overall(p) for p in xi if self.player_role(p) == role]
            if vals:
                return sum(vals) / len(vals)
            return sum(self.effective_overall(p) for p in xi) / max(1, len(xi))

        c = self.shape_counts(team_idx)
        d, m, f, gk = avg("DEF"), avg("MED"), avg("DEL"), avg("POR")

        # Tactical formation shape directly affects line strength (vs base 4-3-3)
        att_shape = (c["DEL"] - 3) * 2.6 + (c["MED"] - 3) * 0.6
        mid_shape = (c["MED"] - 3) * 2.2
        dfn_shape = (c["DEF"] - 4) * 2.8 + (c["MED"] - 3) * 0.5

        res = {
            "att": 0.62 * f + 0.38 * m + att_shape,
            "mid": 0.60 * m + 0.20 * f + 0.20 * d + mid_shape,
            "dfn": 0.72 * d + 0.28 * m + dfn_shape,
            "gk": gk,
        }
        label = self.scheme[team_idx]
        want = scheme_counts(label)
        cur = self.formation_counts(team_idx)
        if all(want[k] == cur.get(k, 0) for k in ("POR", "DEF", "MED", "DEL")):
            sa, sm, sd = SCHEME_STYLE.get(label, (0.0, 0.0, 0.0))
            res["att"] += sa
            res["mid"] += sm
            res["dfn"] += sd
        tp = self.tactic_profile(team_idx)
        res["att"] += tp["att"]
        res["mid"] += tp["mid"]
        res["dfn"] += tp["dfn"]
        return res

    def refresh_ratings(self) -> None:
        self.ratings = [self.compute_ratings(0), self.compute_ratings(1)]

    def rating(self, team_idx: int, key: str) -> float:
        val = self.ratings[team_idx][key]
        mom_boost = (self.momentum if team_idx == 0 else -self.momentum) * 0.35
        morale_boost = self.morale[team_idx] * 0.22
        if key == "gk":
            return val + self.gk_penalty[team_idx] + (mom_boost + morale_boost) * 0.5
        shortage = max(self.red_cards[team_idx], max(0, 11 - len(self.xi[team_idx])))
        return (val + mom_boost + morale_boost) * max(0.3, 1.0 - 0.07 * shortage)

    def duel_advantage(self, player_a: Player, player_b: Player) -> float:
        """Strong individual player-vs-player rating edge (-0.26..+0.26)."""
        return max(
            -0.26,
            min(
                0.26,
                (self.effective_overall(player_a) - self.effective_overall(player_b))
                / 72.0,
            ),
        )

    def goalkeeper(self, team_idx: int) -> Player | None:
        for player in self.xi[team_idx]:
            if self.player_role(player) == "POR":
                return player
        return None

    def pick_player(
        self,
        team_idx: int,
        weights_by_pos: dict[str, float],
        exclude: Player | None = None,
    ) -> Player:
        xi = [p for p in self.xi[team_idx] if p is not exclude] or list(self.xi[team_idx])
        weights = [
            weights_by_pos.get(self.player_role(p), 1.0)
            * (self.effective_overall(p) / 70.0) ** 2.4
            for p in xi
        ]
        if sum(weights) <= 0:
            weights = [1.0] * len(xi)
        return self.rng.choices(xi, weights=weights)[0]

    def ensure_ball_carrier(self, team_idx: int | None = None) -> Player:
        idx = self.possession if team_idx is None else team_idx
        if self.ball_carrier is not None and self.ball_carrier in self.xi[idx]:
            return self.ball_carrier
        if self.zone <= 0:
            weights = {"DEF": 4.0, "POR": 1.0, "MED": 2.0, "DEL": 0.3}
        elif self.zone == 1:
            weights = {"DEF": 2.5, "MED": 4.0, "DEL": 1.2, "POR": 0.1}
        elif self.zone == 2:
            weights = {"MED": 3.5, "DEL": 3.0, "DEF": 0.8, "POR": 0.0}
        else:
            weights = {"DEL": 4.5, "MED": 2.5, "DEF": 0.4, "POR": 0.0}
        self.ball_carrier = self.pick_player(idx, weights)
        return self.ball_carrier

    def set_possession(
        self,
        team_idx: int,
        zone: int,
        lane: int | None = None,
        carrier: Player | None = None,
    ) -> None:
        self.possession = team_idx
        self.zone = max(0, min(3, zone))
        if lane is not None:
            self.lane = max(-1, min(1, lane))
        else:
            self.lane = self.rng.choices((-1, 0, 1), weights=[28, 44, 28])[0]
        if carrier is not None and carrier in self.xi[team_idx]:
            self.ball_carrier = carrier
        else:
            self.ball_carrier = None
            self.ensure_ball_carrier(team_idx)
        if team_idx == 0:
            self.block_solidity = 0
            self.rival_attack_turns = 0

    def pick_scorer(self, team_idx: int, header: bool = False) -> Player:
        weights = (
            {"DEL": 3.0, "MED": 1.2, "DEF": 2.0, "POR": 0.0}
            if header
            else {"DEL": 5.0, "MED": 2.2, "DEF": 0.7, "POR": 0.0}
        )
        return self.pick_player(team_idx, weights)

    def pick_receiver(
        self, team_idx: int, pass_type: str, exclude: Player | None = None
    ) -> Player:
        z = self.zone
        if pass_type == "filtrado":
            weights = {"DEL": 4.0, "MED": 2.5, "DEF": 0.1, "POR": 0.0}
        elif z <= 1:
            weights = {"DEF": 3.0, "MED": 3.0, "DEL": 0.6, "POR": 0.3}
        elif z == 2:
            weights = {"MED": 3.0, "DEL": 2.5, "DEF": 0.6, "POR": 0.0}
        else:
            weights = {"DEL": 3.5, "MED": 2.5, "DEF": 0.4, "POR": 0.0}
        return self.pick_player(team_idx, weights, exclude=exclude)

    def pick_bicycle_taker(self, team_idx: int) -> Player:
        outfield = [p for p in self.xi[team_idx] if self.player_role(p) != "POR"] or list(
            self.xi[team_idx]
        )
        last = self.last_bicycle_taker.get(team_idx)
        weights = []
        for p in outfield:
            w = {"DEL": 3.0, "MED": 2.5, "DEF": 1.6}.get(self.player_role(p), 1.0)
            if p is last:
                w *= 0.25
            weights.append(w)
        chosen = self.rng.choices(outfield, weights=weights)[0]
        self.last_bicycle_taker[team_idx] = chosen
        return chosen

    def add_highlight(self, text: str) -> None:
        self.highlights.append((self.minute(), text))

    def aggregate(self) -> list[int]:
        assert self.first_leg is not None
        return [self.first_leg[0] + self.goals[0], self.first_leg[1] + self.goals[1]]

    def decided_winner(self) -> int | None:
        if self.first_leg is None:
            if self.goals[0] != self.goals[1]:
                return 0 if self.goals[0] > self.goals[1] else 1
            return None
        agg = self.aggregate()
        if agg[0] != agg[1]:
            return 0 if agg[0] > agg[1] else 1
        if self.table_advantage is not None:
            return self.table_advantage
        if self.away_goals_rule and self.home_index is not None:
            away = [0, 0]
            away[self.home_index] = self.first_leg[self.home_index]
            away[1 - self.home_index] = self.goals[1 - self.home_index]
            if away[0] != away[1]:
                return 0 if away[0] > away[1] else 1
        return None

    def scoreboard_text(self) -> str:
        text = f"{self.team_name(0)} {self.goals[0]}, {self.team_name(1)} {self.goals[1]}"
        if self.first_leg is not None:
            agg = self.aggregate()
            text += f". Global: {self.team_name(0)} {agg[0]}, {self.team_name(1)} {agg[1]}"
        return text

    def hud_status(self) -> str:
        tactic_lbl = TACTIC_PROFILES[self.tactic]["label"]
        base = (
            f"Min {self.minute()}' | {self.team_name(0)} {self.goals[0]} - "
            f"{self.goals[1]} {self.team_name(1)} | {self.scheme_label(0)} {tactic_lbl} | {self.weather.name_es.capitalize()}"
        )
        if self.pending_substitution:
            base += " | Cambio pedido"
        if self.first_leg is not None:
            agg = self.aggregate()
            base += f" | Global {agg[0]}-{agg[1]}"
        return base

    @staticmethod
    def format_on_target(count: int) -> str:
        if count == 0:
            return "ninguno a puerta"
        if count == 1:
            return "uno a puerta"
        return f"{count} a puerta"

    def shots_text(self, team_idx: int) -> str:
        return (
            f"Tiros de {self.team_name(team_idx)}: {self.shots[team_idx]}, "
            f"{self.format_on_target(self.shots_on_target[team_idx])}."
        )

    def can_chain_corner(self, team_idx: int, consecutive: bool) -> bool:
        return not (
            consecutive
            and self.corner_streak[0] == team_idx
            and self.corner_streak[1] >= 4
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "goles": list(self.scorers),
            "tarjetas": list(self.cards_log),
            "tiros": list(self.shots),
            "tiros_p": list(self.shots_on_target),
            "tiros_poste": list(self.shots_post),
            "tiros_atajados": list(self.shots_saved),
            "tiros_desviados": list(self.shots_off_target),
            "tiros_bloqueados": list(self.shots_blocked),
            "atajadas": list(self.saves),
            "intercepciones": list(self.interceptions),
            "bloqueos": list(self.blocks),
            "corners": list(self.corners),
            "faltas": list(self.fouls),
            "pos": list(self.possession_turns),
            "fp": list(self.fair_play),
            "marcador": list(self.goals),
        }

    @staticmethod
    def possession_pct(pos: list[int]) -> tuple[int, int]:
        total = pos[0] + pos[1]
        if total <= 0:
            return 50, 50
        pct0 = int(round(100.0 * pos[0] / total))
        return pct0, 100 - pct0

    def stats_lines(self, snap: dict[str, Any]) -> list[str]:
        n0, n1 = self.team_name(0), self.team_name(1)
        pa, pb = self.possession_pct(snap["pos"])
        out = [
            f"Posesión del balón: {n0} {pa} por ciento, {n1} {pb} por ciento.",
            f"Tiros totales: {n0} {snap['tiros'][0]}, {n1} {snap['tiros'][1]}.",
            f"Tiros a puerta: {n0} {snap['tiros_p'][0]}, {n1} {snap['tiros_p'][1]}.",
            (
                f"Tiros al poste: {n0} {snap.get('tiros_poste', [0, 0])[0]}, "
                f"{n1} {snap.get('tiros_poste', [0, 0])[1]}."
            ),
            (
                f"Tiros atajados por el portero contrario: "
                f"{n0} {snap.get('tiros_atajados', [0, 0])[0]}, "
                f"{n1} {snap.get('tiros_atajados', [0, 0])[1]}."
            ),
            (
                f"Tiros desviados: {n0} {snap.get('tiros_desviados', [0, 0])[0]}, "
                f"{n1} {snap.get('tiros_desviados', [0, 0])[1]}."
            ),
            (
                f"Tiros interceptados o bloqueados: "
                f"{n0} {snap.get('tiros_bloqueados', [0, 0])[0]}, "
                f"{n1} {snap.get('tiros_bloqueados', [0, 0])[1]}."
            ),
            f"Atajadas del portero: {n0} {snap.get('atajadas', [0, 0])[0]}, {n1} {snap.get('atajadas', [0, 0])[1]}.",
            f"Intercepciones y bloqueos defensivos: {n0} {snap.get('intercepciones', [0, 0])[0] + snap.get('bloqueos', [0, 0])[0]}, "
            f"{n1} {snap.get('intercepciones', [0, 0])[1] + snap.get('bloqueos', [0, 0])[1]}.",
            f"Tiros de esquina: {n0} {snap['corners'][0]}, {n1} {snap['corners'][1]}. Total {sum(snap['corners'])}.",
            f"Faltas: {n0} {snap['faltas'][0]}, {n1} {snap['faltas'][1]}. Total {sum(snap['faltas'])}.",
        ]
        yellows = [
            t
            for t in snap["tarjetas"]
            if t[2].startswith("amarilla") or t[2] == "segunda amarilla"
        ]
        reds = [
            t for t in snap["tarjetas"] if t[2] in ("roja", "segunda amarilla")
        ]
        y0 = sum(1 for t in yellows if t[0] == 0)
        y1 = sum(1 for t in yellows if t[0] == 1)
        out.append(
            f"Tarjetas amarillas: {n0} {y0}, {n1} {y1}. Total {len(yellows)}."
        )
        if yellows:
            out.append(
                "Amonestados: "
                + "; ".join(
                    f"{name}, de {self.team_name(i)}, minuto {m}"
                    for i, name, _, m in yellows
                )
                + "."
            )
        else:
            out.append("Nadie fue amonestado.")

        r0 = sum(1 for t in reds if t[0] == 0)
        r1 = sum(1 for t in reds if t[0] == 1)
        out.append(f"Expulsados: {n0} {r0}, {n1} {r1}.")
        for i, name, card_type, m in reds:
            reason = "doble amarilla" if card_type == "segunda amarilla" else "roja directa"
            out.append(f"Expulsado {name}, de {self.team_name(i)}, minuto {m}, por {reason}.")

        out.append(
            f"Puntos de fair play, menos es mejor: {n0} {snap['fp'][0]}, {n1} {snap['fp'][1]}."
        )
        return out

    def summary_lines(self, title: str, snap: dict[str, Any]) -> list[str]:
        out = [
            f"{title}. {self.team_name(0)} {snap['marcador'][0]}, "
            f"{self.team_name(1)} {snap['marcador'][1]}."
        ]
        if snap["goles"]:
            out.append(
                "Goles: "
                + "; ".join(
                    f"{p.name}, de {self.team_name(i)}, minuto {m}"
                    for i, p, m in snap["goles"]
                )
                + "."
            )
        else:
            out.append("No hubo goles.")
        return out + self.stats_lines(snap)

    def recap_lines(self) -> list[str]:
        out = []
        line = f"Resultado final: {self.team_name(0)} {self.goals[0]}, {self.team_name(1)} {self.goals[1]}"
        if self.penalties:
            line += f", penales {self.penalties[0]} a {self.penalties[1]}"
        out.append(line)
        if self.first_leg is not None:
            agg = self.aggregate()
            out.append(f"Global: {self.team_name(0)} {agg[0]}, {self.team_name(1)} {agg[1]}")
        out.extend(self.shootout_lines)
        if not self.highlights:
            out.append("Fue un partido con pocas emociones.")
        for m, txt in self.highlights:
            out.append(f"Minuto {m}. {txt}")
        out.append("Estadísticas del partido.")
        out.extend(self.stats_lines(self.snapshot()))
        return out

    def build_result(self) -> MatchResult:
        goals = (0, 3) if self.abandoned else (self.goals[0], self.goals[1])
        return MatchResult(
            goals=goals,
            penalties=self.penalties,
            abandoned=self.abandoned,
            fair_play=(self.fair_play[0], self.fair_play[1]),
            scorers=[(self.teams[i], p, m) for i, p, m in self.scorers],
            assists=[(self.teams[i], p, m) for i, p, m in self.assist_log],
            highlights=list(self.highlights),
            red_cards=(self.red_cards[0], self.red_cards[1]),
            yellow_cards=(self.yellow_cards[0], self.yellow_cards[1]),
        )
