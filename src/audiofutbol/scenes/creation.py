"""Creation tools entry point, local drafts and supported ZIP import."""

from __future__ import annotations

from audiofutbol.data.creations import CreationLibrary
from audiofutbol.domain.creations import Draft, TeamDraft
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.creation_common import file_field, select
from audiofutbol.scenes.creation_teams import edit_team, new_team
from audiofutbol.scenes.creation_tournaments import edit_tournament, new_tournament


def _open(ctx: GameContext, library: CreationLibrary, draft: Draft) -> None:
    if isinstance(draft, TeamDraft):
        edit_team(ctx, library, draft)
    else:
        edit_tournament(ctx, library, draft)


def _choose_draft(ctx: GameContext, library: CreationLibrary) -> Draft | None:
    return select(ctx, "Elige un borrador", [
        (draft, f"{draft.name}. {'Equipo' if isinstance(draft, TeamDraft) else 'Torneo'}")
        for draft in reversed(list(library.drafts.values()))
    ])


def run_creation_menu(ctx: GameContext) -> None:
    try:
        library = CreationLibrary(ctx.paths.saves_dir / "creaciones" / "biblioteca.json")
    except (OSError, ValueError) as exc:
        ctx.ui.speak(f"No se pudo leer tu biblioteca de creaciones. No se modificó. {exc}", interrupt=True)
        return
    while True:
        choice = select(ctx, "Crear. Los borradores se guardan al confirmar cada cambio", (
            ("team", "Equipo"), ("tournament", "Torneo"),
            ("draft", "Continuar un borrador"), ("import", "Importar un aporte ZIP"),
            ("remove", "Borrar un borrador"), ("help", "Cómo funciona Crear"),
        ))
        if choice is None:
            return
        try:
            draft = None
            if choice == "team":
                draft = new_team(ctx, library)
            elif choice == "tournament":
                draft = new_tournament(ctx, library)
            elif choice == "draft":
                draft = _choose_draft(ctx, library)
            elif choice == "import":
                path = file_field(ctx, "zip", "Elige el ZIP del aporte")
                if path is not None:
                    draft = library.import_package(path)
                    ctx.ui.speak("Aporte importado como borrador nuevo. No cambió el catálogo oficial.")
            elif choice == "remove":
                selected = _choose_draft(ctx, library)
                if selected is not None and ctx.ui.confirm(f"¿Borrar el borrador {selected.name}?"):
                    library.remove(selected)
                    ctx.ui.speak("Borrador borrado. Los ZIP ya exportados siguen en su carpeta.")
            else:
                ctx.ui.reader("Cómo funciona Crear", [
                    "Elige Equipo para empezar un plantel nuevo o actualizar una plantilla oficial sin modificarla.",
                    "Puedes añadir jugadores uno por uno o importar el CSV de un solo equipo.",
                    "En Elegir dónde juega puedes proponer un cupo para probarlo en una competición existente.",
                    "Elige Torneo para definir las reglas y seleccionar equipos del catálogo o de tus borradores listos.",
                    "Prueba el resultado en un partido o simula un torneo. Las pruebas no tocan las partidas oficiales.",
                    "Al exportar se crea un ZIP en Descargas. Puedes compartirlo o abrir el formulario de GitHub.",
                ])
            if draft is not None:
                _open(ctx, library, draft)
        except (OSError, ValueError) as exc:
            ctx.ui.speak(f"No se pudo completar la acción. {exc}", interrupt=True)
