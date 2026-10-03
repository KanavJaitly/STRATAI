"""P5-M6 replay source: recorded payloads served as they stood at the replay instant (pure, synthetic)."""

from __future__ import annotations

from data.replay import RecordedEvent, ReplayTBAClient, unplayed


def _match(key: str, level: str, time: int) -> dict:
    return {"key": key, "comp_level": level, "time": time, "event_key": "2026x", "winning_alliance": "red",
            "actual_time": time + 60, "post_result_time": time + 300, "score_breakdown": {"red": {}, "blue": {}},
            "alliances": {"red": {"score": 50, "team_keys": ["frc1", "frc2", "frc3"]},
                          "blue": {"score": 40, "team_keys": ["frc4", "frc5", "frc6"]}}}


def _client() -> ReplayTBAClient:
    matches = {m["key"]: m for m in (_match("2026x_qm1", "qm", 100), _match("2026x_qm2", "qm", 200),
                                     _match("2026x_sf1m1", "sf", 300))}
    teams = {f"frc{i}": {"key": f"frc{i}", "team_number": i} for i in range(1, 7)}
    return ReplayTBAClient({"2026x": RecordedEvent("2026x", {"key": "2026x"}, matches, teams)})


def test_unplayed_is_tbas_representation_and_leaves_the_recording_alone():
    played = _match("k", "qm", 1)
    placeholder = unplayed(played)
    assert placeholder["alliances"]["red"]["score"] == -1 and placeholder["score_breakdown"] is None
    assert placeholder["winning_alliance"] == "" and placeholder["actual_time"] is None
    assert played["alliances"]["red"]["score"] == 50  # deep copy


def test_schedule_before_and_after_completion():
    client = _client()
    before = {m.raw["key"]: m.raw for m in client.fetch_event_matches("2026x")}
    assert set(before) == {"2026x_qm1", "2026x_qm2"}  # playoffs appear only once played
    assert all(m["alliances"]["red"]["score"] == -1 for m in before.values())
    client.complete(["2026x_qm1", "2026x_sf1m1"])
    after = {m.raw["key"]: m.raw for m in client.fetch_event_matches("2026x")}
    assert after["2026x_qm1"]["alliances"]["red"]["score"] == 50 and after["2026x_qm2"]["alliances"]["red"]["score"] == -1
    assert "2026x_sf1m1" in after
    assert client.events["2026x"].ordered_matches()[0] == (100, "2026x_qm1")
    assert client.fetch_team_info(4).raw["team_number"] == 4
