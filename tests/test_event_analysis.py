"""P5-M4 policy and statistics helpers (ml.views.event_analysis). Pure; synthetic values."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.views import event_analysis as ea

T = datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_switch_time_is_the_last_teams_midpoint_match():
    matches = {1: [T + timedelta(hours=h) for h in (1, 2, 3, 4)],  # ceil(4/2)=2 -> +2h
               2: [T + timedelta(hours=h) for h in (1, 5, 6)]}  # ceil(3/2)=2 -> +5h
    assert ea.switch_time(matches) == T + timedelta(hours=5)
    assert ea.switch_time({}) is None
    assert [ea.midpoint_index(n) for n in (1, 2, 3, 12)] == [1, 1, 2, 6]


@pytest.mark.parametrize(("passed", "serve", "expected"), [
    (False, True, ea.POLICY_RAW_EPA), (True, True, ea.POLICY_M5V2), (True, False, ea.POLICY_RAW_EPA),
    (False, False, ea.POLICY_RAW_EPA)])
def test_policy_serves_m5v2_only_after_the_switch_and_only_if_measured_better(passed, serve, expected):
    assert ea.policy_model(passed, serve) == expected


def test_unmeasured_policy_serves_raw_epa_throughout(monkeypatch):
    monkeypatch.setattr(ea, "SERVE_M5V2_AFTER_SWITCH", None)
    assert ea.policy_model(True) == ea.POLICY_RAW_EPA


class _F:
    def __init__(self, team, value):
        self.team_number, self.value = team, value


def test_ordering_ties_and_captains():
    teams = [_F(3, 1.0), _F(1, float("-inf")), _F(2, 1.0), _F(4, 5.0)]
    ordering = ea.order_teams(teams, lambda f: f.value)  # type: ignore[arg-type]
    assert [o.team_number for o in ordering] == [4, 2, 3, 1]
    assert ea.captain_hit_rate(ordering, {4, 1, 99}) == 2 / 8


def test_event_spearman_needs_two_ranked_teams():
    assert ea.event_spearman({1: 3.0, 2: 1.0, 3: 2.0}, {1: 1, 2: 3, 3: 2}) == pytest.approx(1.0)
    assert ea.event_spearman({1: 3.0}, {1: 1}) is None


def test_paired_bootstrap_is_deterministic():
    first = ea.paired_bootstrap([0.1, -0.05, 0.2, 0.0])
    assert first == ea.paired_bootstrap([0.1, -0.05, 0.2, 0.0])
    assert first["mean_difference"] == pytest.approx(0.0625) and first["ci95"][0] <= 0.0625 <= first["ci95"][1]


def test_served_policy_constant_matches_the_record():
    record = Path(ea.RECORD)
    if not record.exists():
        assert ea.SERVE_M5V2_AFTER_SWITCH is None  # not measured: raw EPA throughout
        return
    measured = json.loads(record.read_text(encoding="utf-8"))["b_served_policy"]["serve_m5v2_after_switch"]
    assert ea.SERVE_M5V2_AFTER_SWITCH is measured
