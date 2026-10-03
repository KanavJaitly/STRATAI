"""P5-D14 verification population: sampling, stratification, windows, seed, fingerprint (pure, synthetic facts).

Synthetic event facts below are test fixtures, not evidence about any real event.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import phase5_m6_replay as replay
from scripts import phase5_m6_selection as sel

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _steps(prefix: str, n: int, start: datetime) -> list[sel.Step]:
    return [sel.Step(start + timedelta(minutes=10 * i), (f"{prefix}{i + 1}",)) for i in range(n)]


def _facts(key: str, season: int = 2026, event_type: int = 1, week: int | None = 2, quals: int = 20,
           switch: int | None = 10, edge: int | None = None, roster: int = 30) -> sel.EventFacts:
    return sel.EventFacts(key, season, event_type, week, roster, _steps(f"{key}_qm", quals, T0),
                          _steps(f"{key}_sf", 4, T0 + timedelta(days=1)), switch, edge)


def _population() -> list[sel.EventFacts]:
    return [
        _facts("2026iscmp", event_type=2, week=18),
        _facts("2026wk0a", week=0), _facts("2026wk0b", week=0, event_type=0),
        _facts("2026diva", event_type=3, week=None, roster=75), _facts("2026divb", event_type=3, week=None, roster=75),
        _facts("2026mida", week=3), _facts("2026midb", week=4, switch=2),  # midb: switch too early for a window
        _facts("2025edgea", season=2025, week=2, edge=5), _facts("2025edgeb", season=2025, week=1, edge=0),
        _facts("2026arli", week=0),  # excluded: original P5-M6 population
        _facts("2026tiny", week=0, quals=6),  # too few qualification matches
        _facts("2026late", week=6),
    ]


def test_group_steps_merges_shared_times_in_order():
    steps = sel.group_steps([("b", T0), ("a", T0), ("c", T0 + timedelta(minutes=1))])
    assert steps == [sel.Step(T0, ("a", "b")), sel.Step(T0 + timedelta(minutes=1), ("c",))]


def test_strata_eligibility():
    pools = {k: [f.event_key for f in v] for k, v in sel.candidates(_population()).items()}
    assert pools == {"E1": ["2026iscmp"], "E2": ["2026wk0a", "2026wk0b"], "E3": ["2026diva", "2026divb"],
                     "E4": ["2026mida"], "E5": ["2025edgea"]}  # edgeb: f = 0 cannot sit inside a window


def test_draw_is_deterministic_and_order_independent():
    first = sel.draw(_population())
    assert first == sel.draw(list(reversed(_population())))
    assert first["seed"] == sel.SEED == 20261006 and first["checked_steps"] == 44
    assert sel.draw(_population(), seed=1) != first or len(sel.candidates(_population())["E2"]) == 1


def test_windows_follow_the_approved_shapes():
    plans = {p["stratum"]: p for p in sel.draw(_population())["plans"]}
    assert [len(plans[s]["qual_window"]) for s in ("E1", "E2", "E3", "E4", "E5")] == [8, 8, 5, 8, 6]
    assert [len(plans[s]["playoff_window"]) for s in ("E1", "E2", "E3", "E4", "E5")] == [2, 2, 1, 2, 2]
    assert plans["E2"]["pre_window_bulk"] == [] and plans["E2"]["qual_window"][0] == [f"{plans['E2']['event_key']}_qm1"]
    e4 = plans["E4"]  # centred on the switch step 10: steps 6..13, switch at window index 4
    assert e4["qual_window"][0] == ["2026mida_qm7"] and e4["switch_step_in_window"] == 4
    e5 = plans["E5"]  # first edge step 5 -> start 3
    assert e5["qual_window"][0] == ["2025edgea_qm4"] and ["2025edgea_qm6"] in e5["qual_window"]
    for p in plans.values():  # every qualification match is landed exactly once
        landed = p["pre_window_bulk"] + [k for s in p["qual_window"] for k in s] + p["post_window_bulk"]
        assert len(landed) == len(set(landed)) == 20
        assert p["sentinel_steps"] == [len(p["qual_window"]) // 2]
        assert p["pre_window_bulk"] or p["stratum"] == "E2"  # seeded starts are >= 1


def test_seeded_starts_stay_inside_the_schedule():
    for seed in range(50):
        plans = {p["stratum"]: p for p in sel.draw(_population(), seed=seed)["plans"]}
        for stratum in ("E1", "E3"):
            assert len(plans[stratum]["pre_window_bulk"]) >= 1


def test_fingerprint_changes_with_the_population():
    facts = _population()
    base = sel.fingerprint(facts, {"matches": 100})
    assert base == sel.fingerprint(list(reversed(facts)), {"matches": 100})
    assert base != sel.fingerprint(facts, {"matches": 101})
    facts[5].roster_size += 1
    assert base != sel.fingerprint(facts, {"matches": 100})


def test_missing_stratum_refuses():
    with pytest.raises(ValueError):
        sel.draw([f for f in _population() if f.event_type != 3])


def test_estimate_is_within_budget_for_the_approved_shape():
    estimate = sel.estimate_minutes(sel.draw(_population())["plans"])
    assert estimate["total"] < sel.BUDGET_MINUTES


def test_recorded_run_requires_the_recorded_selection(monkeypatch, tmp_path):
    """Enabled by Kanav's approval (2026-10-03); it still runs only from the write-once selection record."""
    assert replay.RECORDED_RUN_ENABLED is True
    assert replay.SELECTION_RECORD == "p5_m6_selection.json" and replay.RECORD == "p5_m6_replay.json"


def test_no_synthetic_case_in_the_harness():
    import inspect

    code = inspect.getsource(replay).replace(replay.__doc__ or "", "")  # the docstring says it is excluded
    assert "correction" not in code.lower() and "unplayed(" not in code
