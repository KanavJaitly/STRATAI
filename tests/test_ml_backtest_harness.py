"""Phase 4 Milestone 3: the temporal backtesting harness + model interface,
ml.backtest.harness.

Pure, database-free tests throughout -- Model, Fold, the split functions, and
both backtest runners all operate directly on already-assembled TrainingRow/
TeamFeatures objects (Milestone 1/2's own output types), never on the
database itself, so none of this needs a live Postgres to build or verify
against. Covers the milestone's own three named "What to test" scenarios
(split-integrity, metric-correctness end-to-end, protocol-conformance) plus
the tie-exclusion, fresh-model-per-fold, and ranking-ground-truth-gap
behaviors this module's own docstring documents as deliberate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.backtest.harness import (
    MODE_RANKING,
    MODE_WIN_PROB,
    SPLIT_HOLD_OUT_SEASON,
    SPLIT_WALK_FORWARD,
    Fold,
    Model,
    hold_out_season_split,
    run_ranking_backtest,
    run_win_prob_backtest,
    walk_forward_splits,
)
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures


def _team_features(team_number: int, average_score: float | None = None) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _row(
    *, match_key: str, event_key: str = "9970zzztest", season: int = 9970,
    scheduled_time: datetime, label: str = LABEL_RED_WIN,
    red_teams: list[TeamFeatures] | None = None, blue_teams: list[TeamFeatures] | None = None,
    score_red: int = 100, score_blue: int = 80,
) -> TrainingRow:
    return TrainingRow(
        match_key=match_key, event_key=event_key, season=season, comp_level="qualification",
        set_number=None, match_number=1, scheduled_time=scheduled_time, label=label,
        score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
        red_teams=red_teams if red_teams is not None else [_team_features(9701)],
        blue_teams=blue_teams if blue_teams is not None else [_team_features(9702)],
        red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
    )


_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _fold(
    *, label: str, train_rows: list[TrainingRow], test_rows: list[TrainingRow],
    split_strategy: str = SPLIT_HOLD_OUT_SEASON,
) -> Fold:
    """Test-only convenience wrapper: most tests here don't care which split
    strategy produced a Fold, only that Fold's own temporal-integrity
    guarantee holds -- defaults to SPLIT_HOLD_OUT_SEASON so those tests don't
    have to state it explicitly."""
    return Fold(label=label, train_rows=train_rows, test_rows=test_rows, split_strategy=split_strategy)


class _DummyModel:
    """Minimal Model-conforming stub: predict_win_prob returns a fixed
    probability, predict_rating returns the team's average_score (or 0.0 if
    absent), fit just records what it was called with, save/load round-trip
    nothing meaningful -- everything a protocol-conformance test needs and
    nothing a real model would.
    """

    def __init__(self) -> None:
        self.fit_calls: list[list[TrainingRow]] = []

    def fit(self, training_rows):
        self.fit_calls.append(list(training_rows))

    def predict_win_prob(self, match_features) -> float:
        return 0.75

    def predict_rating(self, team_features: TeamFeatures) -> float:
        return team_features.average_score if team_features.average_score is not None else 0.0

    def save(self, path: Path) -> None:
        path.write_text("dummy", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "_DummyModel":
        return cls()


# ---------------------------------------------------------------------------
# Fold / split integrity -- the milestone's own named test
# ---------------------------------------------------------------------------


def test_fold_rejects_a_leaky_split():
    train = [_row(match_key="m1", scheduled_time=_T0 + timedelta(days=10))]
    test = [_row(match_key="m2", scheduled_time=_T0)]  # BEFORE train -- leaky
    with pytest.raises(ValueError, match="temporal ordering"):
        _fold(label="leaky", train_rows=train, test_rows=test)


def test_fold_accepts_a_valid_split():
    train = [_row(match_key="m1", scheduled_time=_T0)]
    test = [_row(match_key="m2", scheduled_time=_T0 + timedelta(days=1))]
    fold = _fold(label="valid", train_rows=train, test_rows=test)
    assert fold.train_rows == train
    assert fold.test_rows == test


def test_fold_allows_empty_train_or_test_with_no_ordering_check():
    # Nothing to violate an ordering guarantee against when one side is empty.
    _fold(label="empty_test", train_rows=[_row(match_key="m1", scheduled_time=_T0)], test_rows=[])
    _fold(label="empty_train", train_rows=[], test_rows=[_row(match_key="m1", scheduled_time=_T0)])


def test_hold_out_season_split_basic():
    rows = [
        _row(match_key="m1", season=2024, scheduled_time=_T0),
        _row(match_key="m2", season=2026, scheduled_time=_T0 + timedelta(days=400)),
    ]
    fold = hold_out_season_split(rows, held_out_season=2026)
    assert [r.match_key for r in fold.train_rows] == ["m1"]
    assert [r.match_key for r in fold.test_rows] == ["m2"]


def test_hold_out_season_split_rejects_holding_out_an_earlier_season():
    # 2024 is chronologically BEFORE 2026, so training on 2026 while testing
    # on 2024 would put future data in the train fold -- Fold's own
    # temporal-ordering assertion must catch this, not silently allow it.
    rows = [
        _row(match_key="m1", season=2024, scheduled_time=_T0),
        _row(match_key="m2", season=2026, scheduled_time=_T0 + timedelta(days=400)),
    ]
    with pytest.raises(ValueError, match="temporal ordering"):
        hold_out_season_split(rows, held_out_season=2024)


def test_hold_out_season_split_raises_for_a_season_with_no_rows():
    rows = [_row(match_key="m1", season=2024, scheduled_time=_T0)]
    with pytest.raises(ValueError, match="no matching rows"):
        hold_out_season_split(rows, held_out_season=2099)


def test_hold_out_season_split_raises_when_nothing_would_remain_to_train_on():
    rows = [_row(match_key="m1", season=2024, scheduled_time=_T0)]
    with pytest.raises(ValueError, match="no rows to train"):
        hold_out_season_split(rows, held_out_season=2024)


def test_walk_forward_splits_produces_one_fold_per_week_boundary():
    # Three distinct ISO weeks -> 2 boundaries: (week1->week2), (week1+2->week3).
    rows = [
        _row(match_key="m1", scheduled_time=_T0),
        _row(match_key="m2", scheduled_time=_T0 + timedelta(weeks=1)),
        _row(match_key="m3", scheduled_time=_T0 + timedelta(weeks=2)),
    ]
    folds = walk_forward_splits(rows)
    assert len(folds) == 2
    assert [r.match_key for r in folds[0].train_rows] == ["m1"]
    assert [r.match_key for r in folds[0].test_rows] == ["m2"]
    assert [r.match_key for r in folds[1].train_rows] == ["m1", "m2"]
    assert [r.match_key for r in folds[1].test_rows] == ["m3"]


def test_walk_forward_splits_empty_for_a_single_week():
    rows = [_row(match_key="m1", scheduled_time=_T0), _row(match_key="m2", scheduled_time=_T0 + timedelta(hours=1))]
    assert walk_forward_splits(rows) == []


def test_walk_forward_splits_every_fold_passes_temporal_integrity():
    # Not hand-checked per fold -- Fold's own __post_init__ already asserts
    # this for every fold walk_forward_splits constructs, so simply
    # constructing them without a raised ValueError is the proof.
    rows = [_row(match_key=f"m{i}", scheduled_time=_T0 + timedelta(weeks=i)) for i in range(5)]
    folds = walk_forward_splits(rows)
    assert len(folds) == 4


# ---------------------------------------------------------------------------
# Model protocol conformance -- the milestone's own named test
# ---------------------------------------------------------------------------


def test_dummy_model_conforms_to_the_model_protocol():
    assert isinstance(_DummyModel(), Model)


def test_dummy_model_runs_end_to_end_through_the_win_prob_harness(tmp_path: Path):
    rows = [
        _row(match_key="m1", scheduled_time=_T0, label=LABEL_RED_WIN),
        _row(match_key="m2", scheduled_time=_T0 + timedelta(days=1), label=LABEL_BLUE_WIN),
    ]
    fold = _fold(label="conformance", train_rows=rows[:1], test_rows=rows[1:])
    result = run_win_prob_backtest(_DummyModel, [fold])
    assert result.mode == MODE_WIN_PROB
    assert result.aggregate.row_count == 1
    assert result.aggregate.accuracy is not None
    # Also exercise save/load, part of the named protocol.
    model = _DummyModel()
    model.save(tmp_path / "model.bin")
    restored = _DummyModel.load(tmp_path / "model.bin")
    assert isinstance(restored, Model)


# ---------------------------------------------------------------------------
# run_win_prob_backtest
# ---------------------------------------------------------------------------


def test_run_win_prob_backtest_excludes_ties_and_counts_them():
    rows = [
        _row(match_key="m1", scheduled_time=_T0 + timedelta(days=1), label=LABEL_RED_WIN),
        _row(match_key="m2", scheduled_time=_T0 + timedelta(days=1), label=LABEL_TIE),
        _row(match_key="m3", scheduled_time=_T0 + timedelta(days=1), label=LABEL_BLUE_WIN),
    ]
    train = [_row(match_key="m0", scheduled_time=_T0)]
    fold = _fold(label="f", train_rows=train, test_rows=rows)
    result = run_win_prob_backtest(_DummyModel, [fold])
    assert result.aggregate.row_count == 2  # the tie excluded
    assert result.aggregate.excluded_count == 1
    assert result.folds[0].excluded_count == 1


def test_run_win_prob_backtest_fits_a_fresh_model_per_fold():
    fold_a = _fold(
        label="a", train_rows=[_row(match_key="a0", scheduled_time=_T0)],
        test_rows=[_row(match_key="a1", scheduled_time=_T0 + timedelta(days=1))],
        split_strategy=SPLIT_WALK_FORWARD,
    )
    fold_b = _fold(
        label="b", train_rows=[_row(match_key="b0", scheduled_time=_T0 + timedelta(days=2))],
        test_rows=[_row(match_key="b1", scheduled_time=_T0 + timedelta(days=3))],
        split_strategy=SPLIT_WALK_FORWARD,
    )
    created_models: list[_DummyModel] = []

    def factory() -> _DummyModel:
        model = _DummyModel()
        created_models.append(model)
        return model

    run_win_prob_backtest(factory, [fold_a, fold_b])
    assert len(created_models) == 2
    assert [r.match_key for r in created_models[0].fit_calls[0]] == ["a0"]
    assert [r.match_key for r in created_models[1].fit_calls[0]] == ["b0"]


def test_run_win_prob_backtest_reports_per_fold_and_aggregate():
    fold = _fold(
        label="f1", train_rows=[_row(match_key="t", scheduled_time=_T0)],
        test_rows=[
            _row(match_key="m1", scheduled_time=_T0 + timedelta(days=1), label=LABEL_RED_WIN),
            _row(match_key="m2", scheduled_time=_T0 + timedelta(days=1), label=LABEL_BLUE_WIN),
        ],
    )
    result = run_win_prob_backtest(_DummyModel, [fold])
    assert len(result.folds) == 1
    assert result.folds[0].fold_label == "f1"
    assert result.aggregate.fold_label == "aggregate"
    assert result.aggregate.season is None  # pooled across (potentially many) seasons by construction


def test_run_win_prob_backtest_rejects_an_empty_fold_list():
    with pytest.raises(ValueError, match="at least one fold"):
        run_win_prob_backtest(_DummyModel, [])


def test_run_win_prob_backtest_rejects_mixed_split_strategies():
    hold_out_fold = _fold(
        label="a", train_rows=[_row(match_key="a0", scheduled_time=_T0)],
        test_rows=[_row(match_key="a1", scheduled_time=_T0 + timedelta(days=1))],
        split_strategy=SPLIT_HOLD_OUT_SEASON,
    )
    walk_forward_fold = _fold(
        label="b", train_rows=[_row(match_key="b0", scheduled_time=_T0 + timedelta(days=2))],
        test_rows=[_row(match_key="b1", scheduled_time=_T0 + timedelta(days=3))],
        split_strategy=SPLIT_WALK_FORWARD,
    )
    with pytest.raises(ValueError, match="mix split strategies"):
        run_win_prob_backtest(_DummyModel, [hold_out_fold, walk_forward_fold])


def test_run_win_prob_backtest_derives_split_strategy_from_folds():
    fold = _fold(
        label="f", train_rows=[_row(match_key="t", scheduled_time=_T0)],
        test_rows=[_row(match_key="m1", scheduled_time=_T0 + timedelta(days=1))],
        split_strategy=SPLIT_WALK_FORWARD,
    )
    result = run_win_prob_backtest(_DummyModel, [fold])
    assert result.split_strategy == SPLIT_WALK_FORWARD


# ---------------------------------------------------------------------------
# run_ranking_backtest
# ---------------------------------------------------------------------------


def test_run_ranking_backtest_hand_computed():
    # Team 1 (avg 90) should be predicted above team 2 (avg 50); real rank says team 1 is #1.
    test_rows = [
        _row(
            match_key="m1", scheduled_time=_T0 + timedelta(days=1),
            red_teams=[_team_features(1, average_score=90.0)], blue_teams=[_team_features(2, average_score=50.0)],
        ),
    ]
    fold = _fold(label="f", train_rows=[_row(match_key="t0", scheduled_time=_T0)], test_rows=test_rows)
    final_ranks = {"9970zzztest": {1: 1, 2: 2}}

    result = run_ranking_backtest(_DummyModel, [fold], final_ranks, top_k=2)
    assert result.mode == MODE_RANKING
    assert result.aggregate.row_count == 1  # one event scored
    assert result.aggregate.spearman == pytest.approx(1.0)
    assert result.aggregate.top_k_recall == pytest.approx(1.0)


def test_run_ranking_backtest_skips_events_with_no_ground_truth():
    test_rows = [_row(match_key="m1", event_key="no_ground_truth_event", scheduled_time=_T0 + timedelta(days=1))]
    fold = _fold(label="f", train_rows=[_row(match_key="t0", scheduled_time=_T0)], test_rows=test_rows)

    result = run_ranking_backtest(_DummyModel, [fold], final_ranks={})
    assert result.aggregate.row_count == 0
    assert result.aggregate.excluded_count == 1
    assert result.aggregate.spearman is None


def test_run_ranking_backtest_uses_each_teams_latest_seen_features_at_an_event():
    # Team 1 appears in two matches at the same event; its second (later)
    # average_score is the one predict_rating should be called with.
    test_rows = [
        _row(
            match_key="m1", scheduled_time=_T0 + timedelta(days=1),
            red_teams=[_team_features(1, average_score=10.0)], blue_teams=[_team_features(2, average_score=50.0)],
        ),
        _row(
            match_key="m2", scheduled_time=_T0 + timedelta(days=2),
            red_teams=[_team_features(1, average_score=99.0)], blue_teams=[_team_features(2, average_score=50.0)],
        ),
    ]
    fold = _fold(label="f", train_rows=[_row(match_key="t0", scheduled_time=_T0)], test_rows=test_rows)
    final_ranks = {"9970zzztest": {1: 1, 2: 2}}

    result = run_ranking_backtest(_DummyModel, [fold], final_ranks, top_k=2)
    # _DummyModel.predict_rating returns average_score verbatim; team 1's
    # latest snapshot (99.0) beats team 2 (50.0), matching the real rank
    # (team 1 = #1) -- if the STALE 10.0 snapshot had been used instead,
    # team 1 would have predicted below team 2 and spearman would be -1.0.
    assert result.aggregate.spearman == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# BacktestResult.summary()
# ---------------------------------------------------------------------------


def test_summary_is_mode_aware():
    fold = _fold(
        label="f", train_rows=[_row(match_key="t", scheduled_time=_T0)],
        test_rows=[_row(match_key="m1", scheduled_time=_T0 + timedelta(days=1))],
    )
    win_prob_summary = run_win_prob_backtest(_DummyModel, [fold]).summary()
    assert "accuracy=" in win_prob_summary
    assert "spearman=" not in win_prob_summary

    ranking_result = run_ranking_backtest(_DummyModel, [fold], final_ranks={})
    ranking_summary = ranking_result.summary()
    assert "spearman=" in ranking_summary
    assert "accuracy=" not in ranking_summary
