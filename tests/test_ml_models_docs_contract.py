"""docs/ml_models.md (Phase 4 M13) matches the live code and the write-once D18 records.

Mirrors Phase 3 M15's discipline: every feature name, constant, endpoint, error code,
exclusion rule and frozen number the page quotes is checked here, so the page cannot
drift from the code or overstate a result.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs" / "ml_models.md"
RESULTS = PROJECT_ROOT / ".agent" / "phase4" / "results" / "d18"


@pytest.fixture(scope="module")
def docs_text() -> str:
    return DOCS.read_text(encoding="utf-8")


def _record(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def test_every_model_input_feature_is_documented(docs_text):
    from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2
    from ml.models.team_vector import TEAM_FEATURE_NAMES

    missing = [name for name in (*TEAM_FEATURE_NAMES, *FEATURE_NAMES_V2, "score_scale", "epa_scale")
               if f"`{name}`" not in docs_text]
    assert not missing
    assert f"the {len(TEAM_FEATURE_NAMES)} names above" in docs_text


def test_documented_constants_match_the_code(docs_text):
    from ml.calibration import gate
    from ml.features.scale import MIN_ALLIANCE_SCORES
    from ml.models import ranking_xgb_v2

    expected = {"ECE_THRESHOLD": gate.ECE_THRESHOLD, "MIN_BIN_COUNT": gate.MIN_BIN_COUNT, "ALPHA": gate.ALPHA,
                "SYMMETRY_TOLERANCE": gate.SYMMETRY_TOLERANCE, "RIDGE_LAMBDA": ranking_xgb_v2.RIDGE_LAMBDA,
                "MIN_QUAL_MATCHES": ranking_xgb_v2.MIN_QUAL_MATCHES, "MIN_ALLIANCE_SCORES": MIN_ALLIANCE_SCORES}
    for name, value in expected.items():
        match = re.search(rf"`{name}` = ([0-9]+(?:\.[0-9]+)?(?:e-?[0-9]+)?)", docs_text)
        assert match, f"{name} is not documented as `{name}` = <value>"
        assert float(match.group(1)) == float(value), name


def test_every_exclusion_reason_is_documented(docs_text):
    from ml.dataset import builder

    reasons = [getattr(builder, n) for n in dir(builder) if n.startswith("EXCLUSION_REASON_")]
    assert reasons and all(f"`{reason}`" in docs_text for reason in reasons)


def test_documented_endpoints_and_codes_are_exactly_the_live_ones(docs_text):
    from api.routes import predictions

    live = {(method, route.path) for route in predictions.router.routes for method in route.methods}
    documented = set(re.findall(r"`(GET|POST) (/predictions/[^`]+)`", docs_text))
    assert documented == live
    codes = {getattr(predictions, n) for n in dir(predictions) if n.startswith("CODE_")}
    assert all(f"`{code}`" in docs_text for code in codes)
    assert f"`{predictions.CALIBRATION_STATUS_UNCALIBRATED}`" in docs_text


def test_referenced_modules_exist(docs_text):
    for path in re.findall(r"`((?:ml|scripts|api|data|docs|\.agent)/[\w./-]+\.(?:py|md|json))`", docs_text):
        assert (PROJECT_ROOT / path).exists(), path


def _row(docs_text: str, label: str) -> str:
    return next(line for line in docs_text.splitlines() if line.startswith(f"| {label}"))


def test_frozen_numbers_match_the_d18_records(docs_text):
    m04, m05, m06, m07 = (_record(f"{n}_result.json") for n in ("m04", "m05v2", "m06", "m07"))
    win, rank = m04["result"]["win_prob"]["aggregate"], m04["result"]["ranking"]["aggregate"]
    assert f"**{win['log_loss']:.4f} / {win['brier_score']:.4f}**" in _row(docs_text, "M4 baseline")
    assert f"**{rank['spearman']:.4f} / {rank['top_k_recall']:.4f}**" in docs_text
    assert f"**{m05['primary']['model']['spearman']:.4f}**" in _row(docs_text, "M5 v2")
    agg = m06["model"]["aggregate"]
    assert f"**{agg['log_loss']:.4f} / {agg['brier_score']:.4f}**" in _row(docs_text, "M6")
    g2 = m07["gate"]["g2"]
    assert (f"**{m07['gate']['ece']:.4f} / {g2['rejected_bins']} of {g2['eligible_bins']} bins rejected**"
            in _row(docs_text, "M7"))


def test_documented_outcomes_match_the_records_and_the_done_means_gate(docs_text):
    from scripts.phase4_done_means import evaluate_done_means

    statuses = {"M5 v2": "m05v2", "M6": "m06", "M7": "m07", "M11": "m11"}
    for label, name in statuses.items():
        passed = _record(f"{name}_result.json")["passed"]
        assert _row(docs_text, label).rstrip(" |").endswith("PASS" if passed else "**FAILED**"), label
    done = evaluate_done_means(RESULTS)
    assert ("done-means is NOT MET" in docs_text) == (not done.met)
    assert ("Win probability calibrated: **NOT MET**" in docs_text) == (not done.win_prob_calibrated)
