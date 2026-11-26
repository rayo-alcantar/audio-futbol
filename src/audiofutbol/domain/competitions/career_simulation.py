"""Fast football simulation for the career; interactive play uses the full match engine."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import exp
from random import Random

from audiofutbol.domain.formations import DEFAULT_SCHEME, SCHEME_STYLE, choose_ai_scheme
from audiofutbol.domain.match.conditional_changes import ConditionalChange
from audiofutbol.domain.models import MatchResult, Player, Team


@dataclass(frozen=True)
class TeamProfile:
    attack: float
    midfield: float
    defence: float


def _average(xi: list[Player], positions: set[str], fallback: float) -> float:
    ratings = [p.overall for p in xi if p.position in positions]
    return sum(ratings) / len(ratings) if ratings else fallback - 8


def profile(team: Team, xi: list[Player]) -> TeamProfile:
    fallback = sum(p.overall for p in xi) / max(1, len(xi))
    att, mid, def_ = SCHEME_STYLE.get(team.scheme or DEFAULT_SCHEME, SCHEME_STYLE[DEFAULT_SCHEME])
    missing = max(0, 11 - len(xi))
    return TeamProfile(
        _average(xi, {"DEL"}, fallback) + att + team.mentality - 1.6 * missing,
        _average(xi, {"MED"}, fallback) + mid - 1.1 * missing,
        .8 * _average(xi, {"DEF"}, fallback) + .2 * _average(xi, {"POR"}, fallback)
        + def_ - team.mentality - 1.3 * missing,
    )


def expected_goals(
    home: TeamProfile, away: TeamProfile, home_form: float = 0, away_form: float = 0,
    *, neutral: bool = False,
) -> tuple[float, float]:
    def against(first: TeamProfile, second: TeamProfile, advantage: float, form: float) -> float:
        attack = first.attack - second.defence
        control = first.midfield - second.midfield
        exponent = max(-1.6, min(1.6, .035 * attack + .014 * control + form * .035 + advantage))
        return max(.18, min(4.1, 1.19 * exp(exponent)))

    return against(home, away, 0 if neutral else .16, home_form), against(away, home, 0 if neutral else -.10, away_form)


def poisson(rng: Random, rate: float) -> int:
    remaining = exp(-rate)
    product = rng.random()
    goals = 0
    while product > remaining:
        goals += 1
        product *= rng.random()
    return goals


def _record_goal(rng: Random, side: Team, xi: list[Player], minute: int, result: MatchResult) -> None:
    outfield = [p for p in xi if p.position != "POR"] or xi
    if not outfield:
        return
    weights = [max(1, p.overall - 38) * {"POR": 1, "DEF": 3, "MED": 8, "DEL": 16}[p.position]
               for p in outfield]
    scorer = rng.choices(outfield, weights)[0]
    scorer.goals += 1
    result.scorers.append((side, scorer, minute))
    candidates = [p for p in outfield if p is not scorer]
    if candidates and rng.random() < .72:
        assist = rng.choices(candidates, [3 if p.position == "MED" else 1 for p in candidates])[0]
        assist.assists += 1
        result.assists.append((side, assist, minute))


def _discipline(rng: Random, side: Team, participants: list[Player], yellow_limit: int) -> int:
    for player in side.players:
        player.suspended_matches = max(0, player.suspended_matches - 1)
    yellows = rng.sample(participants, min(len(participants), poisson(rng, 1.65 + .13 * side.mentality)))
    for player in yellows:
        player.yellow_cards += 1
        if player.yellow_cards >= yellow_limit:
            player.yellow_cards = 0
            player.suspended_matches += 1
    return len(yellows)


@dataclass
class _Side:
    original: Team
    tactics: Team
    xi: list[Player]
    bench: list[Player]
    initial_load: dict[str, float]
    plan: list[ConditionalChange]
    managed: bool
    minutes: dict[str, int] = field(default_factory=dict)
    injuries: list[str] = field(default_factory=list)
    sent_off: list[Player] = field(default_factory=list)
    used: int = 0

    def fatigue(self, player: Player) -> float:
        return min(100., self.initial_load.get(player.name, 0.) +
                   self.minutes.get(player.name, 0) * (.45 if player.position == "POR" else .76))

    def quality(self) -> TeamProfile:
        base = profile(self.tactics, self.xi)
        penalty = sum(max(0., self.fatigue(p) - 28) for p in self.xi) / max(1, len(self.xi)) * .10
        return TeamProfile(base.attack - penalty, base.midfield - penalty, base.defence - penalty)

    def swap(self, outgoing: Player, incoming: Player, result: MatchResult, minute: int, reason: str) -> None:
        if self.used >= 5:
            return
        self.xi[self.xi.index(outgoing)] = incoming
        self.bench.remove(incoming)
        self.used += 1
        result.highlights.append((minute, f"Cambio {reason} en {self.original.name}: "
                                          f"sale {outgoing.name}, entra {incoming.name}."))

    def maybe_send_off(self, minute: int, rng: Random, result: MatchResult) -> None:
        candidates = [p for p in self.xi if p.position != "POR"]
        if candidates and len(self.xi) > 7 and rng.random() < .010:
            player = rng.choice(candidates)
            self.xi.remove(player)
            self.sent_off.append(player)
            result.highlights.append((minute, f"Expulsión de {player.name}, de {self.original.name}."))

    def apply_plan(
        self, minute: int, margin: int, advantage: int, result: MatchResult, *, only_player: Player | None = None,
    ) -> bool:
        changed = False
        for rule in sorted(self.plan, key=lambda r: (r.condition != "injured", r.minute)):
            players = rule.players(self.xi, self.bench)
            if players is None or self.used >= 5:
                continue
            out, incoming = players
            if ((only_player is not None and out is not only_player)
                    or (out.position == "POR") != (incoming.position == "POR")):
                continue
            if rule.matches(minute, margin, self.fatigue(out),
                            injured=out.name in self.injuries, red_card_advantage=advantage):
                reason = "programado por lesión" if out.name in self.injuries else "programado"
                self.swap(out, incoming, result, minute, reason)
                self.plan.remove(rule)
                changed = True
        return changed

    def injury_or_changes(self, minute: int, margin: int, advantage: int, rng: Random, result: MatchResult) -> None:
        if 0 < minute < 90 and minute % 15 == 0 and self.xi and len(self.injuries) < 2:
            injured = rng.choices(self.xi, weights=[1 + self.fatigue(p) / 28 for p in self.xi])[0]
            if rng.random() < .009 + max(0., self.fatigue(injured) - 45) * .00055:
                self.injuries.append(injured.name)
                result.highlights.append((minute, f"Lesión de {injured.name}, de {self.original.name}."))
                bench = [p for p in self.bench if (p.position == "POR") == (injured.position == "POR")]
                if not self.apply_plan(minute, margin, advantage, result, only_player=injured):
                    if self.used < 5 and bench:
                        self.swap(injured, max(bench, key=lambda p: (p.position == injured.position, p.overall)),
                                  result, minute, "por lesión")
                    else:
                        self.xi.remove(injured)
        self.apply_plan(minute, margin, advantage, result)
        if not self.managed and 60 <= minute < 90 and self.used < 3:
            candidates = [p for p in self.xi if p.position != "POR"]
            if candidates:
                out = max(candidates, key=self.fatigue)
                same = [p for p in self.bench if p.position == out.position]
                if self.fatigue(out) >= 51 and same:
                    self.swap(out, max(same, key=lambda p: p.overall), result, minute, "táctico")


def quick_match(
    home: Team, away: Team, rng: Random, form: tuple[float, float], yellow_limit: int,
    controlled: Team | None = None, *, fatigue: tuple[dict[str, float], dict[str, float]] | None = None,
    changes: list[ConditionalChange] | None = None, neutral: bool = False,
) -> MatchResult:
    def side(team: Team, rival: Team, load: dict[str, float]) -> _Side:
        managed = team is controlled
        own, other = team.strength(), rival.strength()
        mentality = -1 if own + 4 < other else 1 if own > other + 4 else 0
        tactics = team if managed else replace(team, scheme=choose_ai_scheme(own, other, rng), mentality=mentality)
        xi = tactics.lineup()
        bench = [p for p in team.players if p.available and p not in xi]
        return _Side(team, tactics, xi, bench, load, list(changes or []) if managed else [], managed)

    load = fatigue or ({}, {})
    sides = side(home, away, load[0]), side(away, home, load[1])
    goals, shots, on_target = [0, 0], [0, 0], [0, 0]
    home_control = 0.
    result = MatchResult((0, 0))
    times = sorted({0, 15, 30, 45, 60, 75, 90} | {r.minute for r in changes or [] if 0 < r.minute < 90})
    for start, end in zip(times, times[1:]):
        if start and start % 15 == 0:
            for s in sides:
                s.maybe_send_off(start, rng, result)
        for i, s in enumerate(sides):
            s.injury_or_changes(start, goals[i] - goals[1 - i], len(sides[1 - i].sent_off) - len(s.sent_off),
                                rng, result)
        span = end - start
        a, b = (s.quality() for s in sides)
        home_control += span * max(.29, min(.71, .50 + (a.midfield - b.midfield) * .008 + rng.uniform(-.04, .04)))
        rates = expected_goals(a, b, *form, neutral=neutral)
        for i, s in enumerate(sides):
            if not s.xi:
                continue
            for player in s.xi:
                s.minutes[player.name] = s.minutes.get(player.name, 0) + span
            volume = min(22., 8. + rates[i] * 3.6)
            accuracy = min(.53, .30 + rates[i] * .052)
            conversion = min(.55, rates[i] / (volume * accuracy))
            for minute in sorted(rng.randint(start + 1, end) for _ in range(poisson(rng, volume * span / 90))):
                shots[i] += 1
                if rng.random() >= accuracy:
                    continue
                on_target[i] += 1
                if rng.random() < conversion:
                    goals[i] += 1
                    _record_goal(rng, s.original, s.xi, minute, result)

    result.goals = goals[0], goals[1]
    cards = [_discipline(rng, s.tactics, [p for p in s.original.players if p.name in s.minutes], yellow_limit)
             for s in sides]
    result.yellow_cards = cards[0], cards[1]
    result.red_cards = len(sides[0].sent_off), len(sides[1].sent_off)
    for s in sides:
        for player in s.sent_off:
            player.suspended_matches += 1
    result.fair_play = tuple(y + 3 * r for y, r in zip(result.yellow_cards, result.red_cards))
    possession = round(home_control * 100 / 90)
    result.statistics = {
        "Posesión": (possession, 100 - possession), "Tiros": tuple(shots), "A puerta": tuple(on_target),
        "Paradas": (on_target[1] - goals[1], on_target[0] - goals[0]),
        "Cambios": (sides[0].used, sides[1].used),
    }
    result.minutes = sides[0].minutes, sides[1].minutes
    result.injuries = tuple(sides[0].injuries), tuple(sides[1].injuries)
    for s in sides:
        for rule in s.plan:
            result.highlights.append((90, f"Cambio pendiente no ejecutado: {rule.outgoing} por {rule.incoming}. "
                                          "No se cumplió la condición o los jugadores no estaban disponibles."))
    ratings = []
    for i, s in enumerate(sides):
        side_ratings = {}
        for p in s.original.players:
            if s.minutes.get(p.name, 0) <= 0:
                continue
            n_goals = sum(pl is p for _, pl, _ in result.scorers)
            n_assists = sum(pl is p for _, pl, _ in result.assists)
            defending = .35 if p.position in ("POR", "DEF") and not goals[1 - i] else .0
            saves = min(.9, (on_target[1 - i] - goals[1 - i]) * .10) if p.position == "POR" else 0.
            impact = (goals[i] - goals[1 - i]) * .10
            rating = 6.1 + rng.uniform(-.27, .27) + impact + n_goals * .86 + n_assists * .44 + defending + saves
            side_ratings[p.name] = round(max(4., min(10., rating)), 1)
        ratings.append(side_ratings)
    result.ratings = ratings[0], ratings[1]
    return result
