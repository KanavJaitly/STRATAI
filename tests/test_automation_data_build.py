"""Tests for automation.data_build.build -- resume, deadline, and Statbotics degradation.

The orchestrator, rankings sync and incompleteness queries are injected, so
these exercise only the build's own control flow; the real sync functions are
the production ones and are covered by their own suites.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from automation import data_build as db


@dataclass
class FakeSeasonResult:
    failures: list = field(default_factory=list)
    statbotics_skipped_reason: str | None = None


class World:
    """Events per season, which of them are complete, and a controllable clock."""

    def __init__(self, events: dict[int, list[str]], complete: set[str] | None = None) -> None:
        self.events = events
        self.complete = set(complete or ())
        self.unranked = {2026: ["2026a", "2026b"]}
        self.synced: list[tuple[int, list[str]]] = []
        self.ranked: list[str] = []
        self.now = 0.0
        self.sync_cost = 60.0
        self.fail_statbotics_for: set[str] = set()
        self.probe_failure: str | None = None

    def list_events(self, season: int) -> list[str]:
        return self.events.get(season, [])

    def find_incomplete(self, _database, keys):
        return [k for k in keys if k not in self.complete]

    def find_unranked(self, _database, season):
        return [k for k in self.unranked.get(season, []) if k not in self.ranked]

    def sync_events(self, season, keys):
        self.synced.append((season, list(keys)))
        self.now += self.sync_cost
        if self.probe_failure:
            return FakeSeasonResult(statbotics_skipped_reason=self.probe_failure)
        self.complete.update(k for k in keys if k not in self.fail_statbotics_for)
        return FakeSeasonResult()

    def sync_ranking(self, key):
        self.ranked.append(key)
        return True

    def run(self, *, deadline: float = 10_000.0, chunk_size: int = 2, reserve: float = 0.0) -> db.BuildReport:
        return db.build(
            None, seasons=[2024, 2025, 2026], held_out_season=2026,
            list_events=self.list_events, sync_events=self.sync_events, sync_ranking=self.sync_ranking,
            deadline=deadline, clock=lambda: self.now, chunk_size=chunk_size,
            finish_reserve_seconds=reserve, find_incomplete=self.find_incomplete, find_unranked=self.find_unranked,
        )


def events() -> dict[int, list[str]]:
    return {2024: ["2024a", "2024b", "2024c"], 2025: ["2025a"], 2026: ["2026a", "2026b"]}


def test_full_build_syncs_everything_in_season_order_and_ranks_the_held_out_season():
    world = World(events())
    report = world.run()
    assert report.stop_reason is None
    assert [season for season, _ in world.synced] == [2024, 2024, 2025, 2026]
    assert world.synced[0][1] == ["2024a", "2024b"]  # chronological order preserved within chunks
    assert report.events_synced == 6 and report.events_still_incomplete == []
    assert world.ranked == ["2026a", "2026b"] and report.rankings_synced == 2


def test_resume_skips_events_already_complete():
    world = World(events(), complete={"2024a", "2024b", "2024c", "2025a"})
    report = world.run()
    assert world.synced == [(2026, ["2026a", "2026b"])]
    assert report.events_already_complete == 4


def test_deadline_stops_cleanly_before_the_reserve():
    world = World(events())
    report = world.run(deadline=150.0, reserve=30.0)  # time for exactly two chunks of 60s
    assert report.stop_reason == db.STOP_DEADLINE
    assert len(world.synced) == 2
    assert set(report.events_still_incomplete) == {"2025a", "2026a", "2026b"}


def test_failed_probe_stops_the_build_immediately():
    world = World(events())
    world.probe_failure = "probe for team 1 at 2024a failed: HTTPStatusError: 503"
    report = world.run()
    assert report.stop_reason == db.STOP_STATBOTICS_UNAVAILABLE
    assert len(world.synced) == 1
    assert world.ranked == []


def test_mid_sync_degradation_stops_instead_of_burning_minutes():
    world = World(events())
    world.fail_statbotics_for = {"2024c", "2025a", "2026a", "2026b"}
    report = world.run(chunk_size=1)
    assert report.stop_reason == db.STOP_STATBOTICS_DEGRADED
    assert [keys for _, keys in world.synced] == [["2024a"], ["2024b"], ["2024c"]]
    assert "2024c" in report.events_still_incomplete


def test_an_interrupted_build_resumes_where_it_stopped():
    world = World(events())
    world.run(deadline=150.0, reserve=30.0)
    first_pass = [k for _, keys in world.synced for k in keys]
    world.synced.clear()
    world.now = 0.0
    report = world.run()
    second_pass = [k for _, keys in world.synced for k in keys]
    assert set(first_pass).isdisjoint(second_pass)
    assert report.stop_reason is None and report.events_still_incomplete == []
