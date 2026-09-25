"""Event/team lookups the ML API layer (Milestone 12) needs that Milestone 1's
own assembler does not otherwise expose.

Deliberately a separate, small module rather than importing
data.metrics.compute's own private _teams_at_event: this codebase's standing
rule is "additive only... do not modify Kanav's M3-M10 computation logic
without coordination", and promoting a private helper to public in that file
would be exactly such a modification for the sake of a different milestone's
convenience. The roster query itself is an 8-line DISTINCT lookup with
nothing to diverge from Phase 3's own copy -- a small, low-risk duplication
in the additive ml/ package rather than a change to Phase 3 code.
"""

from __future__ import annotations

from datetime import datetime

from database.connection import Database

__all__ = [
    "event_exists",
    "get_event_season",
    "get_match_event_and_scheduled_time",
    "list_teams_at_event",
]


def event_exists(database: Database, event_key: str) -> bool:
    """Whether event_key is a real, synced event -- used to give a genuine
    event-not-found response its own distinct code, rather than an empty
    roster looking identical to an unknown event."""
    with database.cursor() as cursor:
        cursor.execute("SELECT 1 FROM events WHERE event_key = %s", (event_key,))
        return cursor.fetchone() is not None


def get_event_season(database: Database, event_key: str) -> int | None:
    """event_key's own real season, or None if it does not exist -- used by
    the ad-hoc (non-match-based) prediction endpoints to build a real
    MatchFeatureRow.season rather than a fabricated placeholder value."""
    with database.cursor() as cursor:
        cursor.execute("SELECT season FROM events WHERE event_key = %s", (event_key,))
        row = cursor.fetchone()
    return row[0] if row is not None else None


def list_teams_at_event(database: Database, event_key: str) -> list[int]:
    """Every team rostered into at least one match at this event, ascending.

    Sourced from match_teams (always populated by a TBA sync), the same
    roster source data.metrics.compute._teams_at_event and
    data.metrics.history already rely on for the identical reason: it is the
    one roster source every synced event actually has, independent of
    whether Statbotics EPA was ever synced for it.
    """
    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT mt.team_number
            FROM match_teams mt
            JOIN matches m ON m.match_key = mt.match_key
            WHERE m.event_key = %s
            ORDER BY mt.team_number
            """,
            (event_key,),
        )
        return [row[0] for row in cursor.fetchall()]


def get_match_event_and_scheduled_time(database: Database, match_key: str) -> tuple[str, datetime | None] | None:
    """(event_key, scheduled_time) for a real match_key, or None if the
    match does not exist at all. scheduled_time itself may be None -- a
    genuinely real, valid state for a match TBA has not yet scheduled (see
    data.staging.validator's own TBA_UNPLAYED_ALLIANCE_SCORE documentation)
    -- callers needing a point-in-time as_of decide separately what to do
    with that case rather than this lookup silently choosing for them.
    """
    with database.cursor() as cursor:
        cursor.execute("SELECT event_key, scheduled_time FROM matches WHERE match_key = %s", (match_key,))
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0], row[1]
