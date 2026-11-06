"""P11A in Phase 11 (workspaces.alliance_plan): the draft record -> planner adapter, the snapshot folder, and the
withheld paths. Pure: the record is replayed from an in-memory log and the database read is replaced, so no
PostgreSQL is needed. Synthetic teams 1-24 (ranked by number) and synthetic season 9911 only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ml.alliance.planner import PlanWithheld, build_plan
from ml.alliance.snapshot import snapshot_filename
from tests.p11a_support import snapshot, truths, synthetic_registry  # noqa: F401 (autouse fixture)
from tests.test_phase11_draft_log import Log, setup
from workspaces import alliance_plan, live_draft
from workspaces import draft_recommendations as rec

EVENT = "9911syn"


def event_snapshot(**kwargs):
    """The synthetic event with teams renumbered 1-24, to match the record's synthetic setup."""
    truth = {i: v for i, v in enumerate(truths(24, 7).values(), start=1)}
    return snapshot(truth=truth, **kwargs)


@pytest.fixture(autouse=True)
def _fresh_cache():
    alliance_plan.clear_cache()
    yield
    alliance_plan.clear_cache()


def test_a_captain_at_its_turn_gets_the_same_pickable_teams_as_p11_fb1():
    log = Log(setup())
    log.captain(1, 1)
    view = log.view()
    pos = alliance_plan.position_from_view(view, 1)
    assert (pos.mode, pos.seed, pos.members, pos.picks_remaining, pos.turns_before) == ("captain", 1, (1,), 2, 0)
    ranked, unranked, excluded = rec.fallback_lists(view, 1, 1, [])
    assert set(pos.available) == set(ranked) | set(unranked)
    assert {t for t, _ in excluded} <= set(pos.unavailable)


def test_after_the_first_pick_is_recorded_the_plan_is_the_next_pick_for_that_alliance():
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 24)
    pos = alliance_plan.position_from_view(log.view(), 1)
    assert pos.members == (1, 24) and pos.picks_remaining == 1 and 24 not in pos.available
    assert pos.unavailable[24] == "picked"
    plan = build_plan(event_snapshot(), pos)
    assert plan["stage"] == "next_pick" and plan["record_seq"] == log.view().record_seq
    assert all(c["team_number"] not in (1, 24) for c in plan["cards"])


def test_a_projected_captain_plans_for_the_alliance_it_will_captain():
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)
    pos = alliance_plan.position_from_view(log.view(), 5)
    assert (pos.mode, pos.seed, pos.members) == ("projected_captain", 4, (5,))


def test_a_picked_team_on_an_alliance_is_on_alliance_not_captain():
    log = Log(setup())
    log.captain(1, 1)
    log.pick(1, 2)
    pos = alliance_plan.position_from_view(log.view(), 2)
    assert pos.mode == "on_alliance" and pos.members == (1, 2)


def test_a_team_that_is_not_selecting_gets_the_alliances_it_could_join():
    log = Log(setup())
    log.captain(1, 1)
    pos = alliance_plan.position_from_view(log.view(), 20)
    assert pos.mode == "non_captain" and pos.members == ()
    seeds = [s for s, _ in pos.other_alliances]
    assert seeds == sorted(seeds) and 1 in seeds
    assert dict(pos.other_alliances)[1] == (1,)
    plan = build_plan(event_snapshot(), pos)
    assert plan["invitation_likelihood"]["status"] == "withheld" and "cards" not in plan


def test_records_without_setup_or_needing_review_are_withheld():
    with pytest.raises(PlanWithheld) as refused:
        alliance_plan.position_from_view(Log().view(), 1)
    assert refused.value.code == "not_configured"
    log = Log(setup())  # the same flagged state as test_phase11_recommendations
    log.captain(1, 1)
    first = log.pick(1, 5)
    log.captain(2, 2)
    log.pick(2, 3)
    log.add("correct", {"target_action_id": first, "replacement": {"type": "pick", "seed": 1, "team": 3}})
    assert log.view().flagged
    with pytest.raises(PlanWithheld) as refused:
        alliance_plan.position_from_view(log.view(), 1)
    assert refused.value.code == "record_needs_review"


def _serve(monkeypatch, log):
    view = log.view()
    row = (7, "uid", EVENT, None, "tester")
    monkeypatch.setattr(live_draft, "load_view_with_previous", lambda database, context, record_id: (row, (view, None)))
    return SimpleNamespace(team_number=1, workspace_id=3)


def test_the_plan_is_withheld_without_a_snapshot_and_current_with_one(monkeypatch, tmp_path):
    log = Log(setup())
    log.captain(1, 1)
    context = _serve(monkeypatch, log)
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=None)
    assert out["status"] == "withheld" and out["withheld"]["code"] == "snapshot_unavailable" and out["plan"] is None
    assert out["experimental"] is True and out["source"] == "p11a_expected_score_plan"
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=str(tmp_path))
    assert out["withheld"]["code"] == "snapshot_unavailable"
    snap = event_snapshot()
    snap.save(tmp_path / snapshot_filename(snap))
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=str(tmp_path))
    assert out["status"] == "current" and out["plan"]["stage"] == "first_pick"
    assert out["plan"]["snapshot_id"] == snap.snapshot_id() and out["record_seq"] == log.view().record_seq
    assert out["plan"]["win_probability"]["status"] == "not_available"


def test_the_newest_snapshot_is_used_and_an_altered_one_is_refused(monkeypatch, tmp_path):
    log = Log(setup())
    log.captain(1, 1)
    context = _serve(monkeypatch, log)
    older, newer = event_snapshot(as_of_offset_hours=100), event_snapshot(as_of_offset_hours=200)
    older.save(tmp_path / snapshot_filename(older))
    path = tmp_path / snapshot_filename(newer)
    newer.save(path)
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=str(tmp_path))
    assert out["plan"]["snapshot_id"] == newer.snapshot_id()
    path.write_text(path.read_text().replace('"auto": ', '"auto": 1', 1))
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=str(tmp_path))
    assert out["status"] == "withheld" and out["withheld"]["code"] == "snapshot_invalid"


def test_an_unapproved_scoring_configuration_withholds_the_plan_but_not_the_profile(monkeypatch, tmp_path):
    log = Log(setup())
    log.captain(1, 1)
    context = _serve(monkeypatch, log)
    snap = event_snapshot(approved=False)
    snap.save(tmp_path / snapshot_filename(snap))
    out = alliance_plan.plan_for_record(None, context, 7, snapshot_dir=str(tmp_path))
    assert out["withheld"]["code"] == "scoring_config_not_approved"
    prof = alliance_plan.profile_for_record(None, context, 7, 5, snapshot_dir=str(tmp_path))
    assert prof["status"] == "current" and prof["profile"]["team_number"] == 5
    assert prof["profile"]["alliance_fit"] is None
    assert prof["profile"]["alliance_fit_absent_reason"].startswith("scoring_config_not_approved")
    missing = alliance_plan.profile_for_record(None, context, 7, 999, snapshot_dir=str(tmp_path))
    assert missing["withheld"]["code"] == "team_not_at_event"
