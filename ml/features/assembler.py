"""Leakage-safe, point-in-time feature assembly for one match.

Phase 4 Milestone 1 (authoritative plan, docs/P4Milestones.md). This is the
foundation every later Phase 4 milestone builds on -- and the one milestone
where getting the temporal boundary wrong would silently corrupt everything
built on top of it, so this module's own docstrings spend more words on *why
a value is excluded* than on how a value is computed.

The central function, build_match_feature_row(database, match_key, as_of),
answers exactly one question honestly: "what did we know about these six
teams strictly before as_of?" -- never "what do we know about them now."
Phase 3's own team_metrics table cannot answer that question by itself, and
that fact is the reason this module exists rather than simply wrapping
data.metrics.read.get_team_metrics:

    TeamMetrics (data/metrics/schemas.py) is explicitly documented as "a
    current-state snapshot... not an append-only history": one row per
    (team_number, event_key), upserted in place and overwritten every time
    compute_event_team_metrics reruns. A team_metrics row computed after an
    event finished reflects EVERY match at that event, including matches that
    happened after any earlier match in that same event. Reading that row to
    build features for an early match in the same event would leak the whole
    rest of the event backward into a "before this match" feature -- exactly
    the failure mode Milestone 1's brief calls point-in-time correctness
    "non-negotiable" to prevent.

So this module never reads team_metrics at all. It recomputes the scoring
statistics and the defense/feeding aggregate fresh, at read time, from
raw matches/match_teams/scouting_observations rows filtered to strictly
before as_of -- reusing Phase 3's own pure functions
(data.metrics.statistics.average_score/score_stddev/consistency_rating/
reliability_score and data.metrics.aggregation.aggregate_defense_feeding)
unmodified, so the *math* is identical to Phase 3's, only the *input rows*
differ. This is additive, not a change to Kanav's M3-M10 computation logic --
none of those modules are touched, only called.

EPA (Statbotics team_event_stats) gets a stricter, structurally different
rule, documented in full at _point_in_time_epa below: team_event_stats has no
historical/versioned series at all (one row per team/event, continuously
overwritten by however Statbotics last reported it), so there is no way to
prove a stored EPA value reflects only matches before any particular cutoff
*within its own event*. Rather than guess, this module never uses a team's
EPA from the SAME event as the target match, at any as_of -- only a strictly
earlier, already-concluded event's EPA is ever offered as a feature. This is
a real, documented gap (Milestone 11, "cross-season generalization guard",
and a future EPA-history table are the places to eventually improve this),
not a shortcut taken silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from data.metrics.aggregation import aggregate_defense_feeding
from data.metrics.schemas import ScoutingObservation
from data.metrics.statistics import (
    average_score,
    consistency_rating,
    reliability_score,
    score_stddev,
)
from database.connection import Database

__all__ = [
    "EPA_WITHHELD_NO_PRIOR_EVENT",
    "MatchFeatureRow",
    "TeamFeatures",
    "build_match_feature_row",
]

# The one reason this module currently ever withholds EPA. A single constant
# (not a set of finer-grained reasons) because the query that produces it
# already collapses every distinguishable cause -- "team has no other event
# at all" and "team's other events haven't concluded before as_of" -- into one
# "nothing qualified" result; see _point_in_time_epa's own docstring for why
# splitting them further isn't worth the complexity it would add.
EPA_WITHHELD_NO_PRIOR_EVENT = "no_prior_concluded_event_epa"


class TeamFeatures(BaseModel):
    """One team's leakage-safe feature snapshot, as known strictly before
    some as_of instant.

    Every optional feature is represented as an explicit (value, presence)
    pair -- e.g. defense_score / defense_score_present -- rather than relying
    on None alone to mean "absent", per Milestone 1's own explicit
    instruction. This is deliberately more than pydantic's None-based
    optionality already provides on its own, for a concrete reason tied to
    this milestone's own named "sentinel-collision" test: a bare None is only
    unambiguous for as long as every downstream consumer stays in Python and
    never substitutes a numeric fill value (0, -1) for missing data before
    handing a row to a model or a serialization format that has no concept of
    None. A real, legitimate defense_score of exactly 0 ("no defense
    observed" is DEFENSE_RATING_DESCRIPTIONS[0] in data/metrics/schemas.py,
    a genuine measured value, not a sentinel) must remain distinguishable
    from "no data exists" even after such a substitution -- and only an
    explicit boolean, not the numeric value itself, can survive that.

    Every value/presence pair here is computed together and checked for
    consistency below: presence is always exactly (value is not None). This
    module never fabricates a presence=True with no value, or a value that
    isn't reflected in presence -- if that ever happened it would mean a
    caller mixed truth from two different points in time, which is precisely
    what this module exists to prevent.

    average_score/score_stddev/consistency_rating/reliability_score are
    recomputed fresh from data.metrics.statistics against a point-in-time-
    filtered score list -- the same functions Phase 3's team_metrics table
    uses, applied to a different (temporally restricted) input. Their None
    conditions are therefore identical to ScoringProfile's own documented
    invariants (data/metrics/schemas.py): 0 matches used -> every one None;
    1 match used -> only average_score set; >= 2 matches used -> all four
    set. matches_considered/matches_used name the same two counts
    ScoringProfile itself carries (matches_scheduled/matches_used), renamed
    here only because "scheduled" would wrongly imply future matches are
    included -- every match counted here already happened before as_of.

    defense_score/defense_agreement/defense_observation_count (and the
    feeding equivalents) come from a fresh data.metrics.aggregation.
    aggregate_defense_feeding call over point-in-time-filtered
    ScoutingObservation rows -- Phase 3's own 2-observation minimum and
    median-based aggregation apply unmodified; this module only changes
    which observations are visible to it.

    EPA fields are described in full at _point_in_time_epa's docstring.
    epa_source_event_key names which (necessarily prior, necessarily
    different) event the EPA value came from, or None if withheld;
    epa_withheld_reason explains why when it is None, and must itself be
    None whenever any epa_*_present is True.
    """

    team_number: int = Field(gt=0)

    epa_total: float | None = None
    epa_total_present: bool
    epa_auto: float | None = None
    epa_auto_present: bool
    epa_teleop: float | None = None
    epa_teleop_present: bool
    epa_endgame: float | None = None
    epa_endgame_present: bool
    epa_source_event_key: str | None = None
    epa_withheld_reason: str | None = None

    average_score: float | None = Field(default=None, ge=0)
    average_score_present: bool
    score_stddev: float | None = Field(default=None, ge=0)
    score_stddev_present: bool
    consistency_rating: float | None = Field(default=None, ge=0, le=100)
    consistency_rating_present: bool
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    reliability_score_present: bool
    matches_considered: int = Field(ge=0)
    matches_used: int = Field(ge=0)

    defense_score: float | None = Field(default=None, ge=0, le=5)
    defense_score_present: bool
    defense_agreement: float | None = Field(default=None, ge=0, le=1)
    defense_agreement_present: bool
    defense_observation_count: int = Field(ge=0)
    feeding_score: float | None = Field(default=None, ge=0, le=5)
    feeding_score_present: bool
    feeding_agreement: float | None = Field(default=None, ge=0, le=1)
    feeding_agreement_present: bool
    feeding_observation_count: int = Field(ge=0)
    contributing_scouting_sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_presence_flags_match_values(self) -> "TeamFeatures":
        pairs = (
            ("epa_total", "epa_total_present"),
            ("epa_auto", "epa_auto_present"),
            ("epa_teleop", "epa_teleop_present"),
            ("epa_endgame", "epa_endgame_present"),
            ("average_score", "average_score_present"),
            ("score_stddev", "score_stddev_present"),
            ("consistency_rating", "consistency_rating_present"),
            ("reliability_score", "reliability_score_present"),
            ("defense_score", "defense_score_present"),
            ("defense_agreement", "defense_agreement_present"),
            ("feeding_score", "feeding_score_present"),
            ("feeding_agreement", "feeding_agreement_present"),
        )
        for value_field, present_field in pairs:
            value = getattr(self, value_field)
            present = getattr(self, present_field)
            if present != (value is not None):
                raise ValueError(
                    f"{present_field}={present} is inconsistent with {value_field}={value!r}"
                )

        if self.matches_used > self.matches_considered:
            raise ValueError(
                f"matches_used ({self.matches_used}) cannot exceed matches_considered ({self.matches_considered})"
            )

        any_epa_present = self.epa_total_present or self.epa_auto_present or self.epa_teleop_present or (
            self.epa_endgame_present
        )
        if any_epa_present:
            if self.epa_source_event_key is None:
                raise ValueError("an EPA field is present but epa_source_event_key is None")
            if self.epa_withheld_reason is not None:
                raise ValueError("an EPA field is present but epa_withheld_reason is set")
        else:
            if self.epa_source_event_key is not None:
                raise ValueError("no EPA field is present but epa_source_event_key is set")
            if self.epa_withheld_reason is None:
                raise ValueError("no EPA field is present but epa_withheld_reason is None (no reason given)")

        return self


class MatchFeatureRow(BaseModel):
    """One match's leakage-safe feature snapshot, as of a stated instant.

    Deliberately carries no outcome/label (score_red, score_blue,
    winning_alliance) -- that is Milestone 2's "labeled match-outcome dataset
    builder" job, not this one's. Keeping the two separate is not a stylistic
    preference: Milestone 1's whole job is to answer "what was knowable
    before this match", and mixing in the match's own real result here would
    make it trivial for a future caller to accidentally join a row's features
    to that same row's own outcome and call it a training example without
    ever having to think about the boundary this module exists to enforce.

    red_teams/blue_teams are not constrained to length 3, or even to being
    non-empty. FRC alliances are overwhelmingly 3 robots, but real synced
    data has already produced a wholly empty alliance (the frc0 unassigned-
    roster placeholder, RUNNING_NOTES.md 2026-08-01 and exercised directly in
    tests/test_metrics_history.py's own qm4 fixture) -- an earlier draft of
    this model required min_length=1 on both lists, which would have made
    build_match_feature_row crash on exactly that real, already-observed
    shape. Rejecting it here would repeat that mistake at a new layer instead
    of letting a consumer (Milestone 2's dataset builder) decide whether to
    skip it and count the skip.

    as_of must be timezone-aware. Every timestamp this module compares it
    against (matches.scheduled_time, scouting_observations.submitted_at) is
    stored as TIMESTAMPTZ; comparing a naive datetime against those columns
    is exactly the kind of "timestamp ambiguity" this milestone's brief asks
    to be checked for -- this codebase has already been burned once by an
    unverified local-vs-UTC assumption (RUNNING_NOTES.md, TBA's raw match
    times), and a naive as_of here would silently repeat that mistake against
    a boundary this milestone specifically exists to make non-negotiable, so
    it is rejected outright rather than guessed at.
    """

    match_key: str = Field(min_length=1)
    as_of: datetime
    event_key: str = Field(min_length=1)
    season: int
    red_teams: list[TeamFeatures] = Field(default_factory=list)
    blue_teams: list[TeamFeatures] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_as_of_is_timezone_aware(self) -> "MatchFeatureRow":
        if self.as_of.tzinfo is None:
            raise ValueError(
                "as_of must be timezone-aware -- a naive datetime cannot be safely compared "
                "against the TIMESTAMPTZ columns this module filters on"
            )
        return self


@dataclass(frozen=True)
class _EpaLookup:
    """Internal result of one point-in-time EPA lookup. Not part of the
    public API -- TeamFeatures is what callers see; this only exists so
    _point_in_time_epa and _build_team_features share one shape without a
    5-tuple."""

    epa_total: float | None
    epa_auto: float | None
    epa_teleop: float | None
    epa_endgame: float | None
    source_event_key: str | None
    withheld_reason: str | None


def _point_in_time_scores(
    database: Database, team_number: int, event_key: str, as_of: datetime,
) -> tuple[list[int], int]:
    """This team's own recorded scores at this event, restricted to matches
    with a known scheduled_time strictly before as_of.

    Matches whose scheduled_time is NULL are excluded entirely, not
    included, and not treated as "before" -- there is no way to prove a NULL
    timestamp is before as_of, and guessing in the permissive direction here
    is exactly the kind of leakage risk this module exists to refuse. In
    practice this is a safety net, not a routine occurrence: Phase 2's own
    2024-season validation (RUNNING_NOTES.md, 2026-07-25) found scheduled_time
    populated for every real synced match it checked.

    Returns (own_scores, matches_considered) -- own_scores already excludes
    unplayed matches (own alliance's score is NULL) the same way
    data.metrics.history.get_team_match_history does; matches_considered
    counts every rostered-and-temporally-eligible match regardless of
    whether it had been played, mirroring ScoringProfile's own
    matches_scheduled/matches_used distinction.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT mt.alliance_color, m.score_red, m.score_blue
            FROM match_teams mt
            JOIN matches m ON m.match_key = mt.match_key
            WHERE mt.team_number = %s AND m.event_key = %s
              AND m.scheduled_time IS NOT NULL AND m.scheduled_time < %s
            ORDER BY m.scheduled_time
            """,
            (team_number, event_key, as_of),
        )
        rows = cursor.fetchall()

    scores: list[int] = []
    for alliance_color, score_red, score_blue in rows:
        own_score = score_red if alliance_color == "red" else score_blue
        if own_score is not None:
            scores.append(own_score)
    return scores, len(rows)


def _point_in_time_observations(
    database: Database, team_number: int, event_key: str, as_of: datetime,
) -> list[ScoutingObservation]:
    """This team's scouting observations at this event, known strictly
    before as_of -- gated on BOTH of two independent timestamps, not one.

    submitted_at alone is not trusted as the sole cutoff, deliberately. It is
    source-dependent in a way this codebase already documents openly:
    data/metrics/scoutradioz.py sets submitted_at to the *match's own
    scheduled time* for every ScoutRadioz-imported row (its own docstring:
    "an ordering/audit timestamp... never used to compute a cross-event
    duration"), while a human_scout submission's submitted_at is whatever the
    submitting client claims, unverified against the match it describes.
    Trusting submitted_at alone would mean a malformed or malicious
    human_scout submission claiming an early submitted_at could make a
    genuinely-future observation look available before it happened.

    So this filters on both: the observation's own match must itself be
    scheduled strictly before as_of (an observation cannot precede the match
    it describes, structurally, regardless of what any source claims), AND
    submitted_at itself must be strictly before as_of (catching the
    legitimate case where a human scout's match happened before as_of but
    they did not actually submit their rating until later). Either check
    alone is insufficient; both together close both directions.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT so.match_key, so.event_key, so.team_number, so.scout_identifier,
                   so.defense_rating, so.feeding_rating, so.notes, so.source, so.submitted_at
            FROM scouting_observations so
            JOIN matches m ON m.match_key = so.match_key
            WHERE so.team_number = %s AND so.event_key = %s
              AND m.scheduled_time IS NOT NULL AND m.scheduled_time < %s
              AND so.submitted_at < %s
            ORDER BY so.submitted_at
            """,
            (team_number, event_key, as_of, as_of),
        )
        rows = cursor.fetchall()

    return [
        ScoutingObservation(
            match_key=match_key, event_key=obs_event_key, team_number=tn, scout_identifier=scout_identifier,
            defense_rating=defense_rating, feeding_rating=feeding_rating, notes=notes, source=source,
            submitted_at=submitted_at,
        )
        for (
            match_key, obs_event_key, tn, scout_identifier,
            defense_rating, feeding_rating, notes, source, submitted_at,
        ) in rows
    ]


def _point_in_time_epa(
    database: Database, team_number: int, target_event_key: str, as_of: datetime,
) -> _EpaLookup:
    """This team's EPA from its most recent already-concluded PRIOR event --
    never from the target match's own event, at any as_of.

    team_event_stats (Statbotics' EPA) has no historical/versioned series:
    one row per (team_number, event_key), continuously overwritten as
    Statbotics reports new values (docs/data_pipeline.md's own description:
    "optional, Statbotics-only"). There is no column recording "as of which
    match this value reflects". That means a stored EPA row for the target
    match's own event cannot be trusted at any as_of, no matter how it
    compares to the event's end_date: the row is whatever Statbotics last
    reported for that whole event, which -- for a live or recently-finished
    event -- routinely already reflects matches later than any particular
    match within it. Rather than guess at a "close enough" boundary, this
    function never offers same-event EPA at all.

    A DIFFERENT, already-concluded event's EPA is safe, because that event's
    own matches are all in the past relative to end_date, and this query
    additionally requires end_date < as_of -- so the source event's own
    conclusion is itself before the point in time being reconstructed.
    end_date is a DATE with no time-of-day or timezone component; the cast to
    ::timestamptz below compares it as midnight in the session's timezone,
    an intentionally explicit choice (rather than relying on an implicit
    cross-type comparison this module cannot verify against a live database
    in every environment) that introduces at most one day of imprecision at
    the boundary -- acceptable for event-to-event carryover, which operates
    on a scale of weeks, not hours.

    Returns the most recent (by end_date) qualifying event's EPA if one
    exists, else every field None with EPA_WITHHELD_NO_PRIOR_EVENT as the
    reason. That single reason deliberately does not distinguish "team has
    never attended another event" from "team's other events haven't
    concluded before as_of": both mean the same thing to a caller ("no
    trustworthy prior EPA exists"), and splitting them would need a second
    query to explain a case this one already resolves correctly.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT tes.event_key, tes.epa_total, tes.epa_auto, tes.epa_teleop, tes.epa_endgame
            FROM team_event_stats tes
            JOIN events e ON e.event_key = tes.event_key
            WHERE tes.team_number = %s
              AND tes.event_key != %s
              AND e.end_date IS NOT NULL
              AND e.end_date::timestamptz < %s
            ORDER BY e.end_date DESC
            LIMIT 1
            """,
            (team_number, target_event_key, as_of),
        )
        row = cursor.fetchone()

    if row is None:
        return _EpaLookup(None, None, None, None, None, EPA_WITHHELD_NO_PRIOR_EVENT)

    source_event_key, epa_total, epa_auto, epa_teleop, epa_endgame = row
    return _EpaLookup(epa_total, epa_auto, epa_teleop, epa_endgame, source_event_key, None)


def _build_team_features(
    database: Database, team_number: int, event_key: str, as_of: datetime,
) -> TeamFeatures:
    """Compose one team's point-in-time scoring, defense/feeding, and EPA
    features. Pure composition -- every actual number comes from Phase 3's
    own reused, unmodified functions (data.metrics.statistics,
    data.metrics.aggregation) applied to this module's point-in-time-
    filtered rows.
    """
    scores, matches_considered = _point_in_time_scores(database, team_number, event_key, as_of)
    matches_used = len(scores)

    average = average_score(scores)
    stddev = score_stddev(scores)
    consistency = consistency_rating(scores)
    reliability = reliability_score(matches_used, matches_considered)

    observations = _point_in_time_observations(database, team_number, event_key, as_of)
    profile = aggregate_defense_feeding(observations)

    epa = _point_in_time_epa(database, team_number, event_key, as_of)

    return TeamFeatures(
        team_number=team_number,
        epa_total=epa.epa_total, epa_total_present=epa.epa_total is not None,
        epa_auto=epa.epa_auto, epa_auto_present=epa.epa_auto is not None,
        epa_teleop=epa.epa_teleop, epa_teleop_present=epa.epa_teleop is not None,
        epa_endgame=epa.epa_endgame, epa_endgame_present=epa.epa_endgame is not None,
        epa_source_event_key=epa.source_event_key, epa_withheld_reason=epa.withheld_reason,
        average_score=average, average_score_present=average is not None,
        score_stddev=stddev, score_stddev_present=stddev is not None,
        consistency_rating=consistency, consistency_rating_present=consistency is not None,
        reliability_score=reliability, reliability_score_present=reliability is not None,
        matches_considered=matches_considered, matches_used=matches_used,
        defense_score=profile.defense_score, defense_score_present=profile.defense_score is not None,
        defense_agreement=profile.defense_agreement, defense_agreement_present=profile.defense_agreement is not None,
        defense_observation_count=profile.defense_observation_count,
        feeding_score=profile.feeding_score, feeding_score_present=profile.feeding_score is not None,
        feeding_agreement=profile.feeding_agreement, feeding_agreement_present=profile.feeding_agreement is not None,
        feeding_observation_count=profile.feeding_observation_count,
        contributing_scouting_sources=list(profile.contributing_sources),
    )


def build_match_feature_row(database: Database, match_key: str, as_of: datetime) -> MatchFeatureRow:
    """Build one match's leakage-safe feature row, as knowable strictly
    before as_of.

    as_of is a required, explicit parameter with no default. A default (e.g.
    "now") would make it trivially easy to build a "historical" row that
    silently uses live current-state data instead of the stated cutoff --
    exactly the mistake this milestone's "point-in-time correctness is
    non-negotiable" rule exists to prevent. Every caller must state, in the
    open, what instant they are pretending it is.

    Raises ValueError if match_key does not exist -- an unknown match is a
    caller error (this is the one required identifying input, unlike, say,
    get_team_match_history's team_number, which is a soft lookup key over an
    otherwise-valid query), not a "real but empty" case to represent silently.

    Deterministic: same match_key + as_of, against unchanged data, always
    reads the same rows in the same order and produces bit-identical output
    -- every query here carries an explicit ORDER BY specifically so this
    holds, not incidentally.
    """
    if as_of.tzinfo is None:
        # Checked here, first, before any query runs -- not left to
        # MatchFeatureRow's own validator alone. That validator only fires
        # after every _point_in_time_* query below has already executed
        # with a naive as_of as a bound parameter, which is exactly the
        # ambiguous comparison this milestone's brief warns against;
        # catching it only after the fact would mean the unsafe queries
        # already ran. Fail before the first one does.
        raise ValueError(
            "as_of must be timezone-aware -- a naive datetime cannot be safely compared "
            "against the TIMESTAMPTZ columns this module filters on"
        )

    with database.cursor() as cursor:
        cursor.execute("SELECT event_key, season FROM matches WHERE match_key = %s", (match_key,))
        match_row = cursor.fetchone()
    if match_row is None:
        raise ValueError(f"No such match: {match_key!r}")
    event_key, season = match_row

    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT team_number, alliance_color
            FROM match_teams
            WHERE match_key = %s
            ORDER BY station_position NULLS LAST, team_number
            """,
            (match_key,),
        )
        roster = cursor.fetchall()

    red_team_numbers = [team_number for team_number, alliance_color in roster if alliance_color == "red"]
    blue_team_numbers = [team_number for team_number, alliance_color in roster if alliance_color == "blue"]

    red_teams = [_build_team_features(database, team_number, event_key, as_of) for team_number in red_team_numbers]
    blue_teams = [_build_team_features(database, team_number, event_key, as_of) for team_number in blue_team_numbers]

    return MatchFeatureRow(
        match_key=match_key, as_of=as_of, event_key=event_key, season=season,
        red_teams=red_teams, blue_teams=blue_teams,
    )
