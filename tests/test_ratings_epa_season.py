"""End-to-end season runs: aggregation, unitless/norm EPA, manifest, provider."""

from __future__ import annotations

import statistics

import pytest

from ml.ratings.epa import NO_PRIOR_LABEL, run_season
from ml.ratings.epa import exclusions as ex
from ml.ratings.epa.constants import REFERENCE_COMMIT, configuration_hash
from ml.ratings.epa.inputs import PriorSeasonInput, PriorTeamYear, SeasonInput, season_input_fingerprint
from ml.ratings.epa.normalization import epa_to_norm_epa_func, scipy_version
from ml.ratings.epa.rounding import numpy_round, reference_round
from ml.ratings.provider import (
    UNAVAILABLE_NO_TEAM_EVENT,
    UNAVAILABLE_NOT_RUN,
    StrataiEpaProvider,
    TeamEventEpa,
    Unavailable,
)
from ratings_epa_support import alliance, bd2024, event, match, random_season


def _small_season() -> SeasonInput:
    """Team 1 plays two quals and a semifinal at a week-1 event, then two quals at champs."""
    e1, cmp = "2024wk1", "2024cmp"
    def m(key, ev, t, red, blue, red_bd, blue_bd, level="qm"):
        return match(key, ev, t, alliance(2024, red, red_bd), alliance(2024, blue, blue_bd), level=level)
    return SeasonInput(
        season=2024,
        events=(event(e1, week=0), event(cmp, event_type=3, week=None)),
        matches=(
            m(f"{e1}_qm1", e1, 100, (1, 2, 3), (4, 5, 6), bd2024(teleop_speaker=12), bd2024(teleop_speaker=6)),
            m(f"{e1}_qm2", e1, 200, (1, 4, 7), (2, 5, 8), bd2024(teleop_speaker=9), bd2024(teleop_speaker=11)),
            m(f"{e1}_qm3", e1, 300, (3, 6, 9), (7, 8, 2), bd2024(teleop_speaker=7), bd2024(teleop_speaker=8)),
            m(f"{e1}_sf1m1", e1, 400, (1, 2, 3), (7, 8, 9), bd2024(teleop_speaker=14), bd2024(teleop_speaker=10), "sf"),
            m(f"{cmp}_qm1", cmp, 900, (1, 5, 9), (2, 6, 7), bd2024(teleop_speaker=15), bd2024(teleop_speaker=9)),
            m(f"{cmp}_qm2", cmp, 1000, (1, 6, 8), (3, 4, 5), bd2024(teleop_speaker=13), bd2024(teleop_speaker=12)),
        ),
    )


def test_team_event_and_team_season_aggregates() -> None:
    result = run_season(_small_season(), created_at="t")
    records = {r.match_key: r for r in result.records}
    team_1 = [r for r in result.records if 1 in r.pre]
    week_1 = result.team_event(1, "2024wk1")
    assert week_1 is not None
    # end of event, playoffs included: after the semifinal
    assert week_1.epa == numpy_round(records["2024wk1_sf1m1"].post[1][0], 2)  # type: ignore[index]
    assert week_1.qual_count == 2 and not week_1.epa_is_season_end
    pre = [numpy_round(r.pre[1][0], 2) for r in team_1[:3]]
    assert week_1.epa_start == reference_round(pre[0], 2)
    assert week_1.epa_mean == reference_round(statistics.mean(pre), 2)
    assert week_1.epa_max == reference_round(max(pre), 2)
    assert week_1.epa_pre_elim == reference_round(numpy_round(records["2024wk1_qm2"].pre[1][0], 2), 2)

    season_1 = next(s for s in result.team_seasons if s.team == 1)
    assert season_1.epa == numpy_round(records["2024cmp_qm2"].post[1][0], 2)  # type: ignore[index]
    assert season_1.epa_pre_champs == numpy_round(records["2024wk1_sf1m1"].post[1][0], 2)  # champs is week 8
    assert season_1.epa_max == season_1.epa  # fewer than 9 matches: max is the end value
    assert season_1.epa_start == reference_round(season_1.start[0], 2)
    assert season_1.matches == 5 and season_1.qual_updates == 4
    # unitless: 1500 + 250 * (epa - score_mean / 3) / score_sd, r() to an integer
    expected = int(reference_round(1500 + 250 * (season_1.epa - result.stats.score_mean / 3) / result.stats.score_sd))
    assert season_1.unitless_epa == expected


def test_max_epa_skips_the_first_eight_matches() -> None:
    result = run_season(random_season(2024, seed=4, teams=8, events=2, quals_per_event=14), created_at="t")
    team = max(result.team_seasons, key=lambda s: s.matches)
    assert team.matches > 9
    posts = [numpy_round(r.post[team.team][0], 2) for r in result.records if team.team in r.pre and r.post]
    assert team.epa_max == max(posts[8:])


def test_norm_epa_is_monotone_and_recorded() -> None:
    result = run_season(random_season(2025, seed=2, teams=30), created_at="t")
    assert result.norm_computed and result.manifest["libraries"]["scipy"] == scipy_version()
    ordered = sorted(result.team_seasons, key=lambda s: s.epa)
    norms = [s.norm_epa for s in ordered]
    assert all(isinstance(n, int) for n in norms)
    assert norms == sorted(norms)  # higher raw EPA never gets a lower norm EPA
    again = run_season(random_season(2025, seed=2, teams=30), created_at="t")
    assert [s.norm_epa for s in again.team_seasons] == [s.norm_epa for s in result.team_seasons]


def test_norm_can_be_left_out_entirely() -> None:
    result = run_season(random_season(2024), compute_norm=False, created_at="t")
    assert not result.norm_computed and all(s.norm_epa is None for s in result.team_seasons)
    assert result.manifest["libraries"]["scipy_used"] is False


def test_norm_function_interpolates_between_quantiles_and_clamps_outside() -> None:
    epas = [float(x) for x in range(1, 201)]
    norm = epa_to_norm_epa_func(epas)
    assert norm is not None
    assert norm(-50.0) == norm(1.0)  # below the lowest quantile: clamped to it
    assert norm(10_000.0) == norm(200.0)  # above the highest: clamped
    lo, hi = norm(100.0), norm(102.0)
    assert norm(101.0) == pytest.approx((lo + hi) / 2)  # quantiles are 1.99 apart; interpolation is linear
    assert epa_to_norm_epa_func([]) is None


def test_manifest_provenance() -> None:
    season_input = _small_season()
    result = run_season(season_input, data_snapshot={"max_raw_payload_id": 42}, created_at="t")
    manifest = result.manifest
    assert manifest["reference"]["commit"] == REFERENCE_COMMIT
    assert manifest["configuration_hash"] == configuration_hash()
    assert manifest["input_fingerprint"] == season_input_fingerprint(season_input)
    assert manifest["prior"] == "none supplied" and result.initialization == NO_PRIOR_LABEL
    assert manifest["data_snapshot"] == {"max_raw_payload_id": 42}
    assert set(manifest["exclusion_counts"]) == set(ex.MATCH_CODES)
    assert manifest["created_at"] == "t"
    assert "manifest" not in result.results_payload()


def test_prior_is_labelled_and_changes_the_start() -> None:
    prior = PriorSeasonInput(source="unit-test", team_years={1: (PriorTeamYear(season=2023, norm_epa=1900),)})
    with_prior = run_season(_small_season().model_copy(update={"prior": prior}), created_at="t")
    without = run_season(_small_season(), created_at="t")
    assert with_prior.initialization == "prior supplied: unit-test"
    assert with_prior.manifest["prior"]["source"] == "unit-test"
    start = {s.team: s.start for s in with_prior.team_seasons}
    base = {s.team: s.start for s in without.team_seasons}
    assert start[1][0] > base[1][0] and start[2] == base[2]


def test_provider_serves_stratai_team_event_epa() -> None:
    result = run_season(_small_season(), created_at="t")
    provider = StrataiEpaProvider([result])
    value = provider.team_event_epa(1, "2024wk1")
    assert isinstance(value, TeamEventEpa) and value.source == "stratai"
    team_event = result.team_event(1, "2024wk1")
    assert value.total == team_event.epa and value.auto == team_event.components["auto_epa"]  # type: ignore[union-attr]
    assert value.lookahead is False
    assert value.provenance["results_fingerprint"] == result.results_fingerprint()
    missing = provider.team_event_epa(99, "2024wk1")
    assert isinstance(missing, Unavailable) and missing.reason == UNAVAILABLE_NO_TEAM_EVENT
    other = provider.team_event_epa(1, "2025wk1")
    assert isinstance(other, Unavailable) and other.reason == UNAVAILABLE_NOT_RUN


def test_availability_metadata() -> None:
    """available_at is the scheduled time of the last match a value depends on."""
    result = run_season(_small_season(), created_at="t")
    # week-1 event 2024wk1 ends at t=400; champs (week 8) ends at t=1000
    assert (result.availability.week_one_complete_time, result.availability.season_final_time) == (400, 1000)
    week_1 = result.team_event(1, "2024wk1")
    champs = result.team_event(1, "2024cmp")
    assert week_1.last_played_time == 400 and week_1.available_at == 400  # type: ignore[union-attr]
    assert champs.last_played_time == 1000 and champs.available_at == 1000  # type: ignore[union-attr]
    team_4 = result.team_event(4, "2024wk1")
    # team 4 last played at t=200, but the statistics needed every week-1 match (t=400)
    assert team_4.last_played_time == 200 and team_4.available_at == 400  # type: ignore[union-attr]
    assert all(e.norm_available_at == 1000 for e in result.team_events)
    assert all(s.available_at == 1000 for s in result.team_seasons)


def test_season_end_team_event_is_available_only_at_season_end() -> None:
    season = _small_season()
    # team 5 plays qm1 and qm2 at 2024wk1; make it a surrogate in both, so it has no counted qual there
    matches = []
    for m in season.matches:
        if m.event_key == "2024wk1" and m.comp_level == "qm" and 5 in m.red.teams + m.blue.teams:
            color = "red" if 5 in m.red.teams else "blue"
            m = m.model_copy(update={color: getattr(m, color).model_copy(update={"surrogate_teams": (5,)})})
        matches.append(m)
    result = run_season(season.model_copy(update={"matches": tuple(matches)}), created_at="t")
    team_event = result.team_event(5, "2024wk1")
    assert team_event.epa_is_season_end and team_event.available_at == result.availability.season_final_time  # type: ignore[union-attr]
