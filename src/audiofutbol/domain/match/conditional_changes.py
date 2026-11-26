"""Conditions used for planned substitutions in played and simulated matches."""

from __future__ import annotations

from dataclasses import dataclass

from audiofutbol.domain.models import Player

CONDITIONS = {
    "always": "sin importar el marcador",
    "ahead": "si vamos ganando",
    "level": "si vamos empatando",
    "behind": "si vamos perdiendo",
    "tired": "si el titular supera 60 de cansancio",
    "injured": "si se lesiona el jugador que debe salir",
    "extra_player": "si el rival tiene más expulsados",
    "short_handed": "si tenemos más expulsados que el rival",
}

MAX_PLANNED_CHANGES = 3

@dataclass(frozen=True)
class ConditionalChange:
    minute: int
    condition: str
    outgoing: str
    incoming: str

    def matches(
        self, minute: int, margin: int, fatigue: float, *, injured: bool = False,
        red_card_advantage: int = 0,
    ) -> bool:
        return minute >= self.minute and {
            "always": True, "ahead": margin > 0, "level": margin == 0,
            "behind": margin < 0, "tired": fatigue >= 60,
            "injured": injured,
            "extra_player": red_card_advantage > 0,
            "short_handed": red_card_advantage < 0,
        }.get(self.condition, False)

    def players(self, xi: list[Player], bench: list[Player]) -> tuple[Player, Player] | None:
        out = next((p for p in xi if p.name == self.outgoing), None)
        incoming = next((p for p in bench if p.name == self.incoming and p.available), None)
        if out is None or incoming is None:
            return None
        return out, incoming

    def describe(self) -> str:
        start = f"Desde el minuto {self.minute}" if self.minute else "Desde el inicio"
        return f"{start}, {CONDITIONS[self.condition]}: sale {self.outgoing}, entra {self.incoming}."
