"""P6-M10b `frame-2027` (§5): the 2027 D18 frame and its write-once record. SYNTHETIC fixtures in tmp directories;
no frame is built from real data, no 2027 data exists, and no database is touched."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.phase6_common as common
import scripts.phase6_m10b as runner
import scripts.phase6_px1b_final1 as final1
from ml.strategy.calibration import SPEC_BLOB
from scripts.phase6_common import file_sha256
from scripts.phase6_playoff_track import Blocked

COUNTS = {"matches_season_2027": 120, "events_2027": 3, "tba_payloads_2027": 500, "statbotics_payloads_2027": 90,
          "team_event_stats_2027": 90}


@pytest.fixture
def world(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    write(runner.PINS_RECORD, {"model_identity": {"base_sha256": "b" * 64, "calibrator_sha256": "c" * 64}})
    write(final1.EPA_RECORD, {"snapshot": "snap", "chain": "chain.json"})
    auth = tmp_path / "frame_auth.json"
    auth.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                "scope": "P6-M10b-frame-2027", "season_complete_and_synced": True,
                                "seasons": [2027], "spec_blob": SPEC_BLOB,
                                "amendment_a1_blob": runner.A1_BLOB}), encoding="utf-8")
    monkeypatch.setattr(runner, "FRAME_AUTHORIZATION", auth)
    monkeypatch.setattr(final1, "adding_commit", lambda path: "713a13c")
    monkeypatch.setattr(final1, "verified_epa_source", lambda record: (Path("snap"), Path("chain.json")))
    monkeypatch.setattr(runner, "data_2027", lambda database: dict(COUNTS))
    return SimpleNamespace(results=results, write=write, auth=auth, mp=monkeypatch, tmp=tmp_path)


def test_all_frame_prerequisites_satisfied(world):
    provenance = runner.frame_prerequisites(None)
    assert provenance["pins"]["commit"] == "713a13c" and provenance["epa_source"]["snapshot"] == "snap"
    assert provenance["epa_source"]["sha256"] == file_sha256(world.results / final1.EPA_RECORD)
    assert provenance["amendment_a1"]["blob"] == runner.A1_BLOB and provenance["data_2027"] == COUNTS


def test_absent_frame_prerequisites_are_listed_together(world, capsys):
    (world.results / runner.PINS_RECORD).unlink()
    (world.results / final1.EPA_RECORD).unlink()
    world.auth.unlink()
    with pytest.raises(Blocked):
        runner.frame_prerequisites(None)
    err = capsys.readouterr().err
    assert "cannot be built yet" in err and runner.PINS_RECORD in err and final1.EPA_RECORD in err
    assert "authorization to build the 2027 frame" in err


@pytest.mark.parametrize("case, message", [
    ("exists", "recorded once"), ("pins_uncommitted", "must be committed"), ("seasons", "does not authorize"),
    ("scope", "does not authorize"), ("not_complete", "does not authorize"), ("a1", "does not authorize"),
    ("no_2027_matches", "nothing to build"), ("epa_unverified", "no longer matches")])
def test_frame_prerequisites_refuse(world, capsys, case, message):
    if case == "exists":
        world.write(runner.FRAME_RECORD, {})
    elif case == "pins_uncommitted":
        world.mp.setattr(final1, "adding_commit", lambda path: None)
    elif case in ("seasons", "scope", "not_complete", "a1"):
        value = json.loads(world.auth.read_text(encoding="utf-8"))
        value.update({"seasons": {"seasons": [2024, 2025, 2026, 2027]}, "scope": {"scope": "P6-M10b"},
                      "not_complete": {"season_complete_and_synced": False},
                      "a1": {"amendment_a1_blob": "0" * 40}}[case])
        world.auth.write_text(json.dumps(value), encoding="utf-8")
    elif case == "no_2027_matches":
        world.mp.setattr(runner, "data_2027", lambda database: {**COUNTS, "matches_season_2027": 0})
    elif case == "epa_unverified":
        def unverified(record):
            raise Blocked("2027 EPA source: the snapshot manifest no longer matches its pin")
        world.mp.setattr(final1, "verified_epa_source", unverified)
    with pytest.raises(Blocked):
        runner.frame_prerequisites(None)
    assert message in capsys.readouterr().err


def test_the_frame_is_built_by_the_frozen_procedure_over_the_pinned_source(world, monkeypatch):
    import ml.ratings.d18_source as d18
    import scripts.run_phase4_stratai as p4

    calls = {}

    def fake_provider(database, snapshot, chain):
        calls["source"] = (snapshot, chain)
        return "PROVIDER", {"verified": True}

    def fake_persist(database, provider, out, extra_info=None, seasons=None):
        calls["persist"] = (provider, out, seasons)
        return world.tmp / "frame_abc"
    monkeypatch.setattr(d18, "load_d18_provider", fake_provider)
    monkeypatch.setattr(p4, "persist_frame", fake_persist)
    monkeypatch.setattr(p4, "frame_info", lambda d: {"manifest": {"content_hash": "h" * 64, "season_keys": [2027],
                                                                  "row_count": 3000, "excluded_by_reason": {"x": 1}}})
    record = runner.run_frame_2027(None)
    assert calls["source"] == (Path("snap"), Path("chain.json"))
    assert calls["persist"] == ("PROVIDER", runner.FRAME_OUT, [2027])
    assert record["content_hash"] == "h" * 64 and record["seasons"] == [2027] and record["acceptance"] is False
    assert record["epa_source"]["sha256"] == file_sha256(world.results / final1.EPA_RECORD)
    assert record["pins"]["commit"] == "713a13c" and record["epa_integrity"] == {"verified": True}
    monkeypatch.setattr(p4, "frame_info", lambda d: {"manifest": {"content_hash": "h" * 64,
                                                                  "season_keys": [2026, 2027], "row_count": 1,
                                                                  "excluded_by_reason": {}}})
    with pytest.raises(Blocked):
        runner.run_frame_2027(None)


def test_persist_frame_default_seasons_are_unchanged(monkeypatch, tmp_path):
    import ml.dataset.builder as builder
    import scripts.run_phase4_stratai as p4

    seen = []

    class Stop(Exception):
        pass

    def capture(database, seasons, epa_provider):
        seen.append(list(seasons))
        raise Stop
    monkeypatch.setattr(builder, "build_training_frame", capture)
    for kwargs in ({}, {"seasons": [2027]}):
        with pytest.raises(Stop):
            p4.persist_frame(None, None, tmp_path, **kwargs)
    assert seen == [[2024, 2025, 2026], [2027]]


def test_the_real_frame_build_is_blocked_today():
    assert not runner.FRAME_AUTHORIZATION.exists()
    with pytest.raises(Blocked):
        runner.frame_prerequisites(None)
