"""Unified hub scene for Nations League and all club competitions."""

from __future__ import annotations

from typing import Any

from audiofutbol.data.competition_loader import load_competition_data
from audiofutbol.domain.competitions.club_tournaments import CopaPersonalizada
from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.models import Team
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.customize import (
    choose_national_field,
    choose_size,
    customize_slots,
    get_club_pool,
    pick_participants,
)
from audiofutbol.scenes.match_scene import run_tournament_match
from audiofutbol.ui.widgets import squad_lines


def _finish_league(ctx: GameContext, tournament: NationsLeague) -> None:
    assert tournament.champion is not None
    assert tournament.runner_up is not None
    if tournament.champion is tournament.user_team:
        ctx.audio.play_theme("musica_fanfarria", volume=0.8)
        ctx.audio.play_sfx("ovacion")
    elif tournament.runner_up is tournament.user_team:
        ctx.audio.play_theme("musica_derrota", volume=0.65)
    else:
        ctx.audio.play_menu_music()
    ctx.ui.speak(
        f"¡{tournament.champion.name} es campeón de la {tournament.TITLE}! "
        f"Subcampeón: {tournament.runner_up.name}."
    )
    top = tournament.top_scorers(1)
    if top:
        ctx.ui.speak("Máximo goleador: " + top[0])
    if tournament.champion is tournament.user_team:
        ctx.ui.speak(f"¡Enhorabuena, has ganado la {tournament.TITLE}!")
    elif tournament.runner_up is tournament.user_team:
        ctx.ui.speak(
            f"{tournament.user_team.name} termina como subcampeón de la {tournament.TITLE}."
        )
    outcomes = tournament.final_summary_lines()
    for line in outcomes:
        ctx.ui.speak(line)
    ctx.saves.delete(tournament.KEY)
    ctx.ui.reader(
        f"Resumen final de la {tournament.TITLE}",
        [
            f"Campeón: {tournament.champion.name}",
            f"Subcampeón: {tournament.runner_up.name}",
        ]
        + outcomes
        + tournament.top_scorers(10),
    )
    ctx.audio.play_menu_music()


def run_league_hub(ctx: GameContext, tournament: NationsLeague) -> None:
    while True:
        if tournament.champion is not None:
            _finish_league(ctx, tournament)
            return

        phase = tournament.phase_name()
        step_kind = tournament.step_type()
        idx = tournament.user_match_index()
        ops: list[str] = []
        actions: list[str] = []

        if idx is not None:
            a, b = tournament.pairs[idx]
            rival = b if a is tournament.user_team else a
            venue = tournament.venue_text(idx, ctx.stadiums.venue_for)
            side = "local" if a is tournament.user_team else "visitante"
            venue_part = f", en {venue}" if venue else ""
            streak_part = tournament.streak_text() if step_kind == "liga" else ""
            ops.append(
                f"Jugar: {phase}, de {side} contra {rival.name}{venue_part}{streak_part}"
            )
            actions.append("jugar")
            ops.append("Simular mi partido")
            actions.append("sim_mio")
        else:
            ops.append(f"Simular: {phase}")
            actions.append("sim_fase")

        if step_kind == "liga":
            ops.append(f"Simular hasta el final de {tournament.LEAGUE_PHASE_LABEL}")
            actions.append("sim_liga")
        if idx is None:
            ops.append("Simular hasta el final del torneo")
            actions.append("sim_todo")
        if step_kind == "liga":
            ops.append("Ver mi posición")
            actions.append("posicion")

        ops.extend(
            [
                "Ver la clasificación completa",
                "Ver la tabla de local",
                "Ver la tabla de visitante",
            ]
        )
        actions.extend(["tabla", "tabla_local", "tabla_visitante"])

        if step_kind == "liga":
            ops.append("Ver mi calendario de local y visitante")
            actions.append("calendario")
        else:
            ops.append("Ver los cruces")
            actions.append("cruces")

        ops.extend(
            [
                "Ver resultados de una fase",
                "Goleadores del torneo",
                "Asistidores del torneo",
                "Mi plantilla",
                "Guardar y volver al menú",
            ]
        )
        actions.extend(["resultados", "goleadores", "asistidores", "plantilla", "guardar"])

        status = (
            f"{tournament.TITLE}. {phase}. "
            f"Tu {tournament.UNIT_LABEL} es {tournament.user_team.name}."
        )
        if tournament.user_eliminated:
            status += " Estás eliminado."
        choice = ctx.ui.menu(status, ops)
        if choice is None:
            if ctx.ui.confirm("¿Volver al menú sin guardar?"):
                return
            continue

        act = actions[choice]
        if act in ("jugar", "sim_mio", "sim_fase"):
            if act == "sim_fase":
                tournament.simulate_remaining(ctx.match_settings())
            else:
                run_tournament_match(ctx, tournament, simulate=(act == "sim_mio"))
                tournament.simulate_remaining(ctx.match_settings())
            was_league = tournament.step_type() == "liga"
            notice = tournament.close_step()
            if notice:
                ctx.ui.speak(notice)
            if tournament.champion is None:
                if was_league:
                    if tournament.step_type() == "liga":
                        ctx.ui.speak(
                            tournament.position_text() + tournament.home_away_summary()
                        )
                else:
                    ctx.ui.reader(
                        "Resultados de la fase", tournament.results_lines(phase)
                    )
        elif act == "sim_liga":
            ctx.ui.speak(f"Simulando {tournament.LEAGUE_PHASE_LABEL}.")
            notice = ""
            while tournament.champion is None and tournament.step_type() == "liga":
                tournament.simulate_remaining(ctx.match_settings())
                notice = tournament.close_step()
            if notice:
                ctx.ui.speak(notice)
        elif act == "sim_todo":
            while tournament.champion is None:
                tournament.simulate_remaining(ctx.match_settings())
                tournament.close_step()
        elif act == "posicion":
            ctx.ui.speak(tournament.position_text() + tournament.home_away_summary())
        elif act == "tabla":
            ctx.ui.reader(
                f"Clasificación de la {tournament.TITLE}", tournament.table_lines()
            )
        elif act == "tabla_local":
            ctx.ui.reader(
                f"Tabla de local de la {tournament.TITLE}",
                tournament.side_table_lines("l"),
            )
        elif act == "tabla_visitante":
            ctx.ui.reader(
                f"Tabla de visitante de la {tournament.TITLE}",
                tournament.side_table_lines("v"),
            )
        elif act == "calendario":
            ctx.ui.reader(
                "Mi calendario", tournament.calendar_lines(ctx.stadiums.venue_for)
            )
        elif act == "cruces":
            ctx.ui.reader(f"Cruces de {phase}", tournament.ties_lines())
        elif act == "resultados":
            seen: list[str] = []
            for ph, *_ in tournament.history:
                if ph not in seen:
                    seen.append(ph)
            if not seen:
                ctx.ui.speak("Todavía no se ha jugado ningún partido.")
            else:
                r = ctx.ui.menu("Elige una fase", seen, initial_index=len(seen) - 1)
                while r is not None:
                    ctx.ui.reader(seen[r], tournament.results_lines(seen[r]))
                    r = ctx.ui.menu("Elige una fase", seen, initial_index=r)
        elif act == "goleadores":
            ctx.ui.reader(
                "Goleadores del torneo",
                tournament.top_scorers(20) or ["Todavía no hay goles"],
            )
        elif act == "asistidores":
            ctx.ui.reader(
                "Asistidores del torneo",
                tournament.top_assists(20) or ["Todavía no hay pases de gol"],
            )
        elif act == "plantilla":
            ctx.ui.reader(
                f"Plantilla de {tournament.user_team.name}",
                squad_lines(tournament.user_team),
            )
        elif act == "guardar":
            if ctx.saves.save(tournament.KEY, tournament):
                ctx.ui.speak("Partida guardada.")
            else:
                ctx.ui.speak("No se pudo guardar la partida.")
            return


def _announce_first_match(ctx: GameContext, tournament: NationsLeague) -> None:
    idx = tournament.user_match_index()
    if idx is None:
        return
    a, b = tournament.pairs[idx]
    rival = b if a is tournament.user_team else a
    side = "local" if a is tournament.user_team else "visitante"
    venue = tournament.venue_text(idx, ctx.stadiums.venue_for)
    place = f", en {venue}" if venue else ""
    ctx.ui.speak(f"Tu primer partido es contra {rival.name}, de {side}{place}.")


def start_new_nations_league(ctx: GameContext) -> None:
    field = choose_national_field(ctx, "Liga de Naciones")
    if field is None:
        return
    top, user_team = field
    n = len(top)
    ctx.ui.speak(f"Liga de Naciones con {n} selecciones. Se sortea el calendario.")
    ctx.audio.play_sfx("sorteo")
    league = NationsLeague(top, user_team, away_goals_rule=ctx.config.gol_visitante)
    away_txt = (
        "El gol de visitante vale como desempate"
        if league.away_goals_rule
        else "El gol de visitante no cuenta"
    )
    ctx.ui.speak(
        f"Son {league.rounds_count} jornadas de todos contra todos. Después, los "
        f"{league.qualify_count} mejores pasan a las eliminatorias a ida y vuelta. {away_txt}."
    )
    _announce_first_match(ctx, league)
    run_league_hub(ctx, league)


def start_new_club_competition(ctx: GameContext, key: str) -> None:
    spec = CLUB_COMPETITIONS[key]
    json_file = spec.json_filename
    if key == "libertadores":
        variant = ctx.ui.menu(
            "Copa Libertadores",
            [
                "Con cuatro equipos mexicanos: América, Cruz Azul, Monterrey y Tigres",
                "Solo equipos de Sudamérica, como la edición real",
            ],
        )
        if variant is None:
            return
        if variant == 1:
            json_file = "libertadores_2026.json"

    data, teams_by_id = load_competition_data(ctx.paths, json_file)
    if not teams_by_id:
        ctx.ui.speak(
            f"No encontré el archivo {json_file} en la carpeta competiciones."
        )
        return
    mode = ctx.ui.menu(
        f"{spec.title}. Participantes",
        ["Usar los participantes oficiales", "Personalizar participantes, meter cualquier club"],
    )
    if mode is None:
        return
    if mode == 1:
        customize_slots(ctx, teams_by_id)
    ordered = sorted(teams_by_id.values(), key=lambda t: t.name)
    user_team = ctx.ui.choose_team(f"Elige tu equipo para la {spec.title}", ordered)
    if user_team is None:
        return

    real_count = sum(1 for t in ordered if t.is_real_squad)
    if real_count == 0:
        ctx.ui.speak(
            "Todavía no hay jugadores reales de clubes en la carpeta datos barra clubes. "
            "Cada club juega con una plantilla de ejemplo de su nivel."
        )
    elif real_count < len(ordered):
        ctx.ui.speak(
            f"{real_count} de {len(ordered)} clubes usan jugadores reales de tu base de datos. "
            "Los demás usan plantillas de ejemplo."
        )
    ctx.audio.play_sfx("sorteo")
    tournament: Any = spec.cls(data, teams_by_id, user_team)
    ctx.ui.speak(spec.intro_text)
    _announce_first_match(ctx, tournament)
    run_league_hub(ctx, tournament)


def continue_saved_league(ctx: GameContext, key: str) -> None:
    loaded = ctx.saves.load(key)
    if not isinstance(loaded, NationsLeague):
        ctx.ui.speak("No se pudo cargar la partida guardada.")
        return
    run_league_hub(ctx, loaded)


def start_custom_cup(ctx: GameContext) -> None:
    """Copa de clubes con participantes libres: cualquier club de cualquier liga."""
    pool = get_club_pool(ctx)
    sizes = [n for n in (8, 16, 32, 64) if n <= len(pool)]
    size = choose_size(ctx, sizes, "clubes")
    if size is None:
        return
    chosen = pick_participants(ctx, pool, size, "un club", use_country=True)
    if chosen is None:
        return
    user_team = ctx.ui.choose_team("Elige tu club para la copa personalizada", chosen)
    if user_team is None:
        return
    teams_by_id: dict[str, Team] = {}
    for k, team in enumerate(chosen):
        team.team_id = f"custom_{k}"
        team.group = None
        teams_by_id[team.team_id] = team
    ctx.audio.play_sfx("sorteo")
    ctx.ui.speak(f"Copa personalizada con {size} clubes. Se hace el sorteo de grupos.")
    tournament = CopaPersonalizada(None, teams_by_id, user_team)
    _announce_first_match(ctx, tournament)
    run_league_hub(ctx, tournament)
