"""Small shareable rule set for planned career substitutions."""

from __future__ import annotations

from dataclasses import dataclass

from audiofutbol.domain.models import Player

CONDITIONS = {
    "always": "sin importar el marcador",
    "ahead": "si vamos ganando",
    "level": "si vamos empatando",
    "behind": "si vamos perdiendo",
    "tired": "si el titular supera 60 de cansancio",
}


@dataclass(frozen=True)
class ConditionalChange:
    minute: int
    condition: str
    outgoing: str
    incoming: str

    def matches(self, minute: int, margin: int, fatigue: float) -> bool:
        return minute >= self.minute and {
            "always": True, "ahead": margin > 0, "level": margin == 0,
            "behind": margin < 0, "tired": fatigue >= 60,
        }.get(self.condition, False)

    def players(self, xi: list[Player], bench: list[Player]) -> tuple[Player, Player] | None:
        out = next((p for p in xi if p.name == self.outgoing), None)
        incoming = next((p for p in bench if p.name == self.incoming and p.available), None)
        if out is None or incoming is None or (out.position == "POR") != (incoming.position == "POR"):
            return None
        return out, incoming

    def describe(self) -> str:
        return f"Desde el minuto {self.minute}, {CONDITIONS[self.condition]}: sale {self.outgoing}, entra {self.incoming}."
