"""P5-M8 / P5-M9 / DM1 human inputs: storage and workflow behind the STRATAI web app.

A person can do all of this through the API (api/routes/human_inputs.py) and the web app (frontend/), without
editing the database, code or seed files:
- upload a game manual;
- enter, review and approve a structured game specification;
- maintain team capability profiles;
- record DM1's review artifacts.

**What this module guarantees:**
- **No silent overwrite.**
  - Content is append-only (migration 0010). An edit is a new version, and only status and review metadata move
    forward.
  - The same PDF bytes for a season are the same manual (idempotent). Different bytes are a new manual version.
- **Validation through the existing frozen models only:** GameSpec, CapabilityIntake, Codebook, Coding,
  ActionFunctionMap, Rubric. No criterion is added, and P5-D13, the M8/M9 methodology and DM1's requirements are
  untouched.
- **Nothing becomes authoritative without a named person.**
  - A PDF upload validates nothing.
  - A spec is authoritative only once a reviewer approves it.
  - Codebooks, consensus codings, action maps and rubrics are `established` by a named person.
  - DM1 is never marked complete here. `dm1_status` reports what exists, and the done-means come only from the
    write-once records (scripts/phase5_done_means.py).
- **Point-in-time metadata.**
  - A season's `entry_started_at` is the creation time of its first spec draft: DM1's clock.
  - Every row records who and when.
- **No LLM** reads the manual or fills any field.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from data.design_reference import (
    Codebook,
    Coding,
    agreement,
    label_status,
    load_reference,
)
from data.game_spec import GameSpec
from database.connection import Database

MAX_MANUAL_BYTES = 100 * 1024 * 1024
PDF_MAGIC = b"%PDF-"
INTAKE_SOURCE, INTAKE_OBJECT_TYPE = "capability_intake", "team_profile"
ARTIFACT_KINDS = ("codebook", "coding", "consensus_coding", "action_function_map", "rubric", "mentor_review")
ESTABLISHABLE = {"codebook", "consensus_coding", "action_function_map", "rubric"}
MIN_PROFILES = 10  # P5-M9: at least 10 sample team profiles


class HumanInputError(ValueError):
    """A request that the workflow refuses: invalid content, a wrong state, or a missing prerequisite."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class MentorReview(BaseModel):
    """P5-M9 (c): a named mentor's review of the sample recommendations."""

    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    profiles_reviewed: list[str] = Field(min_length=1)
    notes: str = Field(min_length=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _require_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumanInputError("invalid_input", f"{field} must name a person")
    return value.strip()


def _rows(cursor) -> list[dict[str, Any]]:
    columns = [c.name for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# --- game manuals ------------------------------------------------------------------------------


def store_manual(database: Database, store_dir: Path, *, season: int, game_name: str, filename: str,
                 content: bytes, uploaded_by: str) -> tuple[dict[str, Any], bool]:
    """Keep the original PDF write-once under its sha256; returns (row, created). The same bytes for the same
    season are the same manual, so a re-upload returns the existing row unchanged."""
    uploaded_by = _require_name(uploaded_by, "uploaded_by")
    game_name = _require_name(game_name, "game_name")
    if season < 1992:
        raise HumanInputError("invalid_input", "season must be 1992 or later")
    if not content or len(content) > MAX_MANUAL_BYTES:
        raise HumanInputError("invalid_input", f"a manual must be 1 byte to {MAX_MANUAL_BYTES} bytes")
    if not content.startswith(PDF_MAGIC):
        raise HumanInputError("invalid_input", "the upload is not a PDF (missing the %PDF- header)")
    sha = hashlib.sha256(content).hexdigest()
    safe_name = Path(filename or "manual.pdf").name[:200] or "manual.pdf"
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM game_manuals WHERE season = %s AND content_sha256 = %s", (season, sha))
        existing = _rows(cursor)
    if existing:
        return existing[0], False
    path = Path(store_dir) / "game_manuals" / str(season) / f"{sha}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise HumanInputError("storage_integrity", f"{path} exists with different content")
    else:
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)  # atomic: a manual file is never half-written
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO game_manuals (season, game_name, filename, media_type, byte_size, content_sha256, "
            "storage_path, uploaded_by) VALUES (%s, %s, %s, 'application/pdf', %s, %s, %s, %s) "
            "ON CONFLICT (season, content_sha256) DO NOTHING RETURNING *",
            (season, game_name, safe_name, len(content), sha, str(path), uploaded_by))
        created = _rows(cursor)
        if not created:  # a concurrent identical upload won
            cursor.execute("SELECT * FROM game_manuals WHERE season = %s AND content_sha256 = %s", (season, sha))
            return _rows(cursor)[0], False
    return created[0], True


def list_manuals(database: Database, season: int | None = None) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        if season is None:
            cursor.execute("SELECT * FROM game_manuals ORDER BY season DESC, uploaded_at, id")
        else:
            cursor.execute("SELECT * FROM game_manuals WHERE season = %s ORDER BY uploaded_at, id", (season,))
        return _rows(cursor)


def manual_file(database: Database, manual_id: int) -> tuple[dict[str, Any], bytes]:
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM game_manuals WHERE id = %s", (manual_id,))
        rows = _rows(cursor)
    if not rows:
        raise HumanInputError("not_found", f"no manual {manual_id}")
    data = Path(rows[0]["storage_path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != rows[0]["content_sha256"]:
        raise HumanInputError("storage_integrity", f"manual {manual_id}'s file no longer matches its sha256")
    return rows[0], data


# --- structured game specifications -----------------------------------------------------------------


def _season_clock(cursor, season: int) -> datetime:
    cursor.execute("SELECT min(entry_started_at) FROM game_spec_versions WHERE season = %s", (season,))
    first = cursor.fetchone()[0]
    return first or _now()


def _validate_spec(spec_json: dict[str, Any], season: int, created_by: str, started: datetime,
                   now: datetime) -> tuple[dict[str, Any], bool, list[dict[str, Any]], str | None]:
    """Fill the point-in-time source fields the server owns, then validate with GameSpec as it stands."""
    filled = json.loads(json.dumps(spec_json))
    filled["season"] = season
    source = dict(filled.get("source") or {})
    source.update({"entered_by": created_by, "entry_started_at": started.isoformat(),
                   "entry_completed_at": now.isoformat(), "llm_used": False})
    filled["source"] = source
    try:
        spec = GameSpec.model_validate(filled)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return filled, False, errors, None
    return spec.model_dump(mode="json"), True, [], spec.sha256()


def save_spec_draft(database: Database, *, season: int, spec_json: dict[str, Any], created_by: str,
                    manual_id: int | None = None, based_on_id: int | None = None) -> dict[str, Any]:
    """A new immutable version in `draft`. An incomplete spec is kept, with its validation errors listed."""
    created_by = _require_name(created_by, "created_by")
    if not isinstance(spec_json, dict):
        raise HumanInputError("invalid_input", "spec_json must be an object")
    with database.cursor() as cursor:
        if manual_id is not None:
            cursor.execute("SELECT season FROM game_manuals WHERE id = %s", (manual_id,))
            row = cursor.fetchone()
            if row is None or row[0] != season:
                raise HumanInputError("invalid_input", f"manual {manual_id} is not a {season} manual")
        started, now = _season_clock(cursor, season), _now()
        filled, complete, errors, sha = _validate_spec(spec_json, season, created_by, started, now)
        cursor.execute("SELECT coalesce(max(version), 0) + 1 FROM game_spec_versions WHERE season = %s", (season,))
        version = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO game_spec_versions (season, version, spec_json, complete, validation_errors, spec_sha256, "
            "manual_id, based_on_id, status, created_by, created_at, entry_started_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s, %s) RETURNING *",
            (season, version, json.dumps(filled), complete, json.dumps(errors), sha, manual_id, based_on_id,
             created_by, now, started))
        return _rows(cursor)[0]


def _spec(cursor, spec_id: int) -> dict[str, Any]:
    cursor.execute("SELECT * FROM game_spec_versions WHERE id = %s FOR UPDATE", (spec_id,))
    rows = _rows(cursor)
    if not rows:
        raise HumanInputError("not_found", f"no spec version {spec_id}")
    return rows[0]


def submit_spec(database: Database, spec_id: int) -> dict[str, Any]:
    """draft -> awaiting_review, only when the spec is complete."""
    with database.cursor() as cursor:
        spec = _spec(cursor, spec_id)
        if spec["status"] != "draft":
            raise HumanInputError("invalid_state", f"spec {spec_id} is {spec['status']}, not draft")
        if not spec["complete"]:
            raise HumanInputError("spec_incomplete", "an incomplete spec cannot go to review",
                                  spec["validation_errors"])
        cursor.execute("UPDATE game_spec_versions SET status = 'awaiting_review', submitted_at = %s WHERE id = %s "
                       "RETURNING *", (_now(), spec_id))
        return _rows(cursor)[0]


def review_spec(database: Database, spec_id: int, *, reviewer: str, approve: bool, note: str = "") -> dict[str, Any]:
    """A named reviewer approves it, which supersedes the season's earlier approved version, or returns it to
    draft with a note."""
    reviewer = _require_name(reviewer, "reviewer")
    with database.cursor() as cursor:
        spec = _spec(cursor, spec_id)
        if spec["status"] != "awaiting_review":
            raise HumanInputError("invalid_state", f"spec {spec_id} is {spec['status']}, not awaiting_review")
        now = _now()
        if not approve:
            if not note.strip():
                raise HumanInputError("invalid_input", "returning a spec for changes needs a note")
            cursor.execute("UPDATE game_spec_versions SET status = 'draft', reviewed_by = %s, reviewed_at = %s, "
                           "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, note, spec_id))
            return _rows(cursor)[0]
        cursor.execute("UPDATE game_spec_versions SET status = 'superseded' WHERE season = %s AND status = "
                       "'approved'", (spec["season"],))
        cursor.execute("UPDATE game_spec_versions SET status = 'approved', reviewed_by = %s, reviewed_at = %s, "
                       "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, note or None, spec_id))
        return _rows(cursor)[0]


def list_specs(database: Database, season: int) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM game_spec_versions WHERE season = %s ORDER BY version", (season,))
        return _rows(cursor)


def approved_spec(database: Database, season: int) -> GameSpec | None:
    with database.cursor() as cursor:
        cursor.execute("SELECT spec_json FROM game_spec_versions WHERE season = %s AND status = 'approved'",
                       (season,))
        row = cursor.fetchone()
    return None if row is None else GameSpec.model_validate(row[0])


def season_workflow(database: Database, season: int) -> dict[str, Any]:
    """The season's state, as the web app shows it. Each source is kept distinct: the uploaded PDF, the
    human-entered/reviewed spec, and derived analysis."""
    manuals, specs = list_manuals(database, season), list_specs(database, season)
    latest = specs[-1] if specs else None
    approved = next((s for s in specs if s["status"] == "approved"), None)
    if latest is None:
        spec_state = "no_structured_spec"
    elif latest["status"] == "draft":
        spec_state = "structured_spec_incomplete" if not latest["complete"] else "draft_complete_not_submitted"
    else:
        spec_state = {"awaiting_review": "awaiting_human_review", "approved": "reviewed_approved",
                      "superseded": "superseded"}[latest["status"]]
    return {"season": season, "source_uploaded": bool(manuals), "manuals": len(manuals),
            "spec_versions": len(specs), "spec_state": spec_state,
            "approved_version": None if approved is None else approved["version"],
            "entry_started_at": None if not specs else min(s["entry_started_at"] for s in specs),
            "note": "Uploading the manual validates nothing: only a reviewer's approval makes a spec authoritative."}


# --- capability profiles ----------------------------------------------------------------------------


def _land_intake(database: Database, profile_key: str, payload: dict[str, Any]) -> int | None:
    """Raw first (P5-M9): the untouched form lands before it is validated."""
    from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter

    RawPayloadWriter(database).write(RawPayloadRecord(INTAKE_SOURCE, INTAKE_OBJECT_TYPE, profile_key, payload))
    with database.cursor() as cursor:
        cursor.execute("SELECT max(id) FROM raw_source_payloads WHERE source = %s AND source_object_type = %s "
                       "AND source_object_id = %s", (INTAKE_SOURCE, INTAKE_OBJECT_TYPE, profile_key))
        return cursor.fetchone()[0]


def _validated_profile(profile_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    from ml.gameanalysis.capability import CapabilityIntake

    body = {**payload, "profile_id": profile_key, "submitted_at": _now().isoformat()}
    try:
        return CapabilityIntake.model_validate(body).model_dump(mode="json")
    except ValidationError as exc:
        raise HumanInputError("invalid_input", "the profile does not satisfy the M9 intake fields",
                              [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                               for e in exc.errors()]) from exc


def _latest_profile(cursor, profile_key: str) -> dict[str, Any] | None:
    cursor.execute("SELECT * FROM capability_profiles WHERE profile_key = %s ORDER BY version DESC LIMIT 1 "
                   "FOR UPDATE", (profile_key,))
    rows = _rows(cursor)
    return rows[0] if rows else None


def save_profile(database: Database, *, profile_key: str, payload: dict[str, Any], created_by: str,
                 new: bool) -> dict[str, Any]:
    """Create (new=True) or edit, which adds a new version and supersedes the previous one. Archived profiles are
    read-only."""
    created_by = _require_name(created_by, "created_by")
    profile_key = _require_name(profile_key, "profile_key")
    raw_id = _land_intake(database, profile_key, {**payload, "profile_id": profile_key})
    valid = _validated_profile(profile_key, payload)
    with database.cursor() as cursor:
        latest = _latest_profile(cursor, profile_key)
        if new and latest is not None:
            raise HumanInputError("conflict", f"profile {profile_key!r} already exists; edit it instead")
        if not new and latest is None:
            raise HumanInputError("not_found", f"no profile {profile_key!r}")
        if latest is not None and latest["status"] == "archived":
            raise HumanInputError("invalid_state", f"profile {profile_key!r} is archived")
        if latest is not None:
            cursor.execute("UPDATE capability_profiles SET status = 'superseded' WHERE id = %s", (latest["id"],))
        cursor.execute(
            "INSERT INTO capability_profiles (profile_key, version, payload, raw_payload_id, based_on_id, status, "
            "created_by) VALUES (%s, %s, %s, %s, %s, 'active', %s) RETURNING *",
            (profile_key, 1 if latest is None else latest["version"] + 1, json.dumps(valid), raw_id,
             None if latest is None else latest["id"], created_by))
        return _rows(cursor)[0]


def duplicate_profile(database: Database, *, profile_key: str, new_key: str, created_by: str) -> dict[str, Any]:
    with database.cursor() as cursor:
        latest = _latest_profile(cursor, profile_key)
    if latest is None:
        raise HumanInputError("not_found", f"no profile {profile_key!r}")
    payload = {k: v for k, v in latest["payload"].items() if k not in ("profile_id", "submitted_at")}
    return save_profile(database, profile_key=new_key, payload=payload, created_by=created_by, new=True)


def archive_profile(database: Database, *, profile_key: str, archived_by: str) -> dict[str, Any]:
    _require_name(archived_by, "archived_by")
    with database.cursor() as cursor:
        latest = _latest_profile(cursor, profile_key)
        if latest is None:
            raise HumanInputError("not_found", f"no profile {profile_key!r}")
        if latest["status"] != "active":
            raise HumanInputError("invalid_state", f"profile {profile_key!r} is {latest['status']}")
        cursor.execute("UPDATE capability_profiles SET status = 'archived' WHERE id = %s RETURNING *", (latest["id"],))
        return _rows(cursor)[0]


def list_profiles(database: Database, include_archived: bool = False) -> list[dict[str, Any]]:
    """The latest version of each profile."""
    with database.cursor() as cursor:
        cursor.execute("SELECT DISTINCT ON (profile_key) * FROM capability_profiles ORDER BY profile_key, version DESC")
        rows = _rows(cursor)
    return [r for r in rows if include_archived or r["status"] == "active"]


def profile_history(database: Database, profile_key: str) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM capability_profiles WHERE profile_key = %s ORDER BY version", (profile_key,))
        return _rows(cursor)


# --- DM1 artifacts --------------------------------------------------------------------------------


def _artifacts(cursor, kind: str, season: int, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM human_review_artifacts WHERE kind = %s AND season = %s"
    params: list[Any] = [kind, season]
    if status is not None:
        sql += " AND status = %s"
        params.append(status)
    cursor.execute(sql + " ORDER BY created_at, id", params)
    return _rows(cursor)


def established(database: Database, kind: str, season: int) -> dict[str, Any] | None:
    with database.cursor() as cursor:
        rows = _artifacts(cursor, kind, season, "established")
    return rows[-1] if rows else None


def latest_codings(database: Database, season: int) -> list[dict[str, Any]]:
    """Each coder's latest submitted independent coding, in order of each coder's first submission."""
    with database.cursor() as cursor:
        rows = _artifacts(cursor, "coding", season, "submitted")
    by_coder: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_coder[row["author"]] = row
    return sorted(by_coder.values(), key=lambda r: min(x["created_at"] for x in rows if x["author"] == r["author"]))


def _validate_artifact(database: Database, kind: str, season: int, author: str,
                       payload: dict[str, Any]) -> dict[str, Any]:
    from ml.gameanalysis.capability import Rubric
    from ml.gameanalysis.rules_p5d13 import ActionFunctionMap

    def codebook() -> Codebook:
        row = established(database, "codebook", season)
        if row is None:
            raise HumanInputError("prerequisite_missing", "establish the season's codebook first")
        return Codebook.model_validate(row["payload"])

    try:
        if kind == "codebook":
            return Codebook.model_validate({**payload, "authored_by": author}).model_dump(mode="json")
        if kind in ("coding", "consensus_coding"):
            book = codebook()
            coder = author if kind == "coding" else "consensus"
            coding = Coding.model_validate({**payload, "coder": coder, "codebook_sha256": book.sha256()})
            rows = [e.row_id for e in load_reference()]
            if sorted(coding.labels) != rows:
                raise HumanInputError("invalid_input", f"a coding must label every one of the {len(rows)} "
                                                       "curated reference rows (an empty list is allowed)")
            unknown = {f for fs in coding.labels.values() for f in fs} - set(book.functions)
            if unknown:
                raise HumanInputError("invalid_input", f"functions outside the codebook: {sorted(unknown)}")
            if kind == "consensus_coding" and len({c["author"] for c in latest_codings(database, season)}) < 2:
                raise HumanInputError("prerequisite_missing", "a consensus follows two independent codings")
            return coding.model_dump(mode="json")
        if kind == "action_function_map":
            book = codebook()
            amap = ActionFunctionMap.model_validate({**payload, "authored_by": author,
                                                     "codebook_sha256": book.sha256()})
            unknown = {f for fs in amap.mapping.values() for f in fs} - set(book.functions)
            if unknown:
                raise HumanInputError("invalid_input", f"functions outside the codebook: {sorted(unknown)}")
            return amap.model_dump(mode="json")
        if kind == "rubric":
            return Rubric.model_validate({**payload, "authored_by": author, "season": season}).model_dump(mode="json")
        if kind == "mentor_review":
            return MentorReview.model_validate({**payload, "reviewer": author}).model_dump(mode="json")
    except ValidationError as exc:
        raise HumanInputError("invalid_input", f"the {kind} does not satisfy its model",
                              [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                               for e in exc.errors()]) from exc
    raise HumanInputError("invalid_input", f"unknown artifact kind {kind!r}")


def submit_artifact(database: Database, *, kind: str, season: int, author: str,
                    payload: dict[str, Any]) -> dict[str, Any]:
    """A new immutable version by this author; their earlier submitted version of the same kind is superseded."""
    if kind not in ARTIFACT_KINDS:
        raise HumanInputError("invalid_input", f"kind must be one of {ARTIFACT_KINDS}")
    author = _require_name(author, "author")
    valid = _validate_artifact(database, kind, season, author, payload)
    with database.cursor() as cursor:
        cursor.execute("SELECT coalesce(max(version), 0) + 1 FROM human_review_artifacts WHERE kind = %s AND season = %s "
                       "AND author = %s", (kind, season, author))
        version = cursor.fetchone()[0]
        cursor.execute("UPDATE human_review_artifacts SET status = 'superseded' WHERE kind = %s AND season = %s AND author = %s "
                       "AND status = 'submitted'", (kind, season, author))
        cursor.execute(
            "INSERT INTO human_review_artifacts (kind, season, author, version, payload, payload_sha256, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'submitted') RETURNING *",
            (kind, season, author, version, json.dumps(valid), hashlib.sha256(_canonical(valid)).hexdigest()))
        return _rows(cursor)[0]


def establish_artifact(database: Database, artifact_id: int, *, established_by: str, note: str = "") -> dict[str, Any]:
    """A named person establishes a submitted codebook, consensus coding, action map or rubric. The previously
    established one of that kind and season is superseded."""
    established_by = _require_name(established_by, "established_by")
    with database.cursor() as cursor:
        cursor.execute("SELECT * FROM human_review_artifacts WHERE id = %s FOR UPDATE", (artifact_id,))
        rows = _rows(cursor)
        if not rows:
            raise HumanInputError("not_found", f"no artifact {artifact_id}")
        artifact = rows[0]
        if artifact["kind"] not in ESTABLISHABLE:
            raise HumanInputError("invalid_state", f"a {artifact['kind']} is not established by sign-off")
        if artifact["status"] != "submitted":
            raise HumanInputError("invalid_state", f"artifact {artifact_id} is {artifact['status']}")
        cursor.execute("UPDATE human_review_artifacts SET status = 'superseded' WHERE kind = %s AND season = %s AND status = "
                       "'established'", (artifact["kind"], artifact["season"]))
        cursor.execute("UPDATE human_review_artifacts SET status = 'established', established_by = %s, established_at = %s, "
                       "note = %s WHERE id = %s RETURNING *", (established_by, _now(), note or None, artifact_id))
        return _rows(cursor)[0]


def list_artifacts(database: Database, season: int, kind: str | None = None) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        if kind is None:
            cursor.execute("SELECT * FROM human_review_artifacts WHERE season = %s ORDER BY kind, created_at, id", (season,))
        else:
            cursor.execute("SELECT * FROM human_review_artifacts WHERE season = %s AND kind = %s ORDER BY created_at, id",
                           (season, kind))
        return _rows(cursor)


def kappa_status(database: Database, season: int) -> dict[str, Any]:
    """Codebook agreement (P5-D13 (5)) between the first two coders' latest independent codings."""
    book_row = established(database, "codebook", season)
    codings = latest_codings(database, season)
    if book_row is None or len(codings) < 2:
        return {"state": "awaiting_codings", "coders": [c["author"] for c in codings],
                "needed": "an established codebook and two independent codings"}
    book = Codebook.model_validate(book_row["payload"])
    first, second = (Coding.model_validate(c["payload"]) for c in codings[:2])
    if first.codebook_sha256 != book.sha256() or second.codebook_sha256 != book.sha256():
        return {"state": "stale_codings", "needed": "codings against the currently established codebook"}
    result = agreement(book, first, second)
    return {"state": "computed", "coders": [first.coder, second.coder], **result, "status": label_status(result)}


# --- recommendations (P5-M9) and DM1 status -------------------------------------------------------------


def recommendation_for(database: Database, profile_key: str, season: int) -> dict[str, Any]:
    """The existing deterministic M9 output (ml.gameanalysis.capability.recommend) for the profile's latest version.
    It needs the season's established rubric. Candidate archetypes come from P5-D13's action map when an approved
    spec, an established codebook and an established map exist; otherwise no archetype is a candidate, and that is
    said."""
    from ml.gameanalysis.capability import CapabilityIntake, Rubric, recommend
    from ml.gameanalysis.rules_p5d13 import ActionFunctionMap, candidate_archetypes

    with database.cursor() as cursor:
        latest = _latest_profile(cursor, profile_key)
    if latest is None:
        raise HumanInputError("not_found", f"no profile {profile_key!r}")
    rubric_row = established(database, "rubric", season)
    if rubric_row is None:
        raise HumanInputError("prerequisite_missing", f"no established {season} feasibility rubric yet")
    spec, book_row, map_row = (approved_spec(database, season), established(database, "codebook", season),
                               established(database, "action_function_map", season))
    if spec is not None and book_row is not None and map_row is not None:
        names = [c["archetype"] for c in candidate_archetypes(
            spec, Codebook.model_validate(book_row["payload"]), ActionFunctionMap.model_validate(map_row["payload"]))]
        candidates_note = "candidate archetypes from P5-D13's action map over the approved spec"
    else:
        names, candidates_note = [], ("no candidate archetypes yet: an approved spec, an established codebook and an "
                                      "established action map are all required (P5-D13)")
    result = recommend(CapabilityIntake.model_validate(latest["payload"]), Rubric.model_validate(rubric_row["payload"]),
                       names)
    return {**result, "profile_version": latest["version"], "season": season, "candidate_archetypes": names,
            "candidates_note": candidates_note,
            "limitations": ["the rubric is human-authored and deterministic; it is not fit to outcomes",
                            "the curated design dataset has no resource, cost or complexity data (P5-D10)"]}


def dm1_status(database: Database, season: int) -> dict[str, Any]:
    """What DM1 still needs, by artifact. Informational only: DM1's done-means comes from the write-once records
    and is never set here."""
    workflow, catalog = season_workflow(database, season), []
    with database.cursor() as cursor:
        cursor.execute("SELECT season FROM game_spec_versions WHERE status = 'approved' AND season < %s ORDER BY 1",
                       (season,))
        catalog = [r[0] for r in cursor.fetchall()]
    kappa = kappa_status(database, season)
    profiles = list_profiles(database)
    reviews = [a for a in list_artifacts(database, season, "mentor_review") if a["status"] == "submitted"]

    def item(name: str, state: str, provided: bool, detail: Any = None) -> dict[str, Any]:
        return {"artifact": name, "state": state, "provided": provided, "detail": detail}

    def sign_off(kind: str) -> dict[str, Any]:
        row = established(database, kind, season)
        submitted = [a for a in list_artifacts(database, season, kind) if a["status"] == "submitted"]
        state = "established" if row else ("awaiting_sign_off" if submitted else "missing")
        return item(kind, state, row is not None,
                    None if row is None else {"by": row["established_by"], "at": row["established_at"]})

    consensus = sign_off("consensus_coding")
    items = [
        item("game_manual", "uploaded" if workflow["source_uploaded"] else "missing", workflow["source_uploaded"],
             "a source artifact only; it validates nothing"),
        item("game_spec", workflow["spec_state"], workflow["spec_state"] == "reviewed_approved", workflow),
        item("catalog_specs", "approved" if catalog else "missing", bool(catalog), {"seasons": catalog}),
        sign_off("codebook"),
        item("independent_codings", "submitted" if len(kappa.get("coders", [])) >= 2 else "incomplete",
             len(kappa.get("coders", [])) >= 2, {"coders": kappa.get("coders", [])}),
        item("codebook_agreement", kappa["state"], kappa["state"] == "computed",
             kappa.get("status") or kappa.get("needed")),
        consensus,
        sign_off("action_function_map"),
        sign_off("rubric"),
        item("team_profiles", "complete" if len(profiles) >= MIN_PROFILES else "incomplete",
             len(profiles) >= MIN_PROFILES, {"active": len(profiles), "required": MIN_PROFILES}),
        item("mentor_review", "recorded" if reviews else "missing", bool(reviews),
             None if not reviews else {"reviewer": reviews[-1]["author"]}),
    ]
    return {"season": season, "items": items, "inputs_ready": all(i["provided"] for i in items if i["artifact"] not in
                                                                    ("mentor_review", "game_manual")),
            "note": "DM1 is met only by the write-once dry-run, score and mentor-review records "
                    "(scripts/phase5_done_means.py), never by entered data alone."}


# --- export for the DM1 runner ------------------------------------------------------------------


def export_dm1_inputs(database: Database, reveal_season: int, out_dir: Path) -> dict[str, Path]:
    """Write the approved and established artifacts as the files scripts/phase5_dm1_dry_run.py reads. Refuses if
    any is missing."""
    from data.game_spec import write_catalog_manifest

    out_dir = Path(out_dir)
    spec = approved_spec(database, reveal_season)
    if spec is None:
        raise HumanInputError("prerequisite_missing", f"no approved {reveal_season} game spec")
    paths: dict[str, Path] = {"spec": out_dir / "spec.json", "catalog": out_dir / "catalog"}
    paths["catalog"].mkdir(parents=True, exist_ok=True)
    paths["spec"].write_text(spec.model_dump_json(), encoding="utf-8")
    with database.cursor() as cursor:
        cursor.execute("SELECT season, spec_json FROM game_spec_versions WHERE status = 'approved' AND season < %s",
                       (reveal_season,))
        catalog = cursor.fetchall()
    if not catalog:
        raise HumanInputError("prerequisite_missing", "no approved catalog spec before the reveal season")
    for season, body in catalog:
        (paths["catalog"] / f"{season}.json").write_text(GameSpec.model_validate(body).model_dump_json(),
                                                          encoding="utf-8")
    write_catalog_manifest(paths["catalog"])
    for kind, name in (("codebook", "codebook"), ("consensus_coding", "consensus"),
                       ("action_function_map", "action_map"), ("rubric", "rubric")):
        row = established(database, kind, reveal_season)
        if row is None:
            raise HumanInputError("prerequisite_missing", f"no established {kind}")
        paths[name] = out_dir / f"{name}.json"
        paths[name].write_text(json.dumps(row["payload"]), encoding="utf-8")
    codings = latest_codings(database, reveal_season)
    if len(codings) < 2:
        raise HumanInputError("prerequisite_missing", "two independent codings are required")
    for index, row in enumerate(codings[:2]):
        paths[f"coding_{index}"] = out_dir / f"coding_{index}.json"
        paths[f"coding_{index}"].write_text(json.dumps(row["payload"]), encoding="utf-8")
    profiles = list_profiles(database)
    if len(profiles) < MIN_PROFILES:
        raise HumanInputError("prerequisite_missing", f"at least {MIN_PROFILES} active team profiles are required")
    paths["profiles"] = out_dir / "profiles.json"
    paths["profiles"].write_text(json.dumps([p["payload"] for p in profiles]), encoding="utf-8")
    return paths
