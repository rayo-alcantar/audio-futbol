"""Manager career navigation and adapters for catalog, fixtures and save storage."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

import pygame

from audiofutbol.data.competition_loader import LIBERTADORES_SOUTH, load_registered_club_field
from audiofutbol.domain.competitions.brazil_career import BrazilianCareer, ContinentalField
from audiofutbol.domain.competitions.career_brazil_rules import CONTINENTAL_TYPES, LEAGUES
from audiofutbol.domain.competitions.career_core import ManagerCareer, SeasonRecord, career_date
from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS
from audiofutbol.domain.competitions.world_career import WorldCareer, WorldSeasonRecord
from audiofutbol.domain.models import format_result_text
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.career_management import MenuAction, _edit_tactics, money, open_menu, run_club_menu
from audiofutbol.scenes.match_scene import run_tournament_match
from audiofutbol.scenes.world_career_ui import choose_new_world_career, manager_actions, read_world_tables, world_record_line
from audiofutbol.scenes.world_market_scene import finances, transfer_wait
from audiofutbol.scenes.world_match_ui import read_match_logs
from audiofutbol.ui.widgets import AudioUI


def start_brazil_career(ctx: GameContext) -> None:
    choice = ctx.ui.menu("Carrera de DT en Brasil. Elige tu división inicial",
                         [CLUB_COMPETITIONS[key].menu_label for key in LEAGUES] + ["Volver"])
    if choice is None or choice == len(LEAGUES):
        return
    try:
        fields = [list(load_registered_club_field(ctx.paths, key)[2].values()) for key in LEAGUES]
        club = ctx.ui.choose_team("Elige el club que dirigirás", sorted(fields[choice], key=lambda t: t.name))
        if club is None:
            return
        career = BrazilianCareer.start(*fields, club.name)
    except (ValueError, KeyError, TypeError) as exc:
        ctx.ui.speak(f"No se pudo iniciar la carrera de Brasil. {exc}")
        return
    _open_new_career(ctx, career)


def start_world_career(ctx: GameContext) -> None:
    career = choose_new_world_career(ctx)
    if career is not None:
        _open_new_career(ctx, career)


def _open_new_career(ctx: GameContext, career: ManagerCareer) -> None:
    if ctx.saves.exists(career.KEY) and not ctx.ui.confirm(
        f"Ya existe una partida de {career.TITLE}. ¿Reemplazarla por esta nueva carrera?"
    ):
        return
    if not ctx.saves.save(career.KEY, career):
        ctx.ui.speak("No se pudo crear el guardado. La carrera anterior no se reemplazó.")
        return
    ctx.audio.play_sfx("sorteo")
    ctx.ui.speak(f"Empieza tu carrera con {career.club.name}. Se guardará después de cada cambio confirmado.")
    if isinstance(career, WorldCareer):
        ctx.ui.speak(f"La directiva te asignó {money(career.market.balance, career.currency)} de presupuesto.")
    run_career_hub(ctx, career)


def continue_brazil_career(ctx: GameContext) -> None:
    career = ctx.saves.load(BrazilianCareer.KEY)
    if not isinstance(career, BrazilianCareer):
        ctx.ui.speak("No se pudo cargar la carrera guardada de Brasil.")
        return
    run_career_hub(ctx, career)


def continue_world_career(ctx: GameContext) -> None:
    career = ctx.saves.load(WorldCareer.KEY)
    if not isinstance(career, WorldCareer):
        ctx.ui.speak("No se pudo cargar la carrera mundial guardada.")
        return
    run_career_hub(ctx, career)


def _continental_field(ctx: GameContext, key: str) -> ContinentalField:
    primary = LIBERTADORES_SOUTH if key == "libertadores" else key
    backup = "sudamericana" if key == "libertadores" else LIBERTADORES_SOUTH
    _, data, first = load_registered_club_field(ctx.paths, primary)
    _, _, second = load_registered_club_field(ctx.paths, backup)
    return data, [*first.values(), *second.values()]


def _record_line(record: SeasonRecord | WorldSeasonRecord) -> str:
    if isinstance(record, WorldSeasonRecord):
        return world_record_line(record)
    division = CLUB_COMPETITIONS[record.division].title
    next_division = CLUB_COMPETITIONS[record.next_division].title
    status = "cumplido" if record.place <= record.objective else "no cumplido"
    continental = CONTINENTAL_TYPES[record.qualified_for].TITLE if record.qualified_for else "sin copa continental"
    return (
        f"{record.year}, {division}, puesto {record.place}. Objetivo {status}. "
        f"Próxima temporada: {next_division}, {continental}. "
        f"Títulos: {', '.join(record.trophies) if record.trophies else 'ninguno'}."
    )


def _calendar(ctx: GameContext, career: ManagerCareer) -> None:
    if not career.employed:
        ctx.ui.speak("No tienes partidos propios mientras estés sin club.")
        return
    league = career.league
    upcoming = []
    for round_ in career.agenda():
        if round_.user_index is None:
            continue
        upcoming.append((round_.day, round_.fixture_text()))
    if league.champion is None and league.step_type() == "liga":
        for index in range(league.step_idx + 1, min(league.step_idx + 7, league.rounds_count)):
            for home, away in league.schedule[index]:
                if home is league.user_team or away is league.user_team:
                    local = home is league.user_team
                    side = "de local" if local else "de visitante"
                    upcoming.append((career.round_day(league, index),
                                     f"Jornada {index + 1}, contra {(away if local else home).name}, {side}"))
                    break
    ctx.ui.reader("Próximos partidos confirmados", [
        f"{career_date(career.year, day)}. {text}." for day, text in sorted(upcoming)
    ] or ["No hay más partidos confirmados todavía."])


def _advance_to_next_window(ctx: GameContext, career: ManagerCareer) -> bool:
    if not ctx.ui.confirm(
        "¿Simular los partidos hasta la próxima ventana de fichajes o el cierre de temporada?"
    ):
        return False
    ctx.ui.speak("Simulando el calendario. Pulsa Escape para detenerte después de la ronda actual.")
    opening_window, starting_day = career.window, career.day
    rounds = 0
    settings = ctx.match_settings()
    employed = career.employed
    while agenda := career.agenda():
        fixture = agenda[0]
        if isinstance(career, WorldCareer):
            if _transfer_pause(ctx, career, fixture.day):
                return True
            if fixture.user_index is not None and (alerts := career.lineup_alerts(fixture)):
                ctx.ui.speak(f"Avance detenido. Hay {len(alerts)} avisos sobre tu once. "
                             "Selecciona el próximo partido para revisar el cansancio y las bajas.")
                return rounds > 0 or starting_day != career.day
        career.prepare_round(fixture)
        if career.window and career.window != opening_window:
            break
        career.finish_round(fixture, settings)
        rounds += 1
        if employed and not career.employed:
            ctx.ui.speak("La directiva te destituyó. Consulta tu perfil y las ofertas en Oficina.")
            return True
        if rounds % 6 == 0:
            ctx.ui.speak(f"{rounds} rondas simuladas. {career_date(career.year, career.day)}.")
        if ctx.window.wait_or_skip_action(20) == "escape":
            break
    if career.finished:
        ctx.ui.speak("Terminó la temporada. Puedes consultar el balance o iniciar la siguiente.")
    elif career.window and career.window != opening_window:
        ctx.ui.speak(f"Abrió la ventana de fichajes {career.window}. Todavía no se jugó el próximo partido.")
    else:
        ctx.ui.speak("Simulación detenida. Puedes retomar el calendario desde aquí.")
    return rounds > 0 or starting_day != career.day


def _transfer_pause(ctx: GameContext, career: WorldCareer, target: int) -> bool:
    """Let the player react before a date jump can expire an actionable offer."""
    while career.day < target:
        fresh_id = career.negotiations.next_id
        previous = {talk.id: talk.state for talk in career.negotiations.for_club(career.managed)}
        if not career.wait_days(1):
            break
        if career.negotiations.next_id != fresh_id or any(
            previous.get(talk.id) == "pending" and talk.state in ("counter", "agreed", "rejected")
            for talk in career.negotiations.for_club(career.managed)
        ):
            ctx.ui.speak("El calendario se detuvo por novedades del mercado. " + career.inbox[-1].text)
            return True
    return False


def _competition_menu(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    def results() -> None:
        lines = [
            f"{tournament.TITLE}. {phase}. {format_result_text(home, away, ga, gb, pen)}"
            for tournament in career.draws.values() if tournament.user_team.name == career.managed
            for phase, home, away, ga, gb, pen in reversed(tournament.history)
            if home is tournament.user_team or away is tournament.user_team
        ]
        ctx.ui.reader("Resultados del club actual o más reciente", lines or ["Aún no hay resultados del club."])

    def table() -> None:
        if isinstance(career, WorldCareer):
            ctx.ui.reader(career.league.TITLE, career.league.table_lines())
            return
        leagues = [career.draws[key] for key in LEAGUES]
        choice = ctx.ui.menu("Elige la división", [t.TITLE for t in leagues] + ["Volver"],
                             initial_index=LEAGUES.index(career.division))
        if choice is not None and choice < len(leagues):
            league = leagues[choice]
            ctx.ui.reader(league.TITLE, league.table_lines())

    def fast_forward() -> None:
        if _advance_to_next_window(ctx, career):
            changed()

    cursor = 0
    while True:
        actions: list[MenuAction] = [
            ("Próximos partidos", lambda: _calendar(ctx, career)),
            ("Clasificaciones", table),
            ("Resultados del club", results),
            ("Goleadores de la liga", lambda: ctx.ui.reader(
                "Goleadores", career.league.top_scorers(15) or ["Aún no hay goles registrados."])),
        ]
        if not career.finished:
            actions.append(("Simular hasta la próxima ventana de fichajes", fast_forward))
        if isinstance(career, WorldCareer):
            actions.append(("Mundo del fútbol: tablas de la temporada anterior", lambda: read_world_tables(ctx, career)))
            actions.insert(1, ("Bitácoras: figura y estadísticas", lambda: read_match_logs(ctx, career)))
        index = open_menu(ctx, "Temporada", actions, cursor)
        if index is None:
            return
        cursor = index


def _office(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    def messages() -> None:
        ctx.ui.reader("Mensajes del club", [
            f"{career_date(m.year, m.day)}. {m.text}" for m in reversed(career.inbox)
        ] or ["No hay mensajes."])

    def mark_read() -> None:
        if career.unread:
            career.unread = 0
            ctx.ui.speak("Todos los mensajes se marcaron como leídos.")
            changed()
        else:
            ctx.ui.speak("No hay mensajes sin leer.")

    def board() -> None:
        place, row = career.league.user_position()
        position = f"Puesto {place} con {row['pts']} puntos en {row['pj']} partidos."
        if not row["pj"]:
            position = "La liga aún no ha empezado."
        lines = [f"Objetivo de la directiva: terminar entre los {career.objective} primeros.", position]
        if isinstance(career, WorldCareer):
            lines.insert(1, f"Confianza de la directiva: {career.coach.confidence} de 100.")
        if career.finished:
            lines.append(_record_line(career.season_record()))
        ctx.ui.reader("Directiva y objetivo", lines)

    cursor = 0
    while True:
        actions: list[MenuAction] = [
            ("Leer mensajes del club", messages),
            ("Marcar todos como leídos", mark_read),
            ("Historial de temporadas", lambda: ctx.ui.reader(
                "Historial", [_record_line(r) for r in reversed(
                    career.closed_seasons if isinstance(career, WorldCareer) else career.history
                )] or ["Aún no hay temporadas cerradas."])),
        ]
        if career.employed:
            actions.insert(2, ("Objetivo de la directiva", board))
        if isinstance(career, WorldCareer):
            actions.insert(0, ("Director técnico: perfil y ofertas", lambda: manager_actions(ctx, career, changed)))
        index = open_menu(ctx, f"Oficina. Mensajes sin leer: {career.unread}", actions, cursor)
        if index is None:
            return
        cursor = index


def run_career_hub(ctx: GameContext, career: ManagerCareer) -> None:
    def balance() -> None:
        text = (f"Presupuesto disponible: {money(career.market.balance, career.currency)}."
                if career.employed else "No tienes presupuesto de club mientras estés sin equipo.")
        ctx.ui.speak(text, interrupt=True)

    scope = ctx.ui.navigation_shortcuts({pygame.K_d: balance}) if isinstance(ctx.ui, AudioUI) else nullcontext()
    with scope:
        _run_career_hub(ctx, career)


def _run_career_hub(ctx: GameContext, career: ManagerCareer) -> None:
    unsaved = False

    def save() -> None:
        nonlocal unsaved
        unsaved = not ctx.saves.save(career.KEY, career)
        if unsaved:
            ctx.ui.speak("No se pudo guardar. Los cambios siguen en memoria. Usa Guardar ahora para reintentar.")

    def save_now() -> None:
        save()
        if not unsaved:
            ctx.ui.speak("Carrera guardada.")

    def advance(simulate: bool) -> None:
        settings = ctx.match_settings()
        agenda = career.agenda()
        if not agenda:
            return
        employed = career.employed
        fixture = agenda[0]
        if isinstance(career, WorldCareer):
            if _transfer_pause(ctx, career, fixture.day):
                save()
                return
            if fixture.user_index is not None:
                while alerts := career.lineup_alerts(fixture):
                    choice = ctx.ui.menu(
                        f"Aviso antes del partido. {len(alerts)} titulares con cansancio o lesión",
                        ["Editar el once", "Leer avisos", "Continuar con los jugadores disponibles", "Volver"],
                    )
                    if choice == 0:
                        _edit_tactics(ctx, career, save)
                    elif choice == 1:
                        ctx.ui.reader("Avisos de plantilla", alerts)
                    elif choice == 2:
                        break
                    else:
                        save()
                        return
        career.prepare_round(fixture)
        uses_full_match = fixture.user_index is not None and (not simulate or not isinstance(career, WorldCareer))
        if uses_full_match:
            scope = ctx.ui.navigation_shortcuts({}) if isinstance(ctx.ui, AudioUI) else nullcontext()
            with scope:
                if isinstance(career, WorldCareer):
                    draw = fixture.tournament
                    home, away = draw.pairs[fixture.user_index]
                    sides = (draw.user_team, away if home is draw.user_team else home)
                    played = run_tournament_match(ctx, draw, simulate=simulate,
                                                  initial_fatigue=career.health_for_fixture(*sides),
                                                  planned_changes=career.changes)
                    if played is not None:
                        career.record_match(draw, sides, played, simulated=False)
                else:
                    run_tournament_match(ctx, fixture.tournament, simulate=simulate)
        elif fixture.user_index is None and employed:
            ctx.ui.speak("Avanzando el calendario hasta el próximo partido de tu club.")
        elif not employed:
            ctx.ui.speak("Simulando una jornada sin club.")
        while True:
            last_log = career.match_logs[-1:] if isinstance(career, WorldCareer) else []
            messages = career.finish_round(fixture, settings)
            for message in messages[1:] if uses_full_match else messages:
                ctx.ui.speak(message)
            if isinstance(career, WorldCareer) and not uses_full_match and career.match_logs[-1:] != last_log:
                log = career.match_logs[-1]
                ctx.ui.speak(f"{log.takeaway} {log.mvp} Puedes leer el detalle en Temporada, Bitácoras.")
            uses_full_match = False
            agenda = career.agenda()
            if employed and not career.employed:
                ctx.ui.speak("La directiva te destituyó. Consulta tu perfil y las ofertas en Oficina.")
            if not career.employed or not agenda or agenda[0].user_index is not None:
                break
            fixture = agenda[0]
            if isinstance(career, WorldCareer) and _transfer_pause(ctx, career, fixture.day):
                break
            career.prepare_round(fixture)
        save()

    def rollover() -> None:
        record = career.season_record()
        if not ctx.ui.confirm(_record_line(record) + " ¿Iniciar la temporada siguiente?"):
            return
        try:
            if isinstance(career, BrazilianCareer):
                field = _continental_field(ctx, record.qualified_for) if record.qualified_for else None
                career.new_season(field)
            else:
                career.new_season()
        except (ValueError, KeyError, TypeError) as exc:
            ctx.ui.speak(f"No se pudo iniciar la próxima temporada. {exc}")
            return
        ctx.ui.speak(f"Comienza la temporada {career.year}. {career.league.TITLE}.")
        save()

    cursor = 0
    while True:
        actions: list[MenuAction] = []
        if career.finished:
            actions.append(("Iniciar temporada siguiente", rollover))
        else:
            fixture = career.agenda()[0]
            if fixture.user_index is None:
                actions.append(("Avanzar calendario" if career.employed else "Simular una jornada sin club",
                                lambda: advance(True)))
            else:
                detail = f"{career_date(career.year, fixture.day)}. {fixture.fixture_text()}"
                actions.extend([
                    (f"Jugar: {detail}", lambda: advance(False)),
                    ("Simular siguiente partido", lambda: advance(True)),
                ])
        progress_actions = len(actions)
        actions.append(("Temporada: calendario y resultados", lambda: _competition_menu(ctx, career, save)))
        if career.employed:
            actions.append(("Gestión del club", lambda: run_club_menu(ctx, career, save)))
        if isinstance(career, WorldCareer):
            if career.employed:
                actions.append(("Dinero y movimientos, tecla D para oír el saldo", lambda: finances(ctx, career)))
            actions.append(("Avanzar días sin jugar", lambda: transfer_wait(ctx, career, save)))
        actions.extend([(f"Oficina. {career.unread} mensajes sin leer", lambda: _office(ctx, career, save)),
                        ("Guardar ahora", save_now)])
        label = career.club.name if career.employed else "Sin club"
        choice = ctx.ui.menu(
            f"Carrera de DT. {label}. {career_date(career.year, career.day)}",
            [label for label, _ in actions] + ["Volver al menú principal"], initial_index=cursor,
        )
        if choice is None or choice == len(actions):
            if not unsaved or ctx.ui.confirm("Hay cambios que no se pudieron guardar. ¿Salir sin guardarlos?"):
                return
            continue
        actions[choice][1]()
        cursor = 0 if choice < progress_actions else choice
