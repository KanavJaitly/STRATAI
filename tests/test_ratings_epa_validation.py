"""Validation, filtering, rejection and the exclusion report (data contract §4-§5)."""

from __future__ import annotations

import pytest

from ml.ratings.epa import exclusions as ex
from ml.ratings.epa import run_season
from ml.ratings.epa.inputs import PriorSeasonInput, PriorTeamYear, SeasonInput
from ml.ratings.epa.validation import adjusted_week, prepare_season
from ratings_epa_support import alliance, bd2024, event, match

WK1 = "2024wk1"


def _m(key: str, time: int | None, red=(1, 2, 3), blue=(4, 5, 6), *, red_bd=None, blue_bd=None,
       red_score=None, blue_score=None, level="qm", event_key=WK1, red_dq=(), blue_dq=()):
    red_bd = bd2024(teleop_speaker=10) if red_bd is None and red_score is None else red_bd
    blue_bd = bd2024(teleop_speaker=8) if blue_bd is None and blue_score is None else blue_bd
    return match(key, event_key, time, alliance(2024, red, red_bd, score=red_score, dq=red_dq),
                 alliance(2024, blue, blue_bd, score=blue_score, dq=blue_dq), level=level)


def _season(*matches, events=(event(WK1),), **kwargs) -> SeasonInput:
    return SeasonInput(season=2024, events=events, matches=matches, **kwargs)


def _codes(prepared) -> dict[str, list[str | None]]:
    out: dict[str, list[str | None]] = {}
    for entry in prepared.collector.report().entries:
        out.setdefault(entry.code, []).append(entry.match_key)
    return out


# --- run rejections ------------------------------------------------------------


@pytest.mark.parametrize(
    ("season_input", "code"),
    [
        (SeasonInput(season=2023, events=(), matches=()), ex.UNSUPPORTED_SEASON),
        (_season(_m("2024wk1_qm1", 1), _m("2024wk1_qm1", 2)), ex.DUPLICATE_MATCH_KEY),
        (_season(events=(event(WK1), event(WK1))), ex.DUPLICATE_EVENT_KEY),
        (_season(_m("2024xx_qm1", 1, event_key="2024xx")), ex.UNKNOWN_EVENT),
        (_season(events=(event("2025abc"),)), ex.EVENT_SEASON_MISMATCH),
        (_season(_m("2024wk1_qm1", 1), prior=PriorSeasonInput(
            source="t", team_years={1: (PriorTeamYear(season=2024, norm_epa=1600),)})), ex.PRIOR_NOT_BEFORE_SEASON),
        (SeasonInput(season=2026, events=(event("2026wk1"),), matches=(),
                     prior=PriorSeasonInput(source="t", team_years={})), ex.TEAM_DISTRICTS_REQUIRED),
    ],
)
def test_run_rejections(season_input: SeasonInput, code: str) -> None:
    with pytest.raises(ex.RunRejected) as info:
        prepare_season(season_input)
    assert info.value.code == code


def test_future_season_prior_is_rejected_not_ignored() -> None:
    prior = PriorSeasonInput(source="t", team_years={1: (PriorTeamYear(season=2025, norm_epa=1900),)})
    with pytest.raises(ex.RunRejected, match="1:2025"):
        prepare_season(_season(_m("2024wk1_qm1", 1), prior=prior))


# --- event filters ---------------------------------------------------------


@pytest.mark.parametrize(
    ("event_input", "expected"),
    [
        (event("2024casj", event_type=0, week=0), (0, 1)),  # regional: TBA week + 1
        (event("2024mimil", event_type=1, week=2), (1, 3)),
        (event("2024micmp", event_type=2, week=5), (2, 6)),
        (event("2024micmp1", event_type=5, week=5), (5, 6)),  # DCMP division is a DCMP
        (event("2024arc", event_type=3, week=None), (3, 8)),  # championship forced to week 8
        (event("2024cmptx", event_type=4, week=6), (4, 8)),
        (event("2026isrtp", event_type=99, week=None), None),  # override: district, but week missing
        (event("2026isrtp", event_type=99, week=3), (1, 4)),  # override to district, week + 1
    ],
)
def test_adjusted_week(event_input, expected) -> None:
    season = int(event_input.event_key[:4])
    prepared, code = adjusted_week(season, event_input)
    if expected is None:
        assert prepared is None and code == ex.EVENT_WEEK_MISSING
    else:
        assert (prepared.event_type, prepared.week) == expected  # type: ignore[union-attr]


def test_filtered_events_and_their_matches_are_reported() -> None:
    events = (event(WK1), event("2024nywz"), event("2024tempclone-1"), event("2024off", event_type=99, week=3),
              event("2024nowk", event_type=0, week=None), event("2024empty", event_type=100, week=None))
    season = _season(
        _m("2024wk1_qm1", 1),
        _m("2024nywz_qm1", 2, event_key="2024nywz"),
        _m("2024tempclone-1_qm1", 3, event_key="2024tempclone-1"),
        _m("2024off_qm1", 4, event_key="2024off"),
        _m("2024nowk_qm1", 5, event_key="2024nowk"),
        events=events,
    )
    prepared = prepare_season(season)
    codes = _codes(prepared)
    assert sorted(codes[ex.EVENT_BLACKLISTED]) == ["2024nywz_qm1", "2024tempclone-1_qm1"]
    assert codes[ex.EVENT_TYPE_EXCLUDED] == [None, "2024off_qm1"]  # 2024empty has no matches: one event entry
    assert codes[ex.EVENT_WEEK_MISSING] == ["2024nowk_qm1"]
    assert [m.match_key for m in prepared.stream] == ["2024wk1_qm1"]


# --- match filters, rejections, statuses ---------------------------------------


def test_invalid_alliances_are_filtered() -> None:
    prepared = prepare_season(_season(
        _m("2024wk1_qm1", 1, red=(1, 1, 2)),  # two distinct teams
        _m("2024wk1_qm2", 2, red=(1, 2, 3), blue=(3, 4, 5)),  # 3 on both alliances
        _m("2024wk1_qm3", 3),
    ))
    assert _codes(prepared)[ex.INVALID_ALLIANCE] == ["2024wk1_qm1", "2024wk1_qm2"]
    assert [m.match_key for m in prepared.stream] == ["2024wk1_qm3"]


def test_missing_time_is_rejected_not_synthesized() -> None:
    prepared = prepare_season(_season(_m("2024wk1_qm1", None), _m("2024wk1_qm2", 2)))
    report = prepared.collector.report()
    assert report.counts[ex.MISSING_TIME] == 1
    assert report.divergences[ex.MISSING_TIME] == 1
    assert [m.match_key for m in prepared.stream] == ["2024wk1_qm2"]


def test_missing_and_malformed_breakdowns_are_rejected_with_detail() -> None:
    malformed = bd2024(teleop_speaker=3)
    del malformed["endGameParkPoints"]
    prepared = prepare_season(_season(
        _m("2024wk1_qm1", 1, red_bd=None, red_score=12),
        _m("2024wk1_qm2", 2, blue_bd=malformed, blue_score=6),
        _m("2024wk1_qm3", 3),
    ))
    report = prepared.collector.report()
    entries = {e.match_key: e for e in report.entries}
    assert entries["2024wk1_qm1"].code == ex.MISSING_BREAKDOWN
    assert entries["2024wk1_qm1"].detail == "red: score 12 with no score_breakdown"
    assert entries["2024wk1_qm2"].code == ex.MALFORMED_BREAKDOWN
    assert entries["2024wk1_qm2"].detail == "blue: endGameParkPoints missing"
    assert report.divergences == {ex.MISSING_TIME: 0, ex.MISSING_BREAKDOWN: 1, ex.MALFORMED_BREAKDOWN: 1}
    assert [m.match_key for m in prepared.stream] == ["2024wk1_qm3"]


def test_rejected_match_does_not_update_or_consume_a_qual_count() -> None:
    good = [_m(f"2024wk1_qm{i}", i) for i in range(1, 4)]
    with_rejected = _season(*good, _m("2024wk1_qm9", 9, red_bd=None, red_score=30))
    without = _season(*good)
    a, b = run_season(with_rejected, created_at="t"), run_season(without, created_at="t")
    assert {t.team: t.qual_updates for t in a.team_seasons} == {t.team: t.qual_updates for t in b.team_seasons}
    assert a.records == b.records
    assert a.report.counts[ex.MISSING_BREAKDOWN] == 1


def test_upcoming_matches_are_predicted_only() -> None:
    prepared = prepare_season(_season(
        _m("2024wk1_qm1", 1),
        _m("2024wk1_qm2", 2, red_score=-1, blue_score=-1),
        match("2024wk1_qm3", WK1, 3, alliance(2024, (1, 2, 3), None, score=None),
              alliance(2024, (4, 5, 6), None, score=None)),
        _m("2024wk1_qm4", 4, red_score=25, blue_score=-1, red_bd=bd2024(teleop_speaker=12, leave=1)),
    ))
    assert _codes(prepared)[ex.UPCOMING] == ["2024wk1_qm2", "2024wk1_qm3", "2024wk1_qm4"]
    assert [m.status for m in prepared.stream] == [ex.UPDATED, ex.UPCOMING, ex.UPCOMING, ex.UPCOMING]


def test_zero_score_is_accepted_and_counted() -> None:
    prepared = prepare_season(_season(_m("2024wk1_qm1", 1, red_bd=None, red_score=0), _m("2024wk1_qm2", 2)))
    report = prepared.collector.report()
    assert report.counts[ex.ZERO_SCORE] == 1
    assert report.possible_divergences[ex.SHARED_EMPTY_BREAKDOWN] == 1
    assert prepared.stream[0].status == ex.UPDATED and prepared.stream[0].red.empty  # type: ignore[union-attr]


def test_skip_rules() -> None:
    fouls_only = bd2024(foul=10)  # no-foul 0, foul 10
    prepared = prepare_season(_season(
        _m("2024wk1_qm1", 1, red=(1, 2, 9999)),
        _m("2024wk1_sf1m1", 2, level="sf", red_dq=(1, 2, 3)),
        _m("2024wk1_qm2", 3, red_dq=(1, 2, 3)),  # a qual with every team DQ'd is NOT skipped
        _m("2024wk1_qm3", 4, red_bd=fouls_only, blue_bd=fouls_only),
        _m("2024wk1_qm4", 5, red_bd=fouls_only),  # only one alliance all-foul: not skipped
    ))
    assert [m.status for m in prepared.stream] == [
        ex.SKIP_PLACEHOLDER, ex.SKIP_ELIM_ALL_DQ, ex.UPDATED, ex.SKIP_ALL_FOULS, ex.UPDATED,
    ]


def test_report_counts_every_code_and_sorts_entries() -> None:
    prepared = prepare_season(_season(_m("2024wk1_qm2", 2, red_score=-1, blue_score=-1), _m("2024wk1_qm1", 1)))
    report = prepared.collector.report()
    assert set(report.counts) == set(ex.MATCH_CODES)
    assert sum(report.counts.values()) == 1
    assert set(report.possible_divergences) == set(ex.POSSIBLE_DIVERGENCE_CODES)
    assert not report.has_divergences
    keys = [(e.code, e.match_key or "") for e in report.entries]
    assert keys == sorted(keys)


def test_ties_are_broken_by_match_key_and_reported() -> None:
    prepared = prepare_season(_season(
        _m("2024wk1_qm3", 100, red=(1, 2, 3), blue=(4, 5, 6)),
        _m("2024wk1_qm1", 100, red=(7, 8, 9), blue=(10, 11, 12)),
        _m("2024wk1_qm2", 200, red=(1, 2, 3), blue=(4, 5, 6)),
        _m("2024wk1_qm4", 200, red=(1, 8, 9), blue=(10, 11, 12)),
    ))
    assert [m.match_key for m in prepared.stream] == ["2024wk1_qm1", "2024wk1_qm3", "2024wk1_qm2", "2024wk1_qm4"]
    ties = prepared.collector.report().ties
    assert [(t.time, t.match_keys, t.order_sensitive) for t in ties] == [
        (100, ("2024wk1_qm1", "2024wk1_qm3"), False),  # no shared team: order cannot matter
        (200, ("2024wk1_qm2", "2024wk1_qm4"), True),  # team 1 plays both
    ]
    assert prepared.collector.report().possible_divergences[ex.TIE_ORDER] == 1
