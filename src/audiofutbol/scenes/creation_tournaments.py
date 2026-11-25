"""Tournament rules, incremental participant selection and isolated play tests."""

from __future__ import annotations

from dataclasses import replace
import random

from audiofutbol.data.competition_loader import load_registered_club_field
from audiofutbol.data.creations import CreationLibrary, catalogue_ref, resolve_tournament
from audiofutbol.domain.competitions.created import build_created_tournament
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.creations import FORMATS, TeamRef, TournamentDraft, playoff_sizes, team_key
from audiofutbol.domain.models import Team
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.creation_common import (
    catalogue, field, number, save_edit, select, share, show_issues, venue_fields,
)
from audiofutbol.scenes.creation_placements import competition_choices, placement_slots
from audiofutbol.scenes.customize import pick_from
from audiofutbol.scenes.league_hub import run_league_hub
from audiofutbol.scenes.world_cup_hub import run_world_cup_hub


def _rules(ctx: GameContext, draft: TournamentDraft) -> TournamentDraft | None:
    allowed = [(key, fmt.label) for key, fmt in FORMATS.items() if fmt.supports(draft.kind)]
    key = select(ctx, "Formato del torneo", allowed)
    if key is None:
        return None
    sizes = FORMATS[key].sizes
    if len(sizes) == 1:
        count = sizes[0]
        ctx.ui.speak(f"Este formato se juega con {count} equipos.")
    elif key in ("liga", "liguilla"):
        count = number(ctx, "Cantidad de participantes", sizes[0], sizes[-1], draft.team_count)
    else:
        count = select(ctx, "Cantidad de participantes", [(n, f"{n} equipos") for n in sizes])
    if count is None:
        return None
    rounds, promote, ko_legs, final_legs, away_goals = 2, 0, 1, 1, False
    if key in ("liga", "liguilla", "grupos"):
        rounds = select(ctx, "Cuántas veces se enfrentan durante la clasificación",
                        ((1, "Una vuelta"), (2, "Dos vueltas, ida y vuelta")))
        if rounds is None:
            return None
    if key == "liguilla":
        promote = select(ctx, "¿Cuántos avanzan a las eliminatorias?",
                         [(size, f"Los {size} primeros") for size in playoff_sizes(count)])
        if promote is None:
            return None
    if key in ("liguilla", "grupos", "eliminacion"):
        if count > 2 and (key != "liguilla" or promote > 2):
            ko_legs = select(ctx, "Cruces antes de la final",
                             ((1, "Partido único"), (2, "Ida y vuelta")))
            if ko_legs is None:
                return None
        final_legs = select(ctx, "Formato de la final", ((1, "Partido único"), (2, "Ida y vuelta")))
        if final_legs is None:
            return None
    if ko_legs == 2 or final_legs == 2 or key == "naciones":
        answer = select(ctx, "Desempate en cruces de ida y vuelta", (
            (False, "Sin gol de visitante; si sigue el empate, tiempo extra y penales"),
            (True, "Desempata primero el gol de visitante"),
        ))
        if answer is None:
            return None
        away_goals = answer
    stadium, city = draft.stadium, draft.city
    can_be_neutral = key == "fase_uefa" or key in ("liguilla", "grupos", "eliminacion") and final_legs == 1
    if can_be_neutral:
        fallback = "Sede neutral de la final. Vacío para usar la sede del formato" if key == "fase_uefa" else "Sede neutral de la final. Vacío para jugar en casa del equipo local"
        venue = venue_fields(ctx, stadium, city, fallback)
        if venue is None:
            return None
        stadium, city = venue
    else:
        stadium, city = "", ""
    teams = draft.teams
    if len(teams) > count:
        if not ctx.ui.confirm(f"¿Conservar solo los primeros {count} participantes?"):
            return None
        teams = teams[:count]
    return replace(draft, format=key, team_count=count, rounds=rounds, advance=promote,
                   knockout_legs=ko_legs, final_legs=final_legs, away_goals=away_goals,
                   stadium=stadium, city=city, teams=teams)


def new_tournament(ctx: GameContext, library: CreationLibrary) -> TournamentDraft | None:
    kind = select(ctx, "Paso 1. ¿Quiénes participan en tu torneo?", (
        ("club", "Clubes"), ("seleccion", "Selecciones nacionales"),
    ))
    if kind is None:
        return None
    name = field(ctx, "Paso 2. Nombre del torneo", required=True, limit=90)
    if name is None:
        return None
    draft = _rules(ctx, TournamentDraft(name=name, kind=kind, format="liga", team_count=8))
    if draft is None:
        return None
    library.save(draft)
    ctx.ui.speak("Borrador creado. Elige los participantes y después podrás probar el torneo.")
    return draft


def _circle(ctx: GameContext, library: CreationLibrary, draft: TournamentDraft) -> dict[str, tuple[TeamRef, Team]]:
    choices = {key: (catalogue_ref(team), team) for key, team in catalogue(ctx, draft.kind).items()}
    for key, custom in library.custom_teams().items():
        if custom.kind == draft.kind and not custom.issues():
            choices[key] = (custom.ref, custom.as_team())
    return choices


def _entrant(ctx: GameContext, pool: dict[str, tuple[TeamRef, Team]]) -> TeamRef | None:
    entries = list(pool.values())
    if all(any(ref.key.startswith(prefix) for ref, _ in entries) for prefix in ("catalogo:", "borrador:")):
        origin = select(ctx, "¿De dónde quieres añadir el equipo?", (
            ("catalogo:", "Catálogo del juego"), ("borrador:", "Mis planteles listos"),
        ))
        if origin is None:
            return None
        entries = [(ref, team) for ref, team in entries if ref.key.startswith(origin)]
    chosen = pick_from(ctx, "Elige un participante", [team for _, team in entries])
    return next((ref for ref, team in entries if team is chosen), None)


def _template_ref(ctx: GameContext, draft: TournamentDraft) -> tuple[TeamRef, ...] | None:
    key = select(ctx, "¿De qué competición quieres tomar los participantes?", competition_choices(draft.kind))
    if key is None:
        return None
    slots = list(placement_slots(ctx, key).values())
    if len(slots) != draft.team_count:
        ctx.ui.speak(f"Esa competición tiene {len(slots)} equipos y tu formato requiere {draft.team_count}. Puedes añadirlos uno por uno.")
        return None
    if not ctx.ui.confirm(f"¿Usar esos {len(slots)} equipos en lugar de la lista actual?"):
        return None
    return tuple(catalogue_ref(team) for team in slots)


def _participants(ctx: GameContext, library: CreationLibrary, draft: TournamentDraft) -> TournamentDraft:
    while True:
        action = select(ctx, f"Participantes de {draft.name}. {len(draft.teams)} de {draft.team_count}", (
            ("add", "Añadir equipo"), ("swap", "Reemplazar equipo"), ("remove", "Quitar equipo"),
            ("fill", "Completar los cupos libres"), ("template", "Usar participantes de otra competición"),
            ("list", "Escuchar la lista"),
        ))
        if action is None:
            return draft
        if action == "list":
            ctx.ui.reader("Participantes", [team.name for team in draft.teams] or ["Todavía no hay equipos."])
            continue
        chosen = list(draft.teams)
        if action == "template":
            replacement = _template_ref(ctx, draft)
            if replacement is None:
                continue
            chosen = list(replacement)
        else:
            idx = None
            if action in ("swap", "remove"):
                idx = select(ctx, "Elige el cupo", [(i, ref.name) for i, ref in enumerate(chosen)])
                if idx is None:
                    continue
                old = chosen.pop(idx)
                if action == "remove":
                    if not ctx.ui.confirm(f"¿Quitar a {old.name}?"):
                        continue
                    draft = save_edit(ctx, library, draft, replace(draft, teams=tuple(chosen)))
                    continue
            missing = draft.team_count - len(chosen)
            if missing < 1:
                ctx.ui.speak("La lista ya está completa. Usa Reemplazar equipo para cambiar un cupo.")
                continue
            pool = _circle(ctx, library, draft)
            occupied = {team_key(pool[ref.key][1].name if ref.key in pool else ref.name) for ref in chosen}
            free = {key: item for key, item in pool.items() if team_key(item[1].name) not in occupied}
            if action == "fill":
                mode = select(ctx, "Cómo completar los cupos", (("quality", "Con los mejores del catálogo"), ("random", "Al azar, desde el catálogo")))
                if mode is None:
                    continue
                official = [item for key, item in free.items() if key.startswith("catalogo:")]
                if mode == "quality":
                    official.sort(key=lambda item: -item[1].strength())
                else:
                    random.shuffle(official)
                chosen.extend(ref for ref, _ in official[:missing])
                if len(chosen) < draft.team_count:
                    ctx.ui.speak("No hay suficientes equipos del catálogo. Puedes añadir tus propios planteles.")
            else:
                entry = _entrant(ctx, free)
                if entry is None:
                    continue
                chosen.insert(idx if idx is not None else len(chosen), entry)
        draft = save_edit(ctx, library, draft, replace(draft, teams=tuple(chosen)))


def _summary(draft: TournamentDraft) -> list[str]:
    lines = [draft.name, FORMATS[draft.format].label,
             f"{len(draft.teams)} de {draft.team_count} participantes."]
    if draft.format in ("liga", "liguilla", "grupos"):
        lines.append(f"Fase de clasificación a {draft.rounds} vuelta{'s' if draft.rounds == 2 else ''}.")
    if draft.format == "liguilla":
        lines.append(f"Avanzan los {draft.advance} primeros.")
    if draft.format == "grupos":
        lines.append("Avanzan los dos primeros de cada grupo de cuatro.")
    if draft.format in ("liguilla", "grupos", "eliminacion"):
        lines.append(f"Partidos por cruce: {draft.knockout_legs}. Partidos de la final: {draft.final_legs}.")
    if draft.away_goals:
        lines.append("Se aplica el gol de visitante en los cruces a ida y vuelta.")
    if draft.stadium:
        lines.append(f"Sede neutral: {draft.stadium}, {draft.city}.")
    if draft.source:
        lines.append(f"Fuente o nota: {draft.source}.")
    return lines + draft.issues() + [ref.name for ref in draft.teams]


def _test(ctx: GameContext, draft: TournamentDraft, teams: list[Team]) -> None:
    player = ctx.ui.choose_team("¿Qué equipo quieres dirigir en la prueba?", teams)
    if player is None:
        return
    uefa = load_registered_club_field(ctx.paths, "champions")[1] if draft.format == "fase_uefa" else None
    engine = build_created_tournament(draft, teams, next(i for i, t in enumerate(teams) if t is player),
                                      uefa_schedule=uefa)
    ctx.ui.speak("Prueba preparada. Puedes jugar o simular. No se cambiarán tus partidas guardadas.")
    if isinstance(engine, WorldCup):
        run_world_cup_hub(ctx, engine, preview=True)
    else:
        run_league_hub(ctx, engine, preview=True)


def edit_tournament(ctx: GameContext, library: CreationLibrary, draft: TournamentDraft) -> None:
    while True:
        action = select(ctx, f"Torneo: {draft.name}. {len(draft.teams)} de {draft.team_count} participantes", (
            ("teams", "Elegir participantes"), ("rules", "Editar formato y reglas"),
            ("details", "Editar nombre y fuente"), ("review", "Revisar el torneo"),
            ("test", "Probar el torneo"), ("export", "Exportar a ZIP"),
        ))
        if action is None:
            return
        try:
            if action == "teams":
                draft = _participants(ctx, library, draft)
            elif action == "rules":
                updated = _rules(ctx, draft)
                if updated is not None:
                    draft = save_edit(ctx, library, draft, updated)
            elif action == "details":
                name = field(ctx, "Nombre del torneo", draft.name, required=True, limit=90)
                if name is not None:
                    source = field(ctx, "Fuente o nota del torneo. Opcional, sin datos privados", draft.source, limit=300)
                    if source is not None:
                        draft = save_edit(ctx, library, draft, replace(draft, name=name, source=source))
            elif action == "review":
                ctx.ui.reader("Resumen del torneo", _summary(draft))
            elif not show_issues(ctx, draft.issues()):
                teams = resolve_tournament(draft, catalogue(ctx, draft.kind), library.custom_teams())
                if action == "test":
                    _test(ctx, draft, teams)
                else:
                    share(ctx, library, draft)
        except (OSError, ValueError, KeyError) as exc:
            ctx.ui.speak(f"No se pudo completar la acción. {exc}", interrupt=True)
