"""P6-M13 parity rerun for P6-M10b: runner and v2 planted-defect tests (plan `P6_M13_M10B_RERUN_PLAN.md`).

SYNTHETIC models and contexts in tmp directories test the audit logic only. The rerun is not run, no registered model
is loaded, and no database is touched.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.phase6_common as common
import scripts.phase6_m13_parity_audit_m10b as rerun
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN
from ml.strategy.calibration import GROUPS, SPEC_BLOB, CalibratedOutcomeModel, Calibrator
from ml.strategy.engine import StrategyEngine
from ml.strategy.outcome import VALIDATED, ComponentOutcomeModel, MatchContext
from ml.strategy.parity_audit import (PLANTED_DEFECTS, PLANTED_DEFECTS_V2, AuditContexts,
                                      planted_different_missing_data_handling, run_audit)
from scripts.phase6_common import git_blob
from scripts.phase6_playoff_track import Blocked
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

SEASON_OF = {"2099fixture": 2026}.get
IDENTITY = {"base_sha256": "b" * 64, "calibrator_sha256": "c" * 64}


def _v2(season_of=SEASON_OF, factors=None):
    base = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={"seasons": [2024, 2025]}, spec_sha256="0" * 64,
                                 artifact_sha256=IDENTITY["base_sha256"])
    calibrator = Calibrator(factors or {"same": 1.3, "mixed": 1.05, "prior": 0.95}, 1.1, {g: 1000 for g in GROUPS},
                            {g: "group" for g in GROUPS}, {}, base_sha256=IDENTITY["base_sha256"],
                            fit_set_fingerprint="f" * 64, artifact_sha256=IDENTITY["calibrator_sha256"])
    return CalibratedOutcomeModel(base, calibrator, season_of, baseline_status=(VALIDATED, None))


def _contexts():
    ordinary = [MatchContext(tuple(team(n, 6, 25, 4) for n in (1, 2, 3)), tuple(team(n, 5, 24, 6) for n in (4, 5, 6)),
                             prediction_season=2026)]
    missing = MatchContext((team(1, None, None, None, epa_scale=None), team(2), team(3)),
                           tuple(team(n) for n in (4, 5, 6)), prediction_season=2026)
    low = MatchContext(tuple(team(n, 1, 2, 0) for n in (1, 2, 3)), tuple(team(n, 9, 40, 9) for n in (4, 5, 6)),
                       prediction_season=2026)
    return AuditContexts(ordinary, missing, (low, "red"))


# --- the audit on v2: the real engine passes, every v2 defect is caught by its target -------------------------------


def test_the_v2_defects_mirror_the_v1_defects_one_for_one():
    assert list(PLANTED_DEFECTS_V2) == list(PLANTED_DEFECTS)
    assert {k: v[1] for k, v in PLANTED_DEFECTS_V2.items()} == {k: v[1] for k, v in PLANTED_DEFECTS.items()}


def test_the_real_v2_engine_passes_every_check():
    results = run_audit(StrategyEngine(_v2()), _contexts())
    assert len(results) == 10 and [r.name for r in results if not r.passed] == []


@pytest.mark.parametrize("name", list(PLANTED_DEFECTS_V2))
def test_each_v2_defect_is_caught_by_its_target_check(name):
    factory, target = PLANTED_DEFECTS_V2[name]
    failed = [r.name for r in run_audit(factory(_v2()), _contexts()) if not r.passed]
    assert target in failed


def test_the_v1_missing_data_defect_would_escape_on_v2():
    """Why the v2 form exists: the v1 defect imputes the source key "imputed", v2 refuses it (§2), so the AI path
    returns nothing too and M6 passes. The v2 form borrows a resolvable key and is caught."""
    contexts = _contexts()
    v1_form = [r.name for r in run_audit(planted_different_missing_data_handling(_v2()), contexts) if not r.passed]
    assert "M6_missing_data_parity" not in v1_form
    factory, target = PLANTED_DEFECTS_V2["different_missing_data_handling"]
    assert target in [r.name for r in run_audit(factory(_v2()), contexts) if not r.passed]


def test_the_v2_different_calibration_defect_changes_only_the_ai_paths_factor():
    from ml.strategy.parity_audit import planted_v2_different_calibration

    model = _v2()
    engine = planted_v2_different_calibration(model)
    assert engine.model is model and engine.ai_model.calibrator.factors["same"] == pytest.approx(1.3 * 1.25)
    assert model.calibrator.factors["same"] == 1.3  # the real model is untouched


# --- preflight ---------------------------------------------------------------------------------------------------


def test_the_preflight_passes_on_supporting_contexts():
    result = rerun.context_preflight(_v2(), _contexts(), SEASON_OF)
    assert result["imputed_source_key"] == "2099fixture" and result["imputed_source_resolves"]
    assert result["prediction_seasons"] == [2026]


@pytest.mark.parametrize("case", ["unresolvable_source", "no_prediction_season", "low_not_low", "missing_scored"])
def test_the_preflight_refuses_contexts_that_would_test_the_wrong_thing(case):
    contexts, model, season_of = _contexts(), _v2(), SEASON_OF
    if case == "unresolvable_source":
        season_of = {"2099fixture": None}.get
        model = _v2(season_of=season_of)
    elif case == "no_prediction_season":
        contexts.ordinary = [MatchContext(contexts.ordinary[0].red_teams, contexts.ordinary[0].blue_teams)]
    elif case == "low_not_low":
        contexts.low_odds = (contexts.ordinary[0], "red")
    elif case == "missing_scored":
        contexts.missing_input = contexts.ordinary[0]
    with pytest.raises(Blocked):
        rerun.context_preflight(model, contexts, season_of)


# --- prerequisites -----------------------------------------------------------------------------------------------


@pytest.fixture
def rerun_world(tmp_path, monkeypatch):
    from ml.registry import model_file_sha256

    results, registry = tmp_path / "results", tmp_path / "registry"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    monkeypatch.setattr(common, "REGISTRY_DIR", registry)
    for model_type, tag in (("strategy_outcome_component", "p6m10-v1"), ("strategy_outcome_calibrator", "p6m10b-v1")):
        (registry / model_type / tag).mkdir(parents=True)
        (registry / model_type / tag / "model.json").write_text(model_type, encoding="utf-8")
    identity = {"base_sha256": model_file_sha256(registry, "strategy_outcome_component", "p6m10-v1"),
                "calibrator_sha256": model_file_sha256(registry, "strategy_outcome_calibrator", "p6m10b-v1")}

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    write(rerun.V1_RECORD, {"plan_blob": git_blob(rerun.V1_PLAN), "frame_content_hash": "h" * 64})
    write("p6_m10b_outcome_model.json", {"passed": True, "model_identity": identity})
    write("p6_m10b_pins.json", {"model_identity": identity})
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                "scope": "P6-M13-M10b", "spec_blob": SPEC_BLOB,
                                "plan_blob": git_blob(rerun.RERUN_PLAN)}), encoding="utf-8")
    monkeypatch.setattr(rerun, "AUTHORIZATION", auth)
    return SimpleNamespace(results=results, registry=registry, write=write, auth=auth, identity=identity,
                           mp=monkeypatch)


def test_all_rerun_prerequisites_satisfied(rerun_world):
    provenance = rerun.rerun_prerequisites()
    assert provenance["model_identity"] == rerun_world.identity
    assert provenance["rerun_plan"]["blob"] == git_blob(rerun.RERUN_PLAN)
    assert provenance["v1_plan"]["blob"] == git_blob(rerun.V1_PLAN)


@pytest.mark.parametrize("case, message", [
    ("record_exists", "once only"), ("outcome_failed", "did not pass"), ("pins_differ", "not the pinned identity"),
    ("registry_differs", "not the model the P6-M10b run evaluated"), ("v1_plan_changed", "procedure must be unchanged"),
    ("auth_other_plan", "does not authorize"), ("auth_other_scope", "does not authorize"),
    ("spec_changed", "not the frozen P6-M10b blob")])
def test_inconsistent_rerun_prerequisites_are_refused(rerun_world, capsys, case, message):
    w = rerun_world
    if case == "record_exists":
        w.write("p6_m13_parity_audit_m10b.json", {})
    elif case == "outcome_failed":
        w.write("p6_m10b_outcome_model.json", {"passed": False, "model_identity": w.identity})
    elif case == "pins_differ":
        w.write("p6_m10b_pins.json", {"model_identity": {**w.identity, "calibrator_sha256": "x" * 64}})
    elif case == "registry_differs":
        (w.registry / "strategy_outcome_calibrator/p6m10b-v1/model.json").write_text("other", encoding="utf-8")
    elif case == "v1_plan_changed":
        w.write(rerun.V1_RECORD, {"plan_blob": "0" * 40, "frame_content_hash": "h" * 64})
    elif case in ("auth_other_plan", "auth_other_scope"):
        value = json.loads(w.auth.read_text(encoding="utf-8"))
        value.update(plan_blob="0" * 40) if case == "auth_other_plan" else value.update(scope="P6-M13")
        w.auth.write_text(json.dumps(value), encoding="utf-8")
    elif case == "spec_changed":
        import scripts.phase6_m10b as runner
        w.mp.setattr(runner, "git_blob", lambda path: "0" * 40)
    with pytest.raises(Blocked):
        rerun.rerun_prerequisites()
    assert message in capsys.readouterr().err


def test_absent_rerun_prerequisites_are_listed_together(rerun_world, capsys):
    (rerun_world.results / "p6_m10b_outcome_model.json").unlink()
    rerun_world.auth.unlink()
    with pytest.raises(Blocked):
        rerun.rerun_prerequisites()
    err = capsys.readouterr().err
    assert "cannot be run yet" in err and "a passed P6-M10b 2027 run" in err and "authorization" in err


def test_the_rerun_is_blocked_today_in_the_real_repository():
    assert not rerun.AUTHORIZATION.exists() and not Path(".agent/phase6/results/p6_m10b_outcome_model.json").exists()
    with pytest.raises(Blocked):
        rerun.rerun_prerequisites()


# --- the runner end to end on SYNTHETIC rows -----------------------------------------------------------------------


@dataclass
class _Row:
    match_key: str
    season: int
    comp_level: str
    red_teams: list
    blue_teams: list
    label: str
    scheduled_time: datetime


def _frame_rows():
    rng = random.Random(4)
    rows = []
    for i in range(14):
        red = [team(10 * i + k + 1, rng.uniform(4, 8), rng.uniform(18, 30), rng.uniform(2, 6)) for k in range(3)]
        blue = [team(10 * i + k + 5, rng.uniform(4, 8), rng.uniform(18, 30), rng.uniform(2, 6)) for k in range(3)]
        rows.append(_Row(f"2026syn_qm{i:02d}", 2026, "qualification", red, blue, LABEL_RED_WIN,
                         datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(hours=i)))
    rows.append(_Row("2026syn_qm90", 2026, "qualification", [team(901, epa_scale=None), team(902), team(903)],
                     [team(904), team(905), team(906)], LABEL_BLUE_WIN, datetime(2026, 3, 2, tzinfo=timezone.utc)))
    rows.append(_Row("2026syn_qm91", 2026, "qualification", [team(911, 1, 2, 0), team(912, 1, 2, 0),
                                                             team(913, 1, 2, 0)],
                     [team(914, 9, 40, 9), team(915, 9, 40, 9), team(916, 9, 40, 9)], LABEL_BLUE_WIN,
                     datetime(2026, 3, 2, tzinfo=timezone.utc)))
    rows.append(_Row("2025syn_qm00", 2025, "qualification", [team(1), team(2), team(3)], [team(4), team(5), team(6)],
                     LABEL_RED_WIN, datetime(2025, 3, 2, tzinfo=timezone.utc)))
    return rows


@pytest.fixture
def synthetic_rerun(monkeypatch):
    import ml.strategy.serving as serving
    import scripts.phase6_m10b as runner

    monkeypatch.setattr(rerun, "rerun_prerequisites", lambda: {
        "spec": {"blob": SPEC_BLOB}, "model_identity": IDENTITY,
        "v1_plan": {"blob": "v1plan", "frame_content_hash": "h" * 64}, "rerun_plan": {"blob": "rerunplan"}})
    monkeypatch.setattr(runner, "season_resolver", lambda database: SEASON_OF)
    monkeypatch.setattr(serving, "load_v2_model", lambda registry, identity, season_of, baseline_status: _v2(season_of))
    monkeypatch.setattr(common, "load_frame", lambda: (_frame_rows(), "h" * 64))
    # The plan's counts (10 ordinary, 2 full-search, 3 planted) make each run several minutes of exhaustive search;
    # the selection and audit code paths are identical at smaller counts.
    import scripts.phase6_m13_parity_audit as v1_runner
    monkeypatch.setattr(v1_runner, "ORDINARY", 2)
    monkeypatch.setattr(v1_runner, "FULL_SEARCH", 1)
    monkeypatch.setattr(v1_runner, "PLANTED_CONTEXTS", 1)
    return monkeypatch


def test_the_rerun_audits_v2_with_the_prediction_season_and_records_everything(synthetic_rerun):
    record = rerun.run_rerun(None)
    assert record["milestone"] == "P6-M13 parity rerun for P6-M10b" and record["spec"]["blob"] == SPEC_BLOB
    assert record["model_identity"] == IDENTITY and record["model"]["served_baseline_status"] == [VALIDATED, None]
    assert record["real_engine_passed"] and record["every_planted_defect_caught"] and record["p6_dm2_met"]
    assert {n: p["target_caught"] for n, p in record["planted_defects"].items()} == {n: True for n in PLANTED_DEFECTS_V2}
    assert record["contexts"]["missing_input"] == "2026syn_qm90" and record["contexts"]["low_odds"]["match_key"] == \
        "2026syn_qm91"
    assert len(record["contexts"]["ordinary"]) == 2 and all(k.startswith("2026") for k in record["contexts"]["ordinary"])
    assert record["preflight"]["prediction_seasons"] == [2026]
    assert set(record["code"]) == set(rerun.CODE_FILES) and all(len(b) == 40 for b in record["code"].values())
    assert record["authorizes_serving_alone"] is False


def test_the_rerun_refuses_a_loaded_model_of_another_identity(synthetic_rerun):
    import ml.strategy.serving as serving

    other = _v2()
    other.calibrator.artifact_sha256 = "d" * 64
    synthetic_rerun.setattr(serving, "load_v2_model", lambda *a, **k: other)
    with pytest.raises(Blocked):
        rerun.run_rerun(None)


def test_the_rerun_refuses_a_frame_other_than_the_plans(synthetic_rerun):
    synthetic_rerun.setattr(common, "load_frame", lambda: (_frame_rows(), "0" * 64))
    with pytest.raises(Blocked):
        rerun.run_rerun(None)


def test_a_failed_planted_defect_means_p6_dm2_is_not_met(synthetic_rerun):
    import ml.strategy.parity_audit as parity

    weak = {"not_a_defect": (StrategyEngine, "M6_missing_data_parity")}  # the real engine: nothing to catch
    synthetic_rerun.setattr(parity, "PLANTED_DEFECTS_V2", weak)
    record = rerun.run_rerun(None)
    assert record["planted_defects"]["not_a_defect"]["target_caught"] is False
    assert record["p6_dm2_met"] is False
