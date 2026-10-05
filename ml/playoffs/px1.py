"""PX-1 (P6-M2): the playoff match model, exactly as `.agent/phase6/P6_M2_PX1_SPEC.md` freezes it.

- **Model:** a regularized logistic regression (P6-Q2), with no intercept.
- **Inputs:** antisymmetric red − blue differences of the seed and of the Phase 4 M6 alliance composition sums, plus
  their interactions with the bracket round.
- **Point in time:** features are assembled at each event's selection moment, never from playoff results.
- **Antisymmetry:** swapping the alliances gives exactly the complement, by construction.
- **Seed-only baseline:** the same machinery on the seed difference alone, for the P6-Q3 gate.

Real assembly needs approved P6-M1 rulesets, because the bracket round comes from their slot mapping. This module
never hard-codes a bracket.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data.alliances import Alliance
from ml.features.assembler import TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector

MODEL_TYPE, SEED_ONLY_MODEL_TYPE = "playoff_px1", "playoff_seed_only"
MODEL_VERSION = "1.0.0"
SPEC_PATH = ".agent/phase6/P6_M2_PX1_SPEC.md"
SELECTION_MOMENT_OFFSET = timedelta(minutes=1)
REGULARIZATION_C = 1.0


def selection_moment(latest_qualification_time: datetime) -> datetime:
    """The `as_of` of an event's alliance selection: one minute after its latest qualification match (§1)."""
    if latest_qualification_time.tzinfo is None:
        raise ValueError("times must carry a timezone")
    return latest_qualification_time + SELECTION_MOMENT_OFFSET


def map_side(side_teams: Sequence[int], alliances: Sequence[Alliance]) -> Alliance | None:
    """The alliance holding at least two of the side's three teams; None if there is none or it is ambiguous."""
    matches = [a for a in alliances if len(set(a.picks) & set(side_teams)) >= 2]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class PlayoffRow:
    match_key: str
    event_key: str
    season: int
    scheduled_time: datetime
    round: int
    red_seed: int
    blue_seed: int
    red_teams: tuple[TeamFeatures, ...]
    blue_teams: tuple[TeamFeatures, ...]
    red_win: bool

    def swapped(self) -> PlayoffRow:
        return PlayoffRow(self.match_key, self.event_key, self.season, self.scheduled_time, self.round,
                          self.blue_seed, self.red_seed, self.blue_teams, self.red_teams, not self.red_win)


def composition_difference(red: Sequence[TeamFeatures], blue: Sequence[TeamFeatures]) -> np.ndarray:
    """Red − blue of the M6 alliance sums (NaN where any team lacks the value)."""
    def alliance(teams):
        return np.sum(np.vstack([team_features_to_vector(t) for t in teams]), axis=0)
    return alliance(red) - alliance(blue)


@dataclass
class Design:
    """Which composition columns enter, the rounds with interactions, and the per-column RMS scale (§2)."""

    seed: bool
    composition_columns: list[str]
    dropped: dict[str, str]
    rounds: list[int]  # interaction rounds (every training round except the lowest)
    scale: list[float] = field(default_factory=list)

    def names(self) -> list[str]:
        base = (["seed_difference"] if self.seed else []) + [f"d_{c}" for c in self.composition_columns]
        return base + [f"{name}*round{k}" for k in self.rounds for name in base]

    def raw(self, row: PlayoffRow) -> np.ndarray | None:
        parts = [float(row.red_seed - row.blue_seed)] if self.seed else []
        if self.composition_columns:
            diff = composition_difference(row.red_teams, row.blue_teams)
            values = [diff[TEAM_FEATURE_NAMES.index(c)] for c in self.composition_columns]
            if any(math.isnan(v) for v in values):
                return None
            parts.extend(values)
        base = np.array(parts, dtype=np.float64)
        interactions = [base * (1.0 if row.round == k else 0.0) for k in self.rounds]
        return np.concatenate([base, *interactions]) if interactions else base

    def transform(self, row: PlayoffRow) -> np.ndarray | None:
        raw = self.raw(row)
        return None if raw is None else raw / np.array(self.scale)


def fit_design(rows: Sequence[PlayoffRow], *, seed: bool = True, composition: bool = True) -> Design:
    dropped: dict[str, str] = {}
    columns: list[str] = []
    if composition:
        diffs = np.vstack([composition_difference(r.red_teams, r.blue_teams) for r in rows])
        for i, name in enumerate(TEAM_FEATURE_NAMES):
            column = diffs[:, i]
            if np.all(np.isnan(column)):
                dropped[name] = "no data"
            elif np.any(np.isnan(column)):
                dropped[name] = "absent in some training rows"
            elif np.allclose(column, 0.0):
                dropped[name] = "no variation"
            else:
                columns.append(name)
    rounds = sorted({r.round for r in rows})[1:]
    design = Design(seed, columns, dropped, rounds)
    matrix = np.vstack([design.raw(r) for r in rows])
    rms = np.sqrt(np.mean(matrix ** 2, axis=0))
    design.scale = [float(v) if v > 0 else 1.0 for v in rms]
    return design


def _expit(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


class PlayoffLogisticModel:
    """PX-1, or (with seed only) the seed-only baseline. Antisymmetric: no intercept, difference features."""

    def __init__(self, design: Design, coef: Sequence[float], *, model_type: str = MODEL_TYPE,
                 fit_info: dict[str, Any] | None = None) -> None:
        self.design = design
        self.coef = np.asarray(coef, dtype=np.float64)
        self.model_type = model_type
        self.fit_info = fit_info or {}

    @classmethod
    def fit(cls, rows: Sequence[PlayoffRow], *, seed_only: bool = False,
            fit_info: dict[str, Any] | None = None) -> PlayoffLogisticModel:
        from sklearn.linear_model import LogisticRegression

        design = fit_design(rows, composition=not seed_only)
        usable = [(design.transform(r), r.red_win) for r in rows]
        excluded = sum(1 for x, _ in usable if x is None)
        usable = [(x, y) for x, y in usable if x is not None]
        x = np.vstack([u[0] for u in usable])
        y = np.array([u[1] for u in usable])
        model = LogisticRegression(penalty="l2", C=REGULARIZATION_C, fit_intercept=False, solver="lbfgs",
                                   max_iter=10000)
        model.fit(x, y)
        info = {**(fit_info or {}), "fit_rows": len(usable), "fit_rows_excluded_missing": excluded,
                "columns": design.names(), "dropped": design.dropped}
        return cls(design, model.coef_[0].tolist(), model_type=SEED_ONLY_MODEL_TYPE if seed_only else MODEL_TYPE,
                   fit_info=info)

    def margin(self, row: PlayoffRow) -> float | None:
        x = self.design.transform(row)
        return None if x is None else float(np.dot(self.coef, x))

    def predict(self, row: PlayoffRow) -> float | None:
        """P(red wins), or None when a used input is absent (insufficient_data)."""
        z = self.margin(row)
        return None if z is None else _expit(z)

    def to_dict(self) -> dict[str, Any]:
        return {"model_type": self.model_type, "model_version": MODEL_VERSION, "coef": self.coef.tolist(),
                "design": {"seed": self.design.seed, "composition_columns": self.design.composition_columns,
                           "dropped": self.design.dropped, "rounds": self.design.rounds, "scale": self.design.scale},
                "fit_info": self.fit_info, "spec": SPEC_PATH}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> PlayoffLogisticModel:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        d = data["design"]
        return cls(Design(d["seed"], d["composition_columns"], d["dropped"], d["rounds"], d["scale"]), data["coef"],
                   model_type=data["model_type"], fit_info=data["fit_info"])


def alliance_match_probability(model: PlayoffLogisticModel, features: dict[int, TeamFeatures],
                               calibrate=None):
    """Adapter for the selection engine: p(red alliance teams, blue alliance teams, seeds, round) from PX-1, and
    PX-2's calibrator when given. Raises if an input is absent: the engine must not run on imputed values."""
    def p(red: tuple[int, ...], blue: tuple[int, ...], red_seed: int, blue_seed: int, round_: int) -> float:
        row = PlayoffRow("", "", 0, datetime.min.replace(tzinfo=None), round_, red_seed, blue_seed,
                         tuple(features[t] for t in red), tuple(features[t] for t in blue), False)
        value = model.predict(row)
        if value is None:
            raise ValueError(f"PX-1 input absent for alliances {red} v {blue}: insufficient_data")
        return value if calibrate is None else calibrate(value)
    return p
