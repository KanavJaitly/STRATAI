"""G1/G2 integrity pins for the PX-1b chain (approved by Kanav 2026-10-08): `ml/playoffs/pins.py` and its use in the
harness. SYNTHETIC unless marked. The real-artifact tests read the registry and the pin record (no database, no
evaluation, no 2027 data) and skip when either is absent."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ml.playoffs.pins import (PIN_VERSION, SERIALIZATION_NAME, PinError, read_pins, require_model_pin,
                              require_slice_content, serialization_signature, slice_content_fingerprint)
from ml.playoffs.px1 import PlayoffLogisticModel
from ml.playoffs.px2b import calibration_slice
from tests.test_phase6_px2b_v2 import _world, write_synthetic_pins

REGISTRY = Path("C:/Dev/StratAI-artifacts/ml_registry")
RESULTS = Path(".agent/phase6/results")


def _slice():
    return calibration_slice(_world())


def _pins(slice_rows, models=None):
    return {"pin_version": PIN_VERSION, "models": models or {},
            "slice_content": {"rows": len(slice_rows), "fingerprint": slice_content_fingerprint(slice_rows),
                              "serialization": {"name": SERIALIZATION_NAME,
                                                "signature_sha256": serialization_signature()}}}


# --- G2: slice content and serialization -------------------------------------------------------------------------


def test_the_slice_fingerprint_is_reproducible_and_order_free():
    slice_rows = _slice()
    assert slice_content_fingerprint(slice_rows) == slice_content_fingerprint(list(reversed(slice_rows)))
    assert serialization_signature() == serialization_signature()
    require_slice_content(_pins(slice_rows), slice_rows)


def test_changed_feature_content_with_unchanged_keys_is_refused():
    slice_rows = _slice()
    pins = _pins(slice_rows)
    row = slice_rows[7]
    altered_team = row.red_teams[0].model_copy(update={"epa_total": (row.red_teams[0].epa_total or 0) + 1.0})
    altered = list(slice_rows)
    altered[7] = replace(row, red_teams=(altered_team, *row.red_teams[1:]))
    assert [r.match_key for r in altered] == [r.match_key for r in slice_rows]  # the keys are identical
    with pytest.raises(PinError, match="content changed"):
        require_slice_content(pins, altered)
    relabelled = list(slice_rows)
    relabelled[3] = replace(slice_rows[3], red_win=not slice_rows[3].red_win)  # an outcome changed
    with pytest.raises(PinError):
        require_slice_content(pins, relabelled)
    with pytest.raises(PinError):
        require_slice_content(pins, slice_rows[:-1])


def test_a_different_serialization_is_refused_as_ambiguous(monkeypatch):
    import ml.playoffs.pins as pins_module

    slice_rows = _slice()
    pins = _pins(slice_rows)
    monkeypatch.setattr(pins_module, "serialization_signature", lambda: "0" * 64)
    with pytest.raises(PinError, match="serialization"):
        require_slice_content(pins, slice_rows)
    renamed = json.loads(json.dumps(pins))
    renamed["slice_content"]["serialization"]["name"] = "something-else"
    monkeypatch.undo()
    with pytest.raises(PinError, match="serialization"):
        require_slice_content(renamed, slice_rows)


# --- G1: model files -------------------------------------------------------------------------------------------


def test_model_pins_refuse_missing_pins_missing_files_and_mismatches():
    pins = {"models": {"m/t": "a" * 64}}
    require_model_pin(pins, "m", "t", "a" * 64)
    with pytest.raises(PinError, match="no pin"):
        require_model_pin(pins, "other", "t", "a" * 64)
    with pytest.raises(PinError, match="missing"):
        require_model_pin(pins, "m", "t", None)
    with pytest.raises(PinError, match="not the pinned"):
        require_model_pin(pins, "m", "t", "b" * 64)


def test_a_missing_or_foreign_pin_record_is_refused(tmp_path):
    with pytest.raises(PinError):
        read_pins(tmp_path / "absent.json")
    (tmp_path / "old.json").write_text(json.dumps({"pin_version": 0, "models": {}, "slice_content": {}}), "utf-8")
    with pytest.raises(PinError):
        read_pins(tmp_path / "old.json")


@pytest.fixture
def pinned_world(tmp_path, monkeypatch):
    """SYNTHETIC registry (px1b-v1, its seed-only comparator) and pin record in tmp dirs."""
    import scripts.phase6_common as common
    from scripts import phase6_playoff_track as track

    results, registry = tmp_path / "results", tmp_path / "registry"
    results.mkdir()
    for module in (common, track):
        monkeypatch.setattr(module, "RESULTS_DIR", results)
    monkeypatch.setattr(track, "REGISTRY_DIR", registry)
    rows = _world()
    for model_type, seed_only in (("playoff_px1b", False), ("playoff_px1b_seed_only", True)):
        (registry / model_type / "px1b-v1").mkdir(parents=True)
        PlayoffLogisticModel.fit(rows, seed_only=seed_only, normalized=not seed_only,
                                 model_type=model_type).save(registry / model_type / "px1b-v1" / "model.json")
    write_synthetic_pins(results / track.PX1B_TRACK.pins_record, registry,
                         [("playoff_px1b", "px1b-v1"), ("playoff_px1b_seed_only", "px1b-v1")], calibration_slice(rows))
    return track, results, registry, rows


def test_the_exact_pinned_artifacts_load(pinned_world):
    track, results, registry, rows = pinned_world
    px1b, seed_only = track._models(track.PX1B_TRACK)
    assert px1b.design.normalized and seed_only.design.names() == ["seed_difference"]
    assert px1b.predict(rows[0]) is not None


def test_an_altered_model_file_is_refused_never_loaded(pinned_world):
    from scripts.phase6_playoff_track import Blocked

    track, results, registry, _ = pinned_world
    path = registry / "playoff_px1b" / "px1b-v1" / "model.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["coef"][0] += 1e-9  # a one-coefficient edit
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Blocked):
        track._models(track.PX1B_TRACK)


def test_a_missing_model_file_or_pin_record_is_refused_with_no_unpinned_fallback(pinned_world):
    from scripts.phase6_playoff_track import Blocked

    track, results, registry, _ = pinned_world
    (registry / "playoff_px1b_seed_only" / "px1b-v1" / "model.json").unlink()
    with pytest.raises(Blocked):
        track._models(track.PX1B_TRACK)
    (results / track.PX1B_TRACK.pins_record).unlink()
    with pytest.raises(Blocked):
        track._models(track.PX1B_TRACK)


def test_the_px1_chain_stays_unpinned():
    from scripts import phase6_playoff_track as track

    assert track.PX1_TRACK.pins_record is None and track.PX1B_TRACK.pins_record == "p6_px1b_chain_pins_v2.json"


# --- the PX-2b v2 and FINAL-1 paths use the pins ----------------------------------------------------------------


def test_px2b_v2_refuses_changed_slice_content_with_unchanged_keys(tmp_path, monkeypatch, capsys):
    from tests.test_phase6_px2b_v2 import _synthetic_track_world
    import ml.playoffs.px2b as px2b
    import scripts.phase6_common as common
    from scripts import phase6_playoff_track as track
    from scripts.phase6_common import file_sha256
    from scripts.phase6_playoff_track import Blocked

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
    rows27, slice_rows, _, _ = _synthetic_track_world(t, results, registry, monkeypatch)
    track.run_m3(None, None, t)  # the pinned content: runs (SYNTHETIC)
    changed = [replace(r, red_win=not r.red_win) if r.match_key == slice_rows[0].match_key else r
               for r in track._track_rows(None, None, t)]
    monkeypatch.setattr(track, "_track_rows", lambda database, rulesets, tr: changed)
    monkeypatch.setattr(px2b, "frozen_slice_keys", lambda path=None: [r.match_key for r in slice_rows])
    with pytest.raises(Blocked):
        track.run_m3(None, None, t)
    assert "content changed" in capsys.readouterr().err


def test_final1_lists_the_pin_record_and_refuses_an_altered_model(pinned_world, monkeypatch, capsys):
    import data.rulesets
    import scripts.phase6_px1b as harness
    from scripts.phase6_playoff_track import Blocked

    track, results, registry, _ = pinned_world
    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 0)
    monkeypatch.setattr(data.rulesets, "approved_seasons", lambda database: [2024, 2025, 2026])
    with pytest.raises(Blocked):
        harness.run_gate2027(None, None)  # pins verified; still blocked by the missing prerequisites
    assert "integrity pins" not in capsys.readouterr().err
    path = registry / "playoff_px1b" / "px1b-v1" / "model.json"
    path.write_text(path.read_text(encoding="utf-8").replace("1", "2", 1), encoding="utf-8")
    with pytest.raises(Blocked):
        harness.run_gate2027(None, None)
    assert "not the pinned" in capsys.readouterr().err
    (results / track.PX1B_TRACK.pins_record).unlink()
    with pytest.raises(Blocked):
        harness.run_gate2027(None, None)
    assert "integrity pins" in capsys.readouterr().err


# --- the real pins (v1 after `phase6_px1b pins`; v2 after `phase6_px1b pins-v2`) -----------------------------------


@pytest.fixture
def real_pins():
    """The v1 record (G1/G2), kept unchanged as history."""
    path = RESULTS / "p6_px1b_chain_pins.json"
    if not path.exists() or not REGISTRY.exists():
        pytest.skip("the real pin record or registry is not present")
    return read_pins(path, version=1)


def test_the_real_v1_pins_still_match_their_files(real_pins):
    from ml.registry import model_file_sha256

    for key, sha in real_pins["models"].items():
        model_type, tag = key.split("/")
        assert model_file_sha256(REGISTRY, model_type, tag) == sha
    assert real_pins["slice_content"]["serialization"]["signature_sha256"] == serialization_signature()


def test_the_real_pinned_artifacts_load_through_the_v2_record():
    from scripts import phase6_playoff_track as track

    if not (RESULTS / track.PX1B_TRACK.pins_record).exists() or not REGISTRY.exists():
        pytest.skip("the real v2 pin record or registry is not present")
    px1b, seed_only = track._models(track.PX1B_TRACK)  # loads only through the G1 check, against v2
    assert px1b.model_type == "playoff_px1b" and seed_only.model_type == "playoff_px1b_seed_only"


def test_the_real_slice_content_matches_its_pin(real_pins):
    import gzip
    import pickle

    from ml.playoffs.px1b import drop_scale_absent

    cache = Path("C:/Dev/StratAI-artifacts/phase6/px_rows_px1-v2.pkl.gz")
    if not cache.exists():
        pytest.skip("the PX-1b rows cache is not present")
    rows = drop_scale_absent(pickle.loads(gzip.decompress(cache.read_bytes())))[0]
    require_slice_content(real_pins, calibration_slice(rows))
