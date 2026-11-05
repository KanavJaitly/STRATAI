"""Phase 11: the team's primary and backup picks for the live draft record's current state (P11-Q1, P11-FB1).

The decision record `.agent/phase11/decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md` freezes the rule this module
implements. It has two sources, tried in a fixed order and never mixed:

1. **The P6-M7 engine, unchanged** (`ml.playoffs.service.pick_list`).
   - It runs at the record's state, for the alliance the team is on (or is projected to captain), with the served
     models.
   - When it returns, its ranking is served with the engine's own status.
   - Today it refuses at every event: the PX-1 gate failed, and the PX-2 and PX-4 records do not exist.
2. **P11-FB1, used only when the engine refuses.**
   - It ranks the available pool by the P5-M4 event-analysis ordering at the selection moment.
   - Primary: the first available team. Backups: the next max(3, m), where m is the other alliances' picks before
     this alliance's next turn.
   - It is served `not_validated`, with the engine's refusal beside it, and it shows no probability.

**Which teams are excluded.** Every unavailable team, the alliance's own members, and the projected captains of
alliances that act before this alliance's next round-1 turn. A team with no ordering position is listed as
unranked, never recommended.

**Withheld, with the exact reason, when:**
- the record has no setup;
- an action is flagged for review;
- the team is not selecting;
- the alliance has no turn left;
- the ordering itself refuses.

The previous recommendation is never presented as current. Every response carries the record sequence it reflects.

**Determinism and speed (P11-Q3).**
- The ordering and profiles at the selection moment are computed once per (event, moment, models, EPA source) and
  cached in process. A recorded action only re-filters the pool, so the warm path stays far under the 2 s target.
- The cache holds a few events and expires its entries after `CACHE_SECONDS`, so a data correction (e.g. late
  ranks) is picked up.
- Every response reports its timings.

**No LLM, no gate changes.** This module only reads the record and calls the engines. Nothing it computes reaches
the engine, the draft model or any gate. Movement explanations are fixed templates over the record.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from data.rulesets import RulesetError
from database.connection import Database
from ml.playoffs.selection import CandidateProfile, candidate_profile
from ml.playoffs.service import (
    SCOPE_REASONS,
    VALIDATED_PLAYOFF_SUCCESS,
    PickListResult,
    SelectionServiceError,
    SelectionTimeUnavailable,
    event_selection_moment,
)
from ml.playoffs.service import pick_list as engine_pick_list
from ml.ratings.statbotics_primary import SilentFallbackError
from ml.views.event_analysis import (
    POLICY_M5V2,
    VALIDATED_AS_MEASURED,
    VALIDATED_RAW_EPA,
    M5V2Required,
    analyze_event,
)
from workspaces import draft_log as dl

RULE = "P11-FB1"
SOURCE_ENGINE, SOURCE_FALLBACK = "engine_p6_m7", "fallback_p11_fb1"
NOT_VALIDATED = "not_validated"
MIN_BACKUPS = 3
CACHE_SECONDS = 600
CACHE_ENTRIES = 8
FALLBACK_REASON = (f"{RULE}: ranks available teams by the P5-M4 team-strength ordering; it is not validated as a pick "
                   "recommendation and gives no P(win event) (decision P11-Q1, 2026-11-04)")


@dataclass(frozen=True)
class Candidate:
    team_number: int
    ordering_position: int | None  # 1-based position in the P5-M4 ordering (fallback)
    profile: CandidateProfile | None
    p_win_event: float | None = None  # engine only
    p_reach_finals: float | None = None  # engine only
    configuration: tuple[int, ...] | None = None  # engine only


@dataclass
class Recommendation:
    record_seq: int
    computed_at: datetime
    status: str  # "current" | "withheld"
    withheld: tuple[str, str] | None = None
    source: str | None = None
    validation_status: str | None = None
    validation_reasons: list[str] = field(default_factory=list)
    engine_refusal: tuple[str, str] | None = None
    seed: int | None = None
    selecting_as: str | None = None  # "on_alliance" | "projected_captain"
    turns_before: int | None = None
    primary: Candidate | None = None
    backups: list[Candidate] = field(default_factory=list)
    unranked_available: list[int] = field(default_factory=list)
    excluded: list[tuple[int, str]] = field(default_factory=list)
    movement: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    timing_ms: dict[str, float] = field(default_factory=dict)
    engine_result: PickListResult | None = None


@dataclass(frozen=True)
class Ordering:
    """The P5-M4 ordering at one moment: teams strongest first, the model, its status, and each team's profile."""

    teams: tuple[int, ...]
    policy: str
    status: str
    profiles: dict[int, CandidateProfile]
    as_of: datetime
    as_of_source: str
    epa_states: tuple[str | None, ...]


# --- whose turn ----------------------------------------------------------------------------------------------------


def selecting_seed(view: dl.DraftView, team_number: int) -> tuple[int | None, str | None]:
    """The alliance whose picks are this team's to advise: the one it is on, or the one it is projected to captain."""
    for seed, alliance in enumerate(view.alliances, start=1):
        if team_number in alliance:
            return seed, "on_alliance"
    for seed, captain in view.projected_captains().items():
        if captain == team_number:
            return seed, "projected_captain"
    return None, None


def _excluded(view: dl.DraftView, seed: int, team_number: int) -> dict[int, str]:
    """Available teams this alliance cannot pick at its next turn, by the rules alone (not by any prediction)."""
    out: dict[int, str] = {team_number: "your team"}
    for member in view.alliances[seed - 1]:
        out[member] = "on your alliance"
    # A seed without a captain names one at its first turn (round 1: turn index seed - 1). If that comes before this
    # alliance's next turn, its projected captain will be on an alliance by then, whoever ends up with it.
    next_turn = view.picks_made + (view.turns_before(seed) or 0)
    for other, captain in view.projected_captains().items():
        if captain is not None and other != seed and other - 1 < next_turn and captain != team_number:
            out.setdefault(captain, f"projected to captain alliance {other} before your turn")
    return out


# --- the fallback rule (pure) ----------------------------------------------------------------------------------------


def fallback_lists(view: dl.DraftView, seed: int, team_number: int,
                   ordering: Sequence[int]) -> tuple[list[int], list[int], list[tuple[int, str]]]:
    """P11-FB1's (primary-first ranked list, unranked available teams, excluded teams) for `seed` from `view`.
    The ranked list is primary + backups: 1 + max(MIN_BACKUPS, m) teams at most."""
    available, _ = view.availability()
    excluded = _excluded(view, seed, team_number)
    candidates = [t for t in available if t not in excluded]
    position = {t: i for i, t in enumerate(ordering)}
    ranked = sorted((t for t in candidates if t in position), key=lambda t: position[t])
    unranked = sorted(t for t in candidates if t not in position)
    m = view.turns_before(seed) or 0
    return ranked[:1 + max(MIN_BACKUPS, m)], unranked, sorted(
        ((t, r) for t, r in excluded.items() if t in available), key=lambda tr: tr[0])


def movement(previous: dl.DraftView | None, current: dl.DraftView, before: Sequence[int],
             after: Sequence[int]) -> list[str]:
    """Why the list changed since the previous record state: fixed templates over the record only."""
    if previous is None or not before:
        return []
    lines: list[str] = []
    gone = [t for t in before if t not in after]
    _, unavailable = current.availability()
    for team in gone:
        reason = unavailable.get(team)
        seed = next((s for s, a in enumerate(current.alliances, 1) if team in a), None)
        if reason == "picked":
            lines.append(f"Team {team} was picked by alliance {seed}.")
        elif reason == "captain":
            lines.append(f"Team {team} is now alliance {seed}'s captain.")
        elif reason == "declined":
            lines.append(f"Team {team} declined alliance {current.declined.get(team)}.")
        elif reason == "backup":
            lines.append(f"Team {team} is a backup robot.")
        else:
            lines.append(f"Team {team} is no longer in the list.")
    if after and (not before or before[0] != after[0]):
        lines.append(f"Team {after[0]} is now first.")
    return lines


# --- the ordering, cached -----------------------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, Ordering]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def event_ordering(database: Database, event_key: str, now: datetime, *, epa_source: Any,
                   ranking: Any) -> Ordering:
    """The P5-M4 ordering and profiles at the event's selection moment (or now, while it is still ahead)."""
    moment = event_selection_moment(database, event_key)  # SelectionTimeUnavailable: no qualification schedule
    if moment > now:  # P11-FB1 orders at the selection moment only; before it there is nothing to order at
        raise SelectionTimeUnavailable(f"{event_key}'s selection moment ({moment.isoformat()}) has not come yet")
    as_of, source = moment, "selection_moment"
    key = (event_key, as_of, id(epa_source), getattr(ranking, "sha256", None))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]
    analysis = analyze_event(database, event_key, as_of, epa_provider=epa_source.provider,
                             m5v2_predict_rating=None if ranking is None else ranking.model.predict_rating)
    ordering = Ordering(
        tuple(o.team_number for o in analysis.ordering), analysis.model,
        VALIDATED_AS_MEASURED if analysis.model == POLICY_M5V2 else VALIDATED_RAW_EPA,
        {f.team_number: candidate_profile(f) for f in analysis.features}, as_of, source,
        tuple(f.epa_source_state for f in analysis.features))
    with _cache_lock:
        if len(_cache) >= CACHE_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.monotonic() + CACHE_SECONDS, ordering)
    return ordering


# --- the recommendation ----------------------------------------------------------------------------------------------


def _refusal(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (RulesetError, SelectionServiceError)):
        return exc.code, str(exc)
    if isinstance(exc, M5V2Required):
        return "model_not_loaded", "ranking_xgb_v2 (M5 v2) is not loaded, and the ordering needs it"
    if isinstance(exc, SilentFallbackError):
        return "epa_source_incomplete", str(exc)
    return "engine_error", type(exc).__name__


def _try_engine(database: Database, event_key: str, seed: int, view: dl.DraftView, now: datetime, *,
                epa_source: Any, ranking: Any, playoff_models: Any) -> tuple[PickListResult | None, tuple | None]:
    def provider() -> Any:
        if epa_source is None:
            raise SelectionServiceError("the EPA source is not loaded")
        return epa_source.provider
    try:
        return engine_pick_list(database, event_key, seed, view.draft_state(), now, epa_provider=provider,
                                m5v2_predict_rating=None if ranking is None else ranking.model.predict_rating,
                                playoff_models=playoff_models), None
    except (RulesetError, SelectionServiceError, M5V2Required, SilentFallbackError) as exc:
        return None, _refusal(exc)


def recommend(database: Database, event_key: str, view: dl.DraftView, previous: dl.DraftView | None, team_number: int,
              *, epa_source: Any, ranking: Any, playoff_models: Any,
              now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Recommendation:
    """The team's recommendations for the record state `view` (see the module docstring). `previous` is the state
    before the latest entry, for the movement explanation."""
    started = time.perf_counter()
    at = now()
    out = Recommendation(view.record_seq, at, "withheld")

    def withhold(code: str, message: str) -> Recommendation:
        out.withheld = (code, message)
        out.timing_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
        return out

    if view.setup is None:
        return withhold("not_configured", "the record has no setup")
    if view.flagged:
        return withhold("record_needs_review", f"{len(view.flagged)} recorded action(s) became invalid after a "
                                               "correction or a new setup; correct them before picks are recommended")
    seed, how = selecting_seed(view, team_number)
    if seed is None:
        return withhold("team_not_selecting", f"team {team_number} is not on an alliance and is not projected to "
                                              "captain one, so it has no picks to make")
    out.seed, out.selecting_as = seed, how
    out.turns_before = view.turns_before(seed)
    if out.turns_before is None:
        return withhold("no_remaining_turn", f"alliance {seed} has no turn left in this draft")

    engine, refusal = _try_engine(database, event_key, seed, view, at, epa_source=epa_source, ranking=ranking,
                                  playoff_models=playoff_models)
    out.timing_ms["engine"] = round((time.perf_counter() - started) * 1000, 1)
    if engine is not None:
        available, _ = view.availability()
        excluded = _excluded(view, seed, team_number)
        ranked = [p for p in engine.recommendation.ranked if p.team_number in available and p.team_number not in excluded]
        keep = 1 + max(MIN_BACKUPS, out.turns_before)
        candidates = [Candidate(p.team_number, None, p.profile, p.p_win_event, p.p_reach_finals, p.configuration)
                      for p in ranked[:keep]]
        out.status, out.source = "current", SOURCE_ENGINE
        out.validation_status = engine.recommendation.probability_status
        out.validation_reasons = list(SCOPE_REASONS) if out.validation_status == VALIDATED_PLAYOFF_SUCCESS else []
        out.excluded = sorted(((t, r) for t, r in excluded.items() if t in available), key=lambda tr: tr[0])
        out.primary, out.backups = (candidates[0] if candidates else None), candidates[1:]
        out.engine_result = engine
        out.provenance = {"engine": "P6-M7", "ruleset_sha256": engine.ruleset_sha256,
                          "ruleset_variant": engine.ruleset_variant, "ordering_policy": engine.ordering_policy,
                          "selection_moment": engine.moment.isoformat(), "record_seq": view.record_seq}
        out.timing_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
        return out

    out.engine_refusal = refusal
    if epa_source is None:
        return withhold("epa_source_not_loaded", "the EPA source is not loaded, so the team-strength ordering the "
                                                 f"fallback rule {RULE} uses cannot be computed")
    try:
        ordering = event_ordering(database, event_key, at, epa_source=epa_source, ranking=ranking)
    except (M5V2Required, SilentFallbackError, SelectionTimeUnavailable) as exc:
        code, message = _refusal(exc)
        return withhold(code, f"the team-strength ordering {RULE} uses is unavailable: {message}")
    out.timing_ms["ordering"] = round((time.perf_counter() - started) * 1000, 1)
    ranked, unranked, excluded = fallback_lists(view, seed, team_number, ordering.teams)
    position = {t: i for i, t in enumerate(ordering.teams, start=1)}
    candidates = [Candidate(t, position[t], ordering.profiles.get(t)) for t in ranked]
    if previous is not None and previous.setup is not None and not previous.flagged:
        prev_seed, _ = selecting_seed(previous, team_number)
        before = fallback_lists(previous, prev_seed, team_number, ordering.teams)[0] if prev_seed == seed else []
        out.movement = movement(previous, view, before, ranked)
    out.status, out.source, out.validation_status = "current", SOURCE_FALLBACK, NOT_VALIDATED
    out.validation_reasons = [FALLBACK_REASON,
                              f"ordering: {ordering.policy}, served as {ordering.status} as a team-strength ordering",
                              f"engine_refused: {refusal[0]}: {refusal[1]}"]
    out.primary, out.backups = (candidates[0] if candidates else None), candidates[1:]
    out.unranked_available, out.excluded = unranked, excluded
    out.provenance = {"rule": RULE, "decision": ".agent/phase11/decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md",
                      "ordering_policy": ordering.policy, "ordering_as_of": ordering.as_of.isoformat(),
                      "ordering_as_of_source": ordering.as_of_source,
                      "ranking_model_sha256": getattr(ranking, "sha256", None) if ordering.policy == POLICY_M5V2
                      else None, "record_seq": view.record_seq}
    if not candidates:
        out.status, out.withheld = "withheld", ("no_candidates", "no available team can be recommended")
    out.timing_ms["total"] = round((time.perf_counter() - started) * 1000, 1)
    return out


__all__ = ["Candidate", "Ordering", "RULE", "Recommendation", "SOURCE_ENGINE", "SOURCE_FALLBACK", "clear_cache",
           "event_ordering", "fallback_lists", "movement", "recommend", "selecting_seed"]
