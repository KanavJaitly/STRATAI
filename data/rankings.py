"""Event qualification-ranking ingestion and read-back.

Additive infrastructure, built to close a real gap Phase 4 Milestone 3 found
during its own Challenge step: no table, client model, or connector
anywhere in this codebase had ever landed a team's real final event
ranking, which is the ground truth Milestone 3's run_ranking_backtest (and
Milestone 5's ranking model) need to evaluate against anything real.
ml.backtest.harness's own module docstring records the original finding in
full.

This module closes it via TBA's own /event/{event_key}/rankings endpoint --
confirmed real and independently verified against TBA's live OpenAPI spec,
not assumed -- which is entirely separate from Statbotics, so it is buildable
and runnable regardless of whether Statbotics is up.

Deliberately no new canonical table. Rankings are landed through the
existing RawPayloadWriter (the same landing layer TBA events/teams/matches
already use, source="tba", object_type=OBJECT_TYPE_EVENT_RANKING) and read
back directly out of raw_source_payloads -- mirroring Milestone 2's own
precedent for dq_team_keys/surrogate_team_keys, which reads raw TBA match
payloads directly rather than adding a schema column for data only Phase 4
consumes. A dedicated event_rankings canonical table is real, legitimate
Phase 2/3-shaped infrastructure that a future milestone could still choose
to build; this module does not preempt that decision, it only unblocks
Phase 4's own immediate need with the smallest correct addition.
"""

from __future__ import annotations

import argparse
import sys
import time

from data.clients.tba import TBAClient
from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.pipeline import SOURCE_TBA
from data.staging.normalizer import parse_tba_team_number
from database.connection import Database, DatabaseConfig

__all__ = [
    "OBJECT_TYPE_EVENT_RANKING",
    "main",
    "read_final_ranks_for_season",
    "sync_event_rankings",
    "sync_season_rankings",
]

OBJECT_TYPE_EVENT_RANKING = "event_ranking"

DEFAULT_EVENT_DELAY_SECONDS = 0.5


def sync_event_rankings(event_key: str, *, database: Database, tba: TBAClient) -> bool:
    """Fetch and land one event's qualification ranking.

    Returns True if a new raw payload was landed (RawPayloadWriter's own
    checksum dedup means an unchanged ranking re-synced later lands
    nothing and returns False -- an idempotent re-run, the same guarantee
    every other object type in this pipeline already has).
    """
    response = tba.fetch_event_rankings(event_key)
    writer = RawPayloadWriter(database)
    return writer.write(RawPayloadRecord(
        source=SOURCE_TBA, source_object_type=OBJECT_TYPE_EVENT_RANKING,
        source_object_id=event_key, payload=response.raw,
    ))


def sync_season_rankings(
    season: int, *, database: Database, tba: TBAClient, delay_seconds: float = DEFAULT_EVENT_DELAY_SECONDS,
) -> dict[str, int]:
    """Sync rankings for every event of `season` already present in the
    canonical `events` table.

    Deliberately reads event_key from the already-synced `events` table
    rather than calling TBA's /events/{year} list again: sync_season (data.
    orchestrator) already applied the official-event-type filter once when
    those rows were loaded, so querying them back gives exactly the same
    event set for free, with one fewer TBA request and no risk of the two
    filters drifting apart.

    Returns {"events": N, "landed": M} -- N is how many events were
    considered, M is how many actually produced a new (non-duplicate) raw
    payload, mirroring sync_season's own summary shape.
    """
    with database.cursor() as cursor:
        cursor.execute("SELECT event_key FROM events WHERE season = %s ORDER BY event_key", (season,))
        event_keys = [row[0] for row in cursor.fetchall()]

    landed = 0
    for index, event_key in enumerate(event_keys):
        if sync_event_rankings(event_key, database=database, tba=tba):
            landed += 1
        if index + 1 < len(event_keys):
            time.sleep(delay_seconds)

    return {"events": len(event_keys), "landed": landed}


def read_final_ranks_for_season(database: Database, season: int) -> dict[str, dict[int, int]]:
    """Read back every landed ranking for `season` as {event_key:
    {team_number: rank}} -- exactly the shape ml.backtest.harness.
    run_ranking_backtest's final_ranks parameter expects.

    Reads the current raw payload directly (source="tba", object_type=
    OBJECT_TYPE_EVENT_RANKING, is_current), the same is_current + source +
    source_object_type convention every other reader of raw_source_payloads
    in this codebase already uses. An event with no landed ranking payload
    (never synced, or TBA returned null because it has no ranking yet) is
    simply absent from the returned mapping -- not an empty dict, which
    run_ranking_backtest's own "no entry means skip this event" contract
    already treats identically to a genuinely empty one, so no special
    casing is needed here.

    A team_key that fails to parse (never observed against real TBA data)
    is skipped for that one entry rather than aborting the whole event's
    ranking, the same defensive posture ml.dataset.builder._team_numbers_
    from_keys already takes for the same class of input.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.event_key, rsp.payload_json
            FROM events e
            JOIN raw_source_payloads rsp
              ON rsp.source = %s AND rsp.source_object_type = %s AND rsp.source_object_id = e.event_key
              AND rsp.is_current
            WHERE e.season = %s
            ORDER BY rsp.id
            """,
            (SOURCE_TBA, OBJECT_TYPE_EVENT_RANKING, season),
        )
        rows = cursor.fetchall()

    # ORDER BY rsp.id + last-one-wins below is belt-and-braces against the
    # (should-be-impossible, per RawPayloadWriter's own documented invariant)
    # case of more than one is_current row for the same event: deterministic
    # highest-id-wins, matching ml.dataset.builder's identical defensive
    # pattern for the same class of raw-payload read.
    final_ranks: dict[str, dict[int, int]] = {}
    for event_key, payload_json in rows:
        team_ranks = _parse_ranking_payload(payload_json)
        if team_ranks:
            final_ranks[event_key] = team_ranks

    return final_ranks


def _parse_ranking_payload(payload_json: object) -> dict[int, int]:
    """{team_number: rank} from one landed raw TBA ranking payload.

    Pure and database-free on purpose, split out of read_final_ranks_for_
    season specifically so this parsing logic is unit-testable without a
    live database -- the same reason ml.dataset.builder._parse_dq_and_
    surrogates is its own function rather than inlined into its caller.
    """
    if not isinstance(payload_json, dict):
        return {}
    rankings = payload_json.get("rankings")
    if not isinstance(rankings, list):
        return {}

    team_ranks: dict[int, int] = {}
    for entry in rankings:
        if not isinstance(entry, dict):
            continue
        team_key = entry.get("team_key")
        rank = entry.get("rank")
        if team_key is None or rank is None:
            continue
        try:
            team_number = parse_tba_team_number(team_key)
        except (AssertionError, TypeError):
            continue
        team_ranks[team_number] = rank
    return team_ranks


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m data.rankings --season YEAR [--season YEAR ...]`.

    Mirrors data.orchestrator's own construction (bare Settings(), same
    Database/DatabaseConfig wiring) so there is no second config or
    connection-setup convention for this additive module to maintain.
    """
    parser = argparse.ArgumentParser(
        description="Sync event qualification rankings (TBA) for one or more already-synced seasons.",
    )
    parser.add_argument("--season", type=int, action="append", required=True, dest="seasons",
                         help="A season whose already-synced events should get rankings synced. Repeatable.")
    parser.add_argument("--delay", type=float, default=DEFAULT_EVENT_DELAY_SECONDS, metavar="SECONDS",
                         help=f"Pause between events (default {DEFAULT_EVENT_DELAY_SECONDS}).")
    args = parser.parse_args(argv)

    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))

    with TBAClient(settings=settings) as tba:
        for season in args.seasons:
            result = sync_season_rankings(season, database=database, tba=tba, delay_seconds=args.delay)
            print(f"season {season}: {result['events']} event(s) considered, {result['landed']} ranking(s) landed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
