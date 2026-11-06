"""P11A B4: season scoring configuration parsing, validation, approval gating and scoring math. Synthetic season
9911 only (tests/p11a_support.py)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.stats import norm

from ml.alliance.scoring_config import (
    ResolvedRule,
    ResolvedScoring,
    ScoringConfigError,
    SeasonScoringConfig,
    alliance_component_mean,
    expected_component_points,
    find_config,
    load_config,
    require_approved,
)
from tests.p11a_support import SEASON, approve, game_spec, scoring_config


def test_a_config_needs_exactly_one_rule_per_component():
    data = scoring_config(approved=False).model_dump(mode="json")
    data["rules"] = data["rules"][:2]
    with pytest.raises(ValueError):
        SeasonScoringConfig.model_validate(data)


def test_a_cap_rule_names_its_action_and_count_and_a_sum_rule_has_none():
    data = scoring_config(approved=False).model_dump(mode="json")
    data["rules"][2]["cap_count"] = None
    with pytest.raises(ValueError):
        SeasonScoringConfig.model_validate(data)
    data = scoring_config(approved=False).model_dump(mode="json")
    data["rules"][0]["cap_action_id"] = "auto_piece"
    with pytest.raises(ValueError):
        SeasonScoringConfig.model_validate(data)


def test_unapproved_or_altered_configs_are_refused():
    with pytest.raises(ScoringConfigError) as refused:
        require_approved(None, SEASON)
    assert refused.value.code == "scoring_config_not_approved"
    with pytest.raises(ScoringConfigError) as refused:
        require_approved(scoring_config(approved=False), SEASON)
    assert refused.value.code == "scoring_config_not_approved"
    approved = scoring_config()
    assert require_approved(approved, SEASON) is approved
    altered = approved.model_copy(update={"fouls": "excluded"})  # content changed after review
    with pytest.raises(ScoringConfigError) as refused:
        require_approved(altered, SEASON)
    assert refused.value.code == "scoring_config_not_approved"


def test_point_values_come_from_the_game_spec_and_must_match_it():
    resolved = ResolvedScoring.resolve(scoring_config(), game_spec())
    assert resolved.rules["endgame"].cap_points == 20.0  # 2 x climb (10 points)
    assert resolved.rules["auto"].cap_points is None
    other = game_spec().model_copy(update={"game_name": "DIFFERENT"})
    with pytest.raises(ScoringConfigError) as refused:
        ResolvedScoring.resolve(scoring_config(), other)
    assert refused.value.code == "game_spec_mismatch"


def test_an_action_from_the_wrong_period_is_refused():
    data = scoring_config(approved=False).model_dump(mode="json")
    data["rules"][2]["cap_action_id"] = "teleop_piece"
    approved = approve(SeasonScoringConfig.model_validate(data))
    with pytest.raises(ScoringConfigError) as refused:
        ResolvedScoring.resolve(approved, game_spec())
    assert refused.value.code == "game_spec_mismatch"


def test_configs_load_from_files_and_no_real_season_is_configured(tmp_path):
    path = tmp_path / f"{SEASON}.json"
    path.write_text(scoring_config().model_dump_json())
    assert find_config(SEASON, tmp_path).content_sha256() == scoring_config().content_sha256()
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(ScoringConfigError):
        load_config(tmp_path / "bad.json")
    for season in (2024, 2025, 2026, 2027):  # nothing is entered or approved for any real season
        assert find_config(season) is None


def test_sum_rule_is_linear_so_nothing_is_double_counted():
    rule = ResolvedRule("teleop", None, None, ())
    means = np.array([[10.0, 20.0, 5.0]])
    m = alliance_component_mean(rule, means)
    assert m[0] == 35.0
    assert expected_component_points(rule, m, np.array([16.0]))[0] == pytest.approx(35.0)


def test_alliance_cap_matches_the_analytic_expectation_and_monte_carlo():
    rule = ResolvedRule("endgame", 20.0, None, ())
    mean, var = 18.0, 25.0
    value = float(expected_component_points(rule, mean, var))
    rng = np.random.default_rng(1)
    mc = np.minimum(20.0, rng.normal(mean, 5.0, 400_000)).mean()
    assert value == pytest.approx(mc, abs=0.03)
    assert value < mean  # the cap binds part of the time
    assert float(expected_component_points(rule, 30.0, 0.0)) == 20.0  # degenerate: deterministic cap


def test_threshold_bonus_adds_its_points_times_the_probability():
    rule = ResolvedRule("auto", None, None, ((20.0, 6.0),))
    value = float(expected_component_points(rule, 22.0, 9.0))
    assert value == pytest.approx(22.0 + 6.0 * (1 - norm.cdf((20.0 - 22.0) / 3.0)))


def test_per_robot_caps_apply_to_each_robot_mean():
    rule = ResolvedRule("auto", None, 8.0, ())
    assert alliance_component_mean(rule, np.array([[12.0, 3.0, 9.0]]))[0] == 19.0


def test_the_config_round_trips_through_json():
    config = scoring_config()
    again = SeasonScoringConfig.model_validate(json.loads(config.model_dump_json()))
    assert again == config and again.content_sha256() == config.content_sha256()
