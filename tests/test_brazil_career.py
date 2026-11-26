"""End-to-end and domain regression coverage for the isolated manager career."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pygame
import pytest

from audiofutbol.data.competition_loader import StadiumDirectory, load_registered_club_field
from audiofutbol.data.save_manager import SaveManager
from audiofutbol.domain.competitions.brazil_career import BrazilianCareer
from audiofutbol.domain.competitions.brasileirao import BrasileiraoB
from audiofutbol.domain.competitions.career_academy import SCOUT_COST
from audiofutbol.domain.competitions.career_brazil_rules import LEAGUES, NATIONAL_CUP
from audiofutbol.domain.competitions.career_market import transfer_value
from audiofutbol.domain.competitions.career_squad import can_release, can_sign
from audiofutbol.domain.match.ports import MatchSettings
from audiofutbol.domain.models import MatchResult
from audiofutbol.engine.audio import AudioEngine
from audiofutbol.engine.config import GameConfig
from audiofutbol.engine.paths import AppPaths
from audiofutbol.engine.tts.base import NullSpeechBackend
from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.engine.window import GameWindow
from audiofutbol.scenes import career_hub, career_management, main_menu
from audiofutbol.ui.widgets import AudioUI


@pytest.fixture
def career_fields():
    return [list(load_registered_club_field(AppPaths.detect(), key)[2].values()) for key in LEAGUES]


@pytest.fixture
def career(career_fields):
    return BrazilianCareer.start(*career_fields, career_fields[0][0].name)


def _resolve(tournament, score):
    for index, (home, away) in enumerate(tournament.pairs):
        if index in tournament.completed:
            continue
        goals = score(tournament, index, home, away)
        # A deterministic shootout resolution for tied knockout fixtures.
        penalty = (5, 4) if tournament.is_knockout() else None
        tournament.register_result(index, home, MatchResult(goals, penalties=penalty))


def test_start_isolated_from_catalog_and_independent_saves(career_fields, career, tmp_path: Path):
    assert career.year == 2026 and career.window == "inicial"
    assert len(career.clubs) == len(career.draws[NATIONAL_CUP].teams) == 40
    assert career.league.user_team is not career.club
    assert career.club.players[0] is not career_fields[0][0].players[0]
    assert career.draws[BrasileiraoB.KEY].zone_label(20, False) == ""
    assert career.agenda()[0].user_index is not None

    saves = SaveManager(AppPaths.detect(tmp_path))
    assert saves.save(career.division, career.league)
    assert saves.save(career.KEY, career)
    assert [key for key, _ in saves.list_saved_slots()] == [career.KEY, career.division]
    independent = saves.slot_path(career.division).read_bytes()
    raw = json.loads(saves.slot_path(career.KEY).read_text(encoding="utf-8"))
    raw["competition"]["career_schema"] = 0
    saves.slot_path(career.KEY).write_text(json.dumps(raw), encoding="utf-8")
    assert saves.load(career.KEY) is None
    assert saves.slot_path(career.division).read_bytes() == independent
    assert saves.legacy_candidates(career.KEY) == []


def test_transfer_negotiation_budget_and_squad_copies(career, tmp_path: Path):
    seller, candidate = next(
        (team, p) for team in career.clubs.values() if team is not career.club
        for p in team.players if can_release(team, p) and can_sign(career.club, p.name)
        and transfer_value(p) <= career.market.balance
    )
    amount = transfer_value(candidate)
    opening = career.market.balance
    assert career.buy(seller, candidate, amount * 7 // 10)[0] == "rejected"
    assert career.buy(seller, candidate, amount * 85 // 100) == ("counter", amount * 94 // 100)
    assert career.market.balance == opening
    assert not career.market.ledger

    keeper = career.club.players[0]
    next(p for p in career.league.user_team.players if p.name == keeper.name).yellow_cards = 2
    career.league.user_team.scheme = "4-4-2"
    career.club.scheme = "4-2-3-1"
    outcome, fee = career.buy(seller, candidate, amount * 85 // 100, accept_counter=True)
    assert outcome == "accepted" and career.market.balance == opening - fee
    assert candidate not in seller.players
    assert career.league.user_team.scheme == "4-2-3-1"
    assert next(p for p in career.league.user_team.players if p.name == keeper.name).yellow_cards == 2
    cup_user = career.draws[NATIONAL_CUP].user_team
    assert next(p for p in cup_user.players if p.name == keeper.name).yellow_cards == 0
    cup_transfer = next(p for p in cup_user.players if p.name == candidate.name)
    players = [p for p in career.club.players if p.name == candidate.name]
    assert len(players) == 1 and cup_transfer is not players[0]
    assert len({p.number for p in career.club.players}) == len(career.club.players)

    listed = next(p for p in career.club.players if
                  career.market.offer_for_sale(p, career.club, list(career.clubs.values())))
    club, earned = career.sell(listed)
    assert any(p.name == listed.name for p in club.players)
    assert listed not in career.club.players
    assert career.market.balance == opening - fee + earned
    assert len(career.market.ledger) == 2

    career.day = 50
    with pytest.raises(ValueError, match="mercado está cerrado"):
        career.sell(career.club.players[0])
    saves = SaveManager(AppPaths.detect(tmp_path))
    assert saves.save(career.KEY, career)
    persisted = saves.load(career.KEY)
    assert persisted.to_dict() == career.to_dict()


def test_youth_growth_cooldown_promotion_and_roster_protection(career):
    opening = career.market.balance
    found = career.scout()
    assert len(found) == 3
    assert career.market.balance == opening - SCOUT_COST
    with pytest.raises(ValueError, match="Faltan 90 días"):
        career.scout()
    previous = found[0].overall
    career.academy.advance(career.year, career.elapsed + 60)
    assert found[0].overall == previous + 2
    found[0].born = career.year - 15
    with pytest.raises(ValueError, match="16 años"):
        career.promote(found[0])
    found[0].born -= 1
    promoted = career.promote(found[0])
    assert promoted in career.club.players and promoted.number >= 1
    assert found[0] not in career.academy.prospects
    assert any(p.name == promoted.name for p in career.league.user_team.players)
    keepers = [p for p in career.club.players if p.position == "POR"]
    if len(keepers) == 2:
        assert not any(can_release(career.club, p) for p in keepers)


@pytest.mark.parametrize("division_index", [0, 1])
def test_full_season_promotion_continental_and_rollover(monkeypatch, career_fields, division_index, tmp_path):
    career = BrazilianCareer.start(*career_fields, career_fields[division_index][0].name)

    def managed_wins(tournament, index, home, away):
        if home.name == career.managed:
            return (3, 0)
        if away.name == career.managed:
            return (0, 3)
        return (1, 0)

    days = []
    balance = career.market.balance
    while agenda := career.agenda():
        fixture = agenda[0]
        career.prepare_round(fixture)
        monkeypatch.setattr(fixture.tournament, "simulate_remaining",
                            lambda settings, t=fixture.tournament: _resolve(t, managed_wins))
        career.finish_round(fixture, MatchSettings())
        days.append(fixture.day)
    assert days == sorted(days)
    assert career.window == "entre temporadas"
    assert career.market.balance > balance
    record = career.season_record()
    assert record.place == 1 and record.qualified_for == "libertadores"
    assert record.next_division == LEAGUES[0] and len(record.trophies) == 2
    old_club = career.club
    with pytest.raises(ValueError, match="participantes"):
        career.new_season()
    assert career.year == 2026 and not career.history
    field = career_hub._continental_field(SimpleNamespace(paths=AppPaths.detect()), record.qualified_for)
    career.new_season(field)
    assert career.year == 2027 and career.club is old_club and career.day == 0
    assert career.history == [record]
    assert all(len(career.draws[key].teams) == 20 for key in LEAGUES)
    copa = career.draws["libertadores"]
    assert len(copa.groups) == 8 and all(len(grp) == 4 for grp in copa.groups)
    assert copa.user_team.name == career.managed
    assert all(t.country != "México" for t in copa.teams)
    saves = SaveManager(AppPaths.detect(tmp_path))
    assert saves.save(career.KEY, career) and saves.load(career.KEY).to_dict() == career.to_dict()


def test_stale_round_cannot_be_applied_twice(monkeypatch, career):
    fixture = career.agenda()[0]
    career.prepare_round(fixture)
    monkeypatch.setattr(fixture.tournament, "simulate_remaining",
                        lambda settings: _resolve(fixture.tournament, lambda *args: (1, 0)))
    career.finish_round(fixture, MatchSettings())
    with pytest.raises(ValueError, match="jornada ya no está pendiente"):
        career.finish_round(fixture, MatchSettings())


def test_fast_forward_stops_before_the_first_match_in_the_new_window(monkeypatch, career):
    ctx = SimpleNamespace(ui=Mock(), window=Mock(), match_settings=MatchSettings)
    ctx.ui.confirm.return_value = True
    for tournament in career.draws.values():
        monkeypatch.setattr(tournament, "simulate_remaining",
                            lambda settings, t=tournament: _resolve(t, lambda *args: (1, 0)))
    assert career_hub._advance_to_next_window(ctx, career)
    assert career.window == "de mitad de temporada"
    fixture = career.agenda()[0]
    assert fixture.day == career.day and not fixture.tournament.completed
    assert any("Abrió la ventana" in m.text for m in career.inbox)

    ctx.window.wait_or_skip_action.return_value = "escape"
    assert career_hub._advance_to_next_window(ctx, career)
    assert career.agenda()[0] != fixture
    assert not career.finished


def test_launch_initial_slot_and_decline_replacement(monkeypatch, tmp_path):
    ui = Mock()
    ui.menu.return_value = 1
    ui.choose_team.side_effect = lambda title, teams: teams[0]
    ctx = SimpleNamespace(paths=AppPaths.detect(), ui=ui, audio=Mock(),
                          saves=SaveManager(AppPaths.detect(tmp_path)))
    hub = Mock()
    monkeypatch.setattr(career_hub, "run_career_hub", hub)
    career_hub.start_brazil_career(ctx)
    slot = ctx.saves.slot_path(BrazilianCareer.KEY)
    saved = slot.read_bytes()
    assert hub.call_args.args[1].division == LEAGUES[1]
    ui.confirm.return_value = False
    career_hub.start_brazil_career(ctx)
    assert slot.read_bytes() == saved and hub.call_count == 1
    career_hub.continue_brazil_career(ctx)
    assert hub.call_args.args[1].to_dict() == json.loads(saved)["competition"]


def test_legacy_brazil_career_reachable_from_saved_menu(monkeypatch):
    labels = iter(("Partidas guardadas",
                   f"Continuar: {BrazilianCareer.TITLE}", "Salir"))
    ctx = SimpleNamespace(
        audio=Mock(), ui=Mock(), window=Mock(), saves=Mock(), national_teams=[],
        loaded_from_csv=True, config=SimpleNamespace(musica=False),
    )
    ctx.ui.menu.side_effect = lambda title, options: options.index(next(labels))
    ctx.saves.list_saved_slots.return_value = [(BrazilianCareer.KEY, BrazilianCareer.TITLE)]
    resume = Mock()
    monkeypatch.setattr(main_menu, "continue_brazil_career", resume)
    monkeypatch.setattr(main_menu, "check_updates_on_startup_if_ready", Mock())
    main_menu.MainMenuScene().run(ctx)
    resume.assert_called_once_with(ctx)


def test_keyboard_hub_simulates_a_real_round_and_autosaves(career, tmp_path):
    paths = AppPaths.detect()
    config = GameConfig()
    audio = AudioEngine(paths, config, init_mixer=False)
    voice = NullSpeechBackend()
    speech = SpeechService([voice])
    window = GameWindow(speech, headless=True)
    ui = AudioUI(speech, audio, window)
    saves = SaveManager(AppPaths.detect(tmp_path))
    ctx = SimpleNamespace(paths=paths, config=config, audio=audio, window=window, ui=ui,
                          saves=saves, stadiums=StadiumDirectory(paths), match_settings=MatchSettings)
    keys = iter([(pygame.K_DOWN, ""), (pygame.K_RETURN, ""), (pygame.K_ESCAPE, "")])
    window.wait_key = lambda: next(keys)
    career_hub.run_career_hub(ctx, career)
    recovered = saves.load(career.KEY)
    assert recovered.league.table[career.managed]["pj"] == 1
    assert not saves.slot_path(career.KEY).with_suffix(".tmp").exists()
    spoken = [message for message, _ in voice.spoken]
    assert any("Simular siguiente partido" in msg for msg in spoken)
    assert any(msg.startswith("Resultado: ") for msg in spoken)
    assert any("Gestión del club" in msg for msg in window.hud.items)


@pytest.mark.parametrize("commit", [False, True])
def test_keyboard_tactics_draft_stays_outside_the_match(career, commit):
    paths = AppPaths.detect()
    speech = SpeechService([NullSpeechBackend()])
    audio = AudioEngine(paths, GameConfig(), init_mixer=False)
    window = GameWindow(speech, headless=True)
    ctx = SimpleNamespace(audio=audio, window=window, speech=speech, ui=AudioUI(speech, audio, window),
                          match_settings=MatchSettings)
    final_keys = [(pygame.K_HOME, ""), (pygame.K_RETURN, "")] if commit else [(pygame.K_ESCAPE, "")]
    keys = iter([
        (pygame.K_DOWN, ""), (pygame.K_RETURN, ""),  # Open scheme.
        (pygame.K_DOWN, ""), (pygame.K_RETURN, ""),  # Choose a different scheme.
        (pygame.K_RETURN, ""),  # Keep the current lineup when changing schemes.
        *final_keys,
    ])
    window.wait_key = lambda: next(keys)
    changed = Mock()
    before = career.club.scheme
    career_management._edit_tactics(ctx, career, changed)
    assert changed.call_count == int(commit)
    assert (career.club.scheme != before) is commit
    assert career.league.user_team.scheme == career.club.scheme
    assert not career.league.history
