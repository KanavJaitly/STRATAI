"""Load whichever model versions Settings pins, once, at application startup.

Phase 4 Milestone 12. Deliberately separate from api.dependencies (which only
reads app.state back) and from api.app (which stays focused on assembling
middleware and routers) -- this is the one place "pinned version tag ->
actual loaded model" logic lives, so it is independently testable without
building a whole FastAPI app.

Settings.ml_ranking_model_version_tag / ml_win_prob_model_version_tag default
to None, which is this project's real current state: M4-M7's real, dated
backtest numbers are blocked on a Statbotics outage (.agent/phase4/
PHASE_STATUS.md), so no model has been accepted for production serving yet.
None here means "nothing pinned", not "the registry is broken" -- the two
are kept distinguishable in the log (see the two log lines below) even
though both resolve to the same None returned to app.state, since a route
serving model_not_loaded needs no finer distinction than that to answer a
request correctly, but an operator debugging why does.

A failure to load a *configured* pin (missing registry entry, corrupted
manifest, feature-list mismatch) is logged as an error and also resolves to
None rather than raising and failing application startup -- the same
"the API still boots with PostgreSQL down" posture api.app.create_app
already takes for the database, applied here to the ML layer: a bad ML
pin should degrade the prediction endpoints, not take down /health and
/ready along with them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from data.config import Settings
from ml.models.ranking_xgb import FEATURE_NAMES as RANKING_FEATURE_NAMES
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.win_prob import FEATURE_NAMES as WIN_PROB_FEATURE_NAMES
from ml.models.win_prob import WinProbXGBModel
from ml.registry import ModelManifest, load_registered_model

__all__ = [
    "load_pinned_ranking_model",
    "load_pinned_win_prob_model",
]


def _load_pinned_model(
    model_class: Any, *, model_type: str, settings: Settings, version_tag: str | None,
    current_feature_list: list[str], logger: logging.Logger,
) -> tuple[Any | None, ModelManifest | None]:
    if not version_tag:
        logger.info("No %s model version pinned (ML_%s_MODEL_VERSION_TAG unset) -- serving model_not_loaded", model_type, model_type.upper())
        return None, None
    try:
        model, manifest = load_registered_model(
            model_class, registry_dir=Path(settings.ml_registry_dir), model_type=model_type,
            version_tag=version_tag, current_feature_list=current_feature_list,
        )
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Failed to load pinned %s model version_tag=%r: %s -- serving model_not_loaded", model_type, version_tag, exc)
        return None, None
    logger.info("Loaded pinned %s model version_tag=%r (model_version=%s)", model_type, version_tag, manifest.model_version)
    return model, manifest


def load_pinned_ranking_model(settings: Settings) -> tuple[RankingXGBModel | None, ModelManifest | None]:
    logger = logging.getLogger(__name__)
    return _load_pinned_model(
        RankingXGBModel, model_type="ranking_xgb", settings=settings,
        version_tag=settings.ml_ranking_model_version_tag, current_feature_list=list(RANKING_FEATURE_NAMES),
        logger=logger,
    )


def load_pinned_win_prob_model(settings: Settings) -> tuple[WinProbXGBModel | None, ModelManifest | None]:
    logger = logging.getLogger(__name__)
    return _load_pinned_model(
        WinProbXGBModel, model_type="win_prob_xgb", settings=settings,
        version_tag=settings.ml_win_prob_model_version_tag, current_feature_list=list(WIN_PROB_FEATURE_NAMES),
        logger=logger,
    )
