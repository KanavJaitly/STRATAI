"""P5-M6: the watch follow-on (team_metrics recompute during --watch; live EPA refresh trigger). Pure fakes."""

from __future__ import annotations

from typing import Any

from data import orchestrator
from data.config import Settings
from data.orchestrator import SyncResult, after_watch_sync
from tests.test_live_watch import COMPLETE, IN_PROGRESS, FakeClock, FakeProgress, FakeSync, run_watch


def test_after_sync_runs_after_every_successful_poll():
    clock = FakeClock()
    calls: list[tuple[str, int]] = []
    sync = FakeSync([{"tba.match": 1}, RuntimeError("tba down"), {}, {}], clock=clock)
    result = run_watch(sync=sync, clock=clock, progress=FakeProgress([IN_PROGRESS, IN_PROGRESS, COMPLETE]),
                       settle_polls=0, after_sync=lambda db, event, r: calls.append((event, r.records_loaded)))
    assert calls[0] == ("2026zzz", 1) and len(calls) == result.successes


def test_a_failing_follow_on_is_counted_and_never_stops_the_watch():
    clock = FakeClock()

    def broken(db: Any, event: str, r: SyncResult) -> None:
        raise ValueError("metrics recompute failed")

    result = run_watch(sync=FakeSync([{"tba.match": 1}], clock=clock), clock=clock,
                       progress=FakeProgress([IN_PROGRESS, COMPLETE]), settle_polls=0, after_sync=broken)
    assert result.successes == 2 and result.failures == 2 and not result.stopped_on_failures
    assert "after_sync" in result.last_error


def test_team_metrics_recompute_only_when_rows_loaded(monkeypatch):
    recomputed: list[str] = []
    monkeypatch.setattr("data.metrics.compute.compute_event_team_metrics",
                        lambda event, database: recomputed.append(event))
    settings = Settings(epa_source="statbotics")
    after_watch_sync(object(), "2026x", SyncResult(run_id=1, event_key="2026x", landed={}, loaded={}),
                     settings=settings)
    after_watch_sync(object(), "2026x", SyncResult(run_id=2, event_key="2026x", landed={"tba.match": 1},
                                                   loaded={"matches": 1}), settings=settings)
    assert recomputed == ["2026x"]


def test_the_cli_wires_the_follow_on():
    import inspect

    assert "after_sync=after_watch_sync" in inspect.getsource(orchestrator.main)
