"""Core football domain entities: players, teams, and match results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audiofutbol.domain.formations import DEFAULT_SCHEME, SCHEMES, scheme_counts

FORMATION: tuple[tuple[str, int], ...] = (
    ("POR", 1),
    ("DEF", 4),
    ("MED", 3),
    ("DEL", 3),
)

POSITION_NAMES_ES: dict[str, str] = {
    "POR": "portero",
    "DEF": "defensa",
    "MED": "mediocampista",
    "DEL": "delantero",
}

POSITION_ORDER: dict[str, int] = {"POR": 0, "DEF": 1, "MED": 2, "DEL": 3}


@dataclass
class Player:
    """A football player with rating, position, and tournament discipline/goals."""

    name: str
    position: str
    overall: int
    number: int = 0
    yellow_cards: int = 0
    suspended_matches: int = 0
    goals: int = 0
    assists: int = 0
    puesto: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "overall": self.overall,
            "number": self.number,
            "yellow_cards": self.yellow_cards,
            "suspended_matches": self.suspended_matches,
            "goals": self.goals,
            "assists": self.assists,
            "puesto": self.puesto,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Player:
        return cls(
            name=str(data["name"]),
            position=str(data["position"]),
            overall=int(data["overall"]),
            number=int(data.get("number", 0)),
            yellow_cards=int(data.get("yellow_cards", 0)),
            suspended_matches=int(data.get("suspended_matches", 0)),
            goals=int(data.get("goals", 0)),
            assists=int(data.get("assists", 0)),
            puesto=str(data.get("puesto", "") or ""),
        )


@dataclass
class Team:
    """A national team or club with a squad and optional venue metadata."""

    name: str
    players: list[Player]
    team_id: str = ""
    country: str = ""
    stadium: str | None = None
    city: str = ""
    group: str | None = None
    level: int = 72
    is_real_squad: bool = False
    scheme: str | None = None
    lineup_names: list[str] | None = None
    positions: dict[str, str] = field(default_factory=dict)
    takers: dict[str, str] = field(default_factory=dict)
    mentality: int = 0

    def lineup(
        self, scheme: str | None = None, ignore_suspensions: bool = False
    ) -> list[Player]:
        """Build the XI for `scheme`, preserving preferred `lineup_names` when valid."""
        use = (
            scheme
            if scheme in SCHEMES
            else (self.scheme if self.scheme in SCHEMES else DEFAULT_SCHEME)
        )
        counts = scheme_counts(use)
        available = [
            p for p in self.players if ignore_suspensions or p.suspended_matches <= 0
        ]
        by_name = {p.name: p for p in available}
        xi: list[Player] = []
        used: set[int] = set()
        for name in self.lineup_names or []:
            p = by_name.get(name)
            if p is not None and id(p) not in used:
                xi.append(p)
                used.add(id(p))
        for pos in ("POR", "DEF", "MED", "DEL"):
            group = [p for p in xi if p.position == pos]
            if len(group) > counts[pos]:
                for p in sorted(group, key=lambda q: q.overall)[: len(group) - counts[pos]]:
                    xi.remove(p)
                    used.discard(id(p))
            elif len(group) < counts[pos]:
                extra = sorted(
                    (p for p in available if p.position == pos and id(p) not in used),
                    key=lambda q: -q.overall,
                )[: counts[pos] - len(group)]
                xi.extend(extra)
                used.update(id(p) for p in extra)
        missing = 11 - len(xi)
        if missing > 0:
            rest = sorted(
                (p for p in available if id(p) not in used),
                key=lambda q: (q.position == "POR", -q.overall),
            )[:missing]
            xi.extend(rest)
        if not any(p.position == "POR" for p in xi):
            xi = [Player("Portero suplente", "POR", 60)] + xi[:10]
        xi.sort(key=lambda p: POSITION_ORDER[p.position])
        return xi

    def starting_xi(self, ignore_suspensions: bool = False) -> list[Player]:
        """Pick the strongest available 11 players respecting 1-4-3-3 formation."""
        available = [
            p for p in self.players if ignore_suspensions or p.suspended_matches <= 0
        ]
        xi: list[Player] = []
        used: set[int] = set()
        for pos, count in FORMATION:
            candidates = sorted(
                (p for p in available if p.position == pos and id(p) not in used),
                key=lambda p: -p.overall,
            )[:count]
            for player in candidates:
                used.add(id(player))
            xi.extend(candidates)

        missing = 11 - len(xi)
        if missing > 0:
            extras = sorted(
                (p for p in available if id(p) not in used),
                key=lambda p: (p.position == "POR", -p.overall),
            )[:missing]
            xi.extend(extras)

        if not any(p.position == "POR" for p in xi):
            xi = [Player("Portero suplente", "POR", 60)] + xi[:10]
        return xi

    def strength(self) -> float:
        """Average overall rating of the full-strength starting XI."""
        xi = self.starting_xi(ignore_suspensions=True)
        return sum(p.overall for p in xi) / float(len(xi))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "players": [p.to_dict() for p in self.players],
            "team_id": self.team_id,
            "country": self.country,
            "stadium": self.stadium,
            "city": self.city,
            "group": self.group,
            "level": self.level,
            "is_real_squad": self.is_real_squad,
            "scheme": self.scheme,
            "lineup_names": self.lineup_names,
            "positions": dict(self.positions),
            "takers": dict(self.takers),
            "mentality": self.mentality,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        return cls(
            name=str(data["name"]),
            players=[Player.from_dict(p) for p in data["players"]],
            team_id=str(data.get("team_id", "")),
            country=str(data.get("country", "")),
            stadium=data.get("stadium"),
            city=str(data.get("city", "")),
            group=data.get("group"),
            level=int(data.get("level", 72)),
            is_real_squad=bool(data.get("is_real_squad", False)),
            scheme=data.get("scheme"),
            lineup_names=(
                [str(n) for n in data["lineup_names"]]
                if data.get("lineup_names")
                else None
            ),
            positions={str(k): str(v) for k, v in (data.get("positions") or {}).items()},
            takers={str(k): str(v) for k, v in (data.get("takers") or {}).items()},
            mentality=int(data.get("mentality", 0)),
        )


@dataclass
class MatchResult:
    """Outcome summary produced by a completed or abandoned match."""

    goals: tuple[int, int]
    penalties: tuple[int, int] | None = None
    abandoned: bool = False
    fair_play: tuple[int, int] = (0, 0)
    scorers: list[tuple[Team, Player, int]] = field(default_factory=list)
    assists: list[tuple[Team, Player, int]] = field(default_factory=list)
    highlights: list[tuple[int, str]] = field(default_factory=list)
    red_cards: tuple[int, int] = (0, 0)
    yellow_cards: tuple[int, int] = (0, 0)


def format_result_text(
    team_a: Team,
    team_b: Team,
    goals_a: int,
    goals_b: int,
    penalties: tuple[int, int] | None = None,
) -> str:
    """Format a human-readable Spanish match result string."""
    text = f"{team_a.name} {goals_a}, {team_b.name} {goals_b}"
    if penalties:
        text += f", penales {penalties[0]} a {penalties[1]}"
    return text
