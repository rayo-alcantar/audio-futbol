"""Safe, versioned JSON persistence for tournament saves with automatic legacy .sav migration."""

from __future__ import annotations

import json
from pathlib import Path
import pickle
from typing import Any

from audiofutbol.domain.competitions.brazil_career import BrazilianCareer
from audiofutbol.domain.competitions.factory import SAVE_SLOTS, deserialize_competition
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.engine.paths import AppPaths

SAVE_SCHEMA_VERSION = 1

_LEGACY_ALLOWED_CLASSES: frozenset[str] = frozenset(
    {
        "Jugador",
        "Equipo",
        "Mundial",
        "LigaNaciones",
        "TorneoClubes",
        "LigaDeCampeones",
        "CopaGrupos",
        "CopaLibertadores",
        "CopaSudamericana",
        "CopaInteramericana",
        "LigaMX",
    }
)

_LEGACY_CLASS_TO_TYPE: dict[str, str] = {
    "Mundial": "mundial",
    "LigaNaciones": "liga",
    "LigaDeCampeones": "champions",
    "CopaLibertadores": "libertadores",
    "CopaSudamericana": "sudamericana",
    "CopaInteramericana": "interamericana",
    "LigaMX": "ligamx",
}


class _LegacyPlaceholder:
    """Inert container for restricted legacy pickle deserialization."""

    __legacy_class__: str = ""


class _RestrictedLegacyUnpickler(pickle.Unpickler):
    """Restricted unpickler that only allows inert v0.2–v0.14 game data classes."""

    def find_class(self, module: str, name: str) -> Any:
        if module in ("__main__", "audiofutbol") and name in _LEGACY_ALLOWED_CLASSES:
            return type(
                name,
                (_LegacyPlaceholder,),
                {"__legacy_class__": name},
            )
        raise pickle.UnpicklingError(f"Forbidden class in legacy save: {module}.{name}")


def _legacy_team_name(team_obj: Any) -> str:
    if isinstance(team_obj, str):
        return team_obj
    return str(getattr(team_obj, "nombre", getattr(team_obj, "name", "")))


def _convert_legacy_player(p_obj: Any) -> dict[str, Any]:
    raw = p_obj.__dict__ if hasattr(p_obj, "__dict__") else dict(p_obj)
    return {
        "name": str(raw.get("nombre", raw.get("name", "Jugador"))),
        "position": str(raw.get("pos", raw.get("position", "MED"))),
        "overall": int(raw.get("ovr", raw.get("overall", 70))),
        "number": int(raw.get("numero", raw.get("number", 0))),
        "yellow_cards": int(raw.get("amarillas", raw.get("yellow_cards", 0))),
        "suspended_matches": int(raw.get("suspendido", raw.get("suspended_matches", 0))),
        "goals": int(raw.get("goles", raw.get("goals", 0))),
    }


def _convert_legacy_team(t_obj: Any) -> dict[str, Any]:
    raw = t_obj.__dict__ if hasattr(t_obj, "__dict__") else dict(t_obj)
    players = raw.get("jugadores", raw.get("players", []))
    return {
        "name": str(raw.get("nombre", raw.get("name", "Equipo"))),
        "players": [_convert_legacy_player(p) for p in players],
        "team_id": str(raw.get("id", raw.get("team_id", ""))),
        "country": str(raw.get("pais", raw.get("country", ""))),
        "stadium": raw.get("estadio", raw.get("stadium")),
        "city": str(raw.get("ciudad", raw.get("city", ""))),
        "group": raw.get("grupo", raw.get("group")),
        "level": int(raw.get("nivel", raw.get("level", 72))),
        "is_real_squad": bool(raw.get("real", raw.get("is_real_squad", False))),
    }


def _convert_legacy_tie(c: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "x": _legacy_team_name(c["x"]),
        "y": _legacy_team_name(c["y"]),
        "r1": list(c["r1"]) if c.get("r1") is not None else None,
        "r2": list(c["r2"]) if c.get("r2") is not None else None,
        "pen": list(c["pen"]) if c.get("pen") is not None else None,
        "forzado": _legacy_team_name(c["forzado"]) if c.get("forzado") is not None else None,
    }
    if "pot" in c:
        out["pot"] = c["pot"]
    if "fin" in c:
        out["fin"] = bool(c["fin"])
    return out


def convert_legacy_object_to_dict(obj: Any, slot_key: str) -> dict[str, Any]:
    """Convert an unpickled v0.2–v0.14 competition instance into the v0.15 JSON dict format."""
    if isinstance(obj, dict):
        return obj.get("competition", obj)

    raw = obj.__dict__
    cls_name = getattr(obj, "__legacy_class__", type(obj).__name__)
    comp_type = _LEGACY_CLASS_TO_TYPE.get(cls_name, slot_key)

    teams_raw = raw.get("equipos", raw.get("teams", []))
    teams_dict = [_convert_legacy_team(t) for t in teams_raw]
    user_team_name = _legacy_team_name(raw.get("mi", raw.get("user_team", "")))
    user_eliminated = bool(raw.get("mi_eliminado", raw.get("user_eliminated", False)))
    tiebreaker_rnd = {
        str(k): float(v)
        for k, v in raw.get("rnd", raw.get("tiebreaker_rnd", {})).items()
    }
    table = raw.get("tabla", raw.get("table", {}))
    history = [
        [
            str(ph),
            _legacy_team_name(a),
            _legacy_team_name(b),
            int(ga),
            int(gb),
            list(pen) if pen else None,
        ]
        for ph, a, b, ga, gb, pen in raw.get("hist", raw.get("history", []))
    ]
    pairs = [
        [_legacy_team_name(a), _legacy_team_name(b)]
        for a, b in raw.get("pares", raw.get("pairs", []))
    ]
    completed = {
        str(k): {
            "ga": int(v["ga"]),
            "gb": int(v["gb"]),
            "pen": list(v["pen"]) if v.get("pen") else None,
        }
        for k, v in raw.get("hechos", raw.get("completed", {})).items()
    }
    champ_raw = raw.get("campeon", raw.get("champion"))
    champion = _legacy_team_name(champ_raw) if champ_raw is not None else None

    if comp_type == "mundial":
        groups = [
            [_legacy_team_name(t) for t in g]
            for g in raw.get("grupos", raw.get("groups", []))
        ]
        podium_raw = raw.get("podio", raw.get("podium"))
        third_raw = raw.get("tercero", raw.get("third_place"))
        return {
            "type": "mundial",
            "teams": teams_dict,
            "user_team": user_team_name,
            "user_eliminated": user_eliminated,
            "tiebreaker_rnd": tiebreaker_rnd,
            "table": table,
            "history": history,
            "draw_lines": list(raw.get("lineas_sorteo", raw.get("draw_lines", []))),
            "groups": groups,
            "group_count": int(raw.get("G", raw.get("group_count", len(groups)))),
            "phases": [
                [str(p[0]), str(p[1]), int(p[2])]
                for p in raw.get("fases", raw.get("phases", []))
            ],
            "phase_idx": int(raw.get("fase", raw.get("phase_idx", 0))),
            "pairs": pairs,
            "completed": completed,
            "alive": [
                _legacy_team_name(t) for t in raw.get("vivos", raw.get("alive", []))
            ],
            "semi_winners": [
                _legacy_team_name(t)
                for t in raw.get("ganadores_semi", raw.get("semi_winners", []))
            ],
            "semi_losers": [
                _legacy_team_name(t)
                for t in raw.get("perdedores_semi", raw.get("semi_losers", []))
            ],
            "third_place": _legacy_team_name(third_raw) if third_raw is not None else None,
            "champion": champion,
            "podium": [_legacy_team_name(t) for t in podium_raw] if podium_raw else None,
            "qualified_thirds": [
                _legacy_team_name(t)
                for t in raw.get("terceros_q", raw.get("qualified_thirds", []))
            ],
        }

    # Nations League and Club Tournaments
    agg_raw = raw.get("globales", raw.get("aggregates", {}))
    aggregates = {
        str(k): [
            _legacy_team_name(v[0]),
            int(v[1]),
            _legacy_team_name(v[2]),
            int(v[3]),
        ]
        for k, v in agg_raw.items()
    }
    schedule = [
        [[_legacy_team_name(a), _legacy_team_name(b)] for a, b in rnd]
        for rnd in raw.get("calendario", raw.get("schedule", []))
    ]
    steps = [
        [str(s[0]), s[1]] for s in raw.get("pasos", raw.get("steps", []))
    ]
    ties = [_convert_legacy_tie(c) for c in raw.get("cruces", raw.get("ties", []))]
    runner_raw = raw.get("subcampeon", raw.get("runner_up"))
    groups_raw = raw.get("grupos", raw.get("groups"))
    venue_raw = raw.get("SEDE_FINAL_DATOS", raw.get("final_venue"))

    out_dict: dict[str, Any] = {
        "type": comp_type,
        "teams": teams_dict,
        "user_team": user_team_name,
        "away_goals_rule": bool(raw.get("visitante", raw.get("away_goals_rule", False))),
        "rounds_count": int(raw.get("jornadas", raw.get("rounds_count", len(schedule)))),
        "qualify_count": int(raw.get("pasan", raw.get("qualify_count", 8))),
        "user_eliminated": user_eliminated,
        "tiebreaker_rnd": tiebreaker_rnd,
        "table": table,
        "history": history,
        "aggregates": aggregates,
        "schedule": schedule,
        "steps": steps,
        "step_idx": int(raw.get("paso", raw.get("step_idx", 0))),
        "ties": ties,
        "ranking": {str(k): int(v) for k, v in raw.get("ranking", {}).items()},
        "qualified": [
            _legacy_team_name(t)
            for t in raw.get("clasificados", raw.get("qualified", []))
        ],
        "pairs": pairs,
        "completed": completed,
        "champion": champion,
        "runner_up": _legacy_team_name(runner_raw) if runner_raw is not None else None,
        "groups": [
            [_legacy_team_name(t) for t in g] for g in groups_raw
        ]
        if groups_raw is not None
        else None,
    }
    if venue_raw:
        out_dict["final_venue"] = [str(venue_raw[0]), str(venue_raw[1])]
    if comp_type == "champions":
        out_dict["direct_qualifiers"] = [
            _legacy_team_name(t)
            for t in raw.get("directos", raw.get("direct_qualifiers", []))
        ]
    return out_dict


class SaveManager:
    """Persists and restores competitions as UTF-8 JSON inside `saves/` (with legacy `.sav` support)."""

    def __init__(self, paths: AppPaths) -> None:
        self.base_dir: Path = paths.base_dir
        self.saves_dir: Path = paths.saves_dir

    def slot_path(self, key: str) -> Path:
        return self.saves_dir / f"partida_{key}.json"

    def legacy_candidates(self, key: str) -> list[Path]:
        """Candidate paths where legacy `.sav` or root `.json` files may reside."""
        if key in (BrazilianCareer.KEY, WorldCareer.KEY):
            return []
        return [
            self.base_dir / f"partida_{key}.json",
            self.saves_dir / f"partida_{key}.sav",
            self.base_dir / f"partida_{key}.sav",
        ]

    def exists(self, key: str) -> bool:
        if self.slot_path(key).is_file():
            return True
        return any(p.is_file() for p in self.legacy_candidates(key))

    def list_saved_slots(self) -> list[tuple[str, str]]:
        return [(key, label) for key, label in SAVE_SLOTS if self.exists(key)]

    def save(self, key: str, competition: Any) -> bool:
        try:
            self.saves_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": SAVE_SCHEMA_VERSION,
                "competition": competition.to_dict(),
            }
            target = self.slot_path(key)
            tmp = target.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            tmp.replace(target)
            return True
        except Exception:
            return False

    def _load_file(self, path: Path, key: str) -> Any | None:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            raw = payload.get("competition", payload)
            return deserialize_competition(raw)

        # Legacy pickle (.sav) from v0.2–v0.14
        with path.open("rb") as fh:
            legacy_obj = _RestrictedLegacyUnpickler(fh).load()
        comp_dict = convert_legacy_object_to_dict(legacy_obj, key)
        comp = deserialize_competition(comp_dict)
        # Upgrade in-place to modern JSON inside saves/ so future loads are instant
        self.save(key, comp)
        return comp

    def load(self, key: str) -> Any | None:
        candidates = [self.slot_path(key), *self.legacy_candidates(key)]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                loaded = self._load_file(candidate, key)
                if loaded is not None:
                    return loaded
            except Exception:
                continue
        return None

    def delete(self, key: str) -> None:
        for target in (self.slot_path(key), *self.legacy_candidates(key)):
            try:
                if target.is_file():
                    target.unlink()
            except Exception:
                pass
