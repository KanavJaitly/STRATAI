"""P5-M2: the live-refreshed EPA provider (.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md, frozen at P5-M0).

What it implements, section by section:

* **§3 as_of semantics.**
  - Live mode reads the newest snapshot created before as_of, and counts a record only if its `retrieved_at`
    is before as_of.
  - Selection is D13 over canonical facts, which are re-read at every refresh.
  - A Statbotics value is servable only when max(D18 `available_at` (A1/A2), `retrieved_at`) < as_of.
  - A STRATAI fallback value is servable only when max(STRATAI `available_at`, `event_end` + 72 h) < as_of.
* **§5 source states (P5-D2).**
  - Served: `current` / `stale` (statbotics) and `fallback_stratai` (stratai_fallback,
    `fallback_reason` = statbotics_unprocessed_72h).
  - Refused: `pending` (EpaSourcePendingError, `epa_source_pending`) and `unavailable`
    (EpaSourceUnavailableError, `epa_source_incomplete`).
  - Absent: `withheld_no_prior_event`.
  - An unprocessed record is never a Statbotics value.
* **§6 Option A (P5-D1).** The fallback is decided per team-event, at 72 h after the source event's end. There is
  no event-scoped fallback.
* **§7 provenance.** Every served value carries its state, `snapshot_id`, `retrieved_at`, raw sha256, D18 rule,
  and (for fallbacks) the STRATAI replay fingerprint.
* **§9 / §10 simulated retrieval.**
  - In `SimulatedRetrieval`, each root record is retrieved at a scheduled time: frozen D18 availability (L1), or
    `event_end` + lag (L2, L4, P5-M6).
  - Every simulated output is labelled with its schedule.

**Open decision Q1** (.agent/phase5/M02_DECISION_REQUIRED.md). The design does not say what happens to a D13
candidate whose processed record is not yet A1/A2-available. That choice is the required `a1a2_policy`:

| Policy | Behaviour |
|---|---|
| `d18_skip` | D18's skip: the next D13 candidate is considered. In simulation the check runs on the scheduled record before its retrieval |
| `literal_state` | §3.5 read literally: the lookup is refused as `unavailable` |

There is no default. Production adoption (P5-D3) is a recorded human decision, so this provider is never selected
implicitly.

**T_w1 / T_end.** These are computed exactly as D18 does (ml.ratings.d18_source), over the snapshot in use. A
season's T_end exists only for seasons the caller lists as concluded: an A1 value is Statbotics' season-end
value, servable only after the season ends.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Literal, Protocol

from ml.ratings.epa_states import CURRENT, FALLBACK_STRATAI, STALE
from ml.ratings.live_snapshots import LiveRecord, SnapshotLog
from ml.ratings.provider import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    StrataiTeamEventValue,
    TeamEventEpa,
    TeamEventFacts,
    Unavailable,
    _d13_order,
)
from ml.ratings.statbotics_primary import (
    RULE_A1_SEASON_END,
    VALUE_SOURCE_FALLBACK,
    VALUE_SOURCE_STATBOTICS,
    SilentFallbackError,
)

LIVE_EPA_SOURCE = "p5_live_statbotics"
DESIGN = ".agent/phase5/LIVE_EPA_REFRESH_DESIGN.md"
FALLBACK_DELAY = timedelta(hours=72)  # P5-D1
FALLBACK_REASON = "statbotics_unprocessed_72h"
A1A2_D18_SKIP, A1A2_LITERAL_STATE = "d18_skip", "literal_state"
A1A2Policy = Literal["d18_skip", "literal_state"]
LIVE_REFRESH_NOT_YET_VALIDATED = "live_refresh_not_yet_validated"
REASON_PENDING, REASON_UNAVAILABLE = "pending", "unavailable"


class EpaSourceUnavailableError(SilentFallbackError):
    """§5 `unavailable`: the D13 candidate has no servable value from either source (refused)."""


class EpaSourcePendingError(SilentFallbackError):
    """§5 `pending`: the candidate ended < 72 h ago and Statbotics has not processed it (refused)."""


@dataclass(frozen=True)
class SnapshotView:
    """What one lookup may see at its as_of: one snapshot, its records, and its health."""

    snapshot_id: str
    records: Callable[[int, str], LiveRecord | None]  # the record retrieved before as_of, if any
    probe: Callable[[int, str], LiveRecord | None]  # what the A1/A2 skip check may consult
    healthy: bool
    snapshot_retrieved_at: str | None
    mode: str  # "live" or "simulated:<schedule>"
    is_root: bool


class Retrieval(Protocol):
    def view(self, as_of: datetime) -> SnapshotView: ...

    def all_records(self) -> dict[tuple[int, str], LiveRecord]: ...


@dataclass
class LiveRetrieval:
    """§3.1 over a real snapshot log: newest snapshot created before as_of; records retrieved before as_of."""

    log: SnapshotLog

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        entries = self.log.entries()
        self._snapshots = [(datetime.fromisoformat(e["created_at"]), e["snapshot_id"])
                           for e in entries if e["kind"] == "snapshot"]
        self._root = self._snapshots[0][1] if self._snapshots else None
        self._refreshes = [(datetime.fromisoformat(e["started_at"]), bool(e["ok"]))
                           for e in entries if e["kind"] == "refresh"]
        self._records: dict[str, dict[tuple[int, str], LiveRecord]] = {}

    def _records_of(self, snapshot_id: str) -> dict[tuple[int, str], LiveRecord]:
        if snapshot_id not in self._records:
            self._records[snapshot_id] = self.log.records(snapshot_id)
        return self._records[snapshot_id]

    def view(self, as_of: datetime) -> SnapshotView:
        eligible = [(created, sid) for created, sid in self._snapshots if created < as_of]
        if not eligible:
            return SnapshotView("none", lambda t, e: None, lambda t, e: None, True, None, "live", False)
        created, snapshot_id = eligible[-1]
        records = self._records_of(snapshot_id)

        def visible(team: int, event_key: str) -> LiveRecord | None:
            record = records.get((team, event_key))
            return record if record is not None and record.retrieved_at < as_of else None

        attempts = [ok for started, ok in self._refreshes if started < as_of]
        return SnapshotView(snapshot_id, visible, visible, not attempts or attempts[-1], created.isoformat(),
                            "live", snapshot_id == self._root)

    def all_records(self) -> dict[tuple[int, str], LiveRecord]:
        return self._records_of(self._snapshots[-1][1]) if self._snapshots else {}


Schedule = Callable[[LiveRecord, datetime | None, datetime], datetime]  # (record, d18 available_at, event_end)


def frozen_d18_schedule(record: LiveRecord, d18_available: datetime | None, event_end: datetime) -> datetime:
    """L1: retrieved_at = the D18 availability (unprocessed or invalid records: the event's end)."""
    return d18_available if d18_available is not None else event_end


def lag_schedule(hours: float) -> Schedule:
    """L2 / L4 / P5-M6: every record is retrieved at event_end + lag."""

    def schedule(record: LiveRecord, d18_available: datetime | None, event_end: datetime) -> datetime:
        return event_end + timedelta(hours=hours)

    schedule.__name__ = f"lag_{hours:g}h"
    return schedule


@dataclass
class SimulatedRetrieval:
    """§9's labelled simulated-retrieval mode over the root snapshot (history cannot be re-retrieved)."""

    snapshot_id: str
    root_records: dict[tuple[int, str], LiveRecord]
    schedule: Schedule
    retrieved_at: dict[tuple[int, str], datetime] = field(default_factory=dict)  # filled by the provider

    def set_schedule(self, retrieved_at: dict[tuple[int, str], datetime]) -> None:
        """The provider's scheduled retrieval times; each record then carries its simulated retrieved_at."""
        self.retrieved_at = retrieved_at
        self._scheduled = {key: replace(self.root_records[key], retrieved_at=when) for key, when in retrieved_at.items()}

    def view(self, as_of: datetime) -> SnapshotView:
        scheduled = getattr(self, "_scheduled", {})

        def visible(team: int, event_key: str) -> LiveRecord | None:
            record = scheduled.get((team, event_key))
            return record if record is not None and record.retrieved_at < as_of else None

        def probe(team: int, event_key: str) -> LiveRecord | None:
            return self.root_records.get((team, event_key))

        return SnapshotView(self.snapshot_id, visible, probe, True, None,
                            f"simulated:{getattr(self.schedule, '__name__', 'schedule')}", True)

    def all_records(self) -> dict[tuple[int, str], LiveRecord]:
        return self.root_records


def week_one_and_season_end(records: dict[tuple[int, str], LiveRecord], event_last_match: dict[str, datetime],
                            event_season: dict[str, int], concluded_seasons: set[int]
                            ) -> tuple[dict[int, datetime], dict[int, datetime]]:
    """D18's T_w1 (last completed match at events whose records are all ("Completed", 1)) and T_end (the
    season's last completed match), the latter only for concluded seasons."""
    meta: dict[str, set[tuple[str, int | None]]] = {}
    for (team, event_key), record in records.items():
        meta.setdefault(event_key, set()).add((record.status, record.week))
    week_one: dict[int, datetime] = {}
    season_end: dict[int, datetime] = {}
    for event_key, last in event_last_match.items():
        season = event_season[event_key]
        if season in concluded_seasons:
            season_end[season] = max(season_end.get(season, last), last)
        if meta.get(event_key) == {("Completed", 1)}:
            week_one[season] = max(week_one.get(season, last), last)
    return week_one, season_end


@dataclass
class LiveStatboticsEpa:
    """The P5-M2 provider; see the module docstring."""

    retrieval: Retrieval
    facts: dict[int, list[TeamEventFacts]]
    event_end: dict[str, datetime]  # §1: the event's last completed match (canonical)
    week_one_complete: dict[int, datetime]
    season_end: dict[int, datetime]
    stratai: dict[tuple[int, str], StrataiTeamEventValue]
    stratai_info: dict[str, Any]
    a1a2_policy: A1A2Policy
    provenance_info: dict[str, Any] = field(default_factory=dict)
    diagnostics: Counter = field(default_factory=Counter)
    source: str = LIVE_EPA_SOURCE

    def __post_init__(self) -> None:
        if self.a1a2_policy not in (A1A2_D18_SKIP, A1A2_LITERAL_STATE):
            raise ValueError(f"a1a2_policy must be chosen explicitly (open decision Q1), got {self.a1a2_policy!r}")
        self._ordered = {
            team: sorted((f for f in items if f.end_instant is not None and f.last_completed_match is not None),
                         key=_d13_order)
            for team, items in self.facts.items()
        }
        self._facts_by_key = {(team, f.event_key): f for team, items in self.facts.items() for f in items}
        if isinstance(self.retrieval, SimulatedRetrieval):
            scheduled = {}
            for key, record in self.retrieval.root_records.items():
                facts = self._facts_by_key.get(key)
                d18 = self.d18_available_at(record, facts) if facts is not None else None
                end = self.event_end.get(record.event_key)
                if end is not None:
                    scheduled[key] = self.retrieval.schedule(record, d18, end)
            self.retrieval.set_schedule(scheduled)

    # --- D18 availability (A1/A2, unchanged) --------------------------------------------------

    def d18_available_at(self, record: LiveRecord, facts: TeamEventFacts) -> datetime | None:
        """D18's available_at, or None when its anchor (T_end / T_w1) does not exist yet."""
        value = record.value
        if not (record.processed and value.valid) or facts.last_completed_match is None:
            return None
        if value.rule == RULE_A1_SEASON_END:
            return self.season_end.get(value.season)
        week_one = self.week_one_complete.get(value.season)
        return None if week_one is None else max(facts.last_completed_match, week_one)

    # --- lookup -------------------------------------------------------------------------------

    def snapshot_view(self, as_of: datetime) -> SnapshotView:
        return self.retrieval.view(as_of)

    def point_in_time_epa(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable:
        view = self.retrieval.view(as_of)
        skipped: list[str] = []
        for facts in self._ordered.get(team, ()):
            event_key = facts.event_key
            if event_key == target_event_key:
                continue
            if not (facts.end_instant < as_of and facts.last_completed_match < as_of):  # type: ignore[operator]
                continue
            if self.a1a2_policy == A1A2_D18_SKIP:
                probe = view.probe(team, event_key)
                if probe is not None and probe.processed and probe.value.valid:
                    anchor = self.d18_available_at(probe, facts)
                    if anchor is None or not anchor < as_of:
                        self.diagnostics[f"skipped:{probe.value.rule}"] += 1
                        skipped.append(event_key)
                        continue
            return self._candidate(team, target_event_key, as_of, facts, view, skipped)
        self.diagnostics["withheld:availability" if skipped else "withheld:no_prior_event"] += 1
        return Unavailable(EPA_WITHHELD_NO_PRIOR_EVENT, "no qualifying prior event with an available EPA")

    def _candidate(self, team: int, target: str, as_of: datetime, facts: TeamEventFacts, view: SnapshotView,
                   skipped: list[str]) -> TeamEventEpa:
        event_key = facts.event_key
        record = view.records(team, event_key)
        base = {"snapshot_id": view.snapshot_id, "retrieval_mode": view.mode, "skipped": skipped,
                "a1a2_policy": self.a1a2_policy}
        if record is not None and record.processed:
            anchor = self.d18_available_at(record, facts)
            if record.value.valid and anchor is not None and max(anchor, record.retrieved_at) < as_of:
                state = CURRENT if view.healthy else STALE
                self.diagnostics[f"served:{state}:{record.value.rule}"] += 1
                value = record.value
                return TeamEventEpa(team, event_key, value.total, value.auto, value.teleop, value.endgame,  # type: ignore[arg-type]
                                    VALUE_SOURCE_STATBOTICS, False,  # type: ignore[arg-type]
                                    {**base, "epa_source_state": state, "rule": value.rule,
                                     "available_at": max(anchor, record.retrieved_at).isoformat(),
                                     "retrieved_at": record.retrieved_at.isoformat(), "raw_sha256": record.raw_sha256,
                                     "snapshot_retrieved_at": view.snapshot_retrieved_at})
            # processed but not servable: invalid (D8), or not yet A1/A2-available (only under literal_state)
            self.diagnostics["refused:unavailable:processed_not_servable"] += 1
            raise EpaSourceUnavailableError(team, target, as_of, event_key, REASON_UNAVAILABLE)
        end = self.event_end.get(event_key)
        if end is None or not end + FALLBACK_DELAY < as_of:
            self.diagnostics["refused:pending"] += 1
            raise EpaSourcePendingError(team, target, as_of, event_key, REASON_PENDING)
        value = self.stratai.get((team, event_key))
        if value is None or not max(value.available_at, (end + FALLBACK_DELAY).timestamp()) < as_of.timestamp():
            self.diagnostics["refused:unavailable:no_stratai_value"] += 1
            raise EpaSourceUnavailableError(team, target, as_of, event_key, REASON_UNAVAILABLE)
        self.diagnostics[f"served:{FALLBACK_STRATAI}"] += 1
        return TeamEventEpa(team, event_key, value.total, value.auto, value.teleop, value.endgame,
                            VALUE_SOURCE_FALLBACK, False,  # type: ignore[arg-type]
                            {**base, "epa_source_state": FALLBACK_STRATAI, "fallback_reason": FALLBACK_REASON,
                             "available_at": value.available_at, "event_end": end.isoformat(),
                             "stratai_replay": self.stratai_info})

    def provenance(self) -> dict[str, Any]:
        return {"source": self.source, "design": DESIGN, "a1a2_policy": self.a1a2_policy,
                "fallback": {"option": "A", "delay_hours": 72, "stratai": self.stratai_info},
                "week_one_complete": {str(k): v.isoformat() for k, v in sorted(self.week_one_complete.items())},
                "season_end": {str(k): v.isoformat() for k, v in sorted(self.season_end.items())},
                "validation_status": LIVE_REFRESH_NOT_YET_VALIDATED,
                "lookup_diagnostics": dict(sorted(self.diagnostics.items())), **self.provenance_info}


def response_epa_status(teams: list[Any]) -> dict[str, Any]:
    """§5 output level over a response's TeamFeatures: degraded, stale_events, fallback_events."""
    stale = sorted({t.epa_source_event_key for t in teams if t.epa_source_state == STALE})
    fallback = sorted({t.epa_source_event_key for t in teams if t.epa_source_state == FALLBACK_STRATAI})
    return {"degraded": bool(stale or fallback), "stale_events": stale, "fallback_events": fallback}
