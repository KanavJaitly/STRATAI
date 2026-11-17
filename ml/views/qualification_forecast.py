"""P5-M5 qualification match forecasts and expected qualification records.

Specification: docs/P5Milestones.md, P5-M5 (frozen at P5-M0); decisions P5-D5 and P5-D9.

* **Per-match probability:**
  - q = the frozen D18 M7 pair's red-win probability, gated exactly as M12;
  - validated only for qualification matches whose six teams all have prior EPA (EPA-complete).
* **Expected wins** = Σ q over the team's qualification matches (blue's q is 1 − q). There is no ranking-point
  projection, because bonus RPs were never modelled.
* **The 80% range** is the central 80% of the exact Poisson-binomial of those q (ml.calibration.gate's recursion).
  Its bounds follow gate.central_interval's convention at 10% / 90%: the smallest k with CDF ≥ 0.10, and the
  smallest k with CDF ≥ 0.90.
* **Labels:**
  - a team-event whose schedule includes an EPA-incomplete match gets its expected record labelled
    `not_validated`;
  - the range is `validated` only if P5-M5 (b)'s single coverage measurement fell within [0.75, 0.85];
  - events in Statbotics weeks 1–3 are `low_confidence`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from database.connection import consistent_reads
from ml.calibration.gate import poisson_binomial_pmf
from ml.features.assembler import EventHistory, MatchFeatureRow, build_match_feature_row
from ml.features.scale import ScaleLookup
from ml.ratings.provider import through_snapshot

RANGE_LOWER, RANGE_UPPER = 0.10, 0.90
COVERAGE_BAND = (0.75, 0.85)  # P5-D9
LOW_CONFIDENCE_WEEKS = frozenset({1, 2, 3})
# Criterion (b)'s single measurement (scripts/phase5_m5_qualification_forecast.py). None means not measured, so
# the range is served not_validated. tests/test_qualification_forecast.py pins it to the record.
RANGE_COVERAGE_VALIDATED: bool | None = False  # p5_m5_qualification_forecast.json: coverage 0.8532
RECORD = ".agent/phase5/results/p5_m5_qualification_forecast.json"

RECORD_VALIDATED = "validated"
NOT_VALIDATED = "not_validated"
REASON_EPA_INCOMPLETE = "schedule_includes_epa_incomplete_match"
REASON_RANGE_COVERAGE = "range_coverage_outside_0.75_0.85"
REASON_RANGE_NOT_MEASURED = "range_coverage_not_measured"


def central_80(pmf: np.ndarray) -> tuple[int, int]:
    """Smallest k with CDF ≥ 0.10 and smallest k with CDF ≥ 0.90 (gate.central_interval's convention)."""
    cdf = np.cumsum(pmf)
    return int(np.searchsorted(cdf, RANGE_LOWER)), int(np.searchsorted(cdf, RANGE_UPPER))


@dataclass(frozen=True)
class MatchForecast:
    match_key: str
    red: tuple[int, ...]
    blue: tuple[int, ...]
    q_red: float
    epa_complete: bool


@dataclass
class TeamRecordForecast:
    team_number: int
    matches: int = 0
    expected_wins: float = 0.0
    win_probabilities: list[float] = field(default_factory=list)
    epa_incomplete_matches: int = 0

    @property
    def range80(self) -> tuple[int, int]:
        return central_80(poisson_binomial_pmf(self.win_probabilities))

    def record_status(self) -> tuple[str, str | None]:
        if self.epa_incomplete_matches:
            return NOT_VALIDATED, REASON_EPA_INCOMPLETE
        return RECORD_VALIDATED, None

    def range_status(self, coverage_validated: bool | None = None) -> tuple[str, str | None]:
        measured = RANGE_COVERAGE_VALIDATED if coverage_validated is None else coverage_validated
        if self.epa_incomplete_matches:
            return NOT_VALIDATED, REASON_EPA_INCOMPLETE
        if measured is None:
            return NOT_VALIDATED, REASON_RANGE_NOT_MEASURED
        return (RECORD_VALIDATED, None) if measured else (NOT_VALIDATED, REASON_RANGE_COVERAGE)


def team_records(matches: Iterable[MatchForecast]) -> dict[int, TeamRecordForecast]:
    """Σ q per team over its qualification matches (blue's win probability is 1 − q)."""
    out: dict[int, TeamRecordForecast] = {}
    for match in matches:
        for teams, q in ((match.red, match.q_red), (match.blue, 1.0 - match.q_red)):
            for team in teams:
                record = out.setdefault(team, TeamRecordForecast(team))
                record.matches += 1
                record.expected_wins += q
                record.win_probabilities.append(q)
                record.epa_incomplete_matches += 0 if match.epa_complete else 1
    return out


def coverage(records: Sequence[tuple[Sequence[float], int]]) -> dict[str, float | int]:
    """Share of team-events whose actual wins fall inside their central 80% range (inclusive)."""
    inside = 0
    for probabilities, actual in records:
        low, high = central_80(poisson_binomial_pmf(probabilities))
        inside += low <= actual <= high
    share = inside / len(records)
    return {"team_events": len(records), "inside": inside, "coverage": share,
            "within_band": COVERAGE_BAND[0] <= share <= COVERAGE_BAND[1]}


def actual_minus_expected(records: Sequence[tuple[Sequence[float], int]]) -> dict[str, float]:
    diffs = np.array([actual - sum(p) for p, actual in records])
    return {"mean_actual_minus_expected": float(diffs.mean()), "mean_abs_actual_minus_expected": float(np.abs(diffs).mean())}


def by_team_event(rows: Iterable[tuple[str, Sequence[int], Sequence[int], float, bool]]
                  ) -> dict[tuple[str, int], tuple[list[float], int]]:
    """(event, red, blue, q, red_won) rows -> {(event, team): (win probabilities, actual wins)}."""
    out: dict[tuple[str, int], tuple[list[float], int]] = defaultdict(lambda: ([], 0))
    for event_key, red, blue, q, red_won in rows:
        for teams, p, won in ((red, q, red_won), (blue, 1.0 - q, not red_won)):
            for team in teams:
                probabilities, wins = out[(event_key, team)]
                probabilities.append(p)
                out[(event_key, team)] = (probabilities, wins + int(won))
    return dict(out)


# --- serving helpers ------------------------------------------------------------------------------

STATBOTICS_WEEK_SQL = """
SELECT payload_json->>'week' FROM raw_source_payloads
WHERE source = 'statbotics' AND source_object_type = 'team_event'
  AND right(source_object_id, length(%(event)s) + 1) = '_' || %(event)s
ORDER BY id DESC LIMIT 1
"""
QUAL_MATCHES_SQL = """
SELECT m.match_key, m.scheduled_time FROM matches m
WHERE m.event_key = %(event)s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
ORDER BY m.scheduled_time, m.match_key
"""


def statbotics_event_week(database, event_key: str) -> int | None:
    """The event's Statbotics week, from the latest landed Statbotics record (None when none is landed)."""
    with database.cursor() as cursor:
        cursor.execute(STATBOTICS_WEEK_SQL, {"event": event_key})
        row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def qualification_matches(database, event_key: str) -> list[tuple[str, object]]:
    with database.cursor() as cursor:
        cursor.execute(QUAL_MATCHES_SQL, {"event": event_key})
        return cursor.fetchall()


# --- the event-level service (P7-M4: extracted unchanged from api/routes/qualification_forecast.py) -------------


@dataclass(frozen=True)
class ForecastMatch:
    """One qualification match's forecast inputs and raw model output (display and labels are the API's job)."""

    match_key: str
    scheduled_time: datetime
    features_as_of: datetime
    red: tuple[int, ...]
    blue: tuple[int, ...]
    q: float
    epa_complete: bool


@dataclass(frozen=True)
class EventQualificationForecast:
    matches: list[ForecastMatch]
    records: dict[int, TeamRecordForecast]
    statbotics_week: int | None
    epa_source_states: list[str | None]


@consistent_reads
def forecast_event_qualification(
    database, event_key: str, as_of: datetime, *, epa_provider,
    predict_win_prob: Callable[[MatchFeatureRow], float],
    predict_win_probs: Callable[[Sequence[MatchFeatureRow]], list[float]] | None = None,
) -> EventQualificationForecast:
    """Every qualification match's q, with features built at min(as_of, scheduled time) so a played match keeps its
    pre-match forecast, plus each team's expected record. SilentFallbackError (EPA source) propagates.

    Every read through `database` comes from one snapshot on one connection (`consistent_reads`, as for the event
    analysis, strength view and pre-match report). Without it each read opened its own connection: about 940 for one
    district event, which took the hosted API past the web app's 30 s limit (2026-11-16)."""
    scales = ScaleLookup(database)
    epa_provider = through_snapshot(epa_provider, database)  # one connection, not one per EPA lookup
    # The event's rows (and, for the Statbotics source, every team's EPA candidates) read once; each match's features
    # apply their own as_of to them. ~3,400 queries became ~270 for a district championship (2026-11-16).
    history = EventHistory.read(database, event_key)
    if hasattr(epa_provider, "prefetched"):
        epa_provider = epa_provider.prefetched(history.teams())
    built = []
    for match_key, scheduled in qualification_matches(database, event_key):
        features_as_of = min(as_of, scheduled)
        built.append((match_key, scheduled, features_as_of,
                      build_match_feature_row(database, match_key, features_as_of, epa_provider=epa_provider,
                                              scale_lookup=scales, history=history)))
    rows = [row for *_, row in built]
    # One batched model call when the model offers it (the served model does; identical values): per-match calls
    # cost seconds on the hosted API's small CPU.
    qs = predict_win_probs(rows) if predict_win_probs is not None else [predict_win_prob(row) for row in rows]
    matches: list[ForecastMatch] = []
    states: list[str | None] = []
    for (match_key, scheduled, features_as_of, row), q in zip(built, qs, strict=True):
        teams = [*row.red_teams, *row.blue_teams]
        states += [t.epa_source_state for t in teams]
        complete = bool(row.red_teams) and bool(row.blue_teams) and all(t.epa_total_present for t in teams)
        matches.append(ForecastMatch(match_key, scheduled, features_as_of,
                                     tuple(t.team_number for t in row.red_teams),
                                     tuple(t.team_number for t in row.blue_teams),
                                     float(q), complete))
    records = team_records(MatchForecast(m.match_key, m.red, m.blue, m.q, m.epa_complete) for m in matches)
    return EventQualificationForecast(matches, records, statbotics_event_week(database, event_key), states)
