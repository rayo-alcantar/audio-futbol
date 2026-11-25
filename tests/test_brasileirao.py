"""Data, competition rules and navigation for both Brazilian divisions."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiofutbol.data.club_pool import build_club_pool
from audiofutbol.data.competition_loader import load_competition_data
from audiofutbol.data.save_manager import SaveManager
from audiofutbol.domain.competitions.brasileirao import BrasileiraoA, BrasileiraoB
from audiofutbol.domain.competitions.factory import CLUB_COMPETITIONS
from audiofutbol.domain.formations import ROLES, preferred_role
from audiofutbol.domain.match.board import yellow_card_badge
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.models import MatchResult, Team
from audiofutbol.engine.paths import AppPaths


def _new_league(cls: type[BrasileiraoA] | type[BrasileiraoB]):
    spec = CLUB_COMPETITIONS[cls.KEY]
    data, clubs = load_competition_data(AppPaths.detect(), spec.json_filename)
    assert data is not None and clubs is not None
    return cls(data, clubs, next(iter(clubs.values())))


@pytest.mark.parametrize("cls", [BrasileiraoA, BrasileiraoB])
def test_brasileirao_squads_and_calendar(cls) -> None:
    league = _new_league(cls)
    assert len(league.teams) == 20
    assert len({t.team_id for t in league.teams}) == 20
    for club in league.teams:
        assert club.country == "Brasil"
        assert club.stadium and club.city
        assert club.is_real_squad and len(club.players) >= 11
        assert len({p.name for p in club.players}) == len(club.players)
        assert len({p.number for p in club.players}) == len(club.players)
        assert sum(p.position == "POR" for p in club.players) >= 2
        for player in club.players:
            assert 1 <= player.number <= 99
            assert ROLES[player.puesto][1] == player.position

    assert len(league.schedule) == 38
    assert all(len(games) == 10 for games in league.schedule)
    for games in league.schedule:
        assert len({t.name for fixture in games for t in fixture}) == 20
    actual = [(a.name, b.name) for rnd in league.schedule for a, b in rnd]
    assert sorted(actual) == sorted(permutations([team.name for team in league.teams], 2))


def test_brasileirao_club_and_player_names_do_not_mix_in_global_pool() -> None:
    pool = build_club_pool(AppPaths.detect())
    clubs = {club.name: club for club in pool}
    brazil = [team for team in pool if team.country == "Brasil"]
    assert len(brazil) == 40 and all(team.is_real_squad for team in brazil)
    assert len({team.team_id for team in brazil}) == 40

    santos, laguna = clubs["Santos"], clubs["Santos Laguna"]
    assert (santos.team_id, laguna.team_id) == ("santos_fc", "santos")
    assert clubs["Vasco da Gama"].team_id == "vasco"
    athletic_mg, athletic_es = clubs["Athletic Club-MG"], clubs["Athletic Club"]
    assert (athletic_mg.team_id, athletic_es.team_id) == ("athletic_club_mg", "athletic_club")
    assert athletic_mg.country == "Brasil" and athletic_es.country == "España"
    assert "Glauco" in {p.name for p in athletic_mg.players}
    assert "Unai Simón" in {p.name for p in athletic_es.players}
    assert {p.name for p in athletic_mg.players}.isdisjoint(p.name for p in athletic_es.players)
    for club, role in (("Avaí", "MP"), ("Seattle Sounders", "MC"), ("Santos", "POR")):
        saved_club = Team.from_dict(clubs[club].to_dict())
        player = next(p for p in saved_club.players if p.name == "João Paulo")
        assert player.puesto == role and preferred_role(player) == role


@pytest.mark.parametrize("cls", [BrasileiraoA, BrasileiraoB])
def test_brasileirao_table_tiebreakers_and_zones(cls) -> None:
    league = _new_league(cls)
    a, b, c = league.teams[:3]
    league.table[a.name].update(pts=12, g=3, gf=20, gc=2)
    league.table[b.name].update(pts=12, g=4, gf=5, gc=10)
    assert league.standings()[:2] == [b, a]  # Wins before goal difference.

    for team in (a, b, c):
        league.table[team.name].update(pts=12, g=4, gf=5, gc=4)
    league.table[a.name]["red_cards"] = 1
    league.table[b.name]["yellow_cards"] = 5
    league.history = [("Jornada 1", a, b, 2, 1, None), ("Jornada 20", b, a, 0, 0, None)]
    assert league._sort_group([a, b]) == [a, b]  # Head-to-head comes before cards.
    assert league.standings()[:3] == [c, b, a]  # More than two: skip head-to-head.
    league.history = [("Jornada 1", a, b, 1, 0, None), ("Jornada 20", b, a, 4, 4, None)]
    assert league._sort_group([a, b]) == [a, b]
    assert "descenso" in league.zone_label(17, False)
    assert "descenso" not in league.zone_label(16, False)
    if cls is BrasileiraoA:
        assert "fase de grupos" in league.zone_label(4, False)
        assert "preliminar" in league.zone_label(5, False)
        assert "Sudamericana" in league.zone_label(11, False)
        assert league.zone_label(12, False) == ""
        league.step_idx = league.rounds_count - 1
        league.close_step()
        assert league.champion is c
        assert c.name in league.final_summary_lines()[0]
        assert "Descenso a la Série B" in league.final_summary_lines()[-1]
    else:
        assert "ascenso directo" in league.zone_label(2, False)
        assert "repechaje" in league.zone_label(6, False)
        assert league.zone_label(7, False) == ""


def test_serie_b_playoffs_keep_regular_champion_and_resume_from_save(tmp_path: Path) -> None:
    league = _new_league(BrasileiraoB)
    saves = SaveManager(AppPaths(tmp_path))
    club_a = _new_league(BrasileiraoA)
    assert saves.save(club_a.KEY, club_a)

    clubs = league.teams
    for pos, team in enumerate(clubs):
        league.table[team.name]["pts"] = 60 - pos
    league.user_team = clubs[2]
    player = clubs[2].players[0]
    player.yellow_cards, player.suspended_matches = 2, 1
    league.step_idx = league.rounds_count - 1
    notice = league.close_step()

    assert f"{clubs[0].name} es campeón" in notice and league.champion is None
    assert league.user_match_index() == 0
    assert league.pairs == [(clubs[5], clubs[2]), (clubs[4], clubs[3])]
    assert not league.is_knockout()
    assert (player.yellow_cards, player.suspended_matches) == (0, 1)
    assert any("Juega el repechaje" in line for line in league.table_lines())
    league.register_result(0, clubs[5], MatchResult(goals=(0, 0)))
    league.register_result(1, clubs[4], MatchResult(goals=(2, 0)))
    league.close_step()

    assert saves.save(league.KEY, league)
    assert {key for key, _ in saves.list_saved_slots()} == {club_a.KEY, league.KEY}
    restored = saves.load(league.KEY)
    assert isinstance(restored, BrasileiraoB)
    assert restored.phase_name() == "Repechaje de ascenso, partido de vuelta"
    assert [a.name for a, _ in restored.pairs] == [clubs[2].name, clubs[3].name]
    seeded, unseeded = restored.pairs[0]
    for team, advantage in ((seeded, 0), (unseeded, 1)):
        kwargs = restored.match_kwargs(0, team)
        assert kwargs["table_advantage"] == advantage
        assert kwargs["no_extra_time"] is True and kwargs["away_goals_rule"] is False
    restored.register_result(0, seeded, MatchResult(goals=(1, 1)))
    restored.register_result(1, restored.pairs[1][0], MatchResult(goals=(1, 0)))
    restored.close_step()

    assert restored.champion.name == clubs[0].name
    assert restored.runner_up.name == clubs[1].name
    assert restored.final_summary_lines()[1] == (
        f"Ascenso por repechaje: {clubs[2].name} y {clubs[4].name}."
    )
    assert restored.zone_label(3, True) == "Asciende a la Série A por repechaje"


def test_brasileirao_card_limit_and_table_totals_follow_team_order() -> None:
    league = _new_league(BrasileiraoA)
    home, away = league.pairs[0]
    engine = MatchEngine(away, home, auto=True, **league.match_kwargs(0, away))
    player = engine.state.xi[0][-1]
    player.yellow_cards = 1
    assert "a una" not in yellow_card_badge(player, limit=3)
    engine.set_pieces.give_card(0, player, "amarilla")
    assert player.yellow_cards == 2 and not player.suspended_matches
    assert "a una" in yellow_card_badge(player, limit=3)
    engine = MatchEngine(away, home, auto=True, **league.match_kwargs(0, away))
    engine.set_pieces.give_card(0, player, "amarilla")
    engine.set_pieces.give_card(1, engine.state.xi[1][-1], "roja")
    assert player.yellow_cards == 0 and player.suspended_matches == 1
    league.register_result(0, away, engine.state.build_result())
    assert league.table[away.name]["yellow_cards"] == 1
    assert league.table[home.name]["red_cards"] == 1


@pytest.mark.parametrize("cls", [BrasileiraoA, BrasileiraoB])
def test_brasileirao_reachable_from_new_game_menu(monkeypatch, cls) -> None:
    from audiofutbol.scenes import league_hub, main_menu

    spec = CLUB_COMPETITIONS[cls.KEY]
    labels = iter(("Nuevo juego", "Brasileirão", spec.menu_label, "Usar los participantes oficiales", "Salir"))
    ui = Mock()
    ui.menu.side_effect = lambda title, options: options.index(next(labels))
    ui.choose_team.side_effect = lambda title, options: options[0]
    ctx = SimpleNamespace(
        audio=Mock(), ui=ui, paths=AppPaths.detect(), window=Mock(), national_teams=[],
        loaded_from_csv=True, config=SimpleNamespace(musica=False),
        stadiums=Mock(venue_for=lambda team: None),
    )
    hub = Mock()
    monkeypatch.setattr(league_hub, "run_league_hub", hub)
    monkeypatch.setattr(main_menu, "check_updates_on_startup_if_ready", lambda ctx: None)
    main_menu.MainMenuScene().run(ctx)
    hub.assert_called_once()
    league = hub.call_args.args[1]
    assert isinstance(league, cls) and len(league.teams) == 20
    ui.speak.assert_any_call(spec.intro_text)
