"""P6-M10c implementation tests (frozen spec `.agent/phase6/P6_M10C_SPEC.md`, blob f24a8d1c): the link, the §3 fit
and DEV-c's runner. SYNTHETIC fixtures in tmp directories test logic only. Nothing is fit on real data,
registered or served, and no database is touched."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.special import expit

import ml.strategy.calibration_m10c as m10c
import scripts.phase6_common as common
import scripts.phase6_m10c as runner
from ml.strategy.calibration import GROUPS, CalibrationFitRefused
from ml.strategy.calibration_m10c import FlooredCalibrator, FlooredOutcomeModel, fit_floored, floored
from ml.strategy.engine import StrategyEngine, candidate_strategies
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext
from ml.strategy.representation import Strategy
from scripts.phase6_playoff_track import Blocked
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

SEASONS = {"2026a": 2026, "2025a": 2025, "2024a": 2024}
RED, BLUE = [1, 2, 3], [4, 5, 6]


def _data(n=8000, eps=0.05, slopes=None, seed=3, probs=(.45, .35, .2)):
    rng = np.random.default_rng(seed)
    slopes = slopes or {"same": 1.3, "mixed": 1.0, "prior": 0.9}
    groups = rng.choice(list(GROUPS), n, p=probs).tolist()
    z = rng.normal(0, 1.8, n)
    a = np.array([slopes[g] for g in groups])
    s = np.where(rng.random(n) < eps / 2 + (1 - eps) * expit(a * z), 1, -1)
    return groups, z, s


def _calibrator(eps=0.05, **slopes):
    values = {"same": 1.3, "mixed": 1.0, "prior": 0.95, **slopes}
    return FlooredCalibrator(values, eps, {g: 1000 for g in GROUPS}, {g: "joint" for g in GROUPS}, {},
                             base_sha256="b" * 64, fit_set_fingerprint="f" * 64)


def _model(eps=0.05):
    base = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={"seasons": [2024, 2025]}, spec_sha256="0" * 64)
    return CalibratedLike(base, _calibrator(eps))


def CalibratedLike(base, calibrator):
    return FlooredOutcomeModel(base, calibrator, SEASONS.get)


def _context(**kw):
    red = tuple(team(n, epa_source_event_key="2026a") for n in RED)
    blue = tuple(team(n, 5.0, 24.0, 6.0, epa_source_event_key="2026a") for n in BLUE)
    return MatchContext(red, blue, prediction_season=2026, **kw)


# --- §1 the link through the real evaluation path --------------------------------------------------------------


def test_the_link_is_symmetric_and_carries_its_identity():
    model = _model()
    out = model.evaluate(_context(), Strategy.baseline(RED), Strategy.baseline(BLUE))
    swapped = model.evaluate(_context().swapped(), Strategy.baseline(BLUE), Strategy.baseline(RED))
    assert abs(out.p_red + swapped.p_red - 1.0) <= 1e-12 and abs(out.p_red + out.p_blue - 1.0) <= 1e-12
    assert out.model_version_tag == "p6m10c-v1" and out.calibration["eps"] == 0.05
    assert out.calibration["group"] == "same" and out.p_red == floored(1.3, 0.05, out.calibration["probit_index"])[0]


def test_ordering_never_reverses_v1_and_the_low_odds_display_is_reachable():
    base = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={"seasons": [2024, 2025]}, spec_sha256="0" * 64)
    lopsided = MatchContext(tuple(team(n, 30.0, 120.0, 30.0, epa_source_event_key="2026a") for n in RED),
                            tuple(team(n, 0.5, 1.0, 0.5, epa_source_event_key="2026a") for n in BLUE),
                            prediction_season=2026)
    v1, v3 = StrategyEngine(base), StrategyEngine(CalibratedLike(base, _calibrator(0.08)))
    strategies = candidate_strategies(RED, BLUE)
    p = np.array([v1.assess(lopsided, "red", s).p_ours for s in strategies])
    q = np.array([v3.assess(lopsided, "red", s).p_ours for s in strategies])
    levels = np.unique(p)
    assert np.all(np.array([q[p == v].max() for v in levels[:-1]]) <= np.array([q[p == v].min() for v in levels[1:]]))
    blue_view = v3.assess(lopsided, "blue", Strategy.baseline(BLUE))
    assert blue_view.p_ours < 0.05 and blue_view.display_ours == "<5%" and blue_view.p_ours >= 0.04 - 1e-15


def test_a_missing_prediction_season_is_refused_not_imputed():
    out = _model().evaluate(MatchContext(_context().red_teams, _context().blue_teams), Strategy.baseline(RED),
                            Strategy.baseline(BLUE))
    assert out.p_red is None and out.reasons == ("missing_input:prediction_season_absent",)


# --- §3 the fit ----------------------------------------------------------------------------------------------------


def test_the_fit_recovers_the_slopes_passes_every_check_and_is_deterministic():
    groups, z, s = _data()
    first = fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")
    second = fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")
    assert first.to_dict() == second.to_dict()
    assert all(abs(first.slopes[g] - v) < 0.15 for g, v in {"same": 1.3, "mixed": 1.0, "prior": 0.9}.items())
    assert 0 < first.eps < 0.08 and set(first.sources.values()) == {"joint"}
    joint = first.fits["joint"]
    assert joint["failed_checks"] == [] and joint["grad_inf"] <= 1e-7 and min(joint["hessian_eigenvalues"]) > 1e-10


def test_the_analytic_gradient_matches_finite_differences():
    groups, z, s = _data(n=3000)
    slot = np.array([GROUPS.index(g) for g in groups])
    objective = m10c._Objective(z, s.astype(float), slot, np.zeros(z.size))
    for theta in (np.array([1.2, 0.9, 1.1, 0.03]), np.array([0.7, 1.4, 1.0, 0.07])):
        fd = np.array([(objective.value(theta + e) - objective.value(theta - e)) / 2e-6 for e in np.eye(4) * 1e-6])
        assert np.max(np.abs(objective.grad(theta) - fd)) < 1e-7


@dataclass
class _Result:
    x: np.ndarray
    success: bool = True
    nit: int = 10


def _fixed(x):
    return lambda fun, x0, **kw: _Result(np.asarray(x, dtype=float))


@pytest.mark.parametrize("optimizer, check", [
    (lambda fun, x0, **kw: _Result(np.array([1.2, 1.0, 0.9, 0.04]), success=False), "optimizer_failed"),
    (lambda fun, x0, **kw: _Result(np.array([1.2, 1.0, 0.9, 0.04]), nit=1000), "optimizer_failed"),
    (_fixed([1.2, 1.0, 0.9, 0.0]), "no_floor_identified"),
    (_fixed([5.0, 1.0, 0.9, 0.04]), "solution_at_bound"),
    (_fixed([1.2, 1.0, 0.9, 0.08]), "solution_at_bound")])
def test_each_refusal_is_named(optimizer, check, monkeypatch):
    groups, z, s = _data(n=3000)
    monkeypatch.setattr(m10c, "POLISH_STEPS", 0)  # keep the injected point
    objective = m10c._Objective(z, s.astype(float), np.array([GROUPS.index(g) for g in groups]), np.zeros(z.size))
    with pytest.raises(CalibrationFitRefused) as e:
        m10c._fit(objective, optimizer=optimizer)
    assert e.value.check == check and check in e.value.details["failed_checks"]


def test_a_point_that_is_not_stationary_is_refused(monkeypatch):
    groups, z, s = _data(n=3000)
    monkeypatch.setattr(m10c, "POLISH_STEPS", 0)
    objective = m10c._Objective(z, s.astype(float), np.array([GROUPS.index(g) for g in groups]), np.zeros(z.size))
    with pytest.raises(CalibrationFitRefused) as e:
        m10c._fit(objective, optimizer=_fixed([0.6, 1.6, 2.0, 0.03]))
    assert e.value.check == "not_stationary"


def test_a_flat_objective_is_refused_as_not_unique():
    n = 900  # every group >= 200, so the joint fit (not the global fallback) is what fails
    with pytest.raises(CalibrationFitRefused) as e:
        fit_floored(["same"] * 300 + ["mixed"] * 300 + ["prior"] * 300, np.zeros(n),
                    np.where(np.arange(n) % 2, 1, -1), base_sha256="b", fit_set_fingerprint="f")
    assert e.value.check == "not_unique"


def test_a_flat_global_fit_refuses_when_a_small_group_needs_it():
    n = 600
    with pytest.raises(CalibrationFitRefused) as e:
        fit_floored(["same"] * 300 + ["mixed"] * 300, np.zeros(n), np.where(np.arange(n) % 2, 1, -1),
                    base_sha256="b", fit_set_fingerprint="f")
    assert e.value.check == "global_fit_refused" and e.value.details["small_groups"] == ["prior"]


def test_the_polish_reaches_stationarity_from_an_offset_start():
    groups, z, s = _data(n=4000)
    objective = m10c._Objective(z, s.astype(float), np.array([GROUPS.index(g) for g in groups]), np.zeros(z.size))
    report = m10c._fit(objective, optimizer=_fixed([1.25, 0.95, 0.95, 0.045]))  # near, not at, the optimum
    assert report["polish_steps"] >= 1 and report["grad_inf"] <= 1e-7


def test_a_small_group_uses_the_global_slope_and_the_global_fit_gates_only_then(monkeypatch):
    groups, z, s = _data(n=20000, probs=(.6, .39, .01))
    assert groups.count("prior") < 200
    cal = fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")
    assert cal.sources["prior"] == "global_fallback" and cal.slopes["prior"] == cal.fits["global"]["theta"][0]
    real = m10c._fit

    def global_fails(objective, **kw):
        report = real(objective, **kw)
        if objective.k == 1 and not (objective.slot < 0).any():  # the global fit
            report = {**report, "failed_checks": ["solution_at_bound"]}
        return report
    monkeypatch.setattr(m10c, "_fit", global_fails)
    with pytest.raises(CalibrationFitRefused) as e:
        fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")
    assert e.value.check == "global_fit_refused"
    groups, z, s = _data(n=20000)
    cal = fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")  # no small group: recorded only
    assert cal.fits["global"]["failed_checks"] == ["solution_at_bound"] and set(cal.sources.values()) == {"joint"}


@pytest.mark.parametrize("groups, z, s", [([], [], []), (["same"], [0.1], [0]), (["other"], [0.1], [1]),
                                          (["same"], [float("nan")], [1])])
def test_invalid_inputs_are_refused(groups, z, s):
    with pytest.raises(CalibrationFitRefused):
        fit_floored(groups, z, s, base_sha256="b", fit_set_fingerprint="f")


def test_the_calibrator_round_trips(tmp_path):
    cal = _calibrator()
    cal.save(tmp_path / "c.json")
    loaded = FlooredCalibrator.load(tmp_path / "c.json")
    assert loaded.slopes == cal.slopes and loaded.eps == cal.eps and len(loaded.artifact_sha256) == 64


# --- §4 DEV-c ------------------------------------------------------------------------------------------------------


def _gate(status, rejected, ece):
    return SimpleNamespace(g2=SimpleNamespace(status=status, rejected_bins=rejected), ece=ece)


@pytest.mark.parametrize("c, b, statuses, outcome", [
    (("fail", 1, 0.02), ("fail", 3, 0.03), ("pass", "pass", "pass", "pass"), "proceed"),
    (("pass", 0, 0.02), ("pass", 0, 0.02), ("pass", "pass", "pass", "pass"), "proceed"),
    (("fail", 2, 0.02), ("fail", 2, 0.03), ("pass", "pass", "fail", "pass"), "rule_not_met"),
    (("fail", 1, 0.031), ("fail", 3, 0.03), ("pass", "pass", "pass", "fail"), "rule_not_met"),
    (("unevaluable", 0, 0.02), ("fail", 3, 0.03), ("pass", "pass", "unevaluable", "pass"), "unevaluable"),
    (("fail", 1, None), ("fail", 3, 0.03), ("pass", "pass", "pass", "unevaluable"), "unevaluable"),
    (("fail", 1, float("nan")), ("fail", 3, 0.03), ("pass", "pass", "pass", "unevaluable"), "unevaluable")])
def test_the_decision_rule(c, b, statuses, outcome):
    decision = runner.dev_decision(None, None, _gate(*c), _gate(*b))
    assert tuple(decision["statuses"].values()) == statuses and decision["outcome"] == outcome
    assert decision["proceed"] is (outcome == "proceed")


def test_fit_failures_in_the_decision_rule():
    failed = runner.dev_decision({"check": "no_floor_identified"}, None, None, None)
    assert failed["statuses"] == {"D1_m10c_fit": "fail", "D2_m10b_form_fit": "pass",
                                  "D3_g2_rejections": "unevaluable", "D4_ece": "unevaluable"}
    assert failed["outcome"] == "rule_not_met" and not failed["proceed"]
    comparator = runner.dev_decision(None, {"check": "solution_at_bound"}, None, None)
    assert comparator["outcome"] == "unevaluable" and comparator["statuses"]["D2_m10b_form_fit"] == "unevaluable"


class _Database:
    def __init__(self, found):
        self.found = found

    def cursor(self):
        found = self.found

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                pass

            def fetchall(self):
                return [(k, t, w) for k, (t, w) in found.items()]
        return Cursor()


def test_event_classes_are_deterministic_and_fail_closed():
    found = {"a": (1, 0), "b": (0, 3), "c": (2, 4), "d": (5, 5), "e": (3, None), "f": (4, None), "g": (99, 2)}
    assert runner.event_classes(_Database(found), found) == {"a": "C", "b": "C", "c": "E", "d": "E", "e": "E",
                                                              "f": "E", "g": "other"}
    for bad in ({"a": (1, None)}, {"a": (True, 1)}, {"a": ("1", 2)}, {}):
        with pytest.raises(Blocked):
            runner.event_classes(_Database(bad), ["a"])


def _row(key, event, hour):
    return SimpleNamespace(match_key=key, event_key=event,
                           scheduled_time=datetime(2025, 3, 1, tzinfo=timezone.utc).replace(hour=hour))


def test_temporal_and_leakage_refusals():
    base = datetime(2024, 4, 20, tzinfo=timezone.utc)
    c, e = [_row("m1", "e1", 1), _row("m2", "e1", 2)], [_row("m3", "e2", 5)]
    assert runner.temporal_checks(base, c, e)["fit_isolated"] is True
    for c_rows, e_rows, base_time in ((c, [_row("m3", "e1", 5)], base), (c, [_row("m3", "e2", 2)], base),
                                      (c, [_row("m2", "e2", 5)], base), (c, e, datetime(2025, 3, 2, tzinfo=timezone.utc))):
        with pytest.raises(Blocked):
            runner.temporal_checks(base_time, c_rows, e_rows)


@pytest.fixture
def dev_world(tmp_path, monkeypatch):
    from tests.test_phase6_m10b_dev import _fake_fit_set, _season_rows

    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    import scripts.phase6_m10_fit as fit_script

    rows = (_season_rows(2024, 500, 1, ["2024a"]) + _season_rows(2025, 1800, 2, ["2025a", "2025a", "2024a"]))
    calls = []
    fake = _fake_fit_set(calls)
    samples, _, _ = fake(rows, (2024,), None)
    base = ComponentOutcomeModel.fit(samples, fit_info={}, spec_sha256="x")
    calls.clear()
    (results / "p6_m10b_dev.json").write_text(json.dumps({"base": {"beta": base.beta,
                                                                   "sigma_matrix": base.sigma_matrix.tolist()}}))
    (results / "p6_m10_fit.json").write_text(json.dumps({"frame_content_hash": "h" * 64, "spec_sha256": "s" * 64}))
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"authorized": True, "authorized_by": "SYNTHETIC", "date": "2099-01-01",
                                "scope": "DEV-c", "spec_blob": m10c.SPEC_BLOB}))
    monkeypatch.setattr(runner, "AUTHORIZATION", auth)
    monkeypatch.setattr(fit_script, "component_fit_set", fake)
    monkeypatch.setattr(common, "load_frame", lambda: (rows, "h" * 64))
    monkeypatch.setattr(runner, "season_resolver", lambda database: SEASONS.get)
    events = sorted({r.event_key for r in rows if r.season == 2025}, key=lambda k: int(k.split("e")[1]))
    monkeypatch.setattr(runner, "event_classes", lambda database, keys: {
        k: ("C" if i < len(events) // 2 else "E") for i, k in enumerate(events)})
    return SimpleNamespace(results=results, auth=auth, rows=rows, calls=calls, mp=monkeypatch)


def test_dev_c_end_to_end_on_synthetic_rows(dev_world):
    record = runner.run_dev(None)
    assert dev_world.calls == [(2024,)]
    assert record["diagnostic_only"] is True and record["acceptance"] is False
    assert record["authorizes_serving"] is False and record["authorizes_registration"] is False
    assert record["base"]["reproduces_dev_m10b"] == {"max_abs_beta_diff": 0.0, "max_abs_sigma_diff": 0.0}
    assert record["temporal"]["fit_isolated"] is True and record["spec"]["blob"] == m10c.SPEC_BLOB
    if record["evaluation"] is not None:
        population = record["evaluation"]["population"]
        assert population["season"] == 2025 and population["class"] == "E" and population["evaluated"] > 0
        for side in ("m10c", "m10b_form"):
            assert set(record["evaluation"][side]["status"]) == {"g1", "g2", "g3", "g4", "overall"}
    assert set(record["decision"]["statuses"]) == {"D1_m10c_fit", "D2_m10b_form_fit", "D3_g2_rejections", "D4_ece"}
    assert record["decision"]["outcome"] in {"proceed", "rule_not_met", "unevaluable"}  # SYNTHETIC: logic only
    json.dumps(record, default=str)


def test_dev_c_refuses_a_base_that_does_not_reproduce_dev_m10b(dev_world):
    (dev_world.results / "p6_m10b_dev.json").write_text(json.dumps(
        {"base": {"beta": {"auto": 9.0, "teleop": 9.0, "endgame": 9.0}, "sigma_matrix": [[0.0] * 4] * 4}}))
    with pytest.raises(Blocked):
        runner.run_dev(None)


@pytest.mark.parametrize("case, message", [("exists", "runs once"), ("no_auth", "authorization to run DEV-c"),
                                           ("bad_scope", "does not authorize DEV-c"),
                                           ("no_dev_m10b", "DEV-M10b's base")])
def test_dev_c_prerequisites(dev_world, capsys, case, message):
    if case == "exists":
        (dev_world.results / runner.DEV_RECORD).write_text("{}")
    elif case == "no_auth":
        dev_world.auth.unlink()
    elif case == "bad_scope":
        dev_world.auth.write_text(json.dumps({"authorized": True, "authorized_by": "x", "date": "d",
                                              "scope": "DEV-M10b", "spec_blob": m10c.SPEC_BLOB}))
    elif case == "no_dev_m10b":
        (dev_world.results / "p6_m10b_dev.json").unlink()
    with pytest.raises(Blocked):
        runner.dev_prerequisites()
    assert message in capsys.readouterr().err
