"""Pure statistical functions over a team's match score history.

Phase 3 Milestone 3. No database, no I/O -- every function here is a pure
transformation of already-extracted data. Milestone 4's match-history layer
(data.metrics.history.get_team_match_history) turns canonical matches/
match_teams rows into the plain inputs these functions take (a team's own
score per match it actually played, with unplayed matches already excluded);
nothing here queries anything itself.

Every function returns None, never 0 or an exception, when its result is
statistically undefined for the given input. This must stay consistent with
data.metrics.schemas.ScoringProfile's model_validator, which already encodes
exactly this behavior as a set of invariants on the object these functions'
outputs will eventually populate (Milestone 10):
  * 0 matches used: every value below is None.
  * 1 match used: average_score is defined; nothing that needs variance is.
  * >= MIN_MATCHES_FOR_STDDEV (2) matches used: everything is defined.
tests/test_statistics.py exercises this consistency directly, not just each
function in isolation, so a future change to one side can't silently drift
from the other.
"""

from __future__ import annotations

import statistics as _statistics

from data.metrics.schemas import (
    BAD_DAY_ZSCORE_THRESHOLD,
    GOOD_DAY_ZSCORE_THRESHOLD,
    MIN_MATCHES_FOR_STDDEV,
)


def average_score(scores: list[int]) -> float | None:
    """Mean of a team's match scores. None for an empty history.

    Defined for a single match (the average of one value is itself) --
    unlike every other function in this module, this does not require
    MIN_MATCHES_FOR_STDDEV matches, matching ScoringProfile's invariant that
    average_score alone survives a 1-match history.
    """
    if not scores:
        return None
    return _statistics.fmean(scores)


def score_stddev(scores: list[int]) -> float | None:
    """Population standard deviation of a team's match scores.

    None below MIN_MATCHES_FOR_STDDEV matches -- variance is undefined for a
    single sample, and there is no sample at all below that.

    Population (not sample) stddev, deliberately: these matches are not a
    sample used to infer some larger population's variance -- they are
    literally every match this team played at this event, the complete
    population being described. Dividing by n rather than n-1 (Bessel's
    correction) is the semantically correct choice for a descriptive
    statistic, not an inferential one.
    """
    if len(scores) < MIN_MATCHES_FOR_STDDEV:
        return None
    return _statistics.pstdev(scores)


def consistency_rating(scores: list[int]) -> float | None:
    """How tightly clustered a team's scoring output is, scaled 0-100.

    100 = perfectly consistent (stddev is 0, including the "always scores
    exactly 0" case); lower values mean output varies more relative to its
    own mean. None below MIN_MATCHES_FOR_STDDEV matches, matching
    score_stddev -- consistency is meaningless without a defined variance.

    Formula: 100 * (1 - coefficient_of_variation), clamped to [0, 100]. The
    coefficient of variation (stddev / mean) is undefined when mean is 0, but
    that can only happen here if every score is 0 (an FRC score is never
    negative, so a zero mean forces every value to be zero) -- handled
    explicitly as the maximum (100: perfectly consistent, even though the
    level is zero), not a division by zero.

    Clamped deliberately, unlike reliability_score: a genuinely very
    inconsistent team can legitimately produce a coefficient of variation
    above 1.0 (e.g. scores of 0 and 300), which this function's own
    documented contract (a 0-100 scale) has to absorb, not reject -- this is
    expected math, not a caller error the way an out-of-range
    reliability_score input would be.

    The mean == 0 check above is deliberately "are all scores 0", not merely
    "is the mean 0": those are only equivalent because an FRC score is never
    negative, an assumption enforced by convention in this codebase, not by
    any type or Field constraint on the data this function receives. If that
    assumption were ever violated (e.g. a negative score from a data bug),
    mixed-sign scores could average to a mean of 0 without every score being
    0 -- reporting "perfectly consistent" (100.0) for that would be exactly
    the kind of confident, wrong answer this project's accuracy principle
    forbids, and one a downstream 0-100-range check could never catch, since
    100.0 is a valid value on that scale. None is returned for that case
    instead -- consistency is genuinely undefined for input outside this
    function's assumed domain, not silently "perfect".
    """
    if len(scores) < MIN_MATCHES_FOR_STDDEV:
        return None
    mean = _statistics.fmean(scores)
    if mean == 0:
        if any(score != 0 for score in scores):
            return None
        return 100.0
    stddev = _statistics.pstdev(scores)
    coefficient_of_variation = stddev / mean
    return max(0.0, min(100.0, 100.0 * (1 - coefficient_of_variation)))


def classify_match_days(scores: list[int]) -> dict[str, int] | None:
    """Classify each match as a good/average/bad day relative to the team's own mean.

    None below MIN_MATCHES_FOR_STDDEV matches -- the z-score thresholds below
    need a defined stddev, matching ScoringProfile's invariant that the three
    day counts are always None together below that threshold.

    A match is "good" if its score exceeds
    mean + GOOD_DAY_ZSCORE_THRESHOLD * stddev, "bad" if it falls below
    mean + BAD_DAY_ZSCORE_THRESHOLD * stddev (BAD_DAY_ZSCORE_THRESHOLD is
    negative), otherwise "average". A team with stddev == 0 (every match
    identical) has every match classified "average" -- it is, by definition,
    neither better nor worse than its own mean.

    Returns counts (good/average/bad, always summing to len(scores)), not a
    per-match list: ScoringProfile stores good_day_count/average_day_count/
    bad_day_count directly, and nothing in Phase 3's current scope needs a
    finer-grained, per-match breakdown. A per-match classification list is a
    reasonable future extension if that need arises later -- not built now.
    """
    if len(scores) < MIN_MATCHES_FOR_STDDEV:
        return None
    mean = _statistics.fmean(scores)
    stddev = _statistics.pstdev(scores)
    good_cutoff = mean + GOOD_DAY_ZSCORE_THRESHOLD * stddev
    bad_cutoff = mean + BAD_DAY_ZSCORE_THRESHOLD * stddev

    good = average = bad = 0
    for score in scores:
        if score > good_cutoff:
            good += 1
        elif score < bad_cutoff:
            bad += 1
        else:
            average += 1
    return {"good": good, "average": average, "bad": bad}


def reliability_score(matches_used: int, matches_scheduled: int) -> float | None:
    """Interim reliability formula: 100 * (matches_used / matches_scheduled).

    Target definition (not implemented -- see data.metrics.schemas' module
    docstring for the full gap analysis): reliability should measure whether
    a robot shows up and finishes a match without a catastrophic failure,
    ideally from per-team no-show/disqualification status. That data does not
    exist anywhere in the canonical schema today (data.clients.schemas.
    MatchAllianceResult models only score and team_keys), so this is
    deliberately the documented interim proxy, not a final answer: it
    captures "did we get a usable recorded result for this team at all",
    which is weaker than "did the robot itself fail", but is honestly
    computable with data that exists today rather than guessing at fields
    that may not exist.

    None when matches_used is below MIN_MATCHES_FOR_STDDEV, matching
    ScoringProfile's invariant, which groups reliability_score with the
    variance fields even though this formula does not use variance: a
    reliability judgment from a single recorded match is exactly as
    statistically shaky as a variance computed from one point. None when
    matches_scheduled is 0 -- nothing was scheduled, so the ratio itself is
    undefined, not merely low-confidence.

    Deliberately not clamped: matches_used should never exceed
    matches_scheduled for valid input (ScoringProfile enforces this as its
    own invariant). Clamping here would silently absorb that caller error
    instead of letting it surface downstream, unlike consistency_rating's
    clamp, which absorbs a legitimate mathematical outcome rather than a bug.
    """
    if matches_used < MIN_MATCHES_FOR_STDDEV or matches_scheduled == 0:
        return None
    return 100.0 * (matches_used / matches_scheduled)
