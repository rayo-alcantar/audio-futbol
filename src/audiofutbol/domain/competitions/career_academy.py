"""Career academy based on the contribution's scouting and development loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product
from random import Random
from typing import Any

from audiofutbol.domain.competitions.career_squad import can_sign, club_key, sign_player
from audiofutbol.domain.models import POSITION_NAMES_ES, Player, Team

SCOUT_COST = 250_000
SCOUT_INTERVAL = 90
TRAINING_INTERVAL = 30
ACADEMY_LIMIT = 12
FIRST = ("Lucas", "Gabriel", "Bruno", "Rafael", "João", "Thiago", "Mateus", "Vinícius", "Davi")
LAST = ("Silva", "Costa", "Moura", "Rocha", "Pereira", "Martins", "Lima", "Ribeiro", "Oliveira")


@dataclass
class Prospect:
    name: str
    position: str
    overall: int
    potential: int
    born: int
    trained_at: int


@dataclass
class CareerAcademy:
    prospects: list[Prospect] = field(default_factory=list)
    last_scouted: int | None = None
    promoted_names: list[str] = field(default_factory=list)

    def scout_blocker(self, elapsed: int, balance: int) -> str:
        if len(self.prospects) + 3 > ACADEMY_LIMIT:
            return "No hay tres plazas libres en la cantera."
        if self.last_scouted is not None and (wait := SCOUT_INTERVAL - elapsed + self.last_scouted) > 0:
            return f"Faltan {wait} días para volver a enviar al ojeador."
        if balance < SCOUT_COST:
            return "No hay presupuesto para enviar al ojeador."
        return ""

    def scout(self, team: Team, year: int, elapsed: int, balance: int) -> list[Prospect]:
        if reason := self.scout_blocker(elapsed, balance):
            raise ValueError(reason)
        used = {club_key(p.name) for p in [*team.players, *self.prospects]}
        used.update(club_key(name) for name in self.promoted_names)
        names = [f"{a} {b}" for a, b in product(FIRST, LAST) if club_key(f"{a} {b}") not in used]
        if len(names) < 3:
            raise ValueError("No hay tres candidatos nuevos disponibles para este informe.")
        rng = Random(f"{team.team_id}-{elapsed}")
        found = []
        for name in rng.sample(names, 3):
            overall = rng.randint(49, 65)
            found.append(Prospect(name, rng.choice(tuple(POSITION_NAMES_ES)), overall,
                                  min(94, overall + rng.randint(10, 28)),
                                  year - rng.randint(15, 18), elapsed))
        self.prospects.extend(found)
        self.last_scouted = elapsed
        return found

    def advance(self, year: int, elapsed: int) -> list[str]:
        messages = []
        remaining = []
        for p in self.prospects:
            if year - p.born >= 21:
                messages.append(f"{p.name} dejó la cantera al cumplir 21 años.")
                continue
            periods = max(0, elapsed - p.trained_at) // TRAINING_INTERVAL
            if periods:
                p.overall = min(p.potential, p.overall + periods)
                p.trained_at += periods * TRAINING_INTERVAL
            remaining.append(p)
        self.prospects = remaining
        return messages

    def promote(self, team: Team, prospect: Prospect, year: int) -> Player:
        if not any(p is prospect for p in self.prospects) or year - prospect.born < 16:
            raise ValueError("El juvenil debe estar en la cantera y tener al menos 16 años.")
        signed = sign_player(team, Player(prospect.name, prospect.position, prospect.overall, birth_year=prospect.born))
        self.release(prospect)
        self.promoted_names.append(signed.name)
        return signed

    def release(self, prospect: Prospect) -> None:
        self.prospects = [p for p in self.prospects if p is not prospect]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CareerAcademy:
        return cls([Prospect(**p) for p in data["prospects"]],
                   data["last_scouted"], list(data["promoted_names"]))
