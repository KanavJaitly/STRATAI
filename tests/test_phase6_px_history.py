"""HV-1 (`.agent/phase6/P6_PX_HISTORICAL_VALIDATION_SPEC_V1.md`): fold construction, the walk-forward assertions, and
the statistics. SYNTHETIC (not evidence), except the cache-integrity test, which reads the real rows cache when it is
present."""

from __future__ import annotations

import math
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ml.playoffs.history import (Fold, FoldError, calibration_slope, fold_assertions, paired, season_fold,
                                 within_season_fold)
from tests.test_phase6_px1 import synthetic_rows

T0 = datetime(2024, 3, 1, tzinfo=timezone.utc)


def _rows():
    """3 seasons x 8 events x 10 matches; each event's selection moment is 1 hour before its first match."""
    base = synthetic_rows(240, 41)
    rows, selection = [], {}
    for i, r in enumerate(base):
        season, event = 2024 + i // 80, f"{2024 + i // 80}e{(i % 80) // 10}"
        start = T0 + timedelta(days=365 * (season - 2024) + 7 * ((i % 80) // 10))
        rows.append(replace(r, season=season, event_key=event, match_key=f"{event}_m{i % 10}",
                            scheduled_time=start + timedelta(minutes=i % 10)))
        selection[event] = start - timedelta(hours=1)
    return rows, selection


def test_season_folds_take_whole_seasons_and_pass_the_walk_forward_assertions():
    rows, selection = _rows()
    f2 = season_fold("F2", rows, (2024, 2025), 2026)
    assert {r.season for r in f2.train} == {2024, 2025} and {r.season for r in f2.test} == {2026}
    report = fold_assertions(f2, selection)
    assert report["time_ordered"] and report["shared_events"] == []


def test_the_within_season_fold_follows_the_median_selection_cutoff():
    rows, selection = _rows()
    f0 = within_season_fold("F0", rows, 2024, selection)
    events = sorted({r.event_key for r in rows if r.season == 2024}, key=lambda e: (selection[e], e))
    assert f0.cutoff == selection[events[4]]
    assert all(r.scheduled_time < f0.cutoff for r in f0.train)
    assert all(selection[r.event_key] >= f0.cutoff for r in f0.test)
    assert len(f0.train) + len(f0.test) + f0.excluded == 80
    fold_assertions(f0, selection)


def test_a_fold_that_is_not_walk_forward_is_refused():
    rows, selection = _rows()
    good = season_fold("F1", rows, (2024,), 2025)
    leaked_event = Fold("x", good.train + (good.test[0],), good.test, 0)
    with pytest.raises(FoldError):
        fold_assertions(leaked_event, selection)  # a test event also in training
    late = replace(good.train[0], scheduled_time=selection[good.test[0].event_key] + timedelta(minutes=1),
                   match_key="late", event_key="2024late")
    selection["2024late"] = T0
    with pytest.raises(FoldError):
        fold_assertions(Fold("y", good.train + (late,), good.test, 0), selection)  # an outcome after a test selection
    with pytest.raises(FoldError):
        fold_assertions(Fold("z", (), good.test, 0), selection)


def test_calibration_slope_is_near_one_when_calibrated_and_below_one_when_overconfident():
    rng = random.Random(7)
    p = [rng.uniform(0.05, 0.95) for _ in range(20000)]
    y = [rng.random() < q for q in p]
    assert calibration_slope(p, y)["slope"] == pytest.approx(1.0, abs=0.06)
    sharpened = [1 / (1 + math.exp(-3 * math.log(q / (1 - q)))) for q in p]
    assert calibration_slope(sharpened, y)["slope"] < 0.5
    assert calibration_slope([0.3, 0.7], [True, True])["slope"] is None


def test_paired_reading_follows_the_frozen_rules():
    labels = [True, False] * 40
    events = [f"e{i // 8}" for i in range(80)]
    good = [0.8 if y else 0.2 for y in labels]
    coin = [0.5] * 80
    assert paired(good, coin, labels, events)["reading"] == "statistically supported"
    assert paired(coin, good, labels, events)["reading"] == "not better"
    assert paired(good, good, labels, events)["reading"] == "not better"  # a zero difference is not an improvement


def test_hv1_refuses_a_different_cache_or_spec(monkeypatch, tmp_path):
    import scripts.phase6_px_history as hv
    from scripts.phase6_playoff_track import Blocked

    fake = tmp_path / "rows.pkl.gz"
    fake.write_bytes(b"not the cache")
    monkeypatch.setattr(hv, "CACHE", fake)
    with pytest.raises(Blocked):
        hv.load_rows()
    monkeypatch.setattr(hv, "git_blob", lambda path: "0" * 40)
    with pytest.raises(Blocked):
        hv.run(None)


def test_the_real_cache_matches_the_spec_when_present():
    import scripts.phase6_px_history as hv

    if not hv.CACHE.exists():
        pytest.skip("the PX rows cache is not on this machine")
    rows = hv.load_rows()
    assert len(rows) == 991 + 2435 + 2626
