"""P6-M9 representation and P6-M10 component-model mechanics, on synthetic fixtures only."""

from __future__ import annotations

import itertools
import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from api.routes.predictions import display_probability
from ml.features.score_components import ScoreComponents
from ml.strategy.display import (BELOW_LOW, ABOVE_HIGH, INDISTINGUISHABLE, compare_odds, display_odds,
                                 rounded_probability)
from ml.strategy.outcome import (INSUFFICIENT_DATA, NOT_VALIDATED, REASON_DEFENSE, REASON_FEEDING,
                                 REASON_OBSERVATION, REASON_PLAYOFF, REASON_STRATEGY, VALIDATED,
                                 ComponentOutcomeModel, FitSample, MatchContext, fit_sample)
from ml.strategy.representation import CoachObservation, RobotPlan, Strategy, StrategyProvenance
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)
RED, BLUE = (1, 2, 3), (4, 5, 6)


def model(**kwargs) -> ComponentOutcomeModel:
    return ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64, **kwargs)


def context(**kwargs) -> MatchContext:
    red = tuple(team(n, 6.0, 25.0, 4.0) for n in RED)
    blue = tuple(team(n, 4.0, 18.0, 6.0) for n in BLUE)
    return MatchContext(red, blue, **kwargs)


# --- P6-M9: representation ----------------------------------------------------------------------------


def test_strategy_has_no_origin_field_and_forbids_one():
    assert not ({"origin", "source", "author", "provenance", "proposer"} & set(Strategy.model_fields))
    with pytest.raises(ValidationError):
        Strategy.model_validate({"robots": [{"team_number": n} for n in RED], "origin": "optimizer_output"})


def test_robot_plan_rules():
    assert RobotPlan(team_number=1, components=("endgame", "auto")).components == ("auto", "endgame")
    with pytest.raises(ValidationError):
        RobotPlan(team_number=1, role="defense", defense_target=4)  # teleop needs the scoring role
    with pytest.raises(ValidationError):
        RobotPlan(team_number=1, role="defense", components=("auto",))  # a defender needs a target
    with pytest.raises(ValidationError):
        RobotPlan(team_number=1, role="feeding", components=(), feed_target=1)
    with pytest.raises(ValidationError):
        Strategy(robots=(RobotPlan(team_number=1, role="feeding", components=(), feed_target=9),
                         RobotPlan(team_number=2), RobotPlan(team_number=3)))  # feeds a non-ally


def test_baseline_and_canonical_identity():
    baseline = Strategy.baseline(RED)
    assert baseline.is_baseline() and baseline.changes_from_baseline() == 0
    reordered = Strategy.baseline((3, 1, 2))
    assert reordered.sha256() == baseline.sha256()


def test_provenance_is_separate_and_timezone_aware():
    with pytest.raises(ValidationError):
        StrategyProvenance(origin="human_entered", author="Coach", created_at=datetime(2026, 1, 1))
    assert StrategyProvenance(origin="optimizer_output", author="engine", created_at=NOW).origin == "optimizer_output"


def test_observation_schema_has_no_free_text():
    assert set(CoachObservation.model_fields) == {"event_key", "team_number", "kind", "component", "observed_at",
                                                 "observer"}
    with pytest.raises(ValidationError):
        CoachObservation(event_key="e", team_number=1, kind="component_unavailable", observed_at=NOW, observer="c")


# --- P6-A5 display ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("p,shown", [(0.0, BELOW_LOW), (0.02, BELOW_LOW), (0.0499, BELOW_LOW), (0.05, "5%"),
                                     (0.12, "10%"), (0.5, "50%"), (0.95, "95%"), (0.951, ABOVE_HIGH),
                                     (1.0, ABOVE_HIGH)])
def test_display_bounds_low_odds_honestly(p, shown):
    assert display_odds(p) == shown


def test_display_rounding_equals_the_phase4_rule_inside_the_range():
    for k in range(50, 951):
        p = k / 1000
        assert rounded_probability(p) == display_probability(p)


def test_comparison_never_claims_superiority():
    assert compare_odds(0.62, 0.60)["label"] == INDISTINGUISHABLE
    far = compare_odds(0.70, 0.50)
    assert "not a claim" in far["label"] and "better" in far["label"]


# --- P6-M10 mechanics --------------------------------------------------------------------------------------


def test_baseline_evaluation_and_exact_swap_symmetry():
    m = model(baseline_status=(VALIDATED, None))
    ctx = context()
    forward = m.evaluate(ctx, Strategy.baseline(RED), Strategy.baseline(BLUE))
    backward = m.evaluate(ctx.swapped(), Strategy.baseline(BLUE), Strategy.baseline(RED))
    assert forward.validation_status == VALIDATED and forward.reasons == ()
    assert abs(forward.p_red + backward.p_red - 1.0) <= 1e-12
    assert forward.p_red == backward.p_blue
    assert forward.p_red > 0.5  # red's measured capability is higher


def test_strategy_can_only_withhold_capability():
    m = model()
    ctx = context()
    baseline = m.evaluate(ctx, Strategy.baseline(RED), Strategy.baseline(BLUE)).p_red
    defend = Strategy(robots=(RobotPlan(team_number=1, role="defense", components=("auto", "endgame"),
                                        defense_target=4), RobotPlan(team_number=2), RobotPlan(team_number=3)))
    result = m.evaluate(ctx, defend, Strategy.baseline(BLUE))
    assert result.p_red < baseline  # the defender's teleop is withheld and no defense effect is measured
    assert result.validation_status == NOT_VALIDATED
    assert set(result.reasons) == {REASON_STRATEGY, REASON_DEFENSE}


def test_feeding_role_is_labelled():
    feed = Strategy(robots=(RobotPlan(team_number=1, role="feeding", components=("auto",), feed_target=2),
                            RobotPlan(team_number=2), RobotPlan(team_number=3)))
    result = model().evaluate(context(), feed, Strategy.baseline(BLUE))
    assert REASON_FEEDING in result.reasons


def test_observations_apply_to_both_paths_through_the_context():
    obs = CoachObservation(event_key="e", team_number=1, kind="component_unavailable", component="teleop",
                           observed_at=NOW, observer="Coach")
    m = model()
    plain = m.evaluate(context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    observed = m.evaluate(context(observations=(obs,)), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert observed.p_red < plain.p_red and observed.reasons == (REASON_OBSERVATION,)


def test_negative_epa_is_zero_capability():
    m = model()
    red = (team(1, -2.0, 20.0, 5.0), team(2), team(3))
    ctx = MatchContext(red, tuple(team(n) for n in BLUE))
    with_auto = m.evaluate(ctx, Strategy.baseline(RED), Strategy.baseline(BLUE)).p_red
    no_auto = Strategy(robots=(RobotPlan(team_number=1, components=("teleop", "endgame")), RobotPlan(team_number=2),
                               RobotPlan(team_number=3)))
    assert m.evaluate(ctx, no_auto, Strategy.baseline(BLUE)).p_red == with_auto


def test_missing_input_is_insufficient_data_never_imputed():
    red = (team(1, epa_scale=None), team(2), team(3))
    result = model().evaluate(MatchContext(red, tuple(team(n) for n in BLUE)), Strategy.baseline(RED),
                              Strategy.baseline(BLUE))
    assert result.p_red is None and result.validation_status == INSUFFICIENT_DATA
    assert "missing_input:1:epa_scale" in result.reasons


def test_playoff_context_is_refused():
    result = model().evaluate(context(comp_level="semifinal"), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert result.p_red is None and result.reasons == (REASON_PLAYOFF,)


def test_unknown_baseline_status_is_not_validated():
    result = model().evaluate(context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert result.validation_status == NOT_VALIDATED


def test_fit_recovers_known_parameters_and_round_trips(tmp_path):
    import numpy as np

    rng = np.random.default_rng(7)
    true_beta = {"auto": 1.1, "teleop": 0.7, "endgame": 0.4}
    samples = []
    for _ in range(4000):
        delta = {c: float(rng.normal(0, 1)) for c in true_beta}
        d = {c: true_beta[c] * delta[c] + float(rng.normal(0, 0.3)) for c in true_beta}
        d["other"] = float(rng.normal(0, 0.2))
        samples.append(FitSample(delta, d))
    fitted = ComponentOutcomeModel.fit(samples, fit_info={"note": "synthetic"}, spec_sha256="0" * 64)
    for c, value in true_beta.items():
        assert abs(fitted.beta[c] - value) < 0.03
    assert abs(fitted.sigma_matrix[3][3] - 0.04) < 0.01
    path = tmp_path / "model.json"
    fitted.save(path)
    loaded = ComponentOutcomeModel.load(path)
    assert loaded.beta == fitted.beta and loaded.sigma == fitted.sigma


def test_fit_sample_uses_baseline_capabilities_and_normalized_actuals():
    red = tuple(team(n, 6.0, 25.0, 4.0) for n in RED)
    blue = tuple(team(n, 4.0, 18.0, 6.0) for n in BLUE)
    a = ScoreComponents(auto=20, teleop=70, endgame=10, fouls=5, adjust=0, total=105)
    b = ScoreComponents(auto=10, teleop=50, endgame=20, fouls=0, adjust=1, total=81)
    sample = fit_sample(red, blue, a, b)
    assert math.isclose(sample.delta["teleop"], 3 * (25.0 - 18.0) / 10.0)
    assert sample.d == {"auto": 0.5, "teleop": 1.0, "endgame": -0.5, "other": 0.2}


def test_strategy_must_match_the_alliance():
    from ml.strategy.representation import StrategyError

    with pytest.raises(StrategyError):
        model().evaluate(context(), Strategy.baseline((1, 2, 7)), Strategy.baseline(BLUE))
    defend_ally = Strategy(robots=(RobotPlan(team_number=1, role="defense", components=(), defense_target=9),
                                   RobotPlan(team_number=2), RobotPlan(team_number=3)))
    with pytest.raises(StrategyError):
        model().evaluate(context(), defend_ally, Strategy.baseline(BLUE))
    assert NOW + timedelta(0) == NOW


def test_event_bootstrap_is_deterministic_and_pooled():
    from ml.backtest.bootstrap import ci_excludes_zero, event_bootstrap_mean_ci

    values = {"e1": [1.0, 1.0], "e2": [0.0], "e3": [2.0, 0.0, 1.0]}
    first = event_bootstrap_mean_ci(values, seed=11, resamples=500)
    assert first == event_bootstrap_mean_ci(values, seed=11, resamples=500)
    assert first["mean"] == 5.0 / 6.0 and first["events"] == 3 and first["units"] == 6
    assert first["ci_low"] <= first["mean"] <= first["ci_high"]
    assert ci_excludes_zero({"ci_low": 0.1, "ci_high": 0.2}) and not ci_excludes_zero({"ci_low": -0.1, "ci_high": 0.2})


def test_alliance_means_are_order_free_to_the_last_bit():
    """P6-M13 run-1 defect: plain addition made the sum depend on team order by one ULP."""
    from ml.strategy.outcome import alliance_means

    values = [(0.1, 0.3, 0.7), (0.2, 0.2, 0.1), (0.3, 0.1, 0.2)]  # plain sums of these depend on order
    teams = [team(10 + i, a, b, c, epa_scale=1.0) for i, (a, b, c) in enumerate(values)]
    strategy = Strategy.baseline([t.team_number for t in teams])
    forward = alliance_means(teams, strategy, ())
    def plain_sum(order, c):  # left-to-right addition, as the run-1 code accumulated (+=)
        total = 0.0
        for i in order:
            total += values[i][c]
        return total

    assert len({plain_sum(o, 0) for o in itertools.permutations(range(3))}) > 1  # really order-sensitive
    for order in itertools.permutations(range(3)):
        assert alliance_means([teams[i] for i in order], strategy, ()) == forward
