from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from data.metrics.schemas import (
    BAD_DAY_ZSCORE_THRESHOLD,
    DEFENSE_RATING_DESCRIPTIONS,
    FEEDING_RATING_DESCRIPTIONS,
    GOOD_DAY_ZSCORE_THRESHOLD,
    MAX_RATING,
    MIN_MATCHES_FOR_STDDEV,
    MIN_RATING,
    DefenseFeedingProfile,
    ScoringProfile,
    ScoutingObservation,
    TeamMetrics,
)

SUBMITTED_AT = datetime(2025, 3, 14, tzinfo=timezone.utc)


def make_scoring_profile(**overrides):
    defaults = dict(
        matches_scheduled=10, matches_used=8, average_score=95.5, score_stddev=12.1,
        consistency_rating=61.2, reliability_score=80.0,
        good_day_count=2, average_day_count=5, bad_day_count=1,
    )
    defaults.update(overrides)
    return ScoringProfile(**defaults)


def make_defense_feeding_profile(**overrides):
    defaults = dict(
        defense_score=4.0, defense_observation_count=3, defense_agreement=0.9, defense_insufficient_data=False,
        feeding_score=2.0, feeding_observation_count=2, feeding_agreement=0.5, feeding_insufficient_data=False,
        contributing_sources=["human_scout"],
    )
    defaults.update(overrides)
    return DefenseFeedingProfile(**defaults)


def make_observation(**overrides):
    defaults = dict(
        match_key="2025casj_qm1", event_key="2025casj", team_number=1114, scout_identifier="alice",
        defense_rating=4, feeding_rating=None, notes=None, source="human_scout", submitted_at=SUBMITTED_AT,
    )
    defaults.update(overrides)
    return ScoutingObservation(**defaults)


def make_team_metrics(**overrides):
    defaults = dict(
        team_number=1114, event_key="2025casj", season=2025, computed_at=SUBMITTED_AT,
        scoring=make_scoring_profile(), defense_feeding=make_defense_feeding_profile(),
    )
    defaults.update(overrides)
    return TeamMetrics(**defaults)


# --- rating scale / thresholds are documented in code, not just prose ------

def test_rating_scale_bounds_are_0_to_5():
    assert MIN_RATING == 0
    assert MAX_RATING == 5


def test_every_rating_value_has_a_written_description():
    for scale in (DEFENSE_RATING_DESCRIPTIONS, FEEDING_RATING_DESCRIPTIONS):
        assert set(scale.keys()) == set(range(MIN_RATING, MAX_RATING + 1))
        assert all(isinstance(text, str) and text for text in scale.values())


def test_good_bad_day_thresholds_are_defined_and_opposite_signed():
    assert GOOD_DAY_ZSCORE_THRESHOLD > 0
    assert BAD_DAY_ZSCORE_THRESHOLD < 0
    assert MIN_MATCHES_FOR_STDDEV >= 2


# --- ScoringProfile: valid construction and boundary values -----------------

def test_scoring_profile_valid_construction():
    profile = make_scoring_profile()
    assert profile.matches_used == 8
    assert profile.good_day_count + profile.average_day_count + profile.bad_day_count == profile.matches_used


def test_scoring_profile_zero_matches_all_none():
    profile = make_scoring_profile(
        matches_scheduled=5, matches_used=0, average_score=None, score_stddev=None,
        consistency_rating=None, reliability_score=None,
        good_day_count=None, average_day_count=None, bad_day_count=None,
    )
    assert profile.matches_used == 0
    assert profile.average_score is None


def test_scoring_profile_single_match_allows_average_but_not_variance():
    profile = make_scoring_profile(
        matches_scheduled=3, matches_used=1, average_score=100.0, score_stddev=None,
        consistency_rating=None, reliability_score=None,
        good_day_count=None, average_day_count=None, bad_day_count=None,
    )
    assert profile.average_score == 100.0
    assert profile.score_stddev is None


def test_scoring_profile_matches_used_equal_to_scheduled_is_valid():
    # Defaults' day counts (2+5+1) already sum to 8, so matches_scheduled=8
    # keeps every field consistent while testing the used==scheduled boundary.
    make_scoring_profile(matches_scheduled=8, matches_used=8)


# --- ScoringProfile: invalid combinations rejected --------------------------

def test_scoring_profile_rejects_matches_used_exceeding_scheduled():
    with pytest.raises(ValidationError, match="cannot exceed"):
        make_scoring_profile(matches_scheduled=2, matches_used=5)


def test_scoring_profile_rejects_populated_fields_with_zero_matches():
    with pytest.raises(ValidationError, match="must be None"):
        make_scoring_profile(matches_scheduled=5, matches_used=0)  # defaults leave scores populated


def test_scoring_profile_rejects_stddev_with_one_match():
    with pytest.raises(ValidationError, match="MIN_MATCHES_FOR_STDDEV"):
        make_scoring_profile(matches_scheduled=3, matches_used=1, average_score=50.0)  # defaults leave stddev populated


def test_scoring_profile_rejects_reliability_score_with_one_match():
    with pytest.raises(ValidationError):
        make_scoring_profile(
            matches_scheduled=3, matches_used=1, average_score=50.0, score_stddev=None,
            consistency_rating=None, reliability_score=90.0,
            good_day_count=None, average_day_count=None, bad_day_count=None,
        )


def test_scoring_profile_rejects_day_counts_not_summing_to_matches_used():
    with pytest.raises(ValidationError, match="day counts sum"):
        make_scoring_profile(matches_scheduled=10, matches_used=8, good_day_count=2, average_day_count=2, bad_day_count=2)


def test_scoring_profile_rejects_partial_day_counts():
    with pytest.raises(ValidationError, match="must be set together"):
        make_scoring_profile(good_day_count=2, average_day_count=None, bad_day_count=1)


def test_scoring_profile_rejects_negative_counts():
    with pytest.raises(ValidationError):
        make_scoring_profile(matches_scheduled=-1, matches_used=0)
    with pytest.raises(ValidationError):
        make_scoring_profile(good_day_count=-1)


def test_scoring_profile_rejects_negative_average_score_and_stddev():
    # An FRC score is never negative, and stddev is never negative by
    # definition -- these are hard invariants, not policy judgment calls.
    with pytest.raises(ValidationError):
        make_scoring_profile(average_score=-1.0)
    with pytest.raises(ValidationError):
        make_scoring_profile(score_stddev=-0.1)


def test_scoring_profile_rejects_consistency_and_reliability_outside_0_to_100():
    with pytest.raises(ValidationError):
        make_scoring_profile(consistency_rating=100.1)
    with pytest.raises(ValidationError):
        make_scoring_profile(consistency_rating=-0.1)
    with pytest.raises(ValidationError):
        make_scoring_profile(reliability_score=100.1)
    with pytest.raises(ValidationError):
        make_scoring_profile(reliability_score=-0.1)


# --- DefenseFeedingProfile: valid construction ------------------------------

def test_defense_feeding_profile_valid_construction():
    profile = make_defense_feeding_profile()
    assert profile.defense_score == 4.0
    assert profile.contributing_sources == ["human_scout"]


def test_defense_feeding_profile_insufficient_data_case():
    profile = make_defense_feeding_profile(
        defense_score=None, defense_observation_count=0, defense_agreement=None, defense_insufficient_data=True,
    )
    assert profile.defense_insufficient_data is True
    assert profile.defense_score is None


def test_defense_feeding_profile_defense_and_feeding_are_independent():
    # Defense confidently scored, feeding insufficient -- both must be representable at once.
    profile = make_defense_feeding_profile(
        feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
    )
    assert profile.defense_insufficient_data is False
    assert profile.feeding_insufficient_data is True


def test_defense_feeding_profile_boundary_ratings_accepted():
    make_defense_feeding_profile(defense_score=0.0)
    make_defense_feeding_profile(defense_score=5.0)


def test_defense_feeding_profile_boundary_agreement_accepted():
    make_defense_feeding_profile(defense_agreement=0.0)
    make_defense_feeding_profile(defense_agreement=1.0)


# --- DefenseFeedingProfile: impossible combinations rejected ----------------

def test_defense_feeding_profile_rejects_score_with_insufficient_data_true():
    with pytest.raises(ValidationError, match="if and only if"):
        make_defense_feeding_profile(defense_score=3.0, defense_insufficient_data=True)


def test_defense_feeding_profile_rejects_missing_score_with_insufficient_data_false():
    with pytest.raises(ValidationError, match="if and only if"):
        make_defense_feeding_profile(defense_score=None, defense_insufficient_data=False)


def test_defense_feeding_profile_rejects_zero_observations_without_insufficient_flag():
    # score is non-None here specifically to isolate this rule from the
    # separate "score set iff insufficient_data is False" check -- this
    # payload satisfies that one so the zero-observation-count rule is the
    # one that actually fires.
    with pytest.raises(ValidationError, match="insufficient_data must be True"):
        make_defense_feeding_profile(
            defense_score=3.0, defense_observation_count=0, defense_insufficient_data=False,
        )


def test_defense_feeding_profile_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        make_defense_feeding_profile(defense_score=5.5)
    with pytest.raises(ValidationError):
        make_defense_feeding_profile(defense_score=-1.0)


def test_defense_feeding_profile_rejects_out_of_range_agreement():
    with pytest.raises(ValidationError):
        make_defense_feeding_profile(defense_agreement=1.5)
    with pytest.raises(ValidationError):
        make_defense_feeding_profile(defense_agreement=-0.1)


def test_defense_feeding_profile_rejects_negative_observation_count():
    with pytest.raises(ValidationError):
        make_defense_feeding_profile(defense_observation_count=-1)


def test_defense_feeding_profile_rejects_empty_sources_when_real_data_present():
    with pytest.raises(ValidationError, match="must be non-empty"):
        make_defense_feeding_profile(contributing_sources=[])


def test_defense_feeding_profile_rejects_nonempty_sources_when_fully_insufficient():
    with pytest.raises(ValidationError, match="must be empty"):
        make_defense_feeding_profile(
            defense_score=None, defense_observation_count=0, defense_agreement=None, defense_insufficient_data=True,
            feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
            contributing_sources=["human_scout"],
        )


def test_defense_feeding_profile_allows_empty_sources_when_fully_insufficient():
    make_defense_feeding_profile(
        defense_score=None, defense_observation_count=0, defense_agreement=None, defense_insufficient_data=True,
        feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
        contributing_sources=[],
    )


# --- ScoutingObservation: valid construction ---------------------------------

def test_scouting_observation_valid_with_only_defense_rating():
    obs = make_observation(defense_rating=4, feeding_rating=None)
    assert obs.defense_rating == 4
    assert obs.feeding_rating is None


def test_scouting_observation_valid_with_only_feeding_rating():
    obs = make_observation(defense_rating=None, feeding_rating=2)
    assert obs.feeding_rating == 2


def test_scouting_observation_valid_with_both_ratings():
    obs = make_observation(defense_rating=3, feeding_rating=3)
    assert obs.defense_rating == 3 and obs.feeding_rating == 3


def test_scouting_observation_boundary_ratings_accepted():
    make_observation(defense_rating=0, feeding_rating=None)
    make_observation(defense_rating=5, feeding_rating=None)


def test_scouting_observation_notes_optional():
    obs = make_observation(notes=None)
    assert obs.notes is None
    obs2 = make_observation(notes="Played strong defense on 254 in teleop.")
    assert "254" in obs2.notes


# --- ScoutingObservation: invalid / missing / impossible --------------------

def test_scouting_observation_rejects_neither_rating_present():
    with pytest.raises(ValidationError, match="At least one"):
        make_observation(defense_rating=None, feeding_rating=None)


def test_scouting_observation_rejects_out_of_range_rating():
    with pytest.raises(ValidationError):
        make_observation(defense_rating=6)
    with pytest.raises(ValidationError):
        make_observation(defense_rating=-1)


@pytest.mark.parametrize("field", ["match_key", "event_key", "scout_identifier", "source"])
def test_scouting_observation_rejects_empty_required_strings(field):
    with pytest.raises(ValidationError):
        make_observation(**{field: ""})


def test_scouting_observation_rejects_missing_required_fields():
    with pytest.raises(ValidationError):
        ScoutingObservation(team_number=1114, scout_identifier="alice", defense_rating=3, source="human_scout", submitted_at=SUBMITTED_AT)


def test_scouting_observation_rejects_non_positive_team_number():
    with pytest.raises(ValidationError):
        make_observation(team_number=0)
    with pytest.raises(ValidationError):
        make_observation(team_number=-5)


# --- TeamMetrics: composition and identity ----------------------------------

def test_team_metrics_valid_construction():
    metrics = make_team_metrics()
    assert metrics.team_number == 1114
    assert isinstance(metrics.scoring, ScoringProfile)
    assert isinstance(metrics.defense_feeding, DefenseFeedingProfile)


def test_team_metrics_rejects_non_positive_team_number():
    with pytest.raises(ValidationError):
        make_team_metrics(team_number=0)


def test_team_metrics_rejects_empty_event_key():
    with pytest.raises(ValidationError):
        make_team_metrics(event_key="")


def test_team_metrics_allows_implausible_season_at_model_level():
    # Deliberate: season plausibility is a quality-check concern (matching
    # StagingEvent/StagingMatch precedent), not a hard pydantic rejection here.
    make_team_metrics(season=1776)


def test_team_metrics_supports_fully_insufficient_data_case():
    # A team with matches but zero scouting observations at all -- must
    # produce a complete, valid object, never a crash.
    metrics = make_team_metrics(
        defense_feeding=make_defense_feeding_profile(
            defense_score=None, defense_observation_count=0, defense_agreement=None, defense_insufficient_data=True,
            feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
            contributing_sources=[],
        ),
    )
    assert metrics.defense_feeding.defense_insufficient_data is True
    assert metrics.defense_feeding.feeding_insufficient_data is True


def test_team_metrics_supports_fully_unplayed_event_case():
    # A team scheduled but the event hasn't started -- zero matches, zero
    # observations, still a complete, valid object.
    metrics = make_team_metrics(
        scoring=make_scoring_profile(
            matches_scheduled=6, matches_used=0, average_score=None, score_stddev=None,
            consistency_rating=None, reliability_score=None,
            good_day_count=None, average_day_count=None, bad_day_count=None,
        ),
        defense_feeding=make_defense_feeding_profile(
            defense_score=None, defense_observation_count=0, defense_agreement=None, defense_insufficient_data=True,
            feeding_score=None, feeding_observation_count=0, feeding_agreement=None, feeding_insufficient_data=True,
            contributing_sources=[],
        ),
    )
    assert metrics.scoring.matches_used == 0
    assert metrics.defense_feeding.defense_insufficient_data is True


def test_team_metrics_json_serialization_is_clean_and_nested():
    metrics = make_team_metrics()
    dumped = metrics.model_dump(mode="json")
    assert set(dumped.keys()) == {"team_number", "event_key", "season", "computed_at", "scoring", "defense_feeding"}
    assert "matches_used" in dumped["scoring"]
    assert "defense_score" in dumped["defense_feeding"]


def test_team_metrics_round_trips_through_json():
    metrics = make_team_metrics()
    restored = TeamMetrics.model_validate_json(metrics.model_dump_json())
    assert restored == metrics


# --- Every field the Definition of Done needs actually exists on TeamMetrics -

def test_team_metrics_has_every_definition_of_done_field():
    field_names = set(TeamMetrics.model_fields.keys())
    assert {"team_number", "event_key", "season", "scoring", "defense_feeding"}.issubset(field_names)

    scoring_fields = set(ScoringProfile.model_fields.keys())
    assert {"average_score", "score_stddev", "consistency_rating", "reliability_score"}.issubset(scoring_fields)
    assert {"good_day_count", "average_day_count", "bad_day_count"}.issubset(scoring_fields)

    defense_feeding_fields = set(DefenseFeedingProfile.model_fields.keys())
    assert {"defense_score", "feeding_score"}.issubset(defense_feeding_fields)


def test_defense_feeding_profile_has_no_path_from_scores_to_ratings():
    # Architectural guard: DefenseFeedingProfile's own fields must never
    # include a ScoringProfile or a raw scoring field -- defense/feeding are
    # directly measured, never inferred from point output. Checked against
    # the model's actual field set, not the docstring prose (which is
    # expected to mention "scores" when explaining this exact constraint).
    field_names = set(DefenseFeedingProfile.model_fields.keys())
    allowed_score_fields = {"defense_score", "feeding_score"}
    assert not any("score" in name for name in field_names - allowed_score_fields)

    field_annotations = {field.annotation for field in DefenseFeedingProfile.model_fields.values()}
    assert ScoringProfile not in field_annotations
