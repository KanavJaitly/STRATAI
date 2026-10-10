"""P6-M10b implementation tests (frozen spec `.agent/phase6/P6_M10B_SPEC.md`, blob d699afaf).

SYNTHETIC fixtures in tmp directories test software logic only. No DEV-M10b run, no production calibrator fit or
registration, no 2027 run, no serving change, and no database is touched.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from scipy.special import expit

from ml.strategy.calibration import (BOUNDS, GROUPS, MIN_GROUP_ROWS, SPEC_BLOB, CalibratedOutcomeModel, Calibrator,
                                     CalibrationFitRefused, CalibrationInputError, calibrated, fit_calibrator,
                                     fit_factor, source_group, stable_log_odds)
from ml.strategy.engine import StrategyEngine, candidate_strategies
from ml.strategy.outcome import (INSUFFICIENT_DATA, NOT_VALIDATED, VALIDATED, ComponentOutcomeModel, MatchContext)
from ml.strategy.representation import Strategy
from scripts.phase6_playoff_track import Blocked
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

RED, BLUE = [1, 2, 3], [4, 5, 6]
SEASONS = {"2026a": 2026, "2025a": 2025, "2027a": 2027}


def _team(n, source="2026a", **kw):
    return team(n, kw.pop("auto", 6.0), kw.pop("teleop", 25.0), kw.pop("endgame", 4.0), epa_source_event_key=source, **kw)


def _base(**kw):
    return ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={"seasons": [2024, 2025]}, spec_sha256="0" * 64,
                                 **kw)


def _calibrator(**factors):
    f = {"same": 1.32, "mixed": 1.0, "prior": 0.96, **factors}
    return Calibrator(f, 1.11, {g: 1000 for g in GROUPS}, {g: "group" for g in GROUPS}, {}, base_sha256="b" * 64,
                      fit_set_fingerprint="f" * 64)


def _context(red_sources=("2026a",) * 3, blue_sources=("2026a",) * 3, season=2026, **kw):
    red = tuple(_team(n, s) for n, s in zip(RED, red_sources))
    blue = tuple(_team(n, s, auto=5.0, teleop=24.0, endgame=6.0) for n, s in zip(BLUE, blue_sources))
    return MatchContext(red, blue, prediction_season=season, **kw)


def _model(**kw):
    return CalibratedOutcomeModel(_base(), _calibrator(**kw), SEASONS.get)


# --- numerical stability and symmetry (§1, C2) -------------------------------------------------------------------


@pytest.mark.parametrize("x", [0.0, 1e-9, 3.0, 8.3, 40.0, 1e3, -1e3])
def test_stable_log_odds_is_finite_and_exactly_antisymmetric(x):
    z = stable_log_odds(x)
    assert math.isfinite(z) and stable_log_odds(-x) == -z


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_probit_index_is_refused(bad):
    with pytest.raises(CalibrationInputError):
        stable_log_odds(bad)


@pytest.mark.parametrize("a", [0.05, 0.96, 1.32, 5.0])
def test_calibrated_output_is_symmetric_and_blue_is_computed_directly(a):
    for x in np.arange(-40, 40.01, 0.5):
        q_red, q_blue = calibrated(a, float(x))
        assert abs(q_red + q_blue - 1.0) <= 1e-12
        assert q_blue == float(expit(-a * stable_log_odds(float(x))))
        assert calibrated(a, float(-x)) == (q_blue, q_red)


# --- source groups and the prediction season (§2, C3) -------------------------------------------------------------


@pytest.mark.parametrize("sources, season, group", [
    (("2026a",) * 6, 2026, "same"), (("2025a",) * 6, 2026, "prior"), (("2026a",) * 3 + ("2025a",) * 3, 2026, "mixed"),
    (("2025a",) * 5 + ("2026a",), 2026, "mixed")])
def test_source_group_assignment(sources, season, group):
    teams = [_team(i + 1, s) for i, s in enumerate(sources)]
    assert source_group(teams, season, SEASONS.get) == group


def test_source_group_refusals():
    six = [_team(i + 1) for i in range(6)]
    with pytest.raises(CalibrationInputError) as e:
        source_group(six, None, SEASONS.get)
    assert e.value.reason == "prediction_season_absent"
    with pytest.raises(CalibrationInputError) as e:
        source_group([*six[:5], _team(6, "unknown")], 2026, SEASONS.get)
    assert e.value.reason == "epa_source_unresolvable"
    with pytest.raises(CalibrationInputError) as e:
        source_group([*six[:5], _team(6, "2027a")], 2026, SEASONS.get)  # a later season is never used
    assert e.value.reason == "epa_source_later_season"
    with pytest.raises(CalibrationInputError):
        source_group(six[:5], 2026, SEASONS.get)


def test_the_group_reads_only_prediction_time_source_keys():
    asked = []
    teams = [_team(i + 1, "2026a", average_score=99.0, average_score_present=True) for i in range(6)]
    source_group(teams, 2026, lambda key: asked.append(key) or SEASONS.get(key))
    assert asked == ["2026a"] * 6  # only D18's as_of source key, nothing else about the teams


def test_the_group_does_not_depend_on_strategy_or_observations():
    model = _model()
    context = _context(red_sources=("2026a", "2025a", "2026a"))
    groups = {model.evaluate(context, s, Strategy.baseline(BLUE)).calibration["group"]
              for s in candidate_strategies(RED, BLUE)[:200]}
    assert groups == {"mixed"}


# --- the single evaluation function (§1, C1/C9) ----------------------------------------------------------------


def test_the_wrapper_applies_the_groups_factor_to_the_base_probit_index():
    model = _model()
    context = _context(red_sources=("2025a",) * 3, blue_sources=("2025a",) * 3)
    red, blue = Strategy.baseline(RED), Strategy.baseline(BLUE)
    base = model.base.evaluate(context, red, blue)
    out = model.evaluate(context, red, blue)
    x = base.mean_difference / base.sigma
    assert out.calibration["group"] == "prior" and out.calibration["factor"] == 0.96
    assert out.p_red == calibrated(0.96, x)[0] and out.model_version_tag == "p6m10b-v1"
    swapped = model.evaluate(context.swapped(), blue, red)
    assert abs(out.p_red + swapped.p_red - 1.0) <= 1e-12  # G3 through the real wrapper


def test_the_wrapper_refuses_without_a_prediction_season_and_passes_base_refusals_through():
    model = _model()
    out = model.evaluate(_context(season=None), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert out.p_red is None and out.validation_status == INSUFFICIENT_DATA
    assert out.reasons == ("missing_input:prediction_season_absent",)
    playoff = model.evaluate(_context(comp_level="semifinal"), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert playoff.p_red is None  # v1's own refusal, unchanged


def test_the_baseline_status_is_not_validated_until_served_by_the_guard():
    out = _model().evaluate(_context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert out.validation_status == NOT_VALIDATED and out.reasons == ("p6_m10b_not_accepted",)


def test_a_calibrator_fit_on_another_base_is_refused():
    with pytest.raises(ValueError):
        CalibratedOutcomeModel(_base(artifact_sha256="a" * 64), _calibrator(), SEASONS.get)


# --- within-match ordering and the unchanged tie-break through the real engine (C1) ------------------------------


@pytest.mark.parametrize("lopsided", [False, True])
def test_recommendations_never_reverse_v1_strict_orders_and_keep_the_tie_break(lopsided):
    if lopsided:
        context = MatchContext(tuple(_team(n, auto=30.0, teleop=120.0, endgame=30.0) for n in RED),
                               tuple(_team(n, auto=0.5, teleop=1.0, endgame=0.5) for n in BLUE), prediction_season=2026)
    else:
        context = _context()
    v1, v2 = StrategyEngine(_base()), StrategyEngine(_model())
    strategies = candidate_strategies(RED, BLUE)
    p = np.array([v1.assess(context, "red", s).p_ours for s in strategies])
    q = np.array([v2.assess(context, "red", s).p_ours for s in strategies])
    levels = np.unique(p)
    assert np.all(np.array([q[p == v].max() for v in levels[:-1]]) <= np.array([q[p == v].min() for v in levels[1:]]))
    rec = v2.recommend(context, "red")
    ranked = [rec.recommended, *rec.alternatives]
    key = [(-a.p_ours, a.strategy.changes_from_baseline(), a.strategy.canonical_json()) for a in ranked]
    assert key == sorted(key) and rec.recommended.p_ours == q.max()  # the unchanged key, on calibrated odds


# --- the fit (§3, C4) --------------------------------------------------------------------------------------------


def _data(a_true, n=6000, seed=3):
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1.5, n)
    s = np.where(rng.random(n) < expit(a_true * z), 1, -1)
    return z, s


def test_the_fit_recovers_the_factor_passes_every_check_and_is_deterministic():
    z, s = _data(1.3)
    first, second = fit_factor(z, s), fit_factor(z, s)
    assert first == second and abs(first["a"] - 1.3) < 0.1
    assert abs(first["derivative"]) <= 1e-8 and first["curvature"] > 1e-12 and first["nit"] < 500


def test_a_solution_at_either_bound_is_refused():
    with pytest.raises(CalibrationFitRefused) as upper:
        fit_factor(*_data(20.0))
    assert upper.value.check == "solution_at_bound"
    rng = np.random.default_rng(5)
    z = rng.normal(0, 1, 4000)
    with pytest.raises(CalibrationFitRefused) as lower:
        fit_factor(z, np.where(z > 0, -1, 1))  # anti-correlated: the optimum is at the 0.05 bound
    assert lower.value.check == "solution_at_bound"


def test_a_flat_objective_is_refused_as_non_unique():
    with pytest.raises(CalibrationFitRefused) as e:
        fit_factor(np.zeros(500), np.where(np.arange(500) % 2, 1, -1))
    assert "not_unique" in e.value.details["failed_checks"] and e.value.details["curvature"] == 0.0


@dataclass
class _Result:
    x: float
    success: bool = True
    nit: int = 10


@pytest.mark.parametrize("result, check", [(_Result(1.3, success=False), "optimizer_failed"),
                                           (_Result(1.3, nit=500), "optimizer_failed"),
                                           (_Result(0.7), "not_stationary")])
def test_optimizer_failures_and_non_stationary_points_are_refused(result, check):
    z, s = _data(1.3)
    with pytest.raises(CalibrationFitRefused) as e:
        fit_factor(z, s, optimizer=lambda *a, **k: result)
    assert e.value.check == check


def test_invalid_fit_inputs_are_refused():
    with pytest.raises(CalibrationFitRefused):
        fit_factor([], [])
    with pytest.raises(CalibrationFitRefused):
        fit_factor([0.5, 1.0], [1, 0])
    with pytest.raises(CalibrationFitRefused):
        fit_calibrator(["same", "other"], [0.1, 0.2], [1, -1], base_sha256="b", fit_set_fingerprint="f")


def test_a_small_group_uses_the_global_factor_and_the_choice_depends_only_on_counts():
    z, s = _data(1.2, n=2150)
    groups = ["same"] * 1000 + ["mixed"] * 1000 + ["prior"] * 150
    cal = fit_calibrator(groups, z, s, base_sha256="b" * 64, fit_set_fingerprint="f" * 64)
    assert cal.counts == {"same": 1000, "mixed": 1000, "prior": 150} and MIN_GROUP_ROWS == 200
    assert cal.sources == {"same": "group", "mixed": "group", "prior": "global_fallback"}
    assert cal.factor("prior") == cal.global_factor and BOUNDS[0] < cal.global_factor < BOUNDS[1]
    again = fit_calibrator(groups, z, s, base_sha256="b" * 64, fit_set_fingerprint="f" * 64)
    assert again.to_dict() == cal.to_dict()


def test_a_refusal_in_any_group_means_no_calibrator():
    z1, s1 = _data(1.2, n=1000, seed=1)
    z2, s2 = _data(20.0, n=1000, seed=2)  # this group's optimum is at the upper bound
    with pytest.raises(CalibrationFitRefused):
        fit_calibrator(["same"] * 1000 + ["prior"] * 1000, np.r_[z1, z2], np.r_[s1, s2], base_sha256="b",
                       fit_set_fingerprint="f")


def test_the_calibrator_artifact_round_trips(tmp_path):
    cal = _calibrator()
    cal.save(tmp_path / "c.json")
    loaded = Calibrator.load(tmp_path / "c.json")
    assert loaded.factors == cal.factors and loaded.artifact_sha256 and loaded.spec_blob == SPEC_BLOB


# --- the runner: gate preservation, calibration set, fit isolation (§3, §5) --------------------------------------


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


def _rows(season, n=400, seed=9):
    from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE

    rng = random.Random(seed)
    src = f"{season}a" if f"{season}a" in SEASONS else "2026a"
    out = []
    for i in range(n):
        red = [_team(10 * i + 1 + k, src, auto=rng.uniform(1, 10), teleop=rng.uniform(5, 40)) for k in range(3)]
        blue = [_team(10 * i + 5 + k, src, auto=rng.uniform(1, 10), teleop=rng.uniform(5, 40)) for k in range(3)]
        label = LABEL_TIE if i % 97 == 0 else (LABEL_RED_WIN if rng.random() < 0.5 else "blue_win")
        out.append(_Row(f"{season}e{i // 20}_qm{i}", f"{season}e{i // 20}", season, "qualification", red, blue, label,
                        datetime(season, 3, 1, tzinfo=timezone.utc) + timedelta(hours=i)))
    return out


def test_the_gate_function_and_constants_are_unchanged():
    import inspect

    import ml.calibration.gate as gate
    import scripts.phase6_m10b as runner

    assert (gate.N_BINS, gate.MIN_BIN_COUNT, gate.ALPHA, gate.ECE_THRESHOLD, gate.MIN_ELIGIBLE_BINS,
            gate.TIE_TOLERANCE, gate.SYMMETRY_TOLERANCE) == (10, 30, 0.05, 0.05, 2, 1e-7, 1e-12)
    assert "evaluate_calibration_gate(" in inspect.getsource(runner.evaluate_gate)
    assert runner.BOOTSTRAP_SEED == 20261005


def test_the_calibration_set_is_2026_only_and_its_fingerprint_is_order_free():
    import scripts.phase6_m10b as runner

    rows = _rows(2026) + _rows(2027, seed=4) + _rows(2025, seed=5)
    cal = runner.calibration_set(rows, _base(), SEASONS.get)
    assert cal["seasons"] == [2026] and all(k.startswith("2026") for k in cal["match_keys"])
    assert cal["excluded"]["tie"] == len([r for r in _rows(2026) if r.label == "tie"])
    again = runner.calibration_set(list(reversed(rows)), _base(), SEASONS.get)
    assert again["fingerprint"] == cal["fingerprint"]


def test_fit_isolation_requires_both_fit_sets_before_2027():
    import scripts.phase6_m10b as runner

    base_fit = {"latest_fit_row": "2025-04-18T19:00:00-04:00"}
    cal = {"calibration_set": {"seasons": [2026], "latest": "2026-07-08T07:30:00-04:00"}}
    first = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert runner.fit_isolation([2024, 2025], base_fit, cal, first)["fit_isolated"]
    assert not runner.fit_isolation([2024, 2025, 2026], base_fit, cal, first)["fit_isolated"]
    late = {"calibration_set": {"seasons": [2026], "latest": "2027-03-02T00:00:00+00:00"}}
    assert not runner.fit_isolation([2024, 2025], base_fit, late, first)["fit_isolated"]
    wrong = {"calibration_set": {"seasons": [2026, 2027], "latest": "2026-07-08T07:30:00-04:00"}}
    assert not runner.fit_isolation([2024, 2025], base_fit, wrong, first)["fit_isolated"]


def test_the_gate_runs_on_calibrated_2027_odds_with_v1_and_m6m7_only_reported():
    import scripts.phase6_m10b as runner

    model = _model()
    cal = {"calibration_set": {"seasons": [2026], "latest": "2026-07-08T07:30:00-04:00"}}
    rows = _rows(2027, n=600) + _rows(2026, seed=2)
    types = {r.event_key: (99 if r.event_key == "2027e0" else 1) for r in rows}
    result = runner.evaluate_gate(rows, model, lambda r: 0.5, {"latest_fit_row": "2025-04-18T19:00:00-04:00"}, cal,
                                  types)
    # A1: counted, not evaluated; 19 because the event's first row is a tie, excluded earlier (as v1)
    assert result["population"]["excluded"]["non_official_event_type:99"] == 19
    assert set(result["population"]["event_types"]) == {"1"}
    assert result["population"]["season"] == 2027
    assert result["population"]["evaluated"] > 0 and result["fit_isolation"]["fit_isolated"]
    assert result["gate"]["g3_max_symmetry_error"] <= 1e-12 and result["gate"]["g3_order_independent"]
    assert "raw_v1_same_rows" in result and result["paired_log_loss_minus_m6m7"]["gated"] is False
    assert set(result["per_group_calibration"]) == set(result["population"]["groups"])  # reported, not gated
    assert sum(v["n"] for v in result["per_group_calibration"].values()) == result["population"]["evaluated"]
    assert isinstance(result["passed"], bool) and result["passed"] == result["gate"]["passed"]  # SYNTHETIC: logic only


# --- acceptance prerequisites, run-once (§6, C10) -----------------------------------------------------------------


def _dev_record(proceed=True, **over):
    """A SYNTHETIC DEV-M10b record of the frozen spec."""
    import scripts.phase6_m10b as runner

    status = "pass" if proceed else "fail"
    return {"milestone": runner.DEV_MILESTONE, "spec": {"blob": SPEC_BLOB},
            "decision": {"proceed": proceed, "statuses": {"i_fit": "pass", "ii_g2_rejections": status,
                                                          "iii_ece": "pass"}}, **over}


def _git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date) if date else None
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=SYNTHETIC", "-c", "user.email=s@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, env=env,
                          check=True).stdout.strip()


@pytest.fixture
def final_world(tmp_path, monkeypatch):
    """Every §6 prerequisite satisfied with SYNTHETIC stand-ins in tmp dirs and a tmp git repo."""
    import scripts.phase6_common as common
    import scripts.phase6_m10b as runner
    import scripts.phase6_px1b_final1 as final1
    import scripts.run_phase4_stratai as p4
    from ml.registry import model_file_sha256

    results, registry = tmp_path / "results", tmp_path / "registry"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    monkeypatch.setattr(common, "REGISTRY_DIR", registry)
    for model_type, tag in (("strategy_outcome_component", "p6m10-v1"), ("strategy_outcome_calibrator", "p6m10b-v1")):
        (registry / model_type / tag).mkdir(parents=True)
        (registry / model_type / tag / "model.json").write_text(f"{model_type}", encoding="utf-8")
    identity = {"base_sha256": model_file_sha256(registry, "strategy_outcome_component", "p6m10-v1"),
                "calibrator_sha256": model_file_sha256(registry, "strategy_outcome_calibrator", "p6m10b-v1")}

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    write(runner.DEV_RECORD, _dev_record())
    write("p6_m10_fit.json", {"registry": {"model_sha256": identity["base_sha256"]}})
    write(runner.PINS_RECORD, {"model_identity": identity})
    write(final1.EPA_RECORD, {"snapshot": "s", "chain": "c"})
    write(runner.FRAME_RECORD, {"frame_dir": str(tmp_path / "frame"), "content_hash": "h" * 64, "seasons": [2027]})
    monkeypatch.setattr(final1, "verified_epa_source", lambda record: (Path("s"), Path("c")))
    monkeypatch.setattr(p4, "frame_info", lambda d: {"manifest": {"content_hash": "h" * 64}})
    monkeypatch.setattr(common, "load_m6m7", lambda: "M6M7")
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                "scope": "P6-M10b", "season": 2027, "season_complete_and_synced": True,
                                "spec_blob": SPEC_BLOB, "amendment_a1_blob": runner.A1_BLOB}), encoding="utf-8")
    monkeypatch.setattr(runner, "AUTHORIZATION", auth)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name, date in ((runner.PINS_RECORD, "2026-10-11T00:00:00-04:00"), (runner.FRAME_RECORD, "2027-04-30T00:00:00-04:00")):
        path = repo / ".agent/phase6/results" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        _git(repo, "add", str(path.relative_to(repo)).replace("\\", "/"))
        _git(repo, "commit", "-q", "-m", name, date=date)
    monkeypatch.setattr(final1, "REPO", repo)
    return {"runner": runner, "results": results, "registry": registry, "write": write, "auth": auth,
            "repo": repo, "mp": monkeypatch, "identity": identity}


def test_all_prerequisites_satisfied(final_world):
    provenance = final_world["runner"].final_prerequisites()
    assert provenance["model_identity"] == final_world["identity"] and "ordering" in provenance


@pytest.mark.parametrize("knockout, named", [("dev", "DEV-M10b proceeded"), ("pins", "calibrator and base pins"),
                                             ("epa", "pinned 2027 EPA source"), ("frame", "2027 D18 frame record"),
                                             ("auth", "authorization to run P6-M10b")])
def test_each_missing_prerequisite_is_refused_and_named(final_world, capsys, knockout, named):
    runner, results = final_world["runner"], final_world["results"]
    import scripts.phase6_px1b_final1 as final1
    if knockout == "auth":
        final_world["auth"].unlink()
    else:
        (results / {"dev": runner.DEV_RECORD, "pins": runner.PINS_RECORD, "epa": final1.EPA_RECORD,
                    "frame": runner.FRAME_RECORD}[knockout]).unlink()
    with pytest.raises(Blocked):
        runner.final_prerequisites()
    err = capsys.readouterr().err
    assert "cannot be evaluated yet" in err and named in err


@pytest.mark.parametrize("case, message", [
    ("outcome_exists", "once only"), ("spec_changed", "not the frozen P6-M10b blob"),
    ("pin_mismatch", "does not match its pin"), ("auth_spec_blob", "does not authorize"),
    ("auth_season", "does not authorize"), ("frame_hash", "does not match its recorded content hash"),
    ("m6m7", "M6/M7 d18 baseline"), ("order", "not a strict ancestor"), ("base_not_v1", "does not match its pin"),
    ("a1_changed", "not the frozen amendment A1"), ("auth_a1_blob", "does not authorize")])
def test_inconsistent_prerequisites_are_refused_at_once(final_world, capsys, case, message):
    runner, mp = final_world["runner"], final_world["mp"]
    if case == "outcome_exists":
        final_world["write"](runner.OUTCOME_RECORD, {"passed": False})
    elif case == "spec_changed":
        mp.setattr(runner, "git_blob", lambda p: "0" * 40)
    elif case == "pin_mismatch":
        (final_world["registry"] / "strategy_outcome_calibrator/p6m10b-v1/model.json").write_text("x", "utf-8")
    elif case == "a1_changed":
        mp.setattr(runner, "A1_BLOB", "0" * 40)
    elif case in ("auth_spec_blob", "auth_season", "auth_a1_blob"):
        value = json.loads(final_world["auth"].read_text(encoding="utf-8"))
        value.update({"auth_spec_blob": {"spec_blob": "0" * 40}, "auth_season": {"season": 2026},
                      "auth_a1_blob": {"amendment_a1_blob": "0" * 40}}[case])
        final_world["auth"].write_text(json.dumps(value), encoding="utf-8")
    elif case == "frame_hash":
        import scripts.run_phase4_stratai as p4
        mp.setattr(p4, "frame_info", lambda d: {"manifest": {"content_hash": "0" * 64}})
    elif case == "m6m7":
        import scripts.phase6_common as common

        def bad():
            raise ValueError("sha mismatch")
        mp.setattr(common, "load_m6m7", bad)
    elif case == "base_not_v1":  # pins self-consistent, but the base is not the v1 artifact the fit record pins
        final_world["write"]("p6_m10_fit.json", {"registry": {"model_sha256": "0" * 64}})
    elif case == "order":  # a real history in which the 2027 frame was committed before the pins
        import scripts.phase6_px1b_final1 as final1
        repo = final_world["repo"].parent / "reordered"
        repo.mkdir()
        _git(repo, "init", "-q")
        for name, date in ((runner.FRAME_RECORD, "2026-10-11T00:00:00-04:00"),
                           (runner.PINS_RECORD, "2027-04-30T00:00:00-04:00")):
            path = repo / ".agent/phase6/results" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            _git(repo, "add", str(path.relative_to(repo)).replace("\\", "/"))
            _git(repo, "commit", "-q", "-m", name, date=date)
        mp.setattr(final1, "REPO", repo)
    with pytest.raises(Blocked):
        runner.final_prerequisites()
    err = capsys.readouterr().err
    assert message in err and "cannot be evaluated yet" not in err


def test_calibrate_and_pins_refuse_until_their_own_prerequisites(monkeypatch):
    import scripts.phase6_m10b as runner

    monkeypatch.setattr(runner, "read_record", lambda name: None)
    with pytest.raises(Blocked):
        runner.run_calibrate(None)  # no DEV-M10b record: the production calibrator is never fit
    with pytest.raises(Blocked):
        runner.run_pins(None)
    monkeypatch.setattr(runner, "read_record", lambda name: {**_dev_record(), "base_sha256": "b"})
    monkeypatch.setattr(runner, "_any_2027", lambda database: 3)
    with pytest.raises(Blocked):
        runner.run_calibrate(None)  # 2027 data exists: too late to fit
    with pytest.raises(Blocked):
        runner.run_pins(None)


def test_the_real_calibrate_and_final_runs_are_blocked_today():
    import scripts.phase6_m10b as runner

    assert not (Path(".agent/phase6/results") / runner.DEV_RECORD).exists()
    with pytest.raises(Blocked):
        runner.run_calibrate(None)
    with pytest.raises(Blocked):
        runner.final_prerequisites()


# --- the serving guard (§7, C11) --------------------------------------------------------------------------------


@pytest.fixture
def serving(tmp_path):
    results, decisions = tmp_path / "results", tmp_path / "decisions"
    results.mkdir()
    decisions.mkdir()
    identity = {"base_sha256": "b" * 64, "calibrator_sha256": "c" * 64}

    def outcome(passed=True):
        (results / "p6_m10b_outcome_model.json").write_text(json.dumps({"passed": passed, "model_identity": identity}),
                                                            encoding="utf-8")

    def confirm(**over):
        import hashlib
        sha = hashlib.sha256((results / "p6_m10b_outcome_model.json").read_bytes()).hexdigest()
        value = {"confirmed": True, "confirmed_by": "SYNTHETIC", "date": "2099-01-01",
                 "record": "p6_m10b_outcome_model.json", "record_sha256": sha, **over}
        (decisions / "p6_m10b_confirmation.json").write_text(json.dumps(value), encoding="utf-8")

    def parity(met=True, ident=None, **over):
        value = {"milestone": "P6-M13 parity rerun for P6-M10b", "spec": {"blob": SPEC_BLOB}, "p6_dm2_met": met,
                 "model_identity": ident or identity, **over}
        (results / "p6_m13_parity_audit_m10b.json").write_text(json.dumps(value), encoding="utf-8")
    return results, decisions, outcome, confirm, parity


def _decision(results, decisions):
    from ml.strategy.serving import m10b_serving_decision

    return m10b_serving_decision(results, decisions)


def test_the_guard_serves_v2_only_with_all_three(serving):
    results, decisions, outcome, confirm, parity = serving
    assert _decision(results, decisions)["serve_v2"] is False
    outcome()
    confirm()
    parity()
    decision = _decision(results, decisions)
    assert decision["serve_v2"] is True and decision["refusals"] == []


@pytest.mark.parametrize("case", ["not_passed", "no_confirmation", "wrong_sha", "unconfirmed", "no_parity",
                                  "parity_failed", "parity_other_identity", "no_outcome", "parity_v1_milestone",
                                  "parity_other_spec"])
def test_the_guard_refuses_each_missing_or_mismatched_condition(serving, case):
    results, decisions, outcome, confirm, parity = serving
    outcome(passed=case != "not_passed")
    if case != "no_confirmation":
        confirm(**({"record_sha256": "0" * 64} if case == "wrong_sha" else {"confirmed": False} if case == "unconfirmed"
                   else {}))
    if case != "no_parity":
        over = ({"milestone": "P6-M13"} if case == "parity_v1_milestone"
                else {"spec": {"blob": "0" * 40}} if case == "parity_other_spec" else {})
        parity(met=case != "parity_failed",
               ident={"base_sha256": "b" * 64, "calibrator_sha256": "x" * 64} if case == "parity_other_identity" else None,
               **over)
    if case == "no_outcome":
        (results / "p6_m10b_outcome_model.json").unlink()
    decision = _decision(results, decisions)
    assert decision["serve_v2"] is False and decision["refusals"]


def test_the_served_model_is_v1_unless_the_guard_passes(serving, monkeypatch):
    import ml.strategy.outcome as outcome_module
    from ml.strategy.serving import load_served_strategy_model

    results, decisions, outcome, confirm, parity = serving
    monkeypatch.setattr(outcome_module, "load_registered_strategy_model",
                        lambda registry, expected_sha256=None, **k: _base(version_tag="p6m10-v1"))
    model, decision = load_served_strategy_model(Path("unused"), results, decisions, SEASONS.get)
    assert isinstance(model, ComponentOutcomeModel) and decision["serve_v2"] is False
    out = model.evaluate(_context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert out.validation_status == NOT_VALIDATED  # v1's status, unchanged
    outcome()
    confirm()
    parity()
    import ml.registry as registry
    monkeypatch.setattr(registry, "load_registered_model",
                        lambda cls, **k: (Calibrator({"same": 1.3, "mixed": 1.0, "prior": 0.96}, 1.1,
                                                     {g: 1000 for g in GROUPS}, {g: "group" for g in GROUPS}, {},
                                                     base_sha256="b" * 64, fit_set_fingerprint="f",
                                                     artifact_sha256="c" * 64), None))
    model, decision = load_served_strategy_model(Path("unused"), results, decisions, SEASONS.get)
    assert isinstance(model, CalibratedOutcomeModel) and decision["serve_v2"] is True
    out = model.evaluate(_context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert out.validation_status == VALIDATED and out.calibration["group"] == "same"


# --- §7 served statuses, the coach path, and the parity audit's contexts --------------------------------------


def _served_v2():
    return CalibratedOutcomeModel(_base(), _calibrator(), SEASONS.get, baseline_status=(VALIDATED, None))


def test_served_v2_validates_only_the_baseline_case():
    from datetime import datetime as dt

    from ml.strategy.outcome import REASON_OBSERVATION, REASON_STRATEGY
    from ml.strategy.representation import CoachObservation

    model = _served_v2()
    baseline = model.evaluate(_context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert baseline.validation_status == VALIDATED
    other = next(s for s in candidate_strategies(RED, BLUE) if s.changes_from_baseline())
    assert REASON_STRATEGY in model.evaluate(_context(), other, Strategy.baseline(BLUE)).reasons
    obs = CoachObservation(event_key="e", team_number=1, kind="component_unavailable", component="teleop",
                           observed_at=dt(2026, 3, 1, tzinfo=timezone.utc), observer="Coach")
    observed = model.evaluate(_context(observations=(obs,)), Strategy.baseline(RED), Strategy.baseline(BLUE))
    assert observed.validation_status == NOT_VALIDATED and observed.reasons == (REASON_OBSERVATION,)


def test_the_coach_path_gets_the_same_calibrated_odds_as_the_ai_path():
    engine = StrategyEngine(_served_v2())
    rec = engine.recommend(_context(), "red")
    coach = engine.assess(_context(), "red", rec.recommended.strategy)
    assert coach.p_ours == rec.recommended.p_ours and coach.evaluation.calibration is not None


def test_the_parity_audit_keeps_the_prediction_season_when_it_rebuilds_a_context():
    from ml.strategy.parity_audit import check_m3_order_invariance

    result = check_m3_order_invariance(StrategyEngine(_served_v2()), [_context()])
    assert result.passed and result.cases == 1


def test_a_refused_production_fit_is_recorded_registers_nothing_and_stops_the_pins(monkeypatch, tmp_path):
    import scripts.phase6_common as common
    import scripts.phase6_m10b as runner

    monkeypatch.setattr(common, "REGISTRY_DIR", tmp_path / "registry")
    monkeypatch.setattr(runner, "read_record", lambda name: _dev_record())
    monkeypatch.setattr(runner, "_any_2027", lambda database: 0)
    monkeypatch.setattr(runner, "_spec", lambda: {"blob": SPEC_BLOB})
    monkeypatch.setattr(runner, "_base", lambda: (_base(artifact_sha256="b" * 64), {"frame_content_hash": "h"}))
    monkeypatch.setattr(common, "load_frame", lambda: ([], "h"))
    monkeypatch.setattr(runner, "season_resolver", lambda database: SEASONS.get)
    z, s = _data(20.0, n=1000)  # its optimum is at the upper bound
    monkeypatch.setattr(runner, "calibration_set", lambda rows, base, season_of: {
        "groups": ["same"] * 1000, "z": list(z), "s": list(s), "fingerprint": "f", "seasons": [2026],
        "latest": None, "excluded": {}})
    record = runner.run_calibrate(None)
    assert record["refused"] is True and record["check"] == "solution_at_bound" and "a" not in record
    assert not (tmp_path / "registry").exists()  # nothing registered
    monkeypatch.setattr(runner, "read_record", lambda name: record)
    with pytest.raises(Blocked):
        runner.run_pins(None)


# --- amendment A1: official events (frozen blob a453eaba) ---------------------------------------------------------


class _Cursor:
    def __init__(self, found):
        self.found, self.query = found, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.query = (sql, params)

    def fetchall(self):
        return list(self.found.items())


class _Database:
    def __init__(self, found):
        self.cursor_ = _Cursor(found)

    def cursor(self):
        return self.cursor_


def test_a1_reads_the_raw_tba_payload_type_and_never_the_canonical_column():
    import scripts.phase6_m10b as runner

    database = _Database({"2027a": 1, "2027b": 3})
    assert runner.official_event_types(database, ["2027b", "2027a", "2027a"]) == {"2027a": 1, "2027b": 3}
    sql, params = database.cursor_.query
    assert "raw_source_payloads" in sql and "'tba'" in sql and "is_current" in sql and "events." not in sql
    assert params == (["2027a", "2027b"],)


@pytest.mark.parametrize("found", [{"2027a": 1}, {"2027a": 1, "2027b": None}, {"2027a": 1, "2027b": "1"},
                                   {"2027a": 1, "2027b": True}, {"2027a": 1, "2027b": 2.0}])
def test_a1_fails_closed_when_a_type_is_unavailable_or_invalid(found):
    import scripts.phase6_m10b as runner

    with pytest.raises(Blocked):
        runner.official_event_types(_Database(found), ["2027a", "2027b"])


def test_a1_keeps_types_0_to_5_and_counts_the_rest_by_type():
    from collections import Counter

    import scripts.phase6_m10b as runner

    rows = [_Row(f"m{t}", f"e{t}", 2027, "qualification", [], [], "red_win", datetime(2027, 3, 1, tzinfo=timezone.utc))
            for t in (0, 1, 2, 3, 4, 5, 6, 7, 99, 100, -1)]
    excluded = Counter()
    kept = runner.official_rows(rows, {r.event_key: int(r.match_key[1:]) for r in rows}, excluded)
    assert [r.match_key for r in kept] == ["m0", "m1", "m2", "m3", "m4", "m5"]
    assert excluded == {f"non_official_event_type:{t}": 1 for t in (6, 7, 99, 100, -1)}


def test_a1_is_pinned_by_its_frozen_blob():
    import scripts.phase6_m10b as runner
    from scripts.phase6_common import git_blob

    assert runner.A1_BLOB == "a453eaba397d8108a8cf967c27da554021921e5f" == git_blob(runner.A1_PATH)
    assert runner._amendment() == {"path": runner.A1_PATH, "blob": runner.A1_BLOB}
