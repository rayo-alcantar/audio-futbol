"""Regression coverage for ordinary-match substitutions and the shared career editor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audiofutbol.data.csv_loader import create_generic_team
from audiofutbol.domain.competitions.career_simulation import _Side
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.match.conditional_changes import ConditionalChange
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.match.ports import HeadlessMatchIO, MatchSettings
from audiofutbol.domain.models import MatchResult
from audiofutbol.scenes.friendly import play_friendly
from audiofutbol.scenes.match_scene import run_tournament_match


def _pair(engine: MatchEngine):
    outgoing = next(p for p in engine.state.xi[0] if p.position == "DEF")
    incoming = next(p for p in engine.subs.bench(0) if p.position == "DEF")
    return outgoing, incoming


def _engine(**kwargs):
    return MatchEngine(create_generic_team("Local", 74), create_generic_team("Rival", 74),
                       io=HeadlessMatchIO(), **kwargs)


@pytest.mark.parametrize("mode", ["friendly", "league", "cup"])
def test_normal_match_flows_expose_the_same_editor_and_apply_the_named_change(mode, monkeypatch):
    ui = Mock()
    ctx = SimpleNamespace(ui=ui, speech=Mock(), audio=Mock(), window=Mock(),
                          stadiums=Mock(venue_for=lambda team: None), match_settings=MatchSettings)
    teams = [create_generic_team(f"Equipo {i}", 70 + i) for i in range(8)]
    harness = Mock()

    def play(engine):
        out, incoming = _pair(engine)
        targets = iter((
            ("Preparación del partido", "Cambios por situación"),
            ("Cambios por situación", "Programar cambio"),
            ("¿Quién sale?", out.name),
            ("¿Quién entra", incoming.name),
            ("¿En qué situación", "si vamos perdiendo"),
            ("¿Desde qué minuto?", "Desde el minuto 65"),
            ("Cambios por situación", "Volver"),
            ("Preparación del partido", "Empezar el partido"),
        ))

        def select(title, options, **kwargs):
            heading, name = next(targets)
            assert title.startswith(heading)
            return next(i for i, label in enumerate(options) if label.startswith(name))

        ui.menu.side_effect = select
        ui.confirm.return_value = True
        engine.tactics.prematch_menu()
        assert engine.subs.planned == [ConditionalChange(65, "behind", out.name, incoming.name)]
        engine.state.turn = 65 * 60 // engine.state.turn_seconds
        assert not engine.subs.process_pending_substitution("el saque de banda")
        engine.state.goals = [0, 1]
        assert engine.subs.process_pending_substitution("el saque de banda")
        assert not engine.subs.process_pending_substitution("la falta")
        assert incoming in engine.state.xi[0] and out not in engine.state.xi[0]
        assert engine.state.substitutions_used[0] == 1
        harness()
        return engine.state.build_result()

    monkeypatch.setattr(MatchEngine, "play", play)
    if mode == "friendly":
        play_friendly(ctx, teams[0], teams[1])
    else:
        tournament = (NationsLeague if mode == "league" else WorldCup)(teams, teams[0])
        run_tournament_match(ctx, tournament, simulate=False)
    harness.assert_called_once()


def test_injury_at_any_minute_prefers_named_replacement_to_manual_prompt(monkeypatch):
    engine = _engine(max_substitutions=5)
    st, subs = engine.state, engine.subs
    out, incoming = _pair(engine)
    subs.planned = [ConditionalChange(0, "injured", out.name, incoming.name)]
    assert not subs.process_pending_substitution("el saque de banda")
    rolls = iter((True, False))
    monkeypatch.setattr(st, "roll", lambda probability: next(rolls))
    monkeypatch.setattr(st.rng, "choices", lambda *args, **kwargs: [out])
    manual = Mock()
    monkeypatch.setattr(subs, "open_substitution_menu", manual)
    subs.check_injuries()
    manual.assert_not_called()
    assert id(out) in st.injured and incoming in st.xi[0]
    assert not subs.planned
    assert any(f"Cambio programado por lesión: sale {out.name}, entra {incoming.name}." in msg
               for _, msg in st.highlights)


@pytest.mark.parametrize("unavailable", ["limit", "suspended", "injured", "wrong_role"])
def test_unavailable_injury_replacement_is_not_forced(unavailable, monkeypatch):
    engine = _engine(max_substitutions=5)
    st, subs = engine.state, engine.subs
    out, incoming = _pair(engine)
    if unavailable == "wrong_role":
        incoming = next(p for p in subs.bench(0) if p.position == "POR")
    if unavailable == "limit":
        st.substitutions_used[0] = 5
    if unavailable == "suspended":
        incoming.suspended_matches = 1
    if unavailable == "injured":
        st.injured.add(id(incoming))
    subs.planned = [ConditionalChange(0, "injured", out.name, incoming.name)]
    st.injured.add(id(out))
    fallback = Mock(return_value=True)
    monkeypatch.setattr(subs, "open_substitution_menu", fallback)
    subs._replace_injured(0, out)
    assert incoming not in st.xi[0] and out in st.xi[0]
    assert fallback.call_count == (0 if unavailable == "limit" else 1)


def test_tactics_menu_has_live_editor_and_execution_still_works_if_user_simulates_rest():
    engine = _engine(max_substitutions=5)
    st, subs = engine.state, engine.subs
    out, incoming = _pair(engine)
    events = iter(("Cambios por situación", "Volver", "Volver al partido"))
    engine.io._decision_callback = lambda title, choices: choices.index(next(events))
    engine.tactics.in_match_menu()
    subs.planned = [ConditionalChange(60, "extra_player", out.name, incoming.name)]
    st.turn = 58 * 60 // st.turn_seconds
    st.red_cards[1] = 1
    st.auto = True
    assert not subs.process_pending_substitution("la falta")
    st.turn = 60 * 60 // st.turn_seconds
    assert subs.process_pending_substitution("el saque de meta")
    assert incoming in st.xi[0]


def test_quick_career_injury_uses_configured_player_instead_of_best_reserve():
    engine = _engine()
    home, rival = engine.state.teams
    xi = home.lineup()
    out = next(p for p in xi if p.position == "DEF")
    bench = [p for p in home.players if all(p is not starter for starter in xi)]
    defenders = sorted((p for p in bench if p.position == "DEF"), key=lambda p: p.overall)
    chosen = defenders[0]
    assert chosen is not defenders[-1]
    side = _Side(home, home, xi, bench, {}, [ConditionalChange(0, "injured", out.name, chosen.name)], True)
    rng = Mock()
    rng.choices.return_value = [out]
    rng.random.return_value = 0
    result = MatchResult((0, 0))
    side.injury_or_changes(15, 0, 0, rng, result)
    assert chosen in side.xi and defenders[-1] not in side.xi
    assert any("Cambio programado por lesión" in text for _, text in result.highlights)
