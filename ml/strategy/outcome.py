"""P6-M10: the strategy-conditional outcome model, the one odds model both strategy paths use.

The frozen model specification is `.agent/phase6/P6_M10_MODEL_SPEC.md`, written before the fit and before any
result. In short:
- **Capability:** each team's measured capability per score component is max(0, prior-event EPA component) / its
  EPA source's causal scale.
- **Strategy weighting:** a strategy weights each capability 1 or 0. It can only withhold a contribution, never
  exceed measured capability.
- **Score difference:** each normalized component score difference is beta_c times the predicted difference, plus
  multivariate-normal noise (fouls and adjustments as an "other" component with no capability).
- **P(win):** P(red wins) = Φ(m / s).

There is exactly **one evaluation entry point**, `ComponentOutcomeModel.evaluate(context, strategy_red,
strategy_blue)`. It receives no information about who proposed a strategy (P6-DM2).
- **Defense and feeding:** these effects are zero, with labels saying so, because no measured data exists (P6-Q11,
  P6-Q12).
- **Unvalidated cases:** any non-baseline strategy, and any coach observation, is served `not_validated`, because
  historical outcomes carry no strategy record (P6-A4).
- **Playoffs:** the playoff context is refused until PX-1/PX-2 pass (P6-A12).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ml.features.assembler import TeamFeatures
from ml.features.score_components import ScoreComponents
from ml.strategy.display import display_odds
from ml.strategy.representation import SCORING_COMPONENTS, CoachObservation, Strategy, StrategyError

MODEL_TYPE = "strategy_outcome_component"
MODEL_VERSION = "1.0.0"
FIT_COMPONENTS: tuple[str, ...] = ("auto", "teleop", "endgame", "other")
SPEC_PATH = ".agent/phase6/P6_M10_MODEL_SPEC.md"
FEATURE_LIST = ["epa_auto", "epa_teleop", "epa_endgame", "epa_scale", "score_scale"]  # registry feature guard

VALIDATED, NOT_VALIDATED, INSUFFICIENT_DATA = "validated", "not_validated", "insufficient_data"
REASON_NOT_RECORDED = "p6_m10_evaluation_not_recorded"
REASON_GATE_FAILED = "p6_m10_gate_failed"
REASON_STRATEGY = "strategy_effect_unmeasured"
REASON_DEFENSE = "defense_effect_insufficient_data"
REASON_FEEDING = "feeding_effect_insufficient_data"
REASON_OBSERVATION = "coach_observation_effect_unmeasured"
REASON_PLAYOFF = "playoff_model_unavailable"
QUALIFICATION = "qualification"


@dataclass(frozen=True)
class MatchContext:
    """Everything the model may use about one match, identical for both strategy paths."""

    red_teams: tuple[TeamFeatures, ...]
    blue_teams: tuple[TeamFeatures, ...]
    comp_level: str = QUALIFICATION
    observations: tuple[CoachObservation, ...] = ()

    def __post_init__(self) -> None:
        if len(self.red_teams) != 3 or len(self.blue_teams) != 3:
            raise ValueError("a match context needs three teams per alliance")

    def swapped(self) -> MatchContext:
        return MatchContext(self.blue_teams, self.red_teams, self.comp_level, self.observations)


@dataclass(frozen=True)
class OutcomeEvaluation:
    p_red: float | None
    p_blue: float | None
    display_red: str | None
    display_blue: str | None
    validation_status: str
    reasons: tuple[str, ...]
    mean_difference: float | None = None
    sigma: float | None = None
    component_means: dict[str, dict[str, float]] = field(default_factory=dict)
    model_version_tag: str | None = None
    model_sha256: str | None = None


@dataclass(frozen=True)
class FitSample:
    """One training match: predicted (delta) and actual (d) normalized component differences, red minus blue."""

    delta: dict[str, float]
    d: dict[str, float]


def _phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def capabilities(team: TeamFeatures) -> dict[str, float] | None:
    """Measured capability per component (spec §2), or None when an input is absent."""
    values = (team.epa_auto, team.epa_teleop, team.epa_endgame)
    if any(v is None for v in values) or team.epa_scale is None:
        return None
    return {c: max(0.0, float(v)) / team.epa_scale for c, v in zip(SCORING_COMPONENTS, values)}


def missing_inputs(context: MatchContext) -> list[str]:
    missing = []
    for team in (*context.red_teams, *context.blue_teams):
        for name in ("epa_auto", "epa_teleop", "epa_endgame", "epa_scale", "score_scale"):
            if getattr(team, name) is None:
                missing.append(f"{team.team_number}:{name}")
    return missing


def _weight(strategy: Strategy, team_number: int, component: str,
            observations: Sequence[CoachObservation]) -> int:
    plan = strategy.plan_for(team_number)
    if component not in plan.components:
        return 0
    if component == "teleop" and plan.role != "scoring":
        return 0
    if any(o.disables(team_number, component) for o in observations):
        return 0
    return 1


def alliance_means(teams: Sequence[TeamFeatures], strategy: Strategy,
                   observations: Sequence[CoachObservation]) -> dict[str, float]:
    means = {c: 0.0 for c in SCORING_COMPONENTS}
    for team in teams:
        caps = capabilities(team)
        if caps is None:
            raise ValueError(f"team {team.team_number} has no measured capability")
        for c in SCORING_COMPONENTS:
            means[c] += _weight(strategy, team.team_number, c, observations) * caps[c]
    return means


def _check_strategy(strategy: Strategy, own: Sequence[TeamFeatures], opponents: Sequence[TeamFeatures]) -> None:
    own_numbers = {t.team_number for t in own}
    if set(strategy.team_numbers()) != own_numbers:
        raise StrategyError(f"strategy teams {sorted(strategy.team_numbers())} are not the alliance {sorted(own_numbers)}")
    opponent_numbers = {t.team_number for t in opponents}
    for robot in strategy.robots:
        if robot.defense_target is not None and robot.defense_target not in opponent_numbers:
            raise StrategyError(f"team {robot.team_number} defends {robot.defense_target}, which is not an opponent")


def _scale(context: MatchContext) -> float:
    scales = {t.score_scale for t in (*context.red_teams, *context.blue_teams)}
    if len(scales) != 1:
        raise ValueError(f"the six teams disagree on the season scale: {sorted(scales)}")
    return scales.pop()


class ComponentOutcomeModel:
    """The P6-M10 component model (spec §2–§3). Construct with `fit`, or `load` a registered artifact."""

    def __init__(self, beta: dict[str, float], sigma_matrix: Sequence[Sequence[float]], *, fit_info: dict[str, Any],
                 spec_sha256: str, version_tag: str | None = None, artifact_sha256: str | None = None,
                 baseline_status: tuple[str, str | None] = (NOT_VALIDATED, REASON_NOT_RECORDED)) -> None:
        self.beta = {c: float(beta[c]) for c in SCORING_COMPONENTS}
        self.sigma_matrix = np.asarray(sigma_matrix, dtype=np.float64)
        if self.sigma_matrix.shape != (4, 4):
            raise ValueError("sigma_matrix must be 4x4 over (auto, teleop, endgame, other)")
        self.sigma = float(math.sqrt(self.sigma_matrix.sum()))
        if not self.sigma > 0:
            raise ValueError("the score-difference variance must be positive")
        self.fit_info = fit_info
        self.spec_sha256 = spec_sha256
        self.version_tag = version_tag
        self.artifact_sha256 = artifact_sha256
        self.baseline_status = baseline_status

    # --- the single evaluation entry point -------------------------------------------------------------

    def evaluate(self, context: MatchContext, strategy_red: Strategy, strategy_blue: Strategy) -> OutcomeEvaluation:
        _check_strategy(strategy_red, context.red_teams, context.blue_teams)
        _check_strategy(strategy_blue, context.blue_teams, context.red_teams)
        common = {"model_version_tag": self.version_tag, "model_sha256": self.artifact_sha256}
        if context.comp_level != QUALIFICATION:
            return OutcomeEvaluation(None, None, None, None, NOT_VALIDATED, (REASON_PLAYOFF,), **common)
        missing = missing_inputs(context)
        if missing:
            return OutcomeEvaluation(None, None, None, None, INSUFFICIENT_DATA,
                                     tuple(f"missing_input:{m}" for m in missing), **common)
        _scale(context)  # the six teams must share one season scale; the model works in normalized units
        red = alliance_means(context.red_teams, strategy_red, context.observations)
        blue = alliance_means(context.blue_teams, strategy_blue, context.observations)
        mean = sum(self.beta[c] * (red[c] - blue[c]) for c in SCORING_COMPONENTS)
        p_red, p_blue = _phi(mean / self.sigma), _phi(-mean / self.sigma)
        status, reasons = self._status(context, strategy_red, strategy_blue)
        return OutcomeEvaluation(p_red, p_blue, display_odds(p_red), display_odds(p_blue), status, reasons, mean,
                                 self.sigma, {"red": red, "blue": blue}, **common)

    def _status(self, context: MatchContext, strategy_red: Strategy,
                strategy_blue: Strategy) -> tuple[str, tuple[str, ...]]:
        reasons: list[str] = []
        roles = {r.role for s in (strategy_red, strategy_blue) for r in s.robots}
        if not (strategy_red.is_baseline() and strategy_blue.is_baseline()):
            reasons.append(REASON_STRATEGY)
        if "defense" in roles:
            reasons.append(REASON_DEFENSE)
        if "feeding" in roles:
            reasons.append(REASON_FEEDING)
        if context.observations:
            reasons.append(REASON_OBSERVATION)
        if reasons:
            return NOT_VALIDATED, tuple(reasons)
        status, reason = self.baseline_status
        return status, (() if reason is None else (reason,))

    # --- fit (spec §4) -----------------------------------------------------------------------------------

    @classmethod
    def fit(cls, samples: Sequence[FitSample], *, fit_info: dict[str, Any], spec_sha256: str) -> ComponentOutcomeModel:
        if not samples:
            raise ValueError("no fit samples")
        beta = {}
        for c in SCORING_COMPONENTS:
            x = np.array([s.delta[c] for s in samples])
            y = np.array([s.d[c] for s in samples])
            denominator = float(np.dot(x, x))
            if denominator <= 0:
                raise ValueError(f"no variation in the predicted {c} difference")
            beta[c] = float(np.dot(x, y) / denominator)
        residuals = np.array([[s.d[c] - (beta[c] * s.delta[c] if c in beta else 0.0) for c in FIT_COMPONENTS]
                              for s in samples])
        sigma_matrix = residuals.T @ residuals / len(samples)
        return cls(beta, sigma_matrix.tolist(), fit_info={**fit_info, "n": len(samples)}, spec_sha256=spec_sha256)

    # --- persistence (registry duck-typing: save / load) -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"model_type": MODEL_TYPE, "model_version": MODEL_VERSION, "beta": self.beta,
                "sigma_matrix": self.sigma_matrix.tolist(), "components": list(FIT_COMPONENTS),
                "spec_sha256": self.spec_sha256, "fit_info": self.fit_info}

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ComponentOutcomeModel:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("model_type") != MODEL_TYPE:
            raise ValueError(f"{path} is not a {MODEL_TYPE} artifact")
        return cls(data["beta"], data["sigma_matrix"], fit_info=data["fit_info"], spec_sha256=data["spec_sha256"],
                   artifact_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())

    def with_status(self, *, version_tag: str, baseline_status: tuple[str, str | None]) -> ComponentOutcomeModel:
        return ComponentOutcomeModel(self.beta, self.sigma_matrix.tolist(), fit_info=self.fit_info,
                                     spec_sha256=self.spec_sha256, version_tag=version_tag,
                                     artifact_sha256=self.artifact_sha256, baseline_status=baseline_status)


# --- fit-sample construction (spec §4) ------------------------------------------------------------------


def normalized_difference(red: ScoreComponents, blue: ScoreComponents, scale: float) -> dict[str, float]:
    return {"auto": (red.auto - blue.auto) / scale, "teleop": (red.teleop - blue.teleop) / scale,
            "endgame": (red.endgame - blue.endgame) / scale,
            "other": ((red.fouls + red.adjust) - (blue.fouls + blue.adjust)) / scale}


def fit_sample(red_teams: Sequence[TeamFeatures], blue_teams: Sequence[TeamFeatures], red: ScoreComponents,
               blue: ScoreComponents) -> FitSample:
    context = MatchContext(tuple(red_teams), tuple(blue_teams))
    if missing_inputs(context):
        raise ValueError("fit rows must have every input")
    scale = _scale(context)
    baseline_red = Strategy.baseline([t.team_number for t in red_teams])
    baseline_blue = Strategy.baseline([t.team_number for t in blue_teams])
    mu_red = alliance_means(red_teams, baseline_red, ())
    mu_blue = alliance_means(blue_teams, baseline_blue, ())
    delta = {c: mu_red[c] - mu_blue[c] for c in SCORING_COMPONENTS}
    return FitSample(delta, normalized_difference(red, blue, scale))
