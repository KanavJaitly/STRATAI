"""Phase 3 Milestone 8: defense/feeding aggregation logic.

Per docs/P3Milestones.md's exact test list: zero observations; one
observation (per the documented threshold); multiple agreeing observations;
multiple disagreeing observations with an outlier. Also verifies the
cross-model consistency Milestone 3's own test suite established as a
pattern: aggregate_defense_feeding's output must always construct a valid
DefenseFeedingProfile without tripping Milestone 1's model_validator.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.metrics.aggregation import (
    MIN_OBSERVATIONS_FOR_SCORE,
    aggregate_defense_feeding,
)
from data.metrics.schemas import DefenseFeedingProfile, ScoutingObservation

_SUBMITTED_AT = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _obs(source: str, *, defense: int | None = None, feeding: int | None = None) -> ScoutingObservation:
    return ScoutingObservation(
        match_key="2026casj_qm1", event_key="2026casj", team_number=1114,
        scout_identifier=source, defense_rating=defense, feeding_rating=feeding,
        source=source, submitted_at=_SUBMITTED_AT,
    )


# --- zero observations -------------------------------------------------

def test_zero_observations_is_entirely_insufficient():
    profile = aggregate_defense_feeding([])
    assert isinstance(profile, DefenseFeedingProfile)
    assert profile.defense_score is None
    assert profile.defense_observation_count == 0
    assert profile.defense_agreement is None
    assert profile.defense_insufficient_data is True
    assert profile.feeding_score is None
    assert profile.feeding_observation_count == 0
    assert profile.feeding_agreement is None
    assert profile.feeding_insufficient_data is True
    assert profile.contributing_sources == []


# --- one observation: below the documented threshold ------------------

def test_one_observation_is_insufficient_per_documented_threshold():
    assert MIN_OBSERVATIONS_FOR_SCORE == 2  # pins the documented policy itself
    profile = aggregate_defense_feeding([_obs("alice", defense=3)])
    assert profile.defense_insufficient_data is True
    assert profile.defense_score is None
    assert profile.defense_agreement is None
    assert profile.defense_observation_count == 1  # the count is still honest
    assert profile.contributing_sources == []


def test_one_observation_never_reports_fabricated_perfect_agreement():
    # A single point trivially has zero variance -- agreement must not be
    # reported as 1.0 ("perfect") from it; it must not be reported at all.
    profile = aggregate_defense_feeding([_obs("alice", feeding=5)])
    assert profile.feeding_agreement is None


# --- multiple agreeing observations -------------------------------------

def test_multiple_agreeing_observations_score_high_with_full_agreement():
    profile = aggregate_defense_feeding([
        _obs("a", defense=3), _obs("b", defense=3), _obs("c", defense=3),
    ])
    assert profile.defense_insufficient_data is False
    assert profile.defense_score == 3.0
    assert profile.defense_agreement == 1.0
    assert profile.defense_observation_count == 3
    assert profile.contributing_sources == ["a", "b", "c"]


# --- multiple disagreeing observations with an outlier ------------------

def test_disagreeing_observations_with_an_outlier_hand_computed():
    # Ratings 0, 3, 3, 3 -- median of the sorted list is (3+3)/2 = 3.0, still
    # reflecting the 3-scout consensus despite the outlier. mean=2.25,
    # population stddev ~= 1.299, agreement = 1 - 1.299/2.5 ~= 0.4804.
    profile = aggregate_defense_feeding([
        _obs("a", defense=0), _obs("b", defense=3), _obs("c", defense=3), _obs("d", defense=3),
    ])
    assert profile.defense_score == 3.0
    assert profile.defense_agreement == pytest.approx(0.4804, abs=1e-3)
    assert profile.defense_agreement < 1.0


def test_maximal_disagreement_at_the_scale_extremes():
    # 0 and 5 are the widest possible split -- the mathematical minimum of
    # the agreement formula, exactly 0.0, not a small positive residue.
    profile = aggregate_defense_feeding([_obs("a", defense=0), _obs("b", defense=5)])
    assert profile.defense_score == 2.5  # median of an even count: the midpoint
    assert profile.defense_agreement == 0.0


# --- median specifically, not mean --------------------------------------

def test_uses_median_not_mean_so_an_outlier_does_not_drag_the_score():
    # Mean of [0,3,3,3,3] is 2.4; median is 3 -- the aggregation must report
    # the scout consensus (3), not the arithmetic average.
    profile = aggregate_defense_feeding([
        _obs("a", defense=0), _obs("b", defense=3), _obs("c", defense=3),
        _obs("d", defense=3), _obs("e", defense=3),
    ])
    assert profile.defense_score == 3.0


def test_even_count_median_is_the_midpoint():
    profile = aggregate_defense_feeding([_obs("a", defense=3), _obs("b", defense=4)])
    assert profile.defense_score == 3.5


# --- boundary ratings are real values, not sentinels ---------------------

def test_boundary_rating_zero_is_a_real_score_not_falsy():
    profile = aggregate_defense_feeding([_obs("a", defense=0), _obs("b", defense=0)])
    assert profile.defense_insufficient_data is False
    assert profile.defense_score == 0.0
    assert profile.defense_agreement == 1.0


def test_boundary_rating_five_aggregates_normally():
    profile = aggregate_defense_feeding([_obs("a", feeding=5), _obs("b", feeding=5)])
    assert profile.feeding_score == 5.0
    assert profile.feeding_agreement == 1.0


# --- defense and feeding aggregate independently -------------------------

def test_defense_and_feeding_aggregate_independently():
    profile = aggregate_defense_feeding([
        _obs("a", defense=3, feeding=4),
        _obs("b", defense=4),
        _obs("c", feeding=5),
    ])
    assert profile.defense_observation_count == 2
    assert profile.feeding_observation_count == 2
    assert profile.defense_insufficient_data is False
    assert profile.feeding_insufficient_data is False
    assert profile.contributing_sources == ["a", "b", "c"]


def test_a_source_that_only_contributed_to_the_insufficient_metric_is_excluded():
    # 'c' submitted only a feeding rating, and feeding stays below threshold
    # (count 1) -- 'c' must not appear in contributing_sources even though it
    # submitted a real observation, since that observation never became part
    # of a reported score.
    profile = aggregate_defense_feeding([
        _obs("a", defense=3), _obs("b", defense=3), _obs("c", feeding=5),
    ])
    assert profile.defense_insufficient_data is False
    assert profile.feeding_insufficient_data is True
    assert profile.contributing_sources == ["a", "b"]


def test_only_defense_observations_leaves_feeding_entirely_insufficient():
    profile = aggregate_defense_feeding([_obs("a", defense=3), _obs("b", defense=4)])
    assert profile.feeding_insufficient_data is True
    assert profile.feeding_score is None
    assert profile.feeding_observation_count == 0


# --- determinism ---------------------------------------------------------

def test_aggregation_is_deterministic():
    observations = [_obs("a", defense=3, feeding=2), _obs("b", defense=4, feeding=3)]
    first = aggregate_defense_feeding(observations)
    second = aggregate_defense_feeding(observations)
    assert first == second


def test_aggregation_does_not_mutate_input_list():
    observations = [_obs("a", defense=3), _obs("b", defense=4)]
    snapshot = list(observations)
    aggregate_defense_feeding(observations)
    assert observations == snapshot


# --- multi-source coexistence (Milestone 9) --------------------------------
#
# Milestone 9 found no public, unauthenticated ScoutRadioz API to build a
# real connector against (every data-bearing route, including its own CSV
# export, requires an authenticated per-team login -- see RUNNING_NOTES.md).
# What Milestone 9's own success criteria actually require -- "ScoutRadioz
# and human-form observations coexist... aggregate together correctly" --
# is independent of whether a live connector exists: aggregate_defense_feeding
# only ever sees already-built ScoutingObservation rows, regardless of their
# origin. These tests construct a second source by hand to prove the pooling
# behavior a real connector would rely on already works, with zero changes
# to this module.

def _obs_from(source: str, *, scout_identifier: str, defense: int | None = None, feeding: int | None = None) -> ScoutingObservation:
    return ScoutingObservation(
        match_key="2026casj_qm1", event_key="2026casj", team_number=1114,
        scout_identifier=scout_identifier, defense_rating=defense, feeding_rating=feeding,
        source=source, submitted_at=_SUBMITTED_AT,
    )


def test_observations_from_two_different_sources_pool_into_one_score():
    observations = [
        _obs_from("human_scout", scout_identifier="alice", defense=3),
        _obs_from("scoutradioz", scout_identifier="scoutbot", defense=5),
    ]
    profile = aggregate_defense_feeding(observations)

    assert profile.defense_observation_count == 2
    assert profile.defense_score == 4.0  # median(3, 5), pooled across sources
    assert not profile.defense_insufficient_data


def test_contributing_sources_names_every_distinct_source_that_produced_a_score():
    observations = [
        _obs_from("human_scout", scout_identifier="alice", defense=3),
        _obs_from("scoutradioz", scout_identifier="scoutbot", defense=4),
    ]
    profile = aggregate_defense_feeding(observations)

    assert profile.contributing_sources == ["human_scout", "scoutradioz"]


def test_identical_scout_identifier_from_two_sources_are_independent_observations():
    # The DB migration's own documented edge case: "the same name arriving
    # from a different source" must count as two independent opinions, not
    # collide or get deduped -- scout_identifier alone is not the identity.
    observations = [
        _obs_from("human_scout", scout_identifier="scoutbot", defense=3),
        _obs_from("scoutradioz", scout_identifier="scoutbot", defense=5),
    ]
    profile = aggregate_defense_feeding(observations)

    assert profile.defense_observation_count == 2
    assert profile.contributing_sources == ["human_scout", "scoutradioz"]


def test_a_source_with_only_an_insufficient_metric_is_excluded_even_alongside_another_source():
    # Mirrors the existing single-source contributing_sources test, but across
    # two distinct sources: scoutradioz's lone feeding rating is below
    # MIN_OBSERVATIONS_FOR_SCORE and must not be named as having contributed.
    observations = [
        _obs_from("human_scout", scout_identifier="alice", defense=3),
        _obs_from("human_scout", scout_identifier="bob", defense=3),
        _obs_from("scoutradioz", scout_identifier="scoutbot", feeding=4),
    ]
    profile = aggregate_defense_feeding(observations)

    assert not profile.defense_insufficient_data
    assert profile.feeding_insufficient_data
    assert profile.contributing_sources == ["human_scout"]


# --- cross-consistency with DefenseFeedingProfile's own invariants --------

@pytest.mark.parametrize("observations", [
    [],
    [_obs("a", defense=3)],
    [_obs("a", defense=3), _obs("b", feeding=4)],
    [_obs("a", defense=0), _obs("b", defense=5), _obs("c", feeding=2), _obs("d", feeding=3)],
    [_obs(f"scout{i}", defense=i % 6, feeding=(i + 1) % 6) for i in range(10)],
])
def test_output_never_trips_defense_feeding_profile_validator(observations):
    # aggregate_defense_feeding already returns a constructed DefenseFeedingProfile,
    # so the real assertion is simply that construction succeeded (no raise) --
    # this sweeps a range of shapes to catch a regression that only manifests
    # for some particular count/mix, not just the hand-picked cases above.
    aggregate_defense_feeding(observations)
