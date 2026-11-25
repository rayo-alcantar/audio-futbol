"""Team creation, squad editing, proposed competition places and match previews."""

from __future__ import annotations

from dataclasses import replace

from audiofutbol.data.creations import CreationLibrary, catalogue_ref, read_roster_csv, squad_from_team
from audiofutbol.domain.creations import Placement, SquadPlayer, TeamDraft, team_key
from audiofutbol.domain.formations import ROLES
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.creation_common import (
    KIND_OPTIONS, catalogue, field, file_field, number, save_edit, select, share, show_issues,
    team_summary, venue_fields,
)
from audiofutbol.scenes.creation_placements import competition_choices, placement_slots, preview_placement
from audiofutbol.scenes.customize import pick_from
from audiofutbol.scenes.friendly import play_friendly


def new_team(ctx: GameContext, library: CreationLibrary) -> TeamDraft | None:
    kind = select(ctx, "Paso 1. ¿Qué tipo de equipo vas a crear?", KIND_OPTIONS)
    if kind is None:
        return None
    start = select(ctx, "Paso 2. ¿Desde dónde quieres empezar?", (
        ("new", "Equipo nuevo"),
        ("copy", "Actualizar el plantel de un equipo del catálogo"),
    ))
    if start is None:
        return None
    if start == "copy":
        original = pick_from(ctx, "Elige el equipo que quieres actualizar", list(catalogue(ctx, kind).values()))
        if original is None:
            return None
        country = original.country or (original.name if kind == "seleccion" else "")
        if not country:
            country = field(ctx, "País del club", required=True, limit=70)
        if not country:
            return None
        stadium, city = ctx.stadiums.venue_for(original) or ("", "")
        draft = TeamDraft(
            name=original.name, kind=kind, country=country,
            stadium=stadium if city else "", city=city if stadium else "",
            original=catalogue_ref(original).key,
            players=squad_from_team(original) if original.is_real_squad else (),
        )
        if not original.is_real_squad:
            ctx.ui.speak("El equipo tenía un plantel de ejemplo. Añade los jugadores de tu aporte.")
    else:
        name = field(ctx, "Paso 3. Nombre del equipo", required=True, limit=90)
        if name is None:
            return None
        if f"catalogo:{team_key(name)}" in catalogue(ctx, kind):
            ctx.ui.speak("Ese equipo ya existe. Elige actualizarlo o usa un nombre que lo distinga.", interrupt=True)
            return None
        country = field(ctx, "Paso 4. País del equipo", name if kind == "seleccion" else "", required=True, limit=70)
        if not country:
            return None
        draft = TeamDraft(name=name, kind=kind, country=country)
    library.save(draft)
    ctx.ui.speak("Borrador creado. Añade jugadores a mano o importa un CSV en Editar plantel.")
    return draft


def _metadata(ctx: GameContext, draft: TeamDraft) -> TeamDraft:
    name = draft.name if draft.original else field(ctx, "Nombre del equipo", draft.name, required=True, limit=90)
    if name is None:
        return draft
    if not draft.original and f"catalogo:{team_key(name)}" in catalogue(ctx, draft.kind):
        ctx.ui.speak("Ese nombre pertenece a un equipo del catálogo.")
        return draft
    country = field(ctx, "País del equipo", draft.country, required=True, limit=70)
    if country is None:
        return draft
    venue = venue_fields(ctx, draft.stadium, draft.city)
    if venue is None:
        return draft
    source = field(ctx, "Fuente o nota del plantel. Opcional, sin datos privados", draft.source, limit=300)
    return replace(draft, name=name, country=country, stadium=venue[0], city=venue[1], source=source) if source is not None else draft


def _edit_player(ctx: GameContext, player: SquadPlayer | None, occupied: set[int]) -> SquadPlayer | None:
    name = field(ctx, "Nombre del jugador", player.name if player else "", required=True)
    if not name:
        return None
    default = player.number if player else next(number for number in range(1, 100) if number not in occupied)
    while True:
        jersey = number(ctx, "Dorsal", 1, 99, default)
        if jersey is None:
            return None
        if jersey not in occupied:
            break
        ctx.ui.speak("Ese dorsal ya está ocupado. Elige otro.")
        default = jersey
    group = select(ctx, "Posición", (("POR", "Portería"), ("DEF", "Defensa"), ("MED", "Mediocampo"), ("DEL", "Ataque")))
    if group is None:
        return None
    role = "POR" if group == "POR" else select(ctx, "Puesto táctico", [(code, details[0]) for code, details in ROLES.items() if details[1] == group])
    if role is None:
        return None
    overall = number(ctx, "Calidad del jugador", 30, 99, player.overall if player else 70)
    return SquadPlayer(name, jersey, role, overall) if overall is not None else None


def _player_choice(ctx: GameContext, draft: TeamDraft, prompt: str) -> int | None:
    return select(ctx, prompt, [(i, f"{p.number}. {p.name}, {ROLES[p.role][0]}, calidad {p.overall}")
                                for i, p in enumerate(draft.players)])


def _squad(ctx: GameContext, library: CreationLibrary, draft: TeamDraft) -> TeamDraft:
    while True:
        action = select(ctx, f"Plantel de {draft.name}. {len(draft.players)} jugadores", (
            ("add", "Añadir jugador"), ("edit", "Editar jugador"), ("remove", "Quitar jugador"),
            ("csv", "Importar CSV y sustituir el plantel"), ("review", "Revisar requisitos del plantel"),
        ))
        if action is None:
            return draft
        if action == "review":
            ctx.ui.reader("Revisión del plantel", draft.issues() or ["El plantel está listo para probarlo."])
            continue
        players = list(draft.players)
        if action == "csv":
            path = file_field(ctx, "csv", "Elige el CSV de este equipo")
            if path is None:
                continue
            try:
                imported = read_roster_csv(path, draft.name)
            except (OSError, ValueError) as exc:
                ctx.ui.speak(f"No pude importar el CSV. {exc}", interrupt=True)
                continue
            if players and not ctx.ui.confirm(f"¿Reemplazar los {len(players)} jugadores por los {len(imported)} del CSV?"):
                continue
            players = list(imported)
        elif action == "add":
            if len(players) >= 30:
                ctx.ui.speak("Ya tienes los 30 jugadores permitidos.")
                continue
            item = _edit_player(ctx, None, {p.number for p in players})
            if item is None:
                continue
            players.append(item)
        else:
            idx = _player_choice(ctx, draft, "Elige al jugador")
            if idx is None:
                continue
            if action == "remove":
                if not ctx.ui.confirm(f"¿Quitar a {players[idx].name} de este plantel?"):
                    continue
                players.pop(idx)
            else:
                edited = _edit_player(ctx, players[idx], {p.number for i, p in enumerate(players) if i != idx})
                if edited is None:
                    continue
                players[idx] = edited
        candidate = replace(draft, players=tuple(players))
        if not show_issues(ctx, candidate.issues(ready=False)):
            draft = save_edit(ctx, library, draft, candidate)


def _competitions(ctx: GameContext, library: CreationLibrary, draft: TeamDraft) -> TeamDraft:
    labels = dict(competition_choices(draft.kind))
    while True:
        action = select(ctx, "Dónde juega este equipo", (
            ("list", "Ver el destino del aporte"),
            ("add", "Proponer un cupo en una competición existente"),
            ("remove", "Quitar una propuesta de competición"),
        ))
        if action is None:
            return draft
        if action == "list":
            lines = ["Disponible para amistosos de prueba y para añadir a torneos creados."]
            if draft.original:
                lines.append("El aporte propone actualizar su plantilla en el catálogo, sin duplicar el equipo.")
            lines.extend(f"{labels.get(p.competition, p.competition)}: reemplazar a {p.replace_name}."
                         for p in draft.placements)
            ctx.ui.reader("Destino del equipo", lines)
        elif action == "remove":
            key = select(ctx, "¿Qué propuesta quieres quitar?", [
                (p.competition, labels.get(p.competition, p.competition)) for p in draft.placements])
            if key:
                updated = tuple(p for p in draft.placements if p.competition != key)
                draft = save_edit(ctx, library, draft, replace(draft, placements=updated))
        else:
            key = select(ctx, "Elige la competición", list(labels.items()))
            if key is None:
                continue
            slots = placement_slots(ctx, key)
            same = next((slot for slot, team in slots.items() if team_key(team.name) == team_key(draft.name)), None)
            if same is not None:
                chosen = slots[same]
            else:
                chosen = pick_from(ctx, f"{labels[key]}. ¿Qué equipo cede su cupo?", list(slots.values()))
            if chosen is None:
                continue
            if not ctx.ui.confirm(f"¿Proponer el cupo de {chosen.name}? No modifica la competición oficial."):
                continue
            slot = next(k for k, team in slots.items() if team is chosen)
            updated = tuple(p for p in draft.placements if p.competition != key) + (Placement(key, slot, chosen.name),)
            draft = save_edit(ctx, library, draft, replace(draft, placements=updated))


def _test(ctx: GameContext, library: CreationLibrary, draft: TeamDraft) -> None:
    if show_issues(ctx, draft.issues()):
        return
    choices = [(None, "Jugar un amistoso de prueba")]
    labels = dict(competition_choices(draft.kind))
    choices.extend((p, f"Probar en {labels.get(p.competition, p.competition)}") for p in draft.placements)
    mode = select(ctx, "Cómo quieres probar el equipo", [
        (index, label) for index, (_, label) in enumerate(choices)])
    if mode is None:
        return
    if placement := choices[mode][0]:
        preview_placement(ctx, draft, placement)
    else:
        user = draft.as_team()
        pool = list(catalogue(ctx, draft.kind).values())
        pool.extend(team.as_team() for team in library.custom_teams().values()
                    if team.kind == draft.kind and not team.issues())
        rivals = {team_key(team.name): team for team in pool if team_key(team.name) != team_key(draft.name)}
        rival = pick_from(ctx, "Elige un rival para la prueba", list(rivals.values()))
        if rival is not None:
            play_friendly(ctx, user, rival)


def edit_team(ctx: GameContext, library: CreationLibrary, draft: TeamDraft) -> None:
    while True:
        action = select(ctx, f"Equipo: {draft.name}. {len(draft.players)} jugadores", (
            ("squad", "Editar plantel"), ("details", "Editar datos, sede y fuente"),
            ("placements", "Elegir dónde juega"), ("review", "Revisar el equipo"),
            ("test", "Probar el equipo"), ("export", "Exportar a ZIP"),
        ))
        if action is None:
            return
        try:
            if action == "squad":
                draft = _squad(ctx, library, draft)
            elif action == "details":
                edited = _metadata(ctx, draft)
                if edited != draft:
                    draft = save_edit(ctx, library, draft, edited)
            elif action == "placements":
                draft = _competitions(ctx, library, draft)
            elif action == "review":
                ctx.ui.reader("Resumen del equipo", team_summary(draft, dict(competition_choices(draft.kind))))
            elif action == "test":
                _test(ctx, library, draft)
            elif not show_issues(ctx, draft.issues()):
                share(ctx, library, draft)
        except (OSError, ValueError) as exc:
            ctx.ui.speak(f"No se pudo completar la acción. {exc}", interrupt=True)
