"""Creation schema, tournament formats, accessible workflows and ZIP roundtrips."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

import pygame
import pytest

from audiofutbol.data.competition_loader import load_registered_club_field
from audiofutbol.data.creations import (
    CreationLibrary, catalogue_ref, export_package, issue_url, read_package,
    read_roster_csv, resolve_tournament, squad_from_team,
)
from audiofutbol.data.csv_loader import create_generic_team
from audiofutbol.domain.competitions.created import CreatedTournament, build_created_tournament
from audiofutbol.domain.competitions.world_cup import WorldCup
from audiofutbol.domain.creations import FORMATS, Placement, SquadPlayer, TeamDraft, TournamentDraft
from audiofutbol.domain.models import MatchResult
from audiofutbol.engine.paths import AppPaths
from audiofutbol.engine.tts.base import NullSpeechBackend
from audiofutbol.engine.tts.service import SpeechService
from audiofutbol.engine.window import GameWindow
from audiofutbol.scenes import creation, creation_common, creation_placements, creation_teams, creation_tournaments, main_menu
from audiofutbol.scenes.creation_preview import simulate_preview
from audiofutbol.scenes.league_hub import run_league_hub
from audiofutbol.ui.text_entry import text_entry


def _club(name="Atlético Época"):
    return TeamDraft(name=name, kind="club", country="México", stadium="La Cancha",
                     city="Puebla", players=squad_from_team(create_generic_team(name, 72)))


def test_roster_validates_accents_jerseys_and_goalkeeper_backup(tmp_path: Path) -> None:
    original = _club()
    copy = replace(original, players=(SquadPlayer("José", 2, "MC", 70),
                                      SquadPlayer("Jose", 2, "DC", 72)))
    assert "El nombre Jose está repetido." in copy.issues()
    assert "El dorsal 2 está repetido." in copy.issues()
    assert "Porteros: se necesitan al menos 2." in copy.issues()
    store = CreationLibrary(tmp_path / "saves" / "creaciones" / "biblioteca.json")
    incomplete = replace(original, players=())
    store.save(incomplete)
    with pytest.raises(ValueError, match="Faltan jugadores"):
        export_package(incomplete, {}, tmp_path / "downloads")
    assert not (tmp_path / "downloads").exists()
    store.save(original)
    assert CreationLibrary(store.path).drafts[original.id] == original
    assert original.as_team().players[0].puesto == original.players[0].role


def test_import_one_roster_from_csv_keeps_roles_and_rejects_wrong_team(tmp_path: Path) -> None:
    original = _club()
    path = tmp_path / "plantel.csv"
    path.write_text("equipo;numero;jugador;posicion;calidad;puesto\n"
                    "Atletico Epoca;13;Ángel;POR;75;POR\n"
                    "Atletico Epoca;20;Íker;DEF;75;LI\n", encoding="utf-8-sig")
    assert read_roster_csv(path, original.name)[1] == SquadPlayer("Íker", 20, "LI", 75)
    with pytest.raises(ValueError, match="pertenece"):
        read_roster_csv(path, "Otro club")


def test_zip_contains_only_portable_data_and_clones_embedded_teams(tmp_path: Path) -> None:
    official = create_generic_team("Club oficial", 68)
    custom = _club()
    draft = TournamentDraft("Mi liga", "club", "liga", 2,
                            teams=(catalogue_ref(official), custom.ref))
    root = tmp_path / "Descargas"
    first = export_package(draft, {custom.ref.key: custom}, root)
    second = export_package(draft, {custom.ref.key: custom}, root)
    assert first != second and first.parent == root
    with ZipFile(first) as archive:
        assert set(archive.namelist()) == {"aporte.json", "LEEME.txt"}
        assert json.loads(archive.read("aporte.json"))["version"] == 1
    assert read_package(first) == (draft, (custom,))

    store = CreationLibrary(tmp_path / "results" / "creaciones.json")
    imported = store.import_package(first)
    assert isinstance(imported, TournamentDraft) and imported.id != draft.id
    assert imported.teams[0] == draft.teams[0]
    assert imported.teams[1].key != draft.teams[1].key
    catalogue = {draft.teams[0].key: official}
    assert resolve_tournament(imported, catalogue, store.custom_teams())[1].name == custom.name
    store = CreationLibrary(store.path)
    copied_team = store.custom_teams()[imported.teams[1].key]
    with pytest.raises(ValueError, match="forma parte"):
        store.remove(copied_team)
    assert len(store.drafts) == 2


def test_package_rejects_unknown_schema_without_modifying_library(tmp_path: Path) -> None:
    store = CreationLibrary(tmp_path / "biblioteca.json")
    original = _club()
    store.save(original)
    contents = store.path.read_bytes()
    path = tmp_path / "incompatible.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("aporte.json", json.dumps({"version": 999}))
    with pytest.raises(ValueError, match="versión"):
        store.import_package(path)
    assert store.path.read_bytes() == contents
    assert store.drafts == {original.id: original}


@pytest.mark.parametrize(
    ("key", "size", "kind", "expected_rounds"),
    [
        ("liga", 5, "club", 10), ("liguilla", 6, "club", 10),
        ("grupos", 8, "club", 6), ("eliminacion", 8, "club", 0),
        ("mundial", 48, "seleccion", None), ("naciones", 8, "seleccion", 4),
        ("fase_uefa", 36, "club", 8), ("liguilla_mx", 18, "club", 17),
        ("apertura", 18, "club", 34), ("ascenso", 20, "club", 38),
    ],
)
def test_all_formats_finish_using_the_same_creation_factory(key, size, kind, expected_rounds) -> None:
    teams = [create_generic_team(f"Equipo {i}", 70) for i in range(size)]
    refs = tuple(map(catalogue_ref, teams))
    draft = TournamentDraft("Torneo de prueba", kind, key, size, teams=refs,
                            advance=4 if key == "liguilla" else 0, knockout_legs=2, final_legs=2)
    uefa = load_registered_club_field(AppPaths.detect(), "champions")[1] if key == "fase_uefa" else None
    runner = build_created_tournament(draft, teams, 0, uefa_schedule=uefa)
    assert runner.TITLE == draft.name
    assert runner.user_team is not teams[0]
    if not isinstance(runner, WorldCup):
        assert runner.rounds_count == expected_rounds
    for _ in range(80):
        if runner.champion is not None:
            break
        for idx, (home, _) in enumerate(runner.pairs):
            runner.register_result(idx, home, MatchResult(goals=(2, 1), penalties=(5, 4)))
        (runner.close_phase if isinstance(runner, WorldCup) else runner.close_step)()
    assert runner.champion is not None
    assert all(team.team_id == "" and team.group is None for team in teams)


def test_odd_double_round_robin_gives_every_entrant_one_bye_per_half() -> None:
    teams = [create_generic_team(f"Club {i}", 70) for i in range(5)]
    draft = TournamentDraft("Liga impar", "club", "liga", 5, teams=tuple(map(catalogue_ref, teams)))
    runner = build_created_tournament(draft, teams, 2)
    assert isinstance(runner, CreatedTournament)
    assert len(runner.schedule) == 10
    assert all(len(day) == 2 for day in runner.schedule)
    for team in runner.teams:
        assert sum(team in pair for day in runner.schedule[:5] for pair in day) == 4
        assert sum(team in pair for day in runner.schedule[5:] for pair in day) == 4
    assert sum(a is runner.user_team for day in runner.schedule for a, _ in day) == 4


def test_preview_uses_real_match_engine_and_never_touches_official_saves() -> None:
    teams = [create_generic_team(f"Club {i}", 70) for i in range(2)]
    draft = TournamentDraft("Copa corta", "club", "eliminacion", 2,
                            teams=tuple(map(catalogue_ref, teams)))
    runner = build_created_tournament(draft, teams, 0)
    ctx = SimpleNamespace(ui=Mock(), audio=Mock(), saves=Mock(), stadiums=Mock(),
                          match_settings=lambda: None)
    runner.simulate_remaining()
    assert len(runner.completed) == 1 and runner.completed[0]["ga"] >= 0
    runner.close_step()
    run_league_hub(ctx, runner, preview=True)
    assert ctx.saves.mock_calls == []


def test_long_simulation_can_stop_between_matchdays(monkeypatch) -> None:
    teams = [create_generic_team(f"Club {i}", 70) for i in range(4)]
    draft = TournamentDraft("Liga de prueba", "club", "liga", 4,
                            teams=tuple(map(catalogue_ref, teams)))
    runner = build_created_tournament(draft, teams, 0)
    synthesize = Mock()
    monkeypatch.setattr(runner, "simulate_remaining", synthesize)
    ctx = SimpleNamespace(ui=Mock(), window=Mock(), match_settings=lambda: None)
    ctx.window.wait_or_skip_action.return_value = "escape"
    simulate_preview(ctx, runner)
    assert runner.step_idx == 1 and runner.champion is None
    synthesize.assert_called_once()
    assert any("Simulación detenida" in call.args[0] for call in ctx.ui.speak.call_args_list)


def test_replace_official_slot_keeps_champions_fixtures(monkeypatch) -> None:
    paths = AppPaths.detect()
    _, _, slots = load_registered_club_field(paths, "champions")
    slot, original = next(iter(slots.items()))
    draft = _club()
    capture = Mock()
    monkeypatch.setattr(creation_placements, "run_league_hub", capture)
    ctx = SimpleNamespace(paths=paths, ui=Mock())
    creation_placements.preview_placement(ctx, draft, Placement("champions", slot, original.name))
    tournament = capture.call_args.args[1]
    assert capture.call_args.kwargs["preview"] is True
    assert tournament.user_team.name == draft.name and tournament.user_team.team_id == slot
    assert sum(tournament.user_team in pair for day in tournament.schedule for pair in day) == 8
    assert slots[slot].name == original.name


def _context(tmp_path: Path, interactions: tuple[str | None, ...]):
    ui = Mock()
    sequence = iter(interactions)
    def menu(title, options):
        choice = next(sequence)
        return options.index(choice) if choice is not None else None
    ui.menu.side_effect = menu
    ui.confirm.return_value = True
    ui.choose_team.side_effect = lambda title, teams: teams[0]
    return SimpleNamespace(
        paths=AppPaths(tmp_path), ui=ui, audio=Mock(), window=Mock(headless=True), saves=Mock(),
        stadiums=Mock(), config=SimpleNamespace(musica=False), loaded_from_csv=True,
        national_teams=[], extra_national_teams=[],
    )


def test_main_menu_team_workflow_imports_exports_and_opens_only_a_draft_issue(monkeypatch, tmp_path: Path) -> None:
    draft = _club()
    csv_path = tmp_path / "plantel.csv"
    rows = ["equipo,numero,jugador,posicion,calidad,puesto"]
    for p in draft.players:
        rows.append(f"{draft.name},{p.number},{p.name},{p.player().position},{p.overall},{p.role}")
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    ctx = _context(tmp_path, (
        "Crear", "Equipo", "Club", "Equipo nuevo", "Editar plantel",
        "Importar CSV y sustituir el plantel", "Volver", "Exportar a ZIP",
        "Abrir formulario de aporte en GitHub", "Volver", "Volver", "Salir",
    ))
    inputs = iter((draft.name, draft.country))
    monkeypatch.setattr(creation_common, "text_entry", lambda *args, **kwargs: next(inputs))
    monkeypatch.setattr(creation_teams, "file_field", lambda *args: csv_path)
    monkeypatch.setattr(creation_common, "downloads_folder", lambda: tmp_path / "Descargas")
    monkeypatch.setattr(main_menu, "check_updates_on_startup_if_ready", lambda _: None)
    mocked_open = Mock(return_value=True)
    monkeypatch.setattr(creation_common.webbrowser, "open", mocked_open)
    main_menu.MainMenuScene().run(ctx)
    exported = list((tmp_path / "Descargas").glob("*.zip"))
    assert len(exported) == 1
    payload, _ = read_package(exported[0])
    assert payload.name == draft.name
    assert mocked_open.call_count == 1
    address = urlparse(mocked_open.call_args.args[0])
    assert address.netloc == "github.com" and address.path.endswith("/issues/new")
    assert exported[0].name in parse_qs(address.query)["body"][0]
    assert str(tmp_path) not in mocked_open.call_args.args[0]
    assert ctx.saves.mock_calls == []


def test_tournament_wizard_saves_draft_and_runs_preview(monkeypatch, tmp_path: Path) -> None:
    teams = [create_generic_team(f"Club {i}", 70) for i in range(5)]
    ctx = _context(tmp_path, (
        "Torneo", "Clubes", FORMATS["liga"].label, "Dos vueltas, ida y vuelta",
        "Elegir participantes", "Completar los cupos libres", "Con los mejores del catálogo",
        "Volver", "Probar el torneo", "Volver", "Volver",
    ))
    answers = iter(("Mi liga", "3"))
    monkeypatch.setattr(creation_common, "text_entry", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(creation_tournaments, "catalogue", lambda *_: {catalogue_ref(t).key: t for t in teams})
    hub = Mock()
    monkeypatch.setattr(creation_tournaments, "run_league_hub", hub)
    creation.run_creation_menu(ctx)
    assert hub.call_args.kwargs["preview"] is True
    engine = hub.call_args.args[1]
    assert engine.TITLE == "Mi liga" and engine.rounds_count == 6
    library = CreationLibrary(ctx.paths.saves_dir / "creaciones" / "biblioteca.json")
    assert next(iter(library.drafts.values())).team_count == 3


def test_text_entry_reads_ime_characters_without_filling_speech_history(monkeypatch) -> None:
    backend = NullSpeechBackend()
    voice = SpeechService([backend])
    window = GameWindow(voice, headless=True)
    ui = SimpleNamespace(speech=voice, window=window)
    events = iter((
        pygame.event.Event(pygame.TEXTINPUT, text="Época,"),
        pygame.event.Event(pygame.TEXTINPUT, text=" Puebla"),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN),
    ))
    monkeypatch.setattr(window, "wait_text_event", lambda: next(events))
    assert text_entry(ui, "Nombre") == "Época, Puebla"
    assert any("Época, Puebla" in line for line, _ in backend.spoken)
    assert voice.history == []


def test_issue_url_has_no_credential_and_never_exposes_full_local_path() -> None:
    url = urlparse(issue_url(_club("Época & Puebla"), "aporte.zip"))
    assert url.scheme == "https" and url.netloc == "github.com"
    query = parse_qs(url.query)
    assert query["title"] == ["Aporte de equipo: Época & Puebla"]
    assert "aporte.zip" in query["body"][0]
