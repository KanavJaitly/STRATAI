"""Pure aggregation of scouting observations into a defense/feeding profile.

Phase 3 Milestone 8. No database, no I/O -- a pure transformation of an
already-fetched list of ScoutingObservation rows for one team at one event,
mirroring exactly how Milestone 3's statistics functions relate to Milestone
4's match-history layer: fetching the right list[ScoutingObservation] for a
team+event is a future milestone's job (mirroring get_team_match_history),
not this module's. This function trusts the caller has already scoped the
list correctly (one team, one event) -- it does not re-validate that, the
same way average_score()/score_stddev() trust their list[int] is already the
right team's own scores.

Design decisions this milestone is explicitly responsible for (per
docs/P3Milestones.md), each logged in RUNNING_NOTES.md's design-decision log
as required:

  * Minimum-observation threshold: MIN_OBSERVATIONS_FOR_SCORE = 2, not 1.
    DefenseFeedingProfile's own model_validator only forces
    insufficient_data=True at exactly zero observations -- deciding whether
    one observation is "enough" is explicitly left to this milestone's
    policy, not baked into the model. One observation cannot establish
    *agreement* (agreement is a statement about consensus among multiple
    scouts), and reporting a formula's trivial "zero variance" for a single
    point as agreement=1.0 would be exactly the class of fabricated
    confidence Milestone 3's consistency_rating bug hunt already found and
    rejected once (a single data point looking artificially "perfectly
    consistent"). Mirrors MIN_MATCHES_FOR_STDDEV=2's identical reasoning.

  * Median, not mean, for the reported score. Ratings are discrete, ordinal
    tiers (see DEFENSE_RATING_DESCRIPTIONS/FEEDING_RATING_DESCRIPTIONS), not
    a continuous measurement, and a scouting lead summarizing "what did
    everyone say" naturally reaches for "most scouts said X", which is what
    the median reports, not "the arithmetic average of everyone's tier
    number". Median is also robust to exactly the failure this data is prone
    to: one scout misidentifying a team or fat-fingering a rating should not
    drag a 3-3-3-3 consensus down to 2.4.

  * Agreement uses population standard deviation (statistics.pstdev), for
    the identical reason Milestone 3 chose population over sample stddev:
    the observations in hand are the complete population of opinions
    collected, not a sample of some larger population to infer from.

  * contributing_sources is the union of sources that contributed to
    *whichever* of defense/feeding actually produced a real (non-
    insufficient) score -- not every source that submitted any observation
    at all. A source whose only rating was for the metric that ended up
    insufficient (e.g. a single feeding rating, below threshold) did not
    "produce" a score and should not be named as having done so; the model's
    own invariant (contributing_sources empty iff both metrics are
    insufficient) is what this has to satisfy exactly.

Known, deliberately unaddressed scope boundary (found during this milestone's
own bug hunt, not fixed here): observations are not deduplicated or
down-weighted by scout_identifier. A team plays several matches at one
event, and the same scout legitimately rates it more than once across them --
each such observation is a genuine, independent data point about that
match's performance, so counting all of them is correct. What this does NOT
address is one scout dominating the sample relative to how many *distinct*
scouts were involved (ten observations from one repeat scout currently
aggregate identically to ten observations from ten different scouts, even
though the latter is a stronger consensus signal). No milestone has assigned
weighting by distinct-scout-count yet, and inventing one now would be
guessing at a policy nobody has asked for; a future milestone extending this
one should decide it deliberately, the same way this milestone decided its
own threshold and median-vs-mean questions.
"""

from __future__ import annotations

import statistics as _statistics

from data.metrics.schemas import MAX_RATING, MIN_RATING, DefenseFeedingProfile, ScoutingObservation

# Below this many observations, a score is not reported at all -- see the
# module docstring for why 2, not 1.
MIN_OBSERVATIONS_FOR_SCORE = 2

# The maximum possible spread between any two ratings on the scale; the
# denominator in the agreement formula below.
_RATING_SPAN = MAX_RATING - MIN_RATING


def _aggregate_one_metric(ratings_by_source: list[tuple[str, int]]) -> tuple[float | None, int, float | None, bool, set[str]]:
    """Aggregate one metric's (source, rating) pairs into (score, count, agreement, insufficient_data, sources).

    Population standard deviation of values confined to [MIN_RATING,
    MAX_RATING] can never exceed _RATING_SPAN / 2 (the bound is achieved only
    when observations split entirely between the two extremes), so
    `agreement` is mathematically guaranteed to land in [0.0, 1.0] here
    without needing to clamp against a genuinely reachable case. The
    `max(0.0, ...)` below is retained anyway as cheap insurance against a
    future implementation mistake (e.g. sample stddev instead of population,
    which *can* exceed this bound for small n) -- if it were ever to fire, it
    would be signaling an internal bug in this function, not papering over
    out-of-domain input the way Milestone 3's consistency_rating bug did:
    0.0 is agreement's own honest minimum, not a fabricated-looking value.
    """
    count = len(ratings_by_source)
    if count < MIN_OBSERVATIONS_FOR_SCORE:
        return None, count, None, True, set()

    ratings = [rating for _source, rating in ratings_by_source]
    score = float(_statistics.median(ratings))
    stddev = _statistics.pstdev(ratings)
    agreement = max(0.0, 1.0 - stddev / (_RATING_SPAN / 2))
    sources = {source for source, _rating in ratings_by_source}
    return score, count, agreement, False, sources


def aggregate_defense_feeding(observations: list[ScoutingObservation]) -> DefenseFeedingProfile:
    """Aggregate one team's scouting observations at one event into a DefenseFeedingProfile.

    Defense and feeding are aggregated entirely independently: an
    observation missing one rating (only one of defense_rating/
    feeding_rating set -- ScoutingObservation permits this, requiring only
    that at least one be present) contributes to whichever metric it
    actually rated and nothing to the other. Below MIN_OBSERVATIONS_FOR_SCORE
    for a metric, that metric's insufficient_data is True and its score/
    agreement are both None -- never a confident-looking value built from
    too little data.
    """
    defense_ratings = [
        (obs.source, obs.defense_rating) for obs in observations if obs.defense_rating is not None
    ]
    feeding_ratings = [
        (obs.source, obs.feeding_rating) for obs in observations if obs.feeding_rating is not None
    ]

    defense_score, defense_count, defense_agreement, defense_insufficient, defense_sources = (
        _aggregate_one_metric(defense_ratings)
    )
    feeding_score, feeding_count, feeding_agreement, feeding_insufficient, feeding_sources = (
        _aggregate_one_metric(feeding_ratings)
    )

    return DefenseFeedingProfile(
        defense_score=defense_score,
        defense_observation_count=defense_count,
        defense_agreement=defense_agreement,
        defense_insufficient_data=defense_insufficient,
        feeding_score=feeding_score,
        feeding_observation_count=feeding_count,
        feeding_agreement=feeding_agreement,
        feeding_insufficient_data=feeding_insufficient,
        contributing_sources=sorted(defense_sources | feeding_sources),
    )
