"""P7-M5: build the strategy engine's MatchContext for a scheduled match or a hypothetical alliance, and evaluate
with the engine's own refusals made typed.

The P6-M11 engine (ml.strategy.engine) and the P6-M10 model (ml.strategy.outcome) are used unchanged. This module
only gathers their inputs, the way the P6-M12 / P6-M13 scripts did inline:

- **Scheduled match.** Features as of the match's own `scheduled_time` (what was knowable before it), the match's
  competition level, and the coach observations recorded before that moment.
- **Hypothetical alliance.** Three teams per side at an event, the caller's explicit `match_context`
  (qualification or playoff), and features and coach observations as of `as_of`.

**One context for both strategy paths.** The AI recommender and every coach assessment for the same match receive
the identical context, including the same `load_coach_observations(database, event_key, as_of)` output (P6-DM2).

**Typed errors, in the engine's own order** (docs/P7Milestones.md standing rules; R14). The engine checks the
strategies, then answers a playoff context (no probability, `playoff_model_unavailable`), then answers missing
inputs (`insufficient_data`), and only then requires one season scale. So `MixedSeasonScale` is raised only where
the engine itself would raise; every other `ValueError` from the engine propagates as a fault.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeVar

from database.connection import Database
from ml.features.assembler import MatchFeatureRow, TeamFeatures, build_match_feature_row, build_team_features
from ml.features.roster import get_match_competition_level, get_match_event_and_scheduled_time
from ml.features.scale import ScaleLookup
from ml.strategy.coach_inputs import load_coach_observations
from ml.strategy.outcome import QUALIFICATION, MatchContext, missing_inputs

PLAYOFF = "playoff"


class StrategyContextError(Exception):
    """A request that cannot become a strategy-engine context. `code` is the API error code."""

    code = "strategy_context_error"


class MatchNotFound(StrategyContextError):
    code = "match_not_found"


class MatchNotScheduled(StrategyContextError):
    """The match has no scheduled time, so no pre-match moment exists to evaluate it at."""

    code = "match_not_scheduled"


class MatchContextUnknown(StrategyContextError):
    """The match has no competition level, so it is neither a qualification nor a known playoff match."""

    code = "match_context_unknown"


class AllianceIncomplete(StrategyContextError):
    """The scheduled match does not have three teams per alliance (the engine needs 3v3)."""

    code = "alliance_incomplete"


class MixedSeasonScale(StrategyContextError):
    """The six teams' features disagree on the season scale, which the engine refuses (normalized units)."""

    code = "mixed_season_scale"


@dataclass(frozen=True)
class StrategyContext:
    """The engine's MatchContext, plus what the response reports about it."""

    context: MatchContext
    match_key: str | None
    event_key: str
    as_of: datetime
    match_context: str  # "qualification" or "playoff" (the engine's comp_level, as the API names it)
    competition_level: str | None  # the scheduled match's TBA level, or None for a hypothetical
    observations_applied: int
    observations_invalid_ignored: int


def _observations(database: Database, event_key: str, as_of: datetime):
    """Coach observations both observed and stored before as_of (P7-D3): a submission stored later, even if
    back-dated, can never change an evaluation of an earlier moment."""
    return load_coach_observations(database, event_key, as_of, landed_before=as_of)


def context_for_match(database: Database, match_key: str, *, epa_provider: Any,
                      as_of: datetime | None = None, row: MatchFeatureRow | None = None) -> StrategyContext:
    """The context for a scheduled match, as of its own scheduled time (pre-match), or as of an earlier `as_of`
    (P7-M7: `min(as_of, scheduled_time)`; a later `as_of` never moves the moment past the match). `row` may pass
    in this match's feature row already built at exactly that moment (the pre-match report), so it is not rebuilt."""
    found = get_match_event_and_scheduled_time(database, match_key)
    if found is None:
        raise MatchNotFound(match_key)
    event_key, scheduled = found
    if scheduled is None:
        raise MatchNotScheduled(match_key)
    if as_of is not None:
        scheduled = min(as_of, scheduled)
    level = get_match_competition_level(database, match_key)
    if level is None:
        raise MatchContextUnknown(match_key)
    if row is None or row.match_key != match_key or row.as_of != scheduled:
        row = build_match_feature_row(database, match_key, scheduled, epa_provider=epa_provider,
                                      scale_lookup=ScaleLookup(database))
    if len(row.red_teams) != 3 or len(row.blue_teams) != 3:
        raise AllianceIncomplete(match_key)
    observations, invalid = _observations(database, event_key, scheduled)
    comp_level = QUALIFICATION if level == QUALIFICATION else level
    context = MatchContext(tuple(row.red_teams), tuple(row.blue_teams), comp_level=comp_level,
                           observations=observations)
    return StrategyContext(context, match_key, event_key, scheduled,
                           QUALIFICATION if level == QUALIFICATION else PLAYOFF, level, len(observations), invalid)


def context_for_alliances(database: Database, event_key: str, red: Sequence[int], blue: Sequence[int],
                          match_context: Literal["qualification", "playoff"], as_of: datetime, *,
                          epa_provider: Any) -> StrategyContext:
    """The context for a hypothetical 3v3 pairing at an event (the caller has checked the event and roster)."""
    scales = ScaleLookup(database)

    def teams(numbers: Sequence[int]) -> tuple[TeamFeatures, ...]:
        return tuple(build_team_features(database, n, event_key, as_of, epa_provider=epa_provider,
                                         scale_lookup=scales) for n in numbers)

    observations, invalid = _observations(database, event_key, as_of)
    comp_level = QUALIFICATION if match_context == QUALIFICATION else PLAYOFF
    context = MatchContext(teams(red), teams(blue), comp_level=comp_level, observations=observations)
    return StrategyContext(context, None, event_key, as_of, match_context, None, len(observations), invalid)


T = TypeVar("T")


def engine_scale_would_fail(context: MatchContext) -> bool:
    """True exactly when the engine would reach its season-scale check and fail it: a qualification context with
    every input present whose six teams disagree on the scale (ml.strategy.outcome evaluate's order)."""
    if context.comp_level != QUALIFICATION or missing_inputs(context):
        return False
    return len({t.score_scale for t in (*context.red_teams, *context.blue_teams)}) != 1


def evaluate_typed(context: MatchContext, call: Callable[[], T]) -> T:
    """Run an engine call; turn the engine's season-scale refusal into MixedSeasonScale. StrategyError and any other
    ValueError propagate unchanged (the first is the caller's 4xx, the rest are faults)."""
    try:
        return call()
    except ValueError as exc:
        from ml.strategy.representation import StrategyError

        if not isinstance(exc, StrategyError) and engine_scale_would_fail(context):
            raise MixedSeasonScale(str(exc)) from exc
        raise


__all__ = [
    "AllianceIncomplete", "MatchContextUnknown", "MatchNotFound", "MatchNotScheduled", "MixedSeasonScale",
    "PLAYOFF", "StrategyContext", "StrategyContextError", "context_for_alliances", "context_for_match",
    "engine_scale_would_fail", "evaluate_typed",
]
