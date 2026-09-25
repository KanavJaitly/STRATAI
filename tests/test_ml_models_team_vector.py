"""ml.models.team_vector: the shared team-level feature vector construction
used by both Milestone 5 (ranking_xgb) and Milestone 6 (win_prob). Split out
specifically so both models could reuse one implementation rather than
duplicating it -- this file pins that shared contract directly, independent
of either model.
"""

from __future__ import annotations

from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.models.team_vector import TEAM_FEATURE_NAMES, team_features_to_vector


def _team_features(*, epa_total: float | None = None, average_score: float | None = None) -> TeamFeatures:
    return TeamFeatures(
        team_number=9800,
        epa_total=epa_total, epa_total_present=epa_total is not None,
        epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key="9990zzzpriorevent" if epa_total is not None else None,
        epa_withheld_reason=None if epa_total is not None else EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=3, matches_used=3,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=1,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=2,
    )


def test_vector_length_matches_feature_names():
    vector = team_features_to_vector(_team_features())
    assert vector.shape == (len(TEAM_FEATURE_NAMES),)


def test_absent_optional_fields_are_nan():
    vector = team_features_to_vector(_team_features())
    for name in ("epa_total", "epa_auto", "epa_teleop", "epa_endgame",
                 "average_score", "score_stddev", "consistency_rating", "reliability_score",
                 "defense_score", "defense_agreement", "feeding_score", "feeding_agreement"):
        value = vector[TEAM_FEATURE_NAMES.index(name)]
        assert value != value, f"{name} should be NaN when absent"


def test_present_values_pass_through_unchanged():
    vector = team_features_to_vector(_team_features(epa_total=12.5, average_score=88.0))
    assert vector[TEAM_FEATURE_NAMES.index("epa_total")] == 12.5
    assert vector[TEAM_FEATURE_NAMES.index("average_score")] == 88.0


def test_count_fields_are_never_nan_even_when_zero():
    vector = team_features_to_vector(_team_features())
    for name in ("matches_considered", "matches_used", "defense_observation_count", "feeding_observation_count"):
        value = vector[TEAM_FEATURE_NAMES.index(name)]
        assert value == value  # not NaN
    assert vector[TEAM_FEATURE_NAMES.index("matches_considered")] == 3.0
    assert vector[TEAM_FEATURE_NAMES.index("defense_observation_count")] == 1.0
    assert vector[TEAM_FEATURE_NAMES.index("feeding_observation_count")] == 2.0


def test_a_real_zero_value_is_distinguishable_from_absence():
    """The sentinel-collision concern Milestone 1's own assembler was tested
    against: a genuine defense_score of exactly 0.0 (a real measured value,
    not a sentinel) must still come through as 0.0, not NaN."""
    team = _team_features().model_copy(update={"average_score": 0.0, "average_score_present": True})
    vector = team_features_to_vector(team)
    assert vector[TEAM_FEATURE_NAMES.index("average_score")] == 0.0
