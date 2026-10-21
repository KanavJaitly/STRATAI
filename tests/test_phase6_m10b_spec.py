"""P6-M10b DRAFT spec, revision 2 (`.agent/phase6/P6_M10B_SPEC_DRAFT_V2.md`): specification checks.

Executable before any implementation (spec §8). No M10b production code exists yet, and none is written here.
- `_z` and `_q` below are TEST-LOCAL REFERENCES of the spec's §1 formulas. They are not an implementation.
- They are checked against the real v1 `StrategyEngine` on SYNTHETIC fixture contexts (not evidence of any
  real-data claim).
The pre-registered implementation tests (T-GROUP, T-FIT, T-WRAP, T-GATE, T-RUN, T-SERVE) come with the code, after
the spec is frozen and implementation is authorized.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.special import expit, log_ndtr

from ml.strategy.engine import StrategyEngine, candidate_strategies
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext
from ml.strategy.representation import Strategy
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team

DRAFT = Path(".agent/phase6/P6_M10B_SPEC_DRAFT_V2.md")
RED, BLUE = [1, 2, 3], [4, 5, 6]
FACTORS = (0.05, 0.5, 0.96, 1.0, 1.32, 5.0)  # the bounds, identity, and the 2026-like group slopes


def _z(x):
    """Spec §1 (reference): z(x) = log_ndtr(x) − log_ndtr(−x) = logit(Φ(x)), with no clipping."""
    return log_ndtr(x) - log_ndtr(-x)


def _q(a, x):
    """Spec §1 (reference): q_red = expit(a·z(x))."""
    return expit(a * _z(x))


def _clipped_logit(x):
    """The rejected draft-1 method: clip Φ(x) to [1e-12, 1 − 1e-12], then take the logit (C2's defect)."""
    p = min(max(0.5 * math.erfc(-x / math.sqrt(2.0)), 1e-12), 1 - 1e-12)
    return math.log(p / (1 - p))


# --- gate preservation (C7) --------------------------------------------------------------------------------------


def test_the_gate_function_and_constants_are_the_ones_the_draft_cites():
    import ml.calibration.gate as gate

    expected = {"N_BINS": (10, "10"), "MIN_BIN_COUNT": (30, "30"), "ALPHA": (0.05, "0.05"),
                "ECE_THRESHOLD": (0.05, "0.05"), "MIN_ELIGIBLE_BINS": (2, "2"), "TIE_TOLERANCE": (1e-7, "1e-7"),
                "SYMMETRY_TOLERANCE": (1e-12, "1e-12")}
    for name, (value, _) in expected.items():
        assert getattr(gate, name) == value, name
    text = DRAFT.read_text(encoding="utf-8")
    assert "ml.calibration.gate.evaluate_calibration_gate" in text and callable(gate.evaluate_calibration_gate)
    for name, (_, written) in expected.items():
        assert f"`{name} = {written}`" in text, name


def test_the_draft_marks_g4_and_the_population_as_proposed_changes_not_preserved():
    text = DRAFT.read_text(encoding="utf-8")
    assert "Proposed changes, each for Kanav's explicit approval (C8)" in text
    assert "calibrator-fit rows only from 2026" in text and "2027 D18 frame" in text
    assert "PROPOSED, NOT ADOPTED, NOT FROZEN" in text


# --- the stable log-odds (C2) ------------------------------------------------------------------------------------


def test_stable_log_odds_are_finite_strictly_increasing_and_exactly_antisymmetric():
    xs = np.arange(-40.0, 40.0001, 0.125)
    z = _z(xs)
    assert np.all(np.isfinite(z))
    assert np.all(np.diff(z) > 0)  # strictly increasing over the whole range, including the far tails
    assert np.array_equal(_z(-xs), -z)  # bit-for-bit antisymmetric
    assert abs(_z(0.0)) == 0.0 and _z(40.0) > 800


def test_clipping_would_create_ties_that_the_stable_form_does_not():
    xs = [7.5, 8.0, 9.0, 12.0, 20.0]
    clipped = {_clipped_logit(x) for x in xs}
    assert len(clipped) == 1  # draft 1's clipped logit collapses every one of these to one value
    assert len({float(_z(x)) for x in xs}) == len(xs)  # the stable form keeps them distinct


@pytest.mark.parametrize("a", FACTORS)
def test_calibrated_output_is_symmetric_within_the_g3_tolerance(a):
    xs = np.arange(-40.0, 40.0001, 0.25)
    q_red = expit(a * _z(xs))
    q_blue = expit(-a * _z(xs))  # computed directly, never as 1 − q_red
    assert np.max(np.abs(q_red + q_blue - 1.0)) <= 1e-12
    assert np.array_equal(expit(a * _z(-xs)), q_blue)  # swapping red and blue gives the blue output exactly


# --- within-match ordering and the unchanged tie-break (C1), against the real v1 engine --------------------------


def _engine() -> StrategyEngine:
    return StrategyEngine(ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64))


def _contexts():
    balanced = MatchContext(tuple(team(n, 6.0, 25.0, 4.0) for n in RED), tuple(team(n, 5.0, 24.0, 6.0) for n in BLUE))
    lopsided = MatchContext(tuple(team(n, 30.0, 120.0, 30.0) for n in RED),
                            tuple(team(n, 0.5, 1.0, 0.5) for n in BLUE))  # pushes x past v1's saturation
    return {"balanced": balanced, "lopsided": lopsided}


def _assessed(engine, context, side):
    own, opponents = (RED, BLUE) if side == "red" else (BLUE, RED)
    out = []
    for strategy in candidate_strategies(own, opponents):
        a = engine.assess(context, side, strategy)
        x = a.evaluation.mean_difference / a.evaluation.sigma
        out.append((a, x if side == "red" else -x))  # x from this side's perspective
    return out


@pytest.mark.parametrize("name", ["balanced", "lopsided"])
@pytest.mark.parametrize("side", ["red", "blue"])
@pytest.mark.parametrize("a_g", FACTORS)
def test_within_match_ordering_never_reverses_and_keeps_the_tie_break(name, side, a_g):
    engine = _engine()
    rows = _assessed(engine, _contexts()[name], side)
    p = np.array([r[0].p_ours for r in rows])
    x = np.array([r[1] for r in rows])
    q = expit(a_g * _z(x))  # this side's calibrated probability (§1; one group per context)
    order_x = np.argsort(x, kind="stable")
    # never reverses the probit index: q is non-decreasing along increasing x
    assert np.all(np.diff(q[order_x]) >= 0)
    # never reverses v1: for every pair v1 orders strictly (p_i < p_j), q_i <= q_j. Pairs v1 ties (e.g. p saturated
    # at exactly 1.0) may be ordered by x in v2 (spec §1.1), so only distinct v1 values are compared.
    levels = np.unique(p)
    q_max = np.array([q[p == level].max() for level in levels])
    q_min = np.array([q[p == level].min() for level in levels])
    assert np.all(q_max[:-1] <= q_min[1:])
    # the recommender's unchanged key, (-p_ours, changes_from_baseline, canonical_json), with q in place of p
    keyed = sorted(range(len(rows)), key=lambda i: (-q[i], rows[i][0].strategy.changes_from_baseline(),
                                                    rows[i][0].strategy.canonical_json()))
    for i, j in zip(keyed, keyed[1:]):
        assert q[i] >= q[j]
        if q[i] == q[j]:  # a tie is broken by the unchanged secondary keys
            assert (rows[i][0].strategy.changes_from_baseline(), rows[i][0].strategy.canonical_json()) <= \
                   (rows[j][0].strategy.changes_from_baseline(), rows[j][0].strategy.canonical_json())


def test_v1_saturates_in_the_lopsided_context_so_the_tie_behaviour_is_actually_exercised():
    rows = _assessed(_engine(), _contexts()["lopsided"], "red")
    p = [r[0].p_ours for r in rows]
    assert sum(1 for v in p if v == 1.0) > 1  # v1 ties at exactly 1.0 here; the ordering test above covers it
    x = [r[1] for r in rows]
    assert max(x) > 8.3
