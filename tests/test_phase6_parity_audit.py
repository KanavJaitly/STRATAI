"""P6-M13: the parity audit passes on the real engine and catches every planted defect (synthetic fixtures)."""

from __future__ import annotations

import pytest

from ml.strategy.engine import StrategyEngine
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext
from ml.strategy.parity_audit import PLANTED_DEFECTS, AuditContexts, run_audit
from tests.phase6_fixtures import FIXTURE_BETA, FIXTURE_SIGMA, team


@pytest.fixture(scope="module")
def setup():
    model = ComponentOutcomeModel(FIXTURE_BETA, FIXTURE_SIGMA, fit_info={}, spec_sha256="0" * 64)
    ordinary = [MatchContext(tuple(team(n, 6, 25, 4) for n in (1, 2, 3)), tuple(team(n, 5, 24, 6) for n in (4, 5, 6)))]
    missing = MatchContext((team(1, None, None, None, epa_scale=None), team(2), team(3)),
                           tuple(team(n) for n in (4, 5, 6)))
    low = MatchContext(tuple(team(n, 1, 2, 0) for n in (1, 2, 3)), tuple(team(n, 9, 40, 9) for n in (4, 5, 6)))
    return model, AuditContexts(ordinary, missing, (low, "red"))


def test_real_engine_passes_every_check(setup):
    model, contexts = setup
    results = run_audit(StrategyEngine(model), contexts)
    assert [r.name for r in results if not r.passed] == []
    assert len(results) == 10


@pytest.mark.parametrize("name", sorted(PLANTED_DEFECTS))
def test_each_planted_defect_is_caught_by_its_target_check(setup, name):
    model, contexts = setup
    factory, target = PLANTED_DEFECTS[name]
    failed = [r.name for r in run_audit(factory(model), contexts) if not r.passed]
    assert target in failed
