"""Phase 5 human-input workflows (P5-M8 / P5-M9 / DM1) over HTTP. The web app (frontend/) is built on these.

Every route is under `/human-inputs`. **Reads are open**, like every other endpoint.

**Writes need the `X-StratAI-Write-Token` header** to equal `Settings.human_inputs_write_token`. With no token
configured, every write is refused (`writes_disabled`, 403), so the default is closed. Every write also names the
person acting (`created_by`, `reviewer`, `author`, ...). Those names are recorded with the row; they are not an
identity system.

Storage and every rule live in data/human_inputs.py. Nothing here computes or approves anything by itself, and
DM1 is never marked complete through this API.

**Error codes:**
- `invalid_input` (422);
- `not_found` (404);
- `invalid_state`, `conflict`, `prerequisite_missing`, `spec_incomplete`, `storage_integrity` (409);
- `writes_disabled`, `write_not_authorized` (403);
- `unsupported_media_type` (415).
"""

from __future__ import annotations

import hmac
from http import HTTPStatus
from pathlib import Path as FsPath
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from api.contract import error_responses
from api.dependencies import get_database, get_settings
from api.errors import ApiError
# The write-token mechanism moved to api.routes.common by P7-M5 (the coach-input writes use it too); these names
# stay importable from here.
from api.routes.common import (
    CODE_WRITE_NOT_AUTHORIZED,
    CODE_WRITES_DISABLED,
    WRITE_TOKEN_HEADER,
    problems_suffix,
    require_writer,
)
from data import human_inputs as hi
from data.config import Settings
from database.connection import Database

# Every route can return 500 (P7-M1 (f)). A route whose input can fail validation also declares 422
# validation_error, through _errors / _READ_ERRORS on the route itself.
router = APIRouter(prefix="/human-inputs", tags=["human inputs (P5-M8/M9, DM1)"],
                   responses=error_responses({}, validates_input=False))

CODE_UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
_STATUS = {"invalid_input": HTTPStatus.UNPROCESSABLE_ENTITY, "not_found": HTTPStatus.NOT_FOUND,
           "invalid_state": HTTPStatus.CONFLICT, "conflict": HTTPStatus.CONFLICT,
           "prerequisite_missing": HTTPStatus.CONFLICT, "spec_incomplete": HTTPStatus.CONFLICT,
           "storage_integrity": HTTPStatus.CONFLICT}


def _errors(*codes: str, write: bool = True, extra: dict[int, list[str]] | None = None) -> dict[int | str, Any]:
    """Declared error responses (P7-M1 (f)): the data.human_inputs codes the route's function can raise, mapped
    through _STATUS exactly as _error maps them, plus the write-token refusals on a write route."""
    declared: dict[int, list[str]] = {}
    for code in codes:
        declared.setdefault(int(_STATUS.get(code, HTTPStatus.UNPROCESSABLE_ENTITY)), []).append(code)
    if write:
        declared.setdefault(int(HTTPStatus.FORBIDDEN), []).extend([CODE_WRITES_DISABLED, CODE_WRITE_NOT_AUTHORIZED])
    for status, more in (extra or {}).items():
        declared.setdefault(int(status), []).extend(more)
    return error_responses(declared)


# A read route whose only possible error is a malformed parameter (e.g. a non-integer season).
_READ_ERRORS = error_responses({})


def _error(exc: hi.HumanInputError) -> ApiError:
    """The envelope's message carries the field-level problems: api/errors.py allow-lists `details` to request
    validation only, and that is not widened here."""
    message = str(exc) + problems_suffix(exc.details)
    return ApiError(status_code=_STATUS.get(exc.code, HTTPStatus.UNPROCESSABLE_ENTITY), code=exc.code,
                    message=message)


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except hi.HumanInputError as exc:
        raise _error(exc) from exc


# --- request bodies ------------------------------------------------------------------------------


class SpecDraftBody(BaseModel):
    spec_json: dict[str, Any]
    created_by: str = Field(min_length=1)
    manual_id: int | None = None
    based_on_id: int | None = None


class ReviewBody(BaseModel):
    reviewer: str = Field(min_length=1)
    approve: bool
    note: str = ""


class ProfileBody(BaseModel):
    profile_key: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]
    created_by: str = Field(min_length=1)


class ProfileEditBody(BaseModel):
    payload: dict[str, Any]
    created_by: str = Field(min_length=1)


class DuplicateBody(BaseModel):
    new_key: str = Field(min_length=1, max_length=100)
    created_by: str = Field(min_length=1)


class ArchiveBody(BaseModel):
    archived_by: str = Field(min_length=1)


class ArtifactBody(BaseModel):
    kind: str
    author: str = Field(min_length=1)
    payload: dict[str, Any]


class EstablishBody(BaseModel):
    established_by: str = Field(min_length=1)
    note: str = ""


# --- game manuals and specs ------------------------------------------------------------------------


@router.post("/game-manuals", status_code=HTTPStatus.CREATED,
             responses={HTTPStatus.OK: {"description": "The same bytes were already stored for this season: the "
                                                      "existing manual, never a duplicate."},
                        **_errors("invalid_input", "storage_integrity",
                                  extra={HTTPStatus.UNSUPPORTED_MEDIA_TYPE: [CODE_UNSUPPORTED_MEDIA_TYPE]})},
             summary="Upload an official game manual (PDF, raw request body)",
             description="Stored write-once under its sha256 with provenance. The same bytes for the same season "
                         "return the existing manual (200), never a duplicate. Uploading validates nothing.")
async def upload_manual(request: Request, season: int = Query(ge=1992), game_name: str = Query(min_length=1),
                        filename: str = Query(min_length=1), uploaded_by: str = Query(min_length=1),
                        database: Database = Depends(get_database), settings: Settings = Depends(get_settings),
                        _: None = Depends(require_writer)) -> Any:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/pdf":
        raise ApiError(status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE, code=CODE_UNSUPPORTED_MEDIA_TYPE,
                       message="Upload the manual as the request body with Content-Type: application/pdf.")
    content = await request.body()  # bounded by api.body_limit (P10-M1, Phase 7 R6)
    # P10-M1 (Phase 7 R11 F2): hashing, the file write and the database work block, so they run in the threadpool,
    # never on the event loop.
    row, created = await run_in_threadpool(_call, hi.store_manual, database, FsPath(settings.artifact_store_dir),
                                           season=season, game_name=game_name, filename=filename, content=content,
                                           uploaded_by=uploaded_by)
    body = {"manual": {k: v for k, v in row.items() if k != "storage_path"}, "created": created}
    return body if created else Response(content=_json(body), status_code=HTTPStatus.OK, media_type="application/json")


def _json(value: Any) -> str:
    import json

    from fastapi.encoders import jsonable_encoder

    return json.dumps(jsonable_encoder(value))


@router.get("/game-manuals", responses=_READ_ERRORS, summary="Uploaded game manuals (metadata and checksums)")
def get_manuals(season: int | None = Query(default=None), database: Database = Depends(get_database)) -> Any:
    return [{k: v for k, v in row.items() if k != "storage_path"} for row in hi.list_manuals(database, season)]


@router.get("/game-manuals/{manual_id}/file", responses=_errors("not_found", "storage_integrity", write=False),
            summary="Download an uploaded manual's original PDF",
            response_class=Response)
def download_manual(manual_id: int = Path(ge=1), database: Database = Depends(get_database)) -> Response:
    row, data = _call(hi.manual_file, database, manual_id)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": content_disposition(row["filename"]),
                             "X-Content-Type-Options": "nosniff",
                             "X-Content-SHA256": row["content_sha256"]})


def content_disposition(filename: str) -> str:
    """P10-M1 (Phase 7 R11 F1): a header that is valid for any stored filename. A raw
    `filename="..."` with a quote, a backslash or a non-latin-1 character made the download a 500. RFC 6266: an
    ASCII fallback with every unsafe character replaced, plus the exact name in RFC 5987 `filename*` encoding.
    Served inline (2026-10-12), so the browser's PDF viewer opens a cited page (`#page=N`) instead of downloading."""
    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename) or "manual.pdf"
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/seasons/{season}/workflow", responses=_READ_ERRORS, summary="The season's game-manual and spec workflow state")
def get_workflow(season: int = Path(ge=1992), database: Database = Depends(get_database)) -> Any:
    return hi.season_workflow(database, season)


@router.get("/seasons/{season}/specs", responses=_READ_ERRORS, summary="Every structured-spec version for a season (immutable)")
def get_specs(season: int = Path(ge=1992), database: Database = Depends(get_database)) -> Any:
    return hi.list_specs(database, season)


@router.post("/seasons/{season}/specs", status_code=HTTPStatus.CREATED, responses=_errors("invalid_input"),
             summary="Save a structured-spec draft as a new version",
             description="Never overwrites: every save is a new version. Incomplete drafts are kept with their "
                         "validation errors.")
def post_spec(body: SpecDraftBody, season: int = Path(ge=1992), database: Database = Depends(get_database),
              _: None = Depends(require_writer)) -> Any:
    return _call(hi.save_spec_draft, database, season=season, spec_json=body.spec_json, created_by=body.created_by,
                 manual_id=body.manual_id, based_on_id=body.based_on_id)


@router.post("/specs/{spec_id}/submit", responses=_errors("not_found", "invalid_state", "spec_incomplete"),
             summary="Send a complete draft for human review")
def post_submit(spec_id: int = Path(ge=1), database: Database = Depends(get_database),
                _: None = Depends(require_writer)) -> Any:
    return _call(hi.submit_spec, database, spec_id)


@router.post("/specs/{spec_id}/review", responses=_errors("invalid_input", "not_found", "invalid_state"),
             summary="Approve, or return for changes (named reviewer)")
def post_review(body: ReviewBody, spec_id: int = Path(ge=1), database: Database = Depends(get_database),
                _: None = Depends(require_writer)) -> Any:
    return _call(hi.review_spec, database, spec_id, reviewer=body.reviewer, approve=body.approve, note=body.note)


# --- capability profiles -------------------------------------------------------------------------


@router.get("/capability-profiles", responses=_READ_ERRORS, summary="Team capability profiles (latest version of each)")
def get_profiles(include_archived: bool = Query(default=False), database: Database = Depends(get_database)) -> Any:
    return hi.list_profiles(database, include_archived)


@router.get("/capability-profiles/{profile_key}/history", responses=_READ_ERRORS, summary="Every version of one profile")
def get_profile_history(profile_key: str = Path(min_length=1), database: Database = Depends(get_database)) -> Any:
    return hi.profile_history(database, profile_key)


@router.post("/capability-profiles", status_code=HTTPStatus.CREATED,
             responses=_errors("invalid_input", "not_found", "invalid_state", "conflict"),
             summary="Create a profile (landed raw-first, then validated)")
def post_profile(body: ProfileBody, database: Database = Depends(get_database), _: None = Depends(require_writer)) -> Any:
    return _call(hi.save_profile, database, profile_key=body.profile_key, payload=body.payload,
                 created_by=body.created_by, new=True)


@router.put("/capability-profiles/{profile_key}",
            responses=_errors("invalid_input", "not_found", "invalid_state", "conflict"), summary="Edit a profile (a new version)")
def put_profile(body: ProfileEditBody, profile_key: str = Path(min_length=1), database: Database = Depends(get_database),
                _: None = Depends(require_writer)) -> Any:
    return _call(hi.save_profile, database, profile_key=profile_key, payload=body.payload,
                 created_by=body.created_by, new=False)


@router.post("/capability-profiles/{profile_key}/duplicate", status_code=HTTPStatus.CREATED,
             responses=_errors("invalid_input", "not_found", "invalid_state", "conflict"),
             summary="Copy a profile under a new key")
def post_duplicate(body: DuplicateBody, profile_key: str = Path(min_length=1),
                   database: Database = Depends(get_database), _: None = Depends(require_writer)) -> Any:
    return _call(hi.duplicate_profile, database, profile_key=profile_key, new_key=body.new_key,
                 created_by=body.created_by)


@router.post("/capability-profiles/{profile_key}/archive",
             responses=_errors("invalid_input", "not_found", "invalid_state"), summary="Archive a profile")
def post_archive(body: ArchiveBody, profile_key: str = Path(min_length=1), database: Database = Depends(get_database),
                 _: None = Depends(require_writer)) -> Any:
    return _call(hi.archive_profile, database, profile_key=profile_key, archived_by=body.archived_by)


@router.get("/capability-profiles/{profile_key}/recommendation",
            responses=_errors("not_found", "prerequisite_missing", write=False),
            summary="The deterministic P5-M9 recommendation (heuristic_not_validated_against_outcomes)")
def get_recommendation(profile_key: str = Path(min_length=1), season: int = Query(ge=1992),
                       database: Database = Depends(get_database)) -> Any:
    return _call(hi.recommendation_for, database, profile_key, season)


# --- DM1 review artifacts and status --------------------------------------------------------------


@router.get("/reference/design-examples", summary="The curated design reference rows (curated_reference_unverified)")
def get_design_examples() -> Any:
    from data.design_reference import load_reference

    return [example.__dict__ for example in load_reference()]


@router.get("/seasons/{season}/artifacts", responses=_READ_ERRORS, summary="DM1 review artifacts for a season (every version)")
def get_artifacts(season: int = Path(ge=1992), kind: str | None = Query(default=None),
                  database: Database = Depends(get_database)) -> Any:
    return hi.list_artifacts(database, season, kind)


@router.post("/seasons/{season}/artifacts", status_code=HTTPStatus.CREATED,
             responses=_errors("invalid_input", "prerequisite_missing"),
             summary="Submit a codebook, coding, consensus coding, action map, rubric or mentor review")
def post_artifact(body: ArtifactBody, season: int = Path(ge=1992), database: Database = Depends(get_database),
                  _: None = Depends(require_writer)) -> Any:
    return _call(hi.submit_artifact, database, kind=body.kind, season=season, author=body.author, payload=body.payload)


@router.post("/artifacts/{artifact_id}/establish", responses=_errors("invalid_input", "not_found", "invalid_state"),
             summary="A named person establishes a submitted codebook, consensus coding, action map or rubric")
def post_establish(body: EstablishBody, artifact_id: int = Path(ge=1), database: Database = Depends(get_database),
                   _: None = Depends(require_writer)) -> Any:
    return _call(hi.establish_artifact, database, artifact_id, established_by=body.established_by, note=body.note)


@router.get("/seasons/{season}/kappa", responses=_READ_ERRORS, summary="Codebook agreement (Cohen's kappa) under P5-D13's gate")
def get_kappa(season: int = Path(ge=1992), database: Database = Depends(get_database)) -> Any:
    return hi.kappa_status(database, season)


@router.get("/seasons/{season}/dm1-status", responses=_READ_ERRORS, summary="What DM1 still needs (informational; never marks DM1 met)")
def get_dm1_status(season: int = Path(ge=1992), database: Database = Depends(get_database)) -> Any:
    from scripts.phase5_done_means import dm1

    return {**hi.dm1_status(database, season), "done_means": dm1()}  # DM1 comes from the write-once records only


@router.get("/write-access", summary="Whether writes are enabled, and whether the supplied token is accepted")
def get_write_access(request: Request, settings: Settings = Depends(get_settings)) -> Any:
    expected = settings.human_inputs_write_token
    supplied = request.headers.get(WRITE_TOKEN_HEADER, "")
    return {"writes_enabled": bool(expected),
            "token_accepted": bool(expected) and hmac.compare_digest(supplied.encode(), expected.encode())}


__all__ = ["router", "WRITE_TOKEN_HEADER"]
