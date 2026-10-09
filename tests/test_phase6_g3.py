"""G3 integrity hardening (approved by Kanav 2026-10-09): the PX-2b calibrator and M8b's ranking model load only after
they match their recorded hashes, and the pin record v2 is additive. SYNTHETIC fixtures in tmp dirs, plus copies of
the real ranking artifact when present. Never the real registry or results, and never a database."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ml.playoffs.pins import (PIN_RECORD, PIN_RECORD_V1, PIN_VERSION, PinError, RANKING_D18, read_pins,
                              require_file_hash)
from ml.playoffs.px1 import PlayoffLogisticModel
from tests.test_phase6_px2b_v2 import _world, write_synthetic_pins

REAL_REGISTRY = Path("C:/Dev/StratAI-artifacts/ml_registry")
REAL_RESULTS = Path(".agent/phase6/results")


@pytest.fixture
def g3(tmp_path, monkeypatch):
    """A pinned PX-1b world in tmp dirs: accepted (SYNTHETIC), px1b models, pins v2, a PX-2b record and calibrator."""
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    import scripts.phase6_common as common
    from scripts import phase6_playoff_track as track
    from scripts.phase6_common import file_sha256

    results, registry, cache = tmp_path / "results", tmp_path / "registry", tmp_path / "cache"
    results.mkdir()
    cache.mkdir()
    for module in (common, track):
        monkeypatch.setattr(module, "RESULTS_DIR", results)
    monkeypatch.setattr(track, "REGISTRY_DIR", registry)
    monkeypatch.setattr(track, "ROWS_CACHE_DIR", cache)
    rows = _world()
    for model_type, seed_only in (("playoff_px1b", False), ("playoff_px1b_seed_only", True)):
        (registry / model_type / "px1b-v1").mkdir(parents=True)
        PlayoffLogisticModel.fit(rows, seed_only=seed_only, normalized=not seed_only,
                                 model_type=model_type).save(registry / model_type / "px1b-v1" / "model.json")
    t = replace(track.PX1B_TRACK, confirmation=tmp_path / "confirmation.json")
    from ml.playoffs.px2b import calibration_slice
    write_synthetic_pins(results / t.pins_record, registry,
                         [("playoff_px1b", "px1b-v1"), ("playoff_px1b_seed_only", "px1b-v1")], calibration_slice(rows))
    (results / t.model_record).write_text(json.dumps({"passed": True}), encoding="utf-8")
    t.confirmation.write_text(json.dumps({"confirmed": True, "confirmed_by": "SYNTHETIC", "date": "2099-01-01",
                                          "record": t.model_record,
                                          "record_sha256": file_sha256(results / t.model_record)}), encoding="utf-8")
    calibrator = SymmetricIsotonicCalibrator()
    calibrator.fit([0.2, 0.4, 0.6, 0.8] * 10, [False, False, True, True] * 10)
    calibrator.save(cache / t.calibrator_file)
    sha = file_sha256(cache / t.calibrator_file)
    (results / t.px2_record).write_text(json.dumps({"passed": True, "calibrator": {"file": t.calibrator_file,
                                                                                   "sha256": sha}}), encoding="utf-8")
    for name in t.m1_records:
        (results / name).write_text(json.dumps({"events": {}}), encoding="utf-8")
    return track, t, results, registry, cache


# --- the PX-2b calibrator --------------------------------------------------------------------------------------


def test_the_recorded_calibrator_loads(g3):
    track, t, results, registry, cache = g3
    calibrator = track._load_calibrator(t)
    assert 0.0 <= calibrator.calibrate(0.7) <= 1.0


def test_an_altered_calibrator_is_refused(g3, capsys):
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = g3
    path = cache / t.calibrator_file
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")  # one byte
    with pytest.raises(Blocked):
        track._load_calibrator(t)
    assert "is not the recorded" in capsys.readouterr().err


def test_missing_or_inconsistent_calibrator_provenance_is_refused(g3, capsys):
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = g3
    (results / t.px2_record).write_text(json.dumps({"passed": True}), encoding="utf-8")  # no calibrator sha256
    with pytest.raises(Blocked):
        track._load_calibrator(t)
    assert "inconsistent provenance" in capsys.readouterr().err
    (results / t.px2_record).unlink()
    with pytest.raises(Blocked):
        track._load_calibrator(t)  # no PX-2b record at all
    (results / t.px2_record).write_text(json.dumps({"passed": True, "calibrator": {"sha256": "a" * 64}}), "utf-8")
    (cache / t.calibrator_file).unlink()
    with pytest.raises(Blocked):
        track._load_calibrator(t)
    assert "missing" in capsys.readouterr().err


def test_px4b_and_m8b_refuse_an_altered_calibrator_with_no_unpinned_fallback(g3, tmp_path, monkeypatch):
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = g3
    (cache / t.calibrator_file).write_text("{}", encoding="utf-8")
    loaded = []
    monkeypatch.setattr(SymmetricIsotonicCalibrator, "load", classmethod(lambda cls, p: loaded.append(p)))
    with pytest.raises(Blocked):
        track.run_m5(None, None, t)
    (results / t.px4_record).write_text(json.dumps({"passed": True}), encoding="utf-8")
    t8 = replace(t, m8_pre_run=tmp_path / "PRE.md", m8_pre_run_json=tmp_path / "pre.json")
    t8.m8_pre_run.write_text("synthetic", encoding="utf-8")
    t8.m8_pre_run_json.write_text(json.dumps({
        "seed": 1, "per_stratum": 1, "reason_categories": [{"code": "x"}], "mentor": "SYNTHETIC MENTOR",
        "mentor_agreement": {"confirmed": True, "date": "d", "evidence": "e"}}), encoding="utf-8")
    with pytest.raises(Blocked):
        track.run_m8(None, None, t8)
    assert loaded == []  # the altered file was never deserialized


def test_the_px1_chain_still_loads_its_calibrator_unpinned(tmp_path, monkeypatch):
    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from scripts import phase6_playoff_track as track

    monkeypatch.setattr(track, "ROWS_CACHE_DIR", tmp_path)
    c = SymmetricIsotonicCalibrator()
    c.fit([0.3, 0.7] * 10, [False, True] * 10)
    c.save(tmp_path / track.PX1_TRACK.calibrator_file)
    assert track._load_calibrator(track.PX1_TRACK).calibrate(0.7) >= 0.5  # frozen PX-1 behaviour


def test_require_file_hash_rules(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("x", encoding="utf-8")
    import hashlib
    require_file_hash("a", f, hashlib.sha256(b"x").hexdigest())
    for expected in (None, "", "b" * 64):
        with pytest.raises(PinError):
            require_file_hash("a", f, expected)
    with pytest.raises(PinError):
        require_file_hash("a", tmp_path / "absent", "c" * 64)


# --- M8b's ranking model ---------------------------------------------------------------------------------------


@pytest.fixture
def ranking_copy(g3):
    track, t, results, registry, cache = g3
    source = REAL_REGISTRY / RANKING_D18[0] / RANKING_D18[1]
    if not source.exists():
        pytest.skip("the real ranking_xgb_v2 d18 artifact is not on this machine")
    shutil.copytree(source, registry / RANKING_D18[0] / RANKING_D18[1])
    from ml.registry import model_file_sha256
    pins = json.loads((results / t.pins_record).read_text(encoding="utf-8"))
    pins["models"]["/".join(RANKING_D18)] = model_file_sha256(registry, *RANKING_D18)
    (results / t.pins_record).write_text(json.dumps(pins), encoding="utf-8")
    return g3


def test_the_pinned_ranking_model_loads(ranking_copy):
    track, t, results, registry, cache = ranking_copy
    assert track._ranking_model(t) is not None


def test_an_altered_ranking_model_is_refused(ranking_copy, capsys):
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = ranking_copy
    path = registry / RANKING_D18[0] / RANKING_D18[1] / "model.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(Blocked):
        track._ranking_model(t)
    assert "ranking_xgb_v2/d18" in capsys.readouterr().err


def test_a_missing_ranking_pin_or_file_is_refused(ranking_copy):
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = ranking_copy
    pins = json.loads((results / t.pins_record).read_text(encoding="utf-8"))
    del pins["models"]["/".join(RANKING_D18)]
    (results / t.pins_record).write_text(json.dumps(pins), encoding="utf-8")
    with pytest.raises(Blocked):
        track._ranking_model(t)  # no pin: never loaded unpinned
    shutil.rmtree(registry / RANKING_D18[0])
    pins["models"]["/".join(RANKING_D18)] = "d" * 64
    (results / t.pins_record).write_text(json.dumps(pins), encoding="utf-8")
    with pytest.raises(Blocked):
        track._ranking_model(t)  # no file


def test_m8b_refuses_an_altered_ranking_model_before_reading_any_data(ranking_copy, tmp_path):
    from scripts.phase6_playoff_track import Blocked

    track, t, results, registry, cache = ranking_copy
    (results / t.px4_record).write_text(json.dumps({"passed": True}), encoding="utf-8")
    t8 = replace(t, m8_pre_run=tmp_path / "PRE.md", m8_pre_run_json=tmp_path / "pre.json")
    t8.m8_pre_run.write_text("synthetic", encoding="utf-8")
    t8.m8_pre_run_json.write_text(json.dumps({
        "seed": 1, "per_stratum": 1, "reason_categories": [{"code": "x"}], "mentor": "SYNTHETIC MENTOR",
        "mentor_agreement": {"confirmed": True, "date": "d", "evidence": "e"}}), encoding="utf-8")
    path = registry / RANKING_D18[0] / RANKING_D18[1] / "model.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(Blocked):
        track.run_m8(None, None, t8)  # database None: the refusal precedes any data access


# --- the v2 pin record --------------------------------------------------------------------------------------------


def test_the_chain_reads_v2_and_refuses_a_v1_record_in_its_place(tmp_path):
    from scripts import phase6_playoff_track as track

    assert track.PX1B_TRACK.pins_record == PIN_RECORD == "p6_px1b_chain_pins_v2.json" and PIN_VERSION == 2
    v1_shaped = tmp_path / "v.json"
    v1_shaped.write_text(json.dumps({"pin_version": 1, "models": {}, "slice_content": {}}), encoding="utf-8")
    with pytest.raises(PinError):
        read_pins(v1_shaped)


def test_pins_v2_refuses_a_v1_model_that_no_longer_matches(monkeypatch):
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 0)
    monkeypatch.setattr("ml.registry.model_file_sha256", lambda registry, model_type, tag: "0" * 64)
    if not (REAL_RESULTS / PIN_RECORD_V1).exists():
        pytest.skip("the v1 pin record is not present")
    with pytest.raises(Blocked):
        harness.run_pins_v2(None, None)


def test_the_real_v2_record_is_additive_when_present():
    from scripts.phase6_common import file_sha256

    v2_path = REAL_RESULTS / PIN_RECORD
    if not v2_path.exists():
        pytest.skip("the v2 pin record is not recorded yet")
    v1 = read_pins(REAL_RESULTS / PIN_RECORD_V1, version=1)
    v2 = read_pins(v2_path)
    assert v2["derived_from"]["sha256"] == file_sha256(REAL_RESULTS / PIN_RECORD_V1)
    assert {k: v for k, v in v2["models"].items() if k in v1["models"]} == v1["models"]
    assert set(v2["models"]) - set(v1["models"]) == {"/".join(RANKING_D18)}
    assert v2["slice_content"] == v1["slice_content"]
