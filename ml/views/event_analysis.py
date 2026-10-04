"""P5-M4 event analysis: the frozen event-level ordering policy and its evaluation statistics.

Specification: docs/P5Milestones.md, P5-M4 (frozen at P5-M0); decision P5-D6.

**Ordering policy.**
- **Before the event switch point:** raw EPA (`RawEpaRankingBaseline`).
- **The switch point** is the moment every rostered team has played its ⌈n_i/2⌉-th qualification match.
- **After the switch point:** M5 v2, but only if the single measurement in criterion (b) found a paired mean
  difference > 0. Otherwise raw EPA throughout.
- **One model per ordering.** The two scores are on different scales and are never mixed.

**Captain candidates** are the top 8 of the ordering. **Strongest teams** come from the same ordering and never
carry a playoff probability.

**Statistics** (no new ones):
- Spearman per event with Phase 4's own function, averaged over events.
- Captain hit rate is |predicted ∩ actual captains| / 8.
- Paired differences use an event-cluster bootstrap: 1,000 resamples, percentile 95%, following Phase 4's D18 M7
  diagnostic.

Final ranks and alliances are labels only, never inputs.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ml.backtest.metrics import spearman_correlation
from ml.features.assembler import TeamFeatures

POLICY_RAW_EPA = "raw_epa"
POLICY_M5V2 = "ranking_xgb_v2"
CAPTAINS = 8
BOOTSTRAP_RESAMPLES = 1000  # Phase 4 precedent (.agent/phase4/results/d18/m07_diagnostics.py)
BOOTSTRAP_SEED = 20261004  # pre-declared for P5-M4

# Criterion (b)'s single measurement decides this (scripts/phase5_m4_event_analysis.py). None means not yet
# measured, which serves raw EPA throughout. tests/test_event_analysis.py pins it to the record.
SERVE_M5V2_AFTER_SWITCH: bool | None = True  # p5_m4_event_analysis.json: +0.0183, CI [0.0082, 0.0288]
RECORD = ".agent/phase5/results/p5_m4_event_analysis.json"

VALIDATED_RAW_EPA = "validated"  # the M4 raw-EPA baseline, pre-event included (0.5955)
VALIDATED_AS_MEASURED = "validated_as_measured"
DESCRIPTIVE = "descriptive"


def midpoint_index(n: int) -> int:
    """The 1-based ⌈n/2⌉-th qualification match."""
    return math.ceil(n / 2)


def switch_time(team_matches: Mapping[int, Sequence[datetime]]) -> datetime | None:
    """The scheduled time of the last team's ⌈n_i/2⌉-th qualification match (the event switch point)."""
    times = [sorted(matches)[midpoint_index(len(matches)) - 1] for matches in team_matches.values() if matches]
    return max(times) if times else None


def policy_model(switch_passed: bool, serve_m5v2_after_switch: bool | None = None) -> str:
    """The model the frozen policy serves: M5 v2 only after the switch, and only if (b) measured it better."""
    serve = SERVE_M5V2_AFTER_SWITCH if serve_m5v2_after_switch is None else serve_m5v2_after_switch
    return POLICY_M5V2 if switch_passed and serve else POLICY_RAW_EPA


@dataclass(frozen=True)
class OrderedTeam:
    rank: int
    team_number: int
    score: float


def order_teams(teams: Sequence[TeamFeatures], score: Callable[[TeamFeatures], float]) -> list[OrderedTeam]:
    """Strongest first. Ties (e.g. two teams without EPA under raw EPA, both -inf) break by team number."""
    scored = sorted(((score(t), t.team_number) for t in teams), key=lambda st: (-st[0], st[1]))
    return [OrderedTeam(i, team, value) for i, (value, team) in enumerate(scored, start=1)]


def event_spearman(scores: Mapping[int, float], final_ranks: Mapping[int, int]) -> float | None:
    """Spearman(score, -final rank) over teams with both: Phase 4's statistic (ranking_midpoint)."""
    teams = sorted(t for t in scores if t in final_ranks)
    if len(teams) < 2:
        return None
    return spearman_correlation([scores[t] for t in teams], [-final_ranks[t] for t in teams])


def captain_hit_rate(ordering: Sequence[OrderedTeam], actual_captains: set[int]) -> float:
    predicted = {o.team_number for o in ordering[:CAPTAINS]}
    return len(predicted & actual_captains) / CAPTAINS


def paired_bootstrap(differences: Sequence[float], *, resamples: int = BOOTSTRAP_RESAMPLES,
                     seed: int = BOOTSTRAP_SEED) -> dict[str, float | int]:
    """Mean of per-event paired differences and its event-bootstrap percentile 95% CI."""
    values = np.asarray(differences, dtype=float)
    rng = np.random.default_rng(seed)
    means = [float(values[rng.integers(0, len(values), len(values))].mean()) for _ in range(resamples)]
    return {"events": len(values), "mean_difference": float(values.mean()),
            "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
            "resamples": resamples, "seed": seed}


# --- serving: the switch point from the canonical schedule ------------------------------------

QUAL_SCHEDULE_SQL = """
SELECT mt.team_number, m.scheduled_time, (m.score_red IS NOT NULL AND m.score_blue IS NOT NULL) AS completed
FROM matches m JOIN match_teams mt ON mt.match_key = m.match_key
WHERE m.event_key = %(event)s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
ORDER BY mt.team_number, m.scheduled_time, m.match_key
"""


@dataclass(frozen=True)
class SwitchState:
    passed: bool
    switch_time: datetime | None  # the last team's ⌈n_i/2⌉-th scheduled qualification match
    teams: int


def serving_switch(database, event_key: str, as_of: datetime) -> SwitchState:
    """Whether every rostered team has played its ⌈n_i/2⌉-th qualification match before as_of.

    n_i counts the team's scheduled qualification matches in the canonical schedule. The evaluation counted the
    frame's retained rows instead (DQ'd and unplayed matches excluded), so the two can differ by a match at
    events with DQs.
    """
    schedule: dict[int, list[tuple[datetime, bool]]] = {}
    with database.cursor() as cursor:
        cursor.execute(QUAL_SCHEDULE_SQL, {"event": event_key})
        for team, when, completed in cursor.fetchall():
            schedule.setdefault(team, []).append((when, completed))
    if not schedule:
        return SwitchState(False, None, 0)
    midpoints = [matches[midpoint_index(len(matches)) - 1] for matches in schedule.values()]
    switch = max(when for when, _ in midpoints)
    passed = all(completed and when < as_of for when, completed in midpoints)
    return SwitchState(passed, switch, len(schedule))
