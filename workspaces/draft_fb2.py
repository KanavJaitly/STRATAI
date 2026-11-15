"""Phase 11: P11-FB2, the alliance-aware fallback rule for the live draft's recommendations.

The rule is frozen in `.agent/phase11/decisions/P11_FB2_DECISION_2026-11-14.md`, committed before this module existed.
This module implements that record and nothing else; the section numbers below (§) are the record's. A change to any
input, formula, weight, threshold or tie-break is a new rule (P11-FB2.1), not an edit here.

FB2 runs only when the P6-M7 engine refuses (P11-Q1, workspaces.draft_recommendations). It ranks the available teams
for the alliance being advised by what each would add to *that* alliance:

- **per-robot component estimates** at the event, strictly before the selection moment, from the P11A A3 estimator
  (`ml.alliance.estimator`, an unchanged copy, current-event population prior only), on qualification alliance rows
  split into auto / teleop / endgame by the P5-M7 adapter (§2.3);
- **gap filling** against a playoff-level benchmark (§3);
- **Phase 3 reliability and consistency** as a multiplicative factor, never imputed when absent (§3);
- **defense and the decline flag** shown on every card, with no effect on the ranking (§6, §7).

The pure part (`estimate_event`, `rank_for_alliance`) needs no database, so the tests drive it directly. The loader
(`load_rows`) reads canonical matches and the untouched TBA payloads, read-only.

Everything FB2 serves is `not_validated`: it is a rule, not a model of pick quality, and the estimator's own open
questions apply (§9). Nothing here uses an LLM.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ml.alliance.estimator import ESTIMATOR_VERSION, EstimatorError, fit_component
from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
from ml.features.score_components import score_components
from ml.playoffs.selection import CandidateProfile
from workspaces import draft_log as dl

RULE = "P11-FB2"
DECISION = ".agent/phase11/decisions/P11_FB2_DECISION_2026-11-14.md"
SOURCE = "fallback_p11_fb2"

COMPONENTS = ("auto", "teleop", "endgame")
TOTAL = "total"
MODE_COMPONENTS, MODE_TOTAL, MODE_EPA = "components", "total", "epa_components"

# §3: judgment calls, not fitted. Frozen.
FIT_WEIGHT = 0.5
CONSISTENCY_WEIGHT = 0.25
BENCHMARK_TEAMS = 24
MIN_ROWS = 12  # the estimator's own minimum (fit_component raises below it)
MIN_BACKUPS = 3


class Fb2Unavailable(Exception):
    """FB2 cannot project at this event and moment (§2.3: neither mode is available)."""

    code = "fb2_projection_unavailable"


# --- §2.3 rows -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AllianceRow:
    """One qualification alliance: its three teams, its official score, and its components (None without a usable
    breakdown)."""

    match_key: str
    teams: tuple[int, int, int]
    total: int
    components: Mapping[str, int] | None


@dataclass(frozen=True)
class EventRows:
    season: int
    rows: tuple[AllianceRow, ...]
    dq_excluded: int  # alliances left out because TBA lists a disqualified team on them
    malformed: int  # alliances whose breakdown the adapter refused (kept, without components)
    unsupported_season: bool  # the P5-M7 adapter does not cover the season


_ROWS_SQL = """
SELECT m.match_key, m.season, m.score_red, m.score_blue,
       array_agg(mt.team_number ORDER BY mt.team_number) FILTER (WHERE mt.alliance_color = 'red') AS red,
       array_agg(mt.team_number ORDER BY mt.team_number) FILTER (WHERE mt.alliance_color = 'blue') AS blue,
       raw.payload -> 'score_breakdown' -> 'red', raw.payload -> 'score_breakdown' -> 'blue',
       raw.payload -> 'alliances' -> 'red' -> 'dq_team_keys', raw.payload -> 'alliances' -> 'blue' -> 'dq_team_keys'
FROM matches m
JOIN match_teams mt ON mt.match_key = m.match_key
LEFT JOIN LATERAL (
    SELECT r.payload_json AS payload FROM raw_source_payloads r
    WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.source_object_id = m.match_key AND r.is_current
    ORDER BY r.id DESC LIMIT 1
) raw ON TRUE
WHERE m.event_key = %(event)s AND m.competition_level = 'qualification'
  AND m.scheduled_time IS NOT NULL AND m.scheduled_time < %(as_of)s
  AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
GROUP BY m.match_key, m.season, m.score_red, m.score_blue, m.scheduled_time, raw.payload
ORDER BY m.scheduled_time, m.match_key
"""


def load_rows(database: Any, event_key: str, as_of: datetime) -> EventRows:
    """The event's qualification alliance rows strictly before `as_of` (§2.3). Read-only."""
    with database.cursor() as cursor:
        cursor.execute(_ROWS_SQL, {"event": event_key, "as_of": as_of})
        fetched = cursor.fetchall()
    season = int(event_key[:4])
    rows: list[AllianceRow] = []
    dq = malformed = 0
    unsupported = False
    for match_key, match_season, score_red, score_blue, red, blue, b_red, b_blue, dq_red, dq_blue in fetched:
        season = int(match_season)
        for teams, score, breakdown, dq_keys in ((red, score_red, b_red, dq_red), (blue, score_blue, b_blue, dq_blue)):
            if not teams or len(teams) != 3:
                continue
            if isinstance(dq_keys, list) and dq_keys:
                dq += 1
                continue
            components: dict[str, int] | None = None
            if isinstance(breakdown, Mapping) and not unsupported:
                try:
                    parts = score_components(season, breakdown)
                    components = {"auto": parts.auto, "teleop": parts.teleop, "endgame": parts.endgame}
                except UnsupportedSeasonError:
                    unsupported = True
                except ScoreBreakdownSchemaError:
                    malformed += 1
            rows.append(AllianceRow(match_key, (int(teams[0]), int(teams[1]), int(teams[2])), int(score), components))
    return EventRows(season, tuple(rows), dq, malformed, unsupported)


# --- §2.3 estimates --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EventEstimates:
    """Each team's per-component strength at the event, the mode they came from, and the benchmark (§3)."""

    mode: str
    components: tuple[str, ...]
    values: Mapping[int, Mapping[str, float]]  # team -> component -> s_c
    labels: Mapping[int, tuple[str, ...]]  # team -> the estimator's label reasons (shown, never ranked on)
    benchmark: Mapping[str, float]
    mode_reason: str | None  # why total mode or EPA components were used
    rows: int
    estimator_version: str = ESTIMATOR_VERSION
    notes: tuple[str, ...] = ()

    def total(self, team: int) -> float | None:
        values = self.values.get(team)
        return None if values is None else sum(values[c] for c in self.components)


def _fit(component: str, rows: Sequence[AllianceRow], y: Sequence[float]) -> Any:
    teams = sorted({t for r in rows for t in r.teams})
    fit = fit_component(component, [r.teams for r in rows], y, teams)
    if fit.degenerate:
        raise EstimatorError("degenerate", f"{component}: sigma^2 is on the optimizer's lower bound")
    return fit


def _from_fits(fits: Sequence[Any], mode: str, reason: str | None, rows: int, notes: list[str]) -> EventEstimates:
    components = tuple(f.component for f in fits)
    values: dict[int, dict[str, float]] = {}
    labels: dict[int, list[str]] = {}
    for fit in fits:
        for i, team in enumerate(fit.teams):
            values.setdefault(team, {})[fit.component] = float(fit.mean[i])
        for d in fit.diagnostics:
            labels.setdefault(d.team, []).extend(f"{fit.component} {r}" for r in d.label_reasons)
    complete = {t: v for t, v in values.items() if all(c in v for c in components)}
    return EventEstimates(mode, components, complete, {t: tuple(v) for t, v in labels.items()},
                          benchmark(complete, components), reason, rows, notes=tuple(notes))


def estimate_event(event_rows: EventRows, *, switch_passed: bool,
                   epa: Mapping[int, tuple[float | None, float | None, float | None]] | None = None) -> EventEstimates:
    """§2.3: component mode, else total mode, else Fb2Unavailable; EPA components before the switch."""
    notes = []
    if event_rows.dq_excluded:
        notes.append(f"{event_rows.dq_excluded} alliance row(s) left out: TBA lists a disqualified team on them")
    if not switch_passed:
        values = {t: {"auto": a, "teleop": te, "endgame": e} for t, (a, te, e) in (epa or {}).items()
                  if a is not None and te is not None and e is not None}
        if not values:
            raise Fb2Unavailable("the P5-M4 switch point has not passed and no team has EPA components")
        return EventEstimates(MODE_EPA, COMPONENTS, values, {}, benchmark(values, COMPONENTS),
                              "the P5-M4 switch point has not passed", 0, notes=tuple(notes))
    rows = event_rows.rows
    reason: str
    with_parts = [r for r in rows if r.components is not None]
    if event_rows.unsupported_season:
        reason = f"the P5-M7 component adapter does not cover season {event_rows.season}"
    elif len(with_parts) < MIN_ROWS:
        reason = f"only {len(with_parts)} alliance row(s) have a score breakdown; {MIN_ROWS} are needed"
    else:
        try:
            fits = [_fit(c, with_parts, [r.components[c] for r in with_parts]) for c in COMPONENTS]  # type: ignore[index]
            if event_rows.malformed:
                notes.append(f"{event_rows.malformed} alliance row(s) with a malformed breakdown left out of the "
                             "component fits")
            if len(with_parts) < len(rows):
                notes.append(f"{len(rows) - len(with_parts)} alliance row(s) without a usable breakdown left out of "
                             "the component fits")
            return _from_fits(fits, MODE_COMPONENTS, None, len(with_parts), notes)
        except EstimatorError as exc:
            reason = f"the component fit is unavailable ({exc.code}: {exc.message})"
    if len(rows) < MIN_ROWS:
        raise Fb2Unavailable(f"{reason}; the total-score fit needs {MIN_ROWS} alliance rows and has {len(rows)}")
    try:
        fit = _fit(TOTAL, rows, [r.total for r in rows])
    except EstimatorError as exc:
        raise Fb2Unavailable(f"{reason}; the total-score fit is unavailable ({exc.code}: {exc.message})") from exc
    return _from_fits([fit], MODE_TOTAL, reason, len(rows), notes)


def benchmark(values: Mapping[int, Mapping[str, float]], components: Sequence[str]) -> dict[str, float]:
    """§3: B_c, the median s_c over the K = min(24, N) teams with the highest s(t)."""
    if not values:
        return {c: 0.0 for c in components}
    top = sorted(values, key=lambda t: (-sum(values[t][c] for c in components), t))[:min(BENCHMARK_TEAMS, len(values))]
    return {c: float(statistics.median(values[t][c] for t in top)) for c in components}


# --- §3-§7 ranking and cards -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentFit:
    component: str
    estimate: float
    effective: float
    gap: float
    filled: float


@dataclass(frozen=True)
class Card:
    """One team's FB2 result for one alliance at one record state."""

    team_number: int
    rank_score: float | None
    projected: float | None  # V (§3), never adjusted
    robots: tuple[int, ...]  # the robots V counts, the candidate included
    members: tuple[int, ...]  # the alliance members assumed (recorded members, or the projected captain itself)
    fits: tuple[ComponentFit, ...]
    qualification_rank: int | None
    decline_flag: str | None
    reasons: tuple[str, ...]
    fouls_included: bool


@dataclass
class Fb2Lists:
    ranked: list[Card]  # primary + backups
    unranked: list[int]
    excluded: list[tuple[int, str]]
    projections: list[Card]  # every available team: ranked candidates, then excluded, then unranked
    members: tuple[int, ...]
    gaps: dict[str, float]


@dataclass(frozen=True)
class TeamInputs:
    """Phase 3 reliability and consistency and P6-Q11 defense at the selection moment, from the P5-M4 analysis'
    point-in-time features (the profiles), for every rostered team."""

    profiles: Mapping[int, CandidateProfile]

    def factor(self, team: int) -> tuple[float, list[str]]:
        """ρ (§3) and the card's §5 line 4. An absent value contributes 1 and is named, never imputed.

        Phase 3 reports both values from the same matches with the same minimum, so they are present or absent
        together in practice; if only one is absent, the card shows that absence (the template has no mixed line)."""
        profile = self.profiles.get(team)
        rel = profile.reliability if profile else None
        con = profile.consistency if profile else None
        rel_value = rel.value if rel is not None else None
        con_value = con.value if con is not None else None
        rho = 1.0
        if rel_value is not None:
            rho *= rel_value / 100.0
        if con_value is not None:
            rho *= 1.0 - CONSISTENCY_WEIGHT * (1.0 - con_value / 100.0)
        if rel_value is not None and con_value is not None:
            return rho, [f"Reliability {rel_value:.1f}, consistency {con_value:.1f} (n = {rel.n}): counted at "
                         f"{rho:.2f}×."]
        lines = []
        if rel_value is None:
            lines.append(f"Reliability absent ({(rel.reason if rel else None) or 'no Phase 3 value'}): not adjusted "
                         "for it.")
        if con_value is None:
            lines.append(f"Consistency absent ({(con.reason if con else None) or 'no Phase 3 value'}): not adjusted "
                         "for it.")
        return rho, lines

    def defense_line(self, team: int) -> str:
        profile = self.profiles.get(team)
        d = profile.defense if profile else None
        if d is None or d.value is None:
            return "Defense: no scouting."
        return f"Defense {d.value:.1f}/5 from {d.n} observations (descriptive; it does not change the ranking)."


def _members(view: dl.DraftView, seed: int, team_number: int) -> tuple[int, ...]:
    alliance = view.alliances[seed - 1]
    return tuple(alliance) if alliance else (team_number,)


def _projected(members: Sequence[int], candidate: int, est: EventEstimates) -> tuple[float, tuple[int, ...]]:
    """V (§3): the members with an estimate plus the candidate; the best three when that is more than three."""
    robots = [m for m in members if m in est.values] + [candidate]
    if len(robots) > 3:
        robots = sorted(robots, key=lambda t: (-(est.total(t) or 0.0), t))[:3]
    return sum(est.total(t) or 0.0 for t in robots), tuple(robots)


def _fmt(x: float) -> str:
    return f"{x:.1f}"


def _card(team: int, members: tuple[int, ...], gaps: Mapping[str, float], est: EventEstimates, inputs: TeamInputs,
          *, ranks: Mapping[int, int], n_ranked: int, decline: str | None, contribution_rank: Mapping[int, int],
          lead: str | None = None) -> Card:
    """The card for a team with an estimate (§3, §5)."""
    s = est.values[team]
    rho, rel_lines = inputs.factor(team)
    fits = tuple(ComponentFit(c, s[c], s[c] * rho, gaps[c], min(max(s[c] * rho, 0.0), gaps[c])) for c in est.components)
    member_total = sum(est.total(m) or 0.0 for m in members if m in est.values)
    fit_total = sum(f.filled for f in fits)
    rank_score = member_total + sum(f.effective for f in fits) + FIT_WEIGHT * fit_total
    projected, robots = _projected(members, team, est)
    fouls = est.mode == MODE_TOTAL
    reasons: list[str] = [lead] if lead else []
    reasons.append(f"Projected alliance score {_fmt(projected)} with teams {', '.join(map(str, robots))} "
                   f"({'fouls included' if fouls else 'no fouls'}; not validated).")
    reasons.append(f"Estimated contribution {_fmt(sum(s.values()))} pts: "
                   + ", ".join(f"{c} {_fmt(s[c])}" for c in est.components) + ".")
    gap_lines = []
    for f in fits:
        if f.gap > 0 and f.filled > 0:
            gap_lines.append(f"Fills {_fmt(f.filled)} of a {_fmt(f.gap)}-pt {f.component} gap.")
        elif f.gap > 0:
            gap_lines.append(f"Adds nothing to your {f.component} gap.")
    reasons.extend(gap_lines or ["Your alliance has no gap against this event's playoff-level benchmark."])
    reasons.extend(rel_lines)
    reasons.append(inputs.defense_line(team))
    if decline:
        reasons.append(decline)
    rank = ranks.get(team)
    if rank is None:
        reasons.append("No qualification rank in the record.")
    else:
        reasons.append(f"Qualification rank {rank} of {n_ranked}.")
        if rank > math.ceil(n_ranked / 2):
            reasons.append(f"Ranked in the lower half, but its estimated contribution is {contribution_rank[team]} of "
                           f"{len(contribution_rank)} at this event; qualification rank also reflects partners, "
                           "schedule and ranking points.")
    if est.labels.get(team):
        reasons.append("Estimate labels: " + "; ".join(est.labels[team]) + ".")
    if est.mode == MODE_TOTAL:
        reasons.append(f"Ranked on the total score only: {est.mode_reason}.")
    elif est.mode == MODE_EPA:
        reasons.append("Ranked on EPA components: the P5-M4 switch point has not passed.")
    return Card(team, rank_score, projected, robots, members, fits, rank, decline, tuple(reasons), fouls)


def _bare_card(team: int, members: tuple[int, ...], line: str, ranks: Mapping[int, int], decline: str | None) -> Card:
    return Card(team, None, None, (), members, (), ranks.get(team), decline, (line,), False)


def rank_for_alliance(view: dl.DraftView, seed: int, team_number: int, est: EventEstimates, inputs: TeamInputs,
                      excluded: Mapping[int, str]) -> Fb2Lists:
    """§4: FB2's primary + backups, unranked teams, excluded teams, and every available team's card, for `seed`.

    `excluded` is FB1's exclusion map (workspaces.draft_recommendations._excluded), unchanged."""
    available, _ = view.availability()
    ranks = dict(view.setup.ranks or {}) if view.setup is not None else {}
    n_ranked = len(ranks)
    members = _members(view, seed, team_number)
    estimated_members = [m for m in members if m in est.values]
    gaps = {c: (max(0.0, est.benchmark[c] - statistics.fmean(est.values[m][c] for m in estimated_members))
                if estimated_members else 0.0) for c in est.components}
    projected_seed = {captain: other for other, captain in view.projected_captains().items()
                      if captain is not None and other != seed}
    order = sorted(est.values, key=lambda t: (-(est.total(t) or 0.0), t))
    contribution_rank = {t: i for i, t in enumerate(order, start=1)}

    def decline(team: int) -> str | None:
        other = projected_seed.get(team)
        return None if other is None else f"May decline (projected captain of alliance {other})."

    ranked: list[Card] = []
    unranked: list[int] = []
    excluded_cards: list[Card] = []
    for team in available:
        if team in excluded:
            lead = f"Not recommended: {excluded[team]}."
            excluded_cards.append(_card(team, members, gaps, est, inputs, ranks=ranks, n_ranked=n_ranked,
                                        decline=None, contribution_rank=contribution_rank, lead=lead)
                                  if team in est.values else _bare_card(team, members, lead, ranks, None))
        elif team not in est.values:
            unranked.append(team)
        else:
            ranked.append(_card(team, members, gaps, est, inputs, ranks=ranks, n_ranked=n_ranked,
                                decline=decline(team), contribution_rank=contribution_rank))
    ranked.sort(key=lambda c: (-(c.rank_score or 0.0), -(c.projected or 0.0),
                               c.qualification_rank if c.qualification_rank is not None else 10 ** 6, c.team_number))
    unranked.sort()
    m = view.turns_before(seed) or 0
    keep = 1 + max(MIN_BACKUPS, m)
    unranked_cards = [_bare_card(t, members, "No estimate at this event, so never recommended.", ranks, decline(t))
                      for t in unranked]
    return Fb2Lists(ranked[:keep], unranked,
                    sorted(((t, r) for t, r in excluded.items() if t in available), key=lambda tr: tr[0]),
                    ranked + sorted(excluded_cards, key=lambda c: c.team_number) + unranked_cards, members, gaps)


@dataclass(frozen=True)
class Fb2Context:
    """What FB2 needs at one event and moment, computed once and cached with the P5-M4 ordering."""

    estimates: EventEstimates | None
    inputs: TeamInputs
    unavailable: str | None = None  # Fb2Unavailable's message
    timing_ms: Mapping[str, float] = field(default_factory=dict)


__all__ = ["AllianceRow", "BENCHMARK_TEAMS", "COMPONENTS", "CONSISTENCY_WEIGHT", "Card", "ComponentFit", "DECISION",
           "EventEstimates", "EventRows", "FIT_WEIGHT", "Fb2Context", "Fb2Lists", "Fb2Unavailable", "MODE_COMPONENTS",
           "MODE_EPA", "MODE_TOTAL", "RULE", "SOURCE", "TeamInputs", "benchmark", "estimate_event", "load_rows",
           "rank_for_alliance"]
