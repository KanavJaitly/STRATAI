"""P6-M13 / P6-DM2: the odds-parity and unbiasedness audit for the AI and coach strategy paths.

Every check takes an engine, so the same audit runs on the real `StrategyEngine` and on deliberately broken engines
(the Phase 4 M8 "teeth" standard). The audit passes only if every check passes on the real engine, and every planted
defect is caught.

**Structural checks:**
- S1: no evaluation input type has a field that could carry a strategy's origin.
- S2: the model has one evaluation entry point, taking only (context, strategy_red, strategy_blue).
- S3: the engine module computes no probability itself. It has no reference to the model's internals (Φ, erfc, the
  normal distribution), and its one probability-producing call is `model.evaluate`.

**Metamorphic checks:**
- M1: a coach strategy identical to the AI's recommendation gets bit-identical odds, status and display.
- M2: the recommended odds are exactly the maximum of `assess` over every candidate. Nothing inflates the winner.
- M3: robot order within a strategy, and team order within an alliance, do not change the odds.
- M4: assessing a side, and the same side with the colours swapped, give identical odds, and p(R, B) + p(B, R) = 1.
- M5: the recommender's display equals the single display rule applied to its probability.
- M6: missing data is handled identically. The coach path returns no probability, and the recommender returns no
  recommendation. Nothing is imputed for the AI.
- M7: low odds are reported honestly. A raw probability below 0.05 is kept unclamped and shown as "<5%" on both paths.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ml.strategy import engine as engine_module
from ml.strategy.display import BELOW_LOW, display_odds
from ml.strategy.engine import StrategyEngine, candidate_strategies
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext
from ml.strategy.representation import CoachObservation, RobotPlan, Strategy

DISALLOWED_FIELD_PARTS = ("source", "origin", "author", "provenance", "proposer", "optimizer", "recommend",
                          "coach", "creator", "ai_")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    cases: int = 0


@dataclass
class AuditContexts:
    """The contexts an audit runs on: ordinary ones, one with an absent input, and one with low odds."""

    ordinary: list[MatchContext]
    missing_input: MatchContext
    low_odds: tuple[MatchContext, str]  # a context and the side whose odds are below 0.05
    full_search: list[MatchContext] = field(default_factory=list)


def _fail(name: str, detail: str, cases: int = 0) -> CheckResult:
    return CheckResult(name, False, detail, cases)


def check_s1_no_origin_fields() -> CheckResult:
    names = {"Strategy": Strategy.model_fields, "RobotPlan": RobotPlan.model_fields,
             "CoachObservation": CoachObservation.model_fields,
             "MatchContext": MatchContext.__dataclass_fields__}
    bad = [f"{cls}.{f}" for cls, fields in names.items() for f in fields
           if any(part in f.lower() for part in DISALLOWED_FIELD_PARTS)]
    forbid = Strategy.model_config.get("extra") == "forbid" and RobotPlan.model_config.get("extra") == "forbid"
    return CheckResult("S1_no_origin_fields", not bad and forbid,
                       f"origin-like fields: {bad}; extra=forbid: {forbid}")


def check_s2_single_entry_point(model: Any) -> CheckResult:
    parameters = list(inspect.signature(model.evaluate).parameters)
    ok = parameters == ["context", "strategy_red", "strategy_blue"]
    return CheckResult("S2_single_entry_point", ok, f"evaluate parameters: {parameters}")


def check_s3_engine_computes_no_probability(engine: Any) -> CheckResult:
    source = inspect.getsource(engine_module) if type(engine) is StrategyEngine else inspect.getsource(type(engine))
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    forbidden = sorted(names & {"_phi", "erfc", "erf", "norm", "cdf", "beta", "sigma_matrix", "sigma"})
    evaluate_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "evaluate"]
    ok = not forbidden and len(evaluate_calls) == 1
    return CheckResult("S3_engine_computes_no_probability", ok,
                       f"model internals referenced: {forbidden}; model.evaluate call sites: {len(evaluate_calls)}")


def _sides(context: MatchContext) -> list[str]:
    return ["red", "blue"]


def check_m1_identical_strategy_identical_odds(engine: Any, contexts: Sequence[MatchContext]) -> CheckResult:
    cases = 0
    for context in contexts:
        for side in _sides(context):
            ai = engine.recommend(context, side)
            if ai.recommended is None:
                continue
            coach = StrategyEngine.assess(engine, context, side, ai.recommended.strategy)
            cases += 1
            if (ai.recommended.p_ours != coach.p_ours or ai.recommended.display_ours != coach.display_ours
                    or ai.recommended.evaluation.validation_status != coach.evaluation.validation_status
                    or ai.recommended.evaluation.sigma != coach.evaluation.sigma):
                return _fail("M1_identical_strategy_identical_odds",
                             f"AI {ai.recommended.p_ours!r} / {ai.recommended.display_ours} vs coach "
                             f"{coach.p_ours!r} / {coach.display_ours}", cases)
    return CheckResult("M1_identical_strategy_identical_odds", cases > 0, "bit-identical on every case", cases)


def check_m2_recommended_is_true_maximum(engine: Any, contexts: Sequence[MatchContext]) -> CheckResult:
    cases = 0
    for context in contexts:
        side = "red"
        own = [t.team_number for t in context.red_teams]
        opponents = [t.team_number for t in context.blue_teams]
        best = max(StrategyEngine.assess(engine, context, side, s).p_ours for s in candidate_strategies(own, opponents))
        recommended = engine.recommend(context, side).recommended
        cases += 1
        if recommended is None or recommended.p_ours != best:
            return _fail("M2_recommended_is_true_maximum",
                         f"recommended {None if recommended is None else recommended.p_ours!r} vs maximum {best!r}",
                         cases)
    return CheckResult("M2_recommended_is_true_maximum", cases > 0, "equal to the exhaustive maximum", cases)


def check_m3_order_invariance(engine: Any, contexts: Sequence[MatchContext]) -> CheckResult:
    cases = 0
    for context in contexts:
        ai = engine.recommend(context, "red").recommended
        if ai is None:
            continue
        reordered_strategy = Strategy(robots=tuple(reversed(ai.strategy.robots)))  # type: ignore[arg-type]
        reordered_context = MatchContext(tuple(reversed(context.red_teams)), tuple(reversed(context.blue_teams)),
                                         context.comp_level, context.observations)
        p = StrategyEngine.assess(engine, reordered_context, "red", reordered_strategy).p_ours
        cases += 1
        if p != ai.p_ours:
            return _fail("M3_order_invariance", f"{ai.p_ours!r} vs reordered {p!r}", cases)
    return CheckResult("M3_order_invariance", cases > 0, "invariant", cases)


def check_m4_colour_swap(engine: Any, contexts: Sequence[MatchContext]) -> CheckResult:
    cases = 0
    for context in contexts:
        ai = engine.recommend(context, "red").recommended
        if ai is None:
            continue
        swapped = StrategyEngine.assess(engine, context.swapped(), "blue", ai.strategy).p_ours
        complement = ai.evaluation.p_red + StrategyEngine.assess(
            engine, context.swapped(), "red", ai.opponent_strategy, ai.strategy).evaluation.p_red
        cases += 1
        if swapped != ai.p_ours or abs(complement - 1.0) > 1e-12:
            return _fail("M4_colour_swap", f"{ai.p_ours!r} vs swapped {swapped!r}; p+p' = {complement!r}", cases)
    return CheckResult("M4_colour_swap", cases > 0, "identical; complements sum to 1", cases)


def check_m5_display_parity(engine: Any, contexts: Sequence[MatchContext]) -> CheckResult:
    cases = 0
    for context in contexts:
        for side in _sides(context):
            recommendation = engine.recommend(context, side)
            for assessment in [recommendation.recommended, *recommendation.alternatives]:
                if assessment is None:
                    continue
                cases += 1
                if assessment.display_ours != display_odds(assessment.p_ours):
                    return _fail("M5_display_parity",
                                 f"shown {assessment.display_ours} for p={assessment.p_ours!r}", cases)
    return CheckResult("M5_display_parity", cases > 0, "one display rule", cases)


def check_m6_missing_data_parity(engine: Any, context: MatchContext) -> CheckResult:
    own = [t.team_number for t in context.red_teams]
    coach = StrategyEngine.assess(engine, context, "red", Strategy.baseline(own))
    ai = engine.recommend(context, "red")
    ok = coach.p_ours is None and ai.recommended is None and not ai.alternatives
    return CheckResult("M6_missing_data_parity", ok,
                       f"coach p={coach.p_ours!r}; AI recommendation present: {ai.recommended is not None}", 1)


def check_m7_low_odds_honesty(engine: Any, context: MatchContext, side: str) -> CheckResult:
    ai = engine.recommend(context, side).recommended
    coach = StrategyEngine.assess(engine, context, side, ai.strategy) if ai is not None else None
    ok = (ai is not None and ai.p_ours < 0.05 and ai.display_ours == BELOW_LOW
          and coach.p_ours == ai.p_ours and coach.display_ours == BELOW_LOW)
    return CheckResult("M7_low_odds_honesty", ok,
                       f"AI p={None if ai is None else ai.p_ours!r} shown {None if ai is None else ai.display_ours}", 1)


def run_audit(engine: Any, contexts: AuditContexts) -> list[CheckResult]:
    return [
        check_s1_no_origin_fields(),
        check_s2_single_entry_point(engine.model),
        check_s3_engine_computes_no_probability(engine),
        check_m1_identical_strategy_identical_odds(engine, contexts.ordinary),
        check_m2_recommended_is_true_maximum(engine, contexts.full_search or contexts.ordinary[:1]),
        check_m3_order_invariance(engine, contexts.ordinary),
        check_m4_colour_swap(engine, contexts.ordinary),
        check_m5_display_parity(engine, contexts.ordinary),
        check_m6_missing_data_parity(engine, contexts.missing_input),
        check_m7_low_odds_honesty(engine, *contexts.low_odds),
    ]


# --- planted defects (each must be caught) -----------------------------------------------------------------


class _ScaledModel:
    """A model whose odds differ from the real one: used only by planted defects."""

    def __init__(self, model: ComponentOutcomeModel, *, beta_factor: float = 1.0, sigma_factor: float = 1.0,
                 mean_bonus: float = 0.0) -> None:
        self.inner = ComponentOutcomeModel({c: v * beta_factor for c, v in model.beta.items()},
                                           (model.sigma_matrix * sigma_factor ** 2).tolist(), fit_info=model.fit_info,
                                           spec_sha256=model.spec_sha256, version_tag=model.version_tag,
                                           artifact_sha256=model.artifact_sha256,
                                           baseline_status=model.baseline_status)
        self.mean_bonus = mean_bonus

    def evaluate(self, context, strategy_red, strategy_blue):
        result = self.inner.evaluate(context, strategy_red, strategy_blue)
        if self.mean_bonus and result.p_red is not None:
            from ml.strategy.outcome import _phi

            mean = result.mean_difference + self.mean_bonus
            result = replace(result, p_red=_phi(mean / result.sigma), p_blue=_phi(-mean / result.sigma),
                             display_red=display_odds(_phi(mean / result.sigma)),
                             display_blue=display_odds(_phi(-mean / result.sigma)), mean_difference=mean)
        return result


class _AiOnlyModelEngine(StrategyEngine):
    """Base for defects that give the recommender a different model than the coach path."""

    ai_model: Any = None

    def recommend(self, context, side, opponent_strategy=None, max_alternatives=5):
        real = self.model
        self.model = self.ai_model
        try:
            return StrategyEngine.recommend(self, context, side, opponent_strategy, max_alternatives)
        finally:
            self.model = real


def planted_source_dependent_weighting(model):
    e = _AiOnlyModelEngine(model)
    e.ai_model = _ScaledModel(model, beta_factor=1.05)
    return e


def planted_hidden_ai_only_feature(model):
    e = _AiOnlyModelEngine(model)
    e.ai_model = _ScaledModel(model, mean_bonus=0.05)
    return e


def planted_different_calibration(model):
    e = _AiOnlyModelEngine(model)
    e.ai_model = _ScaledModel(model, sigma_factor=0.8)
    return e


class _PostAdjustEngine(StrategyEngine):
    adjust: Callable[[Any], Any] = staticmethod(lambda a: a)

    def recommend(self, context, side, opponent_strategy=None, max_alternatives=5):
        result = StrategyEngine.recommend(self, context, side, opponent_strategy, max_alternatives)
        if result.recommended is None:
            return result
        return replace(result, recommended=self.adjust(result.recommended),
                       alternatives=tuple(self.adjust(a) for a in result.alternatives))


def planted_ai_only_adjustment(model):
    e = _PostAdjustEngine(model)
    e.adjust = lambda a: replace(a, p_ours=min(1.0, a.p_ours + 0.02), display_ours=display_odds(min(1.0, a.p_ours + 0.02)))
    return e


def planted_different_rounding(model):
    import math

    e = _PostAdjustEngine(model)
    e.adjust = lambda a: replace(a, display_ours=f"{math.ceil(a.p_ours * 20) * 5}%")
    return e


def planted_probability_inflation(model):
    e = _PostAdjustEngine(model)
    e.adjust = lambda a: replace(a, p_ours=max(a.p_ours, 0.10), display_ours=display_odds(max(a.p_ours, 0.10)))
    return e


class _ImputingEngine(StrategyEngine):
    """Missing-data defect: the recommender imputes absent capability as zero, the coach path does not."""

    def recommend(self, context, side, opponent_strategy=None, max_alternatives=5):
        def fill(team):
            if team.epa_scale is None or team.epa_auto is None:
                return team.model_copy(update={"epa_auto": 0.0, "epa_teleop": 0.0, "epa_endgame": 0.0,
                                               "epa_total": 0.0, "epa_auto_present": True,
                                               "epa_teleop_present": True, "epa_endgame_present": True,
                                               "epa_total_present": True, "epa_scale": team.epa_scale or 1.0,
                                               "epa_scale_present": True,
                                               "score_scale": team.score_scale or 1.0,
                                               "score_scale_present": True})
            return team
        filled = MatchContext(tuple(fill(t) for t in context.red_teams), tuple(fill(t) for t in context.blue_teams),
                              context.comp_level, context.observations)
        if any(t.score_scale != filled.red_teams[0].score_scale for t in (*filled.red_teams, *filled.blue_teams)):
            scale = next(t.score_scale for t in (*context.red_teams, *context.blue_teams) if t.score_scale) or 1.0
            filled = MatchContext(tuple(t.model_copy(update={"score_scale": scale}) for t in filled.red_teams),
                                  tuple(t.model_copy(update={"score_scale": scale}) for t in filled.blue_teams),
                                  context.comp_level, context.observations)
        return StrategyEngine.recommend(self, filled, side, opponent_strategy, max_alternatives)


def planted_different_missing_data_handling(model):
    return _ImputingEngine(model)


PLANTED_DEFECTS: dict[str, tuple[Callable[[ComponentOutcomeModel], Any], str]] = {
    "source_dependent_weighting": (planted_source_dependent_weighting, "M1_identical_strategy_identical_odds"),
    "hidden_ai_only_feature": (planted_hidden_ai_only_feature, "M1_identical_strategy_identical_odds"),
    "ai_only_adjustment": (planted_ai_only_adjustment, "M1_identical_strategy_identical_odds"),
    "different_rounding": (planted_different_rounding, "M5_display_parity"),
    "different_calibration": (planted_different_calibration, "M1_identical_strategy_identical_odds"),
    "different_missing_data_handling": (planted_different_missing_data_handling, "M6_missing_data_parity"),
    "ai_probability_inflation": (planted_probability_inflation, "M7_low_odds_honesty"),
}
