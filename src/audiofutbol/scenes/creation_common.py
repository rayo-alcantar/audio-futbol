"""Accessible fields, catalogue lookup and sharing for creation scenes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence, TypeVar
import webbrowser

from audiofutbol.data.creations import CreationLibrary, catalogue_ref, downloads_folder, export_package, issue_url
from audiofutbol.domain.creations import Draft, TeamDraft
from audiofutbol.domain.models import Team
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.customize import get_club_pool
from audiofutbol.ui.text_entry import text_entry

_T = TypeVar("_T")
KIND_OPTIONS = (("club", "Club"), ("seleccion", "Selección nacional"))


def select(ctx: GameContext, title: str, choices: Sequence[tuple[_T, str]]) -> _T | None:
    if not choices:
        ctx.ui.speak("No hay opciones disponibles.")
        return None
    idx = ctx.ui.menu(title, [label for _, label in choices] + ["Volver"])
    return choices[idx][0] if idx is not None and idx < len(choices) else None


def field(ctx: GameContext, label: str, initial: str = "", *, required: bool = False, limit: int = 100) -> str | None:
    while True:
        value = text_entry(ctx.ui, label, initial, max_length=limit)
        if value is None or value or not required:
            return value
        ctx.ui.speak("Este campo es obligatorio.")


def number(ctx: GameContext, label: str, lower: int, upper: int, initial: int | None = None) -> int | None:
    current = "" if initial is None else str(initial)
    while True:
        value = field(ctx, f"{label}, de {lower} a {upper}", current, required=True, limit=3)
        if value is None:
            return None
        if value.isdecimal() and lower <= int(value) <= upper:
            return int(value)
        ctx.ui.speak(f"Escribe un número entero entre {lower} y {upper}.")
        current = value


def venue_fields(ctx: GameContext, stadium: str, city: str, label: str = "Estadio") -> tuple[str, str] | None:
    name = field(ctx, f"{label}. Déjalo vacío si no corresponde", stadium, limit=120)
    if name is None:
        return None
    if not name:
        return "", ""
    town = field(ctx, "Ciudad del estadio", city, required=True, limit=90)
    return (name, town) if town is not None else None


def catalogue(ctx: GameContext, kind: str) -> dict[str, Team]:
    teams = get_club_pool(ctx) if kind == "club" else ctx.national_teams + ctx.extra_national_teams
    return {catalogue_ref(team).key: team for team in teams}


def file_field(ctx: GameContext, extension: str, label: str) -> Path | None:
    """Offer the native file picker; a keyboard-editable path works without Tk."""
    if not ctx.window.headless:
        try:
            import tkinter as tk
            from tkinter.filedialog import askopenfilename
        except ImportError:
            pass
        else:
            try:
                root = tk.Tk()
            except tk.TclError:
                pass
            else:
                try:
                    root.withdraw()
                    root.attributes("-topmost", True)
                    chosen = askopenfilename(
                        parent=root, title=label, initialdir=str(downloads_folder()),
                        filetypes=[(extension.upper(), f"*.{extension}")],
                    )
                    return Path(chosen) if chosen else None
                except tk.TclError:
                    pass
                finally:
                    root.destroy()
    result = field(ctx, f"{label}. Escribe o pega la ruta completa", required=True, limit=1024)
    return Path(result.strip('"')) if result else None


def save_edit(ctx: GameContext, library: CreationLibrary, previous: Draft, edited: Draft) -> Draft:
    try:
        library.save(edited)
    except (OSError, ValueError) as exc:
        ctx.ui.speak(f"No se guardaron los cambios. {exc}", interrupt=True)
        return previous
    ctx.ui.speak("Borrador guardado.")
    return edited


def show_issues(ctx: GameContext, errors: list[str]) -> bool:
    if errors:
        ctx.ui.reader("Antes de continuar, revisa lo siguiente", errors)
        return True
    return False


def share(ctx: GameContext, library: CreationLibrary, draft: Draft) -> None:
    if not ctx.ui.confirm("¿Exportar a Descargas un ZIP con los datos de esta creación?"):
        return
    try:
        path = export_package(draft, library.custom_teams(), downloads_folder())
    except (OSError, ValueError) as exc:
        ctx.ui.speak(f"No se pudo exportar. {exc}", interrupt=True)
        return
    ctx.ui.speak(f"ZIP exportado a Descargas. Nombre: {path.name}.")
    while True:
        choice = select(ctx, f"Aporte exportado. {path.name}", (
            ("issue", "Abrir formulario de aporte en GitHub"),
            ("folder", "Abrir la carpeta Descargas"),
            ("location", "Leer la ruta completa del ZIP"),
        ))
        if choice is None:
            return
        if choice == "location":
            ctx.ui.reader("Ubicación del aporte", [str(path)])
        elif choice == "folder":
            try:
                if hasattr(os, "startfile"):
                    os.startfile(path.parent)
                else:
                    webbrowser.open(path.parent.as_uri())
            except OSError:
                ctx.ui.speak(f"No se abrió la carpeta. Ruta: {path.parent}.")
        elif ctx.ui.confirm("¿Abrir GitHub? El formulario tendrá el nombre del aporte. Tú adjuntas el ZIP y decides si lo publicas."):
            ctx.ui.reader("Cómo compartir tu aporte en GitHub", [
                "Inicia sesión si GitHub lo pide.",
                f"En el campo de descripción, adjunta el archivo {path.name} desde Descargas.",
                "Describe qué añadiste y cómo lo probaste. Revisa que el ZIP no contenga datos privados antes de adjuntarlo.",
                "Envía la propuesta solo cuando esté lista. El juego no la publicará.",
            ])
            try:
                opened = webbrowser.open(issue_url(draft, path.name))
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                ctx.ui.speak("No se pudo abrir GitHub. El ZIP sigue en Descargas.")
            return


def team_summary(draft: TeamDraft, competition_labels: dict[str, str]) -> list[str]:
    return [
        f"{draft.name}. {'Club' if draft.kind == 'club' else 'Selección nacional'} de {draft.country}.",
        f"Estadio: {draft.stadium}, {draft.city}." if draft.stadium else "Sin estadio definido.",
        f"Jugadores: {len(draft.players)} de un máximo de 30.",
        f"Fuente o nota: {draft.source}." if draft.source else "Sin fuente indicada.",
        *[f"Propuesta: {item.replace_name} cede su cupo en "
          f"{competition_labels.get(item.competition, item.competition)}." for item in draft.placements],
        *draft.issues(),
    ]
