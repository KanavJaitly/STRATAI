"""data.alliance_checks: P5-M1's frozen alliance-quality criteria (synthetic data)."""

from __future__ import annotations

import pytest

from data.alliance_checks import (
    MembershipException,
    SeedRankViolation,
    is_seeded_event,
    playoff_membership_exceptions,
    seed_rank_violations,
)
from data.alliances import Alliance


def _alliance(seed, picks, *, backup=None, declines=(), name=None):
    return Alliance(seed=seed, position=seed or 1, name=name or (f"Alliance {seed}" if seed else "Division"),
                    captain=picks[0] if picks else None, picks=tuple(picks), backup=backup, declines=tuple(declines))


RANKS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8}


def test_consistent_selection_has_no_violations():
    # seed 1 (rank 1) picks rank 2 -> seed 2's captain is rank 3, the best remaining
    alliances = [_alliance(1, [1, 2]), _alliance(2, [3, 4]), _alliance(3, [5, 6])]
    assert seed_rank_violations(alliances, RANKS) == []


def test_declined_team_may_still_captain():
    # rank 2 declined seed 1's invitation and then captains seed 2: allowed by the rule
    alliances = [_alliance(1, [1, 3], declines=[2]), _alliance(2, [2, 4])]
    assert seed_rank_violations(alliances, RANKS) == []


def test_wrong_captain_is_listed_with_the_expected_one():
    alliances = [_alliance(1, [1, 2]), _alliance(2, [5, 4])]  # rank 3 was available
    assert seed_rank_violations(alliances, RANKS) == [
        SeedRankViolation(2, 5, 3, "captain_not_best_ranked_available")]


def test_unranked_captain_is_listed():
    alliances = [_alliance(1, [99, 2])]
    assert seed_rank_violations(alliances, RANKS)[0].reason == "captain_unranked"


def test_seed_rank_refuses_unseeded_events():
    with pytest.raises(ValueError):
        seed_rank_violations([_alliance(None, [1, 2], name="Archimedes")], RANKS)
    assert not is_seeded_event([_alliance(None, [1, 2], name="Archimedes")])
    assert not is_seeded_event([])


def test_membership_lists_playoff_teams_on_no_alliance():
    alliances = [_alliance(1, [1, 2, 3]), _alliance(2, [4, 5, 6])]
    assert playoff_membership_exceptions(alliances, [1, 2, 3, 4, 5, 6, 77]) == [
        MembershipException(77, "not_on_any_alliance")]


def test_membership_counts_a_recorded_backup():
    alliances = [_alliance(1, [1, 2, 3], backup=77)]
    assert playoff_membership_exceptions(alliances, [1, 2, 3, 77]) == []
