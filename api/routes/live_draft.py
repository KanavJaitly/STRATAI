"""Phase 11: the team's live alliance-selection draft record and its recommendations (docs/phase11.md).

    GET  /workspace/alliance-selection/drafts[?event_key=...]           the team's records
    POST /workspace/alliance-selection/drafts                            start one for an event the team attends
    GET  /workspace/alliance-selection/drafts/{record_id}                the live board, the effective draft, history
    POST /workspace/alliance-selection/drafts/{record_id}/actions        record a captain, pick, decline or backup
    POST /workspace/alliance-selection/drafts/{record_id}/undo           undo the most recent action in effect
    POST /workspace/alliance-selection/drafts/{record_id}/corrections    replace an earlier action
    POST /workspace/alliance-selection/drafts/{record_id}/close          close the record (read-only until reopened)
    POST /workspace/alliance-selection/drafts/{record_id}/reopen
    POST /workspace/alliance-selection/drafts/{record_id}/setup          refresh the setup from the event's data
    GET  /workspace/alliance-selection/drafts/{record_id}/recommendations  primary and backup picks for the state

**Thin wrappers over workspaces.live_draft and workspaces.draft_recommendations.**
- The workspace always comes from the session.
- Reading needs `alliance_selection` (P11-Q4). Changing a record also needs `alliance_selection_record` (P11-Q2)
  and a verified workspace. Every change carries the CSRF header.
- An action the rules make impossible is a 409 carrying the rule's own code (for example `wrong_turn` or
  `team_declined`). Sending it again with `override_reason` records it as an override.

**The recommendations** come from the P6-M7 engine when it serves. Otherwise they come from the pre-declared
fallback rule P11-FB1 (`not_validated`, no probability, with the engine's refusal beside it). Every response
carries the record sequence it reflects. The locked alliance-selection operations are not changed.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from api.contract import StrategyOdds, Validation, error_responses
from api.dependencies import get_database, get_epa_source, get_playoff_models, get_ranking_model
from api.routes.alliance_selection import CandidateOut, _candidate, _odds
from api.session import call, require_csrf, require_permission, require_session
from database.connection import Database
from workspaces import draft_log, draft_recommendations, live_draft
from workspaces.sessions import SessionContext

router = APIRouter(prefix="/workspace/alliance-selection", tags=["live alliance selection"])

# The rule codes a recorded action can be refused with (workspaces/draft_log.py check_action and replay;
# tests/test_phase11_live_draft_units.py checks this list against that module).
RULE_CODES = ("unknown_alliance", "backups_not_used", "draft_incomplete", "team_on_alliance", "already_backup",
              "team_not_in_pool", "draft_complete", "wrong_turn", "captain_already_named",
              "captain_rule_not_established", "no_eligible_captain", "wrong_captain", "captain_not_named",
              "team_declined", "alliance_full", "captain_not_pickable", "not_configured", "not_applicable",
              "not_last_action", "not_in_effect", "invalid_action", "invalid_setup")
_AUTH = {401: ["not_authenticated"]}
_READ = {**_AUTH, 403: ["permission_denied"], 409: ["live_draft_unavailable"]}
_WRITE_403 = ["permission_denied", "workspace_not_verified", "csrf_check_failed"]
_CHANGE = {**_AUTH, 403: _WRITE_403, 404: ["draft_not_found"],
           409: ["live_draft_unavailable", "record_closed", "action_id_conflict", *RULE_CODES],
           422: ["invalid_input"]}


# Route dependencies run before the body is validated, so a caller without the permission always gets its 403 (the
# service checks the same permissions again, with the verified-workspace rule).
_WRITES = [Depends(require_csrf), Depends(require_permission(live_draft.VIEW)),
           Depends(require_permission(live_draft.RECORD))]
_VIEWS = [Depends(require_permission(live_draft.VIEW))]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualRulesBody(_Body):
    """The event's rules, entered from the event, when no approved ruleset covers it (stored as manual_entry)."""

    n_alliances: int = Field(ge=2, le=16)
    picks_per_alliance: int = Field(ge=1, le=4)
    declined_team_may_be_picked_later: bool
    declined_team_may_become_captain: bool | None = Field(default=None, description="Null: not established.")
    captain_may_accept_higher_alliance: bool
    backup_robots: bool


class StartBody(_Body):
    event_key: str = Field(min_length=1, max_length=64)
    record_uid: str | None = Field(default=None, description="A client-created UUID (local-first); else the server's.")
    action_id: str | None = Field(default=None, description="The configure entry's UUID; else the server's.")
    manual_rules: ManualRulesBody | None = None


class SetupBody(_Body):
    action_id: str | None = None
    manual_rules: ManualRulesBody | None = None


class ActionBody(_Body):
    type: Literal["captain", "pick", "decline", "backup"]
    seed: int | None = Field(default=None, ge=1, description="The alliance; optional only for a backup.")
    team_number: int = Field(ge=1)
    action_id: str | None = Field(default=None, description="A client-created UUID: a retry with the same id and "
                                                            "content is idempotent.")
    override_reason: str | None = Field(default=None, max_length=500,
                                        description="Record an action the rules refuse, because the room did it.")
    client_recorded_at: datetime | None = None


class ReplacementBody(_Body):
    type: Literal["captain", "pick", "decline", "backup"]
    seed: int | None = Field(default=None, ge=1)
    team_number: int = Field(ge=1)


class CorrectionBody(_Body):
    target_action_id: str = Field(min_length=1, max_length=64)
    replacement: ReplacementBody | None = Field(description="What really happened; null if it did not happen.")
    action_id: str | None = None
    override_reason: str | None = Field(default=None, max_length=500)


class UndoBody(_Body):
    target_action_id: str | None = Field(default=None, description="The most recent action in effect, as the "
                                                                   "caller sees it; refused if it is not.")
    action_id: str | None = None


class EntryBody(_Body):
    action_id: str | None = None


# --- response shapes -------------------------------------------------------------------------------------------------


class AllianceOut(BaseModel):
    seed: int
    captain: int | None = Field(description="Recorded (observed).")
    picks: list[int] = Field(description="Recorded picks, in order (observed).")
    projected_captain: int | None = Field(description="Projection from the rules and ranks, for a seed without a "
                                                      "recorded captain; never a record.")


class TurnOut(BaseModel):
    index: int
    round: int | None
    seed: int
    captain_named: bool
    expected_captain: int | None = Field(description="The captain the rules name now, if it can be determined.")
    expected_captain_reason: str | None


class AvailableOut(BaseModel):
    team_number: int
    rank: int | None
    projected_captain_of: int | None
    declined_earlier: bool


class UnavailableOut(BaseModel):
    team_number: int
    reason: Literal["captain", "picked", "declined", "backup", "projected_captain"] = Field(
        description="projected_captain: the rules will make it a lower alliance's captain, and they do not let a "
                    "captain join a higher alliance.")
    rank: int | None
    seed: int | None


class TeamSeedOut(BaseModel):
    team_number: int
    seed: int | None


class FlagOut(BaseModel):
    action_id: str
    status: str
    code: str | None
    message: str | None


class ViolationOut(BaseModel):
    code: str
    message: str


class EffectiveOut(BaseModel):
    action_id: str
    slot_action_id: str
    seq: int
    type: str
    seed: int | None
    team_number: int
    status: Literal["accepted", "overridden", "invalid", "not_applied"]
    violation: ViolationOut | None
    override_reason: str | None
    notes: list[str]
    summary: str
    recorded_by: str
    recorded_at: datetime | None


class HistoryOut(BaseModel):
    action_id: str
    seq: int
    type: str
    summary: str
    override_reason: str | None
    in_effect: bool
    superseded_by: str | None
    recorded_by: str
    recorded_at: datetime | None
    source: str
    mode: str


class DraftOut(BaseModel):
    record_id: int
    record_uid: str
    event_key: str
    created_at: datetime
    created_by: str
    can_record: bool
    team_number: int | None
    record_seq: int = Field(description="The last log entry's sequence: the version every derived value cites.")
    status: Literal["open", "closed"]
    configured: bool
    setup: dict[str, Any] | None = Field(description="Rules, ranks, pool, what is missing, and provenance.")
    value_kind: Literal["observed"] = "observed"
    alliances: list[AllianceOut]
    turn: TurnOut | None
    complete: bool
    available: list[AvailableOut]
    unavailable: list[UnavailableOut]
    declined: list[TeamSeedOut]
    backups: list[TeamSeedOut]
    flags: list[FlagOut] = Field(description="Actions that became invalid after a correction or a new setup.")
    effective: list[EffectiveOut]
    history: list[HistoryOut]


class DraftSummaryOut(BaseModel):
    record_id: int
    record_uid: str
    event_key: str
    created_at: datetime
    created_by: str
    record_seq: int
    status: Literal["open", "closed"]
    picks_made: int
    complete: bool


class RecommendedOut(BaseModel):
    team_number: int
    ordering_position: int | None = Field(description="Position in the P5-M4 strength ordering (fallback only).")
    win_event: StrategyOdds | None = Field(description="Engine only: P(the alliance wins the event), displayed.")
    reach_finals: StrategyOdds | None
    configuration: list[int] | None
    profile: CandidateOut | None


class CodeMessage(BaseModel):
    code: str
    message: str


class ExcludedOut(BaseModel):
    team_number: int
    reason: str


class RecommendationsOut(BaseModel):
    record_id: int
    record_seq: int = Field(description="The record version these recommendations reflect.")
    computed_at: datetime
    status: Literal["current", "withheld"]
    withheld: CodeMessage | None
    value_kind: Literal["model_prediction"] = "model_prediction"
    source: Literal["engine_p6_m7", "fallback_p11_fb1"] | None
    validation: Validation | None
    engine_refusal: CodeMessage | None = Field(description="Why the P6-M7 engine did not serve (fallback only).")
    seed: int | None
    selecting_as: Literal["on_alliance", "projected_captain"] | None
    turns_before: int | None = Field(description="Other alliances' picks before this alliance's next turn.")
    primary: RecommendedOut | None
    backups: list[RecommendedOut]
    unranked_available: list[int]
    excluded: list[ExcludedOut]
    movement: list[str]
    provenance: dict[str, Any]
    timing_ms: dict[str, float]


# --- routes ------------------------------------------------------------------------------------------------------------


@router.get("/drafts", response_model=list[DraftSummaryOut], dependencies=_VIEWS,
            summary="The team's live draft records",
            responses=error_responses(_READ))
def get_drafts(event_key: str | None = Query(default=None, max_length=64), database: Database = Depends(get_database),
               context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.list_drafts, database, context, event_key=event_key)


@router.post("/drafts", response_model=DraftOut, status_code=HTTPStatus.CREATED,
             dependencies=_WRITES,
             summary="Start the team's live draft record for an event it attends",
             responses=error_responses({**_AUTH, 403: [*_WRITE_403, "team_not_at_event"],
                                        404: ["event_not_found"],
                                        409: ["live_draft_unavailable", "draft_exists"],
                                        422: ["invalid_input", "rules_required"]}))
def post_draft(body: StartBody, database: Database = Depends(get_database),
               context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.start_draft, database, context, event_key=body.event_key, record_uid=body.record_uid,
                action_id=body.action_id,
                manual_rules=None if body.manual_rules is None else body.manual_rules.model_dump())


@router.get("/drafts/{record_id}", response_model=DraftOut, dependencies=_VIEWS,
            summary="The live board, effective draft and history",
            responses=error_responses({**_READ, 404: ["draft_not_found"]}))
def get_draft(record_id: int = Path(ge=1), database: Database = Depends(get_database),
              context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.get_draft, database, context, record_id)


@router.post("/drafts/{record_id}/actions", response_model=DraftOut, dependencies=_WRITES,
             summary="Record one real selection action: a captain named, a pick, a decline or a backup",
             responses=error_responses(_CHANGE))
def post_action(body: ActionBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
                context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.record_action, database, context, record_id, type_=body.type, seed=body.seed,
                team=body.team_number, action_id=body.action_id, override_reason=body.override_reason,
                client_recorded_at=body.client_recorded_at)


@router.post("/drafts/{record_id}/undo", response_model=DraftOut, dependencies=_WRITES,
             summary="Undo the most recent action in effect (kept in the history)",
             responses=error_responses({**_CHANGE, 409: [*_CHANGE[409], "nothing_to_undo"]}))
def post_undo(body: UndoBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
              context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.undo_last, database, context, record_id, target_action_id=body.target_action_id,
                action_id=body.action_id)


@router.post("/drafts/{record_id}/corrections", response_model=DraftOut, dependencies=_WRITES,
             summary="Replace an earlier action with what really happened; later actions are re-validated",
             responses=error_responses(_CHANGE))
def post_correction(body: CorrectionBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
                    context: SessionContext = Depends(require_session)) -> Any:
    replacement = None if body.replacement is None else {
        "type": body.replacement.type, "seed": body.replacement.seed, "team": body.replacement.team_number}
    return call(live_draft.correct_action, database, context, record_id, target_action_id=body.target_action_id,
                replacement=replacement, action_id=body.action_id, override_reason=body.override_reason)


@router.post("/drafts/{record_id}/close", response_model=DraftOut, dependencies=_WRITES,
             summary="Close the record: read-only until reopened", responses=error_responses(_CHANGE))
def post_close(body: EntryBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
               context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.close_draft, database, context, record_id, action_id=body.action_id)


@router.post("/drafts/{record_id}/reopen", response_model=DraftOut, dependencies=_WRITES,
             summary="Reopen a closed record (recorded)",
             responses=error_responses({**_CHANGE, 409: [*_CHANGE[409], "record_open"]}))
def post_reopen(body: EntryBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
                context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.reopen_draft, database, context, record_id, action_id=body.action_id)


@router.post("/drafts/{record_id}/setup", response_model=DraftOut, dependencies=_WRITES,
             summary="Refresh the record's setup from the event's current data (e.g. once final ranks land)",
             responses=error_responses({**_CHANGE, 422: ["invalid_input", "rules_required"]}))
def post_setup(body: SetupBody, record_id: int = Path(ge=1), database: Database = Depends(get_database),
               context: SessionContext = Depends(require_session)) -> Any:
    return call(live_draft.reconfigure_draft, database, context, record_id, action_id=body.action_id,
                manual_rules=None if body.manual_rules is None else body.manual_rules.model_dump())


def _recommended(candidate: draft_recommendations.Candidate, status: str | None) -> RecommendedOut:
    engine = candidate.p_win_event is not None
    return RecommendedOut(
        team_number=candidate.team_number, ordering_position=candidate.ordering_position,
        win_event=_odds(candidate.p_win_event, status) if engine else None,
        reach_finals=_odds(candidate.p_reach_finals, status) if engine and candidate.p_reach_finals is not None
        else None,
        configuration=list(candidate.configuration) if candidate.configuration else None,
        profile=None if candidate.profile is None else _candidate(candidate.profile))


@router.get("/drafts/{record_id}/recommendations", response_model=RecommendationsOut, dependencies=_VIEWS,
            summary="The team's primary and backup picks for the record's current state (P11-Q1)",
            description="From the P6-M7 engine when it serves; otherwise the pre-declared fallback rule P11-FB1, "
                        "served not_validated with no probability and with the engine's refusal. Withheld, with the "
                        "reason, when the record needs review, the team is not selecting, or an input is missing.",
            responses=error_responses({**_READ, 404: ["draft_not_found"]}))
def get_recommendations(record_id: int = Path(ge=1), database: Database = Depends(get_database),
                        context: SessionContext = Depends(require_session),
                        ranking: Any = Depends(get_ranking_model), playoff_models: Any = Depends(get_playoff_models),
                        epa_source: Any = Depends(get_epa_source)) -> Any:
    row, (view, previous) = call(live_draft.load_view_with_previous, database, context, record_id)
    out = draft_recommendations.recommend(database, row[2], view, previous, context.team_number,
                                          epa_source=epa_source, ranking=ranking, playoff_models=playoff_models)
    status = out.validation_status
    return RecommendationsOut(
        record_id=record_id, record_seq=out.record_seq, computed_at=out.computed_at, status=out.status,
        withheld=None if out.withheld is None else CodeMessage(code=out.withheld[0], message=out.withheld[1]),
        source=out.source,
        validation=None if status is None else Validation(status=status, reasons=out.validation_reasons),
        engine_refusal=None if out.engine_refusal is None else CodeMessage(code=out.engine_refusal[0],
                                                                           message=out.engine_refusal[1]),
        seed=out.seed, selecting_as=out.selecting_as, turns_before=out.turns_before,
        primary=None if out.primary is None else _recommended(out.primary, status),
        backups=[_recommended(c, status) for c in out.backups], unranked_available=out.unranked_available,
        excluded=[ExcludedOut(team_number=t, reason=r) for t, r in out.excluded], movement=out.movement,
        provenance=out.provenance, timing_ms=out.timing_ms)


__all__ = ["RULE_CODES", "router", "draft_log"]
