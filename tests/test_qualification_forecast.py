"""P5-M5 forecast helpers (ml.views.qualification_forecast). Pure; synthetic values."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml.calibration.gate import central_interval, poisson_binomial_pmf
from ml.views import qualification_forecast as qf


def test_central_80_follows_the_gate_convention():
    pmf = poisson_binomial_pmf([0.5] * 10)
    low, high = qf.central_80(pmf)
    cdf = np.cumsum(pmf)
    assert cdf[low] >= 0.10 and (low == 0 or cdf[low - 1] < 0.10)
    assert cdf[high] >= 0.90 and cdf[high - 1] < 0.90
    wide = central_interval(pmf)  # the 95% sibling is never narrower
    assert wide[0] <= low and high <= wide[1]


def test_expected_wins_sum_q_with_blue_complement():
    records = qf.team_records([qf.MatchForecast("m1", (1, 2, 3), (4, 5, 6), 0.7, True),
                               qf.MatchForecast("m2", (1, 4, 7), (2, 5, 8), 0.4, False)])
    assert records[1].expected_wins == pytest.approx(1.1) and records[1].matches == 2
    assert records[4].expected_wins == pytest.approx(0.3 + 0.4)
    assert records[3].record_status() == (qf.RECORD_VALIDATED, None)
    assert records[1].record_status() == (qf.NOT_VALIDATED, qf.REASON_EPA_INCOMPLETE)


@pytest.mark.parametrize(("measured", "expected"), [
    (True, (qf.RECORD_VALIDATED, None)), (False, (qf.NOT_VALIDATED, qf.REASON_RANGE_COVERAGE))])
def test_range_label_follows_the_single_measurement(measured, expected):
    record = qf.team_records([qf.MatchForecast("m", (1,), (2,), 0.6, True)])[1]
    assert record.range_status(measured) == expected


def test_unmeasured_range_is_not_validated(monkeypatch):
    monkeypatch.setattr(qf, "RANGE_COVERAGE_VALIDATED", None)
    record = qf.team_records([qf.MatchForecast("m", (1,), (2,), 0.6, True)])[1]
    assert record.range_status() == (qf.NOT_VALIDATED, qf.REASON_RANGE_NOT_MEASURED)


def test_coverage_and_reproduction_statistics():
    rows = [("e", [1], [2], 0.9, True), ("e", [1], [2], 0.9, True), ("e", [1], [2], 0.1, False)]
    team_events = qf.by_team_event(rows)
    assert team_events[("e", 1)] == ([0.9, 0.9, 0.1], 2) and team_events[("e", 2)][1] == 1
    stats = qf.actual_minus_expected(list(team_events.values()))
    assert stats["mean_actual_minus_expected"] == pytest.approx(((2 - 1.9) + (1 - 1.1)) / 2)
    result = qf.coverage(list(team_events.values()))
    assert result["team_events"] == 2 and 0 <= result["coverage"] <= 1


def test_range_constant_matches_the_record():
    record = Path(qf.RECORD)
    if not record.exists():
        assert qf.RANGE_COVERAGE_VALIDATED is None
        return
    measured = json.loads(record.read_text(encoding="utf-8"))["b_range_coverage"]["within_band"]
    assert qf.RANGE_COVERAGE_VALIDATED is measured
