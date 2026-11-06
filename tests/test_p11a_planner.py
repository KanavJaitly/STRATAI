"""P11A planner, snapshot and profile (spec B3, B5, B6, C, D, E, F2, G2, §14). Synthetic season 9911 only."""

from __future__ import annotations

import json
import socket

import pytest

from ml.alliance.contract import P11AProfileOut
from ml.alliance.planner import DraftPosition, PlanWithheld, build_plan
from ml.alliance.profile import team_profile
from ml.alliance.snapshot import EventSnapshot, SnapshotError
from tests.p11a_support import snapshot, truths, synthetic_registry  # noqa: F401 (autouse fixture)


def position(snap, team, *, members=None, available=None, unavailable=None, mode="captain", picks=2, seq=7):
    others = [t for t in snap.teams() if t != team]
    return DraftPosition(team, seq, mode, 1, tuple(members if members is not None else [team]), picks, 0,
                         tuple(available if available is not None else others), dict(unavailable or {}))


def test_no_or_unapproved_scoring_config_withholds_the_plan():
    snap = snapshot(with_config=False)
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, position(snap, snap.teams()[0]))
    assert refused.value.code == "scoring_config_not_approved"
    snap = snapshot(approved=False)
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, position(snap, snap.teams()[0]))
    assert refused.value.code == "scoring_config_not_approved"


def test_a_degenerate_fit_withholds_the_plan(monkeypatch):
    from ml.alliance import estimator
    snap = snapshot()
    real = estimator.noise_diagnostics
    monkeypatch.setattr(estimator, "noise_diagnostics",
                        lambda *a, **k: estimator.NoiseDiagnostics(True, 0.0, real(*a, **k).residual_df))
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, position(snap, snap.teams()[0]))
    assert refused.value.code == "estimator_fit_unreliable"


def test_a_flagged_collapse_screen_is_reported_non_authoritative_and_does_not_withhold():
    snap = snapshot(noise=0.5)  # low noise, accurate fit: the ratio screen fires
    plan = build_plan(snap, position(snap, snap.teams()[0]))
    screens = [d["collapse_screen"] for d in plan["fit_diagnostics"].values()]
    assert any(s["flagged"] for s in screens)
    assert all(s["status"] == "non_authoritative" and s["threshold"] == 0.05 for s in screens)
    assert plan["cards"] and not any(d["degenerate"] for d in plan["fit_diagnostics"].values())


def test_the_plan_carries_every_gate_label_and_no_probability():
    snap = snapshot()
    plan = build_plan(snap, position(snap, snap.teams()[0]))
    assert plan["objective"] == "expected_alliance_score" and plan["unit"] == "points"
    assert plan["win_probability"]["status"] == "not_available"
    assert plan["validation_status"] == "not_validated" and plan["interval_status"] == "not_calibrated"
    assert plan["thresholds_status"] == "candidate_unapproved" and plan["availability_model"] == "not_modelled"
    assert all(c["outcome"] == "unresolved" and c["reason"] in ("comparison_threshold_not_approved", "same_lineup")
               for c in plan["comparisons"])
    text = json.dumps(plan["cards"])
    assert "%" not in text and "chance of winning" not in text.replace("not a chance of winning", "")
    assert len(plan["known_limitations"]) >= 4


def _scenario_truth(our, a, b, base_seed=11):
    t = truths(24, base_seed)
    t[9901] = our
    t[9902] = a
    t[9903] = b
    return t


def _second_pick(snap, partner=9910):
    """Our alliance (9901) with a fixed first partner, choosing the third robot: A and B are compared directly, never
    as each other's best second (at the first pick both would share the lineup {us, A, B})."""
    available = [t for t in snap.teams() if t not in (9901, partner)]
    return position(snap, 9901, members=[9901, partner], available=available, picks=1)


def test_scenario_A_under_sum_rules_alliance_value_is_additive():
    """With only sum rules (no cap, no bonus binding), V is additive, so complementarity cannot change the order: the
    higher-contributing robot ranks higher whatever our own profile is, and the ranking equals the order of V.
    (Complementarity matters only through caps and bonuses; scenario B tests the cap.) Noise 6 is a realistic
    alliance-level residual; at very low noise the candidate collapse rule refuses the fit by design."""
    our = {"auto": 30.0, "teleop": 5.0, "endgame": 5.0}
    a = {"auto": 5.0, "teleop": 45.0, "endgame": 5.0}
    b = {"auto": 35.0, "teleop": 2.0, "endgame": 5.0}
    snap = snapshot(truth=_scenario_truth(our, a, b), noise=6.0, matches_per_team=16, seed=11)
    plan = build_plan(snap, _second_pick(snap))
    ranks = {c["team_number"]: c["rank"] for c in plan["cards"]}
    assert ranks[9902] < ranks.get(9903, len(snap.teams()))
    values = [c["expected_alliance_score"] for c in plan["cards"]]
    assert values == sorted(values, reverse=True)


def test_scenario_B_redundancy_under_a_cap_is_limited_by_the_cap():
    """Endgame is capped at 20 alliance points (2 climbs x 10). A has the larger individual total (75 vs 72) but its
    15 endgame points duplicate ours and the cap removes most of them; B's extra teleop is not capped. So B's
    alliance ranks higher than A's although A is the 'better robot' by individual total."""
    our = {"auto": 10.0, "teleop": 20.0, "endgame": 15.0}
    a = {"auto": 20.0, "teleop": 40.0, "endgame": 15.0}
    b = {"auto": 20.0, "teleop": 52.0, "endgame": 0.0}
    snap = snapshot(truth=_scenario_truth(our, a, b), noise=6.0, matches_per_team=16, seed=12)
    plan = build_plan(snap, _second_pick(snap))
    ranks = {c["team_number"]: c["rank"] for c in plan["cards"]}
    assert ranks[9903] < ranks[9902]  # uncapped teleop beats endgame points the cap mostly removes
    statements = next(c for c in plan["cards"] if c["team_number"] == 9902)["statements"]
    assert any("capped at 20" in s for s in statements)


def test_scenario_C_second_picks_are_conditional_on_the_first_and_update_after_it_is_recorded():
    snap = snapshot(seed=13)
    us = snap.teams()[0]
    plan = build_plan(snap, position(snap, us))
    first = plan["cards"][0]
    second_list = first["conditional_seconds"]
    assert all(s["team_number"] != first["team_number"] for s in second_list)
    lists = [tuple(s["team_number"] for s in c["conditional_seconds"][:3]) for c in plan["cards"][:3]]
    assert len(set(lists)) > 1 or len(plan["cards"]) < 2  # the lists differ by first pick
    available = [t for t in snap.teams() if t not in (us, first["team_number"])]
    after = build_plan(snap, position(snap, us, members=[us, first["team_number"]], available=available, picks=1))
    assert after["stage"] == "next_pick"
    got = {c["team_number"]: c["expected_alliance_score"] for c in after["cards"]}
    for s in second_list[:5]:
        assert got[s["team_number"]] == pytest.approx(s["expected_alliance_score"], abs=0.11)


def test_confirmed_unavailable_teams_never_appear_and_predictions_never_remove_teams():
    snap = snapshot(seed=14)
    us, gone = snap.teams()[0], snap.teams()[1:5]
    available = [t for t in snap.teams() if t not in (us, *gone)]
    plan = build_plan(snap, position(snap, us, available=available, unavailable={t: "picked" for t in gone}))
    seen = {c["team_number"] for c in plan["cards"]} | {s["team_number"] for c in plan["cards"]
                                                        for s in (c["conditional_seconds"] or [])}
    seen |= {t for combo in plan["backup_combinations"] for t in combo["picks"]}
    assert not seen & set(gone)
    assert plan["availability"]["predicted"] is None
    assert set(plan["availability"]["confirmed_available"]) == set(available)


def test_a_non_captain_gets_destinations_not_choices():
    snap = snapshot(seed=15)
    teams = snap.teams()
    us = teams[-1]
    others = ((1, (teams[0],)), (2, (teams[1], teams[2])))
    pos = DraftPosition(us, 3, "non_captain", None, (), 0, None, tuple(t for t in teams[3:] if t != us), {}, others)
    plan = build_plan(snap, pos)
    assert "cards" not in plan and len(plan["destinations"]) == 2
    assert plan["invitation_likelihood"] == {"status": "withheld", "reason": "pick_model_unavailable"}
    assert all(us in d["lineup"] for d in plan["destinations"] if d.get("lineup"))


def test_four_member_alliances_are_valued_by_the_best_three_robot_lineup():
    snap = snapshot(seed=16)
    t = snap.teams()
    members = [t[0], t[1], t[2]]
    available = t[3:]
    plan = build_plan(snap, position(snap, t[0], members=members, available=available, picks=1))
    assert plan["stage"] == "fourth_member"
    for card in plan["cards"]:
        assert len(card["lineup"]) == 3  # never four simultaneous robots
        assert card["lineup_gain"] >= -1e-9


def test_the_plan_is_deterministic_for_the_same_snapshot_and_record():
    snap = snapshot(seed=17)
    a = build_plan(snap, position(snap, snap.teams()[0]))
    b = build_plan(snap, position(snap, snap.teams()[0]))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_snapshots_round_trip_and_refuse_tampering_and_leakage(tmp_path):
    snap = snapshot(seed=18)
    path = tmp_path / "snap.json"
    sid = snap.save(path)
    again = EventSnapshot.load(path)
    assert again.snapshot_id() == sid
    data = json.loads(path.read_text())
    data["qual_rows"][0]["auto"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(SnapshotError) as refused:
        EventSnapshot.load(path)
    assert refused.value.code == "snapshot_integrity"
    late = snapshot(seed=18, as_of_offset_hours=1)  # most qualification rows are after as_of
    with pytest.raises(SnapshotError) as refused:
        late.validate()
    assert refused.value.code == "leakage"
    snap.priors[snap.teams()[0]] = {"source_event": "x", "end_date": "2099-03-05", "auto": [1, 1]}
    with pytest.raises(SnapshotError) as refused:
        snap.validate()
    assert refused.value.code == "leakage"


def test_a_plan_runs_from_a_saved_snapshot_with_the_network_disabled(tmp_path, monkeypatch):
    snap = snapshot(seed=19)
    path = tmp_path / "snap.json"
    snap.save(path)

    def no_network(*args, **kwargs):
        raise OSError("network disabled for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    offline = EventSnapshot.load(path)
    plan = build_plan(offline, position(offline, offline.teams()[0]))
    assert plan["cards"] and plan["snapshot_id"] == snap.snapshot_id()


def test_profiles_show_observed_alliance_matches_and_never_blame_a_robot():
    snap = snapshot(seed=20)
    team = snap.teams()[3]
    prof = P11AProfileOut.model_validate(team_profile(snap, team, our_team=snap.teams()[0]))  # the API contract
    assert prof.matches_played == len(prof.matches) > 0
    assert all(m.kind == "observed_alliance" and team not in m.partners for m in prof.matches)
    assert all(m.anomaly.status == "not_flagged" for m in prof.matches)
    assert prof.estimates.validation_status == "not_validated" and "not validated" in prof.estimates.note
    assert prof.estimates.n == prof.matches_played and prof.estimates.partners > 0
    assert all(0 <= c.w_eff <= 1 and c.sd > 0 for c in prof.estimates.components.values())
    assert prof.alliance_fit.unit == "points" and prof.alliance_fit_absent_reason is None
    assert prof.strengths_and_weaknesses_absent_reason and prof.as_of == snap.as_of
    assert prof.data_through is not None and prof.data_through < prof.as_of
    assert prof.prior is None and prof.prior_absent_reason  # the fixture has no earlier event: absent, not invented
    assert prof.scouting is None and prof.scouting_absent_reason
    assert prof.rank.status == "observed" and prof.rank.value is not None
    assert all(d.collapse_screen.status == "non_authoritative" for d in prof.fit_diagnostics.values())
    no_config = snapshot(seed=20, with_config=False)
    absent = P11AProfileOut.model_validate(team_profile(no_config, team, our_team=no_config.teams()[0]))
    assert absent.alliance_fit is None and absent.alliance_fit_absent_reason.startswith("scoring_config_not_approved")
    with pytest.raises(PlanWithheld):
        team_profile(snap, 1, our_team=None)


def test_a_profile_shows_a_prior_and_scouting_when_the_snapshot_has_them():
    snap = snapshot(seed=21)
    team = snap.teams()[2]
    snap.priors[team] = {"source_event": "9911early", "end_date": "2099-02-20", "auto": [11.0, 4.0],
                         "teleop": [24.0, 9.0], "endgame": [6.0, 2.0]}
    snap.scouting[team] = {"kind": "scouted", "defense": 3.5, "defense_n": 4, "feeding": None, "feeding_n": 0,
                           "computed_at": "2099-03-01T12:00:00+00:00"}
    prof = P11AProfileOut.model_validate(team_profile(snap, team))
    assert prof.prior.source_event == "9911early" and prof.prior.components["auto"].variance == 4.0
    assert prof.scouting.defense == 3.5 and prof.scouting.feeding is None  # missing stays missing
    assert prof.alliance_fit is None and prof.alliance_fit_absent_reason
