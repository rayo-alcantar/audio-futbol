"""Spoken match log entries keep results and events independent of mutable squads."""

from __future__ import annotations

from dataclasses import dataclass

from audiofutbol.domain.models import MatchResult, Team, format_result_text


@dataclass(frozen=True)
class MatchLog:
    year: int
    day: int
    title: str
    score: str
    mvp: str
    lines: list[str]
    simulated: bool
    takeaway: str = ""


def _takeaway(sides: tuple[Team, Team], result: MatchResult) -> str:
    if result.abandoned:
        return "Se registró un abandono."
    a, b = result.goals
    if result.penalties:
        return "El cruce se resolvió en la tanda de penales."
    if a == b:
        if not a:
            chances = sum(result.statistics.get("A puerta", (0, 0)))
            return f"Empate sin goles; hubo {chances} tiros a puerta en total."
        return "El partido terminó igualado."
    winner = 0 if a > b else 1
    score = [0, 0]
    behind = False
    for team, _, _ in sorted(result.scorers, key=lambda goal: goal[2]):
        score[0 if team is sides[0] else 1] += 1
        if score[winner] < score[1 - winner]:
            behind = True
    winning_goals = [minute for team, _, minute in result.scorers if team is sides[winner]]
    name = sides[winner].name
    if behind:
        return f"{name} remontó después de ir perdiendo."
    if abs(a - b) == 1 and max(winning_goals, default=0) >= 80:
        return f"{name} aseguró el resultado con un gol en el tramo final."
    shots = result.statistics.get("Tiros", (0, 0))
    if shots[winner] + 3 < shots[1 - winner]:
        return f"{name} ganó pese a rematar menos veces."
    if abs(a - b) >= 3:
        return f"{name} ganó con una diferencia amplia."
    return f"{name} se llevó un partido ajustado." if abs(a - b) == 1 else f"{name} se llevó la victoria."


def build_match_log(
    year: int, day: int, title: str, sides: tuple[Team, Team], result: MatchResult, *, simulated: bool,
) -> MatchLog:
    score = format_result_text(*sides, *result.goals, result.penalties)
    candidates = [(rating, name, sides[side].name) for side in range(2)
                  for name, rating in result.ratings[side].items()]
    if candidates and not result.abandoned:
        rating, name, club = max(candidates)
        grade = f"{rating:.1f}".replace(".", ",")
        mvp = f"Figura del partido: {name}, de {club}, nota {grade}."
    elif result.scorers and not result.abandoned:
        scores = {(team.name, p.name) for team, p, _ in result.scorers}
        club, name = max(scores, key=lambda item: (sum(t.name == item[0] and p.name == item[1]
                                                       for t, p, _ in result.scorers), item))
        mvp = f"Figura del partido: {name}, de {club}."
    else:
        mvp = "Sin figura registrada."
    takeaway = _takeaway(sides, result)
    lines = [score, takeaway, mvp]
    for key, values in result.statistics.items():
        suffix = " por ciento" if key == "Posesión" else ""
        lines.append(f"{key}: {sides[0].name} {values[0]}{suffix}; {sides[1].name} {values[1]}{suffix}.")
    for label, values in (("Amarillas", result.yellow_cards), ("Rojas", result.red_cards)):
        lines.append(f"{label}: {sides[0].name} {values[0]}; {sides[1].name} {values[1]}.")
    event_lines = [(minute, f"Minuto {minute}. Gol de {p.name}, de {team.name}.")
                   for team, p, minute in result.scorers]
    event_lines.extend((minute, f"Minuto {minute}. Asistencia de {p.name}, de {team.name}.")
                       for team, p, minute in result.assists)
    event_lines.extend((minute, f"Minuto {minute}. {text}") for minute, text in result.highlights
                       if simulated or text.startswith(("Cambio", "Lesión")))
    lines.extend(line for _, line in sorted(event_lines, key=lambda item: item[0]))
    if simulated:
        for i, team in enumerate(sides):
            best = sorted(result.ratings[i].items(), key=lambda item: (-item[1], item[0]))[:3]
            lines.extend(f"{team.name}. {name}: nota {str(rating).replace('.', ',')}."
                         for name, rating in best)
    return MatchLog(year, day, title, score, mvp, lines, simulated, takeaway)
