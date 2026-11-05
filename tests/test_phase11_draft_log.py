"""Phase 11: the live draft record's log and replay (workspaces.draft_log). Pure, no database.

Synthetic events only (teams 1-24 ranked by number): nothing here is evidence about any real team or event.
"""

from __future__ import annotations

import itertools

import pytest

from ml.playoffs.selection import turn_order
from workspaces import draft_log as dl
from workspaces.draft_log import DraftLogError, DraftRules, DraftSetup, LogEntry

_ids = itertools.count(1)


def rules(**overrides) -> DraftRules:
    values = dict(n_alliances=8, picks_per_alliance=2, declined_team_may_be_picked_later=False,
                  declined_team_may_become_captain=True, captain_may_accept_higher_alliance=True, backup_robots=False,
                  captain_rule_established=True, source="approved_ruleset", ruleset_sha256="ab" * 32)
    values.update(overrides)
    return DraftRules(**values)


def setup(n_teams: int = 24, ranks: bool = True, pool: bool = True, **rule_overrides) -> DraftSetup:
    teams = list(range(1, n_teams + 1))
    return DraftSetup(rules(**rule_overrides), {t: t for t in teams} if ranks else None,
                      tuple(teams) if pool else None)


class Log:
    """A record under construction: each call appends one entry."""

    def __init__(self, s: DraftSetup | None = None) -> None:
        self.entries: list[LogEntry] = []
        if s is not None:
            self.add("configure", s.to_json())

    def add(self, type_: str, payload: dict | None = None, override: str | None = None) -> str:
        action_id = f"a{next(_ids)}"
        self.entries.append(LogEntry(action_id, len(self.entries) + 1, type_, payload or {}, override, "tester"))
        return action_id

    def captain(self, seed, team, override=None):
        return self.add("captain", {"seed": seed, "team": team}, override)

    def pick(self, seed, team, override=None):
        return self.add("pick", {"seed": seed, "team": team}, override)

    def decline(self, seed, team, override=None):
        return self.add("decline", {"seed": seed, "team": team}, override)

    def view(self) -> dl.DraftView:
        return dl.replay(self.entries)

    def append_checked(self, type_, payload, override=None):
        """What the service does: check, then keep the entry only if it is accepted."""
        entry = LogEntry(f"a{next(_ids)}", len(self.entries) + 1, type_, payload, override, "tester")
        view, violation = dl.check_append(self.entries, entry)
        if violation is None:
            self.entries.append(entry)
        return view, violation


def run_standard_draft(log: Log, n: int = 8, picks: int = 2) -> None:
    """Every captain picks the best-ranked available team; captains are named as the rules name them."""
    for seed in turn_order(n, picks):
        view = log.view()
        if not view.alliances[seed - 1]:
            expected, _ = view.expected_captain()
            log.captain(seed, expected)
            view = log.view()
        available, _ = view.availability()
        log.pick(seed, available[0] if available[0] not in view.alliances[seed - 1] else available[1])


def test_a_full_serpentine_draft_replays_to_exactly_the_recorded_state():
    log = Log(setup())
    run_standard_draft(log)
    view = log.view()
    assert view.complete and not view.flagged
    # Captain 1 picks 2, so 3 captains alliance 2, which picks 4, and so on down. Round 2 runs in reverse.
    assert view.alliances[0][:2] == (1, 2)
    assert view.alliances[1][:2] == (3, 4)
    assert view.alliances[7][:2] == (15, 16)
    assert view.alliances[7][2] == 17 and view.alliances[0][2] == 24  # serpentine: seed 8 picks first in round 2
    assert view.picks_made == 16
    assert all(a.status == dl.ACCEPTED for a in view.effective)


def test_the_state_at_any_point_is_the_replay_of_that_prefix():
    log = Log(setup())
    run_standard_draft(log)
    full = log.view()
    for k in range(1, len(log.entries) + 1):
        prefix = dl.replay(log.entries[:k])
        assert prefix.record_seq == k
        assert prefix.picks_made == sum(1 for e in log.entries[:k] if e.type == "pick")
    assert dl.replay(list(reversed(log.entries))).alliances == full.alliances  # sequence order, not list order


def test_captain_promotion_when_a_higher_seed_picks_a_projected_captain():
    log = Log(setup())
    log.captain(1, 1)
    assert log.view().projected_captains()[2] == 2
    log.pick(1, 2)  # team 2 (projected captain of alliance 2) joins alliance 1
    view = log.view()
    assert view.acting_seed() == 2
    assert view.expected_captain() == (3, None)  # the next-ranked available team is promoted
    _, violation = log.append_checked("captain", {"seed": 2, "team": 2})
    assert violation.code == "team_on_alliance"
    _, violation = log.append_checked("captain", {"seed": 2, "team": 4})
    assert violation.code == "wrong_captain" and "team 3" in violation.message


@pytest.mark.parametrize("type_,payload,code", [
    ("pick", {"seed": 2, "team": 5}, "wrong_turn"),
    ("pick", {"seed": 1, "team": 1}, "team_on_alliance"),
    ("pick", {"seed": 1, "team": 99}, "team_not_in_pool"),
    ("captain", {"seed": 1, "team": 2}, "captain_already_named"),
    ("pick", {"seed": 9, "team": 5}, "unknown_alliance"),
    ("backup", {"team": 20}, "backups_not_used"),
])
def test_impossible_actions_are_refused_with_a_reason(type_, payload, code):
    log = Log(setup())
    log.captain(1, 1)
    _, violation = log.append_checked(type_, payload)
    assert violation is not None and violation.code == code
    assert len(log.entries) == 2  # nothing recorded


def test_a_pick_needs_its_captain_first():
    log = Log(setup())
    _, violation = log.append_checked("pick", {"seed": 1, "team": 2})
    assert violation.code == "captain_not_named"


def test_a_declined_team_cannot_be_picked_later_but_may_still_captain_when_the_rules_say_so():
    log = Log(setup())
    log.captain(1, 1)
    log.decline(1, 2)  # team 2 declines alliance 1
    view = log.view()
    available, unavailable = view.availability()
    assert 2 not in available and unavailable[2] == "declined"
    _, violation = log.append_checked("pick", {"seed": 1, "team": 2})
    assert violation.code == "team_declined"
    log.pick(1, 3)
    assert log.view().expected_captain() == (2, None)  # declined_team_may_become_captain = True


def test_consecutive_declines_do_not_advance_the_turn():
    log = Log(setup())
    log.captain(1, 1)
    for team in (2, 3, 4):
        _, violation = log.append_checked("decline", {"seed": 1, "team": team})
        assert violation is None
    view = log.view()
    assert view.acting_seed() == 1 and view.picks_made == 0 and set(view.declined) == {2, 3, 4}


def test_a_declined_team_is_skipped_for_captain_when_the_rules_forbid_it():
    log = Log(setup(declined_team_may_become_captain=False))
    log.captain(1, 1)
    log.decline(1, 2)
    log.pick(1, 3)
    assert log.view().expected_captain() == (4, None)


def test_an_unestablished_decline_rule_is_never_guessed_where_it_decides_the_captain():
    log = Log(setup(declined_team_may_become_captain=None))
    log.captain(1, 1)
    log.decline(1, 2)
    log.pick(1, 3)
    expected, why = log.view().expected_captain()
    assert expected is None and why.code == "captain_rule_not_established"
    _, violation = log.append_checked("captain", {"seed": 2, "team": 2})
    assert violation.code == "captain_rule_not_established"
    _, violation = log.append_checked("captain", {"seed": 2, "team": 2}, override="the emcee named team 2")
    assert violation is None
    assert log.view().effective[-1].status == dl.OVERRIDDEN


def test_an_override_is_recorded_as_an_override_with_its_reason():
    log = Log(setup())
    log.captain(1, 1)
    log.decline(1, 2)
    _, violation = log.append_checked("pick", {"seed": 1, "team": 2}, override="event-specific rule")
    assert violation is None
    last = log.view().effective[-1]
    assert last.status == dl.OVERRIDDEN and last.override_reason == "event-specific rule"
    assert last.violation.code == "team_declined"
    history = log.view().history[-1]
    assert history.entry.override_reason == "event-specific rule"


def test_an_override_never_makes_an_impossible_state():
    log = Log(setup())
    log.captain(1, 1)
    _, violation = log.append_checked("pick", {"seed": 1, "team": 1}, override="mistake")
    assert violation.code == "team_on_alliance"
    assert len(log.entries) == 2


def test_undo_gives_the_state_without_the_last_action_and_keeps_it_in_history():
    log = Log(setup())
    log.captain(1, 1)
    picked = log.pick(1, 2)
    log.add("undo", {"target_action_id": picked})
    view = log.view()
    assert view.alliances[0] == (1,) and view.picks_made == 0
    item = next(h for h in view.history if h.entry.action_id == picked)
    assert not item.in_effect and item.superseded_by == log.entries[-1].action_id


def test_undo_only_removes_the_most_recent_action():
    log = Log(setup())
    captain = log.captain(1, 1)
    log.pick(1, 2)
    with pytest.raises(DraftLogError) as refused:
        dl.check_append(log.entries, LogEntry("u", 99, "undo", {"target_action_id": captain}))
    assert refused.value.code == "not_last_action"


def test_a_correction_equals_recording_the_corrected_sequence_originally():
    corrected = Log(setup())
    corrected.captain(1, 1)
    wrong = corrected.pick(1, 5)
    corrected.captain(2, 2)
    corrected.pick(2, 3)
    corrected.add("correct", {"target_action_id": wrong, "replacement": {"type": "pick", "seed": 1, "team": 4}})

    original = Log(setup())
    original.captain(1, 1)
    original.pick(1, 4)
    original.captain(2, 2)
    original.pick(2, 3)

    a, b = corrected.view(), original.view()
    assert a.alliances == b.alliances and a.declined == b.declined and a.picks_made == b.picks_made
    assert [e.action for e in a.effective] == [e.action for e in b.effective]
    assert len(a.history) == len(b.history) + 1  # both versions are kept
    assert not next(h for h in a.history if h.entry.action_id == wrong).in_effect


def test_a_correction_that_invalidates_a_later_action_flags_it():
    log = Log(setup())
    log.captain(1, 1)
    first = log.pick(1, 5)
    log.captain(2, 2)
    log.pick(2, 3)
    # The first pick is corrected to team 3, which alliance 2 picked later: that later pick is now impossible.
    view, violation = log.append_checked("correct", {"target_action_id": first,
                                                     "replacement": {"type": "pick", "seed": 1, "team": 3}})
    assert violation is None
    flagged = view.flagged
    assert len(flagged) == 1 and flagged[0].action.team == 3 and flagged[0].action.seed == 2
    assert flagged[0].status == dl.NOT_APPLIED and flagged[0].violation.code == "team_on_alliance"


def test_a_correction_to_nothing_removes_an_action_that_did_not_happen():
    log = Log(setup())
    log.captain(1, 1)
    ghost = log.decline(1, 2)
    log.pick(1, 3)
    log.add("correct", {"target_action_id": ghost, "replacement": None})
    view = log.view()
    assert 2 not in view.declined and view.alliances[0] == (1, 3)


def test_a_correction_whose_replacement_breaks_the_rules_is_refused_without_an_override():
    log = Log(setup())
    log.captain(1, 1)
    pick = log.pick(1, 2)
    _, violation = log.append_checked("correct", {"target_action_id": pick,
                                                  "replacement": {"type": "pick", "seed": 3, "team": 2}})
    assert violation.code == "wrong_turn"


def test_a_new_configuration_revalidates_every_draft_action():
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)
    smaller = DraftSetup(rules(), {t: t for t in range(3, 25)}, tuple(range(3, 25)))  # 1 and 2 not in the pool
    log.add("configure", smaller.to_json())
    codes = {a.violation.code for a in log.view().flagged}
    assert codes == {"team_not_in_pool"}


def test_backups_follow_the_rules_and_come_after_the_draft():
    log = Log(setup(n_teams=14, n_alliances=4, picks_per_alliance=2, backup_robots=True))
    _, violation = log.append_checked("backup", {"team": 13})
    assert violation.code == "draft_incomplete"
    run_standard_draft(log, n=4, picks=2)
    _, violation = log.append_checked("backup", {"team": 13, "seed": 1})
    assert violation is None
    _, unavailable = log.view().availability()
    assert unavailable[13] == "backup"
    _, violation = log.append_checked("backup", {"team": 1})
    assert violation.code == "team_on_alliance"


def test_an_event_with_fewer_teams_than_picks_cannot_be_completed_and_says_why():
    log = Log(setup(n_teams=10, n_alliances=4, picks_per_alliance=2))  # needs 12 teams
    for seed in turn_order(4, 2):
        view = log.view()
        if not view.alliances[seed - 1]:
            expected, why = view.expected_captain()
            if expected is None:
                assert why.code == "no_eligible_captain"
                break
            log.captain(seed, expected)
        available, _ = log.view().availability()
        if not available:
            _, violation = log.append_checked("pick", {"seed": seed, "team": 1})
            assert violation.code == "team_on_alliance"
            break
        log.pick(seed, available[0])
    assert not log.view().complete


def test_without_ranks_the_captain_is_unchecked_not_refused():
    log = Log(setup(ranks=False))
    _, violation = log.append_checked("captain", {"seed": 1, "team": 7})
    assert violation is None
    assert any("captain_unchecked" in note for note in log.view().effective[0].notes)
    assert log.view().projected_captains()[2] is None


def test_without_a_pool_teams_are_unchecked():
    log = Log(DraftSetup(rules(), None, None, ("rankings_unavailable", "roster_unavailable")))
    _, violation = log.append_checked("captain", {"seed": 1, "team": 7})
    assert violation is None
    assert any("team_unchecked" in note for note in log.view().effective[0].notes)


def test_a_captain_barred_from_higher_alliances_cannot_be_picked_by_one():
    log = Log(setup(captain_may_accept_higher_alliance=False))
    log.captain(1, 1)
    _, violation = log.append_checked("pick", {"seed": 1, "team": 2})
    assert violation.code == "captain_not_pickable"
    _, violation = log.append_checked("pick", {"seed": 1, "team": 9})
    assert violation is None


def test_close_and_reopen_are_state_and_history():
    log = Log(setup())
    log.add("close")
    assert log.view().closed
    log.add("reopen")
    view = log.view()
    assert not view.closed and [h.summary for h in view.history][-2:] == ["Record closed", "Record reopened"]


def test_the_setup_round_trips_and_malformed_ones_are_refused():
    s = setup()
    assert DraftSetup.from_json(s.to_json()) == s
    with pytest.raises(DraftLogError):
        DraftSetup.from_json({"rules": {**s.rules.to_json(), "backup_robots": None}})
    with pytest.raises(DraftLogError):
        DraftSetup.from_json({"rules": {**s.rules.to_json(), "n_alliances": 1}})


def test_unknown_entries_have_no_effect_in_lenient_replay_and_are_refused_strictly():
    log = Log(setup())
    log.add("teleport", {"team": 1})
    view = log.view()
    assert not view.history[-1].in_effect and view.history[-1].summary.startswith("No effect")
    with pytest.raises(DraftLogError):
        dl.replay(log.entries, strict=True)


def test_the_board_lists_available_teams_without_any_unavailable_one():
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)
    log.captain(2, 3)
    log.decline(2, 4)
    board = dl.view_json(log.view(), team_number=1)
    available = {a["team_number"] for a in board["available"]}
    unavailable = {u["team_number"]: u["reason"] for u in board["unavailable"]}
    assert not available & set(unavailable)
    assert unavailable == {1: "captain", 2: "picked", 3: "captain", 4: "declined"}
    assert board["turn"] == {"index": 1, "round": 1, "seed": 2, "captain_named": True, "expected_captain": None,
                             "expected_captain_reason": None}
    # Team 4 declined, but these rules let a declined team captain, so it is alliance 3's projected captain.
    assert board["alliances"][2]["projected_captain"] == 4
    assert board["alliances"][3]["projected_captain"] == 5
    assert next(a for a in board["available"] if a["team_number"] == 5)["projected_captain_of"] == 4


def test_turns_before_counts_other_alliances_picks_until_a_seed_acts_again():
    log = Log(setup())
    log.captain(1, 1)
    view = log.view()
    assert view.turns_before(1) == 0
    assert view.turns_before(8) == 7
    log.pick(1, 2)
    assert log.view().turns_before(1) == 14  # seeds 2-8, then 8-2 in round 2


def test_a_superseded_setup_is_shown_as_superseded_in_the_history():
    """Review finding 10: the latest configure governs; the history says the earlier one no longer does."""
    log = Log(setup())
    log.add("configure", setup().to_json())
    history = log.view().history
    assert [h.in_effect for h in history] == [False, True]
    assert history[0].superseded_by == history[1].entry.action_id
