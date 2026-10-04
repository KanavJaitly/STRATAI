"""P5-M7 meta tracking: weekly scoring-component distributions and the share change-point detector.

Specification: docs/P5Milestones.md, P5-M7 (frozen at P5-M0). Everything here is labelled `descriptive`.

* **Rows.** One row per (completed 2024–2026 match, alliance) with a valid breakdown, split into components by
  ml.features.score_components. The week is TBA's event `week` from the raw event payload. Events without a
  TBA week (championship and off-season events) are outside the weekly series and are counted.
* **Weekly distributions.** Per season, week and component: n, mean, median, quartiles of points, and mean share
  of the official score.
* **Detector.** For each season and week w after the first, and each component, a two-sample test of the
  component's share in week w against weeks < w (week w uses only weeks ≤ w). Holm-corrected across the four
  components at α = 0.05, and reported with its effect size (difference in mean share).

**Open decision Q2** (.agent/phase5/M07_DECISION_REQUIRED.md). The spec does not name the test or its unit of
analysis, and the two candidates behave differently under criterion (b)'s event-level week-label permutations.
`test` is therefore a required argument with no default:

| `test` | Test |
|---|---|
| `row_welch` | Welch's t-test over alliance-match shares |
| `event_welch` | Welch's t-test over event-mean shares |
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import beta, ttest_ind

from ml.features.score_components import COMPONENTS, ScoreComponents

ALPHA = 0.05
TEST_ROW_WELCH, TEST_EVENT_WELCH = "row_welch", "event_welch"
DetectorTest = Literal["row_welch", "event_welch"]
DESCRIPTIVE = "descriptive"

ROWS_SQL = """
SELECT m.season, m.event_key, ev.week, m.match_key, m.score_red, m.score_blue, raw.breakdown
FROM matches m
LEFT JOIN LATERAL (
    SELECT (r.payload_json->>'week')::int AS week FROM raw_source_payloads r
    WHERE r.source = 'tba' AND r.source_object_type = 'event' AND r.source_object_id = m.event_key AND r.is_current
    ORDER BY r.id DESC LIMIT 1) ev ON TRUE
LEFT JOIN LATERAL (
    SELECT r.payload_json->'score_breakdown' AS breakdown FROM raw_source_payloads r
    WHERE r.source = 'tba' AND r.source_object_type = 'match' AND r.source_object_id = m.match_key AND r.is_current
    ORDER BY r.id DESC LIMIT 1) raw ON TRUE
WHERE m.season = ANY(%(seasons)s) AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
ORDER BY m.season, m.event_key, m.match_key
"""


@dataclass(frozen=True)
class ComponentRow:
    season: int
    event_key: str
    week: int | None
    match_key: str
    alliance: str
    parts: ScoreComponents
    official_score: int


def weekly_distributions(rows: Sequence[ComponentRow]) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """season -> week -> component -> {n, mean, median, q1, q3, mean_share} (weeks with a TBA week only)."""
    groups: dict[tuple[int, int], list[ComponentRow]] = defaultdict(list)
    for row in rows:
        if row.week is not None:
            groups[(row.season, row.week)].append(row)
    out: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(dict)
    for (season, week), items in sorted(groups.items()):
        per: dict[str, dict[str, float]] = {}
        for component in COMPONENTS:
            points = np.array([getattr(r.parts, component) for r in items], dtype=float)
            shares = np.array([s for r in items if (s := r.parts.share(component)) is not None])
            per[component] = {"n": len(points), "mean": float(points.mean()), "median": float(np.median(points)),
                              "q1": float(np.quantile(points, 0.25)), "q3": float(np.quantile(points, 0.75)),
                              "mean_share": float(shares.mean()) if len(shares) else None}  # type: ignore[dict-item]
        out[str(season)][str(week)] = per
    return dict(out)


def holm(p_values: Sequence[float], alpha: float = ALPHA) -> list[bool]:
    """Holm step-down rejections, in input order."""
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    reject = [False] * len(p_values)
    for rank, index in enumerate(order):
        if p_values[index] > alpha / (len(p_values) - rank):
            break
        reject[index] = True
    return reject


@dataclass(frozen=True)
class ShareTable:
    """Per season: the unit-level shares the detector tests, with each unit's week."""

    season: int
    weeks: np.ndarray  # one week per unit
    events: np.ndarray  # one event per unit
    shares: dict[str, np.ndarray]  # component -> share per unit


def share_tables(rows: Sequence[ComponentRow], test: DetectorTest) -> list[ShareTable]:
    """Units are alliance-match rows (row_welch) or events with their mean share (event_welch)."""
    if test not in (TEST_ROW_WELCH, TEST_EVENT_WELCH):
        raise ValueError(f"the detector test is open decision Q2 and must be chosen explicitly, got {test!r}")
    tables = []
    for season in sorted({r.season for r in rows}):
        usable = [r for r in rows if r.season == season and r.week is not None and r.parts.total != 0]
        if test == TEST_ROW_WELCH:
            weeks = np.array([r.week for r in usable])
            events = np.array([r.event_key for r in usable])
            shares = {c: np.array([r.parts.share(c) for r in usable]) for c in COMPONENTS}
        else:
            by_event: dict[str, list[ComponentRow]] = defaultdict(list)
            for r in usable:
                by_event[r.event_key].append(r)
            keys = sorted(by_event)
            weeks = np.array([by_event[k][0].week for k in keys])
            events = np.array(keys)
            shares = {c: np.array([np.mean([r.parts.share(c) for r in by_event[k]]) for k in keys]) for c in COMPONENTS}
        tables.append(ShareTable(season, weeks, events, shares))
    return tables


def detect(table: ShareTable, weeks: np.ndarray | None = None) -> list[dict]:
    """One family per week w after the first: Welch t-tests of each component's share (w vs < w), Holm."""
    labels = table.weeks if weeks is None else weeks
    families = []
    for week in sorted(set(labels.tolist()))[1:]:
        current, earlier = labels == week, labels < week
        if current.sum() < 2 or earlier.sum() < 2:
            continue
        tests = []
        for component in COMPONENTS:
            values = table.shares[component]
            result = ttest_ind(values[current], values[earlier], equal_var=False)
            tests.append((component, float(result.pvalue), float(values[current].mean() - values[earlier].mean())))
        rejected = holm([p for _, p, _ in tests])
        families.append({"season": table.season, "week": int(week), "n_week": int(current.sum()),
                         "n_earlier": int(earlier.sum()),
                         "tests": [{"component": c, "p_value": p, "share_difference": d, "flag": f}
                                   for (c, p, d), f in zip(tests, rejected)],
                         "flagged": any(rejected)})
    return families


def event_week_permutation(table: ShareTable, rng: np.random.Generator) -> np.ndarray:
    """Permute week labels across the season's events (every unit of an event moves with it)."""
    keys = sorted(set(table.events.tolist()))
    event_week = {}
    for event, week in zip(table.events.tolist(), table.weeks.tolist()):
        event_week[event] = week
    shuffled = rng.permutation([event_week[k] for k in keys])
    mapping = dict(zip(keys, shuffled.tolist()))
    return np.array([mapping[e] for e in table.events.tolist()])


def clopper_pearson_upper(k: int, n: int, level: float = 0.95) -> float:
    """Upper bound of the two-sided Clopper–Pearson interval (as in Phase 4's diagnostics)."""
    return 1.0 if k == n else float(beta.ppf(1 - (1 - level) / 2, k + 1, n - k))
