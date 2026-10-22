"""Game Manual Manager and season-ruleset entry over HTTP (2026-10-11), under `/human-inputs` like every human input.

**Data entry and status only:**
- the Phase 5 human-input web app is reused for data entry (P6-A1);
- nothing here runs a model, an evaluation or a Phase 6 engine;
- no path names a strategy, alliance-selection, pick-list or playoff route.

**Writes** need the `X-StratAI-Write-Token` header, exactly as the other human-input writes, and name the person
acting. A ruleset approval enforces the unchanged P6-M1 review control (`data.rulesets.review_ruleset`): a named
reviewer, a stated qualification, R1–R14 each completed, the full stored sha256 verified, and no UNVERIFIED marker. It
also writes the same write-once approval record the CLI writes.

**Processing** is deterministic (`data.manual_processing`) and idempotent. It runs after the request returns, and the
web app polls its status.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.contract import error_responses
from api.dependencies import get_database, get_settings
from api.errors import ApiError
from api.routes.common import CODE_WRITE_NOT_AUTHORIZED, CODE_WRITES_DISABLED, require_writer  # P7-M5
from data import manual_processing as mp
from data import readiness as rd
from data import rulesets as rs
from data.config import Settings
from database.connection import Database

router = APIRouter(prefix="/human-inputs", tags=["game manual manager and season rulesets"])

_STATUS = {"invalid_input": HTTPStatus.UNPROCESSABLE_ENTITY, "not_found": HTTPStatus.NOT_FOUND,
           "invalid_state": HTTPStatus.CONFLICT, "storage_integrity": HTTPStatus.CONFLICT,
           "wrong_season": HTTPStatus.CONFLICT, "hash_mismatch": HTTPStatus.CONFLICT,
           "review_incomplete": HTTPStatus.CONFLICT, "invalid_stored_ruleset": HTTPStatus.CONFLICT,
           "unverified_content": HTTPStatus.CONFLICT, "not_approved": HTTPStatus.NOT_FOUND}


def _errors(*codes: str, write: bool = False, validates_input: bool = True) -> dict[int | str, Any]:
    """Declared error responses (the P7-M1 (f) contract every route keeps): the codes the route's own calls can
    raise, mapped through _STATUS exactly as _call maps them, plus the write-token refusals on a write route. The
    codes per route were derived from the data functions each route calls (2026-10-21, while integrating PR #37)."""
    declared: dict[int, list[str]] = {}
    for code in codes:
        declared.setdefault(int(_STATUS.get(code, HTTPStatus.UNPROCESSABLE_ENTITY)), []).append(code)
    if write:
        declared.setdefault(int(HTTPStatus.FORBIDDEN), []).extend([CODE_WRITES_DISABLED, CODE_WRITE_NOT_AUTHORIZED])
    return error_responses(declared, validates_input=validates_input)
MAX_PAGES_PER_REQUEST = 25
# P6_M1_HUMAN_INPUT_GUIDE.md §5: what each pre-approval checklist item attests (the guide has the full text).
CHECKLIST_TITLES = {
    "R1": "Identity and qualification", "R2": "Documents (manual version and Team Update precedence)",
    "R3": "Every value checked against its cited section", "R4": "Alliance counts", "R5": "Selection behaviour",
    "R6": "The bracket", "R7": "The TBA mapping (a real event)", "R8": "Tie behaviour", "R9": "Exclusions",
    "R10": "Stored content is what was checked", "R11": "Fields populated or explicitly unresolved",
    "R12": "Citations exist", "R13": "Event variants tied to the correct events",
    "R14": "Exclusions intentional and documented"}


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (mp.ManualProcessingError, rs.RulesetError) as exc:
        message = str(exc)
        if isinstance(exc.details, list) and exc.details:
            message += " -- " + "; ".join(str(d.get("field", "")) + ": " + str(d.get("message", d))
                                          if isinstance(d, dict) else str(d) for d in exc.details[:12])
        raise ApiError(status_code=_STATUS.get(exc.code, HTTPStatus.UNPROCESSABLE_ENTITY), code=exc.code,
                       message=message) from exc


def _store(settings: Settings) -> FsPath:
    return FsPath(settings.artifact_store_dir)


def _manual(database: Database, manual_id: int) -> dict[str, Any]:
    return _call(mp.manual_meta, database, manual_id)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "storage_path"}


# --- processing ---------------------------------------------------------------------------------------------------


class ProcessBody(BaseModel):
    requested_by: str = Field(min_length=1)


class ResolveBody(BaseModel):
    season: int
    resolved_by: str = Field(min_length=1)
    note: str = ""


@router.get("/game-manuals/{manual_id}/processing", responses=_errors("not_found"), summary="A manual's processing status")
def get_processing(manual_id: int = Path(ge=1), database: Database = Depends(get_database),
                   settings: Settings = Depends(get_settings)) -> Any:
    return mp.status(_store(settings), _manual(database, manual_id))


@router.post("/game-manuals/{manual_id}/processing", status_code=HTTPStatus.ACCEPTED,
             responses=_errors("invalid_input", "not_found", write=True),
             summary="Process a stored manual (idempotent; runs after the response; poll the status)")
def start_processing(body: ProcessBody, background: BackgroundTasks, manual_id: int = Path(ge=1),
                     database: Database = Depends(get_database), settings: Settings = Depends(get_settings),
                     _: None = Depends(require_writer)) -> Any:
    state = _call(mp.start, database, _store(settings), manual_id, requested_by=body.requested_by)
    if state["claimed"]:
        background.add_task(mp.run, database, _store(settings), manual_id, requested_by=body.requested_by.strip())
        state = {**state, "status": "running"}
    return state


@router.post("/game-manuals/{manual_id}/identity-resolution",
             responses=_errors("invalid_input", "invalid_state", "not_found", "storage_integrity", "wrong_season",
                               write=True),
             summary="A named person confirms an ambiguous manual's season (write-once)")
def resolve_identity(body: ResolveBody, manual_id: int = Path(ge=1), database: Database = Depends(get_database),
                     settings: Settings = Depends(get_settings), _: None = Depends(require_writer)) -> Any:
    return _call(mp.resolve_identity, database, _store(settings), manual_id, season=body.season,
                 resolved_by=body.resolved_by, note=body.note)


@router.get("/game-manuals/{manual_id}/extraction", responses=_errors("not_found"),
            summary="Identity, sections, topics and unverified suggestions (page text via /pages)")
def get_extraction(manual_id: int = Path(ge=1), database: Database = Depends(get_database),
                   settings: Settings = Depends(get_settings)) -> Any:
    manual = _manual(database, manual_id)
    data = mp.extraction(_store(settings), manual)
    if data is None:
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code="not_found", message="the manual has not been processed")
    return {**{k: v for k, v in data.items() if k != "pages"},
            "pages": [{k: p[k] for k in ("page", "chars", "text_sha256", "error")} for p in data["pages"]]}


@router.get("/game-manuals/{manual_id}/pages", responses=_errors("invalid_input", "not_found"), summary="Extracted page text (at most 25 pages)")
def get_pages(manual_id: int = Path(ge=1), first: int = Query(ge=1), last: int = Query(ge=1),
              database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Any:
    if last < first or last - first + 1 > MAX_PAGES_PER_REQUEST:
        raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code="invalid_input",
                       message=f"request 1 to {MAX_PAGES_PER_REQUEST} pages, first <= last")
    return _call(mp.pages, _store(settings), _manual(database, manual_id), first, last)


# --- season rulesets (P6-M1 data entry and review) ---------------------------------------------------------------


class RulesetDraftBody(BaseModel):
    ruleset_json: dict[str, Any]
    created_by: str = Field(min_length=1)


class RulesetReviewBody(BaseModel):
    reviewer: str = Field(min_length=1)
    approve: bool
    note: str = ""
    reviewer_qualification: str = ""
    checklist: dict[str, bool] | None = None
    verified_sha256: str = ""


@router.get("/rulesets", responses=_errors(), summary="Season ruleset versions (every version is kept)")
def get_rulesets(season: int | None = Query(default=None), database: Database = Depends(get_database)) -> Any:
    return rs.list_rulesets(database, season)


@router.get("/ruleset-review-checklist", responses=_errors(validates_input=False), summary="The P6-M1 pre-approval checklist items (R1-R14)")
def get_checklist() -> Any:
    return {"items": [{"id": i, "title": CHECKLIST_TITLES[i]} for i in rs.REVIEW_CHECKLIST],
            "guide": ".agent/phase6/P6_M1_HUMAN_INPUT_GUIDE.md §5",
            "control": ".agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md",
            "r15": "written by the approval itself: the write-once approval record, committed afterwards"}


@router.get("/rulesets/{ruleset_id}", responses=_errors("not_found"), summary="One ruleset version")
def get_ruleset(ruleset_id: int = Path(ge=1), database: Database = Depends(get_database)) -> Any:
    found = [r for r in rs.list_rulesets(database) if r["id"] == ruleset_id]
    if not found:
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code="not_found", message=f"no ruleset version {ruleset_id}")
    return found[0]


@router.post("/rulesets", status_code=HTTPStatus.CREATED, responses=_errors("invalid_input", write=True),
             summary="Save a ruleset draft (a new immutable version; schema-validated)")
def post_ruleset(body: RulesetDraftBody, database: Database = Depends(get_database),
                 _: None = Depends(require_writer)) -> Any:
    return _call(rs.save_ruleset_draft, database, body.ruleset_json, created_by=body.created_by)


@router.post("/rulesets/{ruleset_id}/submit", responses=_errors("invalid_state", "not_found", write=True), summary="Submit a draft for review")
def submit_ruleset(ruleset_id: int = Path(ge=1), database: Database = Depends(get_database),
                   _: None = Depends(require_writer)) -> Any:
    return _call(rs.submit_ruleset, database, ruleset_id)


@router.post("/rulesets/{ruleset_id}/review",
             responses=_errors("hash_mismatch", "invalid_input", "invalid_state", "invalid_stored_ruleset", "not_found",
                               "review_incomplete", "unverified_content", write=True),
             summary="Approve (named, qualified reviewer; R1-R14; full sha256) or return with a note")
def review_ruleset(body: RulesetReviewBody, ruleset_id: int = Path(ge=1), database: Database = Depends(get_database),
                   settings: Settings = Depends(get_settings), _: None = Depends(require_writer)) -> Any:
    record_path = None
    if body.approve:  # refuse before approving if the write-once approval record already exists
        record_path = _call(rs.approval_record_path, database, ruleset_id, FsPath(settings.ruleset_approval_record_dir))
    row = _call(rs.review_ruleset, database, ruleset_id, reviewer=body.reviewer, approve=body.approve, note=body.note,
                reviewer_qualification=body.reviewer_qualification, checklist=body.checklist,
                verified_sha256=body.verified_sha256)
    record = _call(rs.write_approval_record, record_path, row) if body.approve else None
    return {"ruleset": row, "approval_record": None if record is None else
            {"path": str(record_path), "record": record, "next_step": "commit the approval record (R15)"}}


@router.get("/seasons/{season}/ruleset-worksheet", responses=_errors("invalid_input", "not_found"),
            summary="A reviewable draft proposal for a new season's ruleset (never saved or approved)")
def get_worksheet(season: int = Path(ge=1992), database: Database = Depends(get_database),
                  settings: Settings = Depends(get_settings)) -> Any:
    from data.ruleset_worksheet import ruleset_worksheet

    return _call(ruleset_worksheet, database, _store(settings), season)


# --- readiness ---------------------------------------------------------------------------------------------------


@router.get("/seasons/{season}/readiness", responses=_errors(), summary="Data coverage, human inputs, the feature map and the task queue")
def get_readiness(request: Request, season: int = Path(ge=1992), database: Database = Depends(get_database),
                  settings: Settings = Depends(get_settings)) -> Any:
    state = request.app.state
    serving = {"ranking_model": getattr(state, "ranking_model", None) is not None,
               "win_prob_model": getattr(state, "win_prob_model", None) is not None}
    return rd.season_readiness(database, _store(settings), FsPath(settings.phase6_dir), season, serving)
