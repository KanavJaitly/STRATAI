"""P7-M6: alliance selection (P7-Q1) -- candidate profiles now, and the pick list behind its real gates.

    GET  /events/{event_key}/alliance-selection/candidates[?as_of=...&configuration=a&configuration=b&configuration=c]
    POST /events/{event_key}/alliance-selection/pick-list

**Candidates** serve every qualification-roster team's P6-M6 factor profile (scoring EPA, average score, reliability,
consistency, defense, feeding, synergy, role compatibility), each with its value, n and the engine's own status. They
need no ruleset. `as_of` defaults to the event's selection moment, or now if that is still ahead (no future as_of,
P7-D4). Synergy and role compatibility are alliance-level: reported for the members of a supplied three-team
`configuration`, and insufficient_data otherwise. reliability is the INTERIM attendance ratio, and says so in its
reasons.

**The pick list** is the P6-M7 engine's ranking of every available pick for one seed's turn by P(the alliance wins the
event), with alternatives. It runs only when every check passes (ml.playoffs.service, R4): an approved P6-M1 ruleset,
the event's rules, the PX gates (PX-1, PX-2, PX-4 records), then its inputs at the selection moment (qualification
finished, final ranks fetched after it, the pinned PX artifacts named in the gate records, the ordering), then the
engine and a consistent draft state. Until then it returns the real refusal. **Today the 2024-2026 rulesets await
review, so it refuses with `not_approved`: real alliance-selection output is deferred with P6-DM1 (P7-Q1).**
Probabilities are display strings only (P6-A5); `probability_status` is `validated_playoff_success` (P7-D7), with its
scope stated, only because the PX-4 record passed. The differences to the next candidate are the display rule's
labels, never numbers (R2, R13).
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field, model_validator

from api.contract import StrategyOdds, Validation, error_responses
from api.dependencies import get_database, get_epa_source, get_playoff_models, get_ranking_model
from api.errors import ApiError
from api.ml_loading import ServedEpaSource, ServedModel
from api.routes.common import (
    AS_OF_DESCRIPTION,
    CODE_EPA_SOURCE_INCOMPLETE,
    CODE_EPA_SOURCE_NOT_LOADED,
    CODE_EPA_SOURCE_PENDING,
    CODE_EVENT_NOT_FOUND,
    CODE_INVALID_AS_OF,
    CODE_MODEL_NOT_LOADED,
    CODE_TEAM_NOT_FOUND,
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    event_not_found_error,
    model_not_loaded_error,
    parse_as_of,
    require_epa_source,
    require_teams_rostered,
    team_not_found_error,
)
from data.rulesets import RulesetError
from database.connection import Database
from ml.features.roster import event_exists
from ml.playoffs.selection import CandidateProfile, DraftState, FactorValue
from ml.playoffs.service import (
    PickListResult,
    PlayoffInputsInsufficient,
    PlayoffModelsNotAccepted,
    PlayoffModelsNotLoaded,
    RankingsUnavailable,
    SelectionServiceError,
    SCOPE_REASONS,
    SelectionTimeUnavailable,
    VALIDATED_PLAYOFF_SUCCESS,
    candidate_profiles,
    event_selection_moment,
    pick_list,
    qualification_roster,
)
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.strategy.display import compare_odds, display_odds
from ml.views.event_analysis import POLICY_RAW_EPA, M5V2Required
from ml.views.strength import RELIABILITY_INTERIM

router = APIRouter(tags=["alliance selection"])

# The RulesetError codes the ruleset loader and the selection engine can raise here (R1, R4): served unchanged, 409.
# (event_rules_required is unreachable: the service always passes one event's rules.)
RULESET_CODES = ("not_approved", "storage_integrity", "wrong_season", "event_excluded", "not_covered",
                 "not_established", "not_supported", "infeasible", "invalid_state")
CODE_SELECTION_TIME_UNAVAILABLE = SelectionTimeUnavailable.code
CODE_PLAYOFF_MODELS_NOT_ACCEPTED = PlayoffModelsNotAccepted.code
CODE_RANKINGS_UNAVAILABLE = RankingsUnavailable.code
CODE_PLAYOFF_INPUTS_INSUFFICIENT = PlayoffInputsInsufficient.code
LAST_CANDIDATE = "last_candidate: no next-best candidate to compare with"
PX4_EVIDENCE = ".agent/phase6/results/p6_m5_px4.json"
INTERIM_NOTE = (" reliability is an INTERIM placeholder (100 * matches_used / matches_scheduled, an attendance ratio, "
                "not a robot-failure measure; docs/metrics_pipeline.md section 6.3).")


# --- shapes ---------------------------------------------------------------------------------------------------------


class FactorOut(BaseModel):
    value: float | None = Field(description="Null when absent, with the reason in validation.reasons; never 0.")
    n: int | None
    validation: Validation


class CandidateOut(BaseModel):
    team_number: int
    scoring_epa: FactorOut
    average_score: FactorOut
    reliability: FactorOut
    consistency: FactorOut
    defense: FactorOut
    feeding: FactorOut
    synergy: FactorOut
    role_compatibility: FactorOut


class CandidatesResponse(BaseModel):
    event_key: str
    as_of: datetime
    as_of_source: Literal["selection_moment", "now", "requested"] = Field(
        description="selection_moment: the event's selection moment (default); now: the default while the selection "
                    "moment is still ahead; requested: the caller's as_of.")
    configuration: list[int] | None
    epa: EpaSourceInfo
    candidates: list[CandidateOut] = Field(description="Every team on the qualification roster, ascending.")


class RankedPickOut(BaseModel):
    team_number: int
    configuration: list[int] = Field(description="The predicted alliance this pick leads to.")
    win_event: StrategyOdds = Field(description="P(the alliance wins the event), displayed.")
    reach_finals: StrategyOdds = Field(description="P(the alliance reaches the finals), displayed.")
    vs_next_label: str | None = Field(description="The display rule's comparison with the next-best candidate's "
                                                  "P(win event); null for the last candidate (see vs_next_reason).")
    vs_next_reach_finals_label: str | None = Field(description="The same comparison for P(reach the finals).")
    vs_next_reason: str | None
    profile: CandidateOut | None


class FieldOut(BaseModel):
    alliances: list[list[int]] = Field(description="Every alliance by seed, captain first.")
    win_event: StrategyOdds
    reach_finals: StrategyOdds


class PlayoffModelInfo(BaseModel):
    px1_sha256: str
    px2_calibrator_sha256: str
    ranking_model_sha256: str | None = Field(description="The M5 v2 ranking model behind the ordering; null when the "
                                                         "ordering is raw EPA.")


class PickListProvenance(BaseModel):
    ruleset_sha256: str = Field(description="The approved P6-M1 season ruleset the draft used.")
    ruleset_variant: str | None = Field(description="The variant that applies to the event; null for the default.")
    ordering_policy: str = Field(description="The P5-M4 ordering model at the selection moment (raw EPA or M5 v2).")


class PickListResponse(BaseModel):
    event_key: str
    seed: int
    as_of: datetime = Field(description="The event's selection moment.")
    probability_status: Literal["validated_playoff_success"] = Field(
        description="validated_playoff_success: the PX-4 gate passed (P7-D7); its scope is in each value's "
                    "validation.reasons.")
    ranked: list[RankedPickOut]
    alternatives: list[FieldOut] = Field(description="Up to 5 distinct feasible alternative configurations "
                                                     "(P6-A7), never padded.")
    alternatives_note: str | None
    evaluated_fields: int
    notes: list[str]
    models: PlayoffModelInfo
    provenance: PickListProvenance
    epa: EpaSourceInfo


class DraftStateBody(BaseModel):
    seed: int = Field(ge=1, description="The seed whose next pick is ranked; it must be that seed's turn.")
    alliances: list[list[int]] = Field(description="Every alliance so far by seed, captain first ([] if not yet "
                                                   "formed); as many alliances as the event's rules give.")
    declined: list[int] = Field(default_factory=list, description="Teams that have declined an invitation.")
    turns_taken: int = Field(ge=0, description="Picks made so far, in serpentine order.")

    @model_validator(mode="after")
    def _distinct(self) -> "DraftStateBody":
        teams = [t for alliance in self.alliances for t in alliance]
        if len(teams) != len(set(teams)):
            raise ValueError("a team appears on more than one alliance")
        return self


# --- helpers --------------------------------------------------------------------------------------------------------


def _factor(value: FactorValue, *extra: str) -> FactorOut:
    reasons = ([value.reason] if value.reason else []) + list(extra)
    return FactorOut(value=value.value, n=value.n,
                     validation=Validation(status=value.validation_status, reasons=reasons))


def _candidate(profile: CandidateProfile) -> CandidateOut:
    return CandidateOut(team_number=profile.team_number, **{
        name: _factor(getattr(profile, name), *((RELIABILITY_INTERIM,) if name == "reliability" else ()))
        for name in ("scoring_epa", "average_score", "reliability", "consistency", "defense", "feeding", "synergy",
                     "role_compatibility")})


def _odds(p: float, status: str) -> StrategyOdds:
    reasons = list(SCOPE_REASONS) if status == VALIDATED_PLAYOFF_SUCCESS else []
    return StrategyOdds(display=display_odds(p), validation=Validation(status=status, reasons=reasons,
                                                                       evidence=PX4_EVIDENCE))


def _service_error(exc: SelectionServiceError) -> ApiError:
    if isinstance(exc, PlayoffModelsNotLoaded):
        return model_not_loaded_error("playoff PX-1 / PX-2", "the PX gates passed but the models are not pinned")
    return ApiError(status_code=HTTPStatus.CONFLICT, code=exc.code, message=str(exc))


def _ruleset_error(exc: RulesetError) -> ApiError:
    return ApiError(status_code=HTTPStatus.CONFLICT, code=exc.code, message=str(exc))


def _pick_list_out(event_key: str, seed: int, out: PickListResult, models: Any, ranking: ServedModel | None,
                   epa: EpaSourceInfo) -> PickListResponse:
    result = out.recommendation
    status = result.probability_status
    ranked = []
    for i, pick in enumerate(result.ranked):
        nxt = result.ranked[i + 1] if i + 1 < len(result.ranked) else None
        ranked.append(RankedPickOut(
            team_number=pick.team_number, configuration=list(pick.configuration),
            win_event=_odds(pick.p_win_event, status), reach_finals=_odds(pick.p_reach_finals, status),
            vs_next_label=None if nxt is None else str(compare_odds(pick.p_win_event, nxt.p_win_event)["label"]),
            vs_next_reach_finals_label=None if nxt is None else str(
                compare_odds(pick.p_reach_finals, nxt.p_reach_finals)["label"]),
            vs_next_reason=LAST_CANDIDATE if nxt is None else None,
            profile=None if pick.profile is None else _candidate(pick.profile)))
    alternatives = [FieldOut(alliances=[list(a) for a in field.alliances], win_event=_odds(field.p_win_event, status),
                             reach_finals=_odds(field.p_reach_finals, status)) for field in result.alternatives]
    uses_ranking = ranking is not None and out.ordering_policy != POLICY_RAW_EPA
    return PickListResponse(
        event_key=event_key, seed=seed, as_of=out.moment, probability_status=status, ranked=ranked,
        alternatives=alternatives, alternatives_note=result.alternatives_note, evaluated_fields=result.evaluated_fields,
        notes=list(result.notes),
        models=PlayoffModelInfo(px1_sha256=models.px1_sha256, px2_calibrator_sha256=models.px2_sha256,
                                ranking_model_sha256=ranking.sha256 if uses_ranking else None),
        provenance=PickListProvenance(ruleset_sha256=out.ruleset_sha256, ruleset_variant=out.ruleset_variant,
                                      ordering_policy=out.ordering_policy),
        epa=epa)


# --- routes ---------------------------------------------------------------------------------------------------------


@router.get(
    "/events/{event_key}/alliance-selection/candidates",
    response_model=CandidatesResponse,
    summary="Alliance-selection candidate profiles (P6-M6)",
    description="Every qualification-roster team's factor profile at the selection moment (default), each factor "
                "with its "
                "value, n and status, straight from its source; defense and feeding are never imputed. A "
                "three-team configuration adds synergy and role compatibility for its members." + INTERIM_NOTE,
    responses=error_responses({
        HTTPStatus.NOT_FOUND: [CODE_EPA_SOURCE_NOT_LOADED, CODE_EVENT_NOT_FOUND, CODE_TEAM_NOT_FOUND],
        HTTPStatus.CONFLICT: [CODE_SELECTION_TIME_UNAVAILABLE],
        HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_INVALID_AS_OF, CODE_EPA_SOURCE_INCOMPLETE, CODE_EPA_SOURCE_PENDING],
    }),
)
def alliance_selection_candidates(
    event_key: str = Path(min_length=1),
    as_of: str | None = Query(default=None, description=AS_OF_DESCRIPTION + " Default: the selection moment, or "
                                                                             "now while it is still ahead."),
    configuration: list[int] | None = Query(default=None, description="Optional: exactly three distinct team "
                                                                      "numbers forming one alliance."),
    database: Database = Depends(get_database),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> CandidatesResponse:
    epa_source = require_epa_source(epa_source)
    requested = parse_as_of(as_of) if as_of is not None else None
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    if configuration is not None:
        if len(configuration) != 3 or len(set(configuration)) != 3:
            raise ApiError(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, code="validation_error",
                           message="configuration must be exactly three distinct team numbers")
        require_teams_rostered(database, event_key, configuration)
        pool = set(qualification_roster(database, event_key))
        for team_number in configuration:  # a playoff-only row is not a selection candidate
            if team_number not in pool:
                raise team_not_found_error(team_number, event_key)
    if requested is not None:
        when, source = requested, "requested"
    else:
        try:
            moment = event_selection_moment(database, event_key)
        except SelectionTimeUnavailable as exc:
            raise _service_error(exc) from exc
        now = datetime.now(timezone.utc)
        when, source = (moment, "selection_moment") if moment <= now else (now, "now")
    try:
        profiles, states = candidate_profiles(database, event_key, when, epa_provider=epa_source.provider,
                                              configuration=configuration)
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    return CandidatesResponse(event_key=event_key, as_of=when, as_of_source=source, configuration=configuration,
                              epa=epa_info(epa_source, when, states), candidates=[_candidate(p) for p in profiles])


@router.post(
    "/events/{event_key}/alliance-selection/pick-list",
    response_model=PickListResponse,
    summary="The alliance-selection pick list for one seed's turn (P6-M7)",
    description="Every available pick ranked by P(the alliance wins the event), from the exact bracket simulator over "
                "the predicted field, with up to 5 alternatives. Runs only with an approved P6-M1 ruleset and "
                "passed PX-1/PX-2/PX-4 gates; otherwise the real refusal (today: not_approved). Odds are display "
                "strings only." + INTERIM_NOTE,
    responses=error_responses({
        HTTPStatus.NOT_FOUND: [CODE_EVENT_NOT_FOUND, CODE_EPA_SOURCE_NOT_LOADED, CODE_MODEL_NOT_LOADED],
        HTTPStatus.CONFLICT: [*RULESET_CODES, CODE_PLAYOFF_MODELS_NOT_ACCEPTED, CODE_SELECTION_TIME_UNAVAILABLE,
                              CODE_RANKINGS_UNAVAILABLE, CODE_PLAYOFF_INPUTS_INSUFFICIENT],
        HTTPStatus.UNPROCESSABLE_ENTITY: [CODE_EPA_SOURCE_INCOMPLETE, CODE_EPA_SOURCE_PENDING],
    }),
)
def alliance_selection_pick_list(
    body: DraftStateBody,
    event_key: str = Path(min_length=1),
    database: Database = Depends(get_database),
    ranking: ServedModel | None = Depends(get_ranking_model),
    playoff_models: Any = Depends(get_playoff_models),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> PickListResponse:
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    loaded: list[ServedEpaSource] = []

    # The dependency loads the EPA source on every request, but its absence is refused only at step 4 of the order
    # (an earlier refusal wins). Loading it lazily would bypass FastAPI's dependency overrides.
    def provider() -> Any:
        loaded.append(require_epa_source(epa_source))
        return loaded[0].provider

    state = DraftState(tuple(tuple(a) for a in body.alliances), frozenset(body.declined), body.turns_taken)
    try:
        out = pick_list(database, event_key, body.seed, state, datetime.now(timezone.utc), epa_provider=provider,
                        m5v2_predict_rating=None if ranking is None else ranking.model.predict_rating,
                        playoff_models=playoff_models)
    except RulesetError as exc:
        raise _ruleset_error(exc) from exc
    except SelectionServiceError as exc:
        raise _service_error(exc) from exc
    except M5V2Required as exc:
        raise model_not_loaded_error("ranking_xgb_v2 (M5 v2)", "the selection ordering needs it") from exc
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    return _pick_list_out(event_key, body.seed, out, playoff_models, ranking,
                          epa_info(loaded[0], out.moment, out.epa_states))


__all__ = ["router"]
