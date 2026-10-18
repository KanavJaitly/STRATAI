"""P7-M6: api.ml_loading.load_playoff_models -- the pinned PX-1 model and PX-2 calibrator, or None, never a crash.

Every file here is SYNTHETIC (a two-coefficient PX-1 stand-in, a calibrator fitted on six points): the tests prove
the pin, hash and type checks, not anything about a real model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from api.ml_loading import load_playoff_models
from data.config import Settings
from ml.calibration.calibrator import SymmetricIsotonicCalibrator
from ml.playoffs.px1 import MODEL_TYPE, SEED_ONLY_MODEL_TYPE


def _px1_payload(model_type: str = MODEL_TYPE) -> dict:
    return {"model_type": model_type, "model_version": "synthetic", "coef": [0.1, 0.2],
            "design": {"seed": True, "composition_columns": [], "dropped": [], "rounds": [], "scale": {}},
            "fit_info": {}, "spec": "synthetic"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def files(tmp_path):
    registry = tmp_path / "registry"
    px1 = registry / MODEL_TYPE / "px1-synthetic" / "model.json"
    px1.parent.mkdir(parents=True)
    px1.write_text(json.dumps(_px1_payload()), encoding="utf-8")
    calibrator = SymmetricIsotonicCalibrator()
    calibrator.fit([0.2, 0.3, 0.4, 0.6, 0.7, 0.8], [False, False, True, False, True, True])
    px2 = tmp_path / "px2_calibrator.json"
    calibrator.save(px2)
    return registry, px1, px2


def _settings(registry: Path, px1: Path, px2: Path, **overrides) -> Settings:
    values = {"ml_registry_dir": str(registry), "ml_px1_version_tag": "px1-synthetic", "ml_px1_sha256": _sha(px1),
              "ml_px2_calibrator_path": str(px2), "ml_px2_calibrator_sha256": _sha(px2)}
    return Settings(**{**values, **overrides})


def test_nothing_pinned_is_none():
    assert load_playoff_models(Settings(ml_px1_version_tag=None, ml_px1_sha256=None, ml_px2_calibrator_path=None,
                                        ml_px2_calibrator_sha256=None)) is None


def test_partly_pinned_is_none(files):
    registry, px1, px2 = files
    assert load_playoff_models(_settings(registry, px1, px2, ml_px2_calibrator_sha256=None)) is None


def test_the_pinned_files_load_with_their_hashes(files):
    registry, px1, px2 = files
    models = load_playoff_models(_settings(registry, px1, px2))
    assert models is not None and models.px1.model_type == MODEL_TYPE
    assert (models.px1_sha256, models.px2_sha256) == (_sha(px1), _sha(px2))
    assert 0.0 < models.calibrate(0.7) < 1.0


def test_a_hash_mismatch_is_none(files):
    registry, px1, px2 = files
    assert load_playoff_models(_settings(registry, px1, px2, ml_px1_sha256="0" * 64)) is None


def test_the_seed_only_baseline_is_never_served_as_px1(files):
    registry, px1, px2 = files
    px1.write_text(json.dumps(_px1_payload(SEED_ONLY_MODEL_TYPE)), encoding="utf-8")
    assert load_playoff_models(_settings(registry, px1, px2)) is None


@pytest.mark.parametrize("payload", [
    {**_px1_payload(), "design": None},  # TypeError
    {k: v for k, v in _px1_payload().items() if k != "design"},  # KeyError
    {**_px1_payload(), "coef": "not numbers"},  # ValueError
    [1, 2, 3],  # TypeError (list indices)
])
def test_a_malformed_px1_file_is_none_not_a_crash(files, payload):
    registry, px1, px2 = files
    px1.write_text(json.dumps(payload), encoding="utf-8")
    assert load_playoff_models(_settings(registry, px1, px2)) is None
