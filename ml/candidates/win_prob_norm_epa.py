"""WP-NORM-EPA-v1: a scale-normalized EPA logistic for match win probability. A RESEARCH CANDIDATE, not served.

Frozen spec: .agent/model_candidates/WP-NORM-EPA-v1.md (audit 2026-11-26, workstream 1). Any change to a definition
below is a new candidate version, not an edit.

**Why it exists (the diagnosis).** The served M6 model takes raw game-point features. FRC scoring changes every season:
the population SD of alliance scores (the causal season scale S, ml/features/scale.py) was about 22 points in 2024,
39 in 2025 and 99 in 2026 (medians over the D18 frame's team appearances). A raw-point model fit on 2024 and 2025 sees
2026 differences that are several times larger than anything it was trained on, so its probabilities are pushed to
the extremes. Dividing each EPA by its own season's scale removes the season's units.

**Definition.**
- Per team: z = epa_total / epa_scale. Both are the as-of values in the team's TeamFeatures: the EPA of its latest
  strictly earlier event (D13/D18), and the scale of that EPA's source season (S(Y, as_of) for the same season, the
  source season's full S for an earlier one). Each team uses its own scale. In 2025 and 2026 about a third of matches
  mix EPA from two seasons, so one scale per match would be wrong for them.
- Per match: x = Σ z over red − Σ z over blue, defined only for 3 v 3 matches where all six z exist.
- p(red wins) = 1 / (1 + exp(−b·x)). No intercept, so p(x) + p(−x) = 1: swapping alliances gives the complement.
- b is the maximum-likelihood estimate on the training rows, fitted by Newton's method in closed form (one
  parameter, a strictly concave log-likelihood): deterministic and reproducible.

**Training rows.** Seasons 2024 and 2025 only (the served models' training seasons, D7), every competition level,
non-tie, with x defined. Ties are excluded from fitting and evaluation.

It estimates nothing about a team; it re-expresses the EPA the served path already reads, so it adds no point-in-time
risk beyond TeamFeatures' own (pinned by the point-in-time tests).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ml.dataset.builder import TrainingRow
from ml.features.assembler import TeamFeatures

CANDIDATE_ID = "WP-NORM-EPA-v1"
TRAINING_SEASONS: frozenset[int] = frozenset({2024, 2025})
WIN_LABELS = {"red_win": True, "blue_win": False}


def team_z(team: TeamFeatures) -> float | None:
    """The team's EPA in units of its own season's scoring scale, or None when either is absent."""
    if team.epa_total is None or team.epa_scale is None:
        return None
    return team.epa_total / team.epa_scale


def match_feature(row: TrainingRow) -> float | None:
    """x = Σ red z − Σ blue z, for a 3 v 3 match with every z defined; else None."""
    if len(row.red_teams) != 3 or len(row.blue_teams) != 3:
        return None
    red = [team_z(t) for t in row.red_teams]
    blue = [team_z(t) for t in row.blue_teams]
    if any(z is None for z in (*red, *blue)):
        return None
    return sum(red) - sum(blue)  # type: ignore[arg-type]


def raw_feature(row: TrainingRow) -> float | None:
    """The raw-point EPA difference (the M4-style input; kept for the diagnosis only)."""
    teams = (*row.red_teams, *row.blue_teams)
    if len(row.red_teams) != 3 or len(row.blue_teams) != 3 or any(t.epa_total is None for t in teams):
        return None
    return sum(t.epa_total for t in row.red_teams) - sum(t.epa_total for t in row.blue_teams)  # type: ignore[misc]


def outcome(row: TrainingRow) -> bool | None:
    """True when red won, False when blue won, None for a tie (or an unknown label)."""
    return WIN_LABELS.get(row.label)


def training_rows(rows: Iterable[TrainingRow]) -> list[TrainingRow]:
    """The rows the candidate is fitted on: training seasons, non-tie, feature defined."""
    return [r for r in rows if r.season in TRAINING_SEASONS and outcome(r) is not None and match_feature(r) is not None]


def _sigmoid(v: float) -> float:
    if v >= 0:
        return 1.0 / (1.0 + math.exp(-v))
    e = math.exp(v)
    return e / (1.0 + e)


def fit_coefficient(xs: Sequence[float], ys: Sequence[bool], *, tolerance: float = 1e-12, max_iter: int = 100) -> float:
    """The maximum-likelihood b for p = sigmoid(b·x), no intercept (Newton's method)."""
    if not xs or len(xs) != len(ys):
        raise ValueError("fit needs matching, non-empty features and outcomes")
    b = 0.0
    for _ in range(max_iter):
        gradient = hessian = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(b * x)
            gradient += x * ((1.0 if y else 0.0) - p)
            hessian -= x * x * p * (1.0 - p)
        if hessian == 0.0:
            raise ValueError("the features carry no information (all zero)")
        step = gradient / hessian
        b -= step
        if abs(step) < tolerance:
            return b
    raise ValueError("the fit did not converge (the outcomes may be perfectly separated)")


@dataclass(frozen=True)
class NormEpaLogistic:
    coefficient: float
    candidate_id: str = CANDIDATE_ID

    @classmethod
    def fit(cls, rows: Iterable[TrainingRow]) -> "NormEpaLogistic":
        train = training_rows(rows)
        return cls(fit_coefficient([match_feature(r) for r in train], [outcome(r) for r in train]))  # type: ignore[misc]

    def predict(self, row: TrainingRow) -> float | None:
        """p(red wins), or None where the feature is undefined (the candidate withholds, never substitutes)."""
        x = match_feature(row)
        return None if x is None else _sigmoid(self.coefficient * x)


__all__ = ["CANDIDATE_ID", "NormEpaLogistic", "TRAINING_SEASONS", "fit_coefficient", "match_feature", "outcome",
           "raw_feature", "team_z", "training_rows"]
