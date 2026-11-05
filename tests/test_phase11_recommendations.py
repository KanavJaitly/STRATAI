"""Phase 11: the live draft record's recommendations (workspaces.draft_recommendations; P11-Q1, P11-FB1).

The engine and the ordering are replaced by fakes, so no database is needed. Synthetic events only (teams ranked by
number; the fake ordering is a fixed permutation): nothing here is evidence about any real team.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone

import pytest

from ml.playoffs.selection import PickRecommendation, RankedPick, turn_order
from ml.playoffs.service import PickListResult, PlayoffModelsNotAccepted
from ml.views.event_analysis import M5V2Required
from tests.test_phase11_draft_log import Log, setup
from workspaces import draft_log as dl
from workspaces import draft_recommendations as rec

NOW = datetime(2030, 3, 2, 18, 0, tzinfo=timezone.utc)


class FakeEpa:
    provider = object()


def ordering(teams) -> rec.Ordering:
    return rec.Ordering(tuple(teams), "raw_epa", "validated", {}, NOW, "selection_moment", ())


@pytest.fixture
def engine_refuses(monkeypatch):
    def refuse(*args, **kwargs):
        raise PlayoffModelsNotAccepted("PX gates not passed: PX-1, PX-2, PX-4")
    monkeypatch.setattr(rec, "engine_pick_list", refuse)


@pytest.fixture
def strength(monkeypatch):
    """The fake P5-M4 ordering: team 24 strongest, then 23, ..., 1 (the reverse of rank)."""
    order = list(range(24, 0, -1))
    monkeypatch.setattr(rec, "event_ordering", lambda *a, **k: ordering(order))
    return order


def recommend(log: Log, team: int, previous: bool = True) -> rec.Recommendation:
    entries = log.entries
    return rec.recommend(None, "2030test", dl.replay(entries), dl.replay(entries[:-1]) if previous else None, team,
                         epa_source=FakeEpa(), ranking=None, playoff_models=None, now=lambda: NOW)


def test_when_the_engine_refuses_the_fallback_is_served_not_validated_with_the_refusal(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    out = recommend(log, team=1)
    assert out.status == "current" and out.source == rec.SOURCE_FALLBACK
    assert out.validation_status == "not_validated"
    assert out.engine_refusal == ("playoff_models_not_accepted", "PX gates not passed: PX-1, PX-2, PX-4")
    assert any(r.startswith("P11-FB1") for r in out.validation_reasons)
    assert out.primary.team_number == 24 and out.primary.p_win_event is None  # no probability, ever
    assert all(c.p_win_event is None for c in out.backups)


def test_backups_are_max_three_or_the_picks_before_the_next_turn(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    assert len(recommend(log, team=1).backups) == 3  # it is alliance 1's turn: m = 0
    log.pick(1, 24)
    out = recommend(log, team=1)
    assert out.turns_before == 14 and len(out.backups) == 14


def test_projected_captains_who_act_first_are_excluded_not_recommended(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)  # team 2 joins alliance 1; 3 captains alliance 2, 4 alliance 3, ...
    out = recommend(log, team=5)  # team 5 is projected to captain alliance 4
    assert out.seed == 4 and out.selecting_as == "projected_captain"
    excluded = dict(out.excluded)
    assert excluded[3] == "projected to captain alliance 2 before your turn"
    assert excluded[4] == "projected to captain alliance 3 before your turn"
    assert 6 not in excluded  # alliance 5 names its captain after alliance 4's turn
    listed = {out.primary.team_number, *(c.team_number for c in out.backups)}
    assert not listed & {1, 2, 3, 4, 5}


def test_no_unavailable_team_is_ever_recommended_through_a_whole_draft(engine_refuses, strength):
    log = Log(setup())
    for seed in turn_order(8, 2):
        view = log.view()
        if not view.alliances[seed - 1]:
            log.captain(seed, view.expected_captain()[0])
        for team in (1, 3, 9):  # several workspaces' views of the same room
            out = recommend(log, team=team)
            if out.status != "current":
                continue
            available, unavailable = log.view().availability()
            listed = [out.primary.team_number, *(c.team_number for c in out.backups)]
            assert set(listed) <= set(available), (seed, team)
            assert not set(listed) & set(unavailable)
            assert out.record_seq == log.view().record_seq
        available, _ = log.view().availability()
        log.pick(seed, next(t for t in strength if t in available))
    assert log.view().complete
    assert recommend(log, team=1).withheld[0] == "no_remaining_turn"


def test_a_declined_team_is_never_recommended(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    log.decline(1, 24)
    out = recommend(log, team=1)
    assert out.primary.team_number == 23
    assert out.movement == ["Team 24 declined alliance 1.", "Team 23 is now first."]


def test_movement_says_why_the_list_changed(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 24)
    log.captain(2, 2)
    out = recommend(log, team=3)  # team 3 is projected to captain alliance 3
    log.pick(2, 23)
    after = recommend(log, team=3)
    assert "Team 23 was picked by alliance 2." in after.movement
    assert after.primary.team_number == 22 and out.primary.team_number == 23


def test_recommendations_are_withheld_while_an_action_is_flagged(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    first = log.pick(1, 5)
    log.captain(2, 2)
    log.pick(2, 3)
    log.add("correct", {"target_action_id": first, "replacement": {"type": "pick", "seed": 1, "team": 3}})
    out = recommend(log, team=1)
    assert out.status == "withheld" and out.withheld[0] == "record_needs_review"
    assert out.primary is None


def test_a_team_that_is_not_selecting_gets_no_recommendation(engine_refuses, strength):
    log = Log(setup())
    log.captain(1, 1)
    assert recommend(log, team=20).withheld[0] == "team_not_selecting"


def test_an_ordering_refusal_withholds_the_fallback_rather_than_guessing(engine_refuses, monkeypatch):
    def refuse(*a, **k):
        raise M5V2Required("2030test")
    monkeypatch.setattr(rec, "event_ordering", refuse)
    log = Log(setup())
    log.captain(1, 1)
    out = recommend(log, team=1)
    assert out.status == "withheld" and out.withheld[0] == "model_not_loaded"
    assert out.engine_refusal[0] == "playoff_models_not_accepted"


def test_the_engine_is_used_unchanged_when_it_serves(monkeypatch, strength):
    def serve(database, event_key, seed, state, now, **kwargs):
        ranked = tuple(RankedPick(t, (1, t, 0), 0.30 - i / 100, 0.5, None) for i, t in enumerate((7, 24, 23, 22, 2)))
        return PickListResult(PickRecommendation(seed, ranked, (), None, "validated_playoff_success"), NOW,
                              "cd" * 32, None, "raw_epa", [])
    monkeypatch.setattr(rec, "engine_pick_list", serve)
    log = Log(setup())
    log.captain(1, 1)
    log.decline(1, 7)  # the engine's stale view of team 7 must not reach the list
    out = recommend(log, team=1)
    assert out.source == rec.SOURCE_ENGINE and out.validation_status == "validated_playoff_success"
    assert out.primary.team_number == 24 and out.primary.p_win_event == pytest.approx(0.29)
    assert 7 not in [c.team_number for c in out.backups]
    assert out.engine_refusal is None


def test_teams_missing_from_the_ordering_are_listed_unranked_never_recommended(engine_refuses, monkeypatch):
    monkeypatch.setattr(rec, "event_ordering", lambda *a, **k: ordering([24, 23, 22, 21, 20]))
    log = Log(setup())
    log.captain(1, 1)
    out = recommend(log, team=1)
    listed = {out.primary.team_number, *(c.team_number for c in out.backups)}
    assert listed <= {24, 23, 22, 21, 20}
    assert 19 in out.unranked_available and 19 not in listed


def test_the_warm_recalculation_is_far_under_the_two_second_target(engine_refuses, strength):
    """P11-Q3's warm path with the engine and ordering faked: the record-side work (replay + pool + lists) only.
    The DB-backed end-to-end measurement is scripts/phase11_replay.py's."""
    log = Log(setup())
    times = []
    for seed in turn_order(8, 2):
        view = log.view()
        if not view.alliances[seed - 1]:
            log.captain(seed, view.expected_captain()[0])
        started = time.perf_counter()
        recommend(log, team=1)
        times.append(time.perf_counter() - started)
        available, _ = log.view().availability()
        log.pick(seed, available[0])
    p95 = statistics.quantiles(times, n=20)[-1]
    assert p95 < 0.2, p95


def test_when_captains_may_not_join_higher_alliances_no_projected_captain_is_offered(engine_refuses, monkeypatch):
    """Review finding 1: the pool and the recommendations follow captain_may_accept_higher_alliance=False."""
    monkeypatch.setattr(rec, "event_ordering", lambda *a, **k: ordering([3, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12]))
    log = Log(setup(n_teams=12, n_alliances=4, picks_per_alliance=2, captain_may_accept_higher_alliance=False))
    log.captain(1, 1)
    available, unavailable = log.view().availability()
    assert {2, 3, 4} <= {t for t, r in unavailable.items() if r == "projected_captain"} and not {2, 3, 4} & set(available)
    out = recommend(log, team=1)
    listed = [out.primary.team_number, *(c.team_number for c in out.backups)]
    assert not {2, 3, 4} & set(listed)
    _, violation = log.append_checked("pick", {"seed": 1, "team": out.primary.team_number})
    assert violation is None  # the recommended primary is recordable


def test_an_ordering_before_the_selection_moment_is_withheld_not_computed_at_now(engine_refuses, monkeypatch):
    """Review finding 5: P11-FB1 orders at the selection moment only."""
    from datetime import timedelta

    monkeypatch.setattr(rec, "event_selection_moment", lambda database, event_key: NOW + timedelta(hours=1))
    monkeypatch.setattr(rec, "analyze_event", lambda *a, **k: pytest.fail("must not order before the moment"))
    log = Log(setup())
    log.captain(1, 1)
    out = rec.recommend(None, "2030test", log.view(), None, 1, epa_source=FakeEpa(), ranking=None,
                        playoff_models=None, now=lambda: NOW)
    assert out.status == "withheld" and out.withheld[0] == "selection_time_unavailable"
