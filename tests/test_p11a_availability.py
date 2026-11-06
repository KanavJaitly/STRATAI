"""P11A and Phase 11 agree on availability (hardening, 2026-11-06).

`draft_recommendations.selectable_teams` is the single definition of who the selecting alliance may pick at its next
turn. These tests walk seeded random legal drafts (picks and declines, under several rule variants) and check, at every
state and for every team with a turn:
- P11A's pickable teams equal P11-FB1's candidates (ranked plus unranked) exactly;
- every team P11-FB1 excludes is unavailable to P11A, with the same reason;
- the P6-M7 engine branch serves only selectable teams;
- the shared function equals the pre-refactor expression (available minus the rule exclusions).
Synthetic teams 1-24 only."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ml.alliance.planner import PlanWithheld
from tests.test_phase11_draft_log import Log, setup
from workspaces import alliance_plan
from workspaces import draft_recommendations as rec

NOW = datetime(2030, 3, 2, 18, 0, tzinfo=timezone.utc)
VARIANTS = {
    "standard": {},
    "no_higher_alliance": {"captain_may_accept_higher_alliance": False},
    "declined_may_be_picked": {"declined_team_may_be_picked_later": True},
    "declined_not_captain": {"declined_team_may_become_captain": False},
    "three_picks": {"picks_per_alliance": 3, "n_alliances": 6},
}


def random_states(variant: dict, seed: int, max_steps: int = 40):
    """Yield the replayed view after every accepted action of a seeded random legal draft."""
    rng = random.Random(seed)
    log = Log(setup(**variant))
    yield log.view()
    for _ in range(max_steps):
        view = log.view()
        acting = view.acting_seed()
        if acting is None:
            return
        if not view.alliances[acting - 1]:
            captain, _ = view.expected_captain()
            if captain is None:
                return
            log.append_checked("captain", {"seed": acting, "team": captain})
            yield log.view()
            continue
        available, _ = view.availability()
        choices = rng.sample(available, min(6, len(available)))
        for team in choices:
            kind = "decline" if rng.random() < 0.2 else "pick"
            _, violation = log.append_checked(kind, {"seed": acting, "team": team})
            if violation is None:
                break
        else:
            return
        yield log.view()


def teams_with_a_turn(view):
    out = []
    for team in range(1, 25):
        seed, _ = rec.selecting_seed(view, team)
        if seed is not None and view.turns_before(seed) is not None:
            out.append((team, seed))
    return out


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_p11a_and_p11_fb1_agree_on_every_state_of_random_drafts(name):
    checked = 0
    for walk in range(6):
        for view in random_states(VARIANTS[name], seed=walk):
            if view.setup is None or view.flagged:
                continue
            for team, seed in teams_with_a_turn(view):
                ranked, unranked, excluded = rec.fallback_lists(view, seed, team, [])
                try:
                    pos = alliance_plan.position_from_view(view, team)
                except PlanWithheld:
                    continue
                assert set(pos.available) == set(ranked) | set(unranked), (name, walk, team)
                for t, reason in excluded:
                    assert pos.unavailable.get(t) == reason, (name, walk, team, t)
                available, _ = view.availability()
                old = [t for t in available if t not in rec.next_turn_exclusions(view, seed, team)]
                assert list(pos.available) == old  # same teams, same rank order as before the refactor
                checked += 1
    assert checked > 50  # the walks really exercised many states


def test_the_engine_branch_serves_only_selectable_teams(monkeypatch):
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)  # projected captains 3.. act before alliance 4's turn in round 1
    view = log.view()
    ranked = [SimpleNamespace(team_number=t, profile=None, p_win_event=None, p_reach_finals=None, configuration=None)
              for t in range(1, 25)]
    engine = SimpleNamespace(recommendation=SimpleNamespace(ranked=ranked, probability_status="not_validated"),
                             ruleset_sha256="ab" * 32, ruleset_variant=None, ordering_policy="x", moment=NOW)
    monkeypatch.setattr(rec, "_try_engine", lambda *a, **k: (engine, None))
    out = rec.recommend(None, "2030test", view, None, 5, epa_source=None, ranking=None, playoff_models=None,
                        now=lambda: NOW)
    selectable, excluded = rec.selectable_teams(view, 4, 5)
    served = [c.team_number for c in [out.primary, *out.backups]]
    assert served and set(served) <= set(selectable)
    assert dict(out.excluded) == excluded
    assert served == selectable[:len(served)]  # engine order filtered, nothing reordered
