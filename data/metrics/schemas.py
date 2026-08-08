"""Canonical models for Phase 3: statistical scoring metrics and scouting-observed
qualities (defense, feeding), composed into one served TeamMetrics object.

Models only. No database, no computation, no aggregation logic in this file
itself -- those live in the modules each later milestone built: pure
statistical functions (Milestone 3, data.metrics.statistics), match-history
retrieval (Milestone 4, data.metrics.history), scouting observation
validation (Milestone 5, data.metrics.validator), normalization (Milestone 6,
data.metrics.normalizer), and the submission path (Milestone 7,
data.metrics.submission). Aggregation (Milestone 8) and the metrics
computation pipeline (Milestone 10) remain future work. This module exists to
fix the *shape* of Phase 3's core domain concepts before any of that logic was
written, for the same reason Milestone 6 (Phase 2's own Milestone 6, absolute
numbering) defined StagingEvent/Match/Team before data/staging/normalizer.py
existed: getting the canonical shape wrong here would force a schema re-key
later, exactly as the team_key -> team_number re-key in Milestone 7 (Phase 2's
own Milestone 7) did.

Two independent measurement tracks compose into TeamMetrics:

  * ScoringProfile -- pure statistics computed from a team's own match score
    history (matches, match_teams). Nothing here is scouted; everything is
    derivable from data StratAI already has.
  * DefenseFeedingProfile -- aggregated from ScoutingObservation rows, which
    are themselves either a human's direct scouting-form submission or a
    future ScoutRadioz pull. This is the load-bearing design constraint from
    the "Critical Constraints" section carried in both CLAUDE.md and
    RUNNING_NOTES.md: "Defense/feeding scores = directly measured, NOT
    inferred from point output." There is deliberately no path from match
    scores to a defense or feeding number anywhere in this module -- nor
    anywhere else in the pipeline, which tests/test_defense_feeding_
    constraint.py pins with two teams whose scouting is identical and whose
    match scores are not.

Both tracks carry their own confidence signal (matches_used/matches_scheduled
and *_observation_count/*_agreement) rather than presenting a bare number. A
ScoringProfile built from 2 matches and one built from 12 are not
interchangeable to a future ML feature pipeline or strategy engine, and
neither is a defense_score built from one scout's opinion versus six scouts'
consensus -- so confidence is a first-class field, not something a caller has
to reconstruct later from a raw count.

All cross-field invariants below are enforced with pydantic model_validators,
which raise ValueError -- these compose directly with the _build_or_raise
pattern data/staging/normalizer.py already established (any ValueError raised
here becomes a pydantic ValidationError, which _build_or_raise converts into a
structured PayloadValidationError once these models are constructed from raw
payloads in a later milestone).

Dependency direction, decided now so a later milestone doesn't have to
discover it awkwardly: ScoutingObservation lives here (data.metrics), not in
data.staging, per this milestone's explicit instruction -- so its
validator/normalizer (structural validation of a raw scouting submission
before it becomes this model) also live in data.metrics, not
data.staging.validator/normalizer. data.staging is a foundational layer
today; nothing in it depends on data.metrics, and adding a
ScoutingObservation-shaped function there would make it import a higher-level
package, inverting that direction. data.metrics importing data.staging's
shared primitives (ValidationIssue, PayloadValidationError) the way
data.pipeline already imports from data.staging is the clean direction, and
the one data.metrics.validator (Milestone 5) and data.metrics.normalizer
(Milestone 6) both use. docs/P3Milestones.md originally pointed the
normalizer at data/staging/normalizer.py, written before this decision was
made, and was corrected to data/metrics when Milestone 5 confirmed the
contradiction.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# --- Rating scale --------------------------------------------------------
#
# 0-5 integer scale for both defense and feeding. 0 is a real, meaningful
# value ("confirmed no defense/feeding observed"), not a missing-data
# sentinel -- missing data is represented by DefenseFeedingProfile's
# insufficient_data flags, never by a 0 rating standing in for "unknown".
MIN_RATING = 0
MAX_RATING = 5

DEFENSE_RATING_DESCRIPTIONS: dict[int, str] = {
    0: "No defense observed -- team played offense/support only.",
    1: "Minimal/incidental defense -- occasional positioning, no sustained effect on an opponent.",
    2: "Light defense -- contested space part of the match but rarely disrupted scoring.",
    3: "Moderate defense -- consistently contested one opponent, measurably slowed their cycle time.",
    4: "Strong defense -- effectively shut down or severely hampered a specific opponent for extended periods.",
    5: "Elite defense -- alliance-defining shutdown; opponent's offense was neutralized for most of the match.",
}

FEEDING_RATING_DESCRIPTIONS: dict[int, str] = {
    0: "No feeding observed -- team did not deliver game pieces to teammates.",
    1: "Minimal/incidental feeding -- rare or accidental hand-offs.",
    2: "Light feeding -- occasional, unreliable delivery to a teammate.",
    3: "Moderate feeding -- regular, functional feeding role for part of the match.",
    4: "Strong feeding -- reliable, high-volume feeding that materially fed a teammate's scoring.",
    5: "Elite feeding -- feeding was the team's primary role, executed at a rate that defined the alliance's cycle.",
}

# --- Good/average/bad-day classification ---------------------------------
#
# A match is a "good day" if score > mean + GOOD_DAY_ZSCORE_THRESHOLD * stddev,
# a "bad day" if score < mean + BAD_DAY_ZSCORE_THRESHOLD * stddev (i.e. more
# than one stddev below the mean), otherwise "average". Requires at least
# MIN_MATCHES_FOR_STDDEV matches -- with fewer, stddev is undefined and no
# classification is attempted (see ScoringProfile's invariants). Thresholds
# live here, not in data.metrics.statistics, so Phase 3 Milestone 3 could
# implement against an already-fixed policy instead of re-deciding it
# mid-implementation.
GOOD_DAY_ZSCORE_THRESHOLD = 1.0
BAD_DAY_ZSCORE_THRESHOLD = -1.0
MIN_MATCHES_FOR_STDDEV = 2

# --- Reliability score ----------------------------------------------------
#
# Target definition (not yet computable -- see the gap below): reliability
# measures whether a robot shows up and finishes a match without a
# catastrophic failure, as distinct from consistency (how tightly clustered
# its output is when it DOES perform normally). Intended formula:
#
#   reliability_score = 100 * (1 - (no_shows + disqualifications) / matches_scheduled)
#
# KNOWN GAP: this needs per-team no-show/DQ status per match, which the
# canonical schema does not currently carry. data.clients.schemas.
# MatchAllianceResult models only `score` and `team_keys`; TBA's real alliance
# object very likely also exposes `dq_team_keys`/`surrogate_team_keys` (this
# is moderately-confident general knowledge, NOT verified against live TBA
# docs the way this codebase's other TBA field mappings were), and neither is
# modelled anywhere from the client layer down to `match_teams`. This is a
# real prerequisite for Phase 3 Milestone 3 to compute reliability_score for
# real, not a code bug -- confirm the field names against TBA's docs and extend
# MatchAllianceResult/StagingMatch/match_teams before relying on the target
# formula. Interim formula, computable with data that exists today:
#
#   reliability_score = 100 * (matches_used / matches_scheduled)
#
# This only captures "did we get a recorded result at all" (missing data),
# not "did the robot itself fail" -- weaker than the target definition, and
# documented here as exactly that: a placeholder, not a final answer.


class ScoringProfile(BaseModel):
    """Pure statistical summary of a team's own match-scoring history at one event.

    Computed entirely from raw match scores already in the canonical schema --
    nothing here is scouted or otherwise externally measured. See
    data.metrics.statistics (Phase 3 Milestone 3) for the functions that
    produce these values; this model only fixes their shape and the
    invariants relating them.

    None means "not computed", and the reason is always determined by
    matches_used:
      * matches_used == 0: every value field below is None -- there is no data.
      * matches_used == 1: average_score is defined (the average of one value
        is itself), but score_stddev, consistency_rating, reliability_score,
        and the day counts are None -- variance is undefined for one sample.
      * matches_used >= MIN_MATCHES_FOR_STDDEV: everything is defined.

    good_day_count + average_day_count + bad_day_count always equals
    matches_used when they are not None.

    average_score/score_stddev are bounded below by 0 (an FRC score is never
    negative; stddev is never negative by definition) but not above -- a
    future game's scoring could exceed anything seen so far, and a hard
    ceiling here would eventually reject real data the way an invented EPA
    tolerance was explicitly rejected in Milestone 9. consistency_rating and
    reliability_score are both scaled 0-100 by definition (see the reliability
    formula documented above ScoringProfile) and bounded accordingly.
    """

    matches_scheduled: int = Field(ge=0)
    matches_used: int = Field(ge=0)
    average_score: float | None = Field(default=None, ge=0)
    score_stddev: float | None = Field(default=None, ge=0)
    consistency_rating: float | None = Field(default=None, ge=0, le=100)
    # The one field here whose name promises more than it delivers, so the
    # caveat travels with the field itself rather than only in prose. Every
    # other surface already carries it -- the KNOWN GAP note above this class,
    # docs/metrics_pipeline.md section 6.3, and the Milestone 14 harness at
    # every site it prints the number -- but an API client saw the bare value
    # with nothing marking it interim. Field(description=) is the one place the
    # caveat reaches the served OpenAPI schema.
    reliability_score: float | None = Field(
        default=None, ge=0, le=100,
        description=(
            "INTERIM placeholder: the attendance ratio "
            "100 * matches_used / matches_scheduled, NOT a robot-failure or "
            "disqualification measure. See the KNOWN GAP note above "
            "ScoringProfile and docs/metrics_pipeline.md section 6.3."
        ),
    )
    good_day_count: int | None = Field(default=None, ge=0)
    average_day_count: int | None = Field(default=None, ge=0)
    bad_day_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_invariants(self) -> "ScoringProfile":
        if self.matches_used > self.matches_scheduled:
            raise ValueError(
                f"matches_used ({self.matches_used}) cannot exceed matches_scheduled ({self.matches_scheduled})"
            )

        variance_fields = ("score_stddev", "consistency_rating", "reliability_score")
        day_count_fields = ("good_day_count", "average_day_count", "bad_day_count")

        if self.matches_used == 0:
            populated = [
                name for name in ("average_score", *variance_fields, *day_count_fields)
                if getattr(self, name) is not None
            ]
            if populated:
                raise ValueError(f"matches_used is 0, so these must be None: {populated}")

        elif self.matches_used < MIN_MATCHES_FOR_STDDEV:
            populated = [name for name in (*variance_fields, *day_count_fields) if getattr(self, name) is not None]
            if populated:
                raise ValueError(
                    f"matches_used ({self.matches_used}) is below MIN_MATCHES_FOR_STDDEV "
                    f"({MIN_MATCHES_FOR_STDDEV}), so these must be None: {populated}"
                )

        day_counts = tuple(getattr(self, name) for name in day_count_fields)
        if any(count is not None for count in day_counts):
            if any(count is None for count in day_counts):
                raise ValueError("good_day_count, average_day_count, and bad_day_count must be set together")
            total = sum(count for count in day_counts if count is not None)
            if total != self.matches_used:
                raise ValueError(f"day counts sum to {total}, expected matches_used ({self.matches_used})")

        return self


class DefenseFeedingProfile(BaseModel):
    """Aggregated defense/feeding assessment for one team at one event, built
    exclusively from ScoutingObservation rows -- never from match scores.

    A score is present if and only if the matching insufficient_data flag is
    False -- there is deliberately no way to construct a confident-looking
    score from zero observations. Phase 3 Milestone 8 (data.metrics.aggregation.
    aggregate_defense_feeding) decided the exact minimum-observation threshold
    for anything above zero (2, not 1 -- see that module's docstring for why);
    this model only enforces that whatever that policy decides, "insufficient"
    and "no score" always travel together.

    *_agreement is a 0.0-1.0 confidence signal (1.0 = every observation
    agreed exactly, 0.0 = maximal disagreement), independent of
    observation_count: six scouts who all disagree is a real, low-confidence
    result, not the same as relying on one scout's opinion. Implemented in
    Phase 3 Milestone 8 (data.metrics.aggregation) as:
    agreement = max(0, 1 - observation_stddev / ((MAX_RATING - MIN_RATING) / 2)).

    contributing_sources lists which sources (e.g. "human_scout",
    "scoutradioz") had at least one observation counted, so a future
    explainability layer can say not just "how many" but "from where". Empty
    if and only if both defense and feeding are insufficient_data -- if
    either has a real score, at least one source must be named as having
    produced it.
    """

    defense_score: float | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    defense_observation_count: int = Field(ge=0)
    defense_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    defense_insufficient_data: bool

    feeding_score: float | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    feeding_observation_count: int = Field(ge=0)
    feeding_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    feeding_insufficient_data: bool

    contributing_sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_invariants(self) -> "DefenseFeedingProfile":
        if self.defense_insufficient_data == (self.defense_score is not None):
            raise ValueError("defense_score must be set if and only if defense_insufficient_data is False")
        if self.feeding_insufficient_data == (self.feeding_score is not None):
            raise ValueError("feeding_score must be set if and only if feeding_insufficient_data is False")
        if self.defense_observation_count == 0 and not self.defense_insufficient_data:
            raise ValueError("defense_insufficient_data must be True when defense_observation_count is 0")
        if self.feeding_observation_count == 0 and not self.feeding_insufficient_data:
            raise ValueError("feeding_insufficient_data must be True when feeding_observation_count is 0")

        has_real_data = not (self.defense_insufficient_data and self.feeding_insufficient_data)
        if has_real_data and not self.contributing_sources:
            raise ValueError("contributing_sources must be non-empty when defense or feeding has real data")
        if not has_real_data and self.contributing_sources:
            raise ValueError("contributing_sources must be empty when both defense and feeding are insufficient_data")
        return self


class ScoutingObservation(BaseModel):
    """One scout's (or ScoutRadioz's) direct assessment of one team's defense
    and/or feeding performance in one specific match.

    This is the source of truth for defense/feeding data -- DefenseFeedingProfile
    aggregates many of these but never substitutes a computed value for a
    missing one. At least one of defense_rating/feeding_rating must be
    present; an observation asserting neither is meaningless and rejected.

    event_key is denormalized from match_key (derivable via matches.event_key)
    because "every observation for this event" is expected to be this model's
    single most common access pattern, feeding both the API and the
    aggregation step -- the same denormalization tradeoff StagingMatch
    already makes for season. Consistency between match_key and event_key is
    a raw-payload validation concern (data.metrics.validator, Milestone 5,
    mirroring validate_tba_match_payload's identical check), not a pydantic
    invariant here -- mirroring how StagingMatch doesn't re-validate its own
    event_key format at the model level either. Both fields must already be
    present in the raw payload the normalizer receives (Milestone 6): nothing
    in this pipeline derives event_key from match_key via a database lookup,
    since data.pipeline.stage_batch calls every normalizer as a pure
    function with no database access.

    scout_identifier is a free-text string, not a foreign key to an accounts
    system -- there is no scouting-user-identity system in Phase 3. This is a
    deliberate, documented MVP limitation: nothing here prevents identity
    spoofing or duplicate scout names, and no Phase 3 milestone currently
    scoped is meant to fix that.
    """

    match_key: str = Field(min_length=1)
    event_key: str = Field(min_length=1)
    team_number: int = Field(gt=0)
    scout_identifier: str = Field(min_length=1)
    defense_rating: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    feeding_rating: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    notes: str | None = None
    source: str = Field(min_length=1)
    submitted_at: datetime

    @model_validator(mode="after")
    def _require_at_least_one_rating(self) -> "ScoutingObservation":
        if self.defense_rating is None and self.feeding_rating is None:
            raise ValueError("At least one of defense_rating or feeding_rating must be provided")
        return self


class TeamMetrics(BaseModel):
    """The complete, served metrics object for one team at one event -- the
    literal answer to "given a team number and event, return a complete
    metrics object" (Phase 3's Definition of Done).

    Composes ScoringProfile (pure statistics on match history) and
    DefenseFeedingProfile (aggregated scouting observations) under one
    identity. The two are kept as named sub-objects rather than flattened:
    unlike StagingMatch's flattening of TBA's alliance nesting (which exists
    only because TBA happens to structure its JSON that way), scoring and
    defense/feeding are two genuinely independent computations with
    independent confidence signals and independent source data -- composition
    here reflects real structure, not a source API's incidental shape.

    Deliberately a current-state snapshot -- one row per (team_number,
    event_key), upserted in place -- not an append-only history, consistent
    with team_event_stats and every other canonical table. Recomputing during
    a live event overwrites the previous value; reconstructing "what did we
    know as of match 5" means replaying the pipeline against a historical cut
    of raw_source_payloads (already versioned), not reading a stored
    TeamMetrics snapshot. Storing every intermediate snapshot was considered
    and rejected for Phase 3: unbounded growth for a need that isn't yet a
    stated requirement, and the versioned landing layer already makes it
    reconstructable later without having stored it directly.

    Event-scoped only. A season- or career-level rollup is a natural, likely
    future model (e.g. TeamSeasonMetrics) built the same way, not something
    this model tries to anticipate by growing extra fields now.

    season has no range constraint at this level, matching the precedent set
    by StagingEvent/StagingMatch: "is this season plausible" is a judgment
    call that belongs in a future quality-check layer (mirroring
    data.staging.quality's existing season plausibility warning), not a hard
    pydantic rejection here.
    """

    team_number: int = Field(gt=0)
    event_key: str = Field(min_length=1)
    season: int
    computed_at: datetime
    scoring: ScoringProfile
    defense_feeding: DefenseFeedingProfile
