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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ml.calibration.gate import poisson_binomial_pmf

RANGE_LOWER, RANGE_UPPER = 0.10, 0.90
COVERAGE_BAND = (0.75, 0.85)  # P5-D9
LOW_CONFIDENCE_WEEKS = frozenset({1, 2, 3})
# Criterion (b)'s single measurement (scripts/phase5_m5_qualification_forecast.py). None means not measured, so
# the range is served not_validated. tests/test_qualification_forecast.py pins it to the record.
RANGE_COVERAGE_VALIDATED: bool | None = None
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
