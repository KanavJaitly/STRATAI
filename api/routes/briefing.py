"""P9-M4: `GET /matches/{match_key}/briefing`, the readable pre-match briefing (Phase 9).

Downstream only (P9-Q1). The route builds the pre-match report by calling the report route's own handler with the
same dependencies, so the moment, the refusals and every engine call are exactly the report's. It then turns the
report into facts and a briefing:
- the LLM formatter when it is enabled, the data egress is approved and a credential resolves, and its output passes
  every fidelity check;
- otherwise the deterministic briefing, with the reason.

No engine runs differently because of this route, and the report route is unchanged.

The response carries the facts the briefing was allowed to state, so a reader (or the dashboard) can trace every
sentence to the report.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from api.contract import error_responses
from api.dependencies import get_database, get_epa_source, get_settings, get_strategy_model, get_win_prob_model
from api.routes import common
from api.routes.pre_match_report import pre_match_report
from briefing.facts import report_facts
from briefing.llm import make_briefing
from data.config import Settings
from database.connection import Database
from ml.strategy.service import MatchNotFound, MatchNotScheduled

router = APIRouter(tags=["pre-match briefing"])


def get_briefing_client_factory() -> Callable[[], Any] | None:
    """The SDK client factory for the LLM formatter: None means the real Anthropic client. Tests override this with
    a stub; it lives here, not in api.dependencies, so the core never references the LLM layer (P9-Q1)."""
    return None

DISCLAIMER = ("A readable summary of the pre-match report. Every number, label and absence comes from the engines' "
              "report; nothing here is a new prediction. Each fact is printed in its fixed wording. In 'llm' mode a "
              "language model chose the grouping, the order and the short lead-ins; in 'deterministic' mode the "
              "layout is fixed.")


class BriefingSentenceOut(BaseModel):
    text: str
    fact_ids: list[str] = Field(description="The facts this sentence states (ids in `facts`).")


class BriefingSectionOut(BaseModel):
    heading: str
    sentences: list[BriefingSentenceOut]


class BriefingFactOut(BaseModel):
    id: str
    kind: Literal["context", "value", "absence", "not_produced", "label"]
    section: str
    statement: str = Field(description="The fact as a fixed-template sentence.")
    source: str = Field(description="The JSON path of the report field this fact comes from.")


class BriefingUsageOut(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    attempts: int | None = Field(default=None, description="Model attempts, when a server-side fallback ran (the "
                                                            "token counts are then summed over every attempt).")


class BriefingResponse(BaseModel):
    match_key: str
    event_key: str
    as_of: str = Field(description="The report's moment: min(as_of, scheduled_time).")
    mode: Literal["llm", "deterministic"] = Field(
        description="llm: arranged by the language model (grouping, order, lead-ins; the facts' wording is fixed) "
                    "and accepted by every check. deterministic: the fixed layout (the LLM is off, unapproved, "
                    "unconfigured, failed or was rejected).")
    fallback_reason: str | None = Field(
        description="Why the deterministic briefing was served (disabled, egress_not_approved, no_credential, "
                    "sdk_unavailable, api_error:<class>, refusal, truncated, no_text, invalid_json, "
                    "validation_failed:<rule>); null in llm mode.")
    model: str | None = Field(description="The model that arranged the briefing, when one was called.")
    usage: BriefingUsageOut | None = Field(description="Token usage, when a model was called.")
    sections: list[BriefingSectionOut]
    facts: list[BriefingFactOut]
    disclaimer: str = DISCLAIMER


@router.get(
    "/matches/{match_key}/briefing",
    response_model=BriefingResponse,
    summary="Readable pre-match briefing for one scheduled match (Phase 9)",
    description="The pre-match report (same moment, same engines, same refusals) as a readable briefing. With the "
                "LLM disabled, unapproved or unavailable, the deterministic briefing is served (mode "
                "'deterministic', with fallback_reason). With it, the language model arranges the facts (it never "
                "writes a value), and its arrangement is served only if it passes every check. No prediction is "
                "affected.",
    responses=error_responses({  # exactly the report route's refusals: the briefing is built through it
        HTTPStatus.NOT_FOUND: [MatchNotFound.code, common.CODE_EPA_SOURCE_NOT_LOADED],
        HTTPStatus.UNPROCESSABLE_ENTITY: [MatchNotScheduled.code, common.CODE_INVALID_AS_OF,
                                          common.CODE_EPA_SOURCE_INCOMPLETE, common.CODE_EPA_SOURCE_PENDING],
    }, validates_input=False),
)
def briefing(
    match_key: str = Path(min_length=1, description="TBA match key, e.g. 2026casj_qm12."),
    as_of: str | None = Query(default=None, description=common.AS_OF_DESCRIPTION + " The report is taken at "
                                                                                    "min(as_of, scheduled_time)."),
    database: Database = Depends(get_database),
    served: Any = Depends(get_win_prob_model),
    strategy_model: Any = Depends(get_strategy_model),
    epa_source: Any = Depends(get_epa_source),
    settings: Settings = Depends(get_settings),
    client_factory: Callable[[], Any] | None = Depends(get_briefing_client_factory),
) -> BriefingResponse:
    report = pre_match_report(match_key=match_key, as_of=as_of, database=database, served=served,
                              strategy_model=strategy_model, epa_source=epa_source).model_dump(mode="json")
    facts = report_facts(report)
    result = make_briefing(facts, enabled=settings.briefing_llm_enabled,
                           egress_approved=settings.briefing_data_egress_approved, model=settings.briefing_model,
                           max_tokens=settings.briefing_max_tokens, timeout=settings.briefing_timeout_seconds,
                           client_factory=client_factory)
    return BriefingResponse(
        match_key=report["match_key"], event_key=report["event_key"], as_of=report["as_of"], mode=result.mode,
        fallback_reason=result.reason, model=result.model, usage=BriefingUsageOut(**result.usage) if result.usage else None,
        sections=[BriefingSectionOut(heading=s.heading, sentences=[BriefingSentenceOut(text=x.text, fact_ids=list(x.fact_ids))
                                                                   for x in s.sentences]) for s in result.sections],
        facts=[BriefingFactOut(id=f.id, kind=f.kind, section=f.section, statement=f.statement, source=f.source)
               for f in facts])
