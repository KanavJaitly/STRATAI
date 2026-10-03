"""P5-M2 live EPA provider, snapshot log and refresh cycle (LIVE_EPA_REFRESH_DESIGN.md).

Pure: synthetic snapshots in tmp_path, synthetic canonical facts, a fake Statbotics client, no database.
Synthetic data: no result here is evidence about any real team.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from ml.ratings.epa_states import CURRENT, FALLBACK_STRATAI, STALE
from ml.ratings.live_epa import (
    A1A2_D18_SKIP,
    A1A2_LITERAL_STATE,
    FALLBACK_REASON,
    EpaSourcePendingError,
    EpaSourceUnavailableError,
    LiveRetrieval,
    LiveStatboticsEpa,
    SimulatedRetrieval,
    frozen_d18_schedule,
    lag_schedule,
    response_epa_status,
)
from ml.ratings.live_snapshots import SnapshotIntegrityError, SnapshotLog, canonical, processed_flags, snapshot_id_of
from ml.ratings.live_source import LiveEpaRefresher, ProviderHolder
from ml.ratings.provider import StrataiTeamEventValue, TeamEventFacts, TeamEventEpa, Unavailable
from ml.ratings.statbotics_primary import SilentFallbackError

UTC = timezone.utc
T0 = datetime(2027, 3, 1, 12, tzinfo=UTC)  # P1 (team 1's latest prior event) ends here
W1 = datetime(2027, 2, 20, tzinfo=UTC)  # T_w1
TEAM, OTHER = 1, 2


def _record(team: int, event: str, total: float, *, status: str = "Completed", qual_count: int = 10) -> dict:
    return {"team": team, "event": event, "year": 2027, "week": 2, "status": status,
            "epa": {"total_points": total, "breakdown": {"auto_points": 1.0, "teleop_points": total - 3.0,
                                                         "endgame_points": 2.0}},
            "record": {"qual": {"count": qual_count}, "total": {"count": max(qual_count, 5), "wins": 0, "losses": 0,
                                                                "ties": 0}}}


def _write_root(root: Path, events: dict[str, list[dict]], finished_at: datetime) -> None:
    (root / "raw").mkdir(parents=True)
    entries = []
    for event_key, records in events.items():
        data = canonical(records)
        (root / "raw" / f"{event_key}.json.gz").write_bytes(gzip.compress(data, mtime=0))
        entries.append({"event_key": event_key, "raw_file": f"raw/{event_key}.json.gz",
                        "raw_sha256": hashlib.sha256(data).hexdigest(), "retrieved_at": finished_at.isoformat()})
    manifest = {"failures": [], "events_requested": len(entries), "events_fetched": len(entries),
                "finished_at": finished_at.isoformat(), "events": entries}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


FACTS = {
    TEAM: [TeamEventFacts("2027p1", T0 - timedelta(hours=12), T0),
           TeamEventFacts("2027p0", T0 - timedelta(days=10), T0 - timedelta(days=9))],
    OTHER: [TeamEventFacts("2027q1", T0 - timedelta(days=5), T0 - timedelta(days=4, hours=12))],
}
ENDS = {"2027p1": T0, "2027p0": T0 - timedelta(days=9), "2027q1": T0 - timedelta(days=4, hours=12)}
STRATAI = {(TEAM, "2027p1"): StrataiTeamEventValue(30.0, 5.0, 20.0, 5.0, int((T0 + timedelta(hours=1)).timestamp()),
                                                   False)}


def _provider(retrieval, policy=A1A2_D18_SKIP, *, season_end=None, stratai=STRATAI) -> LiveStatboticsEpa:
    return LiveStatboticsEpa(retrieval, FACTS, ENDS, {2027: W1}, season_end or {}, stratai, {"replay": "synthetic"},
                             policy)


@pytest.fixture
def root(tmp_path) -> Path:
    path = tmp_path / "root"
    _write_root(path, {"2027p0": [_record(TEAM, "2027p0", 20.0)],
                       "2027q1": [_record(OTHER, "2027q1", 50.0)],
                       "2027p1": [_record(TEAM, "2027p1", 40.0, status="Upcoming", qual_count=0)]},
                T0 - timedelta(days=30))
    return path


@pytest.fixture
def log(tmp_path, root) -> SnapshotLog:
    return SnapshotLog.create_from_root(tmp_path / "log", root)


class FakeClient:
    """Returns scripted bodies per event, or raises the scripted exception."""

    def __init__(self, script: dict[str, object]) -> None:
        self.script = script

    def fetch_event_team_metrics(self, event_key: str):
        outcome = self.script[event_key]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, []


def _refresh(log: SnapshotLog, script: dict, now: datetime):
    return LiveEpaRefresher(log, database=None, client=FakeClient(script), sleep=lambda s: None,  # type: ignore[arg-type]
                            land=False).refresh(list(script), now=now)


def _status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.statbotics.io/v3/team_events")
    return httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))


# --- snapshot log ---------------------------------------------------------------------------------


def test_root_and_copy_on_write(log, root):
    root_id = log.head()
    assert log.manifest(root_id)["parent"] is None and snapshot_id_of(log.manifest(root_id)) == root_id
    assert log.manifest(root_id)["events"]["2027p1"]["processed"] == {str(TEAM): False}  # Upcoming
    outcome = _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0)]}, T0 + timedelta(hours=2))
    assert outcome.ok and outcome.snapshot_id == log.head() != root_id
    child = log.manifest(outcome.snapshot_id)
    assert child["parent"] == root_id and child["events"]["2027p0"] == log.manifest(root_id)["events"]["2027p0"]
    assert child["events"]["2027p1"]["processed"] == {str(TEAM): True}
    assert [e["snapshot_id"] for e in log.snapshots()] == [root_id, outcome.snapshot_id]


def test_processed_requires_every_record_completed():
    assert processed_flags([_record(1, "e", 1.0), _record(2, "e", 1.0, status="Upcoming")]) == {"1": False, "2": False}
    assert processed_flags([]) == {}


def test_tampered_raw_file_is_refused(log, root):
    (root / "raw" / "2027p0.json.gz").write_bytes(gzip.compress(canonical([_record(TEAM, "2027p0", 99.0)])))
    with pytest.raises(SnapshotIntegrityError):
        log.records(log.head())


@pytest.mark.parametrize("failure", [_status_error(), httpx.ReadTimeout("timed out")])
def test_failed_refresh_writes_no_manifest(log, failure):
    root_id = log.head()
    outcome = _refresh(log, {"2027p1": failure}, T0 + timedelta(hours=2))
    assert not outcome.ok and outcome.snapshot_id is None and log.head() == root_id
    entry = log.entries()[-1]
    assert entry["kind"] == "refresh" and entry["ok"] is False and entry["failures"][0]["event_key"] == "2027p1"


def test_partial_failure_commits_nothing(log):
    root_id = log.head()
    outcome = _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0)], "2027q1": _status_error()},
                       T0 + timedelta(hours=2))
    assert not outcome.ok and log.head() == root_id


# --- states (§5) ----------------------------------------------------------------------------------


def _live(log) -> LiveStatboticsEpa:
    return _provider(LiveRetrieval(log))


def test_current_with_provenance(log):
    _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0)]}, T0 + timedelta(hours=2))
    found = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=3))
    assert isinstance(found, TeamEventEpa) and found.source == "statbotics" and found.total == 41.0
    assert found.provenance["epa_source_state"] == CURRENT and found.provenance["snapshot_id"] == log.head()
    assert found.provenance["raw_sha256"] and found.provenance["retrieved_at"]


def test_pending_before_72h_never_an_older_event(log):
    with pytest.raises(EpaSourcePendingError) as caught:
        _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=10))  # p1 Upcoming in root
    assert caught.value.record["candidate"] == "2027p1"
    assert isinstance(caught.value, SilentFallbackError)


def test_unprocessed_after_72h_is_labelled_stratai_fallback(log):
    found = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=73))
    assert isinstance(found, TeamEventEpa) and found.source == "stratai_fallback" and found.total == 30.0
    assert found.provenance["epa_source_state"] == FALLBACK_STRATAI
    assert found.provenance["fallback_reason"] == FALLBACK_REASON


def test_unavailable_when_stratai_has_no_value(log):
    with pytest.raises(EpaSourceUnavailableError):
        _provider(LiveRetrieval(log), stratai={}).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=73))


def test_unprocessed_record_never_served_as_statbotics(log):
    _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0, status="Upcoming")]}, T0 + timedelta(hours=2))
    found = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=80))
    assert found.source == "stratai_fallback"  # type: ignore[union-attr]


def test_stale_while_refreshes_fail(log):
    _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0)]}, T0 + timedelta(hours=2))
    _refresh(log, {"2027q1": _status_error()}, T0 + timedelta(hours=4))
    found = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=5))
    assert found.provenance["epa_source_state"] == STALE and found.total == 41.0  # type: ignore[union-attr]
    before = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=3))
    assert before.provenance["epa_source_state"] == CURRENT  # type: ignore[union-attr]


def test_snapshot_created_after_as_of_is_invisible(log):
    _refresh(log, {"2027p1": [_record(TEAM, "2027p1", 41.0)]}, T0 + timedelta(hours=100))
    found = _live(log).point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=90))
    assert found.source == "stratai_fallback"  # type: ignore[union-attr]


def test_no_prior_event_is_withheld(log):
    found = _live(log).point_in_time_epa(99, "2027t", T0)
    assert isinstance(found, Unavailable)


# --- open decision Q1: the A1/A2 policy -----------------------------------------------------------


def test_policy_is_required():
    with pytest.raises(ValueError):
        _provider(None, policy=None)  # type: ignore[arg-type]


def _a1_log(tmp_path) -> SnapshotLog:
    root = tmp_path / "a1root"
    _write_root(root, {"2027p0": [_record(TEAM, "2027p0", 20.0)],
                       "2027p1": [_record(TEAM, "2027p1", 40.0, qual_count=0)]},  # A1: season-end value
                T0 + timedelta(hours=1))
    return SnapshotLog.create_from_root(tmp_path / "a1log", root)


def test_d18_skip_steps_past_a_not_yet_available_a1_value(tmp_path):
    found = _provider(LiveRetrieval(_a1_log(tmp_path)), A1A2_D18_SKIP).point_in_time_epa(
        TEAM, "2027t", T0 + timedelta(hours=5))
    assert found.event_key == "2027p0" and found.provenance["skipped"] == ["2027p1"]  # type: ignore[union-attr]


def test_literal_state_refuses_a_not_yet_available_a1_value(tmp_path):
    with pytest.raises(EpaSourceUnavailableError):
        _provider(LiveRetrieval(_a1_log(tmp_path)), A1A2_LITERAL_STATE).point_in_time_epa(
            TEAM, "2027t", T0 + timedelta(hours=5))


def test_a1_value_served_after_a_concluded_season(tmp_path):
    provider = _provider(LiveRetrieval(_a1_log(tmp_path)), season_end={2027: T0 + timedelta(hours=2)})
    assert provider.point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=5)).event_key == "2027p1"  # type: ignore[union-attr]


# --- simulated retrieval (L1/L2 setups) -----------------------------------------------------------


def _simulated(log, schedule, policy=A1A2_D18_SKIP) -> LiveStatboticsEpa:
    return _provider(SimulatedRetrieval(log.head(), log.records(log.head()), schedule), policy)


def test_lag_schedule_controls_visibility(tmp_path):
    root = tmp_path / "r"
    _write_root(root, {"2027p0": [_record(TEAM, "2027p0", 20.0)], "2027p1": [_record(TEAM, "2027p1", 40.0)]},
                T0 + timedelta(days=100))
    log = SnapshotLog.create_from_root(tmp_path / "l", root)
    provider = _simulated(log, lag_schedule(24))
    with pytest.raises(EpaSourcePendingError):
        provider.point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=23))
    found = provider.point_in_time_epa(TEAM, "2027t", T0 + timedelta(hours=25))
    assert found.total == 40.0 and found.provenance["retrieval_mode"] == "simulated:lag_24h"  # type: ignore[union-attr]


def test_frozen_schedule_reproduces_d18_availability(tmp_path):
    root = tmp_path / "r"
    _write_root(root, {"2027p0": [_record(TEAM, "2027p0", 20.0)], "2027p1": [_record(TEAM, "2027p1", 40.0)]},
                T0 + timedelta(days=100))
    log = SnapshotLog.create_from_root(tmp_path / "l", root)
    found = _simulated(log, frozen_d18_schedule).point_in_time_epa(TEAM, "2027t", T0 + timedelta(minutes=1))
    assert found.total == 40.0  # A2: available at max(last match, T_w1) = T0  # type: ignore[union-attr]


# --- holder and response status -------------------------------------------------------------------


def test_holder_swap_keeps_in_flight_provider(log):
    first = _live(log)
    holder = ProviderHolder(first)
    in_flight = holder.current
    holder.swap(_live(log))
    assert in_flight is first and holder.current is not first


def test_response_status():
    class T:
        def __init__(self, state, event):
            self.epa_source_state, self.epa_source_event_key = state, event

    status = response_epa_status([T(CURRENT, "a"), T(STALE, "b"), T(FALLBACK_STRATAI, "c"), T(None, None)])
    assert status == {"degraded": True, "stale_events": ["b"], "fallback_events": ["c"]}
    assert response_epa_status([T(CURRENT, "a")])["degraded"] is False


def test_manifest_is_never_overwritten(log):
    manifest = copy.deepcopy(log.manifest(log.head()))
    path = log.log_dir / "manifests" / f"{log.head()}.json"
    path.write_text(json.dumps({**manifest, "events": {}}), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError):
        log.manifest(log.head())


# --- L3 drill on an isolated database (skipped unless DATABASE_URL names a non-serving copy) -----------


def _isolated_db_name() -> str | None:
    try:
        import psycopg

        from data.config import Settings
        from scripts.phase5_isolated_db import serving_name

        name = serving_name(str(Settings().database_url))
        if not name.startswith("stratai_"):
            return None  # the serving database (or an unknown one): never write sentinel rows there
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return name
    except Exception:
        return None


@pytest.mark.skipif(_isolated_db_name() is None, reason="needs DATABASE_URL to name an isolated stratai_* copy")
def test_l3_outage_drill_passes_on_an_isolated_database(monkeypatch):
    from data.config import Settings
    from scripts import phase5_m2_live_epa_checks as checks
    from scripts.phase5_isolated_db import serving_name

    name = _isolated_db_name()
    # run_l3 derives its URL from the configured server; point "serving" elsewhere so the guard admits the copy
    monkeypatch.setattr("scripts.phase5_isolated_db.serving_name", lambda url: "stratai")
    result = checks.run_l3(name)  # type: ignore[arg-type]
    assert result["passed"], result["problems"]
    assert serving_name(str(Settings().database_url)) == name
