"""P11A in Phase 11: the experimental expected-score plan and team profiles for a team's live draft record.

**What it is.** The P11A plan (`ml.alliance.planner`) for the record's current state, read from the event's newest
snapshot in `P11A_SNAPSHOT_DIR` (`ml.alliance.snapshot`, written by `python -m scripts.p11a_snapshot export`).
- The spec (docs/P11-RecommendationIntelligence.md) is PROPOSED, not approved. Implementation was authorised on
  2026-11-06 (.agent/phase11/decisions/P11A_IMPLEMENTATION_START_2026-11-06.md).
- Every plan is labelled `experimental`, `not_validated`, `not_calibrated`, with no win probability.

**What it is not.** It does not replace, reorder or feed `/recommendations`.
- The record's recommendation is still P11-Q1's: the P6-M7 engine when it serves, else P11-FB1. That route and its
  locked contract are unchanged.
- The plan is a separate, additive operation. Promoting it into `/recommendations` would be a change to P11-Q1 and
  needs a human decision (docs/phase11.md, "P11A").

**Availability** comes only from the record:
- the record's own rules (`DraftView.availability()`);
- Phase 11's `draft_recommendations.selectable_teams`, the one shared definition of who the selecting alliance may
  pick at its next turn (P11-FB1 and the P6-M7 branch use it too), so they never disagree about who is pickable;
- these include the captain rule's projection of lower seeds' captains, a deterministic consequence of the rules
  (reason given), not a prediction of anyone's choice.

**Gates** (withheld with a code, HTTP 200, as `/recommendations` does): no setup, record needs review, no snapshot
folder or snapshot, an altered or leaking snapshot, no approved scoring configuration or GameSpec, an unreliable
fit, or a team without data.

Workspace isolation and permissions are those of the record: `live_draft.load_view_with_previous` reads only the
session's workspace and requires `alliance_selection`.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.connection import Database
from ml.alliance.planner import DraftPosition, PlanWithheld, build_plan
from ml.alliance.profile import team_profile
from ml.alliance.snapshot import EventSnapshot, SnapshotError, latest_snapshot_path
from workspaces import draft_log as dl
from workspaces import live_draft
from workspaces.draft_recommendations import selectable_teams, selecting_seed
from workspaces.sessions import SessionContext

SOURCE = "p11a_expected_score_plan"
RELATION = ("Experimental and separate from /recommendations, which still follow P11-Q1 (the P6-M7 engine when it "
            "serves, else P11-FB1). This plan ranks by expected alliance score in points, not by chance of winning.")
_CACHE_ENTRIES = 4
_cache: OrderedDict[tuple[str, int, int], EventSnapshot] = OrderedDict()
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _snapshot(directory: str | None, event_key: str) -> EventSnapshot:
    """The event's newest snapshot, cached by (file, mtime, size). PlanWithheld when there is none or it is bad."""
    if not directory:
        raise PlanWithheld("snapshot_unavailable", "no P11A snapshot folder is configured (P11A_SNAPSHOT_DIR)")
    path = latest_snapshot_path(directory, event_key)
    if path is None:
        raise PlanWithheld("snapshot_unavailable", f"no P11A snapshot exists for {event_key}")
    stat = Path(path).stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        snap = EventSnapshot.load(path)
    except SnapshotError as exc:
        raise PlanWithheld("snapshot_invalid", f"{path.name}: {exc.code}: {exc}") from None
    if snap.event_key != event_key:
        raise PlanWithheld("snapshot_invalid", f"{path.name} holds {snap.event_key}, not {event_key}")
    with _lock:
        _cache[key] = snap
        while len(_cache) > _CACHE_ENTRIES:
            _cache.popitem(last=False)
    return snap


def position_from_view(view: dl.DraftView, team_number: int) -> DraftPosition:
    """The planner's input from the replayed record. PlanWithheld when the record cannot support a plan."""
    if view.setup is None:
        raise PlanWithheld("not_configured", "the record has no setup")
    if view.flagged:
        raise PlanWithheld("record_needs_review", f"{len(view.flagged)} recorded action(s) became invalid after a "
                                                  "correction or a new setup; correct them first")
    available, unavailable = view.availability()
    order = view.order()
    seed, how = selecting_seed(view, team_number)
    if seed is None:  # not selecting: the alliances this team could join
        others = []
        projected = view.projected_captains()
        for other, alliance in enumerate(view.alliances, start=1):
            if view.turns_before(other) is None:
                continue
            members = tuple(alliance) or ((projected.get(other),) if projected.get(other) is not None else ())
            if members and team_number not in members:
                others.append((other, members))
        return _with_rules(view, DraftPosition(team_number, view.record_seq, "non_captain", None, (), 0, None,
                                               tuple(t for t in available if t != team_number), dict(unavailable),
                                               tuple(others)))
    alliance = view.alliances[seed - 1]
    members = tuple(alliance) if alliance else (team_number,)
    remaining = sum(1 for s in order[view.picks_made:] if s == seed)
    turns_before = view.turns_before(seed)
    if how == "projected_captain":
        mode = "projected_captain"
    else:
        mode = "captain" if alliance and alliance[0] == team_number else "on_alliance"
    if turns_before is None or remaining == 0:
        mode = "no_remaining_turn"
    pickable, excluded = selectable_teams(view, seed, team_number)
    blocked = {**unavailable, **excluded}
    return _with_rules(view, DraftPosition(team_number, view.record_seq, mode, seed, members, remaining, turns_before,
                                           tuple(pickable), blocked))


def _with_rules(view: dl.DraftView, position: DraftPosition) -> DraftPosition:
    """Spec H4: the plan names the selection rules it was computed under."""
    rules = view.setup.rules
    return dataclasses.replace(position, ruleset_sha256=rules.ruleset_sha256, rules_source=rules.source)


def _envelope(record_id: int, view: dl.DraftView, started: float) -> dict[str, Any]:
    return {"record_id": record_id, "record_seq": view.record_seq, "computed_at": datetime.now(timezone.utc),
            "source": SOURCE, "experimental": True, "relation_to_recommendations": RELATION, "status": "withheld",
            "withheld": None, "plan": None, "timing_ms": {"total": round((time.perf_counter() - started) * 1000, 1)}}


def plan_for_record(database: Database, context: SessionContext, record_id: int, *,
                    snapshot_dir: str | None) -> dict[str, Any]:
    """The team's P11A plan for the record's current state (withheld with the reason when a gate is unmet)."""
    started = time.perf_counter()
    row, (view, _previous) = live_draft.load_view_with_previous(database, context, record_id)
    out = _envelope(record_id, view, started)
    try:
        position = position_from_view(view, context.team_number)
        snap = _snapshot(snapshot_dir, row[2])
        out["plan"] = build_plan(snap, position)
        out["status"] = "current"
    except PlanWithheld as exc:
        out["withheld"] = {"code": exc.code, "message": exc.message}
    out["timing_ms"]["total"] = round((time.perf_counter() - started) * 1000, 1)
    return out


def profile_for_record(database: Database, context: SessionContext, record_id: int, team_number: int, *,
                       snapshot_dir: str | None) -> dict[str, Any]:
    """One team's P11A profile at the record's event, with alliance fit against the session's team."""
    started = time.perf_counter()
    row, (view, _previous) = live_draft.load_view_with_previous(database, context, record_id)
    out = _envelope(record_id, view, started)
    out.pop("plan")
    out["profile"] = None
    try:
        snap = _snapshot(snapshot_dir, row[2])
        our = context.team_number if context.team_number in snap.teams() else None
        out["profile"] = team_profile(snap, team_number, our_team=our)
        out["status"] = "current"
    except PlanWithheld as exc:
        out["withheld"] = {"code": exc.code, "message": exc.message}
    out["timing_ms"]["total"] = round((time.perf_counter() - started) * 1000, 1)
    return out


__all__ = ["RELATION", "SOURCE", "clear_cache", "plan_for_record", "position_from_view", "profile_for_record"]
