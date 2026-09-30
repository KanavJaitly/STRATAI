"""The bounded 2024 -> 2025 -> 2026 prior-season chain (ml.ratings.chain)."""

from __future__ import annotations

import pytest

from ml.ratings.chain import prior_coverage, prior_from_results, team_districts_from_events
from ml.ratings.epa import run_season
from ml.ratings.epa.initialization import INIT_EPA
from ml.ratings.epa.inputs import SeasonInput
from ratings_epa_support import alliance, bd2026, event, match, random_season


def _chain(seasons=(2024, 2025, 2026), team_districts=None):
    results = []
    for season in seasons:
        prior = prior_from_results(season, results[-2:])
        season_input = random_season(season, seed=season)
        if prior is not None:
            season_input = season_input.model_copy(update={"prior": prior, "team_districts": team_districts or {}})
        results.append(run_season(season_input, created_at="t"))
    return results


def test_2024_has_no_prior() -> None:
    assert prior_from_results(2024, []) is None


def test_each_season_receives_only_earlier_norm_epa() -> None:
    r2024, r2025, r2026 = _chain()
    prior_2025 = prior_from_results(2025, [r2024])
    assert prior_2025 is not None
    assert prior_2025.source == f"stratai-epa-chain:2024={r2024.results_fingerprint()}"
    by_team = {t.team: t.norm_epa for t in r2024.team_seasons}
    assert {t: [(y.season, y.norm_epa) for y in ys] for t, ys in prior_2025.team_years.items()} == {
        t: [(2024, n)] for t, n in by_team.items()
    }
    prior_2026 = prior_from_results(2026, [r2025, r2024])
    assert prior_2026 is not None and prior_2026.source.endswith(
        f"2024={r2024.results_fingerprint()},2025={r2025.results_fingerprint()}")
    assert all([y.season for y in ys] == [2025, 2024] for ys in prior_2026.team_years.values())


@pytest.mark.parametrize("seasons", [[2025], [2026], [2024, 2024]])
def test_prior_refuses_same_later_or_duplicate_seasons(seasons) -> None:
    results = {s: run_season(random_season(s, seed=s), created_at="t") for s in set(seasons)}
    with pytest.raises(ValueError):
        prior_from_results(2025, [results[s] for s in seasons])


def test_prior_refuses_results_without_norm() -> None:
    result = run_season(random_season(2024), compute_norm=False, created_at="t")
    with pytest.raises(ValueError, match="no norm_epa"):
        prior_from_results(2025, [result])


def test_chain_gives_informative_relative_starts() -> None:
    r2024, r2025, _ = _chain()
    starts_2024 = {round(t.start[0], 9) for t in r2024.team_seasons}
    starts_2025 = {round(t.start[0], 9) for t in r2025.team_seasons}
    assert len(starts_2024) == 1  # no history: everyone starts alike
    assert len(starts_2025) > 1  # 2024 history separates the teams
    best_2024 = max(r2024.team_seasons, key=lambda t: t.norm_epa)
    worst_2024 = min(r2024.team_seasons, key=lambda t: t.norm_epa)
    start = {t.team: t.start[0] for t in r2025.team_seasons}
    assert start[best_2024.team] > start[worst_2024.team]


def test_team_without_prior_starts_like_a_rookie() -> None:
    r2024 = run_season(random_season(2024, seed=1), created_at="t")
    base = random_season(2025, seed=2)
    rookie_prior = prior_from_results(2025, [r2024])
    # team 999 never played in 2024; add it to one 2025 match
    m0 = base.matches[0]
    red = m0.red.model_copy(update={"teams": (999, *m0.red.teams[1:])})
    season = base.model_copy(update={"matches": (m0.model_copy(update={"red": red}), *base.matches[1:]),
                                     "prior": rookie_prior})
    with_prior = run_season(season, created_at="t")
    no_prior = run_season(season.model_copy(update={"prior": None}), created_at="t")
    start = {t.team: t.start for t in with_prior.team_seasons}
    assert start[999] == {t.team: t.start for t in no_prior.team_seasons}[999]  # 1450 in both prior slots
    assert INIT_EPA == 1450
    coverage = prior_coverage(season, [t.team for t in with_prior.team_seasons])
    assert coverage["no_prior_season"] == 1 and coverage["one_prior_season"] == len(with_prior.team_seasons) - 1


def test_chain_is_deterministic() -> None:
    first = [r.results_fingerprint() for r in _chain()]
    assert [r.results_fingerprint() for r in _chain()] == first


def test_team_districts_from_events() -> None:
    events = (event("2026isde1", event_type=1, week=16, district="isr"),
              event("2026mimil", event_type=1, week=2, district="fim"),
              event("2026micmp", event_type=2, week=5, district="fim"),
              event("2026casj", event_type=0, week=0))
    matches = (
        match("2026isde1_qm1", "2026isde1", 1, alliance(2026, (1, 2, 3), bd2026(auto_fuel=5)),
              alliance(2026, (4, 5, 6), bd2026(auto_fuel=5))),
        match("2026mimil_qm1", "2026mimil", 2, alliance(2026, (6, 7, 8), bd2026(auto_fuel=5)),
              alliance(2026, (9, 10, 11), bd2026(auto_fuel=5))),
        match("2026micmp_qm1", "2026micmp", 3, alliance(2026, (7, 8, 9), bd2026(auto_fuel=5)),
              alliance(2026, (10, 11, 12), bd2026(auto_fuel=5))),
        match("2026casj_qm1", "2026casj", 4, alliance(2026, (1, 13, 14), bd2026(auto_fuel=5)),
              alliance(2026, (15, 16, 17), bd2026(auto_fuel=5))),
    )
    season = SeasonInput(season=2026, events=events, matches=matches)
    mapping, conflicts = team_districts_from_events(season)
    assert mapping[1] == "isr" and mapping[2] == "isr" and mapping[7] == "fim" and mapping[12] == "fim"
    assert 13 not in mapping  # played only a regional
    assert conflicts == (6,)  # played both an isr and a fim district event


def test_isr_teams_skip_mean_reversion_in_2026() -> None:
    r2024, r2025, _ = _chain((2024, 2025, 2026))
    season = random_season(2026, seed=2026).model_copy(update={"prior": prior_from_results(2026, [r2025, r2024])})
    team = 100
    isr = run_season(season.model_copy(update={"team_districts": {team: "isr"}}), created_at="t")
    other = run_season(season.model_copy(update={"team_districts": {team: "fim"}}), created_at="t")
    start_isr = {t.team: t.start[0] for t in isr.team_seasons}
    start_other = {t.team: t.start[0] for t in other.team_seasons}
    assert start_isr[team] != start_other[team]
    assert all(start_isr[t] == start_other[t] for t in start_isr if t != team)
