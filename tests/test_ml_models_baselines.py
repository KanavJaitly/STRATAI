"""Phase 4 Milestone 4: locked naive baselines, ml.models.baselines.

Every TeamFeatures/TrainingRow value in this file is synthetic and
explicitly hand-constructed for unit testing -- none of it represents a
real match, a real team, or a real EPA value, and none of it is used to
produce, or stand in for, this milestone's actual required deliverable (a
real, dated backtest result on a real held-out season, recorded in
RUNNING_NOTES.md once real Statbotics EPA data is available again). This
file exists only to prove the model code itself is correct: the milestone's
three named tests (symmetry, reproducibility, monotonicity) plus protocol
conformance, missing-EPA handling, and save/load.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ml.backtest.harness import Model
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    MatchFeatureRow,
    TeamFeatures,
)
from ml.models.baselines import (
    BASELINE_VERSION,
    EpaWinProbBaseline,
    RawEpaRankingBaseline,
)


def _team_features(
    team_number: int, epa_total: float | None = None,
) -> TeamFeatures:
    """A synthetic team snapshot with only epa_total meaningfully set --
    every other optional field absent, matching the minimal-valid-construction
    pattern already used in tests/test_ml_backtest_harness.py."""
    return TeamFeatures(
        team_number=team_number,
        epa_total=epa_total, epa_total_present=epa_total is not None,
        epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key="9960zzzpriorevent" if epa_total is not None else None,
        epa_withheld_reason=None if epa_total is not None else EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score_present=False, score_stddev_present=False,
        consistency_rating_present=False, reliability_score_present=False,
        matches_considered=0, matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)


def _row(
    *, match_key: str, red_epas: list[float | None], blue_epas: list[float | None],
    label: str = LABEL_RED_WIN, scheduled_time: datetime = _T0,
) -> TrainingRow:
    """A synthetic labeled row with a red/blue alliance built from the given
    (possibly-missing) EPA values -- team numbers are assigned deterministically
    from the list position so tests can construct many rows tersely."""
    red_teams = [_team_features(9800 + i, epa) for i, epa in enumerate(red_epas)]
    blue_teams = [_team_features(9900 + i, epa) for i, epa in enumerate(blue_epas)]
    if label == LABEL_RED_WIN:
        score_red, score_blue = 100, 80
    elif label == LABEL_BLUE_WIN:
        score_red, score_blue = 80, 100
    else:
        score_red = score_blue = 90  # a genuine tie: equal scores, not just a "tie" label
    return TrainingRow(
        match_key=match_key, event_key="9960zzztest", season=9960, comp_level="qualification",
        set_number=None, match_number=1, scheduled_time=scheduled_time, label=label,
        score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
        red_teams=red_teams, blue_teams=blue_teams,
        red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
    )


def _match_features(red_epas: list[float | None], blue_epas: list[float | None]) -> MatchFeatureRow:
    return MatchFeatureRow(
        match_key="9960zzztest_qm1", as_of=_T0, event_key="9960zzztest", season=9960,
        red_teams=[_team_features(9800 + i, epa) for i, epa in enumerate(red_epas)],
        blue_teams=[_team_features(9900 + i, epa) for i, epa in enumerate(blue_epas)],
    )


# ---------------------------------------------------------------------------
# RawEpaRankingBaseline
# ---------------------------------------------------------------------------


def test_raw_epa_ranking_baseline_conforms_to_model_protocol():
    assert isinstance(RawEpaRankingBaseline(), Model)


def test_raw_epa_ranking_baseline_returns_epa_total_when_present():
    baseline = RawEpaRankingBaseline()
    assert baseline.predict_rating(_team_features(1, epa_total=42.5)) == 42.5


def test_raw_epa_ranking_baseline_returns_negative_infinity_when_absent():
    baseline = RawEpaRankingBaseline()
    assert baseline.predict_rating(_team_features(1, epa_total=None)) == float("-inf")


def test_raw_epa_ranking_baseline_missing_epa_never_outranks_a_measured_team():
    baseline = RawEpaRankingBaseline()
    measured = baseline.predict_rating(_team_features(1, epa_total=0.01))  # a genuinely tiny but real EPA
    unmeasured = baseline.predict_rating(_team_features(2, epa_total=None))
    assert unmeasured < measured


def test_raw_epa_ranking_baseline_fit_is_a_documented_noop():
    baseline = RawEpaRankingBaseline()
    before = baseline.predict_rating(_team_features(1, epa_total=10.0))
    baseline.fit([_row(match_key="m1", red_epas=[999.0], blue_epas=[999.0])])
    after = baseline.predict_rating(_team_features(1, epa_total=10.0))
    assert before == after == 10.0


def test_raw_epa_ranking_baseline_predict_win_prob_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        RawEpaRankingBaseline().predict_win_prob(_match_features([10.0], [5.0]))


def test_raw_epa_ranking_baseline_save_load_round_trip(tmp_path: Path):
    baseline = RawEpaRankingBaseline()
    path = tmp_path / "raw_epa.json"
    baseline.save(path)
    restored = RawEpaRankingBaseline.load(path)
    assert isinstance(restored, RawEpaRankingBaseline)
    assert restored.predict_rating(_team_features(1, epa_total=7.0)) == 7.0


def test_raw_epa_ranking_baseline_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "wrong.json"
    path.write_text('{"baseline": "something_else", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain"):
        RawEpaRankingBaseline.load(path)


# ---------------------------------------------------------------------------
# EpaWinProbBaseline
# ---------------------------------------------------------------------------


def test_epa_win_prob_baseline_conforms_to_model_protocol():
    assert isinstance(EpaWinProbBaseline(), Model)


def test_epa_win_prob_baseline_predict_rating_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        EpaWinProbBaseline().predict_rating(_team_features(1, epa_total=10.0))


def test_epa_win_prob_baseline_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="before fit"):
        EpaWinProbBaseline().predict_win_prob(_match_features([10.0], [5.0]))


def test_epa_win_prob_baseline_fit_raises_with_zero_eligible_rows():
    baseline = EpaWinProbBaseline()
    rows = [
        _row(match_key="m1", red_epas=[10.0], blue_epas=[5.0], label=LABEL_TIE),  # tie excluded
        _row(match_key="m2", red_epas=[None], blue_epas=[5.0]),  # missing EPA excluded
    ]
    with pytest.raises(ValueError, match="zero rows"):
        baseline.fit(rows)


def test_epa_win_prob_baseline_fit_excludes_ties_and_missing_epa_and_counts_them():
    baseline = EpaWinProbBaseline()
    rows = [
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
        _row(match_key="m3", red_epas=[15.0], blue_epas=[15.0], label=LABEL_TIE),  # excluded: tie
        _row(match_key="m4", red_epas=[None], blue_epas=[15.0], label=LABEL_RED_WIN),  # excluded: missing EPA
    ]
    baseline.fit(rows)
    assert baseline.fit_row_count == 2
    assert baseline.fit_excluded_count == 2


def test_epa_win_prob_baseline_predict_raises_on_missing_epa():
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
    ])
    with pytest.raises(ValueError, match="EPA is incomplete"):
        baseline.predict_win_prob(_match_features([10.0], [None]))


def test_epa_win_prob_baseline_predict_raises_on_empty_alliance():
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
    ])
    with pytest.raises(ValueError, match="EPA is incomplete"):
        baseline.predict_win_prob(_match_features([], [10.0]))


def test_epa_win_prob_baseline_symmetry_swap_red_blue_gives_p_and_one_minus_p():
    # The milestone's own named test. Holds structurally for any fitted
    # scale, not just a specific one -- fit on a real, non-degenerate,
    # non-perfectly-separable dataset to get a genuine (not the k=0 default) scale.
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
        _row(match_key="m3", red_epas=[20.0], blue_epas=[10.0], label=LABEL_BLUE_WIN),  # keeps it non-separable
        _row(match_key="m4", red_epas=[10.0], blue_epas=[20.0], label=LABEL_RED_WIN),
    ])

    original = _match_features([25.0, 30.0], [10.0, 15.0])
    swapped = _match_features([10.0, 15.0], [25.0, 30.0])

    p_original = baseline.predict_win_prob(original)
    p_swapped = baseline.predict_win_prob(swapped)
    assert p_swapped == pytest.approx(1.0 - p_original, abs=1e-12)


def test_epa_win_prob_baseline_symmetry_holds_even_at_the_default_unfit_leaning_scale():
    # Symmetry is a property of the formula itself, not of any particular
    # fitted value -- exercised again with a small, deliberately
    # non-representative fit to show it is not an artifact of one dataset.
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[5.0], blue_epas=[5.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[5.0], blue_epas=[5.0], label=LABEL_BLUE_WIN),
    ])
    original = _match_features([50.0], [1.0])
    swapped = _match_features([1.0], [50.0])
    assert baseline.predict_win_prob(swapped) == pytest.approx(1.0 - baseline.predict_win_prob(original), abs=1e-12)


def test_epa_win_prob_baseline_reproducibility_same_data_gives_identical_scale():
    rows = [
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
        _row(match_key="m3", red_epas=[20.0], blue_epas=[10.0], label=LABEL_BLUE_WIN),
        _row(match_key="m4", red_epas=[10.0], blue_epas=[20.0], label=LABEL_RED_WIN),
    ]
    baseline_a = EpaWinProbBaseline()
    baseline_a.fit(list(rows))
    baseline_b = EpaWinProbBaseline()
    baseline_b.fit(list(rows))

    assert baseline_a._scale == pytest.approx(baseline_b._scale, abs=1e-15)
    match = _match_features([25.0], [10.0])
    assert baseline_a.predict_win_prob(match) == pytest.approx(baseline_b.predict_win_prob(match), abs=1e-15)


def test_epa_win_prob_baseline_fit_converges_to_near_zero_for_symmetric_no_signal_data():
    # Hand-verifiable case: at each EPA-difference magnitude, outcomes split
    # evenly, so there is no real signal and the maximum-likelihood scale
    # must be (near) 0 -- a model that always predicts ~50/50 regardless of
    # the (uninformative) EPA gap.
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[20.0], blue_epas=[10.0], label=LABEL_BLUE_WIN),
        _row(match_key="m3", red_epas=[10.0], blue_epas=[20.0], label=LABEL_RED_WIN),
        _row(match_key="m4", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
    ])
    assert baseline._scale == pytest.approx(0.0, abs=1e-8)
    assert baseline.predict_win_prob(_match_features([50.0], [1.0])) == pytest.approx(0.5, abs=1e-6)


def test_epa_win_prob_baseline_monotonic_in_epa_difference():
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[30.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[30.0], label=LABEL_BLUE_WIN),
        _row(match_key="m3", red_epas=[15.0], blue_epas=[14.0], label=LABEL_BLUE_WIN),  # one exception -- avoids
        _row(match_key="m4", red_epas=[14.0], blue_epas=[15.0], label=LABEL_RED_WIN),   # perfect separation
    ])
    diffs = [-20.0, -5.0, 0.0, 5.0, 20.0]
    probabilities = [baseline.predict_win_prob(_match_features([10.0 + d], [10.0])) for d in diffs]
    assert probabilities == sorted(probabilities)
    assert probabilities[0] < probabilities[-1]


def test_epa_win_prob_baseline_save_load_round_trip(tmp_path: Path):
    baseline = EpaWinProbBaseline()
    baseline.fit([
        _row(match_key="m1", red_epas=[20.0], blue_epas=[10.0], label=LABEL_RED_WIN),
        _row(match_key="m2", red_epas=[10.0], blue_epas=[20.0], label=LABEL_BLUE_WIN),
    ])
    path = tmp_path / "epa_win_prob.json"
    baseline.save(path)

    restored = EpaWinProbBaseline.load(path)
    assert isinstance(restored, EpaWinProbBaseline)
    assert restored._scale == pytest.approx(baseline._scale)
    assert restored.fit_row_count == baseline.fit_row_count
    match = _match_features([25.0], [10.0])
    assert restored.predict_win_prob(match) == pytest.approx(baseline.predict_win_prob(match))


def test_epa_win_prob_baseline_save_before_fit_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="unfit"):
        EpaWinProbBaseline().save(tmp_path / "never_written.json")


def test_epa_win_prob_baseline_load_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "wrong.json"
    path.write_text('{"baseline": "raw_epa_ranking", "version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not contain"):
        EpaWinProbBaseline.load(path)


def test_baseline_version_is_a_real_string():
    assert isinstance(BASELINE_VERSION, str) and BASELINE_VERSION
