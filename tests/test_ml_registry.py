"""Phase 4 Milestone 10: model registry, ml.registry.

Uses both a lightweight fixture Model (for fast, focused registry-mechanics
tests) and the real ml.models.ranking_xgb.RankingXGBModel (for one genuine
end-to-end round-trip proving this works against an actual production
model class, not just a stand-in).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.dataset.builder import LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, MatchFeatureRow, TeamFeatures
from ml.models.ranking_xgb import FEATURE_NAMES as RANKING_FEATURE_NAMES
from ml.models.ranking_xgb import RankingXGBModel
from ml.registry import (
    MANIFEST_FILENAME,
    MODEL_FILENAME,
    ModelManifest,
    list_registered_versions,
    load_registered_model,
    register_model,
)

_CREATED_AT = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


class _FixedRatingModel:
    """A trivial fixture Model: predict_rating always returns a fixed
    value. Fast and simple, used for registry-mechanics tests that don't
    need a real fit -- symmetry/leakage properties are already covered by
    ml.models's own test suites; this file tests the REGISTRY, not the
    model."""

    def __init__(self, rating: float = 1.0) -> None:
        self.rating = rating

    def fit(self, training_rows) -> None:
        return

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        raise NotImplementedError

    def predict_rating(self, team_features: TeamFeatures) -> float:
        return self.rating

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"model": "fixed_rating", "rating": self.rating}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "_FixedRatingModel":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(rating=data["rating"])


def _team_features(team_number: int, *, average_score: float | None = None) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=5, matches_used=5,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _real_ranking_rows(count: int = 20) -> list[TrainingRow]:
    rows = []
    for i in range(count):
        red_teams = [_team_features(9800 + i * 6 + j, average_score=20.0 + j) for j in range(3)]
        blue_teams = [_team_features(9800 + i * 6 + 3 + j, average_score=10.0 + j) for j in range(3)]
        rows.append(TrainingRow(
            match_key=f"9998zzztest_qm{i + 1}", event_key="9998zzztest", season=9998, comp_level="qualification",
            set_number=None, match_number=i + 1, scheduled_time=_CREATED_AT + timedelta(hours=i), label=LABEL_RED_WIN,
            score_margin=20, score_red=100, score_blue=80, red_teams=red_teams, blue_teams=blue_teams,
            red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
        ))
    return rows


# ---------------------------------------------------------------------------
# Registry mechanics (fixture model)
# ---------------------------------------------------------------------------


def test_register_and_load_round_trip_gives_identical_predictions(tmp_path: Path):
    model = _FixedRatingModel(rating=42.0)
    register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
        training_dataset_hash="abc123", feature_list=["average_score"], created_at=_CREATED_AT,
    )
    loaded, manifest = load_registered_model(
        _FixedRatingModel, registry_dir=tmp_path, model_type="fixed_rating", version_tag="v1",
        current_feature_list=["average_score"],
    )
    team = _team_features(9800, average_score=10.0)
    assert loaded.predict_rating(team) == model.predict_rating(team)
    assert manifest.model_type == "fixed_rating"


def test_register_creates_model_and_manifest_files(tmp_path: Path):
    model = _FixedRatingModel()
    target_dir = register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
        training_dataset_hash="abc123", feature_list=["average_score"], created_at=_CREATED_AT,
    )
    assert (target_dir / MODEL_FILENAME).exists()
    assert (target_dir / MANIFEST_FILENAME).exists()


def test_register_raises_on_duplicate_version_tag(tmp_path: Path):
    model = _FixedRatingModel()
    register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
        training_dataset_hash="abc123", feature_list=["average_score"], created_at=_CREATED_AT,
    )
    with pytest.raises(FileExistsError, match="write-once"):
        register_model(
            model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
            training_dataset_hash="def456", feature_list=["average_score"], created_at=_CREATED_AT,
        )


def test_load_raises_when_nothing_registered(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_registered_model(
            _FixedRatingModel, registry_dir=tmp_path, model_type="fixed_rating", version_tag="v1",
            current_feature_list=["average_score"],
        )


def test_load_raises_on_feature_list_mismatch(tmp_path: Path):
    """The milestone's own named mismatch-rejection test: an altered
    feature list must refuse to load, with a clear error naming both the
    registered and current feature lists."""
    model = _FixedRatingModel()
    register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
        training_dataset_hash="abc123", feature_list=["average_score", "defense_score"], created_at=_CREATED_AT,
    )
    with pytest.raises(ValueError, match="does not match"):
        load_registered_model(
            _FixedRatingModel, registry_dir=tmp_path, model_type="fixed_rating", version_tag="v1",
            current_feature_list=["average_score"],  # missing defense_score -- a schema-drift scenario
        )


def test_load_raises_on_model_type_mismatch_within_manifest(tmp_path: Path):
    model = _FixedRatingModel()
    target_dir = register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag="v1",
        training_dataset_hash="abc123", feature_list=["average_score"], created_at=_CREATED_AT,
    )
    manifest_data = json.loads((target_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    manifest_data["model_type"] = "some_other_type"
    (target_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        load_registered_model(
            _FixedRatingModel, registry_dir=tmp_path, model_type="fixed_rating", version_tag="v1",
            current_feature_list=["average_score"],
        )


def test_list_registered_versions_returns_empty_for_unknown_model_type(tmp_path: Path):
    assert list_registered_versions(tmp_path, "never_registered") == []


def test_list_registered_versions_returns_sorted_tags(tmp_path: Path):
    model = _FixedRatingModel()
    for tag in ("v2", "v1", "v10"):
        register_model(
            model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.0.0", version_tag=tag,
            training_dataset_hash="abc123", feature_list=["average_score"], created_at=_CREATED_AT,
        )
    assert list_registered_versions(tmp_path, "fixed_rating") == sorted(["v2", "v1", "v10"])


# ---------------------------------------------------------------------------
# Manifest completeness contract
# ---------------------------------------------------------------------------


def test_manifest_completeness_every_field_present_after_round_trip(tmp_path: Path):
    model = _FixedRatingModel()
    register_model(
        model, registry_dir=tmp_path, model_type="fixed_rating", model_version="1.2.3", version_tag="v1",
        training_dataset_hash="deadbeef", feature_list=["average_score", "defense_score"],
        created_at=_CREATED_AT, metrics={"spearman": 0.75, "top_k_recall": None}, random_seed=7,
    )
    _, manifest = load_registered_model(
        _FixedRatingModel, registry_dir=tmp_path, model_type="fixed_rating", version_tag="v1",
        current_feature_list=["average_score", "defense_score"],
    )
    assert manifest.model_type == "fixed_rating"
    assert manifest.model_version == "1.2.3"
    assert manifest.registry_version
    assert manifest.training_dataset_hash == "deadbeef"
    assert manifest.feature_list == ["average_score", "defense_score"]
    assert manifest.random_seed == 7
    assert manifest.metrics == {"spearman": 0.75, "top_k_recall": None}
    assert manifest.created_at == _CREATED_AT


def test_manifest_rejects_empty_feature_list():
    with pytest.raises(ValueError):
        ModelManifest(
            model_type="x", model_version="1.0.0", registry_version="1.0.0",
            training_dataset_hash="abc", feature_list=[], created_at=_CREATED_AT,
        )


def test_manifest_rejects_a_naive_created_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        ModelManifest(
            model_type="x", model_version="1.0.0", registry_version="1.0.0",
            training_dataset_hash="abc", feature_list=["a"], created_at=datetime(2026, 9, 25, 12, 0),
        )


# ---------------------------------------------------------------------------
# End-to-end with a real production model class
# ---------------------------------------------------------------------------


def test_real_ranking_model_round_trips_through_the_registry(tmp_path: Path):
    model = RankingXGBModel(num_boost_round=15)
    model.fit(_real_ranking_rows())
    probe = _team_features(9800, average_score=15.0)
    expected = model.predict_rating(probe)

    register_model(
        model, registry_dir=tmp_path, model_type="ranking_xgb", model_version="1.0.0", version_tag="2026-09-25",
        training_dataset_hash="realhash123", feature_list=list(RANKING_FEATURE_NAMES), created_at=_CREATED_AT,
        metrics={"beats_baseline": None},
    )
    loaded, manifest = load_registered_model(
        RankingXGBModel, registry_dir=tmp_path, model_type="ranking_xgb", version_tag="2026-09-25",
        current_feature_list=list(RANKING_FEATURE_NAMES),
    )
    assert loaded.predict_rating(probe) == expected
    assert manifest.feature_list == list(RANKING_FEATURE_NAMES)


def test_real_ranking_model_refuses_to_load_after_a_simulated_assembler_drift(tmp_path: Path):
    """The milestone's own named "2024<->2026 drift" scenario: register a
    real model against today's feature list, then simulate a future
    assembler that produces a DIFFERENT feature list -- load must refuse."""
    model = RankingXGBModel(num_boost_round=10)
    model.fit(_real_ranking_rows())
    register_model(
        model, registry_dir=tmp_path, model_type="ranking_xgb", model_version="1.0.0", version_tag="2026-09-25",
        training_dataset_hash="realhash123", feature_list=list(RANKING_FEATURE_NAMES), created_at=_CREATED_AT,
    )
    drifted_feature_list = [*RANKING_FEATURE_NAMES, "a_new_2026_only_field"]
    with pytest.raises(ValueError, match="does not match"):
        load_registered_model(
            RankingXGBModel, registry_dir=tmp_path, model_type="ranking_xgb", version_tag="2026-09-25",
            current_feature_list=drifted_feature_list,
        )
