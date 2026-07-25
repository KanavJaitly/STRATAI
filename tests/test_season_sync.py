"""Tests for the season-level sync wrapper in data.orchestrator.

These cover the three policies the wrapper owns and `sync_event` does not:

  * which events a season contains, and in what order;
  * that one failing event does not end the season;
  * that a dead Statbotics is probed once and then skipped, rather than retried
    once per team for the whole season.

`sync_event` itself is stubbed here. Its end-to-end behaviour against a real
database is already covered in tests/test_pipeline.py, and repeating that
through the wrapper would test the same code twice while making these tests
depend on Postgres. What is unique to the wrapper is control flow, so that is
what is exercised.
"""

from __future__ import annotations

from typing import Any

import pytest

from data import orchestrator
from data.clients.schemas import EventSummary, StatboticsTeamEventMetrics, TeamInfo
from data.clients.source_connector import SourceResponse
from data.orchestrator import SeasonResult, SyncResult, official_event_keys, statbotics_probe_failure, sync_season


def event_payload(key: str, *, event_type: int, start_date: str | None = "2024-03-01") -> dict[str, Any]:
    """A TBA event-list entry, in the wire shape the real endpoint returns."""
    return {
        "key": key, "name": f"Event {key}", "event_code": key[4:], "year": 2024,
        "event_type": event_type, "start_date": start_date, "end_date": start_date,
    }


class FakeEventListClient:
    """A TBAClient stand-in for season enumeration and Statbotics probing."""

    def __init__(self, payloads: list[dict[str, Any]], *, teams: list[dict[str, Any]] | None = None) -> None:
        self.payloads = payloads
        self.teams = teams if teams is not None else [{"key": "frc1114", "team_number": 1114}]
        self.event_list_calls: list[int | None] = []
        self.event_teams_calls: list[str] = []

    def fetch_event_list(self, year: int | None = None) -> list[SourceResponse[EventSummary]]:
        self.event_list_calls.append(year)
        return [SourceResponse(p, EventSummary.model_validate(p)) for p in self.payloads]

    def fetch_event_teams(self, event_key: str) -> list[SourceResponse[TeamInfo]]:
        self.event_teams_calls.append(event_key)
        return [SourceResponse(p, TeamInfo.model_validate(p)) for p in self.teams]


class FakeSeasonStatbotics:
    """A StatboticsClient stand-in that either answers or always fails."""

    def __init__(self, *, available: bool) -> None:
        self.available = available
        self.calls: list[tuple[int, str]] = []

    def fetch_team_event_metrics(
        self, team_number: int, event_key: str
    ) -> SourceResponse[StatboticsTeamEventMetrics]:
        self.calls.append((team_number, event_key))
        if not self.available:
            raise RuntimeError("simulated Statbotics 500")
        payload = {"team": team_number, "event": event_key, "epa": {"total_points": 40.0}}
        return SourceResponse(payload, StatboticsTeamEventMetrics.model_validate(payload))


@pytest.fixture
def stub_sync_event(monkeypatch):
    """Replace sync_event with a recorder, so the wrapper is tested in isolation.

    Returns the call log. Event keys listed in `fail_for` raise, which is how the
    per-event failure-isolation tests inject a bad event.
    """
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"fail_for": set(), "next_run_id": 1}

    def fake_sync_event(event_key: str, **kwargs: Any) -> SyncResult:
        calls.append({"event_key": event_key, "statbotics": kwargs.get("statbotics")})
        if event_key in state["fail_for"]:
            raise RuntimeError(f"simulated failure for {event_key}")
        run_id = state["next_run_id"]
        state["next_run_id"] += 1
        return SyncResult(
            run_id=run_id, event_key=event_key,
            landed={"tba.match": 2}, loaded={"matches": 2, "teams": 3},
        )

    monkeypatch.setattr(orchestrator, "sync_event", fake_sync_event)
    return {"calls": calls, "state": state}


# ---------------------------------------------------------------------------
# Season enumeration
# ---------------------------------------------------------------------------


def test_official_event_keys_excludes_offseason_and_preseason():
    # 99 = Offseason, 100 = Preseason. Both are real TBA event types that appear
    # in /events/2024 (134 of the 324 events in 2024), and both must be excluded:
    # they run modified rules with ad-hoc rosters.
    client = FakeEventListClient([
        event_payload("2024casj", event_type=0),      # Regional
        event_payload("2024mibel", event_type=1),     # District
        event_payload("2024micmp", event_type=2),     # District Championship
        event_payload("2024arc", event_type=3),       # Championship Division
        event_payload("2024cmptx", event_type=4),     # Championship Finals
        event_payload("2024micmp1", event_type=5),    # DCMP Division
        event_payload("2024offseason", event_type=99),
        event_payload("2024preseason", event_type=100),
    ])

    keys = official_event_keys(client, 2024)

    assert "2024offseason" not in keys
    assert "2024preseason" not in keys
    assert len(keys) == 6
    assert client.event_list_calls == [2024]


def test_official_event_keys_are_ordered_chronologically():
    # Championship finals must load after the divisions its roster comes from,
    # which start_date ordering guarantees.
    client = FakeEventListClient([
        event_payload("2024cmptx", event_type=4, start_date="2024-04-17"),
        event_payload("2024casj", event_type=0, start_date="2024-03-01"),
        event_payload("2024arc", event_type=3, start_date="2024-04-17"),
        event_payload("2024mibel", event_type=1, start_date="2024-02-29"),
    ])

    keys = official_event_keys(client, 2024)

    assert keys == ["2024mibel", "2024casj", "2024arc", "2024cmptx"]


def test_official_event_keys_reads_event_type_from_the_raw_body():
    # event_type is not a field on EventSummary. It is only reachable because
    # connectors hand back the untouched response body, so this asserts the
    # filter does not depend on the model being widened.
    assert not hasattr(EventSummary.model_validate(event_payload("2024casj", event_type=0)), "event_type")
    client = FakeEventListClient([event_payload("2024casj", event_type=0)])

    assert official_event_keys(client, 2024) == ["2024casj"]


def test_official_event_keys_tolerates_a_missing_start_date():
    client = FakeEventListClient([
        event_payload("2024late", event_type=0, start_date="2024-05-01"),
        event_payload("2024undated", event_type=0, start_date=None),
    ])

    # An undated event sorts first rather than raising a TypeError on None.
    assert official_event_keys(client, 2024) == ["2024undated", "2024late"]


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_one_failing_event_does_not_abort_the_season(stub_sync_event):
    stub_sync_event["state"]["fail_for"] = {"2024bad"}
    client = FakeEventListClient([])

    season = sync_season(
        2024, database=object(), tba=client,
        event_keys=["2024a", "2024bad", "2024b"], delay_seconds=0,
    )

    assert [call["event_key"] for call in stub_sync_event["calls"]] == ["2024a", "2024bad", "2024b"]
    assert season.events_succeeded == 2
    assert season.events_failed == 1
    assert season.failures[0][0] == "2024bad"
    assert "simulated failure for 2024bad" in season.failures[0][1]


def test_season_totals_sum_every_successful_event(stub_sync_event):
    season = sync_season(
        2024, database=object(), tba=FakeEventListClient([]),
        event_keys=["2024a", "2024b", "2024c"], delay_seconds=0,
    )

    assert season.loaded == {"matches": 6, "teams": 9}
    assert season.landed == {"tba.match": 6}
    assert season.records_loaded == 15


def test_a_failed_event_contributes_nothing_to_the_totals(stub_sync_event):
    stub_sync_event["state"]["fail_for"] = {"2024bad"}

    season = sync_season(
        2024, database=object(), tba=FakeEventListClient([]),
        event_keys=["2024a", "2024bad"], delay_seconds=0,
    )

    assert season.loaded == {"matches": 2, "teams": 3}
    assert season.records_loaded == 5


def test_sync_season_enumerates_when_no_event_keys_are_given(stub_sync_event):
    client = FakeEventListClient([
        event_payload("2024casj", event_type=0, start_date="2024-03-01"),
        event_payload("2024skip", event_type=99, start_date="2024-09-01"),
    ])

    season = sync_season(2024, database=object(), tba=client, delay_seconds=0)

    assert season.event_keys == ["2024casj"]
    assert [call["event_key"] for call in stub_sync_event["calls"]] == ["2024casj"]


# ---------------------------------------------------------------------------
# Statbotics circuit breaker
# ---------------------------------------------------------------------------


def test_statbotics_probe_passes_when_the_service_answers():
    client = FakeEventListClient([])
    statbotics = FakeSeasonStatbotics(available=True)

    assert statbotics_probe_failure(statbotics, client, "2024casj") is None
    assert statbotics.calls == [(1114, "2024casj")]


def test_statbotics_probe_reports_the_failure_reason():
    reason = statbotics_probe_failure(
        FakeSeasonStatbotics(available=False), FakeEventListClient([]), "2024casj",
    )

    assert reason is not None
    assert "1114" in reason and "2024casj" in reason
    assert "simulated Statbotics 500" in reason


def test_statbotics_probe_reports_an_event_with_no_teams():
    reason = statbotics_probe_failure(
        FakeSeasonStatbotics(available=True), FakeEventListClient([], teams=[]), "2024casj",
    )

    assert reason is not None
    assert "no teams" in reason


def test_a_dead_statbotics_is_probed_once_and_then_skipped(stub_sync_event):
    # The point of the circuit breaker: without it, extraction requests
    # Statbotics once per team per event -- thousands of calls that each burn the
    # full retry ladder against a service already known to be down.
    statbotics = FakeSeasonStatbotics(available=False)

    season = sync_season(
        2024, database=object(), tba=FakeEventListClient([]), statbotics=statbotics,
        event_keys=["2024a", "2024b", "2024c"], delay_seconds=0,
    )

    assert len(statbotics.calls) == 1, "Statbotics was called more than the single probe"
    assert season.statbotics_skipped_reason is not None
    # Every event ran, and every one ran without Statbotics.
    assert season.events_succeeded == 3
    assert all(call["statbotics"] is None for call in stub_sync_event["calls"])


def test_a_live_statbotics_is_passed_through_to_every_event(stub_sync_event):
    statbotics = FakeSeasonStatbotics(available=True)

    season = sync_season(
        2024, database=object(), tba=FakeEventListClient([]), statbotics=statbotics,
        event_keys=["2024a", "2024b"], delay_seconds=0,
    )

    assert season.statbotics_skipped_reason is None
    assert all(call["statbotics"] is statbotics for call in stub_sync_event["calls"])


def test_no_statbotics_means_no_probe_at_all(stub_sync_event):
    client = FakeEventListClient([])

    season = sync_season(
        2024, database=object(), tba=client, statbotics=None,
        event_keys=["2024a"], delay_seconds=0,
    )

    assert season.statbotics_skipped_reason is None
    # The probe needs a team list; not probing means not fetching one.
    assert client.event_teams_calls == []


def test_an_empty_season_probes_nothing_and_reports_nothing(stub_sync_event):
    statbotics = FakeSeasonStatbotics(available=False)

    season = sync_season(
        2024, database=object(), tba=FakeEventListClient([]), statbotics=statbotics,
        event_keys=[], delay_seconds=0,
    )

    assert statbotics.calls == []
    assert season.events_succeeded == 0
    assert season.statbotics_skipped_reason is None


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_rejects_both_an_event_key_and_a_season():
    with pytest.raises(SystemExit):
        orchestrator.main(["2024casj", "--season", "2024"])


def test_cli_rejects_neither_an_event_key_nor_a_season():
    with pytest.raises(SystemExit):
        orchestrator.main([])
