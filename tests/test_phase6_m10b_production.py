"""P6-M10b production calibrator fit and pins (`scripts/phase6_m10b.py calibrate` / `pins`; frozen spec §3, A1).

SYNTHETIC calibration data, a tmp registry and tmp records test the runner's logic only. Nothing here fits or
registers the production calibrator, reads 2027 data, or touches any database.
"""

from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.special import expit

import scripts.phase6_common as common
import scripts.phase6_m10b as runner
import scripts.phase6_px1b_final1 as final1
from ml.registry import model_file_sha256
from ml.strategy.calibration import GROUPS, SPEC_BLOB
from ml.strategy.outcome import ComponentOutcomeModel
from scripts.phase6_playoff_track import Blocked
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA

EPA = {"epa_source": "d18_statbotics_primary", "frame_content_hash": "h" * 64, "snapshot": "SYNTHETIC"}
COUNTS = {"same": 900, "mixed": 700, "prior": 400}
EXCLUDED = {"model_input_absent": 3, "tie": 5}
ZERO_2027 = {name: 0 for name in runner.DATA_2027_SQL}


def _calibration_set():
    rng = np.random.default_rng(11)
    groups = [g for g, n in COUNTS.items() for _ in range(n)]
    factor = {"same": 1.3, "mixed": 1.05, "prior": 0.9}
    z = rng.normal(0, 1.5, len(groups))
    s = np.where(rng.random(len(groups)) < expit(np.array([factor[g] for g in groups]) * z), 1, -1)
    return {"groups": groups, "z": list(z), "s": list(s), "fingerprint": "f" * 64, "seasons": [2026],
            "latest": "2026-07-08T07:30:00-04:00", "excluded": dict(EXCLUDED), "match_keys": []}


def _dev_record():
    passing = {"i_fit": "pass", "ii_g2_rejections": "pass", "iii_ece": "pass"}
    return {"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB},
            "decision": {"proceed": True, "statuses": passing},
            "base": {"sha256": "d" * 64}, "calibrator": {"sha256": "e" * 64},
            "evaluation": {"raw": {"gate": {"g2": {"rejected_bins": 3}}, "status": {"overall": "fail"}},
                           "calibrated": {"gate": {"g2": {"rejected_bins": 2}}, "status": {"overall": "fail"}}}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    results, registry = tmp_path / "results", tmp_path / "registry"
    results.mkdir()
    base_dir = registry / "strategy_outcome_component" / "p6m10-v1"
    base_dir.mkdir(parents=True)
    (base_dir / "model.json").write_text("SYNTHETIC v1 base", encoding="utf-8")
    base_sha = model_file_sha256(registry, "strategy_outcome_component", "p6m10-v1")
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    monkeypatch.setattr(common, "REGISTRY_DIR", registry)

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    write(runner.DEV_RECORD, _dev_record())
    fit = {"registry": {"model_sha256": base_sha}, "frame_content_hash": "h" * 64}
    write("p6_m10_fit.json", fit)
    write("p6_m10_outcome_model.json", {"population": {"evaluated": sum(COUNTS.values()), "excluded": EXCLUDED}})
    base = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={"seasons": [2024, 2025]}, spec_sha256="0" * 64,
                                 artifact_sha256=base_sha)
    monkeypatch.setattr(runner, "_base", lambda: (base, fit))
    monkeypatch.setattr(runner, "data_2027", lambda database: dict(ZERO_2027))
    monkeypatch.setattr(runner, "season_resolver", lambda database: {}.get)
    monkeypatch.setattr(runner, "_epa_source_identity", lambda: dict(EPA))
    monkeypatch.setattr(runner, "calibration_set", lambda rows, base, season_of: _calibration_set())
    monkeypatch.setattr(runner, "SPEC_GROUP_COUNTS_2026", dict(COUNTS))
    monkeypatch.setattr(common, "load_frame", lambda: ([], "h" * 64))
    monkeypatch.setattr(final1, "adding_commit", lambda path: "c0ffee")
    import scripts.phase5_records as records
    monkeypatch.setattr(records, "provenance", lambda: {"commit": "SYNTHETIC"})
    return SimpleNamespace(results=results, registry=registry, write=write, base_sha=base_sha, mp=monkeypatch)


def _calibrate_and_record(world):
    record = runner.run_calibrate(None)
    world.write(runner.CALIBRATOR_RECORD, record)
    return record


def test_calibrate_fits_registers_and_records_every_identity(world):
    record = _calibrate_and_record(world)
    assert record["refused"] is False and record["spec"]["blob"] == SPEC_BLOB
    assert record["amendment_a1"]["blob"] == runner.A1_BLOB == "a453eaba397d8108a8cf967c27da554021921e5f"
    assert record["base"]["sha256"] == world.base_sha == record["base_sha256"]
    assert record["registry"]["artifact_sha256"] == model_file_sha256(world.registry, "strategy_outcome_calibrator",
                                                                      "p6m10b-v1")
    assert record["registry"]["artifact_sha256"] != record["dev_context"]["dev_calibrator_sha256"]
    assert record["rows"] == 2000 and record["groups"] == COUNTS and record["calibration_set"]["excluded"] == EXCLUDED
    assert record["epa_source"] == EPA and record["no_2027_data"] == ZERO_2027 and record["acceptance"] is False
    assert set(record["sources"].values()) == {"group"} and set(record["factors"]) == set(GROUPS)
    dev = record["dev_context"]
    assert dev["raw_overall"] == dev["calibrated_overall"] == "fail"
    assert "both raw and calibrated DEV predictions failed the overall G2 gate" in dev["statement"]


def test_pins_verify_every_identity_and_record_the_calibrators_commit(world):
    calibrator = _calibrate_and_record(world)
    pins = runner.run_pins(None)
    assert pins["model_identity"] == {"base_sha256": world.base_sha,
                                      "calibrator_sha256": calibrator["registry"]["artifact_sha256"]}
    assert pins["calibrator_record"]["commit"] == "c0ffee" and len(pins["calibrator_record"]["sha256"]) == 64
    assert pins["amendment_a1"]["blob"] == runner.A1_BLOB and pins["spec"]["blob"] == SPEC_BLOB
    assert pins["epa_source"] == EPA and pins["no_2027_data"] == ZERO_2027 and pins["acceptance"] is False
    assert pins["dev_context"] == calibrator["dev_context"]


@pytest.mark.parametrize("case, message", [
    ("calibrator_exists", "fit once"), ("dev_not_proceeded", "did not proceed"),
    ("dev_unevaluable", "did not proceed"), ("data_2027", "2027 data exists"), ("dev_base", "never the DEV base"),
    ("frame", "not the one the base was fit"), ("rows", "not §3's population"), ("excluded", "not §3's population"),
    ("groups", "not §3's population"), ("spec", "not the frozen P6-M10b blob"), ("a1", "amendment A1"),
    ("dirty_tree", "uncommitted tracked changes")])
def test_calibrate_refuses(world, capsys, case, message):
    if case == "calibrator_exists":
        world.write(runner.CALIBRATOR_RECORD, {"refused": False})
    elif case == "dev_not_proceeded":
        world.write(runner.DEV_RECORD, {**_dev_record(), "decision": {"proceed": False}})
    elif case == "dev_unevaluable":
        dev = _dev_record()
        dev["decision"]["statuses"]["iii_ece"] = "unevaluable"
        world.write(runner.DEV_RECORD, dev)
    elif case == "data_2027":
        world.mp.setattr(runner, "data_2027", lambda database: {**ZERO_2027, "tba_payloads_2027": 1})
    elif case == "dev_base":
        dev = _dev_record()
        dev["base"]["sha256"] = world.base_sha
        world.write(runner.DEV_RECORD, dev)
    elif case == "frame":
        world.mp.setattr(common, "load_frame", lambda: ([], "0" * 64))
    elif case == "rows":
        world.write("p6_m10_outcome_model.json", {"population": {"evaluated": 12215, "excluded": EXCLUDED}})
    elif case == "excluded":
        world.write("p6_m10_outcome_model.json", {"population": {"evaluated": 2000, "excluded": {"tie": 5}}})
    elif case == "groups":
        world.mp.setattr(runner, "SPEC_GROUP_COUNTS_2026", {"same": 5439, "mixed": 4132, "prior": 2644})
    elif case == "spec":
        world.mp.setattr(runner, "git_blob", lambda path: "0" * 40)
    elif case == "a1":
        world.mp.setattr(runner, "A1_BLOB", "0" * 40)
    elif case == "dirty_tree":
        import scripts.phase5_records as records

        def dirty():
            raise records.RecordError("refusing to record a result with uncommitted tracked changes: ['x.py']")
        world.mp.setattr(records, "provenance", dirty)
    with pytest.raises(Blocked):
        runner.run_calibrate(None)
    assert message in capsys.readouterr().err
    assert not (world.registry / "strategy_outcome_calibrator").exists()  # nothing registered


def test_a_refused_fit_is_recorded_registers_nothing_and_stops_the_pins(world, capsys):
    rng = np.random.default_rng(3)
    z = rng.normal(0, 1.5, 2000)
    s = np.where(rng.random(2000) < expit(20.0 * z), 1, -1)  # optimum beyond the upper bound
    world.mp.setattr(runner, "calibration_set", lambda rows, base, season_of: {
        **_calibration_set(), "z": list(z), "s": list(s)})
    record = _calibrate_and_record(world)
    assert record["refused"] is True and record["check"] == "solution_at_bound" and "registry" not in record
    assert not (world.registry / "strategy_outcome_calibrator").exists()
    with pytest.raises(Blocked):
        runner.run_pins(None)
    assert "refused fit" in capsys.readouterr().err


@pytest.mark.parametrize("case, message", [
    ("pins_exist", "taken once"), ("no_calibrator", "is required"), ("data_2027", "2027 data exists"),
    ("uncommitted", "must be committed"), ("artifact", "not the artifact its fit record names"),
    ("epa", "EPA source"), ("base_not_v1", "not v1"), ("record_spec", "frozen spec and amendment A1"),
    ("record_a1", "frozen spec and amendment A1")])
def test_pins_refuse(world, capsys, case, message):
    calibrator = _calibrate_and_record(world)
    if case == "pins_exist":
        world.write(runner.PINS_RECORD, {})
    elif case == "no_calibrator":
        (world.results / runner.CALIBRATOR_RECORD).unlink()
    elif case == "data_2027":
        world.mp.setattr(runner, "data_2027", lambda database: {**ZERO_2027, "matches_season_2027": 4})
    elif case == "uncommitted":
        world.mp.setattr(final1, "adding_commit", lambda path: None)
    elif case == "artifact":
        (world.registry / "strategy_outcome_calibrator/p6m10b-v1/model.json").write_text("{}", encoding="utf-8")
    elif case == "epa":
        world.mp.setattr(runner, "_epa_source_identity", lambda: {**EPA, "snapshot": "other"})
    elif case == "base_not_v1":
        world.write("p6_m10_fit.json", {"registry": {"model_sha256": "0" * 64}, "frame_content_hash": "h" * 64})
    elif case in ("record_spec", "record_a1"):
        key = "spec" if case == "record_spec" else "amendment_a1"
        world.write(runner.CALIBRATOR_RECORD, {**calibrator, key: {"blob": "0" * 40}})
    with pytest.raises(Blocked):
        runner.run_pins(None)
    assert message in capsys.readouterr().err


def test_data_2027_counts_every_category_read_only():
    class Cursor:
        def __init__(self):
            self.sql = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            self.sql.append(sql)

        def fetchone(self):
            return (0,)
    cursor = Cursor()
    counts = runner.data_2027(SimpleNamespace(cursor=lambda: cursor))
    assert counts == ZERO_2027 and set(counts) == {"matches_season_2027", "events_2027", "tba_payloads_2027",
                                                   "statbotics_payloads_2027", "team_event_stats_2027"}
    assert all(sql.lstrip().upper().startswith("SELECT COUNT(*)") for sql in cursor.sql)


def test_the_spec_group_counts_are_the_frozen_ones():
    assert runner.SPEC_GROUP_COUNTS_2026 == {"same": 5439, "mixed": 4132, "prior": 2644}
    assert sum(runner.SPEC_GROUP_COUNTS_2026.values()) == 12215
    assert Counter(runner.SPEC_GROUP_COUNTS_2026).total() == 12215
