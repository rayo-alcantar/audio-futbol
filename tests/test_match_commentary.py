"""Verify the edited catalogue, match hooks, and fixture-aware commentary."""

from __future__ import annotations

import random
from string import Formatter
from types import SimpleNamespace

from audiofutbol.data.csv_loader import create_generic_team
from audiofutbol.domain.competitions.nations_league import NationsLeague
from audiofutbol.domain.match.commentary import CommentaryContext
from audiofutbol.domain.match.commentary_lines import COMMENTARY_LINES
from audiofutbol.domain.match.engine import MatchEngine
from audiofutbol.domain.match.ports import HeadlessMatchIO, MatchSettings
from audiofutbol.scenes.match_scene import _commentary_context


class FirstLine(random.Random):
    def choice(self, seq):
        return seq[0]

    def random(self) -> float:
        return 0.0


def _match(*, context=CommentaryContext(), auto: bool = False, seed: int = 13):
    io = HeadlessMatchIO(rng=random.Random(seed + 1))
    engine = MatchEngine(
        create_generic_team("Santos", 75),
        create_generic_team("Vasco da Gama", 75),
        io=io,
        rng=random.Random(seed),
        auto=auto,
        prematch_menu=False,
        settings=MatchSettings(turn_seconds=120),
        commentary_context=context,
    )
    engine.commentary.rng = FirstLine()
    return engine, io


def test_commentary_catalogue_keeps_all_sections_and_usable_fields() -> None:
    expected_sections = {
        f"{part}.{section}"
        for part, count in enumerate((5, 5, 4, 2, 1, 3, 4, 6, 3, 6), 1)
        for section in range(1, count + 1)
    }
    assert set(COMMENTARY_LINES) == expected_sections
    assert sum(map(len, COMMENTARY_LINES.values())) == 206
    assert len(COMMENTARY_LINES["5.1"]) == 12
    assert COMMENTARY_LINES["10.1"][0] == "¿De qué te vas a disfrazar, {jugador}?"
    for lines in COMMENTARY_LINES.values():
        for line in lines:
            assert line == line.strip()
            assert line.count("¿") == line.count("?")
            assert line.count("¡") == line.count("!")
            assert "bastón blanco" not in line and "andadera" not in line
            for _, field, _, _ in Formatter().parse(line):
                assert field is None or field in {"local", "visitante", "dt", "jugador", "arbitro", "estadio", "ciudad"}


def test_kickoff_halftime_and_full_time_follow_match_events(monkeypatch) -> None:
    engine, io = _match(context=CommentaryContext(home_unbeaten=True))
    st = engine.state
    st.halftime_turn, st.total_turns = 1, 2
    monkeypatch.setattr(engine, "_play_turn", lambda: setattr(st, "turn", st.turn + 1))
    result = engine.play()
    intro = COMMENTARY_LINES["1.1"][0].format(local="Santos")
    kickoff = COMMENTARY_LINES["1.5"][0]
    halftime = COMMENTARY_LINES["2.2"][0]
    final = COMMENTARY_LINES["4.1"][0]
    timeline = [
        intro, kickoff, "Final del primer tiempo.", halftime, "Comienza el segundo tiempo.",
        "¡Final del partido!", final,
    ]
    assert [io.messages.index(line) for line in timeline] == sorted(io.messages.index(line) for line in timeline)
    assert result.goals == (0, 0)


def test_live_commentary_never_celebrates_an_overturned_goal(monkeypatch) -> None:
    engine, io = _match()
    st = engine.state
    scorer = st.xi[0][-1]
    monkeypatch.setattr(st, "roll", lambda chance: True)
    engine.set_pieces.score_goal(0, scorer)
    assert st.goals == [0, 0]
    assert any("Gol anulado por el VAR" in line for line in io.messages)
    assert {key for key, _ in engine.commentary.used} == {"8.2"}

    st.turn = 20
    monkeypatch.setattr(st, "roll", lambda chance: chance < 0.20)
    engine.set_pieces.score_goal(0, scorer)
    goal_comment = COMMENTARY_LINES["10.3"][4]
    confirmed = next(line for line in io.messages if "El VAR confirma el gol" in line)
    assert io.messages.index(confirmed) < io.messages.index(goal_comment)
    assert st.goals == [1, 0]


def test_delayed_live_comments_use_actual_home_team_and_avoid_spam() -> None:
    engine, io = _match(context=CommentaryContext(home_index=1))
    st = engine.state
    st.turn = 33  # Minute 66 in two-minute turns.
    engine.commentary.late_match()
    engine.commentary.late_match()
    assert io.messages == [COMMENTARY_LINES["4.2"][0]]
    st.goals[:] = [2, 1]
    engine.commentary.late_match()  # Within the cooldown.
    assert len(io.messages) == 1
    st.turn += 5
    engine.commentary.late_match()
    engine.commentary.late_match()
    assert io.messages[-1] == COMMENTARY_LINES["7.2"][0].format(local="Vasco da Gama")
    assert len(io.messages) == 2


def test_missed_penalty_uses_real_taker_and_keeps_var_handball_comment_conditional(monkeypatch) -> None:
    engine, io = _match()
    st = engine.state
    taker = st.xi[0][-1]
    monkeypatch.setattr(st, "roll", lambda chance: chance < 0.15)
    monkeypatch.setattr(engine.set_pieces, "_choose", lambda *args, **kwargs: 1)
    assert engine.set_pieces.take_penalty_kick(0, taker) == "fuera"
    assert any("El penal se va fuera." == line for line in io.messages)
    assert ("8.6", 2) in engine.commentary.used
    st.turn = 20
    engine.var.review_missed_handball(0, lambda team: None, engine.commentary.missed_handball)
    assert not any(key == "5.1" for key, _ in engine.commentary.used)
    monkeypatch.setattr(st, "roll", lambda chance: True)
    engine.var.review_missed_handball(0, lambda team: None, engine.commentary.missed_handball)
    assert io.messages[-1].startswith("El árbitro no vio nada.")


def test_commentary_never_changes_match_randomness_and_respects_silent_simulation() -> None:
    configured, _ = _match(seed=77)
    baseline, _ = _match(context=None, seed=77)
    expected = baseline.play()
    actual = configured.play()
    assert configured.commentary.used and not baseline.commentary.used
    assert (actual.goals, actual.fair_play, actual.highlights) == (
        expected.goals, expected.fair_play, expected.highlights,
    )
    assert configured.state.rng.getstate() == baseline.state.rng.getstate()
    simulation, io = _match(auto=True)
    simulation.play()
    assert not simulation.commentary.used
    assert COMMENTARY_LINES["1.5"][0] not in io.messages


def test_scene_context_uses_host_fixture_rank_and_streak_not_user_team() -> None:
    teams = [create_generic_team(name, 75) for name in ("Santos", "Vasco", "Bahia", "Remo")]
    home, user, rival, _ = teams
    league = NationsLeague(teams, user)
    league.pairs = [(home, user)]
    league.history = [
        ("Liga", home, rival, 2, 0, None),
        ("Liga", rival, home, 0, 1, None),
        ("Liga", home, user, 1, 1, None),
    ]
    league.table[home.name].update(pj=3, pts=7)
    ctx = SimpleNamespace(stadiums=SimpleNamespace(venue_for=lambda _: ("Vila Belmiro", "Santos")))
    context = _commentary_context(ctx, league, 0)
    assert context == CommentaryContext(
        home_index=1, stadium="Vila Belmiro", city="Santos", for_points=True,
        home_leading=True, home_unbeaten=True,
    )
    league.steps[league.step_idx] = ("unico", 2)
    assert _commentary_context(ctx, league, 0).home_index is None
