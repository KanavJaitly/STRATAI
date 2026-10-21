"""P9-M2: the pre-match report as an ordered list of identified facts.

A fact is the smallest statement a briefing may make. Each one:
- carries a stable id;
- carries the exact value strings it may mention (`values`);
- traces to the report field it came from (`source`, a JSON path);
- is either a stated value, an explicit absence, an unproduced item, or context.

The LLM formatter (P9-M3) is given only these facts and must cite them; its output is checked against their
`values`.

Rules (P9 spec, standing rules):
- Nothing is computed beyond formatting. Numbers are the served values, rounded for reading as the dashboard rounds
  them (1 decimal, 2 for the 0-5 scouting scale, 3 for synergy), with a served sd shown as "± sd". A validated M6/M7
  value is shown as a percentage, as Phase 8 shows it.
- Every caveat the dashboard shows next to a value is part of that value's fact: served labels and their reasons
  (`validation.reasons`), the calibration status, the strategy's selection note and its comparison with the baseline,
  and how the moment was chosen (`as_of_source`). A briefing that states the value states its caveats with it.
- An **unvalidated** M6/M7 value is stated only as existing and unvalidated. **Its number is not stated**, so it can
  never be read as a probability.
- Every null is an absence fact with its served reason code. The six unproduced items are `not_produced` facts with
  their served semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
import math
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Literal

FactKind = Literal["context", "value", "absence", "not_produced", "label"]

# Fixed wording of the templates that contains digits but no data: model names and the scouting scale. The only
# digit-bearing text a briefing may contain that is not one of a cited fact's values (P9-M3's validator uses this).
TEMPLATE_CONSTANTS = ("M6/M7", "P6-M10", "0-5")

NOT_PRODUCED_TITLES = {
    "strengths_and_weaknesses": "Strengths and weaknesses per robot",
    "defensive_threats": "Defensive threats",
    "key_risks": "Key risks",
    "predicted_flow": "Predicted flow",
    "critical_matchups": "Critical matchups",
    "key_success_factors": "Key success factors",
}
EPA_PARTS = (("total", "EPA total"), ("auto", "auto EPA"), ("teleop", "teleop EPA"), ("endgame", "endgame EPA"))
SCORING_MEASURES = (("average_score", "average alliance score"), ("consistency_rating", "consistency rating"),
                    ("reliability_score", "reliability (an INTERIM attendance ratio, not a robot-failure measure)"))


@dataclass(frozen=True)
class Fact:
    id: str
    kind: FactKind
    section: str  # match | red | blue | forecast | strategy | not_produced | source
    statement: str  # the deterministic sentence
    values: tuple[str, ...] = field(default=())  # every token a sentence citing this fact may state
    source: str = ""  # JSON path in the pre-match report


def number(value: float, digits: int = 1) -> str:
    """A served number, rounded for reading exactly as the dashboard shows it (P8 `formatNumber`, i.e. `Intl` in the
    en-US locale): the shortest round-trip decimal of the value, rounded half away from zero, trailing zeros dropped,
    thousands grouped with commas. 8.25 -> '8.3', 1.005 -> '1.01' (2 digits), 150.0 -> '150', 1234.5 -> '1,234.5'. So
    the briefing and an en-US dashboard never state different digits for the same served value (checked against
    Intl in tests/test_phase9_briefing.py)."""
    quantum = Decimal(1).scaleb(-digits)
    with localcontext() as context:
        context.prec = 400  # enough for any float's integer digits: quantize never overflows (review R2 C3)
        rounded = Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP)
    text = format(rounded, ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text  # -0.04 -> '-0', as Intl prints it


def percent(probability: float) -> str:
    """A probability as the dashboard prints it: `Math.round(p * 100)` (half rounds up), not Python's half-to-even
    `round` (0.125 -> '13%', as on screen; review R2 C3)."""
    return f"{math.floor(probability * 100 + 0.5)}%"


def _measure_fact(fid: str, section: str, subject: str, what: str, measure: dict[str, Any], source: str,
                  digits: int = 1) -> Fact:
    if measure.get("value") is None:
        reason = measure.get("absent_reason") or "not available"
        return Fact(fid, "absence", section, f"{subject}: {what} is not available ({reason}).", (reason,), source)
    value = number(measure["value"], digits)
    n = measure.get("n")
    uncertainty = measure.get("uncertainty") or {}
    sd = number(uncertainty["value"], digits) if uncertainty.get("kind") == "sd" and uncertainty.get("value") is not None \
        else None
    tail = (f" ± {sd}" if sd is not None else "") + (f" (n = {n})" if n is not None else "")
    values = (value,) + ((sd,) if sd is not None else ()) + ((str(n),) if n is not None else ())
    return Fact(fid, "value", section, f"{subject}: {what} {value}{tail}.", values, source)


def _team_facts(i: int, team: dict[str, Any]) -> list[Fact]:
    side, number_ = team["alliance"], team["team_number"]
    subject = f"Team {number_} ({side})"
    base = f"teams[{i}].strength"
    view = team["strength"]
    facts: list[Fact] = []
    epa = view["epa"]
    if epa.get("withheld_reason"):
        facts.append(Fact(f"{side}.{number_}.epa", "absence", side,
                          f"{subject}: no EPA is available ({epa['withheld_reason']}).",
                          (str(number_), epa["withheld_reason"]), f"{base}.epa"))
    else:
        for part, label in EPA_PARTS:
            facts.append(_measure_fact(f"{side}.{number_}.epa.{part}", side, subject, label, epa[part],
                                       f"{base}.epa.{part}"))
    for key, label in SCORING_MEASURES:
        facts.append(_measure_fact(f"{side}.{number_}.{key}", side, subject, label, view["scoring"][key],
                                   f"{base}.scoring.{key}"))
    for kind in ("defense", "feeding"):
        scouting = view[kind]
        fact = _measure_fact(f"{side}.{number_}.{kind}", side, subject,
                             f"{kind} score (0-5, from scouting observations only)", scouting["score"],
                             f"{base}.{kind}.score", digits=2)
        agreement = _measure_fact("", side, "", "scout agreement", scouting["agreement"], "", digits=2)
        clause = agreement.statement[2:-1]  # "scout agreement 0.5 (n = 3)" or "scout agreement is not available (…)"
        status = scouting.get("validation_status")
        text = fact.statement[:-1] + f"; {clause}" + (f"; label {status}" if status else "") + "."
        facts.append(Fact(fact.id, fact.kind, fact.section, text,
                          fact.values + agreement.values + ((status,) if status else ()), fact.source))
    facts.append(_labels_fact(i, team, side, number_, subject))
    return [_with_team(f, number_) for f in facts]


def _labels_fact(i: int, team: dict[str, Any], side: str, number_: int, subject: str) -> Fact:
    """The labels the dashboard shows beside a team's figures: the EPA label and source, the scoring label, and the
    team's validation status with its qualifiers (review R2 C4)."""
    view = team["strength"]
    epa, scoring = view["epa"], view["scoring"]
    source = ", ".join(str(x) for x in (epa.get("epa_value_source"),
                                         epa.get("source_event_key") and f"from {epa['source_event_key']}",
                                         epa.get("epa_source_state")) if x) or "no source"
    validation = team.get("validation") or {}
    reasons = list(validation.get("reasons") or [])
    labels = [epa.get("validation_status") or "descriptive", scoring.get("validation_status") or "descriptive",
              validation.get("status") or "descriptive"]
    text = (f"{subject}: EPA label {labels[0]} (source: {source}); scoring label {labels[1]}; overall label "
            f"{labels[2]}" + (f", with the qualifiers {', '.join(reasons)}" if reasons else "") + ".")
    values = tuple(dict.fromkeys([*labels, *reasons, *(str(x) for x in (epa.get("epa_value_source"),
                                                                         epa.get("source_event_key"),
                                                                         epa.get("epa_source_state")) if x)]))
    return Fact(f"{side}.{number_}.labels", "label", side, text, values, f"teams[{i}]")


def _with_team(fact: Fact, team: int) -> Fact:
    return fact if str(team) in fact.values else Fact(fact.id, fact.kind, fact.section, fact.statement,
                                                       (str(team),) + fact.values, fact.source)


def _synergy_facts(i: int, entry: dict[str, Any]) -> list[Fact]:
    side = entry["alliance"]
    label = entry["validation"]["status"]
    source = f"synergy[{i}]"
    score = entry.get("score")
    if score is None:
        reason = entry.get("absent_code") or "not available"
        return [Fact(f"{side}.synergy", "absence", side, f"{side.capitalize()} alliance synergy is not available "
                     f"({reason}).", (reason,), source)]
    if score.get("overall_score") is None:
        return [Fact(f"{side}.synergy", "absence", side, f"{side.capitalize()} alliance synergy: the overall score is "
                     f"not available (inputs absent); label {label}.", ("inputs absent", label), f"{source}.score")]
    value = number(score["overall_score"], 3)  # the dashboard's SynergyView precision
    confidence = number(score["confidence"], 2)
    return [Fact(f"{side}.synergy", "value", side, f"{side.capitalize()} alliance synergy: overall score {value} "
                 f"(a descriptive index); label {label}; confidence {confidence} (the share of each term's possible "
                 "evidence that is present).", (value, label, confidence), f"{source}.score.overall_score")]


def _win_probability_facts(section: dict[str, Any]) -> list[Fact]:
    scope = section["probability_scope"]
    value = section.get("value")
    if value is None:
        reason = section.get("absent_code") or "not available"
        return [Fact("forecast.win_probability", "absence", "forecast",
                     f"Match win probability (the M6/M7 statistical model, {scope} scope) is not available ({reason}).",
                     (reason, scope), "win_probability")]
    status = value["validation"]["status"]
    calibration = value.get("calibration_status")
    reasons = list(value["validation"].get("reasons") or [])
    caveats = (f"; calibration status {calibration}" if calibration else "") + \
        (f"; qualifiers {', '.join(reasons)}" if reasons else "")
    if value.get("validated_value") is not None:
        shown = percent(value["validated_value"])
        return [Fact("forecast.win_probability", "value", "forecast",
                     f"Match win probability for red (the M6/M7 statistical model, {scope} scope): {shown}; "
                     f"label {status}{caveats}.", (shown, status, scope, *([calibration] if calibration else []),
                                                *reasons), "win_probability.value.validated_value")]
    reason = value.get("unvalidated_reason") or "not validated"
    # The unvalidated number is deliberately not stated: it must never be read as a probability. Its label, reasons,
    # calibration status and scope are (review R2 C4).
    return [Fact("forecast.win_probability", "label", "forecast",
                 f"The M6/M7 statistical model gives only an unvalidated output for this match ({reason}); it is not "
                 f"a validated probability and no number is reported here ({scope} scope; label {status}{caveats}).",
                 tuple(dict.fromkeys((reason, status, scope, *([calibration] if calibration else []), *reasons))),
                 "win_probability.value")]


def _role(robot: dict[str, Any]) -> str:
    """A robot's role as the dashboard shows it: the teleop role and the phases it scores in (review R2 C4)."""
    role = robot.get("role") or "scoring"
    components = robot.get("components")
    scores_in = ", ".join(components if components is not None else ["auto", "teleop", "endgame"]) or "none"
    if role == "defense":
        return f"defense on {robot.get('defense_target')}, scores in {scores_in}"
    if role == "feeding":
        return f"feeding {robot.get('feed_target')}, scores in {scores_in}"
    return f"scoring ({scores_in})"


def _strategy_facts(section: dict[str, Any]) -> list[Fact]:
    if section.get("absent_code"):
        code = section["absent_code"]
        return [Fact("strategy", "absence", "strategy", f"The match strategy is not available ({code}).", (code,),
                     "strategy")]
    facts: list[Fact] = []
    for i, side in enumerate(section["sides"]):
        name = side["side"]
        plan, kind = (side.get("recommended"), "AI recommendation") if side.get("recommended") else \
            (side.get("baseline"), "baseline")
        if plan is None:
            reasons = ", ".join(side.get("unavailable_reasons") or ["not available"])
            facts.append(Fact(f"strategy.{name}", "absence", "strategy",
                              f"{name.capitalize()} strategy: the engine gives no strategy ({reasons}).",
                              tuple(side.get("unavailable_reasons") or ["not available"]), f"strategy.sides[{i}]"))
            continue
        robots = plan["strategy"]["robots"]
        roles = "; ".join(f"{r['team_number']}: {_role(r)}" for r in robots)
        odds = plan["odds"]
        label = odds["validation"]["status"]
        reasons = list(odds["validation"].get("reasons") or [])
        qualifiers = f"; qualifiers {', '.join(reasons)}" if reasons else ""
        values = tuple(str(r["team_number"]) for r in robots) + tuple(
            str(r[t]) for r in robots for t in ("defense_target", "feed_target") if r.get(t)) + (label, *reasons)
        if odds.get("display") is not None:
            text = (f"{name.capitalize()} {kind}: {roles}. Odds of winning under it: {odds['display']} (label {label}"
                    f"{qualifiers}; the strategy model's odds, a separate model from the match win probability).")
            values += (odds["display"],)
        else:
            text = f"{name.capitalize()} {kind}: {roles}. The engine gives no odds for it (label {label}{qualifiers})."
        if side.get("unavailable_reasons"):  # shown beside a baseline-only plan too (review R2 C4)
            text += f" The engine gives no probability: {', '.join(side['unavailable_reasons'])}."
            values += tuple(side["unavailable_reasons"])
        if kind == "AI recommendation":
            notes = [n for n in (side.get("selection_note"),
                                 f"versus the baseline: {side['vs_baseline_label']}" if side.get("vs_baseline_label")
                                 else None) if n]
            if notes:
                text += f" Note: {'; '.join(notes)}."
        facts.append(Fact(f"strategy.{name}", "value", "strategy", text, values,
                          f"strategy.sides[{i}].{'recommended' if kind == 'AI recommendation' else 'baseline'}"))
    context = section.get("context")
    if context is not None and facts:
        applied = context.get("coach_observations_applied", 0)
        facts.append(Fact("strategy.coach_observations", "context", "strategy",
                          f"Coach observations applied to the strategy inputs: {applied}.", (str(applied),),
                          "strategy.context.coach_observations_applied"))
    return facts


_AS_OF_SOURCE = {"requested": " (the requested moment)", "scheduled_time": " (the scheduled time)",
                 "now": " (now)"}


def report_facts(report: dict[str, Any]) -> list[Fact]:
    """Every fact a briefing may state about this report, in reading order."""
    red, blue = report["red_team_numbers"], report["blue_team_numbers"]
    level = report.get("competition_level") or "unknown level"
    facts = [Fact("match", "context", "match",
                  f"Match {report['match_key']} at {report['event_key']} ({level}), scheduled "
                  f"{report['scheduled_time']}; this briefing uses data available at {report['as_of']}"
                  f"{_AS_OF_SOURCE.get(report.get('as_of_source'), '')}.",
                  (report["match_key"], report["event_key"], level, report["scheduled_time"], report["as_of"]),
                  "match_key"),
             Fact("alliances", "context", "match",
                  f"Red alliance: {', '.join(map(str, red))}. Blue alliance: {', '.join(map(str, blue))}.",
                  tuple(map(str, red + blue)), "red_team_numbers")]
    for i, team in enumerate(report["teams"]):
        facts += _team_facts(i, team)
    for i, entry in enumerate(report["synergy"]):
        facts += _synergy_facts(i, entry)
    facts += _win_probability_facts(report["win_probability"])
    facts += _strategy_facts(report["strategy"])
    for key, title in NOT_PRODUCED_TITLES.items():
        semantics = report["not_produced"][key]["semantics"]
        facts.append(Fact(f"not_produced.{key}", "not_produced", "not_produced",
                          f"{title}: not produced by any engine. (What it would mean: {semantics})", (),
                          f"not_produced.{key}"))
    epa = report["epa"]
    flags = epa.get("validation_flags") or []
    facts.append(Fact("source.epa", "context", "source",
                      f"EPA source {epa['epa_source']}"
                      + ("" if epa.get("evaluated_configuration") else " (not the configuration the models were evaluated on)")
                      + (f"; flags: {', '.join(flags)}" if flags else "") + ".",
                      (epa["epa_source"], *flags), "epa"))
    _assert_unique(facts)
    return [_with_own_codes(f) for f in facts]


CODE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _with_own_codes(fact: Fact) -> Fact:
    """Every snake_case code a fact's own statement contains (served labels, reasons, codes) is one of its values, so
    a sentence may repeat it. Numbers are not added this way: a fact's numbers are exactly the ones declared above."""
    codes = tuple(c for c in dict.fromkeys(CODE.findall(fact.statement)) if c not in fact.values)
    return fact if not codes else Fact(fact.id, fact.kind, fact.section, fact.statement, fact.values + codes,
                                       fact.source)


def _assert_unique(facts: list[Fact]) -> None:
    ids = [f.id for f in facts]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate fact ids: {sorted(duplicates)}")
