"""FINAL-1 (PX-1b's 2027 acceptance evaluation; `scripts/phase6_px1b_final1.py`): software verification only.

SYNTHETIC fixtures in tmp directories test the logic. They are not acceptance evidence. No acceptance record is
written anywhere, no model is registered, and no database is touched.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.rulesets import SeasonRuleset
from scripts.phase6_playoff_track import Blocked
from tests.phase6_bracket_fixtures import ruleset
from tests.test_phase6_px1 import synthetic_rows

FP = "f" * 64
T2027 = datetime(2027, 3, 6, 12, tzinfo=timezone.utc)
REAL_RESULTS = Path(".agent/phase6/results")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Every FINAL-1 prerequisite satisfied with SYNTHETIC stand-ins in tmp dirs."""
    import data.rulesets
    import scripts.phase6_common as common
    import scripts.phase6_px1b as harness
    import scripts.phase6_px1b_final1 as final1
    from ml.playoffs.pins import PIN_RECORD
    from ml.playoffs.px1 import PlayoffLogisticModel
    from ml.playoffs.px2b import calibration_slice
    from scripts import phase6_playoff_track as track
    from scripts.phase6_common import file_sha256, git_blob
    from tests.test_phase6_px2b_v2 import _world, write_synthetic_pins

    results, registry, decisions = tmp_path / "results", tmp_path / "registry", tmp_path / "decisions"
    for d in (results, decisions):
        d.mkdir()
    for module in (common, track):
        monkeypatch.setattr(module, "RESULTS_DIR", results)
    monkeypatch.setattr(track, "REGISTRY_DIR", registry)
    monkeypatch.setattr(final1, "D9_CONFIRMATION", decisions / "p6_d9_v1_confirmation.json")
    monkeypatch.setattr(final1, "AUTHORIZATION", decisions / "p6_px1b_final1_authorization.json")
    rows = _world()
    for model_type, seed_only in (("playoff_px1b", False), ("playoff_px1b_seed_only", True)):
        d = registry / model_type / "px1b-v1"
        d.mkdir(parents=True)
        PlayoffLogisticModel.fit(rows, seed_only=seed_only, normalized=not seed_only,
                                 model_type=model_type).save(d / "model.json")
        (d / "manifest.json").write_text(json.dumps({"training_dataset_hash": FP,
                                                     "created_at": "2026-10-09T01:08:51.645865Z"}), "utf-8")
    write_synthetic_pins(results / PIN_RECORD, registry,
                         [("playoff_px1b", "px1b-v1"), ("playoff_px1b_seed_only", "px1b-v1")], calibration_slice(rows))
    pins = json.loads((results / PIN_RECORD).read_text(encoding="utf-8"))
    pins["population_fingerprint"] = FP
    (results / PIN_RECORD).write_text(json.dumps(pins), encoding="utf-8")

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    write(final1.FINAL_RECORD, {"dataset_fingerprint": FP, "rows": {"by_season": {"2024": 1, "2025": 1, "2026": 1}}})
    write(final1.DEV_RECORD, {"decision": {"proceed_to_final": True}})
    rules = SeasonRuleset.model_validate(ruleset(2027))
    write(final1.M1_2027_RECORD, {"escalate": False, "events": {},
                                  "seasons": {"2027": {"escalate": False, "ruleset_sha256": rules.sha256()}}})
    snapshot, chain = tmp_path / "snapshot", tmp_path / "chain.json"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(json.dumps({"seasons": [2026, 2027]}), encoding="utf-8")
    chain.write_text("{}", encoding="utf-8")
    write(final1.EPA_RECORD, {"snapshot": str(snapshot), "chain": str(chain),
                              "manifest_sha256": file_sha256(snapshot / "manifest.json"),
                              "chain_sha256": file_sha256(chain)})
    final1.D9_CONFIRMATION.write_text(json.dumps({"confirmed": True, "confirmed_by": "SYNTHETIC", "date": "2099-01-01",
                                                  "record": final1.D9_RECORD,
                                                  "record_blob": git_blob(final1.D9_RECORD)}), encoding="utf-8")
    final1.AUTHORIZATION.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                                "scope": "FINAL-1", "season": 2027,
                                                "season_complete_and_synced": True}), encoding="utf-8")
    monkeypatch.setattr(data.rulesets, "approved_seasons", lambda database: [2024, 2025, 2026, 2027])
    monkeypatch.setattr(data.rulesets, "approved_ruleset", lambda database, season: rules)
    monkeypatch.setattr(harness, "_playoff_matches", lambda database, season: 12)
    monkeypatch.setattr(common, "load_m6m7", lambda: "M6M7")
    return {"final1": final1, "results": results, "registry": registry, "snapshot": snapshot, "chain": chain,
            "write": write, "rows": rows, "monkeypatch": monkeypatch}


def _refused(final1, capsys) -> str:
    with pytest.raises(Blocked):
        final1.prerequisites(None, None)
    return capsys.readouterr().err


def test_all_prerequisites_satisfied_yields_the_verified_provenance(world):
    provenance = world["final1"].prerequisites(None, None)
    assert {"spec", "d9_record", "p6_d9_v1_confirmation", "p6_px1b_final1_authorization", "candidate", "pins",
            "m6m7_sha256", "ruleset_2027_sha256", "m1_2027", "epa_source"} <= set(provenance)
    assert set(provenance["pins"]["models"]) == {"playoff_px1b/px1b-v1", "playoff_px1b_seed_only/px1b-v1"}


# --- each absent prerequisite is refused, and named -------------------------------------------------------------


@pytest.mark.parametrize("knockout, named", [
    ("d9", "D9 decision v1"), ("authorization", "authorization to run FINAL-1"),
    ("final", "p6_px1b_final_fit.json"), ("dev", "DV1 and DV2"), ("pins", "integrity pins"),
    ("ruleset", "2027 P6-M1 ruleset"), ("m1", "reproduction check for 2027"), ("data", "2027 playoff data"),
    ("epa", "pinned D18 EPA source covering 2027")])
def test_each_missing_prerequisite_is_refused(world, capsys, knockout, named):
    import data.rulesets
    import scripts.phase6_px1b as harness
    from ml.playoffs.pins import PIN_RECORD

    final1, results, mp = world["final1"], world["results"], world["monkeypatch"]
    if knockout == "d9":
        final1.D9_CONFIRMATION.unlink()
    elif knockout == "authorization":
        final1.AUTHORIZATION.unlink()
    elif knockout == "ruleset":
        mp.setattr(data.rulesets, "approved_seasons", lambda database: [2024, 2025, 2026])
    elif knockout == "data":
        mp.setattr(harness, "_playoff_matches", lambda database, season: 0)
    else:
        name = {"final": final1.FINAL_RECORD, "dev": final1.DEV_RECORD, "pins": PIN_RECORD,
                "m1": final1.M1_2027_RECORD, "epa": final1.EPA_RECORD}[knockout]
        (results / name).unlink()
    err = _refused(final1, capsys)
    assert "cannot be evaluated yet" in err and named in err


# --- each inconsistent prerequisite is refused at once ------------------------------------------------------------


def _edit(path: Path, **changes):
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("case", ["d9_blob", "d9_unconfirmed", "auth_season", "auth_not_synced", "auth_scope",
                                  "final_has_2027", "m1_escalated", "m1_other_ruleset"])
def test_inconsistent_decisions_and_records_are_refused(world, capsys, case):
    final1, results = world["final1"], world["results"]
    if case == "d9_blob":
        _edit(final1.D9_CONFIRMATION, record_blob="0" * 40)
    elif case == "d9_unconfirmed":
        _edit(final1.D9_CONFIRMATION, confirmed=False)
    elif case == "auth_season":
        _edit(final1.AUTHORIZATION, season=2026)  # 2026 is never a substitute for 2027
    elif case == "auth_not_synced":
        _edit(final1.AUTHORIZATION, season_complete_and_synced=False)
    elif case == "auth_scope":
        _edit(final1.AUTHORIZATION, scope="PX-2b")
    elif case == "final_has_2027":
        _edit(results / final1.FINAL_RECORD, rows={"by_season": {"2026": 1, "2027": 1}})
    elif case == "m1_escalated":
        _edit(results / final1.M1_2027_RECORD, escalate=True)
    elif case == "m1_other_ruleset":
        _edit(results / final1.M1_2027_RECORD, seasons={"2027": {"escalate": False, "ruleset_sha256": "0" * 64}})
    err = _refused(final1, capsys)
    assert "cannot be evaluated yet" not in err  # refused for the inconsistency, not for absence


def test_an_altered_candidate_model_is_refused(world, capsys):
    path = world["registry"] / "playoff_px1b" / "px1b-v1" / "model.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["coef"][0] += 1e-9
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "not the pinned" in _refused(world["final1"], capsys)


def test_an_altered_seed_only_baseline_is_refused(world, capsys):
    path = world["registry"] / "playoff_px1b_seed_only" / "px1b-v1" / "model.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert "not the pinned" in _refused(world["final1"], capsys)


def test_a_training_fingerprint_mismatch_is_refused(world, capsys):
    manifest = world["registry"] / "playoff_px1b" / "px1b-v1" / "manifest.json"
    _edit(manifest, training_dataset_hash="0" * 64)
    assert "disagree" in _refused(world["final1"], capsys)


def test_an_m6m7_baseline_hash_mismatch_is_refused(world, capsys):
    import scripts.phase6_common as common

    def mismatched():
        raise ValueError("registered model has sha256 x, not the pinned y")
    world["monkeypatch"].setattr(common, "load_m6m7", mismatched)
    assert "M6/M7 d18 baseline does not match its pin" in _refused(world["final1"], capsys)


@pytest.mark.parametrize("case", ["chain_altered", "manifest_altered", "no_2027", "snapshot_missing"])
def test_an_inconsistent_epa_source_is_refused(world, capsys, case):
    if case == "chain_altered":
        world["chain"].write_text('{"x": 1}', encoding="utf-8")
    elif case == "manifest_altered":
        (world["snapshot"] / "manifest.json").write_text(json.dumps({"seasons": [2027], "x": 1}), encoding="utf-8")
    elif case == "no_2027":
        from scripts.phase6_common import file_sha256
        (world["snapshot"] / "manifest.json").write_text(json.dumps({"seasons": [2026]}), encoding="utf-8")
        _edit(world["results"] / world["final1"].EPA_RECORD,
              manifest_sha256=file_sha256(world["snapshot"] / "manifest.json"))
    else:
        (world["snapshot"] / "manifest.json").unlink()
    assert "2027 EPA source" in _refused(world["final1"], capsys)


def test_a_changed_px1b_spec_is_refused(world, capsys):
    final1 = world["final1"]
    real_blob = final1.git_blob
    world["monkeypatch"].setattr(final1, "git_blob", lambda p: "0" * 40 if p == final1.PX1B_SPEC else real_blob(p))
    assert "frozen PX-1b spec" in _refused(final1, capsys)


# --- run once; never overwritten -------------------------------------------------------------------------------


def test_an_existing_acceptance_record_refuses_a_rerun(world, capsys):
    final1 = world["final1"]
    world["write"](final1.GATE_RECORD, {"passed": False})
    assert "runs once" in _refused(final1, capsys)


def test_write_once_refuses_to_overwrite(tmp_path, monkeypatch):
    import scripts.phase5_records as records
    from scripts.phase5_records import RecordError, write_once

    monkeypatch.setattr(records, "provenance", lambda: {"commit": "SYNTHETIC"})  # tree state is not under test here
    write_once("x.json", {"a": 1}, results_dir=tmp_path)
    with pytest.raises(RecordError):
        write_once("x.json", {"a": 2}, results_dir=tmp_path)
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))["a"] == 1


# --- the frozen evaluation on identical rows ------------------------------------------------------------------


class _Stub:
    def __init__(self, values):
        self.values = values

    def predict(self, row):
        return self.values.get(row.match_key)


def _rows_2027(n=160):
    rows = synthetic_rows(n, 77)
    return [replace(r, season=2027, event_key=f"2027e{i // 8:02d}", match_key=f"2027e{i // 8:02d}_m{i % 8}",
                    scheduled_time=T2027 + timedelta(hours=i)) for i, r in enumerate(rows)]


def test_all_three_models_are_scored_on_identical_rows_with_the_frozen_bootstrap(world):
    rows = _rows_2027()
    good = _Stub({r.match_key: (0.85 if r.red_win else 0.15) for r in rows})
    coin = _Stub({r.match_key: 0.5 for r in rows})
    seen = []
    result = world["final1"].evaluate(rows, good, coin, lambda r: seen.append(r.match_key) or 0.5)
    assert seen == [r.match_key for r in rows]  # M6/M7 scored on exactly the rows PX-1b and seed-only were
    for comparison in ("vs_m6m7", "vs_seed_only"):
        assert result[comparison]["resamples"] == 2000 and result[comparison]["seed"] == 20261010
        assert result[comparison]["events"] == 20 and result[comparison]["units"] == 160
    assert result["bootstrap"] == {"resamples": 2000, "seed": 20261010}
    assert result["passed"] is True  # SYNTHETIC: logic only, not evidence


@pytest.mark.parametrize("m6m7, seed, passed", [(0.5, 0.5, True), ("same", 0.5, False), (0.5, "same", False),
                                                ("same", "same", False)])
def test_the_gate_needs_both_cis_entirely_below_zero(world, m6m7, seed, passed):
    rows = _rows_2027()
    values = {r.match_key: (0.8 if r.red_win else 0.2) for r in rows}
    px1b = _Stub(values)
    seed_model = _Stub(values if seed == "same" else {k: seed for k in values})
    m6m7_fn = (lambda r: values[r.match_key]) if m6m7 == "same" else (lambda r: m6m7)
    result = world["final1"].evaluate(rows, px1b, seed_model, m6m7_fn)
    assert result["passed"] is passed
    assert result["vs_m6m7"]["passed"] is (m6m7 != "same") and result["vs_seed_only"]["passed"] is (seed != "same")


def test_insufficient_rows_are_counted_and_excluded_from_every_model(world):
    rows = _rows_2027()
    values = {r.match_key: 0.6 for r in rows}
    values[rows[0].match_key] = None
    seen = []
    result = world["final1"].evaluate(rows, _Stub(values), _Stub({k: 0.5 for k in values}),
                                      lambda r: seen.append(r.match_key) or 0.5)
    assert result["insufficient_data"] == 1 and rows[0].match_key not in seen and len(seen) == 159


def test_the_candidate_must_be_registered_before_the_first_2027_selection_moment(world):
    final1 = world["final1"]
    provenance = {"candidate": {"registered_at": "2026-10-09T01:08:51Z"}}
    report = final1.require_candidate_frozen_first(provenance, {"e": "2027-03-06T10:00:00+00:00"})
    assert report["frozen_first"]
    with pytest.raises(Blocked):
        final1.require_candidate_frozen_first({"candidate": {"registered_at": "2027-03-07T00:00:00Z"}},
                                              {"e": "2027-03-06T10:00:00+00:00"})


def test_the_full_run_on_synthetic_data_returns_but_writes_nothing(world, monkeypatch):
    """run_gate2027 only returns its result; `main` alone writes the write-once record. SYNTHETIC end to end."""
    final1, results = world["final1"], world["results"]
    rows = _rows_2027()
    monkeypatch.setattr(final1, "assemble_2027", lambda database, rulesets, provenance: (
        rows, {}, {"epa_integrity": {}, "excluded_by_event": {}, "selection_moments": {"e": T2027.isoformat()}}))
    import scripts.phase6_playoff_track as track
    monkeypatch.setattr(track, "_m6m7_on", lambda r: 0.5)
    result = final1.run_gate2027(None, None)
    assert result["population"]["eligible_rows"] == 160 and isinstance(result["passed"], bool)
    assert "does NOT accept PX-1b" in result["acceptance_note"]
    assert not (results / final1.GATE_RECORD).exists() and not (REAL_RESULTS / final1.GATE_RECORD).exists()
