"""Stadium attendance calculation based on home-form and match importance."""

from __future__ import annotations

from typing import Any


def calculate_attendance(tournament: Any, match_idx: int) -> tuple[str, float] | None:
    """Compute (narration_text, crowd_volume_multiplier) for a match."""
    try:
        if (hasattr(tournament, "step_type") and tournament.step_type() == "unico"
                and getattr(tournament, "is_neutral", lambda: True)()):
            return (
                "El estadio está lleno hasta la bandera: es una final.",
                1.15,
            )
        home_team = tournament.pairs[match_idx][0]
        row = tournament.table[home_team.name]
        home_played = row.get("lj", 0)
        home_pts = row.get("lpts", 0)
        prior = max(0.6, min(2.2, 1.0 + (home_team.strength() - 70.0) / 10.0))
        ppg = (home_pts + prior * 2.0) / (home_played + 2.0)
        if ppg >= 1.8:
            return (
                f"El estadio está lleno. La afición de {home_team.name} no deja un solo asiento libre.",
                1.15,
            )
        if ppg >= 1.1:
            return ("El estadio está a media entrada.", 0.8)
        return (
            f"Hay poca gente: el estadio tiene una entrada baja, porque a {home_team.name} no le va bien de local.",
            0.55,
        )
    except Exception:
        return None
