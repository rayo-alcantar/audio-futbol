"""End-to-end simulation and JSON save/load roundtrip tests for competitions."""

from __future__ import annotations

from pathlib import Path

from audiofutbol.data.competition_loader import StadiumDirectory, load_competition_data
from audiofutbol.data.csv_loader import create_generic_team, load_national_teams
from audiofutbol.data.save_manager import SaveManager
from audiofutbol.domain.competitions.attendance import calculate_attendance
from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.club_tournaments import (
    ChampionsLeague,
    CopaInteramericana,
    CopaLibertadores,
    CopaPersonalizada,
    CopaSudamericana,
    LaLiga,
    Liga1Peru,
    LigaArgentina,
    LigaMX,
    PremierLeague,
)
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.models import MatchResult
from audiofutbol.engine.paths import AppPaths


def test_world_cup_full_simulation_and_save_roundtrip(tmp_path: Path) -> None:
    paths = AppPaths.detect()
    teams, _ = load_national_teams(paths)
    wc = WorldCup(teams[:48], teams[0])
    assert wc.group_count == 12
    assert len(wc.draw_lines) == 48

    # Play 1 phase, save, reload, finish tournament
    wc.simulate_remaining()
    wc.close_phase()

    saves = SaveManager(AppPaths(tmp_path))
    assert saves.save(WorldCup.KEY, wc) is True
    assert saves.exists(WorldCup.KEY) is True
    loaded = saves.load(WorldCup.KEY)
    assert isinstance(loaded, WorldCup)
    assert loaded.phase_idx == wc.phase_idx
    assert loaded.user_team.name == wc.user_team.name

    while loaded.champion is None:
        loaded.simulate_remaining()
        loaded.close_phase()

    assert loaded.podium is not None
    assert len(loaded.podium) == 3
    assert len(loaded.top_scorers(5)) > 0


def test_nations_league_full_simulation_and_save_roundtrip(tmp_path: Path) -> None:
    teams = [create_generic_team(f"Sel {i}", 70 + (i % 15)) for i in range(16)]
    league = NationsLeague(teams, teams[0], away_goals_rule=True)
    assert league.rounds_count == 8
    assert league.qualify_count == 8

    league.simulate_remaining()
    league.close_step()

    saves = SaveManager(AppPaths(tmp_path))
    assert saves.save(NationsLeague.KEY, league) is True
    loaded = saves.load(NationsLeague.KEY)
    assert isinstance(loaded, NationsLeague)
    assert loaded.step_idx == 1

    stadiums = StadiumDirectory(AppPaths.detect())
    assert len(loaded.calendar_lines(stadiums.venue_for)) == 8
    assert calculate_attendance(loaded, 0) is not None

    while loaded.champion is None:
        loaded.simulate_remaining()
        loaded.close_step()
    assert loaded.runner_up is not None


def test_all_club_competitions_simulate_and_serialize(tmp_path: Path) -> None:
    paths = AppPaths.detect()
    saves = SaveManager(AppPaths(tmp_path))

    cases = [
        ("champions_2026_27.json", ChampionsLeague),
        ("libertadores_mx_2026.json", CopaLibertadores),
        ("sudamericana_2026.json", CopaSudamericana),
        ("interamericana_2026.json", CopaInteramericana),
        ("ligamx_apertura_2026.json", LigaMX),
        ("premier_league_2026_27.json", PremierLeague),
        ("laliga_2026_27.json", LaLiga),
        ("liga1_peru_2026.json", Liga1Peru),
        ("liga_argentina_2025.json", LigaArgentina),
        ("brasileirao_a_2026.json", BrasileiraoA),
        ("brasileirao_b_2026.json", BrasileiraoB),
    ]
    for json_file, cls in cases:
        data, eqs = load_competition_data(paths, json_file)
        assert data is not None and eqs is not None
        first_team = next(iter(eqs.values()))
        tourney = cls(data, eqs, first_team)

        # Advance 1 step, test JSON save & load
        tourney.simulate_remaining()
        tourney.close_step()
        assert saves.save(tourney.KEY, tourney) is True
        restored = saves.load(tourney.KEY)
        assert isinstance(restored, cls)
        assert restored.step_idx == tourney.step_idx

        # Finish entire tournament to champion
        while restored.champion is None:
            restored.simulate_remaining()
            restored.close_step()
        assert restored.champion is not None
        assert restored.runner_up is not None
        assert len(restored.table_lines()) >= len(eqs)


def test_world_cup_semifinal_winner_is_not_marked_eliminated() -> None:
    teams = [create_generic_team(f"Sel {i}", 80) for i in range(8)]
    user_team = teams[0]
    wc = WorldCup(teams, user_team)

    # Group stage (3 rounds): make user_team win every match 4-0
    for _ in range(3):
        idx = wc.user_match_index()
        assert idx is not None
        wc.register_result(idx, user_team, MatchResult(goals=(4, 0)))
        wc.simulate_remaining()
        wc.close_phase()
        assert wc.user_eliminated is False

    # Semifinal (with 8 teams, first KO round is Semifinales, data == 4)
    assert wc.phase_name() == "Semifinales"
    semi_idx = wc.user_match_index()
    assert semi_idx is not None
    wc.register_result(semi_idx, user_team, MatchResult(goals=(4, 0)))
    wc.simulate_remaining()
    notice = wc.close_phase()

    # User won 4-0 in semifinals -> advancing to Final, must NOT be marked eliminated during 3rd-place phase!
    assert "final" in notice.lower()
    assert wc.phase_name() == "Partido por el tercer lugar"
    assert user_team in wc.semi_winners
    assert wc.user_eliminated is False
    assert wc.user_match_index() is None  # User doesn't play the 3rd-place match

    # Simulate 3rd-place match -> advance to La gran final -> user plays final!
    wc.simulate_remaining()
    wc.close_phase()
    assert wc.phase_name() == "La gran final"
    assert wc.user_eliminated is False
    final_idx = wc.user_match_index()
    assert final_idx is not None
    wc.register_result(final_idx, user_team, MatchResult(goals=(2, 1)))
    wc.close_phase()
    assert wc.champion is user_team


class Jugador:
    pass


class Equipo:
    pass


class LigaNaciones:
    pass


def test_legacy_sav_pickle_migration_from_root_dir(tmp_path: Path) -> None:
    import pickle

    def make_legacy_team(name: str) -> Equipo:
        eq = Equipo()
        eq.nombre = name
        eq.jugadores = []
        for idx, pos in enumerate(
            ("POR", "DEF", "DEF", "DEF", "DEF", "MED", "MED", "MED", "DEL", "DEL", "DEL"),
            start=1,
        ):
            j = Jugador()
            j.nombre = f"{name} Jug {idx}"
            j.pos = pos
            j.ovr = 78
            j.numero = idx
            j.amarillas = 0
            j.suspendido = 0
            j.goles = 1 if idx == 11 else 0
            eq.jugadores.append(j)
        return eq

    t1 = make_legacy_team("Argentina")
    t2 = make_legacy_team("Uruguay")
    legacy = LigaNaciones()
    legacy.equipos = [t1, t2]
    legacy.mi = t1
    legacy.visitante = True
    legacy.jornadas = 1
    legacy.pasan = 2
    legacy.mi_eliminado = False
    legacy.rnd = {"Argentina": 0.1, "Uruguay": 0.2}
    legacy.tabla = {
        "Argentina": {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "fp": 0},
        "Uruguay": {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "fp": 0},
    }
    legacy.hist = []
    legacy.calendario = [[(t1, t2)]]
    legacy.pasos = [("liga", 0), ("unico", 2)]
    legacy.paso = 0
    legacy.cruces = []
    legacy.ranking = {}
    legacy.clasificados = []
    legacy.pares = [(t1, t2)]
    legacy.hechos = {}
    legacy.campeon = None
    legacy.subcampeon = None

    # Write a legacy .sav file in the root directory using __main__ module references
    import sys

    main_mod = sys.modules["__main__"]
    for cls in (Jugador, Equipo, LigaNaciones):
        cls.__module__ = "__main__"
        setattr(main_mod, cls.__name__, cls)
    raw_bytes = pickle.dumps(legacy, protocol=4)
    sav_path = tmp_path / "partida_liga.sav"
    sav_path.write_bytes(raw_bytes)

    saves = SaveManager(AppPaths(tmp_path))
    assert saves.exists("liga") is True
    slots = saves.list_saved_slots()
    assert ("liga", "Liga de Naciones") in slots

    loaded = saves.load("liga")
    assert isinstance(loaded, NationsLeague)
    assert loaded.user_team.name == "Argentina"
    assert len(loaded.teams) == 2
    assert saves.slot_path("liga").is_file()


def test_custom_club_cup_full_simulation_and_save_roundtrip(tmp_path: Path) -> None:
    from audiofutbol.data.club_pool import build_club_pool, fresh_copy

    paths = AppPaths.detect()
    pool = build_club_pool(paths)
    chosen = [fresh_copy(t) for t in pool[:8]]
    teams_by_id = {}
    for k, team in enumerate(chosen):
        team.team_id = f"custom_{k}"
        team.group = None
        teams_by_id[team.team_id] = team

    cup = CopaPersonalizada(None, teams_by_id, chosen[0])
    cup.simulate_remaining()
    cup.close_step()

    saves = SaveManager(AppPaths(tmp_path))
    assert saves.save(CopaPersonalizada.KEY, cup) is True
    loaded = saves.load(CopaPersonalizada.KEY)
    assert isinstance(loaded, CopaPersonalizada)
    assert loaded.step_idx == cup.step_idx

    while loaded.champion is None:
        loaded.simulate_remaining()
        loaded.close_step()
    assert loaded.champion is not None
    assert loaded.runner_up is not None


def test_top_assists_and_tactical_preferences_persist_across_saves(tmp_path: Path) -> None:
    teams = [create_generic_team(f"Sel {i}", 76 + (i % 8)) for i in range(8)]
    user_team = teams[0]
    user_team.scheme = "3-5-2"
    user_team.mentality = 1
    user_team.takers = {"penal": user_team.players[10].name}
    user_team.players[9].assists = 3

    wc = WorldCup(teams, user_team)
    league = NationsLeague(teams, user_team)
    assert any("3 pases de gol" in line for line in wc.top_assists(5))
    assert any("3 pases de gol" in line for line in league.top_assists(5))

    saves = SaveManager(AppPaths(tmp_path))
    assert saves.save(WorldCup.KEY, wc) is True
    loaded = saves.load(WorldCup.KEY)
    assert isinstance(loaded, WorldCup)
    assert loaded.user_team.scheme == "3-5-2"
    assert loaded.user_team.mentality == 1
    assert loaded.user_team.takers == user_team.takers
    assert any(p.assists == 3 for p in loaded.user_team.players)



