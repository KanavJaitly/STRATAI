"""Phase 4 Milestone 9: alliance synergy scoring, ml.synergy.score.

Every TeamFeatures value in this file is synthetic and hand-constructed for
unit testing -- there is no "real" alliance synergy ground truth anywhere
to validate against (the milestone's own brief: "a documented weighted
combination", not a fitted or empirically-validated model), so this file
tests the documented formula's own properties instead: the milestone's
three named tests (complementarity, determinism + weight-config,
insufficient-data honesty) plus each component's own edge cases.
"""

from __future__ import annotations

import pytest

from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.synergy.score import DEFAULT_SYNERGY_WEIGHTS, SynergyWeights, alliance_synergy


def _team(
    team_number: int, *,
    average_score: float | None = None,
    defense_score: float | None = None,
    feeding_score: float | None = None,
    epa_auto: float | None = None,
    epa_teleop: float | None = None,
    epa_endgame: float | None = None,
) -> TeamFeatures:
    any_epa_present = epa_auto is not None or epa_teleop is not None or epa_endgame is not None
    return TeamFeatures(
        team_number=team_number,
        epa_total=None, epa_total_present=False,
        epa_auto=epa_auto, epa_auto_present=epa_auto is not None,
        epa_teleop=epa_teleop, epa_teleop_present=epa_teleop is not None,
        epa_endgame=epa_endgame, epa_endgame_present=epa_endgame is not None,
        epa_source_event_key="9970zzzpriorevent" if any_epa_present else None,
        epa_withheld_reason=None if any_epa_present else EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=5, matches_used=5,
        defense_score=defense_score, defense_score_present=defense_score is not None,
        defense_agreement_present=False, defense_observation_count=2 if defense_score is not None else 0,
        feeding_score=feeding_score, feeding_score_present=feeding_score is not None,
        feeding_agreement_present=False, feeding_observation_count=2 if feeding_score is not None else 0,
    )


# ---------------------------------------------------------------------------
# The milestone's own named tests
# ---------------------------------------------------------------------------


def test_complementary_alliance_scores_higher_than_redundant_at_equal_raw_scoring():
    """Two alliances with the identical alliance-total average_score (190),
    but one is three near-identical "pure scorers" and the other is a
    scorer + a defender + a feeder -- synergy != sum of raw scoring."""
    redundant = (
        _team(9800, average_score=190 / 3, defense_score=1.0, feeding_score=1.0),
        _team(9801, average_score=190 / 3, defense_score=1.0, feeding_score=1.0),
        _team(9802, average_score=190 / 3, defense_score=1.0, feeding_score=1.0),
    )
    complementary = (
        _team(9900, average_score=150.0, defense_score=0.5, feeding_score=0.5),
        _team(9901, average_score=20.0, defense_score=4.5, feeding_score=0.5),
        _team(9902, average_score=20.0, defense_score=0.5, feeding_score=4.5),
    )
    assert sum(t.average_score for t in redundant) == pytest.approx(sum(t.average_score for t in complementary))

    redundant_score = alliance_synergy(*redundant)
    complementary_score = alliance_synergy(*complementary)

    assert redundant_score.overall_score is not None and complementary_score.overall_score is not None
    assert complementary_score.overall_score > redundant_score.overall_score
    assert complementary_score.role_fit_term > redundant_score.role_fit_term


def test_three_identical_teams_have_zero_role_fit_and_scoring_distribution():
    """Perfect redundancy (three literally identical profiles) gives
    exactly 0.0 diversity -- real math (cosine similarity of identical
    vectors is exactly 1), not an approximation."""
    teams = tuple(_team(9800 + i, average_score=50.0, defense_score=2.0, feeding_score=2.0,
                         epa_auto=10.0, epa_teleop=10.0, epa_endgame=10.0) for i in range(3))
    result = alliance_synergy(*teams)
    assert result.role_fit_term == pytest.approx(0.0, abs=1e-9)
    assert result.scoring_distribution_term == pytest.approx(0.0, abs=1e-9)


def test_orthogonal_epa_specialists_have_high_scoring_distribution_term():
    """One pure-auto, one pure-teleop, one pure-endgame specialist -- the
    game-phase analogue of the alliance-level complementarity test above."""
    teams = (
        _team(9800, epa_auto=30.0, epa_teleop=0.1, epa_endgame=0.1),
        _team(9801, epa_auto=0.1, epa_teleop=30.0, epa_endgame=0.1),
        _team(9802, epa_auto=0.1, epa_teleop=0.1, epa_endgame=30.0),
    )
    result = alliance_synergy(*teams)
    assert result.scoring_distribution_term is not None and result.scoring_distribution_term > 0.9


def test_determinism_same_inputs_give_identical_result():
    teams = (
        _team(9800, average_score=80.0, defense_score=2.0, feeding_score=1.0),
        _team(9801, average_score=40.0, defense_score=4.0, feeding_score=1.0),
        _team(9802, average_score=40.0, defense_score=1.0, feeding_score=4.0),
    )
    result_a = alliance_synergy(*teams)
    result_b = alliance_synergy(*teams)
    assert result_a == result_b


def test_weight_config_changes_the_overall_score_predictably():
    teams = (
        _team(9800, average_score=150.0, defense_score=0.5, feeding_score=0.5),
        _team(9801, average_score=20.0, defense_score=4.5, feeding_score=0.5),
        _team(9802, average_score=20.0, defense_score=0.5, feeding_score=4.5),
    )
    role_fit_only = alliance_synergy(*teams, weights=SynergyWeights(role_fit=1.0, scoring_distribution=0.0, defense_feeding_coverage=0.0))
    coverage_only = alliance_synergy(*teams, weights=SynergyWeights(role_fit=0.0, scoring_distribution=0.0, defense_feeding_coverage=1.0))
    assert role_fit_only.overall_score == pytest.approx(role_fit_only.role_fit_term)
    assert coverage_only.overall_score == pytest.approx(coverage_only.defense_feeding_coverage_term)


def test_synergy_weights_rejects_negative_component():
    with pytest.raises(ValueError, match=">= 0"):
        SynergyWeights(role_fit=-0.1)


def test_synergy_weights_rejects_all_zero():
    with pytest.raises(ValueError, match="at least one"):
        SynergyWeights(role_fit=0.0, scoring_distribution=0.0, defense_feeding_coverage=0.0)


def test_insufficient_data_lowers_confidence_not_silently_zero():
    """A team with no defense/feeding data at all must not make the
    coverage term read as "measured and bad" (0.0) -- it must exclude that
    team's absent values and lower confidence instead."""
    full_coverage = (
        _team(9800, average_score=50.0, defense_score=3.0, feeding_score=3.0),
        _team(9801, average_score=50.0, defense_score=3.0, feeding_score=3.0),
        _team(9802, average_score=50.0, defense_score=3.0, feeding_score=3.0),
    )
    partial_coverage = (
        _team(9900, average_score=50.0, defense_score=3.0, feeding_score=3.0),
        _team(9901, average_score=50.0, defense_score=3.0, feeding_score=3.0),
        _team(9902, average_score=50.0),  # defense/feeding entirely absent
    )
    full_result = alliance_synergy(*full_coverage)
    partial_result = alliance_synergy(*partial_coverage)

    # Coverage TERM (the mean of present values) is unaffected by the
    # missing team's absence, since it excludes rather than zero-fills --
    # both alliances' present defense/feeding values are all 3.0/5.0.
    assert full_result.defense_feeding_coverage_term == pytest.approx(partial_result.defense_feeding_coverage_term)
    # But present_count and confidence DO reflect the missing data.
    assert partial_result.defense_feeding_coverage_present_count == 4  # out of 6
    assert full_result.defense_feeding_coverage_present_count == 6
    assert partial_result.confidence < full_result.confidence


def test_zero_usable_axes_reports_none_not_a_fabricated_value():
    teams = tuple(_team(9800 + i) for i in range(3))  # nothing present at all
    result = alliance_synergy(*teams)
    assert result.role_fit_term is None
    assert result.scoring_distribution_term is None
    assert result.defense_feeding_coverage_term is None
    assert result.overall_score is None
    assert result.confidence == 0.0


def test_one_usable_axis_gives_zero_not_none():
    """Exactly one team-field present across all three teams -- there is
    only one comparable axis, so diversity is structurally 0.0 (see
    _pairwise_cosine_diversity's own docstring), distinguishable from the
    zero-usable-axes case (None) above."""
    teams = (
        _team(9800, average_score=80.0),
        _team(9801, average_score=40.0),
        _team(9802, average_score=20.0),
    )
    result = alliance_synergy(*teams)
    assert result.role_fit_term == pytest.approx(0.0)
    assert result.role_fit_axes_used == ["average_score"]


def test_one_team_missing_one_axis_excludes_only_that_axis():
    teams = (
        _team(9800, average_score=80.0, defense_score=2.0, feeding_score=1.0),
        _team(9801, average_score=40.0, defense_score=4.0, feeding_score=1.0),
        _team(9802, average_score=40.0, defense_score=1.0),  # feeding_score absent
    )
    result = alliance_synergy(*teams)
    assert "feeding_score" not in result.role_fit_axes_used
    assert "average_score" in result.role_fit_axes_used
    assert "defense_score" in result.role_fit_axes_used


def test_default_synergy_weights_sum_to_one():
    assert DEFAULT_SYNERGY_WEIGHTS.role_fit + DEFAULT_SYNERGY_WEIGHTS.scoring_distribution + DEFAULT_SYNERGY_WEIGHTS.defense_feeding_coverage == pytest.approx(1.0)


def test_overall_score_and_confidence_are_within_documented_bounds():
    teams = (
        _team(9800, average_score=80.0, defense_score=2.0, feeding_score=1.0, epa_auto=5.0, epa_teleop=10.0, epa_endgame=2.0),
        _team(9801, average_score=40.0, defense_score=4.0, feeding_score=1.0, epa_auto=2.0, epa_teleop=15.0, epa_endgame=1.0),
        _team(9802, average_score=40.0, defense_score=1.0, feeding_score=4.0, epa_auto=1.0, epa_teleop=8.0, epa_endgame=6.0),
    )
    result = alliance_synergy(*teams)
    assert 0.0 <= result.confidence <= 1.0
    assert result.overall_score is not None and 0.0 <= result.overall_score <= 1.0
