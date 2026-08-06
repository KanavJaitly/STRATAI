"""Reading a stored TeamMetrics back out of team_metrics.

Phase 3 Milestone 13. The counterpart to Milestone 10's write path: where
data.metrics.compute computes a TeamMetrics and CanonicalRepository.
load_team_metrics flattens it into the table, this reassembles one row back
into the canonical model. Read-only -- nothing here computes, aggregates, or
recomputes anything, which is the milestone's own constraint: the API request
path reads team_metrics directly and never triggers a computation.

Lives in data.metrics rather than in the api package for the same reason
data.metrics.history (Milestone 4) does: every layer keeps its own SQL, and
api imports data rather than issuing queries of its own
(docs/data_pipeline.md section 2.3's dependency direction). It is a sibling of
history.py, not of compute.py -- compute_team_metrics is deliberately NOT what
the API calls.

Why the five-way diagnosis lives here
=====================================
A missing team_metrics row has four distinguishable causes, and telling them
apart requires knowing how the table is populated -- domain knowledge about
Milestone 10's pipeline, not about HTTP. Specifically:
compute_event_team_metrics only ever upserts a row for a team that
match_teams rosters at the event, and _delete_orphaned_team_metrics actively
removes the row for a team a schedule correction drops from that roster. So
"no row" means either "compute has not run for this event yet" or "this team
was never at this event" -- and those are different answers to the caller:
the first resolves by waiting or triggering a compute, the second never
resolves at all. Collapsing them into one "not computed" would tell a client
to retry something that can never succeed.

look_up_team_metrics therefore returns a status alongside the metrics, and
the API layer maps that status onto a response. Statuses are module-level
string constants rather than an Enum, matching this codebase's existing
convention for exactly this kind of closed vocabulary (data.staging.quality's
severity constants).

Reassembly re-validates
=======================
_team_metrics_from_row builds real ScoringProfile/DefenseFeedingProfile/
TeamMetrics objects, so Milestone 1's model_validators run on the way out --
it does not use model_construct. A stored row that somehow contradicted its
own invariants (a defense_score set alongside defense_insufficient_data=True,
say) therefore raises here instead of being served as a model that lies about
itself. 0008_metrics_schema.sql's CHECK constraints transcribe those same
validators, so this is unreachable in practice; it is deliberate
belt-and-braces on the boundary where data leaves the system, and failing
loudly is the right direction to fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.metrics.schemas import DefenseFeedingProfile, ScoringProfile, TeamMetrics
from database.connection import Database

__all__ = [
    "STATUS_EVENT_NOT_FOUND",
    "STATUS_FOUND",
    "STATUS_METRICS_NOT_COMPUTED",
    "STATUS_TEAM_DID_NOT_ATTEND",
    "STATUS_TEAM_NOT_FOUND",
    "TeamMetricsLookup",
    "get_team_metrics",
    "look_up_team_metrics",
]


# The metrics exist and are returned.
STATUS_FOUND = "found"
# team_number is not in the canonical teams table. Note what this does and does
# not assert: it is a fact about StratAI's own database, not about FRC. A real
# team that has simply never been synced reads as not found, which is honest --
# the API can only answer for data it holds.
STATUS_TEAM_NOT_FOUND = "team_not_found"
# event_key is not in the canonical events table, same caveat.
STATUS_EVENT_NOT_FOUND = "event_not_found"
# Both exist, but this team is not rostered into any match at this event. A
# dead end: no compute run will ever produce this row (see the module
# docstring).
STATUS_TEAM_DID_NOT_ATTEND = "team_did_not_attend"
# Both exist and the team is rostered, but no metrics row has been written yet.
# A wait-and-retry state, unlike the one above.
STATUS_METRICS_NOT_COMPUTED = "metrics_not_computed"


# Every column of team_metrics, in the order _team_metrics_from_row unpacks
# them. Spelled out rather than SELECT * so a future migration that adds a
# column cannot silently shift the positional unpacking below.
_TEAM_METRICS_COLUMNS = """
    team_number, event_key, season, computed_at,
    matches_scheduled, matches_used, average_score, score_stddev,
    consistency_rating, reliability_score,
    good_day_count, average_day_count, bad_day_count,
    defense_score, defense_observation_count, defense_agreement, defense_insufficient_data,
    feeding_score, feeding_observation_count, feeding_agreement, feeding_insufficient_data,
    contributing_sources
"""


@dataclass(frozen=True)
class TeamMetricsLookup:
    """The outcome of one team_metrics lookup: a status, and metrics if found.

    metrics is not None if and only if status is STATUS_FOUND. The four other
    statuses each name a different reason no metrics exist, which the caller
    needs in order to say something true about what to do next -- see this
    module's docstring for why "no row" is not one answer but two.
    """

    status: str
    metrics: TeamMetrics | None = None


def _team_metrics_from_row(row: tuple[Any, ...]) -> TeamMetrics:
    """Reassemble one team_metrics row into the canonical nested model.

    The inverse of CanonicalRepository._upsert_team_metrics: 0008 flattens
    TeamMetrics' two sub-models into columns that each keep their model field
    name, so this is mechanical. Column types are chosen to make it so --
    DOUBLE PRECISION rather than NUMERIC specifically so psycopg returns float
    and not Decimal here (0008 records that reasoning), and TEXT[] comes back
    as a list[str] with no conversion.
    """
    return TeamMetrics(
        team_number=row[0],
        event_key=row[1],
        season=row[2],
        computed_at=row[3],
        scoring=ScoringProfile(
            matches_scheduled=row[4],
            matches_used=row[5],
            average_score=row[6],
            score_stddev=row[7],
            consistency_rating=row[8],
            reliability_score=row[9],
            good_day_count=row[10],
            average_day_count=row[11],
            bad_day_count=row[12],
        ),
        defense_feeding=DefenseFeedingProfile(
            defense_score=row[13],
            defense_observation_count=row[14],
            defense_agreement=row[15],
            defense_insufficient_data=row[16],
            feeding_score=row[17],
            feeding_observation_count=row[18],
            feeding_agreement=row[19],
            feeding_insufficient_data=row[20],
            contributing_sources=list(row[21]),
        ),
    )


def get_team_metrics(database: Database, team_number: int, event_key: str) -> TeamMetrics | None:
    """Fetch one team's stored metrics at one event, or None if no row exists.

    A direct primary-key read against team_metrics -- one query, no
    computation. Returns None for every reason a row might be absent without
    distinguishing them; look_up_team_metrics is the function that tells those
    reasons apart.
    """
    with database.cursor() as cursor:
        cursor.execute(
            f"SELECT {_TEAM_METRICS_COLUMNS} FROM team_metrics WHERE team_number = %s AND event_key = %s",
            (team_number, event_key),
        )
        row = cursor.fetchone()

    return None if row is None else _team_metrics_from_row(row)


def _diagnose_missing_row(database: Database, team_number: int, event_key: str) -> str:
    """Explain why team_number/event_key has no team_metrics row.

    One statement, three EXISTS subqueries: a single round trip, and -- because
    it is one statement -- a single snapshot, so the three facts cannot
    contradict each other the way three separate queries around a concurrent
    sync could.

    The roster check duplicates data.metrics.history's match_teams/matches
    join rather than calling get_team_match_history. That was a considered
    tradeoff: get_team_match_history fetches every row, resolves each
    alliance's score, and sorts by play order to produce a history object,
    which is a great deal of work to answer a boolean, and it cannot fold into
    the single statement above. The join shape is copied verbatim so there
    remains one convention for "was this team at this event", not two.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                EXISTS (SELECT 1 FROM teams  WHERE team_number = %s),
                EXISTS (SELECT 1 FROM events WHERE event_key   = %s),
                EXISTS (
                    SELECT 1
                    FROM match_teams mt
                    JOIN matches m ON m.match_key = mt.match_key
                    WHERE mt.team_number = %s AND m.event_key = %s
                )
            """,
            (team_number, event_key, team_number, event_key),
        )
        team_exists, event_exists, attended = cursor.fetchone()

    if not team_exists:
        return STATUS_TEAM_NOT_FOUND
    if not event_exists:
        return STATUS_EVENT_NOT_FOUND
    if not attended:
        return STATUS_TEAM_DID_NOT_ATTEND
    return STATUS_METRICS_NOT_COMPUTED


def look_up_team_metrics(database: Database, team_number: int, event_key: str) -> TeamMetricsLookup:
    """Read one team's stored metrics at one event, or say precisely why not.

    The happy path costs exactly one query: the team_metrics read is attempted
    first, and nothing else runs when it succeeds. Only a miss pays for the
    diagnosis, which is one further query.

    Read-only, and never recomputes -- a team whose metrics have not been
    computed gets STATUS_METRICS_NOT_COMPUTED, not a freshly computed object.
    Computing is data.metrics.compute's job, triggered by the pipeline, not by
    a read.
    """
    metrics = get_team_metrics(database, team_number, event_key)
    if metrics is not None:
        return TeamMetricsLookup(status=STATUS_FOUND, metrics=metrics)
    return TeamMetricsLookup(status=_diagnose_missing_row(database, team_number, event_key))
