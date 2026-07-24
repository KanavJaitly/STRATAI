"""Audit tracing: which raw landing payload produced which canonical row.

Every canonical row this pipeline writes is derived from exactly one raw
payload version in `raw_source_payloads`. That relationship is recorded here, in
the `canonical_lineage` table, rather than as a column on the canonical tables
themselves -- which keeps the canonical schema and the Milestone 7 repository
untouched, and makes lineage an append-only *history* instead of a single
last-writer pointer. Ask "where did this row come from" and the answer is every
payload version it was ever built from, plus the pipeline run that promoted
each one.

`entity_type` reuses the vocabulary already shared by
raw_source_payloads.source_object_type and source_watermarks.object_type
('event', 'team', 'match', 'team_event'), so the raw rows, the incremental
state, the quality issues, and the lineage all name the same thing the same way.
`match_teams` has no entity type of its own -- its rows are reconciled from a
match's roster, so they are traced through their parent match.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from data.staging.schemas import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
)
from database.connection import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineageEntry:
    """A claim that one canonical entity was built from one raw payload.

    Run-agnostic like QualityIssue: LineageStore stamps the pipeline_run_id at
    write time.
    """

    entity_type: str
    entity_key: str
    raw_payload_id: int
    source: str


@dataclass(frozen=True)
class LineageRecord:
    """A persisted lineage row, as read back for tracing."""

    entity_type: str
    entity_key: str
    raw_payload_id: int
    pipeline_run_id: int | None
    source: str
    loaded_at: datetime


def entity_key_of(entity: Any) -> str:
    """Render a staging entity's canonical natural key as lineage text.

    Mirrors the natural keys the canonical tables are keyed on, so a lineage row
    can be joined straight back to the row it describes: team_number for teams,
    event_key for events, match_key for matches, and the composite
    "<team_number>_<event_key>" for team_event_stats.
    """
    if isinstance(entity, StagingTeam):
        return str(entity.team_number)
    if isinstance(entity, StagingEvent):
        return entity.event_key
    if isinstance(entity, StagingMatch):
        return entity.match_key
    if isinstance(entity, StagingTeamEventStats):
        return f"{entity.team_number}_{entity.event_key}"
    raise TypeError(f"No lineage key defined for {type(entity).__name__}")


@dataclass
class LineageStore:
    """Reads and writes canonical_lineage."""

    database: Database

    def record(self, entries: Sequence[LineageEntry], pipeline_run_id: int | None = None) -> int:
        """Persist lineage for entities that were just loaded. Returns rows attempted.

        Idempotent: the unique index on (entity_type, entity_key,
        raw_payload_id) plus ON CONFLICT DO NOTHING means re-promoting the same
        payload -- which happens whenever a run reprocesses ground it already
        covered -- adds nothing and preserves the original row. The retained
        pipeline_run_id is therefore the run that *first* promoted that payload,
        the more useful audit fact than whichever run last re-promoted it.

        Should only be called after the load succeeded: a lineage row asserts
        that a canonical row exists and came from this payload.
        """
        if not entries:
            return 0

        with self.database.cursor() as cursor:
            for entry in entries:
                cursor.execute(
                    """
                    INSERT INTO canonical_lineage (
                        entity_type, entity_key, raw_payload_id, pipeline_run_id, source
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (entity_type, entity_key, raw_payload_id) DO NOTHING
                    """,
                    (entry.entity_type, entry.entity_key, entry.raw_payload_id, pipeline_run_id, entry.source),
                )

        logger.info("Recorded lineage for %d canonical entity version(s) in run %s", len(entries), pipeline_run_id)
        return len(entries)

    def trace(self, entity_type: str, entity_key: str) -> list[LineageRecord]:
        """Return every payload version a canonical entity was built from, oldest first.

        Ordered by raw_payload_id, which is the landing layer's insertion order,
        so the list reads as the entity's history and the last element is its
        current provenance.
        """
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT entity_type, entity_key, raw_payload_id, pipeline_run_id, source, loaded_at
                FROM canonical_lineage
                WHERE entity_type = %s AND entity_key = %s
                ORDER BY raw_payload_id
                """,
                (entity_type, entity_key),
            )
            return [LineageRecord(*row) for row in cursor.fetchall()]

    def latest(self, entity_type: str, entity_key: str) -> LineageRecord | None:
        """Return the most recent lineage record for an entity, or None if untraced."""
        history = self.trace(entity_type, entity_key)
        return history[-1] if history else None

    def trace_to_payload(self, entity_type: str, entity_key: str) -> tuple[int, dict[str, Any]] | None:
        """Resolve a canonical entity to the raw payload it currently comes from.

        Returns (raw_payload_id, payload_json) for its newest lineage record, or
        None when the entity has no lineage -- the one-call answer to "show me
        the source data behind this row".
        """
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT raw.id, raw.payload_json
                FROM canonical_lineage AS lineage
                JOIN raw_source_payloads AS raw ON raw.id = lineage.raw_payload_id
                WHERE lineage.entity_type = %s AND lineage.entity_key = %s
                ORDER BY raw.id DESC
                LIMIT 1
                """,
                (entity_type, entity_key),
            )
            row = cursor.fetchone()
        return None if row is None else (row[0], row[1])
