"""PX-2b v2 (`.agent/phase6/P6_M3_PX2B_SPEC_V2.md`, blob b4397537; approved 2026-10-08): out-of-sample calibration.

The requirements (decisions/P6_PX2B_V2_APPROVAL_2026-10-08.md) are tested on SYNTHETIC rows, except the provenance
tests at the end. Those read the real PX-1b rows cache and records, with no database, model evaluation or 2027 data,
and skip when the artifacts are absent.
"""

from __future__ import annotations

import gzip
import json
import pickle
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.playoffs.px1 import PlayoffLogisticModel
from ml.playoffs.px2b import (CalibrationIsolationError, calibration_base_rows, calibration_slice,
                              fit_out_of_sample_calibrator, isolation_report, require_frozen_slice, require_isolated,
                              straddling_events)
from tests.test_phase6_px1 import synthetic_rows

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
CACHE = Path("C:/Dev/StratAI-artifacts/phase6/px_rows_px1-v2.pkl.gz")
RESULTS = Path(".agent/phase6/results")


def _season(rows, season, start, *, events_of=10):
    """Rows of one season, one per minute from `start`, `events_of` consecutive matches per event."""
    return [replace(r, season=season, scheduled_time=start + timedelta(minutes=i),
                    event_key=f"{season}e{i // events_of:03d}", match_key=f"{season}m{i:04d}")
            for i, r in enumerate(rows)]


def _world(n_2025: int = 300, n_2026: int = 200):
    base = synthetic_rows(n_2025 + n_2026, 21)
    return _season(base[:n_2025], 2025, T0 - timedelta(days=300)) + _season(base[n_2025:], 2026, T0)


# --- 1/2: the slice and the base population ------------------------------------------------------------------


def test_the_slice_is_the_last_20_percent_of_2026_by_time_then_key():
    rows = _world()
    slice_rows = calibration_slice(rows)
    season = sorted((r for r in rows if r.season == 2026), key=lambda r: (r.scheduled_time, r.match_key))
    assert slice_rows == season[160:] and len(slice_rows) == 40


def test_the_base_excludes_every_row_at_or_after_the_slice_and_every_straddling_event():
    rows = _world()  # 2026 events of 10 matches: the cut at 2026 row 160 is an event boundary
    shifted = [replace(r, event_key="2026e016") if r.match_key in ("2026m0155", "2026m0158") else r for r in rows]
    slice_rows = calibration_slice(shifted)  # slice event 2026e016 now also has two rows before the cut
    base = calibration_base_rows(shifted, slice_rows)
    start = min(r.scheduled_time for r in slice_rows)
    assert all(r.scheduled_time < start for r in base)
    assert straddling_events(shifted, slice_rows) == ["2026e016"]
    assert not {r.event_key for r in base} & {r.event_key for r in slice_rows}
    assert {"2026m0155", "2026m0158"}.isdisjoint(r.match_key for r in base)  # excluded although earlier in time
    assert len(base) == 300 + 160 - 2


def test_the_built_slice_must_equal_the_frozen_keys_exactly():
    slice_rows = calibration_slice(_world())
    keys = [r.match_key for r in slice_rows]
    require_frozen_slice(slice_rows, keys)
    for frozen in (keys[:-1], keys + ["extra"], list(reversed(keys)), keys[:-1] + ["other"]):
        with pytest.raises(CalibrationIsolationError):
            require_frozen_slice(slice_rows, frozen)


# --- 3: per-prediction out-of-sample proof --------------------------------------------------------------------


def _report(base, slice_rows, *, latest=None):
    return isolation_report([r.match_key for r in base], [r.event_key for r in base],
                            latest or max(r.scheduled_time for r in base), slice_rows)


def test_isolation_holds_only_when_matches_events_and_time_are_all_disjoint():
    rows = _world()
    slice_rows = calibration_slice(rows)
    base = calibration_base_rows(rows, slice_rows)
    good = _report(base, slice_rows)
    assert good["isolated"] and good["match_overlap"] == 0 and good["event_overlap"] == 0 and good["time_ordered"]
    require_isolated(good)
    leaked_match = _report(base + [slice_rows[0]], slice_rows)
    assert not leaked_match["isolated"] and leaked_match["match_overlap"] == 1
    other_match_same_event = replace(base[0], match_key="elsewhere", event_key=slice_rows[5].event_key)
    leaked_event = _report(base + [other_match_same_event], slice_rows,
                           latest=max(r.scheduled_time for r in base))
    assert not leaked_event["isolated"] and leaked_event["match_overlap"] == 0 and leaked_event["event_overlap"] > 0
    late = _report(base, slice_rows, latest=slice_rows[0].scheduled_time)  # disjoint keys/events, but not earlier
    assert not late["isolated"] and not late["time_ordered"]
    for report in (leaked_match, leaked_event, late):
        with pytest.raises(CalibrationIsolationError):
            require_isolated(report)


# --- 4: the calibrator sees only the base model's out-of-sample predictions ----------------------------------


def test_the_calibrator_is_fit_only_on_base_predictions_and_slice_outcomes(monkeypatch):
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator

    rows = _world()
    slice_rows = calibration_slice(rows)
    base = calibration_base_rows(rows, slice_rows)
    base_model = PlayoffLogisticModel.fit(base, normalized=True, model_type="playoff_px1b_calbase")
    seen = []
    monkeypatch.setattr(SymmetricIsotonicCalibrator, "fit", lambda self, p, y: seen.append((list(p), list(y))))
    _, report = fit_out_of_sample_calibrator(base_model, [r.match_key for r in base], [r.event_key for r in base],
                                             max(r.scheduled_time for r in base), slice_rows)
    assert report["isolated"] and report["slice_rows"] == 40
    assert seen == [([base_model.predict(r) for r in slice_rows], [r.red_win for r in slice_rows])]


def test_the_calibrator_refuses_in_sample_predictions():
    rows = _world()
    slice_rows = calibration_slice(rows)
    in_sample = PlayoffLogisticModel.fit(rows, normalized=True)  # v1's situation: trained on the slice
    with pytest.raises(CalibrationIsolationError):
        fit_out_of_sample_calibrator(in_sample, [r.match_key for r in rows], [r.event_key for r in rows],
                                     max(r.scheduled_time for r in rows), slice_rows)


# --- 5/6: through the harness: applied to the candidate, gate unchanged --------------------------------------


@pytest.fixture
def accepted_px1b(tmp_path, monkeypatch):
    """SYNTHETIC: PX-1b's acceptance and a calibration-base record and registry entry in tmp dirs."""
    import scripts.phase6_common as common
    from scripts import phase6_playoff_track as track
    from scripts.phase6_common import file_sha256

    results, registry = tmp_path / "results", tmp_path / "registry"
    results.mkdir()
    for module in (common, track):
        monkeypatch.setattr(module, "RESULTS_DIR", results)
    monkeypatch.setattr(track, "REGISTRY_DIR", registry)
    monkeypatch.setattr(track, "ROWS_CACHE_DIR", tmp_path)
    t = replace(track.PX1B_TRACK, confirmation=tmp_path / "confirmation.json")
    (results / t.model_record).write_text(json.dumps({"passed": True}), encoding="utf-8")
    t.confirmation.write_text(json.dumps({"confirmed": True, "confirmed_by": "SYNTHETIC", "date": "2099-01-01",
                                          "record": t.model_record,
                                          "record_sha256": file_sha256(results / t.model_record)}), encoding="utf-8")
    return t, results, registry


def _synthetic_track_world(t, results, registry, monkeypatch):
    import ml.playoffs.px2b as px2b
    from ml.playoffs.px1b import dataset_fingerprint
    from scripts import phase6_playoff_track as track

    rows26 = _world()
    base_synth = synthetic_rows(120, 33)
    rows27 = _season(base_synth, 2027, T0 + timedelta(days=365))
    rows = rows26 + rows27
    slice_rows = calibration_slice(rows26)
    base = calibration_base_rows(rows26, slice_rows)
    base_model = PlayoffLogisticModel.fit(base, normalized=True, model_type="playoff_px1b_calbase")
    candidate = PlayoffLogisticModel.fit(rows26, normalized=True, model_type="playoff_px1b")  # px1b-v1 stand-in
    base_dir = registry / "playoff_px1b_calbase" / "px2b-v2"
    base_dir.mkdir(parents=True)
    base_model.save(base_dir / "model.json")
    (base_dir / "manifest.json").write_text(json.dumps({"training_dataset_hash": dataset_fingerprint(base)}),
                                            encoding="utf-8")
    (results / t.calibration_base_record).write_text(json.dumps({
        "registry": {"model_type": "playoff_px1b_calbase", "version_tag": "px2b-v2"},
        "base": {"fingerprint": dataset_fingerprint(base), "match_keys": [r.match_key for r in base],
                 "events": sorted({r.event_key for r in base}),
                 "latest": max(r.scheduled_time for r in base).isoformat()}}), encoding="utf-8")
    monkeypatch.setattr(px2b, "frozen_slice_keys", lambda path=None: [r.match_key for r in slice_rows])
    monkeypatch.setattr(track, "_models", lambda tr=None: (candidate, candidate))
    monkeypatch.setattr(track, "_track_rows", lambda database, rulesets, tr: rows)
    return rows27, slice_rows, base_model, candidate


def test_px2b_v2_calibrates_out_of_sample_and_evaluates_the_candidate(accepted_px1b, monkeypatch):
    from ml.calibration import gate as gate_module
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from scripts import phase6_playoff_track as track

    t, results, registry = accepted_px1b
    rows27, slice_rows, base_model, candidate = _synthetic_track_world(t, results, registry, monkeypatch)
    fit_inputs, gate_inputs = [], []
    original_fit = SymmetricIsotonicCalibrator.fit
    monkeypatch.setattr(SymmetricIsotonicCalibrator, "fit",
                        lambda self, p, y: (fit_inputs.append(list(p)), original_fit(self, p, y))[1])
    original_gate = gate_module.evaluate_calibration_gate
    monkeypatch.setattr(gate_module, "evaluate_calibration_gate",
                        lambda q, y, **kw: (gate_inputs.append(list(q)), original_gate(q, y, **kw))[1])
    result = track.run_m3(None, None, t)
    assert fit_inputs == [[base_model.predict(r) for r in slice_rows]]  # base model, never the candidate
    assert fit_inputs[0] != [candidate.predict(r) for r in slice_rows]
    calibrator = SymmetricIsotonicCalibrator.load(track.ROWS_CACHE_DIR / "px2b_calibrator.json")
    assert gate_inputs == [[calibrator.calibrate(candidate.predict(r)) for r in rows27]]  # applied to px1b-v1
    assert result["calibration"]["isolation"]["isolated"] and result["calibration"]["applied_to"] == "playoff_px1b px1b-v1"
    assert result["slice_rows"] == 40 and result["evaluated"] == len(rows27)
    assert result["specs"]["px2b"]["path"].endswith("P6_M3_PX2B_SPEC_V2.md")


def test_px2b_v2_refuses_a_changed_slice_or_a_mismatched_base_model(accepted_px1b, monkeypatch):
    import ml.playoffs.px2b as px2b
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    t, results, registry = accepted_px1b
    _, slice_rows, _, _ = _synthetic_track_world(t, results, registry, monkeypatch)
    monkeypatch.setattr(px2b, "frozen_slice_keys", lambda path=None: [r.match_key for r in slice_rows][1:])
    with pytest.raises(CalibrationIsolationError):
        track.run_m3(None, None, t)  # the slice is not the frozen one
    monkeypatch.setattr(px2b, "frozen_slice_keys", lambda path=None: [r.match_key for r in slice_rows])
    manifest = registry / "playoff_px1b_calbase" / "px2b-v2" / "manifest.json"
    manifest.write_text(json.dumps({"training_dataset_hash": "0" * 64}), encoding="utf-8")
    with pytest.raises(Blocked):
        track.run_m3(None, None, t)  # the registered base model was not trained on the recorded set


def test_px2b_v2_refuses_if_the_spec_is_not_the_approved_blob(accepted_px1b, monkeypatch):
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    t, results, registry = accepted_px1b
    _synthetic_track_world(t, results, registry, monkeypatch)
    monkeypatch.setattr(track, "git_blob", lambda path: "f" * 40)
    with pytest.raises(Blocked):
        track.run_m3(None, None, t)


# --- 7: blocked runs refuse ------------------------------------------------------------------------------------


def test_the_calibration_base_fit_refuses_once_2027_data_exists_or_without_px1b_v1(monkeypatch):
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    monkeypatch.setattr(harness, "read_record", lambda name: None)
    with pytest.raises(Blocked):
        harness.run_calbase(None, None)  # no px1b-v1 final-fit record
    monkeypatch.setattr(harness, "read_record", lambda name: {"dataset_fingerprint": "x"})
    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 5 if season == 2027 else 0)
    with pytest.raises(Blocked):
        harness.run_calbase(None, None)  # 2027 outcomes exist: too late to freeze the base


def test_the_real_px2b_v2_run_is_blocked_today():
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    assert not (RESULTS / "p6_px1b_gate_2027.json").exists()  # PX-1b is not accepted
    with pytest.raises(Blocked):
        track.run_m3(None, None, track.PX1B_TRACK)


# --- 1/8: provenance reproducible from the real artifacts (no DB, no evaluation, no 2027 data) ---------------


@pytest.fixture(scope="module")
def real_rows():
    if not CACHE.exists():
        pytest.skip("the PX-1b rows cache is not on this machine")
    from ml.playoffs.px1b import drop_scale_absent

    rows = pickle.loads(gzip.decompress(CACHE.read_bytes()))
    return drop_scale_absent(rows)[0]


def test_the_real_slice_is_the_frozen_526_and_the_population_is_px1b_v1s(real_rows):
    from ml.playoffs.px1b import dataset_fingerprint
    from ml.playoffs.px2b import frozen_slice_keys

    final = json.loads((RESULTS / "p6_px1b_final_fit.json").read_text(encoding="utf-8"))
    assert dataset_fingerprint(real_rows) == final["dataset_fingerprint"]
    slice_rows = calibration_slice(real_rows)
    require_frozen_slice(slice_rows, frozen_slice_keys())
    assert len(slice_rows) == 526


def test_the_real_base_is_isolated_and_excludes_the_11_straddling_events(real_rows):
    slice_rows = calibration_slice(real_rows)
    base = calibration_base_rows(real_rows, slice_rows)
    report = _report(base, slice_rows)
    assert report["isolated"] and report["match_overlap"] == 0 and report["event_overlap"] == 0
    assert len(straddling_events(real_rows, slice_rows)) == 11


def test_the_recorded_calibration_base_matches_a_rebuild(real_rows):
    from ml.playoffs.px1b import dataset_fingerprint

    path = RESULTS / "p6_px2b_calbase.json"
    if not path.exists():
        pytest.skip("p6_px2b_calbase.json not recorded yet")
    record = json.loads(path.read_text(encoding="utf-8"))
    slice_rows = calibration_slice(real_rows)
    base = calibration_base_rows(real_rows, slice_rows)
    assert record["base"]["fingerprint"] == dataset_fingerprint(base)
    assert record["base"]["match_keys"] == [r.match_key for r in base]
    assert record["isolation"]["isolated"] and record["slice"]["equals_frozen_keys"]
