"""P7-M7: pre-match report data -- one structured aggregate per scheduled match, assembled from existing engines.

Everything is taken at one moment, `min(as_of, scheduled_time)`, from point-in-time sources only (P7-Q12):
- each team's strength: the P5-M3 view (`build_team_strength`), which recomputes Phase 3 statistics before the
  moment and carries each team's EPA components (auto / teleop / endgame) with provenance;
- each alliance's synergy: the Phase 4 M9 heuristic (`alliance_synergy`) on the same features;
- the M6/M7 win probability input row (`build_match_feature_row`); the caller applies the model and its display
  and gating rule, in its own fields (P7-A7);
- each side's strategy: the P6-M11 engine with the P6-M10 model, through the P7-M5 service (`context_for_match`),
  so roles come from the engine's recommendation and its baseline.

The stored `team_metrics` snapshot is never read: it includes later matches. No new model, heuristic or derivation
rule is introduced; every report item no engine produces is an explicit absence (NOT_PRODUCED). Nothing here
generates free text: every string is an engine label, an identifier, or a constant documented in docs/phase7.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from database.connection import Database
from ml.features.assembler import MatchFeatureRow, build_match_feature_row
from ml.features.roster import get_match_competition_level, get_match_event_and_scheduled_time
from ml.features.scale import ScaleLookup
from ml.strategy.engine import Recommendation, StrategyEngine
from ml.strategy.service import (
    MatchNotFound,
    MatchNotScheduled,
    StrategyContext,
    StrategyContextError,
    context_for_match,
    evaluate_typed,
)
from ml.synergy.score import AllianceSynergyScore, alliance_synergy
from ml.views.strength import TeamStrengthView, build_team_strength

NOT_PRODUCED_BY_ANY_ENGINE = "not_produced_by_any_engine"
# The ROADMAP Phase 8 report items no engine produces today, with what each would mean (P7-Q12). A derivation rule
# for any of them needs its own dated decision; until then each is served as null with NOT_PRODUCED_BY_ANY_ENGINE.
NOT_PRODUCED = {
    "strengths_and_weaknesses": "Per-team labels of what a team does well or poorly relative to the field.",
    "defensive_threats": "Opposing robots likely to play effective defense against this alliance.",
    "key_risks": "Events that would most reduce this alliance's chance of winning (e.g. a mechanism failure).",
    "predicted_flow": "The expected sequence of the match by phase (auto, teleop, endgame).",
    "critical_matchups": "Robot-versus-robot interactions that most influence the outcome.",
    "key_success_factors": "The conditions under which this alliance wins.",
}
SCOPE_QUALIFICATION, SCOPE_PLAYOFF, SCOPE_UNSPECIFIED = "qualification", "playoff", "unspecified"


@dataclass(frozen=True)
class Absence:
    """Why a report part is absent: a stable `code` to match on, and a `reason` to show."""

    code: str
    reason: str


SYNERGY_ALLIANCE_INCOMPLETE = Absence("alliance_incomplete", "synergy needs three teams on the alliance")
STRATEGY_MODEL_NOT_LOADED = Absence("model_not_loaded", "the P6-M10 strategy model is not pinned/loadable")
# The P7-M5 service's refusals of a scheduled match (match_context_unknown and alliance_incomplete are raised before
# the engine runs; mixed_season_scale is the engine's own refusal).
STRATEGY_REFUSALS = {
    "match_context_unknown": "the match has no competition level, so it is neither a qualification nor a known "
                             "playoff match",
    "alliance_incomplete": "the strategy model needs three teams per alliance",
    "mixed_season_scale": "the six teams disagree on the season scale, which the strategy model cannot combine",
}


@dataclass(frozen=True)
class SideStrategy:
    side: str
    recommendation: Recommendation


@dataclass(frozen=True)
class PreMatchInputs:
    """The engine outputs one report is serialized from; each absent part carries its reason."""

    match_key: str
    event_key: str
    competition_level: str | None
    scheduled_time: datetime
    moment: datetime
    probability_scope: str
    row: MatchFeatureRow
    strengths: list[tuple[str, TeamStrengthView]]  # (alliance colour, view), red first
    synergy: dict[str, AllianceSynergyScore | None]
    synergy_absent: dict[str, Absence | None]
    strategy_context: StrategyContext | None
    strategies: list[SideStrategy]
    strategy_absent: Absence | None


def pre_match_inputs(database: Database, match_key: str, as_of: datetime, *, epa_provider: Any,
                     strategy_model: Any | None) -> PreMatchInputs:
    """Assemble every engine output for one scheduled match at `min(as_of, scheduled_time)`.

    Raises MatchNotFound / MatchNotScheduled (the whole report needs a scheduled match) and SilentFallbackError
    (the EPA source refuses). A strategy-side refusal (no model, no competition level, not 3v3, mixed season scale)
    becomes `strategy_absent`; the rest of the report is still served."""
    found = get_match_event_and_scheduled_time(database, match_key)
    if found is None:
        raise MatchNotFound(match_key)
    event_key, scheduled = found
    if scheduled is None:
        raise MatchNotScheduled(match_key)
    moment = min(as_of, scheduled)
    level = get_match_competition_level(database, match_key)
    scope = SCOPE_QUALIFICATION if level == "qualification" else (SCOPE_PLAYOFF if level else SCOPE_UNSPECIFIED)
    scales = ScaleLookup(database)
    row = build_match_feature_row(database, match_key, moment, epa_provider=epa_provider, scale_lookup=scales)
    strengths = [(colour, build_team_strength(database, team.team_number, event_key, moment,
                                              epa_provider=epa_provider, scale_lookup=scales))
                 for colour, teams in (("red", row.red_teams), ("blue", row.blue_teams)) for team in teams]
    synergy: dict[str, AllianceSynergyScore | None] = {}
    synergy_absent: dict[str, Absence | None] = {}
    for colour, teams in (("red", row.red_teams), ("blue", row.blue_teams)):
        complete = len(teams) == 3
        synergy[colour] = alliance_synergy(*teams) if complete else None
        synergy_absent[colour] = None if complete else SYNERGY_ALLIANCE_INCOMPLETE

    context, strategies, absent = None, [], None
    if strategy_model is None:
        absent = STRATEGY_MODEL_NOT_LOADED
    else:
        try:
            context = context_for_match(database, match_key, epa_provider=epa_provider, as_of=moment, row=row)
            engine = StrategyEngine(strategy_model)
            for side in ("red", "blue"):
                strategies.append(SideStrategy(side, evaluate_typed(
                    context.context, lambda side=side: engine.recommend(context.context, side))))
        except StrategyContextError as exc:
            context, strategies = None, []
            absent = Absence(exc.code, STRATEGY_REFUSALS.get(exc.code, str(exc)))
    return PreMatchInputs(match_key, event_key, level, scheduled, moment, scope, row, strengths, synergy,
                          synergy_absent, context, strategies, absent)


__all__ = [
    "Absence", "NOT_PRODUCED", "NOT_PRODUCED_BY_ANY_ENGINE", "PreMatchInputs", "SCOPE_PLAYOFF", "SCOPE_QUALIFICATION",
    "SCOPE_UNSPECIFIED", "STRATEGY_MODEL_NOT_LOADED", "STRATEGY_REFUSALS", "SYNERGY_ALLIANCE_INCOMPLETE",
    "SideStrategy", "pre_match_inputs",
]
