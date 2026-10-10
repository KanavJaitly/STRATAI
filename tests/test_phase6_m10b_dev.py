"""P6-M10b DEV-M10b runner tests (frozen spec `P6_M10B_SPEC.md` §4, blob d699afaf).

SYNTHETIC rows and fit samples in tmp directories test the runner's logic only. DEV-M10b is not run, nothing is fit on
real data, nothing is registered, and no database is touched.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.phase6_common as common
import scripts.phase6_m10b as runner
from ml.calibration.gate import G2_FAIL, G2_PASS, G2_UNEVALUABLE, evaluate_calibration_gate
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE
from ml.features.score_components import ScoreComponents
from ml.strategy.calibration import SPEC_BLOB, CalibrationFitRefused
from ml.strategy.outcome import SPEC_PATH as V1_SPEC_PATH
from ml.strategy.outcome import fit_sample
from scripts.phase6_common import file_sha256
from scripts.phase6_playoff_track import Blocked
from tests.phase6_fixtures import team

SEASON_OF = {"2024a": 2024, "2025a": 2025, "2026a": 2026}.get


# --- the proceed rule (§4, C5) -----------------------------------------------------------------------------------


def _gate(status, rejected, ece):
    return SimpleNamespace(g2=SimpleNamespace(status=status, rejected_bins=rejected), ece=ece)


@pytest.mark.parametrize("raw, calibrated, statuses, outcome", [
    ((G2_FAIL, 4, 0.04), (G2_FAIL, 2, 0.03), ("pass", "pass", "pass"), "proceed"),  # the valid passing case
    ((G2_FAIL, 4, 0.04), (G2_PASS, 0, 0.04), ("pass", "pass", "pass"), "proceed"),  # ECE equal is allowed
    ((G2_PASS, 0, 0.02), (G2_PASS, 0, 0.02), ("pass", "pass", "pass"), "proceed"),  # raw has 0: equal is enough
    ((G2_FAIL, 3, 0.04), (G2_FAIL, 3, 0.02), ("pass", "fail", "pass"), "rule_not_met"),  # not strictly fewer
    ((G2_FAIL, 2, 0.04), (G2_FAIL, 3, 0.02), ("pass", "fail", "pass"), "rule_not_met"),  # more rejections
    ((G2_FAIL, 4, 0.03), (G2_FAIL, 1, 0.031), ("pass", "pass", "fail"), "rule_not_met"),  # ECE worse
    ((G2_UNEVALUABLE, 0, 0.04), (G2_PASS, 0, 0.03), ("pass", "unevaluable", "pass"), "unevaluable"),
    ((G2_FAIL, 4, 0.04), (G2_UNEVALUABLE, 0, 0.03), ("pass", "unevaluable", "pass"), "unevaluable"),
    ((G2_FAIL, 4, None), (G2_FAIL, 1, 0.03), ("pass", "pass", "unevaluable"), "unevaluable"),  # missing raw ECE
    ((G2_FAIL, 4, 0.04), (G2_FAIL, 1, float("nan")), ("pass", "pass", "unevaluable"), "unevaluable"),
    ((G2_FAIL, 4, 0.04), (G2_FAIL, 6, None), ("pass", "fail", "unevaluable"), "rule_not_met"),
])
def test_the_proceed_rule_with_explicit_statuses(raw, calibrated, statuses, outcome):
    decision = runner.dev_decision(None, _gate(*raw), _gate(*calibrated))
    assert tuple(decision["statuses"].values()) == statuses and decision["outcome"] == outcome
    assert decision["proceed"] is (outcome == "proceed")
    assert all(d["status"] in ("pass", "fail", "unevaluable") for d in decision["diagnostics"].values())


def test_zero_rejections_from_an_unevaluable_gate_are_never_a_pass():
    """Both report rejected_bins = 0, but the raw G2 was never measured: (ii) is unevaluable, DEV does not proceed."""
    decision = runner.dev_decision(None, _gate(G2_UNEVALUABLE, 0, 0.03), _gate(G2_UNEVALUABLE, 0, 0.02))
    assert decision["statuses"]["ii_g2_rejections"] == "unevaluable" and "raw_rejections" not in \
        decision["diagnostics"]["ii_g2_rejections"]
    assert decision["proceed"] is False and decision["outcome"] == "unevaluable"
    assert "blocked at DEV" in decision["consequence"]


def test_missing_ece_is_unevaluable_not_a_pass():
    decision = runner.dev_decision(None, _gate(G2_FAIL, 4, None), _gate(G2_FAIL, 1, None))
    assert decision["statuses"]["iii_ece"] == "unevaluable" and decision["proceed"] is False


def test_a_refused_fit_never_proceeds():
    decision = runner.dev_decision({"refused": True, "check": "solution_at_bound"}, None, None)
    assert decision["statuses"] == {"i_fit": "fail", "ii_g2_rejections": "unevaluable", "iii_ece": "unevaluable"}
    assert decision["proceed"] is False and decision["outcome"] == "rule_not_met"


def test_gate_status_is_explicit():
    rng = random.Random(2)
    p = [rng.random() for _ in range(2000)]
    gate = evaluate_calibration_gate(p, [rng.random() < v for v in p], symmetry_errors=[0.0],
                                     order_independent=True, fit_isolated=True)
    status = runner.gate_status(gate)
    assert set(status) == {"g1", "g2", "g3", "g4", "overall"}
    assert set(status.values()) <= {"pass", "fail", "unevaluable"}
    tiny = evaluate_calibration_gate([0.5], [True], symmetry_errors=[0.0], order_independent=True, fit_isolated=True)
    assert runner.gate_status(tiny)["g2"] == "unevaluable"


def test_the_rule_reads_the_real_gate_result():
    rng = random.Random(1)
    p = [rng.random() for _ in range(2000)]
    y = [rng.random() < v for v in p]
    gate = evaluate_calibration_gate(p, y, symmetry_errors=[0.0], order_independent=True, fit_isolated=True)
    assert runner.dev_decision(None, gate, gate)["proceed"] is (gate.g2.status != G2_UNEVALUABLE
                                                               and gate.ece is not None)


# --- prerequisites (run-once, ordering, frozen procedure, authorization) -----------------------------------------


@pytest.fixture
def dev_world(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    monkeypatch.setattr(common, "REGISTRY_DIR", tmp_path / "registry")
    (results / "p6_m10_fit.json").write_text(json.dumps({"spec_sha256": file_sha256(V1_SPEC_PATH),
                                                         "frame_content_hash": "h" * 64}), encoding="utf-8")
    auth = tmp_path / "dev_auth.json"
    auth.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                "scope": "DEV-M10b", "spec_blob": SPEC_BLOB}), encoding="utf-8")
    monkeypatch.setattr(runner, "DEV_AUTHORIZATION", auth)
    return SimpleNamespace(results=results, auth=auth, mp=monkeypatch, tmp=tmp_path)


def test_all_dev_prerequisites_satisfied(dev_world):
    provenance = runner.dev_prerequisites()
    assert provenance["spec"]["blob"] == SPEC_BLOB and provenance["v1_procedure"]["spec"] == V1_SPEC_PATH
    assert provenance["authorization"]["sha256"] == file_sha256(dev_world.auth)


@pytest.mark.parametrize("case, message", [
    ("dev_exists", "runs once"), ("calibrator_exists", "must precede the production calibrator"),
    ("v1_spec_changed", "not the v1 specification"), ("wrong_scope", "does not authorize DEV-M10b"),
    ("wrong_spec_blob", "does not authorize DEV-M10b"), ("spec_changed", "not the frozen P6-M10b blob")])
def test_inconsistent_dev_prerequisites_are_refused(dev_world, capsys, case, message):
    if case == "dev_exists":
        (dev_world.results / runner.DEV_RECORD).write_text("{}", encoding="utf-8")
    elif case == "calibrator_exists":
        (dev_world.results / runner.CALIBRATOR_RECORD).write_text("{}", encoding="utf-8")
    elif case == "v1_spec_changed":
        (dev_world.results / "p6_m10_fit.json").write_text(json.dumps({"spec_sha256": "0" * 64}), encoding="utf-8")
    elif case in ("wrong_scope", "wrong_spec_blob"):
        value = json.loads(dev_world.auth.read_text(encoding="utf-8"))
        value.update(scope="P6-M10b") if case == "wrong_scope" else value.update(spec_blob="0" * 40)
        dev_world.auth.write_text(json.dumps(value), encoding="utf-8")
    elif case == "spec_changed":
        dev_world.mp.setattr(runner, "git_blob", lambda path: "0" * 40)
    with pytest.raises(Blocked):
        runner.dev_prerequisites()
    assert message in capsys.readouterr().err


def test_absent_dev_prerequisites_are_listed_together(dev_world, capsys):
    (dev_world.results / "p6_m10_fit.json").unlink()
    dev_world.auth.unlink()
    with pytest.raises(Blocked):
        runner.dev_prerequisites()
    err = capsys.readouterr().err
    assert "cannot be run yet" in err and "p6_m10_fit.json" in err and "authorization to run DEV-M10b" in err


def test_dev_never_runs_again_in_the_real_repository(capsys):
    """DEV-M10b ran once on 2026-10-10; its record is write-once and the runner refuses a second run."""
    assert (Path(".agent/phase6/results") / runner.DEV_RECORD).exists()
    with pytest.raises(Blocked):
        runner.dev_prerequisites()
    assert "runs once" in capsys.readouterr().err


# --- only a genuine DEV record of this spec unlocks the next stage -----------------------------------------------


_PASSING = {"proceed": True, "statuses": {"i_fit": "pass", "ii_g2_rejections": "pass", "iii_ece": "pass"}}


@pytest.mark.parametrize("record, ok", [
    ({"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB}, "decision": _PASSING}, True),
    ({"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB}, "decision": {**_PASSING, "proceed": False}},
     False),
    ({"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB},
      "decision": {"proceed": True, "statuses": {**_PASSING["statuses"], "iii_ece": "unevaluable"}}}, False),
    ({"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB}, "decision": {"proceed": True}}, False),
    ({"milestone": runner.DEV_MILESTONE, "spec": {"blob": "0" * 40}, "decision": _PASSING}, False),
    ({"milestone": "P6-M10b (P6-M10 v2) 2027 acceptance", "spec": {"blob": SPEC_BLOB}, "decision": _PASSING}, False),
    ({"decision": {"proceed": "yes"}}, False), (None, False)])
def test_dev_proceeded(record, ok):
    assert runner.dev_proceeded(record) is ok


def test_a_dev_record_can_never_switch_serving(tmp_path):
    from ml.strategy.serving import m10b_serving_decision

    results, decisions = tmp_path / "results", tmp_path / "decisions"
    results.mkdir()
    decisions.mkdir()
    (results / runner.DEV_RECORD).write_text(json.dumps(
        {"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB}, "decision": _PASSING,
         "passed": True}), encoding="utf-8")
    assert m10b_serving_decision(results, decisions)["serve_v2"] is False


# --- the procedure end to end, on SYNTHETIC rows -------------------------------------------------------------------


@dataclass
class _Row:
    match_key: str
    event_key: str
    season: int
    comp_level: str
    red_teams: list
    blue_teams: list
    label: str
    scheduled_time: datetime
    score_red: int = 0
    score_blue: int = 0


def _alliance(rng, base_number, source):
    return [team(base_number + k, rng.uniform(1, 12), rng.uniform(5, 45), rng.uniform(0, 10),
                 epa_source_event_key=source) for k in range(3)]


def _season_rows(season, n, seed, sources):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        red, blue = _alliance(rng, 10 * i + 1, rng.choice(sources)), _alliance(rng, 10 * i + 5, rng.choice(sources))
        margin = sum(t.epa_total for t in red) - sum(t.epa_total for t in blue)
        p_red = 0.5 * math.erfc(-margin / 12.0 / math.sqrt(2.0))
        label = LABEL_TIE if i % 101 == 0 else (LABEL_RED_WIN if rng.random() < p_red else LABEL_BLUE_WIN)
        rows.append(_Row(f"{season}e{i // 25}_qm{i}", f"{season}e{i // 25}", season, "qualification", red, blue,
                         label, datetime(season, 3, 1, tzinfo=timezone.utc) + timedelta(hours=i)))
    return rows


def _fake_fit_set(calls):
    """Stands in for the real v1 fit-set builder (which reads score breakdowns from the database)."""
    def component_fit_set(rows, seasons, database):
        calls.append(tuple(seasons))
        rng = random.Random(7)
        samples, used = [], []
        for row in rows:
            if row.season not in seasons:
                continue

            def actual(teams):
                values = [max(0, round(sum(getattr(t, f"epa_{c}") for t in teams) + rng.gauss(0, 6)))
                          for c in ("auto", "teleop", "endgame")]
                return ScoreComponents(*values, 0, 0, sum(values))
            samples.append(fit_sample(row.red_teams, row.blue_teams, actual(row.red_teams), actual(row.blue_teams)))
            used.append(row)
        return samples, used, {"epa_incomplete": 3}
    return component_fit_set


@pytest.fixture
def dev_run(dev_world, monkeypatch):
    import scripts.phase6_m10_fit as fit_script

    rows = (_season_rows(2024, 500, 1, ["2024a"]) + _season_rows(2025, 1400, 2, ["2025a", "2025a", "2024a"])
            + _season_rows(2026, 1200, 3, ["2026a", "2026a", "2025a"]) + _season_rows(2027, 50, 4, ["2026a"]))
    calls = []
    monkeypatch.setattr(fit_script, "component_fit_set", _fake_fit_set(calls))
    monkeypatch.setattr(common, "load_frame", lambda: (rows, "h" * 64))
    monkeypatch.setattr(runner, "season_resolver", lambda database: SEASON_OF)
    monkeypatch.setattr(runner, "dev_prerequisites", lambda: {
        "spec": {"path": ".agent/phase6/P6_M10B_SPEC.md", "blob": SPEC_BLOB},
        "v1_procedure": {"spec": V1_SPEC_PATH, "spec_sha256": file_sha256(V1_SPEC_PATH), "spec_blob": "v1blob"}})
    return SimpleNamespace(rows=rows, calls=calls, world=dev_world)


def test_dev_refits_on_2024_calibrates_on_2025_and_evaluates_2026(dev_run):
    record = runner.run_dev(None)
    assert dev_run.calls == [(2024,)]
    assert record["seasons"] == {"base_fit": 2024, "calibration": 2025, "evaluation": 2026}
    assert record["calibration_set"]["seasons"] == [2025] and record["evaluation"]["population"]["season"] == 2026
    assert record["evaluation"]["fit_isolation"]["fit_isolated"] is True
    assert record["evaluation"]["fit_isolation"]["base_fit_seasons"] == [2024]
    assert record["evaluation"]["population"]["excluded"] == {"tie": 12}  # §2 refusals counted apart: none here
    assert set(record["calibration_set"]["groups"]) <= {"same", "mixed", "prior"}


def test_the_dev_record_is_provenance_complete_and_never_acceptance(dev_run):
    record = runner.run_dev(None)
    assert record["diagnostic_only"] is True and record["acceptance"] is False
    assert record["authorizes_serving"] is False and "never independent acceptance evidence" in record["evidence_class"]
    assert record["milestone"] == runner.DEV_MILESTONE and record["spec"]["blob"] == SPEC_BLOB
    assert record["frame_content_hash"] == "h" * 64 and record["v1_procedure"]["spec"] == V1_SPEC_PATH
    base, calibrator = record["base"], record["calibrator"]
    assert len(base["sha256"]) == 64 and base["registered"] is False and base["fit_rows"] == 500
    assert len(base["fit_set_fingerprint"]) == 64 and len(record["calibration_set"]["fingerprint"]) == 64
    assert len(record["evaluation"]["population"]["fingerprint"]) == 64
    assert calibrator["refused"] is False and calibrator["registered"] is False
    assert calibrator["base_sha256"] == base["sha256"] and len(calibrator["sha256"]) == 64
    assert set(record["evaluation"]) >= {"raw", "calibrated", "per_group_calibration", "fit_isolation"}
    assert set(record["decision"]["statuses"]) == {"i_fit", "ii_g2_rejections", "iii_ece"}
    assert record["decision"]["proceed"] is all(s == "pass" for s in record["decision"]["statuses"].values())
    for side in ("raw", "calibrated"):  # SYNTHETIC: logic only
        assert set(record["evaluation"][side]["status"]) == {"g1", "g2", "g3", "g4", "overall"}
    json.dumps(record, default=str)


def test_dev_is_deterministic_and_registers_nothing(dev_run):
    first, second = runner.run_dev(None), runner.run_dev(None)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    assert not (dev_run.world.tmp / "registry").exists()
    assert sorted(p.name for p in dev_run.world.results.iterdir()) == ["p6_m10_fit.json"]  # main writes the one record


def test_a_refused_dev_fit_stops_v2(dev_run, monkeypatch):
    import ml.strategy.calibration as calibration

    def refuse(*args, **kwargs):
        raise CalibrationFitRefused("solution_at_bound", {"a": 5.0})
    monkeypatch.setattr(calibration, "fit_calibrator", refuse)
    record = runner.run_dev(None)
    assert record["calibrator"] == {"refused": True, "check": "solution_at_bound", "details": {"a": 5.0},
                                    "registered": False}
    assert record["evaluation"] is None and record["decision"]["proceed"] is False
    assert not runner.dev_proceeded({**record, "spec": {"blob": SPEC_BLOB}})


def test_dev_refuses_a_frame_other_than_v1s(dev_run, monkeypatch):
    monkeypatch.setattr(common, "load_frame", lambda: (dev_run.rows, "0" * 64))
    with pytest.raises(Blocked):
        runner.run_dev(None)


def test_dev_refuses_a_base_fit_set_that_is_not_2024_only(dev_run, monkeypatch):
    import scripts.phase6_m10_fit as fit_script

    real = fit_script.component_fit_set
    monkeypatch.setattr(fit_script, "component_fit_set",
                        lambda rows, seasons, database: real(rows, (2024, 2025), database))
    with pytest.raises(Blocked):
        runner.run_dev(None)
