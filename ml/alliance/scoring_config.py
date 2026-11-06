"""P11A B4: the season scoring configuration, and the scoring math that applies it (spec B4, B5.1).

**What a configuration is.**
- One per season: human-entered from the game manual, versioned, and reviewed.
- It references the season's approved P5-M8 GameSpec (`data/game_spec.py`) by sha256, and it **never restates a point
  value**. Every point value comes from a GameSpec scoring action, named by `action_id`.
- The frozen P5 GameSpec schema is not extended, because that would change frozen P5 catalog hashes (P11A-Q4 fallback).
- One rule per estimator component (auto, teleop, endgame: the P5-M7 adapter components). A rule says how the three
  active robots' contributions combine into alliance points:
  - `sum`: independent per-robot contributions; alliance points are their sum;
  - `alliance_cap`: the sum is capped at `cap_count` × the points of `cap_action_id` (a shared resource or a limited
    number of scoring positions);
  - plus optional per-robot caps, and threshold bonuses (`bonus_action_id` points when the component reaches
    `threshold_points`).
- Every rule cites the manual. Fouls are not a robot capability; they are either excluded or added as the event's
  observed mean (`fouls`).

**Approval.**
- A configuration is usable for scoring only when `status == "approved"` with a named, qualified reviewer whose
  verified sha256 equals the content's sha256.
- `require_approved` refuses anything else (`scoring_config_not_approved`); nothing is ever approved here.

**The scoring math.** The alliance component points S are modelled as normal, with mean m and variance v: estimation
plus match-level residual (the predictive distribution, spec B5.1).
- `sum`: E[S] = m (linear; no double counting).
- `alliance_cap` c: E[min(c, S)] = m − E[(S − c)+],
  with E[(S − c)+] = (m − c) Φ(z) + √v φ(z), z = (m − c)/√v.
- Threshold bonus (B points at threshold T): + B · P(S ≥ T).
- Per-robot cap: each robot's *mean* contribution is capped before summing. Per-match per-robot variability is not
  identifiable from alliance data (spec B5.2(b)), so this is an approximation, and outputs say so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.stats import norm

from data.game_spec import GameSpec

SCHEMA_VERSION = "p11a-scoring-config-v1"
COMPONENTS = ("auto", "teleop", "endgame")
CONFIG_DIR = Path(__file__).resolve().parents[2] / "data" / "season_scoring"


class ScoringConfigError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ThresholdBonus(_Frozen):
    threshold_points: float = Field(gt=0, description="Component points at which the bonus is earned (from the manual)")
    bonus_action_id: str = Field(min_length=1, description="The GameSpec scoring action whose points are awarded")
    citation: str = Field(min_length=1)


class ComponentRule(_Frozen):
    component: Literal["auto", "teleop", "endgame"]
    combination: Literal["sum", "alliance_cap"]
    cap_action_id: str | None = None
    cap_count: int | None = Field(default=None, ge=1)
    per_robot_cap_action_id: str | None = None
    per_robot_cap_count: int | None = Field(default=None, ge=1)
    bonuses: tuple[ThresholdBonus, ...] = ()
    citation: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> ComponentRule:
        if self.combination == "alliance_cap" and (self.cap_action_id is None or self.cap_count is None):
            raise ValueError(f"{self.component}: an alliance_cap rule names cap_action_id and cap_count")
        if self.combination == "sum" and (self.cap_action_id is not None or self.cap_count is not None):
            raise ValueError(f"{self.component}: a sum rule has no alliance cap")
        if (self.per_robot_cap_action_id is None) != (self.per_robot_cap_count is None):
            raise ValueError(f"{self.component}: a per-robot cap names both its action and its count")
        return self


class ConfigSource(_Frozen):
    entered_by: str = Field(min_length=1)
    entered_at: datetime
    manual_title: str = Field(min_length=1)
    manual_version: str = Field(min_length=1)


class ConfigReview(_Frozen):
    reviewer: str = Field(min_length=1)
    qualification: str = Field(min_length=1, description="The reviewer's FRC-domain qualification")
    reviewed_at: datetime
    verified_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SeasonScoringConfig(_Frozen):
    schema_version: Literal["p11a-scoring-config-v1"] = SCHEMA_VERSION
    season: int = Field(ge=1992)
    game_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rules: tuple[ComponentRule, ...]
    fouls: Literal["excluded", "event_mean"]
    source: ConfigSource
    status: Literal["draft", "awaiting_review", "approved", "superseded"] = "draft"
    review: ConfigReview | None = None

    @model_validator(mode="after")
    def _complete(self) -> SeasonScoringConfig:
        names = [r.component for r in self.rules]
        if sorted(names) != sorted(COMPONENTS):
            raise ValueError(f"exactly one rule per component {COMPONENTS}; got {names}")
        if self.status in ("approved", "superseded") and self.review is None:
            raise ValueError("an approved configuration carries its review")
        return self

    def content_sha256(self) -> str:
        """The sha256 of everything a reviewer verifies: the content without status and review."""
        content = self.model_dump(mode="json", exclude={"status", "review"})
        return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def rule(self, component: str) -> ComponentRule:
        return next(r for r in self.rules if r.component == component)


def load_config(path: Path) -> SeasonScoringConfig:
    try:
        return SeasonScoringConfig.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ScoringConfigError("scoring_config_invalid", f"{path.name}: {exc}") from None


def find_config(season: int, directory: Path | None = None) -> SeasonScoringConfig | None:
    """The season's configuration file (<dir>/<season>.json), or None when none exists."""
    path = (directory or CONFIG_DIR) / f"{season}.json"
    return load_config(path) if path.exists() else None


def require_approved(config: SeasonScoringConfig | None, season: int) -> SeasonScoringConfig:
    """The configuration, only if it is approved by a reviewer who verified exactly this content."""
    if config is None:
        raise ScoringConfigError("scoring_config_not_approved", f"no scoring configuration exists for {season}")
    if config.season != season:
        raise ScoringConfigError("scoring_config_invalid", f"the configuration is for {config.season}, not {season}")
    if config.status != "approved" or config.review is None:
        raise ScoringConfigError("scoring_config_not_approved",
                                 f"the {season} scoring configuration is {config.status}, not approved")
    if config.review.verified_sha256 != config.content_sha256():
        raise ScoringConfigError("scoring_config_not_approved",
                                 f"the {season} configuration's content differs from what its reviewer verified")
    return config


@dataclass(frozen=True)
class ResolvedRule:
    component: str
    cap_points: float | None
    per_robot_cap_points: float | None
    bonuses: tuple[tuple[float, float], ...]  # (threshold points, bonus points)


@dataclass(frozen=True)
class ResolvedScoring:
    """An approved configuration with every point value resolved from its GameSpec."""

    season: int
    config_sha256: str
    game_spec_sha256: str
    fouls: str
    rules: dict[str, ResolvedRule]

    @classmethod
    def resolve(cls, config: SeasonScoringConfig, spec: GameSpec) -> ResolvedScoring:
        approved = require_approved(config, config.season)
        if spec.season != approved.season:
            raise ScoringConfigError("game_spec_mismatch", f"the GameSpec is for {spec.season}")
        if spec.sha256() != approved.game_spec_sha256:
            raise ScoringConfigError("game_spec_mismatch", "the configuration references a different GameSpec")
        actions = {a.action_id: a for a in spec.scoring_actions}

        def points(action_id: str, component: str) -> float:
            action = actions.get(action_id)
            if action is None:
                raise ScoringConfigError("game_spec_mismatch", f"GameSpec has no scoring action {action_id!r}")
            if action.period != component:
                raise ScoringConfigError("game_spec_mismatch",
                                         f"{action_id} is a {action.period} action, not {component}")
            return float(action.points)

        rules = {}
        for r in approved.rules:
            rules[r.component] = ResolvedRule(
                r.component,
                None if r.cap_action_id is None else r.cap_count * points(r.cap_action_id, r.component),
                None if r.per_robot_cap_action_id is None else
                r.per_robot_cap_count * points(r.per_robot_cap_action_id, r.component),
                tuple((b.threshold_points, points(b.bonus_action_id, r.component)) for b in r.bonuses))
        return cls(approved.season, approved.content_sha256(), approved.game_spec_sha256, approved.fouls, rules)


def expected_component_points(rule: ResolvedRule, mean: np.ndarray | float, var: np.ndarray | float) -> np.ndarray:
    """E[points] for alliance component sums S ~ N(mean, var) under `rule` (vectorized). `mean` is the alliance sum
    after per-robot caps (see `alliance_component_mean`)."""
    m = np.asarray(mean, dtype=float)
    sd = np.sqrt(np.maximum(np.asarray(var, dtype=float), 0.0))
    if rule.cap_points is None:
        value = m.copy()
    else:
        c = rule.cap_points
        safe = np.where(sd > 0, sd, 1.0)
        z = (m - c) / safe
        excess = np.where(sd > 0, (m - c) * norm.cdf(z) + sd * norm.pdf(z), np.maximum(m - c, 0.0))
        value = m - excess
    for threshold, bonus in rule.bonuses:
        safe = np.where(sd > 0, sd, 1.0)
        p = np.where(sd > 0, 1 - norm.cdf((threshold - m) / safe), (m >= threshold).astype(float))
        value = value + bonus * p
    return value


def alliance_component_mean(rule: ResolvedRule, robot_means: np.ndarray) -> np.ndarray:
    """The alliance mean for one component from its robots' means (last axis = robots), with any per-robot cap
    applied to each robot's mean (an approximation; see the module docstring)."""
    means = np.asarray(robot_means, dtype=float)
    if rule.per_robot_cap_points is not None:
        means = np.minimum(means, rule.per_robot_cap_points)
    return means.sum(axis=-1)


__all__ = ["COMPONENTS", "CONFIG_DIR", "ComponentRule", "ConfigReview", "ConfigSource", "ResolvedRule",
           "ResolvedScoring", "ScoringConfigError", "SeasonScoringConfig", "ThresholdBonus",
           "alliance_component_mean", "expected_component_points", "find_config", "load_config", "require_approved"]
