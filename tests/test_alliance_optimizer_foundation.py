"""The alliance optimizer foundation (audit 2026-11-26, workstream 7; ml/alliance/optimizer).

SYNTHETIC fixtures only: invented components ("a", "b", "c"), invented values and invented team numbers. Nothing here
describes any real FRC season's scoring, and no configuration here is approved for real use.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from ml.alliance.optimizer.backup import backup_value, roster_value
from ml.alliance.optimizer.config import ConfigError, SeasonScoringConfig
from ml.alliance.optimizer.evaluator import RobotProfile, evaluate_lineup
from ml.alliance.optimizer.search import (
    STAGE,
    STATUS,
    EveryoneAvailable,
    GivenProbabilities,
    rank_backup_picks,
    rank_first_picks,
    rank_second_picks,
)

ROOT = Path(__file__).resolve().parents[1]


def config(**over) -> SeasonScoringConfig:
    data = {
        "season": 9999, "version": "synthetic-1",
        "components": [{"name": "a", "kind": "capped", "cap": 40}, {"name": "b", "kind": "additive"},
                       {"name": "c", "kind": "best_k", "k": 1}],
        "alliance": {"active_robots": 3, "roster_size": 4, "lineup_choice": True,
                     "short_handed": "plays_with_available"},
        "approval": {"status": "draft"},
        "bonuses": [], "roles": [],
    }
    data.update(over)
    return SeasonScoringConfig.from_dict(data)


def robot(team: int, a=0.0, b=0.0, c=0.0, **extra) -> RobotProfile:
    return RobotProfile(team=team, contributions={"a": a, "b": b, "c": c}, **extra)


# --- configuration -------------------------------------------------------------------------------------------------


def test_an_unapproved_configuration_is_refused_unless_explicitly_allowed():
    draft = config()
    with pytest.raises(ConfigError, match="not approved"):
        draft.require_usable()
    draft.require_usable(allow_unapproved=True)
    with pytest.raises(ConfigError, match="not approved"):
        rank_second_picks(1, 2, [3], {t: robot(t) for t in (1, 2, 3)}, draft)
    with pytest.raises(ConfigError, match="names who approved"):
        config(approval={"status": "approved"})
    approved = config(approval={"status": "approved", "approved_by": "synthetic reviewer", "approved_on": "2099-01-01"})
    approved.require_usable()


@pytest.mark.parametrize(("change", "message"), [
    ({"components": [{"name": "a", "kind": "capped"}]}, "positive cap"),
    ({"components": [{"name": "a", "kind": "best_k", "k": 4}]}, "k exceeds"),
    ({"components": [{"name": "a", "kind": "additive", "cap": 3}]}, "only to a capped"),
    ({"components": [{"name": "a", "kind": "sum"}]}, "unknown rule"),
    ({"components": []}, "at least one component"),
    ({"bonuses": [{"name": "x", "component": "z", "threshold": 1, "value": 1}]}, "unknown component"),
    ({"alliance": {"active_robots": 3, "roster_size": 2, "lineup_choice": True,
                   "short_handed": "plays_with_available"}}, "at least the active"),
    ({"extra": 1}, "unknown configuration keys"),
])
def test_malformed_configurations_are_refused(change, message):
    with pytest.raises(ConfigError, match=message):
        config(**change)


# --- interactions --------------------------------------------------------------------------------------------------


def test_a_capped_component_saturates_so_overlapping_robots_add_less_than_their_sum():
    cfg = config()
    two = evaluate_lineup([robot(1, a=30), robot(2, a=30)], cfg)
    assert two.components["a"] == 40  # not 60
    noisy = evaluate_lineup([robot(1, a=30, variances={"a": 25.0}), robot(2, a=10, variances={"a": 25.0})], cfg)
    assert noisy.components["a"] < 40  # E[min(S, cap)] < min(E[S], cap) when S can exceed the cap
    sd, z = math.sqrt(50), 0.0
    assert noisy.components["a"] == pytest.approx(40 - sd * math.exp(-z * z / 2) / math.sqrt(2 * math.pi))


def test_a_best_k_component_counts_only_the_best_robots():
    cfg = config()
    assert evaluate_lineup([robot(1, c=12), robot(2, c=9), robot(3, c=5)], cfg).components["c"] == 12


def test_a_bonus_rewards_reaching_the_threshold_and_its_expectation_follows_the_uncertainty():
    cfg = config(bonuses=[{"name": "rp", "component": "b", "threshold": 20, "value": 10}])
    below = evaluate_lineup([robot(1, b=12), robot(2, b=7)], cfg)
    above = evaluate_lineup([robot(1, b=12), robot(3, b=8)], cfg)
    assert below.bonuses["rp"] == 0 and above.bonuses["rp"] == 10
    assert above.total - below.total == pytest.approx(11)  # one point of b, and the bonus it unlocks
    uncertain = evaluate_lineup([robot(1, b=12, variances={"b": 4.0}), robot(2, b=8, variances={"b": 0.0})], cfg)
    assert uncertain.bonuses["rp"] == pytest.approx(5.0)  # the mean sits on the threshold: P = 0.5


def test_roles_replace_normal_scoring_are_assigned_only_when_better_and_respect_their_limit():
    cfg = config(roles=[{"name": "defense", "max_per_alliance": 1}])
    defender = robot(1, b=5, role_contributions={"defense": {}}, role_values={"defense": 12})
    other = robot(2, b=4, role_contributions={"defense": {}}, role_values={"defense": 9})
    value = evaluate_lineup([defender, other, robot(3, b=6)], cfg)
    assert value.roles == {1: "defense"}  # 12+4+6 = 22 beats 5+9+6 = 20; both defending (27) exceeds the limit
    assert value.total == pytest.approx(12 + 4 + 6)
    weak = robot(4, b=5, role_contributions={"defense": {}}, role_values={"defense": 2})
    assert evaluate_lineup([weak, robot(3, b=6)], cfg).roles == {}  # defending would cost value: not assigned


# --- picks ---------------------------------------------------------------------------------------------------------

# Captain 1 fills the capped component; 2 scores more in total than 3, but mostly on that same capped component.
PROFILES = {
    1: robot(1, a=35, b=10),
    2: robot(2, a=30, b=12),   # raw total 42, but its "a" is wasted beside the captain
    3: robot(3, a=0, b=25),    # raw total 25, all of it counts
    4: robot(4, a=0, b=20, c=6),
    5: robot(5, a=5, b=8, c=10),
}


def test_the_first_pick_accounts_for_interactions_not_raw_totals():
    ranking = rank_first_picks(1, [2, 3, 4, 5], PROFILES, config(), EveryoneAvailable(), allow_unapproved=True)
    assert ranking.status == STATUS and ranking.stage == STAGE and ranking.config_approval == "draft"
    order = [c.team for c in ranking.candidates]
    assert order.index(3) < order.index(2)  # 3 ranks above 2 despite a lower raw total
    best = ranking.candidates[0]
    assert best.value == pytest.approx(max(evaluate_lineup([PROFILES[1], PROFILES[best.team], PROFILES[d]],
                                                           config()).total for d in (2, 3, 4, 5) if d != best.team))


def test_the_second_pick_depends_on_the_first():
    after_3 = [c.team for c in rank_second_picks(1, 3, [2, 4, 5], PROFILES, config(), allow_unapproved=True).candidates]
    after_5 = [c.team for c in rank_second_picks(1, 5, [2, 3, 4], PROFILES, config(), allow_unapproved=True).candidates]
    assert after_3[0] == 4  # with 3 taken: 4 adds b and the c the alliance lacks
    assert after_5[0] == 3  # with 5 (already the best at c) taken: 3's b is worth most
    assert after_3[0] != after_5[0]


def test_the_chance_a_partner_is_gone_changes_the_first_pick_by_the_stated_formula():
    cfg = config()
    optimistic = rank_first_picks(1, [2, 3, 4, 5], PROFILES, cfg, EveryoneAvailable(), allow_unapproved=True)
    # Everyone else is likely to take 4 and 3 before this alliance picks again.
    probabilities = {2: 0.9, 3: 0.05, 4: 0.05, 5: 0.9}
    realistic = rank_first_picks(1, [2, 3, 4, 5], PROFILES, cfg, GivenProbabilities(probabilities),
                                 allow_unapproved=True)
    by_team = {c.team: c.value for c in realistic.candidates}
    # By hand for candidate 2: partners sorted by V(1, 2, d), each weighted by p_d and the chance all better ones left.
    pairs = sorted(((d, evaluate_lineup([PROFILES[1], PROFILES[2], PROFILES[d]], cfg).total) for d in (3, 4, 5)),
                   key=lambda x: -x[1])
    expected, none_left = 0.0, 1.0
    for d, value in pairs:
        expected += value * probabilities[d] * none_left
        none_left *= 1 - probabilities[d]
    expected += none_left * evaluate_lineup([PROFILES[1], PROFILES[2]], cfg).total
    assert by_team[2] == pytest.approx(expected)
    best_case = {c.team: c.value for c in optimistic.candidates}
    assert best_case[3] == best_case[4]  # as pairs, 3 and 4 complete the same alliance
    assert by_team[3] < best_case[3]  # its best partner is likely gone
    # 3's next-best partner (5) is likely to remain; 4's (2) completes a weaker alliance, so 3 is now clearly ahead.
    assert by_team[3] > by_team[4]
    with pytest.raises(ConfigError, match="no availability probability"):
        rank_first_picks(1, [2, 3, 6], {**PROFILES, 6: robot(6)}, cfg, GivenProbabilities(probabilities),
                         allow_unapproved=True)


# --- the backup robot ----------------------------------------------------------------------------------------------


def test_a_backup_is_worth_what_it_saves_when_an_active_robot_cannot_play():
    cfg = config()
    active = [robot(1, b=20, availability=0.9), robot(2, b=15, availability=0.8), robot(3, b=10, availability=1.0)]
    strong, weak = robot(4, b=12, availability=1.0), robot(5, b=2, availability=1.0)
    assert backup_value(active, strong, cfg) > backup_value(active, weak, cfg) > 0
    # By hand for the weak backup: it plays only when 1 or 2 is out (with lineup choice, it never displaces 3).
    always = [robot(1, b=20, availability=1.0), robot(2, b=15, availability=1.0), robot(3, b=10, availability=1.0)]
    assert backup_value(always, weak, cfg) == pytest.approx(0)  # nobody is ever out: a weaker backup adds nothing
    assert backup_value(always, robot(6, b=40, availability=1.0), cfg) == pytest.approx(40 - 10)  # it plays instead
    ranking = rank_backup_picks([1, 2, 3], [4, 5], {r.team: r for r in [*active, strong, weak]}, cfg,
                                allow_unapproved=True)
    assert [c.team for c in ranking.candidates] == [4, 5]


def test_short_handed_policy_and_missing_availability():
    plays = config()
    forfeits = config(alliance={"active_robots": 3, "roster_size": 4, "lineup_choice": True, "short_handed": "forfeits"})
    roster = [robot(1, b=20, availability=0.5), robot(2, b=15, availability=1.0), robot(3, b=10, availability=1.0)]
    assert roster_value(roster, plays) == pytest.approx(0.5 * 45 + 0.5 * 25)
    assert roster_value(roster, forfeits) == pytest.approx(0.5 * 45)
    with pytest.raises(ConfigError, match="no availability estimate"):
        roster_value([robot(1, b=1), robot(2, b=1, availability=1.0)], plays)
    no_backup = config(alliance={"active_robots": 3, "roster_size": 3, "lineup_choice": True,
                                 "short_handed": "plays_with_available"})
    with pytest.raises(ConfigError, match="no backup robot"):
        rank_backup_picks([1, 2, 3], [4], {t: robot(t, availability=1.0) for t in (1, 2, 3, 4)}, no_backup,
                          allow_unapproved=True)


# --- not active ----------------------------------------------------------------------------------------------------


def test_the_foundation_is_not_wired_into_the_api_the_live_draft_or_the_fallbacks():
    users = [path for folder in ("api", "workspaces", "data", "scripts")
             for path in (ROOT / folder).rglob("*.py") if "ml.alliance.optimizer" in path.read_text(encoding="utf-8")]
    assert users == []
    package = ROOT / "ml" / "alliance" / "optimizer"
    assert not list(package.rglob("*.json")) and not list(package.rglob("*.yaml"))  # no season configuration shipped
