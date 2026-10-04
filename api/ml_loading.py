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
