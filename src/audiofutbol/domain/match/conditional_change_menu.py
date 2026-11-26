"""Edit a substitution plan through the same spoken MatchIO in career and normal play."""

from __future__ import annotations

from collections.abc import Callable

from audiofutbol.domain.formations import preferred_role_text
from audiofutbol.domain.match.conditional_changes import CONDITIONS, MAX_PLANNED_CHANGES, ConditionalChange
from audiofutbol.domain.match.ports import MatchIO
from audiofutbol.domain.models import Player


def _pick(io: MatchIO, title: str, labels: list[str]) -> int | None:
    start = 0
    while labels:
        page = labels[start:start + 9]
        nav = []
        if start:
            nav.append(("Página anterior", start - 9))
        if start + len(page) < len(labels):
            nav.append(("Página siguiente", start + 9))
        choice = io.choose(title, [*page, *(label for label, _ in nav), "Volver"])
        if choice is None or choice == len(page) + len(nav):
            return None
        if choice < len(page):
            return start + choice
        start = nav[choice - len(page)][1]
    return None


def _make_rule(
    io: MatchIO, xi: list[Player], bench: list[Player], minute: int,
    role_for: Callable[[Player], str],
) -> ConditionalChange | None:
    def label(p: Player) -> str:
        return f"{p.name}, {preferred_role_text(p)}, media {p.overall}"

    pick = _pick(io, "¿Quién sale? Jugadores en el once", [label(p) for p in xi])
    if pick is None:
        return None
    out = xi[pick]
    available = [p for p in bench if p.available and (p.position == "POR") == (role_for(out) == "POR")]
    available.sort(key=lambda p: (p.position != role_for(out), -p.overall, p.name))
    if not available:
        io.speak("No hay suplentes compatibles disponibles.")
        return None
    take = _pick(io, f"¿Quién entra por {out.name}?", [label(p) for p in available])
    if take is None:
        return None
    conditions = list(CONDITIONS)
    condition = _pick(io, "¿En qué situación harás el cambio?", list(CONDITIONS.values()))
    if condition is None:
        return None
    minutes = [minute, *(m for m in (15, 30, 45, 55, 60, 65, 70, 75, 80, 85, 90, 100, 110)
                         if minute < m < (90 if minute < 90 else 120))]
    times = [("Desde el inicio" if m == 0 else f"Desde el minuto {m}") for m in minutes]
    when = _pick(io, "¿Desde qué minuto?", times)
    if when is None:
        return None
    rule = ConditionalChange(minutes[when], conditions[condition], out.name, available[take].name)
    return rule if io.confirm(f"¿Programar el cambio? {rule.describe()}") else None


def edit_change_plan(
    io: MatchIO, xi: list[Player], bench: list[Player], current: list[ConditionalChange],
    *, minute: int = 0, role_for: Callable[[Player], str] | None = None,
) -> list[ConditionalChange]:
    rules = current.copy()
    role = role_for or (lambda player: player.position)
    while True:
        can_add = len(rules) < MAX_PLANNED_CHANGES
        options = (["Programar cambio"] if can_add else []) + [r.describe() for r in rules]
        choice = _pick(io, f"Cambios por situación. {len(rules)} de {MAX_PLANNED_CHANGES} programados", options)
        if choice is None:
            return sorted(rules, key=lambda r: r.minute)
        index = choice - int(can_add)
        if index < 0:
            if rule := _make_rule(io, xi, bench, minute, role):
                if rule not in rules:
                    rules.append(rule)
                    io.speak("Cambio programado.")
                else:
                    io.speak("Ese cambio ya está programado.")
            continue
        rule = rules[index]
        action = _pick(io, rule.describe(), ["Editar este cambio", "Quitar este cambio"])
        if action == 0 and (updated := _make_rule(io, xi, bench, minute, role)):
            if updated == rule or updated not in rules:
                rules[index] = updated
                io.speak("Cambio actualizado.")
            else:
                io.speak("Ese cambio ya está programado.")
        elif action == 1 and io.confirm(f"¿Quitar este cambio? {rule.describe()}"):
            rules.pop(index)
            io.speak("Cambio quitado.")
