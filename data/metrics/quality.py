"""Quality checks over a computed TeamMetrics, and the vocabulary its issues use.

Phase 3 Milestone 11. Every other quality check in this codebase judges an
*ingested* record -- a payload some external source sent, screened before it
reaches the canonical tables (data.staging.quality). A team_metrics row is not
ingested; it is computed by data.metrics.compute from rows that already passed
those checks. That changes what there is to look for, in two ways:

  * Nothing here can be out of range. consistency_rating and reliability_score
    are bounded 0-100 in three independent places -- statistics.py clamps or
    constrains them at the source, ScoringProfile's Field(ge=, le=) rejects
    anything else, and 0008's team_metrics_scoring_range_check refuses to
    store it. The same is true of every cross-field invariant either model
    declares. So "implausible" here can only mean *jointly* suspicious: two or
    more fields that are each individually valid but that cannot both be true
    of the same team's match set. Each rule below was checked against both the
    validators and the CHECK constraints to confirm it can actually fire on a
    constructible, storable row; a rule that could not was dropped rather than
    written as dead code.

  * Nothing here is ever rejected. Severity is policy (see data.staging.
    quality's module docstring), and the policy for a computed metric is that
    it is *untrustworthy, not corrupt*. A metric computed from two matches is
    real -- it is the honest summary of the two matches that exist -- and
    discarding it would leave the team with no metrics at all, which is
    strictly worse than a flagged one. So every rule here is a warning: the
    row records an issue and loads anyway. There is deliberately no
    metrics-side rejection path to write, since the constraints above already
    make a genuinely impossible metric unstorable.

The point of the milestone is the second bullet's consequence. Before this,
a reliability_score of 100.0 from two matches and one from twelve were the same
number in the same column, indistinguishable to anything reading team_metrics.
Now the thin one leaves a row in data_quality_issues naming the team, the
field, and why -- queryable, not silently equivalent.

No second mechanism. These functions build data.staging.quality's own
QualityIssue, with its own severity and issue-type constants, and
data.metrics.compute hands them to the same DataQualityRecorder that writes
every ingestion issue, into the same data_quality_issues table. This module
adds checks, not machinery. It lives in data.metrics rather than in
data.staging.quality only because it must import data.metrics.schemas, and
data.staging must not depend on data.metrics -- the same reasoning, and the
same resolution, as Milestone 7's check_scouting_observation_references in
data.metrics.submission.

Deliberately NOT implemented: re-deriving consistency_rating from
average_score and score_stddev and flagging any disagreement. It sounds
stronger than the zero-variance check below and is not. compute.py computes
all three from one scores list in a single expression, so no code path can
make them disagree in the middle of the range -- it would fire only on a row
mutated outside the pipeline, which nothing does. The cost is a second copy of
Milestone 3's formula in a module that does not own it, which a deliberate
future change to that formula would light up on every existing row. The
boundary check keeps the reachable half of the catch and survives such a
change, because it depends on no particular formula: any definition of
consistency maps zero variance to its maximum.
"""

from __future__ import annotations

from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE
from data.metrics.schemas import (
    MAX_RATING,
    MIN_MATCHES_FOR_STDDEV,
    MIN_RATING,
    DefenseFeedingProfile,
    ScoringProfile,
    TeamMetrics,
)
from data.staging.quality import (
    ISSUE_IMPLAUSIBLE_VALUE,
    ISSUE_INCONSISTENT_VALUES,
    ISSUE_LOW_SAMPLE_SIZE,
    LOW_AGREEMENT,
    LOW_SAMPLE_MATCHES,
    LOW_SAMPLE_OBSERVATIONS,
    SEVERITY_WARNING,
    QualityIssue,
)

__all__ = [
    "OBJECT_TYPE_TEAM_METRICS",
    "QUALITY_SOURCE",
    "check_team_metrics",
    "team_metrics_object_id",
]

# The `source` recorded on a metric issue. data_quality_issues.source names the
# producer of the record an issue is about: for an ingested payload that is the
# external API it came from, and for a computed row it is the computation.
# Matches data.metrics.compute.PIPELINE_NAME (pinned by a test) so an issue
# joins to the pipeline_runs row that produced it on one predicate, and follows
# the precedent data.staging.quality.issues_from_extraction_errors already set
# by recording source="pipeline" for an issue with no external source.
QUALITY_SOURCE = "metrics_compute"

# Matches data.metrics.compute.ENTITY_TYPE_TEAM_METRICS (pinned by a test).
# 0007 established that one word describes one entity across the raw rows, the
# watermarks, the quality issues, and the lineage; this is that word for a
# team_metrics row, and it is what separates metric issues from ingestion ones
# for any caller that wants only one kind.
OBJECT_TYPE_TEAM_METRICS = "team_metrics"

# Float comparison tolerance. Every value compared here is a Python float
# round-tripped through DOUBLE PRECISION, so exact equality would be a latent
# false positive; the quantities being distinguished (0 vs. a real stddev, an
# exact ratio vs. a different one) are never this close legitimately.
_TOLERANCE = 1e-6

# reliability_score's maximum on its documented 0-100 scale: a team that was
# recorded in every match it was scheduled for.
_MAX_RELIABILITY = 100.0

# consistency_rating's maximum, reached only at zero variance.
_MAX_CONSISTENCY = 100.0

# The widest population stddev the rating scale admits, and therefore the
# denominator behind every agreement value -- used only to phrase a flagged
# disagreement in rating tiers rather than in agreement units, which is the
# form a scouting lead can act on.
_RATING_HALF_SPAN = (MAX_RATING - MIN_RATING) / 2


def team_metrics_object_id(team_number: int, event_key: str) -> str:
    """Render a team_metrics row's data_quality_issues.object_id.

    Its own primary key as text, identical to what canonical_lineage.entity_key
    already stores for the same row, so an issue and its lineage can be joined
    on this value. Deliberately duplicates data.metrics.compute.
    team_metrics_entity_key's two-line format rather than importing it:
    compute.py imports this module, and importing it back would be circular.
    Equality of the two is pinned by a test, the same trade this codebase
    already makes for the TBA team-key regex duplicated between data.pipeline
    and data.staging.quality.
    """
    return f"{team_number}_{event_key}"


def _issue_builder(source: str, object_id: str):
    """Build QualityIssues for one team_metrics row, mirroring data.staging.quality's own.

    raw_payload_id is always None, and that is the accurate value rather than a
    missing one: a team_metrics row has no single originating payload. It is
    derived from every match this team played and every scouting observation
    recorded about it, across up to three sources, so naming any one payload
    would assert a provenance that is not true. That many-to-one relationship
    is already recorded properly in canonical_lineage by Milestone 10, and
    object_id here equals entity_key there, so nothing is lost -- the full set
    of contributing payloads is one join away. Issues with no raw payload are
    also not new: extraction-failure issues have been written this way since
    Phase 2 Milestone 9.
    """

    def build(issue_type: str, field_name: str, description: str) -> QualityIssue:
        return QualityIssue(
            source=source,
            object_type=OBJECT_TYPE_TEAM_METRICS,
            object_id=object_id,
            issue_type=issue_type,
            # Every metric rule is a warning, without exception -- see this
            # module's docstring. Not a parameter, so no future rule can
            # quietly acquire the power to discard a computed metric.
            severity=SEVERITY_WARNING,
            description=description,
            field=field_name,
            raw_payload_id=None,
        )

    return build


# ---------------------------------------------------------------------------
# Scoring checks
# ---------------------------------------------------------------------------


def _check_reliability_against_its_counts(scoring: ScoringProfile, build) -> list[QualityIssue]:
    """Flag a reliability_score that disagrees with the two counts defining it.

    reliability_score IS 100 * matches_used / matches_scheduled (data.metrics.
    statistics.reliability_score), and all three values sit in the same row.
    Disagreement means the number and its own inputs came from different
    computations -- a row written by something other than the current pipeline,
    or a formula change that never reached rows already stored.

    A warning rather than a rejection because there is no way to tell which
    side is wrong. The score may be stale and the counts current, or the
    reverse; discarding the row would throw away whichever one was right.
    """
    if scoring.reliability_score is None or scoring.matches_scheduled == 0:
        return []

    expected = _MAX_RELIABILITY * (scoring.matches_used / scoring.matches_scheduled)
    if abs(scoring.reliability_score - expected) <= _TOLERANCE:
        return []
    return [build(
        ISSUE_INCONSISTENT_VALUES, "reliability_score",
        f"reliability_score is {scoring.reliability_score:.4f} but matches_used"
        f"/matches_scheduled ({scoring.matches_used}/{scoring.matches_scheduled}) "
        f"defines it as {expected:.4f}",
    )]


def _check_maximal_reliability_from_a_thin_sample(scoring: ScoringProfile, build) -> list[QualityIssue]:
    """Flag a perfect reliability_score resting on too few matches to mean it.

    100.0 is the strongest claim this scale can make -- the team was recorded
    in every match it was scheduled for. Over a full qualification schedule
    that is a real, earned result. Over two matches it is arithmetic: a team
    scheduled for two and recorded in two stores exactly the same 100.0 as a
    team that went twelve for twelve, and nothing in team_metrics distinguishes
    them. That is the specific "indistinguishable from high-confidence" failure
    this milestone exists to close, and it is a joint condition -- neither the
    value nor the sample size is suspicious alone.

    This deliberately overlaps the low-sample-size warning below, which fires
    on the same row. They answer different questions and are found by different
    queries: filtering data_quality_issues on field='matches_used' asks "whose
    statistics rest on too little data", while field='reliability_score' asks
    "whose reliability number is overclaiming". Collapsing them would leave the
    second question unanswerable, since the first names no field.
    """
    if scoring.reliability_score is None:
        return []
    if scoring.reliability_score < _MAX_RELIABILITY - _TOLERANCE:
        return []
    if not 0 < scoring.matches_used < LOW_SAMPLE_MATCHES:
        return []
    return [build(
        ISSUE_IMPLAUSIBLE_VALUE, "reliability_score",
        f"reliability_score is a perfect {scoring.reliability_score:.1f} from only "
        f"{scoring.matches_used} recorded match(es) (fewer than {LOW_SAMPLE_MATCHES}); "
        f"the value is arithmetically correct but too thin to read as reliability",
    )]


def _check_consistency_against_stddev(scoring: ScoringProfile, build) -> list[QualityIssue]:
    """Flag consistency_rating and score_stddev making contradictory claims.

    consistency_rating is 100 * (1 - stddev/mean), clamped. For scores that are
    never negative the clamp's upper arm is unreachable, so the rating reaches
    100 exactly when stddev is 0 -- and the all-scores-zero branch that returns
    100.0 directly has a stddev of 0 too. "Perfectly consistent" and "output
    visibly varied" are therefore contradictory statements about one match set,
    in either direction.

    Deliberately checked at this boundary rather than by re-deriving the whole
    formula (see this module's docstring): zero variance implies maximum
    consistency under any definition of consistency, so this survives a future
    change to the formula that a full re-derivation would not.
    """
    consistency, stddev = scoring.consistency_rating, scoring.score_stddev
    if consistency is None or stddev is None:
        return []

    claims_perfect = abs(consistency - _MAX_CONSISTENCY) <= _TOLERANCE
    scores_varied = stddev > _TOLERANCE

    if claims_perfect and scores_varied:
        return [build(
            ISSUE_INCONSISTENT_VALUES, "consistency_rating",
            f"consistency_rating is a perfect {consistency:.4f}, which requires zero "
            f"variance, but score_stddev is {stddev:.4f}",
        )]
    if not claims_perfect and not scores_varied:
        return [build(
            ISSUE_INCONSISTENT_VALUES, "consistency_rating",
            f"score_stddev is {stddev:.4f} (no variance), which requires a perfect "
            f"consistency_rating of {_MAX_CONSISTENCY:.1f}, but it is {consistency:.4f}",
        )]
    return []


def _check_day_counts_against_stddev(scoring: ScoringProfile, build) -> list[QualityIssue]:
    """Flag a good or bad day recorded for a team whose scores never varied.

    classify_match_days puts a match above mean + 1 stddev in "good" and below
    mean - 1 stddev in "bad". At zero variance both cutoffs collapse onto the
    mean, and the comparisons are strict, so every match classifies "average" --
    a match cannot be strictly above or below a value it equals. A good or bad
    day therefore asserts a deviation the stddev says did not happen.

    One-armed on purpose. The converse does not hold: a non-zero stddev implies
    nothing about whether any match cleared a one-stddev cutoff (scores of 10
    and 20 vary, yet both classify "average"), so an all-average team with real
    variance is perfectly ordinary and is not flagged.
    """
    if scoring.score_stddev is None or scoring.score_stddev > _TOLERANCE:
        return []

    issues: list[QualityIssue] = []
    for field_name, count in (
        ("good_day_count", scoring.good_day_count),
        ("bad_day_count", scoring.bad_day_count),
    ):
        if count:
            issues.append(build(
                ISSUE_INCONSISTENT_VALUES, field_name,
                f"{field_name} is {count} but score_stddev is 0, so no match deviated "
                f"from the mean and every match must classify as an average day",
            ))
    return issues


def _check_for_statistics_missing_despite_enough_matches(
    scoring: ScoringProfile, build,
) -> list[QualityIssue]:
    """Flag a statistic absent where the sample size promises one.

    data.metrics.statistics is total by contract: at MIN_MATCHES_FOR_STDDEV
    matches or more, every one of these values is defined. Exactly one
    production path returns None anyway -- consistency_rating's out-of-domain
    guard, which fires only when the mean is 0 while some score is not, and
    that requires a *negative* score to have reached match_teams. So an
    unexpected None here is evidence of upstream corruption, and today it is
    invisible: it looks exactly like the ordinary "not enough matches yet"
    None, which is the same value for an entirely benign reason.

    One issue per missing field, so the audit trail names which statistic went
    missing rather than only that something did.
    """
    if scoring.matches_used < MIN_MATCHES_FOR_STDDEV:
        return []

    return [
        build(
            ISSUE_IMPLAUSIBLE_VALUE, field_name,
            f"{field_name} is not computed despite {scoring.matches_used} matches used "
            f"(at least {MIN_MATCHES_FOR_STDDEV} defines it); this normally means a "
            f"negative score reached the match history",
        )
        for field_name in (
            "score_stddev", "consistency_rating", "reliability_score",
            "good_day_count", "average_day_count", "bad_day_count",
        )
        if getattr(scoring, field_name) is None
    ]


def _check_scoring_sample_size(scoring: ScoringProfile, build) -> list[QualityIssue]:
    """Warn that a team's statistics rest on too few matches, without discarding them.

    matches_used is the scoring track's confidence signal -- ScoringProfile
    carries no insufficient_data flag because the count itself is one. Below
    LOW_SAMPLE_MATCHES every statistic derived from it is real but shaky, and
    that is a warning by definition of this project's severity policy: the
    numbers are the honest summary of the matches that exist, and rejecting
    them would leave the team with nothing at all.

    Not flagged at matches_used == 0. There, every value field is already None,
    so nothing is being presented as confident and there is no false impression
    to correct -- and during a live event that is every team on the schedule
    before the first match is played.
    """
    if not 0 < scoring.matches_used < LOW_SAMPLE_MATCHES:
        return []
    return [build(
        ISSUE_LOW_SAMPLE_SIZE, "matches_used",
        f"Scoring statistics are computed from {scoring.matches_used} match(es), below "
        f"the {LOW_SAMPLE_MATCHES} needed for confidence; the values are real but "
        f"should not be compared with a team's full-schedule statistics",
    )]


# ---------------------------------------------------------------------------
# Defense / feeding checks
# ---------------------------------------------------------------------------


def _check_one_scouted_metric(
    metric: str,
    score: float | None,
    observation_count: int,
    agreement: float | None,
    insufficient_data: bool,
    build,
) -> list[QualityIssue]:
    """Run every defense/feeding rule for one of the two metrics.

    Called once for defense and once for feeding, which are aggregated
    independently (an observation rating only one contributes only to that
    one), so their confidence can differ sharply for the same team and each
    must be judged on its own.

    Nothing here fires when insufficient_data is True. That is the model
    correctly reporting no score, not a low-confidence one -- flagging it would
    write two rows for every unscouted team at every event, and at a real event
    most teams have no observations at all. Drowning the genuine findings in
    that is exactly how a quality table becomes something people stop reading.
    """
    issues: list[QualityIssue] = []
    count_field, agreement_field = f"{metric}_observation_count", f"{metric}_agreement"

    # A score reported below the aggregator's own minimum. aggregate_defense_
    # feeding refuses to report one below MIN_OBSERVATIONS_FOR_SCORE, because a
    # single observation cannot establish agreement and reporting the trivial
    # zero-variance of one point as consensus is fabricated confidence. That
    # policy lives only in the aggregator: both the model and 0008's
    # sufficiency CHECK require merely a non-zero count, so a score built from
    # one observation is storable and looks like any other.
    if not insufficient_data and observation_count < MIN_OBSERVATIONS_FOR_SCORE:
        issues.append(build(
            ISSUE_INCONSISTENT_VALUES, count_field,
            f"{metric}_score is reported from {observation_count} observation(s), below the "
            f"{MIN_OBSERVATIONS_FOR_SCORE} the aggregation policy requires before reporting "
            f"any score",
        ))

    # A score and its agreement are produced together and are meaningless
    # apart: agreement is the confidence half of the score. The model enforces
    # score <-> insufficient_data but leaves agreement independently optional,
    # so a score can be stored stripped of its uncertainty -- precisely the
    # state this milestone exists to make impossible to overlook.
    if not insufficient_data and agreement is None:
        issues.append(build(
            ISSUE_INCONSISTENT_VALUES, agreement_field,
            f"{metric}_score is {score} but {agreement_field} is absent, leaving the score "
            f"with no confidence signal at all",
        ))
    elif insufficient_data and agreement is not None:
        issues.append(build(
            ISSUE_INCONSISTENT_VALUES, agreement_field,
            f"{agreement_field} is {agreement} but {metric}_insufficient_data is True, so "
            f"there is no score for it to describe",
        ))

    if not insufficient_data and observation_count < LOW_SAMPLE_OBSERVATIONS:
        issues.append(build(
            ISSUE_LOW_SAMPLE_SIZE, count_field,
            f"{metric}_score rests on {observation_count} observation(s), below the "
            f"{LOW_SAMPLE_OBSERVATIONS} needed for confidence; it is a real assessment but "
            f"a thin consensus",
        ))

    # Low agreement is an independent axis from observation count, and the only
    # rule here that fires on entirely ordinary data. Six scouts who disagree
    # is a real, low-confidence result that no count can express -- the score
    # clears every sample-size rule and still should not be trusted.
    if not insufficient_data and agreement is not None and agreement < LOW_AGREEMENT:
        tiers = (1.0 - agreement) * _RATING_HALF_SPAN
        issues.append(build(
            ISSUE_LOW_SAMPLE_SIZE, agreement_field,
            f"{agreement_field} is {agreement:.2f} across {observation_count} observation(s), "
            f"below {LOW_AGREEMENT}: scouts differ by about {tiers:.1f} rating tiers, so they "
            f"do not agree which tier this team belongs in",
        ))

    return issues


def _check_defense_feeding(profile: DefenseFeedingProfile, build) -> list[QualityIssue]:
    """Run the defense and feeding rules over one aggregated profile."""
    return [
        *_check_one_scouted_metric(
            "defense", profile.defense_score, profile.defense_observation_count,
            profile.defense_agreement, profile.defense_insufficient_data, build,
        ),
        *_check_one_scouted_metric(
            "feeding", profile.feeding_score, profile.feeding_observation_count,
            profile.feeding_agreement, profile.feeding_insufficient_data, build,
        ),
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def check_team_metrics(metrics: TeamMetrics, *, source: str = QUALITY_SOURCE) -> list[QualityIssue]:
    """Run every quality check against one computed TeamMetrics.

    The metrics-side counterpart to data.staging.quality.check_entity, and
    deliberately a separate entry point rather than a new branch inside it:
    check_entity dispatches over data.staging's four models and raises
    TypeError for anything else, and teaching it about TeamMetrics would make
    data.staging import data.metrics. Keeping them separate also means a
    TeamMetrics cannot be routed through the ingestion dispatcher by accident --
    it still raises there, loudly.

    Pure and total: no database access, no I/O, and no exception for any
    input the models permit. Returns every finding as a QualityIssue for the
    caller to record; persisting is data.metrics.compute's job, exactly as
    stage_batch -- not the normalizers -- owns quality screening on the
    ingestion side.

    Every issue returned is a warning. Nothing this function reports should
    keep a metric out of team_metrics, and no caller should treat a non-empty
    result as a reason to skip a load.
    """
    build = _issue_builder(source, team_metrics_object_id(metrics.team_number, metrics.event_key))
    scoring = metrics.scoring

    return [
        *_check_reliability_against_its_counts(scoring, build),
        *_check_maximal_reliability_from_a_thin_sample(scoring, build),
        *_check_consistency_against_stddev(scoring, build),
        *_check_day_counts_against_stddev(scoring, build),
        *_check_for_statistics_missing_despite_enough_matches(scoring, build),
        *_check_scoring_sample_size(scoring, build),
        *_check_defense_feeding(metrics.defense_feeding, build),
    ]
