"""Game, catalogue, identity, employment and persistence coverage for world career."""

from __future__ import annotations

from collections import Counter
from random import Random
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from audiofutbol.data.career_catalog import load_world_catalogue
from audiofutbol.data.creations import CreationLibrary
from audiofutbol.data.save_manager import SaveManager
from audiofutbol.domain.competitions.career_market import transfer_value
from audiofutbol.domain.competitions.career_recruitment import RecruitmentFilter, demands, player_age, search_players, spending_ceiling
from audiofutbol.domain.competitions.career_simulation import TeamProfile, expected_goals, quick_match
from audiofutbol.domain.competitions.career_squad import can_release, can_sign, club_key
from audiofutbol.domain.competitions.career_world_catalog import ClubSeed, DivisionLink, WorldLeagueSpec
from audiofutbol.domain.competitions.career_world_league import WorldLeague
from audiofutbol.domain.competitions.career_world_market import recruit
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.domain.creations import TeamRef, TournamentDraft
from audiofutbol.domain.match.conditional_changes import ConditionalChange
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.match.ports import HeadlessMatchIO
from audiofutbol.domain.match.ports import MatchSettings
from audiofutbol.domain.models import MatchResult
from audiofutbol.engine.audio import AudioEngine
from audiofutbol.engine.config import GameConfig
from audiofutbol.engine.paths import AppPaths
from audiofutbol.engine.tts.base import NullSpeechBackend
from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.engine.window import GameWindow
from audiofutbol.scenes import career_hub, main_menu, world_career_ui
from audiofutbol.ui.widgets import AudioUI


@pytest.fixture(scope="module")
def real_catalogue():
    return load_world_catalogue(AppPaths.detect(), custom=False)


@pytest.fixture
def career():
    leagues = {}
    seeds = {}
    for division, country, n in (("upper", "Prueba", 7), ("lower", "Prueba", 7), ("overseas", "Exterior", 6)):
        names = tuple(f"{division}-{i}" for i in range(n))
        for i, name in enumerate(names):
            seeds[name] = ClubSeed(name, name, country, "Europa", 66 + (3 if division == "upper" else 0) + i)
        leagues[division] = WorldLeagueSpec(division, division, country, "Europa", names)
    return WorldCareer.start(leagues, [DivisionLink("upper", "lower", 2)], seeds, {}, "upper", "upper-6", "María DT")


def advance(career):
    next_ = career.agenda()[0]
    career.prepare_round(next_)
    return career.finish_round(next_, MatchSettings())


def test_bundled_league_club_identity_and_real_rosters(real_catalogue):
    cat = real_catalogue
    fields = [name for league in cat.leagues.values() for name in league.club_names]
    assert len(cat.leagues) == 160
    assert len({league.country for league in cat.leagues.values()}) == 91
    assert len(fields) == len(set(map(club_key, fields))) == 2381
    assert set(fields) == cat.stock.keys() | cat.rosters.keys()
    assert len(cat.links) == 68
    assert "Santos" in cat.leagues["world:brasil:1"].club_names
    assert "Santos Laguna" in cat.leagues["world:mexico:1"].club_names
    assert "Athletic Club-MG" in cat.leagues["world:brasil:2"].club_names
    assert "Athletic Club" in cat.leagues["world:espana:1"].club_names
    assert "Guarani" in cat.leagues["world:brasil:3"].club_names
    assert cat.rosters["Bayern de Múnich"].country == "Alemania"
    assert cat.rosters["París Saint-Germain"].is_real_squad
    for link in cat.links:
        assert 0 < link.places < min(len(cat.leagues[link.upper].club_names), len(cat.leagues[link.lower].club_names))


def test_creator_league_reuses_the_same_clubs_and_starts(tmp_path):
    source = AppPaths.detect()
    paths = SimpleNamespace(competitions_dir=source.competitions_dir, clubs_dir=source.clubs_dir,
                            saves_dir=tmp_path)
    refs = tuple(TeamRef(f"catalogo:{club_key(name)}", name)
                 for name in ("Flamengo", "Palmeiras", "Arsenal", "Barcelona"))
    draft = TournamentDraft("Liga de prueba", "club", "liga", 4, teams=refs)
    library = CreationLibrary(tmp_path / "creaciones" / "biblioteca.json")
    library.save(draft)
    catalogue = load_world_catalogue(paths)
    key = f"creation:{draft.id}"
    assert set(catalogue.leagues[key].club_names) == {r.name for r in refs}
    c = WorldCareer.start(catalogue.leagues, catalogue.links, catalogue.stock, catalogue.rosters,
                          key, "Flamengo", "DT")
    advance(c)
    assert c.league.step_idx == 1 and len(c.league.schedule) == 6


def test_world_calendar_handles_an_odd_number_of_clubs_and_market_window(career):
    counts = Counter((home.name, away.name) for round_ in career.league.schedule for home, away in round_)
    assert len(career.league.schedule) == 14
    assert len(counts) == 42 and set(counts.values()) == {1}
    for pairs in career.league.schedule:
        assert len({t.name for pair in pairs for t in pair}) == 2 * len(pairs)
    days = [career.round_day(career.league, i) for i in range(career.league.rounds_count)]
    assert days == sorted(set(days)) and 141 in days and days[-1] == 281


def test_quick_ai_is_calibrated_and_tracks_real_match_events():
    neutral = TeamProfile(72, 72, 72)
    home, away = expected_goals(neutral, neutral)
    assert 1.0 < away < home < 1.5
    elite, weak = TeamProfile(86, 84, 84), TeamProfile(65, 65, 64)
    strong, underdog = expected_goals(elite, weak)
    assert strong > 2 * underdog > 0
    a = ClubSeed("a", "A", "Prueba", "Europa", 81).generate()
    b = ClubSeed("b", "B", "Prueba", "Europa", 68).generate()
    a.scheme, a.mentality = "4-2-3-1", 1
    suspended = a.players[-1]
    suspended.suspended_matches = 1
    result = quick_match(a, b, Random(8), (0, 0), 5, controlled=a)
    assert a.scheme == "4-2-3-1" and b.scheme is None
    assert suspended.suspended_matches == 0
    assert all(p is not suspended for _, p, _ in result.scorers)
    assert sum(result.goals) == len(result.scorers)
    assert len(result.assists) <= len(result.scorers)


def test_world_market_transfers_do_not_leak_funds_and_rosters(career):
    seller, p = next((t, p) for t in career.clubs.values() if t is not career.club
                     for p in t.players if can_release(t, p) and can_sign(career.club, p.name)
                     and transfer_value(p) <= career.market.balance)
    capital = career.market.balance + sum(career.market.club_funds.values())
    fee = transfer_value(p)
    assert career.buy(seller, p, fee) == ("accepted", fee)
    assert any(x.name == p.name for x in career.club.players)
    assert sum(career.market.club_funds.values()) + career.market.balance == capital
    assert seller.name in career.touched
    player = next(x for x in career.club.players if career.sale_offer(x) is not None)
    target, fee = career.sell(player)
    assert target.country == career.club.country
    assert all(x is not player for x in career.club.players)
    assert sum(career.market.club_funds.values()) + career.market.balance == capital
    field = [career.clubs[name] for name in career.leagues["upper"].club_names]
    before = career.club.to_dict()
    deals = recruit(career.market, field, career.managed, Random(3))
    assert deals
    assert len(deals) <= 3 and career.club.to_dict() == before
    assert sum(career.market.club_funds.values()) + career.market.balance == capital


def test_resignation_and_rehire_preserve_dt_points_separate_from_club(career, tmp_path):
    for _ in range(3):
        advance(career)
    old_name = career.managed
    career.coach.points = 250
    career.scout()
    old_budget = career.market.balance
    old_squad = [p.name for p in career.academy.prospects]
    career.resign()
    assert not career.employed and career.agenda()[0].user_index is None
    assert not career.job_offers(career.division) and not career.job_offers("overseas")
    with pytest.raises(ValueError, match="dirigir un club"):
        career.scout()
    advance(career)
    offers = career.job_offers(career.division)
    assert offers
    offer = offers[0]
    new_budget = career.market.club_funds[club_key(offer.club)]
    career.accept_job(offer)
    assert career.employed and career.coach.points == 250 and career.managed == offer.club
    assert career.league.user_team.name == offer.club and career.league.step_idx == 4
    assert career.market.balance == new_budget and career.market.club_funds[club_key(old_name)] == old_budget
    assert [p.name for p in career.academies[club_key(old_name)].prospects] == old_squad
    assert not career.academy.prospects
    assert [e.event for e in career.coach.appointments] == ["Contratación", "Dimisión", "Contratación"]
    saves = SaveManager(AppPaths.detect(tmp_path))
    assert saves.save(career.KEY, career)
    loaded = saves.load(career.KEY)
    assert loaded.to_dict() == career.to_dict() and not saves.legacy_candidates(career.KEY)


def test_dismissal_does_not_reset_dt_profile(career):
    career.coach.tenure_matches = 7
    career.coach.confidence = 11
    career.coach.points = 66
    while (fixture := career.agenda()[0]).user_index is None:
        advance(career)
    career.prepare_round(fixture)
    fixture.tournament.register_result(fixture.user_index, career.league.user_team, MatchResult((0, 5)))
    career.finish_round(fixture, MatchSettings())
    assert not career.employed and career.coach.points == 66
    assert career.coach.reputation == "en ascenso"
    assert career.coach.appointments[-1].event == "Destitución"


def test_season_simulates_foreign_tables_and_cross_country_job(real_catalogue, tmp_path):
    cat = real_catalogue
    c = WorldCareer.start(cat.leagues, cat.links, cat.stock, cat.rosters,
                          "world:espana:1", "Barcelona", "DT")
    for _ in range(len(c.league.schedule)):
        advance(c)
    assert c.finished and c.season_record().league_points > 0
    c.coach.points = max(c.coach.points, 250)
    offer = c.job_offers("world:inglaterra:2")[0]
    c.accept_job(offer)
    assert c.year == 2027 and c.managed == offer.club and c.employed
    assert c.leagues[c.division].country == "Inglaterra"
    assert len(c.world_tables) == 160 and len(c.closed_seasons) == 1
    assert len(c.leagues["world:brasil:1"].club_names) == 20
    assert all(len(rows) == len(cat.leagues[key].club_names) for key, rows in c.world_tables.items())
    assert c.market.ledger[-1].reason == "Presupuesto de la nueva temporada"
    saves = SaveManager(AppPaths.detect(tmp_path))
    assert saves.save(c.KEY, c)
    assert saves.slot_path(c.KEY).stat().st_size < 2_000_000
    loaded = saves.load(c.KEY)
    assert loaded.to_dict() == c.to_dict()


def test_keyboard_world_hub_simulates_and_autosaves(career, tmp_path):
    paths = AppPaths.detect()
    voice = NullSpeechBackend()
    speech = SpeechService([voice])
    config = GameConfig()
    window = GameWindow(speech, headless=True)
    ui = AudioUI(speech, AudioEngine(paths, config, init_mixer=False), window)
    saves = SaveManager(AppPaths.detect(tmp_path))
    ctx = SimpleNamespace(ui=ui, window=window, match_settings=MatchSettings, saves=saves)
    while career.agenda()[0].user_index is None:
        advance(career)
    keys = iter([(pygame.K_d, "d"), (pygame.K_DOWN, ""), (pygame.K_RETURN, ""),
                 (pygame.K_DOWN, ""), (pygame.K_RETURN, ""), (pygame.K_ESCAPE, "")])
    window.wait_key = lambda: next(keys)
    career_hub.run_career_hub(ctx, career)
    loaded = saves.load(career.KEY)
    assert loaded.coach.tenure_matches == 1
    assert any("Resultado:" in text for text, _ in voice.spoken)
    assert any("Presupuesto disponible:" in text for text, _ in voice.spoken)
    assert any("novedades del mercado" in text for text, _ in voice.spoken)
    assert loaded.match_logs[0].mvp.startswith("Figura del partido:")
    assert any("A puerta:" in text for text in loaded.match_logs[0].lines)
    assert ui._navigation_shortcuts == {}


def test_world_menu_start_and_continue(monkeypatch):
    labels = iter(("Nuevo juego", "Modo carrera", "Partidas guardadas",
                   f"Continuar: {WorldCareer.TITLE}", "Salir"))
    ui = Mock()
    ui.menu.side_effect = lambda title, options: options.index(next(labels))
    ctx = SimpleNamespace(audio=Mock(), ui=ui, window=Mock(), saves=Mock(), national_teams=[],
                          loaded_from_csv=True, config=SimpleNamespace(musica=False))
    ctx.saves.list_saved_slots.return_value = [(WorldCareer.KEY, WorldCareer.TITLE)]
    start, resume = Mock(), Mock()
    monkeypatch.setattr(main_menu, "start_world_career", start)
    monkeypatch.setattr(main_menu, "continue_world_career", resume)
    monkeypatch.setattr(main_menu, "check_updates_on_startup_if_ready", Mock())
    main_menu.MainMenuScene().run(ctx)
    start.assert_called_once_with(ctx)
    resume.assert_called_once_with(ctx)


def test_brazil_uses_world_career_and_plays_cup_with_three_divisions(real_catalogue):
    cat = real_catalogue
    career = WorldCareer.start(cat.leagues, cat.links, cat.stock, cat.rosters,
                               "world:brasil:2", "Athletic Club-MG", "DT")
    assert career.league.steps[-2:] == [("ida", "ascenso"), ("vuelta", "ascenso")]
    assert len(career.draws["copa_do_brasil"].teams) == 60
    for _ in range(5):
        advance(career)
    assert any("Copa do Brasil" in log.title for log in career.match_logs)
    restored = WorldCareer.from_dict(career.to_dict())
    assert restored.to_dict() == career.to_dict()


def test_recruitment_filters_can_combine_club_league_age_media_and_position(career):
    seller = career.clubs["lower-0"]
    chosen = next(p for p in seller.players if can_release(seller, p) and can_sign(career.club, p.name))
    chosen.birth_year = career.year - 22
    spec = RecruitmentFilter(name=chosen.name, league="lower", club=seller.name, position=chosen.position,
                             min_age=22, max_age=22, min_overall=chosen.overall, max_overall=chosen.overall)
    assert search_players(career, spec)[0][:2] == (seller, chosen)
    assert not search_players(career, RecruitmentFilter(league="overseas", club=seller.name))
    assert player_age(chosen, career.year + 1) == (23, False)
    assert player_age(career.club.players[0], career.year)[1]


def test_purchase_waits_for_reply_and_only_settles_on_confirmation(career):
    seller = career.clubs["lower-0"]
    p = next(p for p in seller.players if can_release(seller, p) and can_sign(career.club, p.name))
    amount = demands(p, seller, career.club, career.year)
    balance = career.market.balance
    desk = career.negotiations
    talk = desk.bid(career, seller, p, amount)
    assert talk.state == "pending"
    assert career.wait_days(1) == 1 and talk.state == "pending"
    assert desk.from_dict(desk.to_dict()).talks[0].response_due == talk.response_due
    assert career.wait_days(1) == 1 and talk.state == "agreed"
    assert career.market.balance == balance and p in seller.players
    desk.close(career, talk)
    assert career.market.balance == balance - amount and p not in seller.players
    with pytest.raises(ValueError):
        desk.close(career, talk)


@pytest.mark.parametrize("expected, multiplier", [("agreed", .96), ("counter", 1.12), ("rejected", 1.6)])
def test_ai_can_accept_counter_or_reject_a_sale_counteroffer(career, expected, multiplier):
    desk = career.negotiations
    career.negotiations.tick(career)
    offer = next(t for t in desk.talks if t.state == "offered")
    player = next(p for p in career.club.players if p.name == offer.player)
    buyer = career.clubs[offer.buyer]
    ceiling = spending_ceiling(player, buyer, career.market.club_funds[club_key(buyer.name)], career.year)
    opening = career.market.balance
    desk.counter(career, offer, int(ceiling * multiplier))
    career.wait_days(2)
    assert offer.state == expected
    assert career.market.balance == opening
    if expected != "rejected":
        desk.close(career, offer)
        assert offer.state == "closed" and career.market.balance > opening
        assert any(p.name == offer.player for p in buyer.players)


def test_negotiation_expiry_and_calendar_do_not_skip_matches(career):
    seller = career.clubs["lower-0"]
    p = next(p for p in seller.players if can_release(seller, p) and can_sign(career.club, p.name))
    opening = career.market.balance
    talk = career.negotiations.bid(career, seller, p, demands(p, seller, career.club, career.year))
    fixture = career.agenda()[0]
    assert career.wait_days(60) == fixture.day
    assert career.agenda()[0] == fixture and not fixture.tournament.history
    advance(career)
    career.wait_days(60)
    assert talk.state == "expired" and p in seller.players
    assert career.market.balance >= opening  # Match revenue may have been credited.


def test_injuries_and_cansancio_alerts_are_recoverable(career):
    fixture = next(f for f in career.agenda() if f.user_index is not None)
    first, second = [p for p in career.club.lineup() if p.position != "POR"][:2]
    kickoff = career.elapsed + fixture.day
    result = MatchResult((2, 0), minutes=({first.name: 90}, {}), injuries=((second.name,), ()))
    notes = career.fitness.post_match(career.club, result, 0, kickoff - 1)
    assert any(second.name in line for line in notes)
    assert career.fitness.is_injured(career.club, second, kickoff)
    assert any(first.name in text for text in career.lineup_alerts(fixture))
    assert any(second.name in text for text in career.lineup_alerts(fixture))
    load = career.fitness.prepare(career.club, kickoff)
    assert load[first.name] > 28 and second not in career.club.lineup()
    assert career.fitness.load(career.club, first, kickoff + 10) == 0
    assert not career.fitness.is_injured(career.club, second, kickoff + 60)


def test_situational_changes_work_in_quick_and_interactive_engine(career):
    home, away = career.club, career.clubs["upper-0"]
    starters = home.lineup()
    starter = next(p for p in starters if p.position == "MED")
    sub = next(p for p in home.players if p.position == "MED" and p not in starters)
    always = ConditionalChange(55, "always", starter.name, sub.name)
    resulting = quick_match(home, away, Random(4), (0, 0), 5, controlled=home, changes=[always])
    assert any("Cambio programado" in msg and minute == 55 for minute, msg in resulting.highlights)
    assert resulting.minutes[0][sub.name] == 35
    home = WorldCareer.from_dict(career.to_dict()).club
    engine = MatchEngine(home, away, io=HeadlessMatchIO(), planned_changes=[
        ConditionalChange(65, "behind", starter.name, sub.name)], initial_fatigue=({starter.name: 39.}, {}))
    assert not engine.subs.process_pending_substitution("saque de banda")
    engine.state.turn = 66 * 60 // engine.state.turn_seconds
    engine.state.goals = [0, 1]
    assert engine.subs.process_pending_substitution("saque de banda")
    assert not engine.subs.process_pending_substitution("otra detención")
    assert any(p.name == sub.name for p in engine.state.xi[0])
