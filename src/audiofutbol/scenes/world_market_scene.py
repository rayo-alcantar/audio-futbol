"""Spoken scout filters and the calendar-driven market desk."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from audiofutbol.domain.competitions.career_core import FIRST_YEAR, SEASON_DAYS, career_date
from audiofutbol.domain.competitions.career_recruitment import RecruitmentFilter, player_age, search_players
from audiofutbol.domain.competitions.career_transfer_desk import OPEN, TransferTalk
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.domain.models import POSITION_NAMES_ES
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.career_management import MenuAction, money, open_menu
from audiofutbol.scenes.world_career_ui import _pick, choose_world_league
from audiofutbol.ui.text_entry import text_entry

_STATES = {
    "pending": "esperando respuesta", "counter": "contraoferta", "offered": "oferta recibida",
    "agreed": "acuerdo por confirmar", "closed": "cerrada", "expired": "vencida",
    "rejected": "rechazada", "withdrawn": "retirada",
}


def _date(elapsed: int) -> str:
    year, day = divmod(elapsed, SEASON_DAYS)
    return career_date(FIRST_YEAR + year, day)


def _money(career: WorldCareer, amount: int) -> str:
    return money(amount, career.currency)


def _amount(ctx: GameContext, prompt: str, initial: int) -> int | None:
    value = text_entry(ctx.ui, prompt + ". Importe en euros, sin decimales", str(initial), max_length=13)
    if value is None:
        return None
    clean = re.sub(r"[ .]", "", value)
    if not re.fullmatch(r"[0-9]{1,10}", clean) or not 0 < int(clean) <= 2_000_000_000:
        ctx.ui.speak("El importe no es válido.")
        return None
    return int(clean)


def _range(ctx: GameContext, name: str, current: tuple[int, int], limits: tuple[int, int]) -> tuple[int, int] | None:
    entered = text_entry(ctx.ui, f"{name}. Escribe un valor o un rango con guion. Vacío para todos",
                         "" if current == limits else f"{current[0]}-{current[1]}", max_length=12)
    if entered is None:
        return None
    if not entered:
        return limits
    parsed = re.fullmatch(r"([0-9]{1,2})(?:\s*-\s*([0-9]{1,2}))?", entered)
    if not parsed:
        ctx.ui.speak("Escribe un valor como 75 o un rango como 75 guion 90.")
        return None
    a, b = int(parsed[1]), int(parsed[2] or parsed[1])
    if not limits[0] <= a <= b <= limits[1]:
        ctx.ui.speak(f"El rango debe estar entre {limits[0]} y {limits[1]}.")
        return None
    return a, b


def _results(ctx: GameContext, career: WorldCareer, filters: RecruitmentFilter, changed: Callable[[], None]) -> None:
    ctx.ui.speak("Buscando jugadores.")
    candidates = search_players(career, filters)
    if not candidates:
        ctx.ui.speak("No encontré jugadores con estos filtros.")
        return
    shown = candidates[:180]
    label = f"{len(candidates)} resultados"
    if len(candidates) > len(shown):
        label += f". Primeros {len(shown)}; ajusta los filtros para acotar"
    labels = []
    for seller, p, value in shown:
        age, estimated = player_age(p, career.year)
        age_label = f"{age} años" + (" de juego" if estimated else "")
        labels.append(f"{p.name}, {seller.name}, {POSITION_NAMES_ES[p.position]}, "
                      f"media {p.overall}, {age_label}. Valor orientativo {_money(career, value)}.")
    selected = _pick(ctx, label, labels)
    if selected is None:
        return
    seller, player, reference = shown[selected]
    if not career.window:
        ctx.ui.speak("Puedes consultar jugadores fuera de la ventana, pero no presentar ofertas.")
        return
    amount = _amount(ctx, f"Oferta a {seller.name} por {player.name}", min(reference, career.market.balance))
    if amount is None or not ctx.ui.confirm(f"¿Enviar una oferta de {_money(career, amount)}? El dinero no se retira aún."):
        return
    try:
        talk = career.negotiations.bid(career, seller, player, amount)
    except ValueError as exc:
        ctx.ui.speak(str(exc))
        return
    ctx.ui.speak(f"Oferta enviada. Respuesta prevista: {_date(talk.response_due)}. No se movió dinero.")
    changed()


def _filter_menu(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    filters = RecruitmentFilter()
    cursor = 0

    def text(field: str, title: str) -> None:
        nonlocal filters
        value = text_entry(ctx.ui, title + ". Vacío para todos", getattr(filters, field), max_length=55)
        if value is not None:
            filters = replace(filters, **{field: value})

    def league() -> None:
        nonlocal filters
        kind = ctx.ui.menu("Filtrar por liga", ["Elegir una liga", "Todas las ligas", "Volver"])
        if kind == 0 and (key := choose_world_league(ctx, career.leagues)):
            filters = replace(filters, league=key)
        elif kind == 1:
            filters = replace(filters, league=None)

    def position() -> None:
        nonlocal filters
        keys = [None, *POSITION_NAMES_ES]
        selected = ctx.ui.menu("Posición", ["Todas", *POSITION_NAMES_ES.values(), "Volver"])
        if selected is not None and selected < len(keys):
            filters = replace(filters, position=keys[selected])

    def bracket(ages: bool) -> None:
        nonlocal filters
        current = (filters.min_age, filters.max_age) if ages else (filters.min_overall, filters.max_overall)
        value = _range(ctx, "Edad" if ages else "Media", current, (15, 99) if ages else (1, 99))
        if value:
            filters = replace(filters, min_age=value[0], max_age=value[1]) if ages else replace(
                filters, min_overall=value[0], max_overall=value[1])

    def toggle() -> None:
        nonlocal filters
        filters = replace(filters, affordable=not filters.affordable)

    def reset() -> None:
        nonlocal filters
        filters = RecruitmentFilter()
        ctx.ui.speak("Filtros restablecidos.")

    while True:
        league_label = career.leagues[filters.league].title if filters.league else "todas"
        idx = open_menu(ctx, "Buscar jugadores. Los filtros se pueden combinar", [
            ("Ver resultados", lambda: _results(ctx, career, filters, changed)),
            (f"Nombre: {filters.name or 'todos'}", lambda: text("name", "Nombre del jugador")),
            (f"Liga: {league_label}", league),
            (f"Club: {filters.club or 'todos'}", lambda: text("club", "Nombre del club")),
            (f"Posición: {POSITION_NAMES_ES.get(filters.position, 'todas')}", position),
            (f"Edad: {filters.min_age} a {filters.max_age}", lambda: bracket(True)),
            (f"Media: {filters.min_overall} a {filters.max_overall}", lambda: bracket(False)),
            (f"Solo dentro del presupuesto: {'sí' if filters.affordable else 'no'}", toggle),
            ("Limpiar filtros", reset),
        ], cursor)
        if idx is None:
            return
        cursor = idx


def _description(career: WorldCareer, talk: TransferTalk) -> str:
    other = talk.seller if talk.buying else talk.buyer
    detail = f". Respuesta prevista: {_date(talk.response_due)}" if talk.state == "pending" else ""
    if talk.state in OPEN:
        detail += f". Vence: {_date(talk.expires)}"
    return (f"{'Compra' if talk.buying else 'Venta'} de {talk.player}, {other}. {_STATES[talk.state]}. "
            f"{_money(career, talk.amount)}{detail}")


def _open_talk(ctx: GameContext, career: WorldCareer, talk: TransferTalk, changed: Callable[[], None]) -> None:
    def act(action: str) -> None:
        try:
            if action == "close" and ctx.ui.confirm(f"¿Cerrar el traspaso por {_money(career, talk.amount)}?"):
                career.negotiations.close(career, talk)
                ctx.ui.speak("Traspaso cerrado. Se actualizaron ambos presupuestos y plantillas.")
            elif action == "counter":
                amount = _amount(ctx, "Enviar contraoferta", talk.amount)
                if amount is None or not ctx.ui.confirm(f"¿Enviar {_money(career, amount)} como contraoferta?"):
                    return
                career.negotiations.counter(career, talk, amount)
                ctx.ui.speak(f"Contraoferta enviada. Respuesta prevista: {_date(talk.response_due)}.")
            elif action == "withdraw" and ctx.ui.confirm("¿Retirar o rechazar esta negociación?"):
                career.negotiations.withdraw(career, talk)
                ctx.ui.speak("Negociación cerrada sin cambiar el presupuesto.")
            else:
                return
        except ValueError as exc:
            ctx.ui.speak(str(exc))
            return
        changed()

    options: list[MenuAction] = []
    if career.window and talk.state in ("counter", "offered", "agreed"):
        options.append(("Aceptar y cerrar el traspaso", lambda: act("close")))
        if talk.state != "agreed" and talk.rounds < 3:
            options.append(("Enviar contraoferta", lambda: act("counter")))
    if talk.state in OPEN:
        options.append(("Rechazar o retirar", lambda: act("withdraw")))
    options.append(("Leer el estado", lambda: ctx.ui.reader("Detalles", [
        _description(career, talk), talk.reason or "La IA todavía no ha respondido.",
    ])))
    open_menu(ctx, _description(career, talk), options)


def _desk(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    while True:
        talks = sorted(career.negotiations.for_club(career.managed), key=lambda t: (t.state not in OPEN, -t.id))
        if not talks:
            ctx.ui.speak("No hay negociaciones todavía. Envía una oferta o avanza el calendario.")
            return
        pick = _pick(ctx, "Negociaciones. Primero las que siguen abiertas",
                     [_description(career, t) for t in talks])
        if pick is None:
            return
        _open_talk(ctx, career, talks[pick], changed)


def transfer_wait(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    previous = career.inbox[-1:]
    days = career.wait_days(7, stop_on_news=True)
    if not days:
        ctx.ui.speak("No se puede avanzar más sin resolver la próxima jornada o cerrar la temporada.")
        return
    ctx.ui.speak(f"Avanzaste {days} día{'s' if days != 1 else ''}. {career_date(career.year, career.day)}.")
    if career.inbox[-1:] != previous:
        ctx.ui.speak(career.inbox[-1].text)
    changed()


def finances(ctx: GameContext, career: WorldCareer) -> None:
    ctx.ui.reader("Dinero del club", [
        f"Presupuesto disponible: {_money(career, career.market.balance)}.",
        *[f"{career_date(x.year, x.day)}. {x.reason}. {'Ingreso' if x.amount >= 0 else 'Gasto'}: "
          f"{_money(career, abs(x.amount))}. Saldo: {_money(career, x.balance)}."
          for x in reversed(career.market.ledger)],
    ])


def run_world_market(ctx: GameContext, career: WorldCareer, changed: Callable[[], None]) -> None:
    cursor = 0
    while True:
        active = sum(t.state in OPEN for t in career.negotiations.for_club(career.managed))
        window = f"Ventana {career.window}" if career.window else "Mercado cerrado"
        idx = open_menu(ctx, f"Fichajes. {window}. Disponible: {_money(career, career.market.balance)}", [
            ("Buscar jugadores y filtrar", lambda: _filter_menu(ctx, career, changed)),
            (f"Negociaciones: {active} abiertas", lambda: _desk(ctx, career, changed)),
            ("Avanzar días hasta novedades", lambda: transfer_wait(ctx, career, changed)),
            ("Dinero y movimientos", lambda: finances(ctx, career)),
        ], cursor)
        if idx is None:
            return
        cursor = idx
