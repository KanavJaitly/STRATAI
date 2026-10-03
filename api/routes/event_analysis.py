"""P5-M4: the event analysis endpoint (pre-event and in-event).

    GET /events/{event_key}/analysis[?as_of=<ISO-8601 with offset>]

Every element carries a validation_status:

* **Ordering:** a predicted qualification ordering under the frozen event-level policy (ml.views.event_analysis).
  - Before the event switch point it is raw EPA, `validated` (D18 M4 baseline).
  - After the switch it is M5 v2, `validated_as_measured` (P5-M4 criterion (b)). One model per ordering.
* **Captain candidates:** the top 8 of the ordering, `validated_as_measured` (P5-M4 (c)). Improvement over raw
  EPA is not claimed.
* **Strongest teams:** the same ordering's top 8, with no playoff probability (unvalidated until the playoff
  track).
* **Team comparison:** each attending team's P5-M3 strength view, `descriptive`.

Final rankings and alliances are never inputs.

Codes:
- event_not_found;
- model_not_loaded (M5 v2 needed after the switch but not pinned);
- epa_source_not_loaded, epa_source_incomplete, epa_source_pending;
- invalid_as_of.
"""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from api.dependencies import get_database, get_epa_source, get_ranking_model
from api.errors import ApiError, ErrorResponse
from api.ml_loading import ServedEpaSource, ServedModel
from api.routes.common import (
    EpaSourceInfo,
    epa_info,
    epa_source_incomplete_error,
    event_not_found_error,
    require_epa_source,
)
from api.routes.strength import parse_as_of
from database.connection import Database
from ml.features.assembler import TeamFeatures, build_team_features
from ml.features.roster import event_exists, list_teams_at_event
from ml.features.scale import ScaleLookup
from ml.models.baselines import RawEpaRankingBaseline
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.views.event_analysis import (
    CAPTAINS,
    DESCRIPTIVE,
    POLICY_M5V2,
    VALIDATED_AS_MEASURED,
    VALIDATED_RAW_EPA,
    order_teams,
    policy_model,
    serving_switch,
)
from ml.views.strength import TeamStrengthView, build_team_strength

router = APIRouter(tags=["event analysis"])

CODE_MODEL_NOT_LOADED = "model_not_loaded"
EVIDENCE_RAW_EPA = ("Raw EPA (D18 M4 baseline): mean per-event Spearman 0.5955 against final qualification rank, "
                    "held-out 2026, 208 events; pre-event orderings included.")
EVIDENCE_M5V2 = ("M5 v2 after the event switch point, measured once (P5-M4 (b), "
                 ".agent/phase5/results/p5_m4_event_analysis.json): mean Spearman 0.6138 vs raw EPA 0.5955 at the "
                 "same snapshot; paired difference +0.0183, event-bootstrap 95% CI [0.0082, 0.0288], 208 events.")
EVIDENCE_CAPTAINS_PRE = ("Captain hit rate (top 8 vs actual alliance captains), pre-event: 0.4207 (95% CI "
                         "0.4056-0.4357), 208 events (P5-M4 (c)).")
EVIDENCE_CAPTAINS_SWITCH = ("Captain hit rate at the switch point: 0.4255 under the policy vs 0.4207 for raw EPA; "
                            "paired 95% CI [-0.0126, 0.0198] includes 0, so no improvement over raw EPA is claimed "
                            "(P5-M4 (c)).")
STRONGEST_NOTE = "Ordering only: no playoff or alliance-success probability is served (unvalidated; Phase 6)."


class RankedTeam(BaseModel):
    rank: int
    team_number: int
    score: float | None  # null for a team with no prior EPA under raw EPA (ranked last)
    epa_value_source: str | None
    epa_source_state: str | None
    epa_source_event_key: str | None


class EventOrdering(BaseModel):
    model: str
    switch_point_passed: bool
    switch_time: datetime | None
    validation_status: str
    evidence: str
    teams: list[RankedTeam]


class LabelledTeams(BaseModel):
    validation_status: str
    evidence: str
    team_numbers: list[int]


class TeamComparison(BaseModel):
    validation_status: str
    teams: list[TeamStrengthView]


class EventAnalysisResponse(BaseModel):
    event_key: str
    as_of: datetime
    ordering: EventOrdering
    captain_candidates: LabelledTeams
    strongest_teams: LabelledTeams
    team_comparison: TeamComparison
    epa: EpaSourceInfo
    ranking_model_sha256: str | None


@router.get(
    "/events/{event_key}/analysis",
    response_model=EventAnalysisResponse,
    summary="Event analysis: ordering, captain candidates, strongest teams, team comparison",
    description="The frozen P5-M4 ordering policy as of a point in time. Every element carries its validation "
                "status; no playoff probability is served.",
    responses={HTTPStatus.NOT_FOUND: {"model": ErrorResponse}, HTTPStatus.UNPROCESSABLE_ENTITY: {"model": ErrorResponse}},
)
def event_analysis(
    event_key: str = Path(min_length=1),
    as_of: str | None = Query(default=None, description="ISO-8601 with offset; default: now"),
    database: Database = Depends(get_database),
    served: ServedModel | None = Depends(get_ranking_model),
    epa_source: ServedEpaSource | None = Depends(get_epa_source),
) -> EventAnalysisResponse:
    epa_source = require_epa_source(epa_source)
    when = parse_as_of(as_of)
    if not event_exists(database, event_key):
        raise event_not_found_error(event_key)
    switch = serving_switch(database, event_key, when)
    model = policy_model(switch.passed)
    if model == POLICY_M5V2 and served is None:
        raise ApiError(status_code=HTTPStatus.NOT_FOUND, code=CODE_MODEL_NOT_LOADED,
                       message="The event switch point has passed, so the policy serves M5 v2, which is not loaded.")
    scales = ScaleLookup(database)
    teams = list_teams_at_event(database, event_key)
    try:
        features = [build_team_features(database, t, event_key, when, epa_provider=epa_source.provider,
                                        scale_lookup=scales) for t in teams]
        views = [build_team_strength(database, t, event_key, when, epa_provider=epa_source.provider,
                                     scale_lookup=scales) for t in teams]
    except SilentFallbackError as exc:
        raise epa_source_incomplete_error(exc) from exc
    score = served.model.predict_rating if model == POLICY_M5V2 else RawEpaRankingBaseline().predict_rating  # type: ignore[union-attr]
    ordering = order_teams(features, score)
    by_team: dict[int, TeamFeatures] = {f.team_number: f for f in features}
    ranked = [RankedTeam(rank=o.rank, team_number=o.team_number,
                         score=o.score if o.score != float("-inf") else None,
                         epa_value_source=by_team[o.team_number].epa_value_source,
                         epa_source_state=by_team[o.team_number].epa_source_state,
                         epa_source_event_key=by_team[o.team_number].epa_source_event_key) for o in ordering]
    status, evidence = ((VALIDATED_AS_MEASURED, EVIDENCE_M5V2) if model == POLICY_M5V2
                        else (VALIDATED_RAW_EPA, EVIDENCE_RAW_EPA))
    top = [o.team_number for o in ordering[:CAPTAINS]]
    return EventAnalysisResponse(
        event_key=event_key, as_of=when,
        ordering=EventOrdering(model=model, switch_point_passed=switch.passed, switch_time=switch.switch_time,
                               validation_status=status, evidence=evidence, teams=ranked),
        captain_candidates=LabelledTeams(validation_status=VALIDATED_AS_MEASURED,
                                         evidence=EVIDENCE_CAPTAINS_SWITCH if switch.passed else EVIDENCE_CAPTAINS_PRE,
                                         team_numbers=top),
        strongest_teams=LabelledTeams(validation_status=status, evidence=f"{evidence} {STRONGEST_NOTE}",
                                      team_numbers=top),
        team_comparison=TeamComparison(validation_status=DESCRIPTIVE, teams=views),
        epa=epa_info(epa_source),
        ranking_model_sha256=served.sha256 if model == POLICY_M5V2 and served is not None else None,
    )
