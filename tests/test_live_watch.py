"""Tests for the live-event watch loop in data.orchestrator.

A real live event cannot be simulated, and hammering TBA for hours is exactly
what the loop is designed *not* to do, so everything unique to `watch_event` is
control flow and that is what these exercise: cadence, idle backoff, failure
isolation, the three stop conditions, the settle window, the Statbotics clock,
and a clean interrupt.

`sync_event` itself is stubbed. Its end-to-end behaviour against a real database
is already covered in tests/test_pipeline.py, and re-running it here would test
the same code twice while making these tests need Postgres. The clock and the
sleep are injected too, so a simulated three-hour watch runs in milliseconds and
is fully deterministic -- no wall-clock waiting, no flakiness.
"""

from __future__ import annotations

import signal
from datetime import date
from typing import Any

import pytest

from data.orchestrator import (
    DEFAULT_CALENDAR_GRACE_DAYS,
    EventProgress,
    SyncResult,
    completion_reason,
    parse_duration,
    watch_event,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """A monotonic clock that only advances when the fake sleep is called.

    This is what makes the tests both fast and exact: simulated time passes only
    where the loop actually waits, so `sleep_totals` below is the true cadence
    the loop chose, not an approximation of wall-clock timing.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.slices: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slices.append(seconds)
        self.now += seconds


class FakeSync:
    """A sync_event stand-in that records its calls and replays scripted outcomes.

    `script` is one entry per poll: a dict of landed counts, or an Exception
    instance to raise. It repeats its final entry once exhausted, so a test only
    has to describe the polls it cares about.
    """

    def __init__(self, script: list[Any], *, clock: FakeClock | None = None) -> None:
        self.script = script
        self.clock = clock
        self.calls: list[dict[str, Any]] = []
        self.call_times: list[float] = []

    def __call__(self, event_key: str, **kwargs: Any) -> SyncResult:
        step = self.script[min(len(self.calls), len(self.script) - 1)]
        self.calls.append({"event_key": event_key, **kwargs})
        if self.clock is not None:
            self.call_times.append(self.clock.now)
        if isinstance(step, Exception):
            raise step
        landed = dict(step)
        return SyncResult(
            run_id=len(self.calls),
            event_key=event_key,
            landed=landed,
            loaded={"matches": sum(landed.values())} if landed else {},
        )

    @property
    def poll_gaps(self) -> list[float]:
        """Simulated seconds between consecutive polls."""
        return [b - a for a, b in zip(self.call_times, self.call_times[1:])]


class FakeProgress:
    """An event_progress stand-in replaying one EventProgress per poll."""

    def __init__(self, script: list[EventProgress | None]) -> None:
        self.script = script
        self.calls = 0

    def __call__(self, database: Any, event_key: str) -> EventProgress | None:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return step


def progress_at(
    played: int, total: int = 10, *, finals_played: int = 0, finals_total: int = 0,
    end_date: date | None = date(2026, 8, 1),
) -> EventProgress:
    return EventProgress(
        event_key="2026zzz", end_date=end_date, matches_total=total, matches_played=played,
        finals_total=finals_total, finals_played=finals_played,
    )


IN_PROGRESS = progress_at(4)
COMPLETE = progress_at(10, finals_played=2, finals_total=2)


def run_watch(*, sync: FakeSync, clock: FakeClock, progress: FakeProgress, **kwargs: Any):
    """Drive watch_event with the fakes, with test-friendly defaults."""
    kwargs.setdefault("interval_seconds", 120.0)
    kwargs.setdefault("max_interval_seconds", 600.0)
    kwargs.setdefault("today", lambda: date(2026, 8, 1))
    return watch_event(
        "2026zzz",
        database=object(),
        tba=object(),
        sync=sync,
        progress=progress,
        sleep=clock.sleep,
        clock=clock,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


def test_the_loop_polls_once_per_interval_until_the_event_ends():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}] * 4, clock=clock)
    progress = FakeProgress([IN_PROGRESS, IN_PROGRESS, IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    # Three in-progress polls, then the completing one.
    assert result.polls == 4
    assert result.successes == 4
    assert sync.poll_gaps == [120.0, 120.0, 120.0]


def test_every_poll_is_an_ordinary_sync_event_call_for_the_same_event():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS, COMPLETE])

    run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert [call["event_key"] for call in sync.calls] == ["2026zzz", "2026zzz"]
    # The collaborators are built once and handed to every poll, as in sync_season.
    for call in sync.calls:
        for name in ("writer", "repository", "recorder", "watermarks", "quality", "lineage"):
            assert call[name] is sync.calls[0][name]


# ---------------------------------------------------------------------------
# No-op polls and idle backoff
# ---------------------------------------------------------------------------


def test_a_poll_that_finds_nothing_new_is_handled_and_does_not_error():
    clock = FakeClock()
    sync = FakeSync([{}, {}, {"tba.match": 2}, {}], clock=clock)
    progress = FakeProgress([IN_PROGRESS, IN_PROGRESS, IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.failures == 0
    assert result.successes == 4
    # Three of the four polls landed nothing; only the real change is counted.
    assert result.landed == {"tba.match": 2}


def test_the_interval_backs_off_only_after_several_consecutive_idle_polls():
    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)  # nothing ever lands
    progress = FakeProgress([IN_PROGRESS] * 5 + [COMPLETE])

    run_watch(
        sync=sync, clock=clock, progress=progress,
        idle_polls_before_backoff=3, settle_polls=0,
    )

    # Two idle polls at the base interval, then 1.5x compounding.
    assert sync.poll_gaps == [120.0, 120.0, 180.0, 270.0, 405.0]


def test_backoff_is_capped_at_the_maximum_interval():
    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)
    progress = FakeProgress([IN_PROGRESS] * 8 + [COMPLETE])

    run_watch(
        sync=sync, clock=clock, progress=progress,
        idle_polls_before_backoff=1, max_interval_seconds=300.0, settle_polls=0,
    )

    assert max(sync.poll_gaps) == 300.0
    assert sync.poll_gaps[-1] == 300.0


def test_anything_landing_snaps_the_interval_back_to_the_base():
    clock = FakeClock()
    sync = FakeSync([{}, {}, {}, {}, {"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS] * 5 + [COMPLETE])

    run_watch(
        sync=sync, clock=clock, progress=progress,
        idle_polls_before_backoff=3, settle_polls=0,
    )

    assert sync.poll_gaps[:4] == [120.0, 120.0, 180.0, 270.0]
    assert sync.poll_gaps[4] == 120.0  # the poll that landed something reset it


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_a_failed_poll_is_caught_and_the_loop_continues():
    clock = FakeClock()
    sync = FakeSync(
        [{"tba.match": 1}, ConnectionError("TBA unreachable"), {"tba.match": 1}], clock=clock,
    )
    progress = FakeProgress([IN_PROGRESS, IN_PROGRESS, IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.failures == 1
    assert result.successes >= 2
    assert result.last_error == "ConnectionError: TBA unreachable"
    assert result.stop_reason.startswith("finals complete")
    assert not result.stopped_on_failures


def test_a_run_of_failures_backs_off_and_then_recovers():
    clock = FakeClock()
    sync = FakeSync(
        [ConnectionError("down"), ConnectionError("down"), {"tba.match": 1}], clock=clock,
    )
    progress = FakeProgress([IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert sync.poll_gaps[0] == 180.0  # 120 * 1.5
    assert sync.poll_gaps[1] == 270.0  # 180 * 1.5
    assert result.successes >= 1
    assert result.failures == 2


def test_the_watch_gives_up_after_the_configured_consecutive_failures():
    clock = FakeClock()
    sync = FakeSync([RuntimeError("404 Not Found")], clock=clock)
    progress = FakeProgress([None])

    result = run_watch(sync=sync, clock=clock, progress=progress, max_failures=4)

    assert result.polls == 4
    assert result.failures == 4
    assert result.stopped_on_failures
    assert "4 consecutive failures" in result.stop_reason


def test_a_success_resets_the_consecutive_failure_count():
    clock = FakeClock()
    sync = FakeSync(
        [RuntimeError("a"), RuntimeError("b"), {"tba.match": 1},
         RuntimeError("c"), RuntimeError("d"), {"tba.match": 1}],
        clock=clock,
    )
    progress = FakeProgress([IN_PROGRESS] * 5 + [COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, max_failures=3, settle_polls=0)

    # Without the reset, failures 1-2 plus 3 would have ended the watch early.
    assert not result.stopped_on_failures
    assert result.failures == 4


# ---------------------------------------------------------------------------
# Stop conditions
# ---------------------------------------------------------------------------


def test_the_watch_stops_when_the_finals_are_complete():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS, IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.polls == 3
    assert result.stop_reason.startswith("finals complete")
    assert not result.interrupted


def test_an_unplayed_final_does_not_end_the_watch():
    """Double elimination: f1m1 played, f1m2 still pending, so it is not over."""
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    mid_finals = progress_at(9, finals_played=1, finals_total=2)
    progress = FakeProgress([mid_finals, mid_finals, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.polls == 3


def test_unplayed_qualification_matches_do_not_prevent_stopping():
    """The 2024gagwi / 2024mdsev case: sentinel quals stay unplayed forever."""
    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)
    sentinel_event = progress_at(88, total=90, finals_played=2, finals_total=2)
    progress = FakeProgress([sentinel_event])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.polls == 1
    assert result.stop_reason.startswith("finals complete")
    assert result.progress is not None and result.progress.matches_unplayed == 2


def test_the_calendar_fallback_stops_an_event_that_never_published_finals():
    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)
    cancelled = progress_at(0, total=0, end_date=date(2026, 7, 20))
    progress = FakeProgress([cancelled])

    result = run_watch(
        sync=sync, clock=clock, progress=progress,
        settle_polls=0, today=lambda: date(2026, 8, 1),
    )

    assert result.polls == 1
    assert "no finals were published" in result.stop_reason


def test_the_calendar_grace_keeps_a_watch_alive_on_the_final_evening():
    """A venue west of UTC is still playing when UTC has rolled to the next day."""
    reason = completion_reason(
        progress_at(30, total=60, end_date=date(2026, 8, 1)),
        today=date(2026, 8, 2),
        calendar_grace_days=DEFAULT_CALENDAR_GRACE_DAYS,
    )
    assert reason is None


def test_an_event_not_loaded_yet_is_never_treated_as_complete():
    assert completion_reason(None, today=date(2030, 1, 1)) is None


def test_max_duration_bounds_a_watch_that_would_otherwise_run_forever():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS])

    result = run_watch(
        sync=sync, clock=clock, progress=progress, max_duration_seconds=500.0,
    )

    assert result.polls == 5  # polls at t+0, 120, 240, 360, 480; t+600 is past the bound
    assert "max duration reached" in result.stop_reason


# ---------------------------------------------------------------------------
# Settle window
# ---------------------------------------------------------------------------


def test_completion_is_followed_by_the_configured_settle_polls():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=2)

    # One in-progress poll, the poll that detects completion, then two more.
    assert result.polls == 4
    assert result.stop_reason.startswith("finals complete")


def test_the_settle_countdown_restarts_if_the_event_goes_back_in_progress():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    # TBA publishes an extra finals match after the bracket first looked done.
    reopened = progress_at(10, finals_played=2, finals_total=3)
    progress = FakeProgress([COMPLETE, reopened, COMPLETE, COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=1)

    # Poll 1 detects completion, poll 2 revokes it, poll 3 detects it afresh and
    # poll 4 is its settle poll. Without the restart the watch would have stopped
    # at poll 3, having spent its only settle poll on the stale detection.
    assert result.polls == 4


# ---------------------------------------------------------------------------
# Statbotics cadence
# ---------------------------------------------------------------------------


class FakeStatbotics:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.probe_calls = 0

    def fetch_team_event_metrics(self, team_number: int, event_key: str):
        self.probe_calls += 1
        if not self.available:
            raise RuntimeError("simulated Statbotics 500")
        return object()


@pytest.fixture
def stub_probe(monkeypatch):
    """Replace the Statbotics probe, which needs a TBA client to pick a team."""
    from data import orchestrator

    state = {"reason": None}

    def fake_probe(statbotics, tba, event_key):
        return state["reason"]

    monkeypatch.setattr(orchestrator, "statbotics_probe_failure", fake_probe)
    return state


def test_statbotics_runs_on_its_own_slower_clock(stub_probe):
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS] * 6 + [COMPLETE])

    result = run_watch(
        sync=sync, clock=clock, progress=progress, settle_polls=0,
        statbotics=FakeStatbotics(), statbotics_interval_seconds=300.0,
    )

    used = [call["statbotics"] is not None for call in sync.calls]
    # 120s polls, 300s Statbotics cadence: polls at t+0, t+360, t+720.
    assert used == [True, False, False, True, False, False, True]
    assert result.statbotics_polls == 3


def test_a_dead_statbotics_is_probed_once_and_then_skipped_for_the_whole_watch(stub_probe):
    stub_probe["reason"] = "probe for team 1114 at 2026zzz failed: RuntimeError: 500"
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS, IN_PROGRESS, COMPLETE])

    result = run_watch(
        sync=sync, clock=clock, progress=progress, settle_polls=0,
        statbotics=FakeStatbotics(available=False),
    )

    assert result.statbotics_skipped_reason == stub_probe["reason"]
    assert result.statbotics_polls == 0
    assert all(call["statbotics"] is None for call in sync.calls)


def test_no_statbotics_means_no_probe_and_no_statbotics_polls(stub_probe):
    stub_probe["reason"] = "should never be consulted"
    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)
    progress = FakeProgress([COMPLETE])

    result = run_watch(sync=sync, clock=clock, progress=progress, settle_polls=0)

    assert result.statbotics_skipped_reason is None
    assert result.statbotics_polls == 0


# ---------------------------------------------------------------------------
# Interrupts
# ---------------------------------------------------------------------------


def test_sigint_stops_the_watch_cleanly_between_polls():
    clock = FakeClock()
    sync = FakeSync([{"tba.match": 1}], clock=clock)
    progress = FakeProgress([IN_PROGRESS])

    def sleep_then_interrupt(seconds: float) -> None:
        clock.sleep(seconds)
        if len(sync.calls) == 2 and not interrupted["sent"]:
            interrupted["sent"] = True
            signal.raise_signal(signal.SIGINT)

    interrupted = {"sent": False}
    result = watch_event(
        "2026zzz", database=object(), tba=object(),
        sync=sync, progress=progress, sleep=sleep_then_interrupt, clock=clock,
        today=lambda: date(2026, 8, 1),
    )

    assert result.interrupted
    assert result.stop_reason == "interrupted"
    assert result.polls == 2  # the in-flight poll finished; no third one started
    assert result.failures == 0


def test_signal_handlers_are_restored_when_the_watch_ends():
    before_int = signal.getsignal(signal.SIGINT)
    before_term = signal.getsignal(signal.SIGTERM)

    clock = FakeClock()
    sync = FakeSync([{}], clock=clock)
    run_watch(sync=sync, clock=clock, progress=FakeProgress([COMPLETE]), settle_polls=0)

    assert signal.getsignal(signal.SIGINT) is before_int
    assert signal.getsignal(signal.SIGTERM) is before_term


def test_signal_handlers_are_restored_even_when_the_watch_raises():
    before_int = signal.getsignal(signal.SIGINT)

    class Exploding(FakeSync):
        def __call__(self, event_key: str, **kwargs: Any) -> SyncResult:
            raise KeyboardInterrupt("operator aborted hard")

    clock = FakeClock()
    with pytest.raises(KeyboardInterrupt):
        run_watch(sync=Exploding([{}]), clock=clock, progress=FakeProgress([IN_PROGRESS]))

    assert signal.getsignal(signal.SIGINT) is before_int


# ---------------------------------------------------------------------------
# Duration parsing (CLI)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("90", 90.0), ("45s", 45.0), ("30m", 1800.0), ("8h", 28800.0), ("2d", 172800.0),
     ("1.5h", 5400.0), ("8H", 28800.0), (" 8h ", 28800.0)],
)
def test_parse_duration_accepts_seconds_and_units(text: str, expected: float):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "soon", "8w", "-1", "0", "8 hours"])
def test_parse_duration_rejects_nonsense(text: str):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        parse_duration(text)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_rejects_watch_combined_with_another_mode():
    from data import orchestrator

    for argv in (["2026zzz", "--watch", "2026zzz"], ["--season", "2024", "--watch", "2026zzz"]):
        with pytest.raises(SystemExit) as exit_info:
            orchestrator.main(argv)
        assert exit_info.value.code != 0


# ===========================================================================
# event_progress against a real database.
#
# The loop tests above inject `progress`, so this is the only place the actual
# SQL runs -- and the stop condition is only as good as this query.
# ===========================================================================

W_EVENT = "2026zzzwatch"


def _database_available() -> bool:
    try:
        import psycopg

        from data.config import Settings

        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _cleanup(database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (W_EVENT,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (W_EVENT,))


@pytest.fixture
def database():
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)


def _insert_event(database, end_date: str) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            "INSERT INTO events (event_key, season, name, end_date) VALUES (%s, 2026, %s, %s)",
            (W_EVENT, "Watch Test Event", end_date),
        )


def _insert_match(database, key: str, level: str, score: int | None) -> None:
    with database.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO matches (match_key, event_key, season, competition_level,
                                 match_number, score_red, score_blue)
            VALUES (%s, %s, 2026, %s, 1, %s, %s)
            """,
            (f"{W_EVENT}_{key}", W_EVENT, level, score, score),
        )


@requires_db
def test_event_progress_returns_none_for_an_event_that_is_not_loaded_yet(database):
    from data.orchestrator import event_progress

    assert event_progress(database, W_EVENT) is None


@requires_db
def test_event_progress_counts_played_matches_and_finals(database):
    from data.orchestrator import event_progress

    _insert_event(database, "2026-04-04")
    _insert_match(database, "qm1", "qualification", 88)
    _insert_match(database, "qm2", "qualification", None)
    _insert_match(database, "f1m1", "final", 120)
    _insert_match(database, "f1m2", "final", None)

    progress = event_progress(database, W_EVENT)

    assert progress is not None
    assert (progress.matches_total, progress.matches_played) == (4, 2)
    assert (progress.finals_total, progress.finals_played) == (2, 1)
    assert progress.matches_unplayed == 2
    assert progress.end_date == date(2026, 4, 4)
    assert not progress.finals_complete


@requires_db
def test_event_progress_reports_finals_complete_despite_unplayed_qualifications(database):
    """The real 2024gagwi / 2024mdsev shape, read through the real query."""
    from data.orchestrator import event_progress

    _insert_event(database, "2026-04-04")
    _insert_match(database, "qm1", "qualification", 88)
    _insert_match(database, "qm73", "qualification", None)  # frc0/-1 sentinel row
    _insert_match(database, "f1m1", "final", 120)
    _insert_match(database, "f1m2", "final", 131)

    progress = event_progress(database, W_EVENT)

    assert progress is not None and progress.finals_complete
    assert progress.matches_unplayed == 1
    assert completion_reason(progress, today=date(2026, 4, 4)) is not None


@requires_db
def test_event_progress_handles_an_event_with_no_matches_yet(database):
    """An event synced before its schedule is published must not look complete."""
    from data.orchestrator import event_progress

    _insert_event(database, "2026-04-04")

    progress = event_progress(database, W_EVENT)

    assert progress is not None
    assert (progress.matches_total, progress.finals_total) == (0, 0)
    assert not progress.finals_complete
    assert completion_reason(progress, today=date(2026, 4, 4)) is None
