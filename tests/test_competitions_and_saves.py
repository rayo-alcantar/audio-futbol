"""End-to-end simulation and JSON save/load roundtrip tests for competitions."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiofutbol.data.competition_loader import (
    StadiumDirectory,
    load_competition_data,
    load_registered_club_field,
)
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


@pytest.mark.parametrize(("label", "cls"), [("LaLiga", LaLiga), ("Premier League", PremierLeague)])
def test_european_leagues_open_from_new_game_menu(monkeypatch, label, cls) -> None:
    from audiofutbol.scenes import league_hub, main_menu

    paths = AppPaths.detect()
    spec, _, _ = load_registered_club_field(paths, cls.KEY)
    choices = iter(("Nuevo juego", "Ligas europeas", label, "Usar los participantes oficiales", "Salir"))
    ui = Mock()
    ui.menu.side_effect = lambda title, options: options.index(next(choices))
    ui.choose_team.side_effect = lambda title, options: options[0]
    ctx = SimpleNamespace(
        audio=Mock(), ui=ui, paths=paths, window=Mock(), national_teams=[],
        loaded_from_csv=True, config=SimpleNamespace(musica=False), stadiums=StadiumDirectory(paths),
    )
    hub = Mock()
    monkeypatch.setattr(league_hub, "run_league_hub", hub)
    monkeypatch.setattr(main_menu, "check_updates_on_startup_if_ready", Mock())

    main_menu.MainMenuScene().run(ctx)

    hub.assert_called_once()
    league = hub.call_args.args[1]
    assert isinstance(league, cls)
    assert len(league.teams) == 20
    fixtures = Counter((a.team_id, b.team_id) for round_ in league.schedule for a, b in round_)
    assert len(league.schedule) == 38 and all(len(round_) == 10 for round_ in league.schedule)
    assert len(fixtures) == 380 and set(fixtures.values()) == {1}
    ui.speak.assert_any_call(spec.intro_text)


@pytest.mark.parametrize(
    ("results", "expected_prefix"),
    [
        (
            {("A", "B"): (1, 0), ("A", "C"): (1, 0), ("B", "C"): (3, 0),
             ("C", "B"): (0, 3), ("B", "D"): (3, 0), ("D", "B"): (1, 0)},
            ("A", "B"),
        ),
        (
            {("A", "B"): (2, 0), ("B", "A"): (1, 0), ("A", "C"): (0, 8), ("C", "B"): (1, 0),
             ("A", "D"): (1, 0), ("D", "A"): (0, 1), ("B", "D"): (1, 0), ("D", "B"): (0, 1)},
            ("C", "A", "B"),
        ),
        (
            {("A", "B"): (4, 0), ("B", "A"): (1, 0), ("B", "C"): (0, 1), ("C", "B"): (1, 0),
             ("A", "D"): (4, 0), ("B", "D"): (1, 0), ("D", "B"): (0, 1), ("D", "C"): (1, 0)},
            ("C", "A", "B"),
        ),
    ],
    ids=["two_clubs", "multiple_clubs_direct_margin_between_remaining", "multiple_clubs_direct_points"],
)
def test_laliga_final_tiebreak_prefers_direct_results(tmp_path, results, expected_prefix) -> None:
    clubs = {name: create_generic_team(name, 70) for name in "ABCD"}
    league = LaLiga(None, clubs, clubs["A"])
    saves = SaveManager(AppPaths(tmp_path))

    for _ in range(league.rounds_count - 1):
        for idx, (home, away) in enumerate(league.pairs):
            league.register_result(idx, home, MatchResult(goals=results.get((home.name, away.name), (0, 0))))
        league.close_step()

    assert saves.save(league.KEY, league)
    restored = saves.load(league.KEY)
    assert isinstance(restored, LaLiga)
    for idx, (home, away) in enumerate(restored.pairs):
        restored.register_result(idx, home, MatchResult(goals=results.get((home.name, away.name), (0, 0))))
    restored.close_step()

    assert len({restored.table[club]["pts"] for club in expected_prefix}) == 1
    overall = sorted(restored.teams, key=restored._sort_key)
    assert [team.name for team in overall[:len(expected_prefix)]] != list(expected_prefix)
    assert [team.name for team in restored.standings()][:len(expected_prefix)] == list(expected_prefix)
    assert restored.champion is not None and restored.champion.name == expected_prefix[0]


def test_laliga_final_summary_reports_zones_and_relegation() -> None:
    _, data, clubs = load_registered_club_field(AppPaths.detect(), LaLiga.KEY)
    league = LaLiga(data, clubs, next(iter(clubs.values())))
    for _ in range(league.rounds_count):
        for idx, (home, _) in enumerate(league.pairs):
            league.register_result(idx, home, MatchResult(goals=(0, 0)))
        league.close_step()

    order = [team.name for team in league.standings()]
    assert len(league.history) == 380
    lines = league.final_summary_lines()
    assert all(club in lines[0] for club in order[:4])
    assert order[4] in lines[1] and order[5] in lines[2]
    assert all(club in lines[3] for club in order[-3:])
    assert "descenso" not in league.zone_label(17, False)
    assert league.zone_label(18, True) == "Desciende a Segunda División"


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



