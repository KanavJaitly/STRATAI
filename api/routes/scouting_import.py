"""Uploading a ScoutRadioz scouting CSV export in the web app (audit 2026-11-26, workstream 8).

Thin HTTP wrappers over data.metrics.scoutradioz_upload: a preview that writes nothing, then an import of exactly the
previewed file, confirmed by its sha256. Both need the `scouting_import` permission (administrators only) and the
CSRF header. Unlike workspaces.scouting's private team reports, this writes the shared scouting_observations through
the same import the script path uses (data.metrics.scoutradioz.import_scoutradioz_csv), and only from the caller's own
team's ScoutRadioz organization. No response contains a scout's name.

Error codes: `not_authenticated` (401); `permission_denied`, `csrf_check_failed` (403); `file_changed` (409);
`empty_file`, `file_too_large`, `not_a_csv`, `invalid_header`, `too_many_rows`, `no_valid_rows`,
`mapping_not_configured`, `validation_error` (422); `payload_too_large` (413, the API's body limit).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.contract import error_responses
from api.dependencies import get_database
from api.errors import ApiError
from api.session import require_csrf, require_permission
from data.metrics.scoutradioz_upload import MAX_UPLOAD_BYTES, UploadRefused, import_upload, preview_upload
from database.connection import Database
from workspaces import activity
from workspaces.sessions import SessionContext

router = APIRouter(prefix="/workspace/scouting/imports", tags=["team scouting"])

_REFUSALS = ["empty_file", "file_too_large", "not_a_csv", "invalid_header", "too_many_rows", "no_valid_rows",
             "mapping_not_configured"]
_ERRORS = {401: ["not_authenticated"], 403: ["permission_denied", "csrf_check_failed"], 413: ["payload_too_large"],
           422: _REFUSALS}


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str | None = Field(default=None, max_length=200)
    content: str = Field(max_length=MAX_UPLOAD_BYTES, description="The CSV file's text, exactly as exported")


class ImportBody(PreviewBody):
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="The file_sha256 the preview returned")
    confirm: Literal[True] = Field(description="Must be true: the import writes to the shared scouting data")


def _refused(exc: UploadRefused) -> ApiError:
    status = HTTPStatus.CONFLICT if exc.code == "file_changed" else HTTPStatus.UNPROCESSABLE_ENTITY
    return ApiError(status_code=status, code=exc.code, message=exc.message)


@router.post("/preview", dependencies=[Depends(require_csrf)],
             summary="Check a ScoutRadioz CSV export and show, row by row, what importing it would do (writes nothing)",
             responses=error_responses(_ERRORS))
def post_preview(body: PreviewBody, database: Database = Depends(get_database),
                 context: SessionContext = Depends(require_permission("scouting_import"))) -> Any:
    try:
        return preview_upload(database, body.content.encode("utf-8"), team_number=context.team_number,
                              filename=body.filename).as_dict()
    except UploadRefused as exc:
        raise _refused(exc) from None


@router.post("", dependencies=[Depends(require_csrf)],
             summary="Import the accepted rows of a previewed ScoutRadioz CSV export (idempotent on retry)",
             responses=error_responses({**_ERRORS, 409: ["file_changed"]}))
def post_import(body: ImportBody, database: Database = Depends(get_database),
                context: SessionContext = Depends(require_permission("scouting_import"))) -> Any:
    try:
        result = import_upload(database, body.content.encode("utf-8"), team_number=context.team_number,
                               expected_sha256=body.file_sha256, filename=body.filename)
    except UploadRefused as exc:
        raise _refused(exc) from None
    outcome = result["import"]
    if outcome["landed"] or outcome["loaded"]:
        with database.cursor() as cursor:
            activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                            actor_label=context.name, action="scouting_csv_imported",
                            details={"event_key": result["event_key"], "file_sha256": result["file_sha256"],
                                     "counts": result["counts"], "landed": outcome["landed"],
                                     "loaded": outcome["loaded"], "run_id": outcome["run_id"]})
    return result
