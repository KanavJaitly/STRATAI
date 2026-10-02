"""The production serving contract (2026-10-02): only the D18 models of record are servable,
every pin is explicit (type, version tag, sha256), and the evaluated EPA source is the default."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.ml_loading import (
    NOT_SERVABLE_MODEL_TYPES,
    SERVABLE_RANKING_MODELS,
    SERVABLE_WIN_PROB_MODELS,
    load_epa_source,
    load_pinned_ranking_model,
)
from data.config import Settings
from ml.models.calibrated_win_prob import CalibratedWinProbModel
from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.ratings.provider import EpaSourceNotConfigured, default_point_in_time_provider

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_only_the_d18_models_of_record_are_servable():
    assert SERVABLE_RANKING_MODELS == {"ranking_xgb_v2": (RankingXGBModelV2, tuple(FEATURE_NAMES_V2))}
    assert SERVABLE_WIN_PROB_MODELS == {"win_prob_xgb_calibrated": (CalibratedWinProbModel, tuple(WIN_PROB_FEATURE_NAMES))}
    assert {"ranking_xgb", "win_prob_xgb"} <= set(NOT_SERVABLE_MODEL_TYPES)
    assert not set(NOT_SERVABLE_MODEL_TYPES) & (set(SERVABLE_RANKING_MODELS) | set(SERVABLE_WIN_PROB_MODELS))


def test_the_api_package_never_imports_the_superseded_ranking_model():
    for path in (PROJECT_ROOT / "api").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and node.module == "ml.models.ranking_xgb" for alias in node.names}
        assert "RankingXGBModel" not in imported, path


@pytest.mark.parametrize(("field", "value"), [("ml_ranking_model_type", "ranking_xgb"),
                                              ("ml_win_prob_model_type", "win_prob_xgb")])
def test_settings_refuse_a_superseded_model_type(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("kind", ["ranking", "win_prob"])
def test_a_pinned_version_requires_its_artifact_sha256(kind):
    with pytest.raises(ValidationError, match="SHA256"):
        Settings(**{f"ml_{kind}_model_version_tag": "d18"})


def test_defaults_are_the_evaluated_configuration_and_pin_nothing(monkeypatch):
    for name in ("EPA_SOURCE", "ML_RANKING_MODEL_VERSION_TAG", "ML_WIN_PROB_MODEL_VERSION_TAG"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.epa_source == "d18_statbotics_primary"
    assert settings.ml_ranking_model_type == "ranking_xgb_v2"
    assert settings.ml_win_prob_model_type == "win_prob_xgb_calibrated"
    assert settings.ml_ranking_model_version_tag is None  # serving requires an explicit pin
    assert load_pinned_ranking_model(settings) is None


def test_the_d18_source_fails_loudly_when_unconfigured(monkeypatch):
    monkeypatch.delenv("STATBOTICS_SNAPSHOT_DIR", raising=False)
    settings = Settings(epa_source="d18_statbotics_primary", statbotics_snapshot_dir=None)
    with pytest.raises(EpaSourceNotConfigured, match="STATBOTICS_SNAPSHOT_DIR"):
        default_point_in_time_provider(object(), settings)  # type: ignore[arg-type]
    assert load_epa_source(settings, object()) is None  # type: ignore[arg-type]  # served as epa_source_not_loaded
