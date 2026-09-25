"""Labeled match-outcome dataset construction: turning feature rows into training data.

Phase 4 Milestone 2 (authoritative plan, docs/P4Milestones.md). See
ml.dataset.builder for the implementation and its extensive
inclusion/exclusion-rule documentation.
"""

from ml.dataset.builder import (
    DATASET_BUILDER_VERSION,
    EXCLUSION_REASON_DQ_AFFECTED,
    EXCLUSION_REASON_DQ_STATUS_UNKNOWN,
    EXCLUSION_REASON_NO_SCHEDULED_TIME,
    EXCLUSION_REASON_UNPLAYED,
    EXCLUSION_REASON_WINNING_ALLIANCE_MISSING,
    LABEL_BLUE_WIN,
    LABEL_RED_WIN,
    LABEL_TIE,
    TRAINING_ROW_ARROW_SCHEMA,
    DatasetManifest,
    ExcludedMatch,
    PersistedDataset,
    TrainingFrameResult,
    TrainingRow,
    build_training_frame,
    persist_training_frame,
)

__all__ = [
    "DATASET_BUILDER_VERSION",
    "EXCLUSION_REASON_DQ_AFFECTED",
    "EXCLUSION_REASON_DQ_STATUS_UNKNOWN",
    "EXCLUSION_REASON_NO_SCHEDULED_TIME",
    "EXCLUSION_REASON_UNPLAYED",
    "EXCLUSION_REASON_WINNING_ALLIANCE_MISSING",
    "LABEL_BLUE_WIN",
    "LABEL_RED_WIN",
    "LABEL_TIE",
    "TRAINING_ROW_ARROW_SCHEMA",
    "DatasetManifest",
    "ExcludedMatch",
    "PersistedDataset",
    "TrainingFrameResult",
    "TrainingRow",
    "build_training_frame",
    "persist_training_frame",
]
