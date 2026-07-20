from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from psycopg.types.json import Jsonb

from database.connection import Database


def compute_payload_checksum(payload: Any) -> str:
    """Return a deterministic SHA-256 checksum for a JSON-serializable payload.

    The payload is canonicalized (sorted keys, no incidental whitespace) before
    hashing so identical data always produces the same checksum regardless of
    source-side key ordering or formatting.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class RawPayloadRecord:
    """A single raw payload fetched from an external source, prior to any transformation."""

    source: str
    source_object_type: str
    source_object_id: str
    payload: Any
    source_schema_version: str | None = None
    fetch_timestamp: datetime | None = None


@dataclass
class RawPayloadWriter:
    """Persists RawPayloadRecords into raw_source_payloads.

    Deduplicates on (source, source_object_type, source_object_id, payload_checksum):
    an identical payload is never reinserted, while a changed payload for the same
    object creates a new row and clears the prior row's is_current flag. This layer
    is intentionally source-agnostic so any connector (TBA, Statbotics, ScoutRadioz,
    or future sources) can reuse it without the landing layer knowing their schemas.
    """

    database: Database

    def write(self, record: RawPayloadRecord) -> bool:
        """Persist one raw payload. Returns True if a new row was inserted, False if it was an exact duplicate."""
        with self.database.cursor() as cursor:
            return self._write_with_cursor(record, cursor)

    def write_many(self, records: Iterable[RawPayloadRecord]) -> int:
        """Persist multiple raw payloads over a single shared connection.

        Records are committed one at a time so a failure partway through a large
        batch (e.g. a live-sync poll with hundreds of objects) does not roll back
        payloads already landed earlier in the same call.
        """
        inserted_count = 0
        with self.database.connection() as conn:
            for record in records:
                with conn.cursor() as cursor:
                    if self._write_with_cursor(record, cursor):
                        inserted_count += 1
                conn.commit()
        return inserted_count

    def _write_with_cursor(self, record: RawPayloadRecord, cursor: Any) -> bool:
        checksum = compute_payload_checksum(record.payload)
        fetch_timestamp = record.fetch_timestamp or datetime.now(timezone.utc)

        cursor.execute(
            """
            INSERT INTO raw_source_payloads (
                source, source_object_type, source_object_id,
                fetch_timestamp, payload_json, payload_checksum,
                schema_version, is_current
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (source, source_object_type, source_object_id, payload_checksum)
            DO NOTHING
            RETURNING id
            """,
            (
                record.source,
                record.source_object_type,
                record.source_object_id,
                fetch_timestamp,
                Jsonb(record.payload),
                checksum,
                record.source_schema_version,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            return False

        new_id = inserted[0]
        cursor.execute(
            """
            UPDATE raw_source_payloads
            SET is_current = FALSE
            WHERE source = %s AND source_object_type = %s AND source_object_id = %s AND id != %s
            """,
            (record.source, record.source_object_type, record.source_object_id, new_id),
        )
        return True
