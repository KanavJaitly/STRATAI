"""Hand-calculated EPA arithmetic (spec §3-§5).

Each expected value is derived in the comment beside it from the formulas in
docs/ratings/epa_specification.md, not from the engine's code. The only
values taken from a calculator are exponentials and logarithms, written out
to full precision.
"""

from __future__ import annotations

import math

import pytest

from ml.ratings.epa import exclusions as ex
from ml.ratings.epa.constants import AUTO, COMP_0, ENDGAME, NO_FOUL, RP_1, RP_2, RP_3, TELEOP, TIEBREAKER
from ml.ratings.epa.engine import EpaEngine
from ml.ratings.epa.initialization import INIT_EPA, initial_rating, mean_reversion_for, prior_team_years
from ml.ratings.epa.inputs import PriorSeasonInput, PriorTeamYear, SeasonInput
from ml.ratings.epa.math import inv_unit_sigmoid, percent, unit_sigmoid, win_probability
from ml.ratings.epa.validation import prepare_season
from ml.ratings.epa.year_stats import YearStats, compute_year_stats
from ratings_epa_support import alliance, bd2024, bd2025, event, match

import numpy as np

approx = lambda x: pytest.approx(x, rel=1e-12, abs=1e-12)  # noqa: E731

SIGMOID_0 = 0.11920292202211755  # 1 / (1 + e^2) = unit_sigmoid(0)
INV_SIGMOID_025 = 0.22534692783297255  # 0.5 + ln(0.25 / 0.75) / 4
INV_SIGMOID_EPS = -2.9538773894909434  # 0.5 + ln(1e-6 / (1 - 1e-6)) / 4


def stats_2024(**overrides: object) -> YearStats:
    base = dict(
        season=2024, week_one_matches=10, score_mean=66.0, score_sd=30.0, no_foul_mean=60.0, foul_mean=6.0,
        auto_mean=15.0, teleop_mean=30.0, endgame_mean=15.0, rp_1_mean=0.25, rp_2_mean=0.0, rp_3_mean=0.0,
        tiebreaker_mean=0.2, comp_means=(6.0, 9.0, 24.0, 30.0, 1.5, 0.9, 6.0, 1.2, 0.6, 0.3),
    )
    return YearStats(**{**base, **overrides})  # type: ignore[arg-type]


# --- constants and helper curves --------------------------------------------


def test_init_epa_is_1450() -> None:
    assert INIT_EPA == 1450  # 1500 - 0.2 * 250


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, 1 / 3),  # 0.5 - (0.2/6)(0-6) = 0.7 -> clamp 0.5 -> * 2/3
        (6, 1 / 3),  # 0.5 exactly
        (9, 0.4 * 2 / 3),  # 0.5 - 0.1
        (12, 0.2),  # 0.5 - 0.2 = 0.3, the floor
        (40, 0.2),
    ],
)
def test_percent(n: int, expected: float) -> None:
    assert percent(n) == approx(expected)


def test_sigmoids() -> None:
    assert unit_sigmoid(0.5) == 0.5
    assert unit_sigmoid(0.0) == approx(SIGMOID_0)
    assert inv_unit_sigmoid(0.25) == approx(INV_SIGMOID_025)
    assert inv_unit_sigmoid(unit_sigmoid(0.3)) == approx(0.3)


def test_win_probability() -> None:
    assert win_probability(30.0, 30.0, 30.0) == 0.5
    # 1 / (1 + 10^(-5/8 * 10/30)) = 1 / (1 + 10^-0.2083333)
    assert win_probability(60.0, 50.0, 30.0) == approx(0.617678266169229)
    assert win_probability(50.0, 60.0, 30.0) == approx(1 - 0.617678266169229)


# --- initialization ----------------------------------------------------------


def test_initial_rating_without_prior() -> None:
    """z = (1450 - 1500) / 250 = -0.2; sd_frac = 30 / 60 = 0.5; start = mean/3 + mean*0.5*z."""
    start = initial_rating(stats_2024(), None, None, 0.4)
    assert start[NO_FOUL] == approx(14.0)  # 60/3 - 0.2*30
    assert start[AUTO] == approx(3.5)  # 5 - 0.2*7.5
    assert start[TELEOP] == approx(7.0)  # 10 - 0.2*15
    assert start[ENDGAME] == approx(3.5)
    # rp: mean replaced by inv_sigmoid(rate) AFTER sd was taken from the raw rate
    assert start[RP_1] == approx(INV_SIGMOID_025 / 3 - 0.2 * 0.125)
    assert start[RP_2] == approx(-1 / 3)  # inv_sigmoid(EPS) = -2.95 -> floored at -1; sd 0
    assert start[RP_3] == approx(-1 / 3)
    assert start[TIEBREAKER] == approx(0.2 / 3 - 0.2 * 0.1)
    assert start[COMP_0] == approx(2.0 - 0.2 * 3.0)
    assert INV_SIGMOID_EPS < -1


def test_initial_rating_with_two_prior_seasons() -> None:
    # prev = 0.7*1700 + 0.3*1600 = 1670; curr = 0.6*1670 + 0.4*1450 = 1582; z = 82/250 = 0.328
    start = initial_rating(stats_2024(), PriorTeamYear(season=2023, norm_epa=1700),
                           PriorTeamYear(season=2022, norm_epa=1600), 0.4)
    assert start[NO_FOUL] == approx(20 + 30 * 0.328)  # 29.84


def test_initial_rating_with_one_prior_season() -> None:
    # missing second year counts as 1450: prev = 1190 + 435 = 1625; curr = 975 + 580 = 1555; z = 0.22
    start = initial_rating(stats_2024(), PriorTeamYear(season=2023, norm_epa=1700), None, 0.4)
    assert start[NO_FOUL] == approx(26.6)


def test_initial_rating_prior_team_year_without_a_value() -> None:
    with_none = initial_rating(stats_2024(), PriorTeamYear(season=2023, norm_epa=None), None, 0.4)
    assert with_none[NO_FOUL] == approx(14.0)


def test_isr_mean_reversion_is_zero() -> None:
    # 2026 isr: curr = prev = 1670 -> z = 0.68 -> 20 + 30*0.68 = 40.4
    stats = stats_2024(season=2026)
    start = initial_rating(stats, PriorTeamYear(season=2025, norm_epa=1700), PriorTeamYear(season=2024, norm_epa=1600),
                           mean_reversion_for(2026, 5635, {5635: "isr"}))
    assert start[NO_FOUL] == approx(40.4)
    assert mean_reversion_for(2026, 1, {5635: "isr"}) == 0.4
    assert mean_reversion_for(2025, 5635, {5635: "isr"}) == 0.4


def test_starting_total_is_clamped_at_zero() -> None:
    # prev = 1000; curr = 600 + 580 = 1180; z = -1.28 < -60/3/30 = -2/3, so z = -2/3 and total = 0
    start = initial_rating(stats_2024(), PriorTeamYear(season=2023, norm_epa=1000),
                           PriorTeamYear(season=2022, norm_epa=1000), 0.4)
    assert start[NO_FOUL] == pytest.approx(0.0, abs=1e-12)
    assert start[AUTO] == pytest.approx(0.0, abs=1e-12)
    assert start[RP_1] == approx(INV_SIGMOID_025 / 3 - (2 / 3) * 0.125)  # rp is not clamped


def test_prior_window_takes_two_most_recent_of_the_last_four_seasons() -> None:
    prior = PriorSeasonInput(source="test", team_years={
        1: (PriorTeamYear(season=2021, norm_epa=1000), PriorTeamYear(season=2022, norm_epa=1600),
            PriorTeamYear(season=2019, norm_epa=1900), PriorTeamYear(season=2023, norm_epa=1700)),
    })
    first, second = prior_team_years(prior, 1, 2024)
    assert (first.season, second.season) == (2023, 2022)  # type: ignore[union-attr]
    only_old = PriorSeasonInput(source="test", team_years={1: (PriorTeamYear(season=2019, norm_epa=1900),)})
    assert prior_team_years(only_old, 1, 2024) == (None, None)  # 2019 is outside Y-4..Y-1
    assert prior_team_years(None, 1, 2024) == (None, None)


# --- year statistics --------------------------------------------------------


def test_year_stats_from_week_one() -> None:
    m1_red = bd2024(leave=4, teleop_speaker=11, park=1, on_stage=3, coop=True)  # 4 + 22 + 4 = 30
    m1_blue = bd2024(leave=2, auto_speaker=1, teleop_speaker=8, park=1, on_stage=3)  # 7 + 16 + 4 = 27
    m2_red = bd2024(teleop_speaker=15, park=2, on_stage=3, foul=5, melody=True)  # 30 + 5 + 5 fouls = 40
    later = bd2024(teleop_speaker=40)
    season = SeasonInput(
        season=2024,
        events=(event("2024wk1", week=0), event("2024wk2", week=1)),
        matches=(
            match("2024wk1_qm1", "2024wk1", 100, alliance(2024, (1, 2, 3), m1_red), alliance(2024, (4, 5, 6), m1_blue)),
            match("2024wk1_qm2", "2024wk1", 200, alliance(2024, (1, 5, 3), m2_red), alliance(2024, (4, 2, 6), None, score=0)),
            match("2024wk1_qm3", "2024wk1", 300, alliance(2024, (1, 2, 3), None, score=-1),
                  alliance(2024, (4, 5, 6), None, score=-1)),
            match("2024wk2_qm1", "2024wk2", 900, alliance(2024, (1, 2, 3), later), alliance(2024, (4, 5, 6), later)),
        ),
    )
    stats = compute_year_stats(2024, prepare_season(season).stream)
    assert stats.week_one_matches == 2  # the upcoming match and the week-2 match are excluded
    # scores 30, 40, 27, 0: mean 24.25; sample sd sqrt(876.75 / 3) = 17.0953 -> r() 17.1
    assert (stats.score_mean, stats.score_sd) == (24.25, 17.1)
    # the empty alliance's components are None and excluded: no-foul 30, 35, 27
    assert stats.no_foul_mean == 30.67
    assert stats.foul_mean == 1.67  # 0, 5, 0
    assert (stats.auto_mean, stats.teleop_mean, stats.endgame_mean) == (3.67, 22.67, 4.33)  # (4,0,7) (22,30,16) (4,5,4)
    # rp values of the empty alliance are False, not None, so they count: melody F, T, F, F
    assert stats.rp_1_mean == 0.25
    assert stats.rp_3_mean == 0  # 2024 has no rp_3: None x3, plus the empty alliance's False
    assert stats.tiebreaker_mean == 0.33  # coop 1, 0, 0 (empty: None)
    assert stats.comp_means[0] == 2.0  # leave 4, 0, 2
    assert stats.foul_rate() == approx(1.67 / 30.67)


def test_year_stats_2025_revalues_processor_algae() -> None:
    a = bd2025(processor=2)  # 12 points
    b = bd2025(processor=4)  # 24 points
    season = SeasonInput(season=2025, events=(event("2025wk1"),), matches=(
        match("2025wk1_qm1", "2025wk1", 100, alliance(2025, (1, 2, 3), a), alliance(2025, (4, 5, 6), b)),
    ))
    stats = compute_year_stats(2025, prepare_season(season).stream)
    # comp_6 (processor count) mean 3 -> subtract 3*3 = 9 from no-foul, teleop and processor points
    assert stats.comp_means[6] == 3.0
    assert stats.no_foul_mean == 18.0 - 9
    assert stats.teleop_mean == 18.0 - 9
    assert stats.comp_means[7] == 18.0 - 9
    assert stats.score_sd == 8.49  # sd(12, 24) = 8.4853


def test_no_week_one_data_rejects_the_run() -> None:
    season = SeasonInput(season=2024, events=(event("2024wk2", week=1),), matches=(
        match("2024wk2_qm1", "2024wk2", 100, alliance(2024, (1, 2, 3), bd2024(leave=2)),
              alliance(2024, (4, 5, 6), bd2024(leave=4))),
    ))
    with pytest.raises(ex.RunRejected) as info:
        compute_year_stats(2024, prepare_season(season).stream)
    assert info.value.code == ex.NO_WEEK_ONE_DATA


# --- one match, by hand -----------------------------------------------------


def _uniform_ratings(teams: range, **values: float) -> dict[int, np.ndarray]:
    index = {"total": NO_FOUL, "auto": AUTO, "teleop": TELEOP, "endgame": ENDGAME, "comp_6": COMP_0 + 6}
    out = {}
    for team in teams:
        v = np.zeros(18)
        for name, value in values.items():
            v[index[name]] = value
        out[team] = v
    return out


def _stream(season: int, *matches) -> tuple:
    events = tuple(event(k) for k in sorted({m.event_key for m in matches}))
    return prepare_season(SeasonInput(season=season, events=events, matches=matches)).stream


RED_45 = bd2024(leave=6, auto_speaker=2, teleop_speaker=10, on_stage=9)  # auto 16, teleop 20, endgame 9
BLUE_24 = bd2024(teleop_speaker=12)  # teleop 24


def test_2024_qualification_update_by_hand() -> None:
    stream = _stream(2024, match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 3), RED_45),
                                 alliance(2024, (4, 5, 6), BLUE_24)))
    engine = EpaEngine(stats_2024(), _uniform_ratings(range(1, 7), total=10, auto=3, teleop=5, endgame=2))
    record = engine.process(stream[0])

    # prediction: each alliance sums to 30, so an even match
    assert (record.red_score, record.blue_score, record.win_prob) == (30.0, 30.0, 0.5)
    assert record.red_score_with_fouls == approx(30 * (1 + 6 / 60))  # foul rate 0.1 -> 33
    assert record.red_rps[0] == approx(SIGMOID_0)  # rp ratings sum to 0 -> sigmoid(0)
    assert record.red_rps[2] == 0  # 2024 has no rp_3 prediction

    # red: err = actual - pred, split three ways; attrib = epa + err/3; new = 2/3 epa + 1/3 attrib (N = 0)
    red = engine.rating(1)
    assert red[NO_FOUL] == approx(35 / 3)  # err 15 -> 5 -> attrib 15 -> 20/3 + 5
    assert red[AUTO] == approx(34 / 9)  # err 7 -> attrib 3 + 7/3 = 16/3 -> 2 + 16/9
    assert red[TELEOP] == approx(50 / 9)  # err 5 -> attrib 20/3 -> 10/3 + 20/9
    assert red[ENDGAME] == approx(7 / 3)  # err 3 -> attrib 3 -> 4/3 + 1
    assert red[RP_1] == approx(-SIGMOID_0 / 9)  # actual 0 - pred sigmoid(0), /3, then * 1/3
    assert red[COMP_0] == approx(2 / 3)  # leave 6 -> attrib 2 -> 2/3
    assert red[COMP_0 + 3] == approx(10 / 3)  # speaker points 10 + 20 = 30 -> 10 -> 10/3
    # blue: err -6 -> -2 -> attrib 8 -> 20/3 + 8/3
    blue = engine.rating(4)
    assert blue[NO_FOUL] == approx(28 / 3)
    assert blue[AUTO] == approx(2.0)  # err -9 -> -3 -> attrib 0 -> 2 + 0
    assert blue[TELEOP] == approx(6.0)  # err 9 -> 3 -> attrib 8 -> 10/3 + 8/3
    assert engine.qual_count(1) == engine.qual_count(4) == 1
    # the record holds the unchanged pre-match ratings
    assert record.pre[1][NO_FOUL] == 10.0 and record.post[1][NO_FOUL] == approx(35 / 3)  # type: ignore[index]


def test_2024_elimination_update_by_hand() -> None:
    stream = _stream(
        2024,
        match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 3), RED_45), alliance(2024, (4, 5, 6), BLUE_24)),
        match("2024e_sf1m1", "2024e", 200, alliance(2024, (1, 2, 3), RED_45), alliance(2024, (4, 5, 6), BLUE_24),
              level="sf"),
    )
    engine = EpaEngine(stats_2024(), _uniform_ratings(range(1, 7), total=10, auto=3, teleop=5, endgame=2))
    engine.process(stream[0])
    rp_before = engine.rating(1)[RP_1]
    record = engine.process(stream[1])
    # red 3 * 35/3 = 35 vs blue 3 * 28/3 = 28: 1 / (1 + 10^(-5/8 * 7/30))
    assert record.win_prob == approx(0.5831683920478329)
    # err 45 - 35 = 10 -> attrib 35/3 + 10/3 = 15; new = 2/3 * 35/3 + 1/3 * 15 = 115/9 (N = 1, p = 1/3)
    # elim weight 1/3: 1/3 * 115/9 + 2/3 * 35/3 = 325/27
    assert engine.rating(1)[NO_FOUL] == approx(325 / 27)
    # ranking points are frozen in playoffs by attrib = epa, so the update is
    # (1-p)*epa + p*epa: equal in exact arithmetic, but not bit-for-bit in
    # floating point. The reference does the same arithmetic, so the value may
    # move by an ulp; it is reproduced, not special-cased.
    assert engine.rating(1)[RP_1] == pytest.approx(rp_before, rel=1e-15)
    assert engine.qual_count(1) == 1  # playoff matches do not advance the step-size count


def test_2025_processor_algae_attribution_by_hand() -> None:
    red_bd = bd2025(processor=6)  # teleop 36, comp_6 6, comp_7 36
    blue_bd = bd2025(net=3)  # teleop 12, comp_8 12
    stream = _stream(2025, match("2025e_qm1", "2025e", 100, alliance(2025, (1, 2, 3), red_bd),
                                 alliance(2025, (4, 5, 6), blue_bd)))
    stats = stats_2024(season=2025, rp_3_mean=0.0)
    engine = EpaEngine(stats, _uniform_ratings(range(1, 7), comp_6=1.0))
    record = engine.process(stream[0])
    # prediction: each side sums processor algae 3, both sides 6 -> +3*6 = 18 teleop and total
    assert record.red_score == approx(18.0) and record.blue_score == approx(18.0)
    red = engine.rating(1)
    # red err /3: total 6, teleop 6, comp_6 1, comp_7 (36 - 9)/3 = 9, comp_8 (0 - 9)/3 = -3
    # revalue: 3 * err[comp_6] = 3 is removed from comp_7, teleop and total -> 6, 3, 3
    # attrib = epa + err: total 3, teleop 3, comp_6 2, comp_7 6, comp_8 -3; new = 2/3 epa + 1/3 attrib
    assert red[NO_FOUL] == approx(1.0)
    assert red[TELEOP] == approx(1.0)
    assert red[COMP_0 + 6] == approx(4 / 3)
    assert red[COMP_0 + 7] == approx(2.0)
    assert red[COMP_0 + 8] == approx(-1.0)
    blue = engine.rating(4)
    # blue err /3: total -2, teleop -2, comp_6 -1, comp_7 -3, comp_8 1; revalue +3 -> total 1, teleop 1, comp_7 0
    assert blue[NO_FOUL] == approx(1 / 3)
    assert blue[TELEOP] == approx(1 / 3)
    assert blue[COMP_0 + 6] == approx(2 / 3)
    assert blue[COMP_0 + 7] == approx(0.0)
    assert blue[COMP_0 + 8] == approx(1 / 3)
    assert record.red_rps[2] == approx(SIGMOID_0)  # 2025 has an rp_3 prediction


def test_skipped_match_is_predicted_but_not_updated() -> None:
    stream = _stream(2024, match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 9975), RED_45),
                                 alliance(2024, (4, 5, 6), BLUE_24)))
    assert stream[0].skip_code == ex.SKIP_PLACEHOLDER
    ratings = _uniform_ratings(range(1, 7), total=10)
    ratings[9975] = np.zeros(18)
    engine = EpaEngine(stats_2024(), ratings)
    record = engine.process(stream[0])
    assert record.status == ex.SKIP_PLACEHOLDER
    assert record.red_score == 20.0  # still predicted
    assert record.post == record.pre
    assert engine.qual_count(1) == 0


def test_upcoming_match_is_predicted_with_no_post_ratings() -> None:
    stream = _stream(2024, match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 3), None, score=-1),
                                 alliance(2024, (4, 5, 6), None, score=None)))
    engine = EpaEngine(stats_2024(), _uniform_ratings(range(1, 7), total=10))
    record = engine.process(stream[0])
    assert record.status == ex.UPCOMING and record.post is None and record.win_prob == 0.5
    assert engine.rating(1)[NO_FOUL] == 10.0


def test_reference_rounded_record() -> None:
    stream = _stream(2024, match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 3), RED_45),
                                 alliance(2024, (4, 5, 6), BLUE_24)))
    engine = EpaEngine(stats_2024(), _uniform_ratings(range(1, 7), total=10, auto=3, teleop=5, endgame=2))
    rounded = engine.process(stream[0]).reference_rounded(2024)
    assert rounded["epa_win_prob"] == 0.5 and rounded["epa_winner"] == "red"  # >= 0.5 is red
    assert rounded["epa_red_score_pred"] == 33.0
    assert rounded["epa_red_rp_1_pred"] == 0.1192  # r(0.11920..., 4)
    assert "epa_red_rp_3_pred" not in rounded  # only from 2025
    assert rounded["epas"]["1"]["epa"] == 11.67  # np.round(35/3, 2)
    assert rounded["epas"]["1"]["rp_1_epa"] == round(-SIGMOID_0 / 9, 4)  # -0.0132
    assert rounded["pre_epas"]["1"]["epa"] == 10.0


def test_engine_refuses_out_of_order_matches() -> None:
    stream = _stream(
        2024,
        match("2024e_qm1", "2024e", 100, alliance(2024, (1, 2, 3), RED_45), alliance(2024, (4, 5, 6), BLUE_24)),
        match("2024e_qm2", "2024e", 200, alliance(2024, (1, 2, 3), RED_45), alliance(2024, (4, 5, 6), BLUE_24)),
    )
    engine = EpaEngine(stats_2024(), _uniform_ratings(range(1, 7), total=10))
    engine.process(stream[1])
    with pytest.raises(ValueError, match="is not after"):
        engine.process(stream[0])
    with pytest.raises(ValueError, match="is not after"):
        engine.process(stream[1])  # the same match twice


def test_math_constants_are_exact() -> None:
    assert math.isclose(SIGMOID_0, 1 / (1 + math.exp(2)), rel_tol=0, abs_tol=0)
