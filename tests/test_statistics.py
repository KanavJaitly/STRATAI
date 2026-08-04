from __future__ import annotations

import pytest

from data.metrics.schemas import MIN_MATCHES_FOR_STDDEV, ScoringProfile
from data.metrics.statistics import (
    average_score,
    classify_match_days,
    consistency_rating,
    reliability_score,
    score_stddev,
)


# --- average_score -----------------------------------------------------

def test_average_score_empty_input_is_none():
    assert average_score([]) is None


def test_average_score_single_match_is_defined():
    assert average_score([100]) == 100.0


def test_average_score_normal_case_hand_computed():
    # (80 + 100 + 120) / 3 = 100
    assert average_score([80, 100, 120]) == pytest.approx(100.0)


def test_average_score_uniform_input():
    assert average_score([50, 50, 50, 50]) == pytest.approx(50.0)


def test_average_score_with_large_outlier():
    # (10 + 10 + 10 + 1000) / 4 = 257.5
    assert average_score([10, 10, 10, 1000]) == pytest.approx(257.5)


def test_average_score_all_zeros():
    assert average_score([0, 0, 0]) == 0.0


# --- score_stddev --------------------------------------------------------

def test_score_stddev_empty_input_is_none():
    assert score_stddev([]) is None


def test_score_stddev_single_match_is_none():
    assert score_stddev([100]) is None


def test_score_stddev_normal_case_hand_computed():
    # mean=100, deviations -50/+50, squares 2500 each, mean 2500, sqrt=50
    assert score_stddev([50, 150]) == pytest.approx(50.0)


def test_score_stddev_uniform_input_is_zero():
    assert score_stddev([100, 100, 100]) == 0.0


def test_score_stddev_with_large_outlier_is_large():
    assert score_stddev([10, 10, 10, 1000]) > 400


def test_score_stddev_is_population_not_sample():
    # Population stddev of [0, 10]: mean=5, deviations +-5, sqrt(25)=5.
    # Sample stddev (n-1) would give sqrt(50) ~= 7.07 -- confirms which one this is.
    assert score_stddev([0, 10]) == pytest.approx(5.0)


# --- consistency_rating ----------------------------------------------------

def test_consistency_rating_empty_input_is_none():
    assert consistency_rating([]) is None


def test_consistency_rating_single_match_is_none():
    assert consistency_rating([100]) is None


def test_consistency_rating_uniform_input_is_perfect():
    assert consistency_rating([100, 100, 100]) == 100.0


def test_consistency_rating_all_zeros_is_perfect_not_a_crash():
    # mean=0 would divide-by-zero in a naive coefficient-of-variation formula.
    assert consistency_rating([0, 0, 0]) == 100.0


def test_consistency_rating_normal_case_hand_computed():
    # mean=100, stddev=50 (from test_score_stddev_normal_case), CV=0.5
    # consistency = 100 * (1 - 0.5) = 50
    assert consistency_rating([50, 150]) == pytest.approx(50.0)


def test_consistency_rating_with_large_outlier_is_low():
    assert consistency_rating([10, 10, 10, 1000]) < 20


def test_consistency_rating_extreme_variance_clamps_to_zero_not_negative():
    # mean=150, stddev=150, CV=1.0 -> exactly 0, and going further negative
    # (e.g. [0, 0, 600], CV > 1) must still clamp to 0, not go below.
    assert consistency_rating([0, 300]) == 0.0
    assert consistency_rating([0, 0, 600]) == 0.0


def test_consistency_rating_mixed_sign_zero_mean_is_none_not_fabricated_perfect():
    # Negative scores should never reach this function (an FRC score is never
    # negative), but that is a convention, not an enforced constraint on the
    # input list. If it were ever violated, a mean of 0 from mixed-sign
    # values must not be reported as "perfectly consistent" -- that would be
    # a confident, wrong answer sitting inside the valid 0-100 range, where
    # no downstream check could ever catch it.
    assert consistency_rating([-100, 100]) is None
    assert consistency_rating([-50, 25, 25]) is None


def test_consistency_rating_is_always_within_0_to_100():
    for scores in ([0, 300], [0, 0, 600], [1, 1000], [5, 5, 5, 5000]):
        rating = consistency_rating(scores)
        assert rating is not None
        assert 0.0 <= rating <= 100.0


# --- classify_match_days ----------------------------------------------------

def test_classify_match_days_empty_input_is_none():
    assert classify_match_days([]) is None


def test_classify_match_days_single_match_is_none():
    assert classify_match_days([100]) is None


def test_classify_match_days_uniform_input_is_all_average():
    # stddev is 0, so no match can be strictly above/below its own mean.
    result = classify_match_days([100, 100, 100, 100])
    assert result == {"good": 0, "average": 4, "bad": 0}


def test_classify_match_days_normal_case_hand_computed():
    # mean=100, stddev~31.62 (see test docstring below for the arithmetic).
    # good_cutoff ~= 131.62, bad_cutoff ~= 68.38.
    # 50 < 68.38 -> bad; 100,100,100 -> average; 150 > 131.62 -> good.
    result = classify_match_days([50, 100, 100, 100, 150])
    assert result == {"good": 1, "average": 3, "bad": 1}


def test_classify_match_days_counts_always_sum_to_input_length():
    for scores in ([10, 20], [1, 2, 3, 4, 5], [0, 0, 0, 500], [100] * 10):
        result = classify_match_days(scores)
        assert sum(result.values()) == len(scores)


def test_classify_match_days_large_outlier_is_classified_good():
    result = classify_match_days([10, 10, 10, 1000])
    assert result["good"] == 1
    assert result["bad"] == 0


# --- reliability_score -------------------------------------------------------

def test_reliability_score_zero_scheduled_is_none():
    assert reliability_score(matches_used=0, matches_scheduled=0) is None


def test_reliability_score_below_min_matches_used_is_none():
    # matches_used=1 is below MIN_MATCHES_FOR_STDDEV (2), even though
    # matches_scheduled is well-formed -- must match ScoringProfile exactly.
    assert reliability_score(matches_used=1, matches_scheduled=5) is None
    assert reliability_score(matches_used=0, matches_scheduled=5) is None


def test_reliability_score_perfect_attendance_hand_computed():
    assert reliability_score(matches_used=10, matches_scheduled=10) == 100.0


def test_reliability_score_partial_attendance_hand_computed():
    assert reliability_score(matches_used=6, matches_scheduled=10) == pytest.approx(60.0)


def test_reliability_score_low_dq_low_variance_team_scores_high():
    # A team that attended nearly every scheduled match and whose scores were
    # tightly clustered scores well on BOTH metrics -- reliability from
    # availability, consistency from variance, independently confirmed here.
    reliable_team_scores = [98, 100, 102, 99, 101]
    assert reliability_score(matches_used=10, matches_scheduled=10) == 100.0
    assert consistency_rating(reliable_team_scores) > 90.0


def test_reliability_score_frequent_no_show_team_scores_low():
    # A team that only produced usable results for 2 of 10 scheduled matches
    # -- the interim proxy's honest read of "frequent no-show", given the
    # documented absence of per-match DQ/no-show data.
    assert reliability_score(matches_used=2, matches_scheduled=10) == 20.0
    assert reliability_score(matches_used=2, matches_scheduled=10) < reliability_score(matches_used=10, matches_scheduled=10)


def test_reliability_score_never_clamped_above_100_on_malformed_input():
    # matches_used > matches_scheduled should never happen for valid input
    # (ScoringProfile enforces this upstream); this function deliberately does
    # NOT hide that with a clamp, so the raw, out-of-range result is what a
    # caller bug actually produces -- verified here so a future "helpful"
    # clamp doesn't get added silently.
    assert reliability_score(matches_used=10, matches_scheduled=5) == 200.0


# --- Cross-consistency with ScoringProfile's own invariants -----------------
#
# The real point of this module: its outputs must be directly usable to
# construct a ScoringProfile without ever tripping the model's validator,
# across every documented matches_used bucket. This is the test that would
# catch the two layers drifting apart from each other.

def _build_profile_from(scores: list[int], matches_scheduled: int) -> ScoringProfile:
    matches_used = len(scores)
    day_counts = classify_match_days(scores)
    return ScoringProfile(
        matches_scheduled=matches_scheduled,
        matches_used=matches_used,
        average_score=average_score(scores),
        score_stddev=score_stddev(scores),
        consistency_rating=consistency_rating(scores),
        reliability_score=reliability_score(matches_used, matches_scheduled),
        good_day_count=day_counts["good"] if day_counts else None,
        average_day_count=day_counts["average"] if day_counts else None,
        bad_day_count=day_counts["bad"] if day_counts else None,
    )


def test_statistics_outputs_construct_a_valid_scoring_profile_zero_matches():
    profile = _build_profile_from([], matches_scheduled=5)
    assert profile.matches_used == 0
    assert profile.average_score is None
    assert profile.reliability_score is None


def test_statistics_outputs_construct_a_valid_scoring_profile_one_match():
    profile = _build_profile_from([120], matches_scheduled=5)
    assert profile.matches_used == 1
    assert profile.average_score == 120.0
    assert profile.score_stddev is None
    assert profile.reliability_score is None


def test_statistics_outputs_construct_a_valid_scoring_profile_many_matches():
    profile = _build_profile_from([80, 100, 120, 140, 60], matches_scheduled=6)
    assert profile.matches_used == 5
    assert profile.average_score is not None
    assert profile.score_stddev is not None
    assert profile.consistency_rating is not None
    assert profile.reliability_score is not None
    assert profile.good_day_count + profile.average_day_count + profile.bad_day_count == 5


@pytest.mark.parametrize("scores", [[], [50], [50, 50], [10, 20, 30], list(range(1, 20))])
def test_statistics_outputs_never_trip_scoring_profile_validator(scores):
    # The general-case sweep behind the three targeted tests above: any
    # length of score history, fed straight through, must always construct.
    _build_profile_from(scores, matches_scheduled=max(len(scores), 1))


def test_min_matches_for_stddev_is_the_shared_threshold():
    # Documents the coupling directly: every function's threshold check is
    # literally MIN_MATCHES_FOR_STDDEV imported from data.metrics.schemas, not
    # a locally redefined "2".
    assert score_stddev([0] * (MIN_MATCHES_FOR_STDDEV - 1)) is None
    assert score_stddev([0] * MIN_MATCHES_FOR_STDDEV) is not None
