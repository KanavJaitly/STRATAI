"""Point-in-time guarantees: a rating before match N cannot see N or anything later.

The synthetic season has three events, one per week (adjusted weeks 1, 2, 3).
For target matches after week 1, every perturbation of match N's own result,
of later matches, of later events, or of later score breakdowns must leave
every pre-match rating and prediction up to and including N bit-identical.

Week 1 is the documented exception (spec §3, year_stats module docstring):
season statistics come from all week-1 results, so a week-1 result can move
earlier week-1 predictions. The last tests pin that behaviour so it cannot be
mistaken for a leak-free guarantee, and show the loop itself is causal even
there once the statistics are held fixed.
"""

from __future__ import annotations

import random

import pytest

from ml.ratings.epa import run_season, start_engine
from ml.ratings.epa.engine import EpaEngine
from ml.ratings.epa.inputs import MatchInput, SeasonInput
from ml.ratings.epa.validation import prepare_season
from ratings_epa_support import SCORERS, alliance, random_bd, random_season

SEASONS = [2024, 2025, 2026]


def _base(season: int) -> SeasonInput:
    return random_season(season, seed=season + 1, teams=15, quals_per_event=10, elims_per_event=3)


def _rescored(m: MatchInput, rng: random.Random, season: int) -> MatchInput:
    return m.model_copy(update={
        "red": alliance(season, m.red.teams, random_bd(season, rng)),
        "blue": alliance(season, m.blue.teams, random_bd(season, rng)),
    })


def _replace(season_input: SeasonInput, keys: set[str], fn) -> SeasonInput:
    return season_input.model_copy(update={
        "matches": tuple(fn(m) if m.match_key in keys else m for m in season_input.matches)
    })


def _order(season_input: SeasonInput) -> list[str]:
    return [m.match_key for m in prepare_season(season_input).stream]


def _targets(season_input: SeasonInput) -> list[str]:
    """Matches after week 1: the first and last of week 2, and one in week 3."""
    stream = prepare_season(season_input).stream
    week_2 = [m.match_key for m in stream if m.week == 2]
    week_3 = [m.match_key for m in stream if m.week == 3]
    return [week_2[0], week_2[-1], week_3[len(week_3) // 2]]


def _assert_prefix_identical(a, b, target: str, *, include_target_post: bool) -> None:
    ra = {r.match_key: r for r in a.records}
    rb = {r.match_key: r for r in b.records}
    for record in a.records:
        other = rb[record.match_key]
        assert record.pre == other.pre, record.match_key
        assert (record.win_prob, record.red_score, record.blue_score, record.red_rps, record.blue_rps) == (
            other.win_prob, other.red_score, other.blue_score, other.red_rps, other.blue_rps), record.match_key
        if record.match_key == target:
            if include_target_post:
                assert record.post == other.post
            break
        assert record.post == other.post, record.match_key
    assert target in ra


@pytest.mark.parametrize("season", SEASONS)
def test_match_n_result_cannot_reach_ratings_before_n(season: int) -> None:
    base = _base(season)
    baseline = run_season(base, compute_norm=False, created_at="t")
    for target in _targets(base):
        changed = _replace(base, {target}, lambda m: _rescored(m, random.Random(target), season))
        result = run_season(changed, compute_norm=False, created_at="t")
        assert result.stats == baseline.stats  # a week >= 2 match never feeds the statistics
        _assert_prefix_identical(baseline, result, target, include_target_post=False)
        # the perturbation did change something: N's own update
        after = {r.match_key: r for r in result.records}[target]
        before = {r.match_key: r for r in baseline.records}[target]
        assert after.post != before.post


@pytest.mark.parametrize("season", SEASONS)
def test_later_matches_and_breakdowns_cannot_reach_ratings_up_to_n(season: int) -> None:
    base = _base(season)
    baseline = run_season(base, compute_norm=False, created_at="t")
    order = _order(base)
    for target in _targets(base):
        later = set(order[order.index(target) + 1:])
        rng = random.Random(target)
        changed = _replace(base, later, lambda m: _rescored(m, rng, season))
        _assert_prefix_identical(baseline, run_season(changed, compute_norm=False, created_at="t"), target,
                                 include_target_post=True)


@pytest.mark.parametrize("season", SEASONS)
def test_later_breakdown_detail_with_the_same_scores_cannot_leak(season: int) -> None:
    """Only the future breakdown's contents change; every future score stays the same."""
    base = _base(season)
    baseline = run_season(base, compute_norm=False, created_at="t")
    order = _order(base)
    target = _targets(base)[0]
    later = set(order[order.index(target) + 1:])

    def shifted(m: MatchInput) -> MatchInput:
        def move(a):
            bd = dict(a.breakdown)
            bd["foulPoints"] += 3  # three points reclassified as fouls, score unchanged
            bd["adjustPoints"] -= 3
            assert SCORERS[season](bd) == a.score
            return a.model_copy(update={"breakdown": bd})
        return m.model_copy(update={"red": move(m.red), "blue": move(m.blue)})

    changed = _replace(base, later, shifted)
    _assert_prefix_identical(baseline, run_season(changed, compute_norm=False, created_at="t"), target,
                             include_target_post=True)


@pytest.mark.parametrize("season", SEASONS)
def test_later_events_cannot_reach_ratings_up_to_n(season: int) -> None:
    base = _base(season)
    baseline = run_season(base, compute_norm=False, created_at="t")
    order = _order(base)
    target = _targets(base)[1]  # last match of week 2
    kept = set(order[: order.index(target) + 1])
    truncated = base.model_copy(update={
        "matches": tuple(m for m in base.matches if m.match_key in kept),
        "events": tuple(e for e in base.events if any(m.event_key == e.event_key for m in base.matches
                                                       if m.match_key in kept)),
    })
    result = run_season(truncated, compute_norm=False, created_at="t")
    _assert_prefix_identical(baseline, result, target, include_target_post=True)
    assert len(result.records) == len(kept) < len(baseline.records)


def test_no_state_survives_between_runs_or_seasons() -> None:
    """Running other seasons first (the reference's shared-state failure mode) changes nothing."""
    fresh = run_season(_base(2026), created_at="t").canonical_json()
    for season in (2024, 2025):
        run_season(_base(season), created_at="t")
    assert run_season(_base(2026), created_at="t").canonical_json() == fresh


def test_week_one_results_do_move_week_one_predictions_through_the_statistics() -> None:
    """Pinned reference behaviour, not a guarantee: the week-1 statistics use every
    week-1 result, so changing the LAST week-1 match changes the FIRST one's prediction."""
    base = _base(2024)
    stream = prepare_season(base).stream
    week_1 = [m.match_key for m in stream if m.week == 1]
    last = week_1[-1]
    changed = _replace(base, {last}, lambda m: _rescored(m, random.Random(99), 2024))
    a, b = run_season(base, compute_norm=False, created_at="t"), run_season(changed, compute_norm=False, created_at="t")
    assert a.stats != b.stats
    assert a.records[0].pre != b.records[0].pre  # starting ratings moved with the statistics


def test_the_loop_is_causal_in_week_one_once_statistics_are_fixed() -> None:
    base = _base(2024)
    prepared, engine = start_engine(base)
    stats, start = engine.stats, engine.ratings()
    stream = list(prepared.stream)
    baseline = [engine.process(m) for m in stream]

    target_index = next(i for i, m in enumerate(stream) if m.week == 1 and i > 3)
    target_key = stream[target_index].match_key
    changed = _replace(base, {target_key}, lambda m: _rescored(m, random.Random(7), 2024))
    changed_stream = prepare_season(changed).stream
    import numpy as np

    fixed = EpaEngine(stats, {t: np.array(v) for t, v in start.items()})
    perturbed = [fixed.process(m) for m in changed_stream]
    for i in range(target_index):
        assert perturbed[i] == baseline[i]
    assert perturbed[target_index].pre == baseline[target_index].pre
    assert perturbed[target_index].post != baseline[target_index].post


def test_season_end_team_event_values_are_flagged_as_lookahead() -> None:
    """A team-event with no counted qual (here: every qual as a surrogate) takes the
    season-end rating (reference calc.py:45-48); it must say so."""
    base = _base(2024)
    stream = prepare_season(base).stream
    first_event = stream[0].event_key
    team = stream[0].red_teams[0]
    quals = {m.match_key for m in base.matches if m.event_key == first_event and m.comp_level == "qm"
             and team in m.red.teams + m.blue.teams}

    def as_surrogate(m: MatchInput) -> MatchInput:
        color = "red" if team in m.red.teams else "blue"
        a = getattr(m, color)
        return m.model_copy(update={color: a.model_copy(update={"surrogate_teams": (team,)})})

    result = run_season(_replace(base, quals, as_surrogate), created_at="t")
    team_event = result.team_event(team, first_event)
    assert team_event is not None and team_event.qual_count == 0 and team_event.epa_is_season_end
    season_final = next(s for s in result.team_seasons if s.team == team).final
    assert team_event.vector == season_final
    others = [e for e in result.team_events if e.qual_count > 0]
    assert others and not any(e.epa_is_season_end for e in others)
