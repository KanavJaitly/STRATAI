"""Load the pinned models and the configured EPA source, once, at application startup.

Phase 4 Milestone 12, aligned on 2026-10-02 with what Phase 4 actually evaluated (D18):

* Ranking: only ``ranking_xgb_v2`` (M5 v2, RankingXGBModelV2) is servable. M5 v1
  (``ranking_xgb``) FAILED its gate and is refused by name -- there is no path that
  falls back to it.
* Win probability: only ``win_prob_xgb_calibrated`` (M6 + its symmetric isotonic
  calibrator, the pair D18 M7 evaluated) is servable. Raw M6 (``win_prob_xgb``) is
  refused: the calibration evidence belongs to the calibrated pair.
* Each pin is (model type, version tag, artifact sha256), all from Settings. The
  sha256 is checked against the registered file before it is loaded, so the served
  artifact is exactly the configured one; replacing it means changing the pins.
* EPA: the source Settings selects; ``d18_statbotics_primary`` is the evaluated
  configuration (ml.ratings.d18_source), loaded with its snapshot-integrity checks.

Nothing pinned is a real, representable state (model_not_loaded), distinct in the
log from a pin that failed to load. A failed load is logged and resolves to None
rather than failing startup, so /health and /ready stay up (api.app's posture for
the database, applied to the ML layer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data.config import Settings
from database.connection import Database
from ml.models.calibrated_win_prob import CALIBRATED_WIN_PROB_MODEL_TYPE, CalibratedWinProbModel
from ml.models.ranking_xgb_v2 import FEATURE_NAMES_V2, RankingXGBModelV2
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.registry import ModelManifest, load_registered_model, model_file_sha256

__all__ = [
    "NOT_SERVABLE_MODEL_TYPES",
    "SERVABLE_RANKING_MODELS",
    "SERVABLE_WIN_PROB_MODELS",
    "ServedEpaSource",
    "ServedModel",
    "load_epa_source",
    "load_pinned_ranking_model",
    "load_pinned_strategy_model",
    "load_playoff_models",
    "load_pinned_win_prob_model",
]

logger = logging.getLogger(__name__)

SERVABLE_RANKING_MODELS: dict[str, tuple[type, tuple[str, ...]]] = {
    "ranking_xgb_v2": (RankingXGBModelV2, tuple(FEATURE_NAMES_V2)),
}
SERVABLE_WIN_PROB_MODELS: dict[str, tuple[type, tuple[str, ...]]] = {
    CALIBRATED_WIN_PROB_MODEL_TYPE: (CalibratedWinProbModel, tuple(WIN_PROB_FEATURE_NAMES)),
}
NOT_SERVABLE_MODEL_TYPES = {
    "ranking_xgb": "M5 v1 FAILED its held-out gate (D5) and is superseded by ranking_xgb_v2 (D16)",
    "win_prob_xgb": "raw M6 without its evaluated calibrator; serve win_prob_xgb_calibrated",
}


@dataclass(frozen=True)
class ServedModel:
    """A loaded model and everything needed to trace it to its evaluated artifact."""

    model: Any
    manifest: ModelManifest
    version_tag: str
    sha256: str

    def identity(self) -> dict[str, Any]:
        return {"model_type": self.manifest.model_type, "model_version": self.manifest.model_version,
                "model_version_tag": self.version_tag, "model_sha256": self.sha256,
                "training_dataset_hash": self.manifest.training_dataset_hash,
                "provenance": self.manifest.provenance}


@dataclass(frozen=True)
class ServedEpaSource:
    provider: Any
    epa_source: str
    evaluated_configuration: bool  # True only for the D18 configuration Phase 4 evaluated
    provenance: dict[str, Any]
    adoption: dict[str, Any] | None = None  # P5-D3, for the adopted live source
    log_stamp: tuple[int, int] | None = None  # the live snapshot log's (mtime_ns, size) at load


def _load(kind: str, servable: dict[str, tuple[type, tuple[str, ...]]], model_type: str, version_tag: str | None,
          sha256: str | None, settings: Settings) -> ServedModel | None:
    if model_type in NOT_SERVABLE_MODEL_TYPES or model_type not in servable:
        logger.error("Refusing to serve %s model type %r: %s -- serving model_not_loaded", kind, model_type,
                     NOT_SERVABLE_MODEL_TYPES.get(model_type, "not a servable type"))
        return None
    if not version_tag:
        logger.info("No %s model version pinned (ML_%s_MODEL_VERSION_TAG unset) -- serving model_not_loaded",
                    kind, kind.upper())
        return None
    model_class, feature_list = servable[model_type]
    registry = Path(settings.ml_registry_dir)
    try:
        model, manifest = load_registered_model(model_class, registry_dir=registry, model_type=model_type,
                                                version_tag=version_tag, current_feature_list=list(feature_list),
                                                expected_sha256=sha256)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load pinned %s model %s/%s: %s -- serving model_not_loaded",
                     kind, model_type, version_tag, exc)
        return None
    if not isinstance(model, model_class):  # defensive: the registry returned what the allow-list names
        logger.error("Loaded %s model is %s, not %s -- serving model_not_loaded", kind, type(model), model_class)
        return None
    actual = model_file_sha256(registry, model_type, version_tag)
    logger.info("Loaded pinned %s model %s/%s (model_version=%s, sha256=%s)", kind, model_type, version_tag,
                manifest.model_version, actual)
    return ServedModel(model, manifest, version_tag, actual)


def load_pinned_ranking_model(settings: Settings) -> ServedModel | None:
    return _load("ranking", SERVABLE_RANKING_MODELS, settings.ml_ranking_model_type,
                 settings.ml_ranking_model_version_tag, settings.ml_ranking_model_sha256, settings)


def load_pinned_win_prob_model(settings: Settings) -> ServedModel | None:
    return _load("win_prob", SERVABLE_WIN_PROB_MODELS, settings.ml_win_prob_model_type,
                 settings.ml_win_prob_model_version_tag, settings.ml_win_prob_model_sha256, settings)


def load_pinned_strategy_model(settings: Settings) -> Any | None:
    """The pinned P6-M10 model (P7-M5), or None (served as model_not_loaded).

    Loaded only through ml.strategy.outcome.load_registered_strategy_model, which checks the artifact's sha256 and
    attaches the status its recorded evaluation earned (not_validated, p6_m10_gate_failed). The generic loader
    would serve the constructor default reason instead (p6_m10_evaluation_not_recorded; docs/P7Milestones.md P7-M5 (a)).
    """
    from ml.strategy.outcome import MODEL_TYPE, load_registered_strategy_model

    if settings.ml_strategy_model_type != MODEL_TYPE:
        logger.error("Refusing to serve strategy model type %r -- serving model_not_loaded",
                     settings.ml_strategy_model_type)
        return None
    if not settings.ml_strategy_model_version_tag:
        logger.info("No strategy model version pinned (ML_STRATEGY_MODEL_VERSION_TAG unset) -- serving "
                    "model_not_loaded")
        return None
    if not settings.ml_strategy_model_sha256:
        # The pin is (type, version tag, sha256); without the sha256 nothing proves the artifact is the one pinned.
        logger.error("Strategy model %s is pinned without ML_STRATEGY_MODEL_SHA256 -- serving model_not_loaded",
                     settings.ml_strategy_model_version_tag)
        return None
    try:
        model = load_registered_strategy_model(Path(settings.ml_registry_dir),
                                               version_tag=settings.ml_strategy_model_version_tag,
                                               expected_sha256=settings.ml_strategy_model_sha256)
    except (FileNotFoundError, ValueError, KeyError) as exc:  # KeyError: an artifact missing its fields
        logger.error("Failed to load pinned strategy model %s/%s: %s -- serving model_not_loaded", MODEL_TYPE,
                     settings.ml_strategy_model_version_tag, exc)
        return None
    logger.info("Loaded pinned strategy model %s/%s (sha256=%s)", MODEL_TYPE, settings.ml_strategy_model_version_tag,
                model.artifact_sha256)
    return model


def load_playoff_models(settings: Settings) -> Any | None:
    """The pinned PX-1 model and PX-2 calibrator (P7-M6), or None (served as model_not_loaded once the PX gates have
    passed; before that the pick list refuses with playoff_models_not_accepted). Every file is checked against its
    pinned sha256 before it is loaded, and the PX-1 file must be a `playoff_px1` model; nothing is substituted. The
    pick list also requires those sha256s to appear in the PX gate records (ml.playoffs.service, P7-D5)."""
    import hashlib

    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from ml.playoffs.px1 import MODEL_TYPE, PlayoffLogisticModel
    from ml.playoffs.service import PlayoffModels

    pins = (settings.ml_px1_version_tag, settings.ml_px1_sha256, settings.ml_px2_calibrator_path,
            settings.ml_px2_calibrator_sha256)
    if not any(pins):
        logger.info("No playoff models pinned (ML_PX1_* / ML_PX2_*) -- the pick list serves model_not_loaded")
        return None
    if not all(pins):
        logger.error("Playoff models are partly pinned; every ML_PX1_* and ML_PX2_* setting is required -- "
                     "serving model_not_loaded")
        return None
    px1_path = Path(settings.ml_registry_dir) / MODEL_TYPE / settings.ml_px1_version_tag / "model.json"
    px2_path = Path(settings.ml_px2_calibrator_path)
    try:
        px1_sha = hashlib.sha256(px1_path.read_bytes()).hexdigest()
        px2_sha = hashlib.sha256(px2_path.read_bytes()).hexdigest()
        if px1_sha != settings.ml_px1_sha256 or px2_sha != settings.ml_px2_calibrator_sha256:
            raise ValueError("a playoff model file does not match its pinned sha256")
        px1 = PlayoffLogisticModel.load(px1_path)
        if px1.model_type != MODEL_TYPE:  # the seed-only baseline is never served as PX-1
            raise ValueError(f"the pinned PX-1 file is a {px1.model_type!r} model, not {MODEL_TYPE!r}")
        calibrator = SymmetricIsotonicCalibrator.load(px2_path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.error("Failed to load the pinned playoff models: %s -- serving model_not_loaded", exc)
        return None
    logger.info("Loaded pinned playoff models (PX-1 %s, PX-2 %s)", px1_sha, px2_sha)
    return PlayoffModels(px1, calibrator.calibrate, px1_sha, px2_sha)


def load_epa_source(settings: Settings, database: Database) -> ServedEpaSource | None:
    """The EPA provider Settings selects, built once (ml.ratings.provider.default_point_in_time_provider)."""
    from ml.ratings.d18_source import D18_EPA_SOURCE
    from ml.ratings.provider import default_point_in_time_provider

    try:
        provider = default_point_in_time_provider(database, settings)
        provenance = provider.provenance()
    except Exception as exc:  # integrity failures, missing config, database down: never a silent substitute
        logger.error("Failed to load EPA source %r: %s -- prediction endpoints serve epa_source_not_loaded",
                     settings.epa_source, exc)
        return None
    provenance = {k: v for k, v in provenance.items() if k != "lookup_diagnostics"}
    logger.info("Loaded EPA source %r", settings.epa_source)
    if settings.epa_source == LIVE_EPA_SOURCE:
        from ml.ratings.live_epa import ADOPTION

        return ServedEpaSource(provider, settings.epa_source, False, provenance, adoption=ADOPTION,
                               log_stamp=live_log_stamp(settings))
    return ServedEpaSource(provider, settings.epa_source, settings.epa_source == D18_EPA_SOURCE, provenance)


LIVE_EPA_SOURCE = "p5_live_statbotics"


def live_log_stamp(settings: Settings) -> tuple[int, int] | None:
    """(mtime_ns, size) of the live snapshot log: it changes with every refresh entry (P5-M2 §4)."""
    if not settings.live_epa_log_dir:
        return None
    path = Path(settings.live_epa_log_dir) / "log.jsonl"
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size
