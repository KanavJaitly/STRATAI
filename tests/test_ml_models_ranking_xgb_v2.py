"""M5 v2 (decision D16 §1): attributed target, causal normalization, midpoint evaluation.

All synthetic. Nothing here touches held-out data.
"""

from __future__ import annotations

import itertools
import math
import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ml.backtest.ranking_midpoint import FIRST, LAST, MIDPOINT, decision_snapshots, evaluate_ranking
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, TeamFeatures
from ml.features.scale import MIN_ALLIANCE_SCORES, ScaleLookup, _Timeline
from ml.models.ranking_xgb_v2 import (
    FEATURE_NAMES_V2,
    RIDGE_LAMBDA,
    RankingXGBModelV2,
    event_contribution_targets,
    team_vector_v2,
)

T0 = datetime(9990, 3, 1, tzinfo=timezone.utc)


def tf(team: int, *, epa: float | None = None, avg: float | None = None, score_scale: float | None = None,
       epa_scale: float | None = None) -> TeamFeatures:
    has_epa = epa is not None
    return TeamFeatures(
        team_number=team, epa_total=epa, epa_total_present=has_epa, epa_auto=None, epa_auto_present=False,
        epa_teleop=None, epa_teleop_present=False, epa_endgame=None, epa_endgame_present=False,
        epa_source_event_key="9989zzzprior" if has_epa else None,
        epa_withheld_reason=None if has_epa else EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=avg, average_score_present=avg is not None, score_stddev_present=False,
        consistency_rating_present=False, reliability_score_present=False, matches_considered=4, matches_used=4,
        average_auto_points_present=False, auto_points_matches_used=0, defense_score_present=False,
        defense_agreement_present=False, defense_observation_count=0, feeding_score_present=False,
        feeding_agreement_present=False, feeding_observation_count=0,
        score_scale=score_scale, score_scale_present=score_scale is not None,
        epa_scale=epa_scale if has_epa else None, epa_scale_present=has_epa and epa_scale is not None,
    )


def row(i: int, event: str, red: list[int], blue: list[int], score_red: int, score_blue: int, *,
        level: str = "qualification", features=None) -> TrainingRow:
    label = LABEL_RED_WIN if score_red > score_blue else LABEL_BLUE_WIN if score_blue > score_red else LABEL_TIE
    make = features or (lambda t: tf(t))
    return TrainingRow(
        match_key=f"{event}_qm{i}", event_key=event, season=9990, comp_level=level, match_number=i,
        scheduled_time=T0 + timedelta(minutes=10 * i), label=label, score_margin=score_red - score_blue,
        score_red=score_red, score_blue=score_blue, red_teams=[make(t) for t in red], blue_teams=[make(t) for t in blue],
        dq_status_known=True,
    )


def _event(true: dict[int, float], event: str = "9990zzza") -> list[TrainingRow]:
    """Every 3-v-3 split of 6 teams, margins exactly the true contributions' difference."""
    teams = sorted(true)
    rows = []
    for i, red in enumerate(itertools.combinations(teams, 3)):
        blue = [t for t in teams if t not in red]
        base = 60
        rows.append(row(i, event, list(red), blue, base + round(sum(true[t] for t in red)),
                        base + round(sum(true[t] for t in blue))))
    return rows


def test_target_is_the_ridge_attribution_divided_by_the_event_sd() -> None:
    true = {1: 30, 2: 20, 3: 10, 4: 0, 5: -10, 6: -20}
    rows = _event(true)
    targets, excluded = event_contribution_targets(rows)
    teams = sorted(true)
    A = np.array([[1.0 if t in [x.team_number for x in r.red_teams] else -1.0 for t in teams] for r in rows])
    d = np.array([r.score_red - r.score_blue for r in rows], dtype=float)
    c = np.linalg.solve(A.T @ A + RIDGE_LAMBDA * np.eye(6), A.T @ d)
    sigma = statistics.pstdev([s for r in rows for s in (r.score_red, r.score_blue)])
    for k, team in enumerate(teams):
        assert targets[(team, "9990zzza")] == pytest.approx(c[k] / sigma, abs=1e-12)
    # attribution separates partners: the order of the true contributions is recovered
    assert sorted(teams, key=lambda t: -targets[(t, "9990zzza")]) == [1, 2, 3, 4, 5, 6]
    assert excluded == {"events_zero_sigma": 0, "team_events_below_min_matches": 0}
    # unlike v1, two partners on the same alliance get different values
    assert targets[(1, "9990zzza")] != targets[(2, "9990zzza")]


def test_target_exclusions_ties_and_playoffs() -> None:
    rows = _event({1: 30, 2: 20, 3: 10, 4: 0, 5: -10, 6: -20})
    rows.append(row(50, "9990zzza", [1, 2, 7], [3, 4, 5], 70, 70))  # team 7: one match, a tie
    rows.append(row(51, "9990zzza", [1, 2, 3], [4, 5, 6], 300, 0, level="semifinal"))  # playoffs are ignored
    targets, excluded = event_contribution_targets(rows)
    assert (7, "9990zzza") not in targets and excluded["team_events_below_min_matches"] == 1
    without_playoff, _ = event_contribution_targets(rows[:-1])
    assert targets == without_playoff
    flat = [row(i, "9990zzzb", [1, 2, 3], [4, 5, 6], 50, 50) for i in range(4)]
    targets, excluded = event_contribution_targets(flat)
    assert targets == {} and excluded["events_zero_sigma"] == 1


def test_feature_vector_normalizes_by_the_causal_scales() -> None:
    vector = team_vector_v2(tf(1, epa=40.0, avg=120.0, score_scale=60.0, epa_scale=20.0))
    named = dict(zip(FEATURE_NAMES_V2, vector))
    assert named["epa_total_norm"] == 2.0 and named["average_score_norm"] == 2.0
    missing = dict(zip(FEATURE_NAMES_V2, team_vector_v2(tf(1, epa=40.0, avg=120.0))))
    assert math.isnan(missing["epa_total_norm"]) and math.isnan(missing["average_score_norm"])  # no scale: absent
    assert missing["matches_used"] == 4.0


def test_timeline_scale_is_exact_strict_and_thresholded() -> None:
    rng = random.Random(1)
    rows = [(T0 + timedelta(minutes=i), rng.randint(0, 200), rng.randint(0, 200)) for i in range(400)]
    timeline = _Timeline(rows)
    t = T0 + timedelta(minutes=150)  # strictly before: matches 0..149
    expected = statistics.pstdev([s for _, a, b in rows[:150] for s in (a, b)])
    assert timeline.scale(t) == pytest.approx(expected, rel=1e-12)
    assert timeline.scale(T0 + timedelta(minutes=MIN_ALLIANCE_SCORES // 2 - 1)) is None  # 198 scores < 200
    assert timeline.scale(T0 + timedelta(minutes=MIN_ALLIANCE_SCORES // 2)) is not None
    assert timeline.scale(None) == pytest.approx(statistics.pstdev([s for _, a, b in rows for s in (a, b)]), rel=1e-12)


def test_epa_scale_uses_the_source_season(monkeypatch) -> None:
    lookup = ScaleLookup(database=None)  # type: ignore[arg-type]
    monkeypatch.setattr(lookup, "season_scale", lambda season, before: {9990: 50.0, 9989: 20.0}[season]
                        if before is not None or season == 9989 else 99.0)
    monkeypatch.setattr(lookup, "event_season", lambda key: {"9990x": 9990, "9989y": 9989}.get(key))
    assert lookup.feature_scales(9990, T0, "9990x") == (50.0, 50.0)  # same season: season-to-date
    assert lookup.feature_scales(9990, T0, "9989y") == (50.0, 20.0)  # earlier season: its full season
    assert lookup.feature_scales(9990, T0, None) == (50.0, None)


def test_midpoint_snapshot_rule() -> None:
    rows = [row(i, "9990zzzc", [1, 2, 3], [4, 5, 6], 60 + i, 50) for i in range(5)]
    rows.append(row(9, "9990zzzc", [1, 2, 3], [4, 5, 6], 99, 0, level="final"))
    snaps = decision_snapshots(rows, MIDPOINT)["9990zzzc"]
    assert snaps[1].n == 5 and snaps[1].k == 3 and snaps[1].match_key == "9990zzzc_qm2"  # ceil(5/2) = 3rd row
    assert decision_snapshots(rows, FIRST)["9990zzzc"][1].match_key == "9990zzzc_qm0"
    assert decision_snapshots(rows, LAST)["9990zzzc"][1].match_key == "9990zzzc_qm4"  # never the final
    four = decision_snapshots(rows[:4], MIDPOINT)["9990zzzc"][1]
    assert (four.n, four.k) == (4, 2)


def test_evaluation_scores_a_perfect_ordering_as_one() -> None:
    rows = [row(i, "9990zzzd", [1, 2, 3], [4, 5, 6], 60, 50,
                features=lambda t: tf(t, epa=float(10 - t), epa_scale=1.0)) for i in range(3)]
    ranks = {"9990zzzd": {t: t for t in range(1, 7)}}
    result = evaluate_ranking(lambda f: f.epa_total, decision_snapshots(rows, MIDPOINT), ranks)
    assert result.spearman == pytest.approx(1.0) and result.top_k_recall == 1.0 and result.events_scored == 1
    assert evaluate_ranking(lambda f: f.epa_total, decision_snapshots(rows, MIDPOINT), {}).events_skipped == 1


def _training_rows(seed: int = 3) -> list[TrainingRow]:
    rng = random.Random(seed)
    strength = {t: rng.uniform(-30, 30) for t in range(1, 25)}
    rows, i = [], 0
    for e in range(6):
        event = f"9990zzz{e}"
        for _ in range(40):
            teams = rng.sample(list(strength), 6)
            red, blue = teams[:3], teams[3:]
            make = lambda t: tf(t, epa=strength[t] + 40 + rng.gauss(0, 3), avg=100.0, score_scale=50.0,  # noqa: E731
                                epa_scale=20.0)
            score_red = 100 + round(sum(strength[t] for t in red) + rng.gauss(0, 10))
            score_blue = 100 + round(sum(strength[t] for t in blue) + rng.gauss(0, 10))
            rows.append(row(i, event, red, blue, score_red, score_blue, features=make))
            i += 1
    return rows


def test_fit_is_reproducible_and_round_trips(tmp_path: Path) -> None:
    rows = _training_rows()
    a, b = RankingXGBModelV2(), RankingXGBModelV2()
    a.fit(rows)
    b.fit(rows)
    probe = [t for r in rows[-20:] for t in (*r.red_teams, *r.blue_teams)]
    assert [a.predict_rating(t) for t in probe] == [b.predict_rating(t) for t in probe]
    assert a.labelled_team_events > 0 and a.fit_validation_sample_count > 0
    path = tmp_path / "m.json"
    a.save(path)
    loaded = RankingXGBModelV2.load(path)
    assert [loaded.predict_rating(t) for t in probe] == [a.predict_rating(t) for t in probe]
    path.write_text(path.read_text().replace('"epa_total_norm"', '"renamed"'))
    with pytest.raises(ValueError, match="feature list"):
        RankingXGBModelV2.load(path)


def test_fit_learns_the_synthetic_signal() -> None:
    rows = _training_rows()
    model = RankingXGBModelV2()
    model.fit(rows)
    high = model.predict_rating(tf(1, epa=90.0, avg=100.0, score_scale=50.0, epa_scale=20.0))
    low = model.predict_rating(tf(1, epa=5.0, avg=100.0, score_scale=50.0, epa_scale=20.0))
    assert high > low
    with pytest.raises(NotImplementedError):
        model.predict_win_prob(None)  # type: ignore[arg-type]
