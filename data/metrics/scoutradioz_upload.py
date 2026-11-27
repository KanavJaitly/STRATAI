"""In-app ScoutRadioz CSV upload: check and preview a file, then import it on confirmation (audit 2026-11-26, WS8).

The import itself is data.metrics.scoutradioz.import_scoutradioz_csv, unchanged: raw landing, staging, the shared
reference checks, loading, lineage and the run record are exactly the script path's. This module adds what a web
upload needs in front of it:

1. **File checks.** UTF-8 text (a byte-order mark is accepted), no NUL bytes, at most MAX_UPLOAD_BYTES and MAX_ROWS,
   a header with ScoutRadioz's own export columns, no repeated column names, and the approved mapping's columns.
2. **The approved mapping.** The column mapping comes from data/metrics/scoutradioz_mappings.py for the file's
   season. A season without one is refused, never guessed.
3. **Per-row preview.** Every data row gets one status, and a bad row never stops the others:
   - `accepted`: new, valid, and references a match, team and event StratAI has;
   - `rejected`: not a valid observation (reason given: columns, team key, time, rating, blank scout, another
     event, another team's export, a match or team StratAI does not have, extra cells);
   - `excluded`: the mapping says the row expresses no rating (2026: defense 0 = "played no defense");
   - `duplicate`: the same match, team and scout as an earlier row of this file;
   - `already_imported`: stored before with the same ratings and notes (nothing to do);
   - `conflict`: stored before with DIFFERENT ratings or notes. Not imported: an upload never overwrites a stored
     observation (CLAUDE.md, "never overwrite historical data").
4. **Confirmation.** The import needs the sha256 of the file that was previewed, so what is imported is what was
   shown. Only `accepted` rows are passed on, in a temporary file deleted afterwards.
5. **Idempotent retries.** A retried confirmation finds every row it imported `already_imported` and writes
   nothing. A retry after a failure partway through is safe too: landing deduplicates by checksum, and loading
   resumes from the source watermark.

**Personal data.** The `scouter` column holds scouts' names. Nothing returned here contains it: rows report the row
number, match, team, mapped ratings, whether notes exist, and a status; a reason never quotes the scout. The names
are stored only where the script path stores them (scout_identifier, and the raw landing row).

**Team privacy.** Only exports from the caller's own ScoutRadioz organization (org_key `frc<team number>`) are
accepted, so one team's upload cannot record observations under another team's organization.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data.clients.schemas import ScoutRadiozMatchScoutingRow
from data.metrics.normalizer import normalize_scoutradioz_observation
from data.metrics.scoutradioz import (
    SOURCE_SCOUTRADIOZ,
    ScoutRadiozFieldMapping,
    _row_expresses_no_rating,
    import_scoutradioz_csv,
    map_scoutradioz_row_to_observation_payload,
)
from data.metrics.scoutradioz_mappings import approved_mapping, describe
from data.metrics.submission import PayloadValidationError
from database.connection import Database

MAX_UPLOAD_BYTES = 900_000  # under the API's 1 MiB request-body limit once the text is wrapped in JSON
MAX_ROWS = 5_000
REQUIRED_COLUMNS: tuple[str, ...] = tuple(ScoutRadiozMatchScoutingRow.model_fields)

ACCEPTED, REJECTED, EXCLUDED = "accepted", "rejected", "excluded"
DUPLICATE, ALREADY_IMPORTED, CONFLICT = "duplicate", "already_imported", "conflict"
STATUSES = (ACCEPTED, REJECTED, EXCLUDED, DUPLICATE, ALREADY_IMPORTED, CONFLICT)


class UploadRefused(ValueError):
    """The file as a whole cannot be imported. `code` is stable; the message is safe to show (it names no scout)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RowResult:
    row: int  # the CSV line number: the header is row 1
    status: str
    reason: str | None = None
    match_key: str | None = None
    team_number: int | None = None
    defense_rating: int | None = None
    feeding_rating: int | None = None
    has_notes: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "status": self.status, "reason": self.reason, "match_key": self.match_key,
                "team_number": self.team_number, "defense_rating": self.defense_rating,
                "feeding_rating": self.feeding_rating, "has_notes": self.has_notes}


@dataclass
class UploadPreview:
    file_sha256: str
    filename: str | None
    event_key: str
    season: int
    mapping: ScoutRadiozFieldMapping
    fieldnames: list[str]
    rows: list[RowResult]
    accepted_raw: list[dict[str, str]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        tally = collections.Counter(r.status for r in self.rows)
        return {"rows": len(self.rows), **{status: tally.get(status, 0) for status in STATUSES}}

    def as_dict(self) -> dict[str, Any]:
        return {"file_sha256": self.file_sha256, "filename": self.filename, "event_key": self.event_key,
                "season": self.season, "mapping": describe(self.mapping), "counts": self.counts(),
                "rows": [r.as_dict() for r in self.rows]}


def _decode(content: bytes) -> str:
    if not content.strip():
        raise UploadRefused("empty_file", "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRefused("file_too_large", f"The file is larger than {MAX_UPLOAD_BYTES:,} bytes; split it by event.")
    if b"\x00" in content:
        raise UploadRefused("not_a_csv", "The file is not a text CSV (it contains binary data).")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadRefused("not_a_csv", "The file is not UTF-8 text. Export it from ScoutRadioz as CSV.") from None


def _scrub(reason: str, scouter: str | None) -> str:
    """A reason with the scout's name removed, in case a validation message ever quoted it."""
    return reason.replace(scouter, "[scout]") if scouter else reason


def _existing(database: Database, event_key: str) -> dict[tuple[str, int, str], tuple[Any, Any, Any]]:
    with database.cursor() as cursor:
        cursor.execute("SELECT match_key, team_number, scout_identifier, defense_rating, feeding_rating, notes "
                       "FROM scouting_observations WHERE event_key = %s AND source = %s", (event_key, SOURCE_SCOUTRADIOZ))
        return {(m, t, s): (d, f, n) for m, t, s, d, f, n in cursor.fetchall()}


def _references(database: Database, event_key: str, team_numbers: set[int]) -> tuple[bool, set[str], set[int]]:
    """The same existence facts check_scouting_observation_references tests per row, fetched once for the file."""
    with database.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM events WHERE event_key = %s)", (event_key,))
        event_exists = bool(cursor.fetchone()[0])
        cursor.execute("SELECT match_key FROM matches WHERE event_key = %s", (event_key,))
        matches = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT team_number FROM teams WHERE team_number = ANY(%s)", (sorted(team_numbers),))
        teams = {row[0] for row in cursor.fetchall()}
    return event_exists, matches, teams


def preview_upload(database: Database, content: bytes, *, team_number: int,
                   filename: str | None = None) -> UploadPreview:
    """Check a ScoutRadioz CSV export and say, row by row, what importing it would do. Writes nothing."""
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        raise UploadRefused("not_a_csv", "The file has no header row.")
    repeated = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
    if repeated:
        raise UploadRefused("invalid_header", f"Column names appear more than once: {', '.join(repeated)}.")
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise UploadRefused("invalid_header", "This is not a ScoutRadioz match-scouting export: missing column(s) "
                                              f"{', '.join(missing)}.")
    raw_rows = []
    for raw in reader:
        raw_rows.append(raw)
        if len(raw_rows) > MAX_ROWS:
            raise UploadRefused("too_many_rows", f"The file has more than {MAX_ROWS:,} rows; split it by event.")
    if not raw_rows:
        raise UploadRefused("empty_file", "The file has a header but no data rows.")

    parsed_rows: list[tuple[int, dict[str, str], ScoutRadiozMatchScoutingRow | None, str | None]] = []
    for row_number, raw in enumerate(raw_rows, start=2):
        if None in raw:  # DictReader files cells beyond the header under the key None
            parsed_rows.append((row_number, raw, None, "The row has more cells than the header has columns."))
            continue
        try:
            parsed_rows.append((row_number, raw, ScoutRadiozMatchScoutingRow.model_validate(raw), None))
        except ValueError as exc:
            fields = sorted({str(e["loc"][0]) for e in getattr(exc, "errors", lambda: [])()} or {"row"})
            parsed_rows.append((row_number, raw, None, f"Invalid or missing value(s): {', '.join(fields)}."))

    events = collections.Counter(p.event_key for _, _, p, _ in parsed_rows if p is not None)
    if not events:
        raise UploadRefused("no_valid_rows", "No row matches the ScoutRadioz export columns.")
    event_key = events.most_common(1)[0][0]
    head = event_key[:4]
    season = int(head) if head.isdigit() else None
    mapping = approved_mapping(season)
    if mapping is None:
        raise UploadRefused("mapping_not_configured",
                            f"No approved column mapping exists for the {season or 'unknown'} scouting form, so its "
                            "ratings cannot be read. An administrator must establish and record one first "
                            "(data/metrics/scoutradioz_mappings.py).")
    for rating in (mapping.defense_rating, mapping.feeding_rating):
        if rating is not None and rating.column not in fieldnames:
            raise UploadRefused("invalid_header", f"The {season} mapping reads column {rating.column!r}, which this "
                                                  "file does not have.")

    team_keys = {p.team_key for _, _, p, _ in parsed_rows if p is not None}
    candidate_teams = {int(k[3:]) for k in team_keys if k.startswith("frc") and k[3:].isdigit()}
    event_exists, known_matches, known_teams = _references(database, event_key, candidate_teams)
    stored = _existing(database, event_key)
    own_org = f"frc{team_number}"

    results: list[RowResult] = []
    accepted_raw: list[dict[str, str]] = []
    seen: dict[tuple[str, int, str], int] = {}
    for row_number, raw, parsed, problem in parsed_rows:
        if parsed is None:
            results.append(RowResult(row_number, REJECTED, problem))
            continue
        result = RowResult(row_number, REJECTED, match_key=parsed.match_key)
        results.append(result)
        if parsed.org_key != own_org:
            result.reason = (f"Exported by another ScoutRadioz organization ({parsed.org_key}); only team "
                             f"{team_number}'s own exports are accepted.")
            continue
        if parsed.event_key != event_key:
            result.reason = f"Another event ({parsed.event_key}); this file is for {event_key}. Upload one event at a time."
            continue
        if _row_expresses_no_rating(raw, mapping):
            result.status, result.reason = EXCLUDED, "The form recorded no rating here (the mapping excludes it)."
            continue
        try:
            payload = map_scoutradioz_row_to_observation_payload(raw, parsed, mapping)
            observation = normalize_scoutradioz_observation(payload)
        except (ValueError, PayloadValidationError) as exc:
            result.reason = _scrub(str(exc), parsed.scouter)
            continue
        result.team_number = observation.team_number
        result.defense_rating, result.feeding_rating = observation.defense_rating, observation.feeding_rating
        result.has_notes = bool(observation.notes)
        if not event_exists:
            result.reason = f"Event {event_key} is not in StratAI's data yet."
            continue
        if observation.match_key not in known_matches:
            result.reason = f"Match {observation.match_key} is not in StratAI's data for {event_key}."
            continue
        if observation.team_number not in known_teams:
            result.reason = f"Team {observation.team_number} is not in StratAI's data."
            continue
        key = (observation.match_key, observation.team_number, observation.scout_identifier)
        if key in seen:
            result.status, result.reason = DUPLICATE, f"Same match, team and scout as row {seen[key]}; that row is used."
            continue
        seen[key] = row_number
        if key in stored:
            same = stored[key] == (observation.defense_rating, observation.feeding_rating, observation.notes)
            result.status = ALREADY_IMPORTED if same else CONFLICT
            result.reason = ("Already imported with the same values." if same else
                             "Already stored with different values; an upload never overwrites a stored observation.")
            continue
        result.status, result.reason = ACCEPTED, None
        accepted_raw.append(raw)

    return UploadPreview(file_sha256=hashlib.sha256(content).hexdigest(), filename=filename, event_key=event_key,
                         season=season, mapping=mapping, fieldnames=fieldnames, rows=results,
                         accepted_raw=accepted_raw)


def _not_loaded(source_object_id: str, reason: str) -> dict[str, Any]:
    """A row staging skipped, without the scout: source_object_id is "match:team:scout_identifier"."""
    match_key, _, rest = source_object_id.partition(":")
    team, _, scout = rest.partition(":")
    return {"match_key": match_key, "team_number": int(team) if team.isdigit() else None,
            "reason": reason.replace(scout, "[scout]") if scout else reason}


def import_upload(database: Database, content: bytes, *, team_number: int, expected_sha256: str,
                  filename: str | None = None, recompute_metrics: bool = True) -> dict[str, Any]:
    """Import the accepted rows of a previewed file. Refuses a file other than the one previewed (by sha256)."""
    preview = preview_upload(database, content, team_number=team_number, filename=filename)
    if preview.file_sha256 != expected_sha256:
        raise UploadRefused("file_changed", "This is not the file that was previewed. Preview it again.")
    outcome: dict[str, Any] = {"run_id": None, "landed": 0, "loaded": 0, "not_loaded": [], "metrics_recomputed": False}
    if preview.accepted_raw:
        handle, temp_name = tempfile.mkstemp(suffix=".csv", prefix="stratai_upload_")
        try:
            with os.fdopen(handle, "w", newline="", encoding="utf-8") as out:
                writer = csv.DictWriter(out, fieldnames=preview.fieldnames)
                writer.writeheader()
                writer.writerows(preview.accepted_raw)
            result = import_scoutradioz_csv(Path(temp_name), preview.mapping, database=database)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        outcome.update(run_id=result.run_id, landed=result.landed, loaded=result.loaded,
                       not_loaded=[_not_loaded(s.source_object_id, s.reason) for s in result.skipped])
        if recompute_metrics and result.loaded:
            from data.metrics.compute import compute_event_team_metrics

            compute_event_team_metrics(preview.event_key, database=database)
            outcome["metrics_recomputed"] = True
    return {**preview.as_dict(), "import": outcome}


__all__ = ["ACCEPTED", "ALREADY_IMPORTED", "CONFLICT", "DUPLICATE", "EXCLUDED", "MAX_ROWS", "MAX_UPLOAD_BYTES",
           "REJECTED", "REQUIRED_COLUMNS", "STATUSES", "RowResult", "UploadPreview", "UploadRefused", "import_upload",
           "preview_upload"]
