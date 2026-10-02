"""Model registry: versioned save/load with a manifest, refusing to load a
model whose recorded feature list no longer matches the current feature
assembler.

Phase 4 Milestone 10 (docs/P4Milestones.md). "Any served prediction traces
to an exact model version + training dataset + feature list" is this
milestone's own done-means -- ModelManifest carries all three, plus the
model's own version string, its random seed, whatever backtest metrics it
was registered with, and a real creation timestamp, so a served prediction
is never disconnected from the evidence that justified shipping it.

The registry's own feature-list guard is deliberately independent of
whatever check the underlying model class does internally
(ml.models.ranking_xgb.RankingXGBModel.load and
ml.models.win_prob.WinProbXGBModel.load already refuse a feature-list
mismatch baked into their own save files) -- this is defense in depth, not
duplication: a future model class that forgets to add its own internal
check is still caught here, because load_registered_model compares the
manifest's own recorded feature_list against whatever the CALLER passes as
current_feature_list (e.g. ml.models.team_vector.TEAM_FEATURE_NAMES), not
against anything the model file itself claims. This is exactly the guard
against the "2024<->2026 schema drift" class of silent bug this milestone
names by name: a model registered against last season's feature list must
fail loudly the moment this season's assembler produces a different one,
never silently mispredict on features it was never trained to see.

Storage layout: registry_dir/<model_type>/<version_tag>/{model.json,
manifest.json} -- one directory per registered version, write-once (see
register_model's own docstring for why re-registration under an existing
tag is refused rather than silently overwritten). "Store artifacts outside
the request path" (the milestone's own wording) is satisfied structurally:
register_model and load_registered_model are both plain filesystem
operations with no network or database access, meant to run offline
(training time) and at API startup (a pinned version loaded once), never
per-request.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ml.backtest.harness import Model

__all__ = [
    "MANIFEST_FILENAME",
    "MODEL_FILENAME",
    "REGISTRY_MANIFEST_VERSION",
    "ModelManifest",
    "list_registered_versions",
    "load_registered_model",
    "register_model",
]

# Bumped whenever ModelManifest's own shape changes -- independent of any
# individual model's own *_VERSION constant, matching every other
# versioned artifact in this codebase's identical convention.
REGISTRY_MANIFEST_VERSION = "1.0.0"

MODEL_FILENAME = "model.json"
MANIFEST_FILENAME = "manifest.json"


class ModelManifest(BaseModel):
    """Everything a served prediction must be traceable back to. Every
    field here is required and non-empty (see the model_validator below) --
    a manifest with a blank model_type or an empty feature_list is not a
    partially-complete manifest, it is a caller error to surface loudly, the
    same "manifest-completeness contract" this milestone's own brief names.
    """

    model_type: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    registry_version: str = Field(min_length=1)
    training_dataset_hash: str = Field(min_length=1)
    feature_list: list[str] = Field(min_length=1)
    random_seed: int | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    created_at: datetime
    # Additive (2026-10-02): where the artifact comes from -- e.g. the evaluated source
    # version, frame hash and result record it reproduces (scripts/register_d18_production_models.py).
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_created_at_is_timezone_aware(self) -> "ModelManifest":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return self


def register_model(
    model: Model, *, registry_dir: Path, model_type: str, model_version: str, version_tag: str,
    training_dataset_hash: str, feature_list: Sequence[str], created_at: datetime,
    metrics: Mapping[str, float | None] | None = None, random_seed: int | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> Path:
    """Save `model` plus a manifest under
    registry_dir/model_type/version_tag/. Returns that directory's path.

    Write-once: raises FileExistsError if (model_type, version_tag) is
    already registered -- a re-registration under the same tag is a caller
    error to surface loudly, not a silent overwrite of an artifact an
    already-running API process might be pinned to.

    created_at is a required, caller-supplied, timezone-aware timestamp
    (not datetime.now() computed internally) so a caller registering a
    model trained earlier can record when TRAINING actually happened, not
    merely when this function was called -- the same real-vs-computed-time
    distinction this codebase already draws elsewhere (e.g.
    ml.dataset.builder.DatasetManifest's own build_date).
    """
    target_dir = registry_dir / model_type / version_tag
    if target_dir.exists():
        raise FileExistsError(
            f"a model is already registered at {target_dir} -- registry entries are write-once, "
            "choose a new version_tag rather than overwriting an existing one"
        )
    target_dir.mkdir(parents=True)
    model.save(target_dir / MODEL_FILENAME)

    manifest = ModelManifest(
        model_type=model_type, model_version=model_version, registry_version=REGISTRY_MANIFEST_VERSION,
        training_dataset_hash=training_dataset_hash, feature_list=list(feature_list),
        random_seed=random_seed, metrics=dict(metrics) if metrics else {}, created_at=created_at,
        provenance=dict(provenance) if provenance else {},
    )
    (target_dir / MANIFEST_FILENAME).write_text(manifest.model_dump_json(), encoding="utf-8")
    return target_dir


def load_registered_model(
    model_class: Any, *, registry_dir: Path, model_type: str, version_tag: str, current_feature_list: Sequence[str],
    expected_sha256: str | None = None,
) -> tuple[Model, ModelManifest]:
    """Load a previously-registered model, refusing to load if its
    manifest's own recorded feature_list does not match
    current_feature_list -- see the module docstring for the full
    rationale. Raises FileNotFoundError if nothing is registered at that
    (model_type, version_tag), and ValueError if the manifest's own
    model_type disagrees with the model_type requested (a defensive
    consistency check against a manually-tampered registry directory).
    """
    target_dir = registry_dir / model_type / version_tag
    manifest_path = target_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"no registered model found at {target_dir}")

    manifest = ModelManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.model_type != model_type:
        raise ValueError(
            f"{manifest_path} records model_type={manifest.model_type!r}, which does not match "
            f"the requested model_type={model_type!r}"
        )
    if list(manifest.feature_list) != list(current_feature_list):
        raise ValueError(
            f"registered model at {target_dir} was trained against feature list "
            f"{manifest.feature_list!r}, which does not match the current feature assembler's "
            f"list {list(current_feature_list)!r} -- refusing to load a model whose features "
            "no longer match what this code computes"
        )

    if expected_sha256 is not None:
        actual = model_file_sha256(registry_dir, model_type, version_tag)
        if actual != expected_sha256:
            raise ValueError(
                f"registered model at {target_dir} has sha256 {actual}, not the pinned {expected_sha256} -- "
                "refusing to load an artifact other than the one configured"
            )

    model = model_class.load(target_dir / MODEL_FILENAME)
    return model, manifest


def model_file_sha256(registry_dir: Path, model_type: str, version_tag: str) -> str:
    """sha256 of a registered model's own saved file: the artifact's identity."""
    return hashlib.sha256((registry_dir / model_type / version_tag / MODEL_FILENAME).read_bytes()).hexdigest()


def list_registered_versions(registry_dir: Path, model_type: str) -> list[str]:
    """Every version_tag registered for model_type, sorted -- empty if
    model_type has never been registered at all (not an error; an empty
    registry is a real, valid starting state)."""
    model_type_dir = registry_dir / model_type
    if not model_type_dir.exists():
        return []
    return sorted(
        entry.name for entry in model_type_dir.iterdir()
        if entry.is_dir() and (entry / MANIFEST_FILENAME).exists()
    )
