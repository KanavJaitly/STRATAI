"""PX-2b / PX-4b / M8b read the pinned 2027 D18 EPA source (Kanav, 2026-10-11): implementation only, fail-closed.
SYNTHETIC files in tmp directories; no evaluation runs and no database is touched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.phase6_common as common
import scripts.phase6_px1b_final1 as final1
from scripts.phase6_common import file_sha256
from scripts.phase6_playoff_track import CHAIN, PX1_TRACK, PX1B_TRACK, SNAPSHOT, Blocked, _epa_source


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A SYNTHETIC 2027 snapshot and chain, and a committed-looking pin record naming their sha256."""
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    snapshot = tmp_path / "statbotics_snapshot_2027"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(json.dumps({"seasons": [2024, 2025, 2026, 2027]}), encoding="utf-8")
    chain = tmp_path / "chain_2027.json"
    chain.write_text(json.dumps({"seasons": [2027]}), encoding="utf-8")
    record = {"milestone": "PX-1b 2027 EPA source pin", "acceptance": False, "snapshot": str(snapshot),
              "manifest_sha256": file_sha256(snapshot / "manifest.json"), "chain": str(chain),
              "chain_sha256": file_sha256(chain), "seasons": [2024, 2025, 2026, 2027]}

    def write(value):
        (results / PX1B_TRACK.epa_record).write_text(json.dumps(value), encoding="utf-8")
    write(record)
    monkeypatch.setattr(final1, "adding_commit", lambda path: "abc1234")
    return {"record": record, "write": write, "snapshot": snapshot, "chain": chain, "mp": monkeypatch}


def test_the_px1_track_is_unchanged():
    assert PX1_TRACK.epa_record is None and _epa_source(PX1_TRACK) == (SNAPSHOT, CHAIN)


def test_the_px1b_track_resolves_only_the_verified_pinned_record(pinned):
    assert PX1B_TRACK.epa_snapshot is None and PX1B_TRACK.epa_record == "p6_px1b_epa_source_2027.json"
    assert _epa_source(PX1B_TRACK) == (pinned["snapshot"], pinned["chain"])


def test_a_missing_record_is_refused(pinned, capsys):
    (common.RESULTS_DIR / PX1B_TRACK.epa_record).unlink()
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "has not been recorded" in capsys.readouterr().err


def test_an_uncommitted_record_is_refused(pinned, capsys):
    pinned["mp"].setattr(final1, "adding_commit", lambda path: None)
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "must be committed" in capsys.readouterr().err


@pytest.mark.parametrize("change", [{"milestone": "something else"}, {"seasons": [2024, 2025, 2026]}])
def test_a_record_that_is_not_the_2027_pin_is_refused(pinned, capsys, change):
    pinned["write"]({**pinned["record"], **change})
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "is not the pinned 2027 EPA source record" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["manifest", "chain"])
def test_a_changed_source_no_longer_matches_its_pin(pinned, capsys, target):
    path = pinned["snapshot"] / "manifest.json" if target == "manifest" else pinned["chain"]
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "no longer matches its pin" in capsys.readouterr().err


def test_a_mismatched_pin_in_the_record_is_refused(pinned, capsys):
    pinned["write"]({**pinned["record"], "chain_sha256": "0" * 64})
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "no longer matches its pin" in capsys.readouterr().err


def test_a_snapshot_that_does_not_cover_2027_is_refused(pinned, capsys):
    manifest = pinned["snapshot"] / "manifest.json"
    manifest.write_text(json.dumps({"seasons": [2024, 2025, 2026]}), encoding="utf-8")
    pinned["write"]({**pinned["record"], "manifest_sha256": file_sha256(manifest)})
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)
    assert "does not cover 2027" in capsys.readouterr().err


def test_the_pinned_source_is_absent_today_so_the_track_refuses():
    assert not (Path(".agent/phase6/results") / PX1B_TRACK.epa_record).exists()
    with pytest.raises(Blocked):
        _epa_source(PX1B_TRACK)


def test_px2b_rows_are_assembled_only_from_the_verified_2027_source(pinned, monkeypatch):
    """Audit (2026-10-11): the PX-1b consumers pass _epa_source's verified paths, so the shared assembler's 2026
    defaults (snapshot or SNAPSHOT) are never reached on the PX-1b track."""
    import ml.playoffs.px1b as px1b
    import scripts.phase6_playoff_track as track

    seen = {}

    def capture(database, rulesets, m1, **kw):
        seen.update(kw)
        return [], None, None, None, None, None
    monkeypatch.setattr(track, "assemble_rows", capture)
    monkeypatch.setattr(track, "_m1", lambda t: {"events": {}})
    monkeypatch.setattr(px1b, "drop_scale_absent", lambda rows: (rows, {}))
    track._track_rows(None, None, PX1B_TRACK)
    assert seen["snapshot"] == pinned["snapshot"] and seen["chain"] == pinned["chain"]
    assert seen["snapshot"] != SNAPSHOT and seen["seasons"] == (2026, 2027)


def test_every_px1b_consumer_takes_its_source_from_the_verified_path():
    import inspect

    import scripts.phase6_playoff_track as track

    for function in (track._track_rows, track.run_m5, track.run_m8):
        source = inspect.getsource(function)
        assert "_epa_source(track)" in source and "SNAPSHOT" not in source.replace("_epa_source", "")
