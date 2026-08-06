"""Read-only report of computed team metrics, for manual human validation.

Phase 3 Milestone 14. The metrics counterpart to scripts/spot_check.py, and
deliberately built to the same shape: print what the pipeline computed, in a
form a person can scan, and let that person judge it. Phase 2's spot check put
stored match results in front of someone who knew the real results; this puts
computed defense and feeding ratings in front of someone who watched the
robots.

It is strictly read-only. Every statement is a SELECT, and nothing here
recomputes: metrics come from data.metrics.read.look_up_team_metrics -- the
same function Milestone 13's API endpoint calls -- which reads team_metrics
directly and never invokes data.metrics.compute. Running this script adds no
pipeline_runs row and changes no stored value.

No verdict, deliberately
========================
There is no pass/fail here, no threshold, no "looks right", and the exit code
is always 0. scripts/spot_check.py declines to grade itself because an
automated comparison against TBA would just re-implement the pipeline's
normalization and agree with it by construction. The reason here is stronger:
defense and feeding have no external truth source at all. There is no
thebluealliance.com page for "was 1678 actually a 3.5 defender" -- the only
authority is a human who watched the matches. An automated check could only
compare the aggregation against itself.

Two divergences from scripts/spot_check.py, both for that reason:

  * No --preset. The Phase 2 preset curates memorable *public* results so they
    can be checked against TBA. Nothing here can be curated in advance, because
    only the validator knows which teams they scouted. --event with no --team
    is the discovery mode that replaces it.
  * --team requires --event, with no default. spot_check.py can default
    --season 2024; there is no sensible default event, because TeamMetrics is
    keyed by the (team, event) pair.

Usage:

    python -m scripts.metrics_spot_check --event 2024casj
    python -m scripts.metrics_spot_check --event 2024casj --team 1678 --team 254
    python -m scripts.metrics_spot_check --event 2024casj --team 1678 --verbose

The per-team report leads with defense and feeding, because those are the only
numbers a human can actually validate from memory, and it always lists the
individual observations behind them -- which match, which scout, what rating.
That listing is the milestone's real deliverable, not a --verbose extra:
Milestone 14's brief says that when a score is disputed, the harness must
surface which observations contributed so Milestone 8's aggregation can be
revisited. contributing_sources alone does not do that -- it names sources
("human_scout"), not the ratings the median was taken over.

`--verbose` adds raw payload provenance, exactly as it does in
scripts/spot_check.py: each observation's raw_payload_id and the team_metrics
row's canonical_lineage entries.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from data.config import Settings

# ENTITY_TYPE_TEAM_METRICS and team_metrics_entity_key are both exported by
# data.metrics.compute, and importing them is not touching the compute path:
# the first is a constant and the second is a pure string formatter over
# (team_number, event_key). Duplicating the key format here instead would fail
# silently -- a wrong key simply reports "no lineage recorded" -- so the single
# source of truth is worth the import. Nothing in this module calls
# compute_team_metrics or compute_event_team_metrics.
from data.metrics.compute import ENTITY_TYPE_TEAM_METRICS, team_metrics_entity_key
from data.metrics.read import (
    STATUS_EVENT_NOT_FOUND,
    STATUS_FOUND,
    STATUS_METRICS_NOT_COMPUTED,
    STATUS_TEAM_DID_NOT_ATTEND,
    STATUS_TEAM_NOT_FOUND,
    look_up_team_metrics,
)
from data.metrics.schemas import MAX_RATING, MIN_MATCHES_FOR_STDDEV, TeamMetrics
from database.connection import Database, DatabaseConfig

# Printed once at the top of every run. The Phase 2 spot check carries the same
# warning for the same reason -- the point of a manual validation harness is
# defeated the moment the reader assumes something was checked for them.
BANNER = """\
==============================================================================
COMPUTED METRICS FOR MANUAL VALIDATION
Nothing here is checked automatically. Defense and feeding come from scouting
observations only -- compare them against your own assessment of these teams.
The pipeline must not be allowed to grade its own work.
=============================================================================="""

# reliability_score is not yet what its name promises. data/metrics/schemas.py
# documents the intended formula (penalising no-shows and disqualifications)
# and the fact that the canonical schema carries neither, so the computed value
# is the interim 100 * matches_used / matches_scheduled -- which reads 100.0 for
# every team whose scheduled matches all have a stored score. Printing that
# number without this caveat would invite a validator to sign off on a
# placeholder as a validated result, so the caveat appears at every site the
# number does.
RELIABILITY_INTERIM_NOTE = """\
  * reliability_score is the documented INTERIM placeholder formula
    (100 * matches_used / matches_scheduled), not the intended no-show/DQ
    measure -- see data/metrics/schemas.py. It reads 100.0 whenever every
    scheduled match has a stored score. Do not read it as a validated result."""

# What each non-found lookup status means to a person, and whether it can be
# resolved. Milestone 13 made this distinction machine-readable for API clients
# for exactly this reason: "no metrics" is not one answer but four, and two of
# them point in opposite directions -- one resolves by running a compute, the
# other never resolves at all.
STATUS_EXPLANATIONS: dict[str, str] = {
    STATUS_TEAM_NOT_FOUND: (
        "This team number is not in StratAI's teams table. That is a fact about\n"
        "    this database, not about FRC -- a real team that has never been synced\n"
        "    reads exactly this way."
    ),
    STATUS_EVENT_NOT_FOUND: (
        "This event key is not in StratAI's events table. Same caveat: it may be a\n"
        "    real event that has simply never been synced."
    ),
    STATUS_TEAM_DID_NOT_ATTEND: (
        "Team and event both exist, but match_teams does not roster this team at\n"
        "    this event. This never resolves: no compute run will ever produce this\n"
        "    row. If you scouted this team here, the roster is wrong, not the metrics."
    ),
    STATUS_METRICS_NOT_COMPUTED: (
        "Team is rostered at this event, but no metrics row has been written yet.\n"
        "    This resolves by running a compute for the event\n"
        "    (python -m data.orchestrator --event EVENT_KEY)."
    ),
}


def _rows(database: Database, query: str, params: Sequence[Any] = ()) -> list[tuple]:
    """Run one SELECT and return its rows. Copied from scripts/spot_check.py."""
    with database.cursor() as cursor:
        cursor.execute(query, tuple(params))
        return cursor.fetchall()


@dataclass(frozen=True)
class ContributingObservation:
    """One scouting_observations row that fed a team's defense/feeding profile."""

    match_key: str
    scout_identifier: str
    defense_rating: int | None
    feeding_rating: int | None
    notes: str | None
    source: str
    submitted_at: datetime
    raw_payload_id: int | None


def fetch_contributing_observations(
    database: Database, team_number: int, event_key: str
) -> list[ContributingObservation]:
    """Fetch every scouting observation behind one team's defense/feeding profile.

    Milestone 13's reader does not cover this: the API deliberately serves
    DefenseFeedingProfile, whose contributing_sources field names *sources*
    ("human_scout"), not the individual ratings the aggregation medianed. This
    milestone's brief needs the ratings themselves, so that a disputed score
    can be traced back into Milestone 8's aggregation.

    The column list, the filter, and ORDER BY submitted_at are copied verbatim
    from data.metrics.compute._fetch_team_scouting_observations, so this
    displays the observations *in the order the aggregation consumed them* --
    dispute a median and you are looking at exactly the list Milestone 8 saw.
    That function is private and sits on the compute path, which this
    read-only harness must not touch, so this is deliberate, cross-referenced
    duplication rather than an import -- the same accepted tradeoff
    data/metrics/history.py records for its play-order expression. Keep the two
    queries in step if either changes.
    """
    return [
        ContributingObservation(*row)
        for row in _rows(
            database,
            """
            SELECT match_key, scout_identifier, defense_rating, feeding_rating,
                   notes, source, submitted_at, raw_payload_id
            FROM scouting_observations
            WHERE team_number = %s AND event_key = %s
            ORDER BY submitted_at
            """,
            (team_number, event_key),
        )
    ]


def _lineage_note(database: Database, entity_type: str, entity_key: str) -> str:
    """Render an entity's raw-payload provenance. Copied from scripts/spot_check.py."""
    raw_ids = _rows(
        database,
        """
        SELECT raw_payload_id FROM canonical_lineage
        WHERE entity_type = %s AND entity_key = %s ORDER BY raw_payload_id
        """,
        (entity_type, entity_key),
    )
    if not raw_ids:
        return "    [no lineage recorded]"
    return f"    [raw_source_payloads.id: {', '.join(str(r[0]) for r in raw_ids)}]"


# --- value rendering ------------------------------------------------------
#
# None is never printed as "None". Every absent value renders as "--", and
# wherever the model has a *reason* for the absence (an insufficient_data flag,
# a matches_used below the stddev minimum) the reason is printed too -- a blank
# stddev must read as the model's documented contract, not as a bug.


def _decimal(value: float | None, width: int = 0, places: int = 1) -> str:
    return f"{'--':>{width}}" if value is None else f"{value:{width}.{places}f}"


def _rating_summary(
    score: float | None, count: int, agreement: float | None, insufficient: bool
) -> str:
    """One-line 'score (n=N a=A)' summary for the event overview table."""
    if insufficient:
        return f"{'--':>4} (n={count})"
    return f"{_decimal(score, 4, 1)} (n={count} a={_decimal(agreement, 0, 2)})"


def _rating_detail(
    label: str, score: float | None, count: int, agreement: float | None, insufficient: bool
) -> str:
    """Full detail line for one axis.

    Count and agreement always appear together, never one alone. They are
    orthogonal confidence axes -- DefenseFeedingProfile's own docstring makes
    the point that six scouts who all disagree is a real, low-confidence
    result, not the same thing as trusting one scout's opinion -- so showing
    either number without the other misleads.
    """
    plural = "" if count == 1 else "s"
    if insufficient:
        return f"    {label:9s} -- (insufficient data)   {count} observation{plural}   agreement --"
    return (
        f"    {label:9s} {_decimal(score, 4, 1)} / {MAX_RATING}   "
        f"{count} observation{plural}   agreement {_decimal(agreement, 0, 2)}"
    )


def _match_label(match_key: str, event_key: str) -> str:
    """Strip the event prefix from a match key: '2024casj_qm12' -> 'qm12'."""
    prefix = f"{event_key}_"
    return match_key[len(prefix):] if match_key.startswith(prefix) else match_key


def _sources(metrics: TeamMetrics) -> str:
    return ", ".join(metrics.defense_feeding.contributing_sources) or "(none)"


# --- reports --------------------------------------------------------------


def print_event_metrics(database: Database, event_key: str, *, verbose: bool = False) -> None:
    """Print one line per team with computed metrics at an event, to pick from."""
    print(f"\n=== METRICS AT EVENT {event_key} ===")
    header = _rows(
        database, "SELECT name, season FROM events WHERE event_key = %s", (event_key,)
    )
    if not header:
        print("  EVENT NOT IN DATABASE")
        return
    name, season = header[0]
    print(f"  {name}   season={season}")

    team_numbers = [
        row[0]
        for row in _rows(
            database,
            "SELECT team_number FROM team_metrics WHERE event_key = %s ORDER BY team_number",
            (event_key,),
        )
    ]
    print(f"  {len(team_numbers)} team(s) with a computed metrics row")
    if not team_numbers:
        print("\n  Nothing computed for this event yet. Run a compute for it:")
        print(f"    python -m data.orchestrator --event {event_key}")
        return

    print()
    print(f"  {'team':>6s}  {'matches':>9s}  {'avg':>6s}  {'consist':>7s}  {'reliab*':>7s}  |  "
          f"{'defense':18s}  {'feeding':18s}  sources")
    for team_number in team_numbers:
        lookup = look_up_team_metrics(database, team_number, event_key)
        if lookup.metrics is None:
            # Only reachable if the row was deleted between the listing query
            # and this read -- a concurrent compute dropping an off-roster team.
            print(f"  {team_number:>6d}  {lookup.status}")
            continue

        metrics = lookup.metrics
        scoring = metrics.scoring
        defense_feeding = metrics.defense_feeding
        matches = f"{scoring.matches_used}/{scoring.matches_scheduled}"
        print(
            f"  {team_number:>6d}  {matches:>9s}  {_decimal(scoring.average_score, 6, 1)}  "
            f"{_decimal(scoring.consistency_rating, 7, 1)}  {_decimal(scoring.reliability_score, 7, 1)}  |  "
            f"{_rating_summary(defense_feeding.defense_score, defense_feeding.defense_observation_count, defense_feeding.defense_agreement, defense_feeding.defense_insufficient_data):18s}  "
            f"{_rating_summary(defense_feeding.feeding_score, defense_feeding.feeding_observation_count, defense_feeding.feeding_agreement, defense_feeding.feeding_insufficient_data):18s}  "
            f"{_sources(metrics)}"
        )
    print()
    print(RELIABILITY_INTERIM_NOTE)
    if verbose:
        print(f"\n  event lineage:\n{_lineage_note(database, 'event', event_key)}")


def print_team_metrics(database: Database, team_number: int, event_key: str, *, verbose: bool = False) -> None:
    """Print one team's complete computed metrics, defense/feeding first.

    Defense and feeding lead because they are the only part a human can
    validate from memory -- scoring statistics are derived from match scores
    the validator would have to look up anyway, while a defense rating is
    exactly the thing they watched happen.
    """
    print(f"\n=== TEAM {team_number} @ {event_key} ===")
    lookup = look_up_team_metrics(database, team_number, event_key)

    if lookup.metrics is None:
        print(f"  NO METRICS: {lookup.status}")
        explanation = STATUS_EXPLANATIONS.get(lookup.status)
        if explanation:
            print(f"    {explanation}")
        return

    metrics = lookup.metrics
    print(f"  season={metrics.season}   computed_at: {metrics.computed_at}")

    _print_defense_feeding(database, metrics, verbose=verbose)
    _print_scoring(metrics)

    if verbose:
        print("\n  team_metrics lineage:")
        print(_lineage_note(database, ENTITY_TYPE_TEAM_METRICS, team_metrics_entity_key(team_number, event_key)))


def _print_defense_feeding(database: Database, metrics: TeamMetrics, *, verbose: bool) -> None:
    """Print the scouted half: both axes, their confidence, and every observation."""
    defense_feeding = metrics.defense_feeding
    print("\n  --- DEFENSE / FEEDING (scouted -- compare against your own assessment) ---")
    print(_rating_detail(
        "defense", defense_feeding.defense_score, defense_feeding.defense_observation_count,
        defense_feeding.defense_agreement, defense_feeding.defense_insufficient_data,
    ))
    print(_rating_detail(
        "feeding", defense_feeding.feeding_score, defense_feeding.feeding_observation_count,
        defense_feeding.feeding_agreement, defense_feeding.feeding_insufficient_data,
    ))
    print(f"    contributing_sources: {_sources(metrics)}")

    observations = fetch_contributing_observations(database, metrics.team_number, metrics.event_key)
    print(f"\n    contributing observations ({len(observations)}):")
    if not observations:
        print("      (none -- no scouting observations stored for this team at this event,")
        print("       so both ratings above are insufficient_data rather than low scores)")
        return

    for observation in observations:
        defense = "--" if observation.defense_rating is None else str(observation.defense_rating)
        feeding = "--" if observation.feeding_rating is None else str(observation.feeding_rating)
        line = (
            f"      {_match_label(observation.match_key, metrics.event_key):8s} "
            f"defense {defense:2s}  feeding {feeding:2s}   "
            f"scout={observation.scout_identifier:16s} source={observation.source:14s} "
            f"{observation.submitted_at:%Y-%m-%d %H:%M}"
        )
        if verbose:
            payload = "--" if observation.raw_payload_id is None else str(observation.raw_payload_id)
            line += f"   [raw_source_payloads.id: {payload}]"
        print(line)
        if observation.notes:
            print(f"        notes: {observation.notes}")


def _print_scoring(metrics: TeamMetrics) -> None:
    """Print the computed half: statistics derived from this team's match scores."""
    scoring = metrics.scoring
    print("\n  --- SCORING (computed from match scores -- never scouted) ---")
    print(f"    matches used         {scoring.matches_used} of {scoring.matches_scheduled} scheduled")
    print(f"    average score        {_decimal(scoring.average_score)}")
    print(f"    score stddev         {_decimal(scoring.score_stddev)}")
    print(f"    consistency          {_decimal(scoring.consistency_rating)} / 100")
    print(f"    reliability          {_decimal(scoring.reliability_score)} / 100"
          "   [INTERIM placeholder formula -- see below]")

    if None in (scoring.good_day_count, scoring.average_day_count, scoring.bad_day_count):
        print("    day classification   -- (not classified)")
    else:
        print(f"    day classification   {scoring.good_day_count} good / "
              f"{scoring.average_day_count} average / {scoring.bad_day_count} bad")

    # Explain a blank rather than leaving the reader to guess. ScoringProfile
    # fixes the rule: which fields are None is always determined by
    # matches_used, and both cases below are the model working as documented.
    if scoring.matches_used == 0:
        print("\n    Every value above is None because matches_used is 0 -- this team has no\n"
              "    stored score at this event. Not a computation failure.")
    elif scoring.matches_used < MIN_MATCHES_FOR_STDDEV:
        print(f"\n    stddev, consistency, reliability and the day counts are None because\n"
              f"    matches_used is {scoring.matches_used}, below MIN_MATCHES_FOR_STDDEV "
              f"({MIN_MATCHES_FOR_STDDEV}).\n"
              f"    Variance is undefined for one sample. Not a computation failure.")

    print()
    print(RELIABILITY_INTERIM_NOTE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only report of computed StratAI team metrics, for manual human validation.",
    )
    parser.add_argument("--event", action="append", default=[], metavar="EVENT_KEY",
                        help="Print every team with computed metrics at this event. Repeatable. "
                             "Also scopes --team.")
    parser.add_argument("--team", action="append", default=[], type=int, metavar="TEAM_NUMBER",
                        help="Print one team's full metrics report, at every --event given. Repeatable.")
    parser.add_argument("--verbose", action="store_true",
                        help="Also print raw_source_payloads provenance for observations and metrics.")
    args = parser.parse_args(argv)

    if not args.event:
        if args.team:
            parser.error("--team requires --event: metrics are keyed by the (team, event) pair")
        parser.error("nothing to report: pass --event, optionally with --team")

    database = Database(DatabaseConfig(Settings().database_url))

    print(BANNER)
    for event_key in args.event:
        print_event_metrics(database, event_key, verbose=args.verbose)
    for team_number in args.team:
        for event_key in args.event:
            print_team_metrics(database, team_number, event_key, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
