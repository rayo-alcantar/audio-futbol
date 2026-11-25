"""Official competition fields shared by creation previews and the standard launcher."""

from __future__ import annotations

from audiofutbol.data.competition_loader import LIBERTADORES_SOUTH, load_registered_club_field
from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.creations import Placement, TeamDraft, team_key
from audiofutbol.domain.models import Team
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.league_hub import run_league_hub
from audiofutbol.scenes.world_cup_hub import run_world_cup_hub

NATIONAL_FIELDS = {"mundial": "Mundial", "liga": "Liga de Naciones"}


def competition_choices(kind: str) -> list[tuple[str, str]]:
    if kind == "seleccion":
        return list(NATIONAL_FIELDS.items())
    return [(key, spec.menu_label) for key, spec in CLUB_COMPETITIONS.items()] + [
        (LIBERTADORES_SOUTH, "Copa Libertadores, solo Sudamérica"),
    ]


def placement_slots(ctx: GameContext, key: str) -> dict[str, Team]:
    if key in NATIONAL_FIELDS:
        teams = sorted(ctx.national_teams, key=lambda team: -team.strength())
        size = next((n for n in (48, 32, 16, 8) if n <= len(teams)), 0)
        return {team_key(team.name): team for team in teams[:size]}
    return load_registered_club_field(ctx.paths, key)[2]


def preview_placement(ctx: GameContext, draft: TeamDraft, placement: Placement) -> None:
    allowed = dict(competition_choices(draft.kind))
    key = placement.competition
    if key not in allowed:
        raise ValueError("Esta competición ya no está disponible para el equipo.")
    if key in NATIONAL_FIELDS:
        spec, data, slots = None, None, placement_slots(ctx, key)
    else:
        spec, data, slots = load_registered_club_field(ctx.paths, key)
    if placement.replace_id not in slots:
        raise ValueError("El cupo ya no existe. Vuelve a elegir un equipo para reemplazar.")
    user = draft.as_team()
    current = slots[placement.replace_id]
    user.team_id, user.group = current.team_id, current.group
    copies = {slot: (user if slot == placement.replace_id else Team.from_dict(team.to_dict()))
              for slot, team in slots.items()}
    teams = list(copies.values())
    if len({team_key(team.name) for team in teams}) != len(teams):
        raise ValueError("Tu equipo ya está en este torneo. Elige su propio cupo para actualizar la plantilla.")
    ctx.ui.speak(f"Prueba de {allowed[key]}. No cambia las partidas oficiales.")
    if key == "mundial":
        run_world_cup_hub(ctx, WorldCup(teams, user), preview=True)
    elif key == "liga":
        run_league_hub(ctx, NationsLeague(teams, user, away_goals_rule=ctx.config.gol_visitante), preview=True)
    else:
        assert spec is not None
        run_league_hub(ctx, spec.cls(data, copies, user), preview=True)
