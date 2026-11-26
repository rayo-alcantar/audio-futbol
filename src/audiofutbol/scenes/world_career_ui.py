"""Accessible world league picker, coach profile and job market."""

from __future__ import annotations

from collections.abc import Callable

from audiofutbol.data.career_catalog import WorldCatalogue, load_world_catalogue
from audiofutbol.domain.competitions.career_core import career_date
from audiofutbol.domain.competitions.career_squad import club_key
from audiofutbol.domain.competitions.career_world_catalog import WorldLeagueSpec
from audiofutbol.domain.competitions.world_career import WorldCareer, WorldSeasonRecord
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.career_management import money, open_menu
from audiofutbol.ui.text_entry import text_entry


def _pick(ctx: GameContext, title: str, items: list[str]) -> int | None:
    start = 0
    while items:
        page = items[start:start + 9]
        nav = []
        if start:
            nav.append(("Página anterior", start - 9))
        if start + len(page) < len(items):
            nav.append(("Página siguiente", start + 9))
        pick = ctx.ui.menu(title, page + [text for text, _ in nav] + ["Volver"])
        if pick is None or pick == len(page) + len(nav):
            return None
        if pick < len(page):
            return start + pick
        start = nav[pick - len(page)][1]
    return None


def choose_world_league(ctx: GameContext, leagues: dict[str, WorldLeagueSpec]) -> str | None:
    regions = sorted({spec.region for spec in leagues.values()}, key=club_key)
    while (ri := _pick(ctx, "Elige una región", regions)) is not None:
        selected = [s for s in leagues.values() if s.region == regions[ri]]
        countries = sorted({s.country for s in selected}, key=club_key)
        while (ci := _pick(ctx, f"{regions[ri]}. Elige el país", countries)) is not None:
            options = [s for s in selected if s.country == countries[ci]]
            li = _pick(ctx, f"{countries[ci]}. Elige la división", [
                f"{s.title}. {len(s.club_names)} clubes" + (f". Edición de referencia {s.edition}" if s.edition else "")
                for s in options
            ])
            if li is not None:
                return options[li].key
    return None


def _choose_initial_club(ctx: GameContext, catalogue: WorldCatalogue) -> tuple[str, str] | None:
    options = ["Elegir por región y liga", "Buscar un club por nombre", "Volver"]
    while (mode := ctx.ui.menu("¿Cómo quieres elegir tu club?", options)) in (0, 1):
        if mode == 0:
            if key := choose_world_league(ctx, catalogue.leagues):
                teams = sorted(catalogue.selectable(key), key=lambda t: club_key(t.name))
                club = ctx.ui.choose_team("Elige el club que dirigirás", teams)
                if club is not None:
                    return key, club.name
            continue
        query = text_entry(ctx.ui, "Escribe parte del nombre del club", max_length=55)
        if not query:
            continue
        matches = sorted((club, spec.title, key)
                         for key, spec in catalogue.leagues.items() for club in spec.club_names
                         if club_key(query) in club_key(club))
        if not matches:
            ctx.ui.speak("No encontré clubes con ese nombre.")
            continue
        choice = _pick(ctx, f"Búsqueda de clubes. {len(matches)} resultados",
                       [f"{club}. {league}" for club, league, _ in matches])
        if choice is not None:
            club, _, key = matches[choice]
            return key, club
    return None


def choose_new_world_career(ctx: GameContext) -> WorldCareer | None:
    ctx.ui.speak("Cargando el catálogo mundial de clubes.")
    try:
        catalogue = load_world_catalogue(ctx.paths)
        choice = _choose_initial_club(ctx, catalogue)
        if choice is None:
            return None
        division, club = choice
        name = text_entry(ctx.ui, "Nombre del DT. Puedes dejarlo vacío", max_length=50)
        if name is None:
            return None
        return WorldCareer.start(catalogue.leagues, catalogue.links, catalogue.stock, catalogue.rosters,
                                 division, club, name)
    except (ValueError, KeyError, TypeError) as exc:
        ctx.ui.speak(f"No se pudo iniciar la carrera mundial. {exc}")
        return None


def world_record_line(record: WorldSeasonRecord) -> str:
    result = "Campeón. " if record.champion else ""
    if not record.manager_employed:
        context = "Sin DT al cierre."
    else:
        context = "Objetivo de la directiva " + ("cumplido." if record.place <= record.objective else "no cumplido.")
    return (f"{record.year}. {record.club}, {record.league}. Puesto {record.place}, "
            f"{record.league_points} puntos de liga. {result}{context}")


def read_world_tables(ctx: GameContext, career: WorldCareer) -> None:
    if not career.world_tables:
        ctx.ui.speak("Habrá tablas de las otras ligas después de cerrar el primer año.")
        return
    if key := choose_world_league(ctx, career.leagues):
        ctx.ui.reader(f"{career.leagues[key].title}. Temporada {career.year - 1}", [
            f"{place}. {name}, {points} puntos"
            for place, (name, points) in enumerate(career.world_tables.get(key, []), 1)
        ] or ["No hay datos de la temporada anterior."])


def _profile(ctx: GameContext, career: WorldCareer) -> None:
    coach = career.coach
    employment = f"Dirige a {career.managed}." if career.employed else "Actualmente sin club."
    ctx.ui.reader("Perfil del DT", [
        f"{coach.name}. Reputación: {coach.reputation}. {coach.points} puntos de entrenador.",
        employment,
        f"{coach.wins} victorias, {coach.draws} empates, {coach.losses} derrotas. {coach.titles} títulos.",
        *[f"{career_date(e.year, e.day)}. {e.event}: {e.club}, {e.league}."
          for e in reversed(coach.appointments)],
    ])


def _jobs(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    if not career.finished:
        offers = career.job_offers(career.division)
    else:
        key = choose_world_league(ctx, career.leagues)
        if key is None:
            return
        offers = career.job_offers(key)
    if not offers:
        ctx.ui.speak(
            "No hay ofertas para tu reputación en esta liga. Busca en otra antes de empezar la temporada."
            if career.finished else
            "No hay vacantes disponibles. Avanza el calendario. Tras una salida, pueden aparecer desde los 14 días."
        )
        return
    pick = _pick(ctx, "Ofertas para el DT", [
        f"{offer.club}. Presupuesto disponible: "
        f"{money(career.market.club_funds[club_key(offer.club)], career.currency)}"
        for offer in offers
    ])
    if pick is None:
        return
    offer = offers[pick]
    when = " al iniciar la temporada siguiente" if career.finished else ""
    if not ctx.ui.confirm(f"¿Aceptar el puesto en {offer.club}{when}? El presupuesto del club anterior no se traslada."):
        return
    try:
        career.accept_job(offer)
    except (ValueError, KeyError) as exc:
        ctx.ui.speak(f"No se pudo cambiar de club. {exc}")
        return
    ctx.ui.speak(f"Contrato aceptado. Ahora diriges a {career.managed} en {career.league.TITLE}.")
    changed()


def manager_actions(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    def resign() -> None:
        if ctx.ui.confirm(f"¿Dimitir de {career.managed}? Conservas tu perfil como DT, pero no controlarás al club."):
            career.resign()
            ctx.ui.speak("Dimisión confirmada. Ahora puedes avanzar el calendario y consultar ofertas.")
            changed()

    cursor = 0
    while True:
        actions = [("Consultar mi perfil y trayectoria", lambda: _profile(ctx, career))]
        if not career.employed or career.finished:
            actions.append(("Buscar ofertas de trabajo", lambda: _jobs(ctx, career, changed)))
        if career.employed:
            actions.append(("Dimitir del cargo", resign))
        label = career.club.name if career.employed else "Sin club"
        index = open_menu(ctx, f"Director técnico. {career.coach.name}. {label}. "
                               f"Reputación: {career.coach.reputation}, {career.coach.points} puntos", actions, cursor)
        if index is None:
            return
        cursor = index
