"""Audio-first club, transfer and youth menus for the manager career."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from audiofutbol.domain.competitions.career_core import ManagerCareer, career_date
from audiofutbol.domain.competitions.career_academy import SCOUT_COST
from audiofutbol.domain.competitions.career_market import transfer_value
from audiofutbol.domain.competitions.career_squad import can_release, can_sign, club_key, copy_tactics, season_copy
from audiofutbol.domain.competitions.world_career import WorldCareer
from audiofutbol.domain.match.state import MatchState
from audiofutbol.domain.match.tactics import TacticsManager
from audiofutbol.domain.models import POSITION_NAMES_ES, Player
from audiofutbol.scenes.base import GameContext
from audiofutbol.scenes.match_scene import PygameMatchIO
from audiofutbol.ui.text_entry import text_entry
from audiofutbol.ui.widgets import squad_lines

MenuAction = tuple[str, Callable[[], None]]


def open_menu(ctx: GameContext, title: str, actions: list[MenuAction], initial: int = 0) -> int | None:
    choice = ctx.ui.menu(title, [label for label, _ in actions] + ["Volver"], initial_index=initial)
    if choice is None or choice == len(actions):
        return None
    actions[choice][1]()
    return choice


def money(amount: int, currency: str = "reales") -> str:
    millions, rest = divmod(amount, 1_000_000)
    thousands, units = divmod(rest, 1_000)
    parts = []
    if millions:
        parts.append("un millón" if millions == 1 else f"{millions} millones")
    if thousands:
        parts.append("mil" if thousands == 1 else f"{thousands} mil")
    if units or not parts:
        parts.append(str(units))
    return f"{' '.join(parts)} {currency}"


def _player_label(player: Player) -> str:
    return f"{player.name}, {POSITION_NAMES_ES[player.position]}, media {player.overall}"


def _buy(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    price_text = partial(money, currency=career.currency)
    filters = [("Todas las posiciones", None), *(
        (name.capitalize(), position) for position, name in POSITION_NAMES_ES.items()
    )]
    choice = ctx.ui.menu("Buscar fichajes. Elige posición", [label for label, _ in filters] + ["Volver"])
    if choice is None or choice == len(filters):
        return
    query = text_entry(ctx.ui, "Nombre o club. Déjalo vacío para ver todos", max_length=55)
    if query is None:
        return
    query = club_key(query)
    position = filters[choice][1]
    candidates = []
    for seller in career.clubs.values():
        if seller is career.club:
            continue
        club_matches = query in club_key(seller.name)
        for player in seller.players:
            if position is not None and player.position != position:
                continue
            if not club_matches and query not in club_key(player.name):
                continue
            asking = transfer_value(player)
            if (asking * 94 // 100 <= career.market.balance and can_release(seller, player)
                    and can_sign(career.club, player.name)):
                candidates.append((seller, player, asking))
    if not candidates:
        ctx.ui.speak("No hay jugadores disponibles para esa búsqueda dentro de tu presupuesto.")
        return
    candidates.sort(key=lambda item: (-item[1].overall, item[2], club_key(item[1].name)))
    index = 0
    page_size = 9
    while True:
        page = candidates[index:index + page_size]
        labels = [f"{_player_label(p)}, {t.name}, precio de referencia {price_text(cost)}" for t, p, cost in page]
        nav = []
        if index:
            nav.append(("Página anterior", index - page_size))
        if index + page_size < len(candidates):
            nav.append(("Página siguiente", index + page_size))
        choice = ctx.ui.menu(
            f"Fichajes. Resultados {index + 1} a {index + len(page)} de {len(candidates)}",
            labels + [label for label, _ in nav] + ["Volver"],
        )
        if choice is None or choice == len(page) + len(nav):
            return
        if choice >= len(page):
            index = nav[choice - len(page)][1]
            continue
        seller, player, price = page[choice]
        bids = [n for n in (price * 70 // 100, price * 85 // 100, price) if n <= career.market.balance]
        offer = ctx.ui.menu(f"Oferta por {player.name}. Disponible: {price_text(career.market.balance)}",
                            [price_text(n) for n in bids] + ["Cancelar"])
        if offer is None or offer == len(bids):
            continue
        bid = bids[offer]
        if not ctx.ui.confirm(f"¿Ofrecer {price_text(bid)} a {seller.name} por {player.name}?"):
            continue
        try:
            status, fee = career.buy(seller, player, bid)
            if status == "counter":
                if not ctx.ui.confirm(f"{seller.name} pide {price_text(fee)}. ¿Aceptar la contraoferta?"):
                    ctx.ui.speak("Negociación cancelada. No se movió dinero.")
                    continue
                status, fee = career.buy(seller, player, bid, accept_counter=True)
        except ValueError as exc:
            ctx.ui.speak(str(exc))
            continue
        if status == "accepted":
            ctx.ui.speak(f"Fichaje confirmado. {player.name} llega por {price_text(fee)}.")
            changed()
            return
        ctx.ui.speak("El club rechazó la oferta. Puedes intentar un importe mayor.")


def _sell(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    price_text = partial(money, currency=career.currency)
    offers = [(p, offer) for p in career.club.players if (offer := career.sale_offer(p)) is not None]
    if not offers:
        ctx.ui.speak("No hay ofertas que mantengan la profundidad de tu plantilla.")
        return
    choice = ctx.ui.menu("Ofertas por tus jugadores", [
        f"{_player_label(p)}. {buyer.name} ofrece {price_text(fee)}" for p, (buyer, fee) in offers
    ] + ["Volver"])
    if choice is None or choice == len(offers):
        return
    player, (buyer, fee) = offers[choice]
    if not ctx.ui.confirm(f"¿Vender a {player.name} a {buyer.name} por {price_text(fee)}?"):
        return
    try:
        buyer, fee = career.sell(player)
    except ValueError as exc:
        ctx.ui.speak(str(exc))
        return
    ctx.ui.speak(f"Venta confirmada a {buyer.name} por {price_text(fee)}.")
    changed()


def _market(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    price_text = partial(money, currency=career.currency)
    cursor = 0
    while True:
        window = f"Ventana {career.window} abierta" if career.window else (
            "Mercado cerrado. Abre al inicio, a mitad de temporada y al terminar"
        )
        actions = []
        if career.window:
            actions.extend([
                ("Buscar y fichar jugadores", lambda: _buy(ctx, career, changed)),
                ("Ofertas por mis jugadores", lambda: _sell(ctx, career, changed)),
            ])
        actions.append(("Consultar movimientos", lambda: ctx.ui.reader(
            "Movimientos del presupuesto", [
                f"{career_date(entry.year, entry.day)}. {entry.reason}. "
                f"{'Ingreso' if entry.amount >= 0 else 'Gasto'}: {price_text(abs(entry.amount))}. "
                f"Saldo: {price_text(entry.balance)}."
                for entry in reversed(career.market.ledger)
            ] or ["Aún no hay movimientos."]
        )))
        index = open_menu(ctx, f"Fichajes. {window}. Presupuesto: {price_text(career.market.balance)}", actions, cursor)
        if index is None:
            return
        cursor = index


def _academy(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    price_text = partial(money, currency=career.currency)

    def scout() -> None:
        if reason := career.academy.scout_blocker(career.elapsed, career.market.balance):
            ctx.ui.speak(reason)
            return
        if not ctx.ui.confirm(f"¿Enviar al ojeador por {price_text(SCOUT_COST)}? Evaluará tres juveniles."):
            return
        try:
            career.scout()
        except ValueError as exc:
            ctx.ui.speak(str(exc))
            return
        ctx.ui.speak("Informe listo. Consulta los tres juveniles en Ver juveniles.")
        changed()

    def prospects() -> None:
        players = career.academy.prospects
        if not players:
            ctx.ui.speak("No hay juveniles. Envía al ojeador para encontrar candidatos.")
            return
        labels = [
            f"{p.name}, {POSITION_NAMES_ES[p.position]}, {career.year - p.born} años, "
            f"media {p.overall}, potencial {p.potential}" for p in players
        ]
        index = ctx.ui.menu("Juveniles. Elige uno para gestionarlo", labels + ["Volver"])
        if index is None or index == len(players):
            return
        p = players[index]

        def promote() -> None:
            if career.year - p.born < 16:
                ctx.ui.speak("Todavía no tiene 16 años.")
                return
            if not ctx.ui.confirm(f"¿Subir a {p.name} al primer equipo?"):
                return
            try:
                player = career.promote(p)
            except ValueError as exc:
                ctx.ui.speak(str(exc))
                return
            ctx.ui.speak(f"{player.name} subió al primer equipo con el dorsal {player.number}.")
            changed()

        def release() -> None:
            if ctx.ui.confirm(f"¿Dar de baja a {p.name} de la cantera?"):
                career.academy.release(p)
                career.notify(f"{p.name} dejó la cantera.")
                ctx.ui.speak(f"{p.name} dejó la cantera.")
                changed()

        open_menu(ctx, labels[index], [("Subir al primer equipo", promote), ("Dar de baja", release)])

    cursor = 0
    while True:
        index = open_menu(ctx, f"Cantera. {len(career.academy.prospects)} juveniles", [
            ("Ver juveniles", prospects), ("Enviar ojeador", scout),
        ], cursor)
        if index is None:
            return
        cursor = index


def _edit_tactics(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    draft = season_copy(career.club)
    opponent = next(club for club in career.clubs.values() if club is not career.club)
    io = PygameMatchIO(ctx)
    load = None
    if isinstance(career, WorldCareer):
        fixture = next((f for f in career.agenda() if f.user_index is not None), None)
        day = career.elapsed + (fixture.day - career.day if fixture else 0)
        load = career.fitness.prepare(draft, day)
    state = MatchState(draft, season_copy(opponent), ctx.match_settings(), yellow_card_limit=3)
    if load is not None:
        state.enable_workload((load, {}))
    tactics = TacticsManager(state, io, lambda: {}, io.speak)
    try:
        if not tactics.menu(club_setup=True):
            ctx.ui.speak("No se cambiaron las tácticas del club.")
            return
        copy_tactics(draft, career.club)
        career.refresh_clubs(career.club)
        ctx.ui.speak("Táctica del club aplicada a los próximos partidos.")
        changed()
    finally:
        ctx.window.update_status("")


def run_club_menu(ctx: GameContext, career: ManagerCareer, changed: Callable[[], None]) -> None:
    from audiofutbol.scenes.world_market_scene import run_world_market
    from audiofutbol.scenes.world_match_ui import read_fitness, run_change_plans

    cursor = 0
    while True:
        items: list[MenuAction] = [
            ("Plantilla del primer equipo", lambda: ctx.ui.reader(career.club.name, squad_lines(career.club))),
            ("Editar esquema y alineación", lambda: _edit_tactics(ctx, career, changed)),
            ("Cantera", lambda: _academy(ctx, career, changed)),
        ]
        if isinstance(career, WorldCareer):
            items[2:2] = [
                ("Fichajes y presupuesto", lambda: run_world_market(ctx, career, changed)),
                ("Parte médico y cansancio", lambda: read_fitness(ctx, career)),
                ("Cambios por situación", lambda: run_change_plans(ctx, career, changed)),
            ]
        else:
            items.insert(2, ("Fichajes y presupuesto", lambda: _market(ctx, career, changed)))
        index = open_menu(ctx, "Gestión del club", items, cursor)
        if index is None:
            return
        cursor = index
