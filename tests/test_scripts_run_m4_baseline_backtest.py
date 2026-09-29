"""Pure-logic tests for scripts/run_m4_baseline_backtest.py's own helper
functions -- _team_epa_complete and _split_epa_complete.

Every TrainingRow/TeamFeatures value here is synthetic, hand-built for unit
testing only, exactly as in tests/test_ml_models_baselines.py -- this proves
the script's own filtering logic is correct, not that any real backtest
number exists yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ml.backtest.harness import SPLIT_HOLD_OUT_SEASON, Fold
from ml.dataset.builder import LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from scripts.run_m4_baseline_backtest import _split_epa_complete, _team_epa_complete

_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _team_features(team_number: int, epa_total: float | None) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total=epa_total, epa_total_present=epa_total is not None,
        epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key="9950zzzprior" if epa_total is not None else None,
        epa_withheld_reason=None if epa_total is not None else EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score_present=False, score_stddev_present=False,
        consistency_rating_present=False, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        average_auto_points_present=False, auto_points_matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _row(
    match_key: str, red_epas: list[float | None], blue_epas: list[float | None],
    scheduled_time: datetime = _T0,
) -> TrainingRow:
    return TrainingRow(
        match_key=match_key, event_key="9950zzztest", season=9950, comp_level="qualification",
        set_number=None, match_number=1, scheduled_time=scheduled_time, label=LABEL_RED_WIN,
        score_margin=20, score_red=100, score_blue=80,
        red_teams=[_team_features(9700 + i, epa) for i, epa in enumerate(red_epas)],
        blue_teams=[_team_features(9800 + i, epa) for i, epa in enumerate(blue_epas)],
        red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
    )


def test_team_epa_complete_true_when_every_team_has_epa():
    row = _row("m1", red_epas=[10.0, 20.0], blue_epas=[15.0])
    assert _team_epa_complete(row) is True


def test_team_epa_complete_false_when_any_team_missing_epa():
    row = _row("m1", red_epas=[10.0, None], blue_epas=[15.0])
    assert _team_epa_complete(row) is False


def test_team_epa_complete_false_for_an_empty_alliance():
    row = _row("m1", red_epas=[], blue_epas=[15.0])
    assert _team_epa_complete(row) is False


def test_split_epa_complete_filters_and_counts_both_sides():
    fold = Fold(
        label="f",
        train_rows=[
            _row("t1", red_epas=[10.0], blue_epas=[15.0]),
            _row("t2", red_epas=[10.0], blue_epas=[None]),  # excluded
        ],
        test_rows=[
            _row("m1", red_epas=[10.0], blue_epas=[15.0], scheduled_time=_T0 + timedelta(days=1)),
            _row("m2", red_epas=[None], blue_epas=[15.0], scheduled_time=_T0 + timedelta(days=1)),  # excluded
            _row("m3", red_epas=[10.0], blue_epas=[15.0], scheduled_time=_T0 + timedelta(days=1)),
        ],
        split_strategy=SPLIT_HOLD_OUT_SEASON,
    )
    eligible_fold, train_excluded, test_excluded = _split_epa_complete(fold)
    assert [r.match_key for r in eligible_fold.train_rows] == ["t1"]
    assert [r.match_key for r in eligible_fold.test_rows] == ["m1", "m3"]
    assert train_excluded == 1
    assert test_excluded == 1
