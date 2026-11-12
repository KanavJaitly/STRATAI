"""P11A acceptance criteria and scenarios that had no dedicated test (docs/p11a_requirements_map.md).

Each test names the spec item it asserts. SYNTHETIC season 9911 and synthetic teams only: nothing here is a real game,
a real rule or evidence about a real team. The assertions derive from the configuration's mechanics, never from
hard-coded preferences (spec §19).
"""

from __future__ import annotations

import itertools
import json
from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from ml.alliance import planner
from ml.alliance.contract import P11APlanOut
from ml.alliance.planner import DraftPosition, build_plan
from ml.alliance.profile import team_profile
from ml.alliance.scoring_config import COMPONENTS, ResolvedScoring, expected_component_points
from ml.alliance.snapshot import EventSnapshot, QualRow, snapshot_filename
from ml.playoffs.selection import turn_order
from tests.p11a_support import (T0, approve, game_spec, scoring_config, snapshot, synthetic_registry,  # noqa: F401
                                truths, write_registry)
from tests.test_phase11_draft_log import Log, setup
from workspaces import alliance_plan, live_draft


def position(snap, team, *, members=None, available=None, picks=2, seq=7, mode="captain"):
    others = [t for t in snap.teams() if t != team]
    return DraftPosition(team, seq, mode, 1, tuple(members if members is not None else [team]), picks, 0,
                         tuple(available if available is not None else others), {})


# --- criterion 4: V has exactly the configuration's terms ---------------------------------------------------------


@pytest.mark.parametrize("fouls", ["event_mean", "excluded"])
def test_criterion_4_V_is_exactly_the_configured_component_terms_plus_declared_fouls(tmp_path, fouls):
    data = scoring_config(approved=False).model_dump(mode="json")
    data["fouls"] = fouls
    config = approve(type(scoring_config())(**data))
    snap = snapshot()
    snap.scoring_config = config.model_dump(mode="json")
    (tmp_path / "9911.json").write_text(config.model_dump_json())
    model = planner._model(snap, planner.EstimatorPolicy(), tmp_path)
    assert set(model.scoring.rules) == set(COMPONENTS) == {r.component for r in config.rules}
    resolved = ResolvedScoring.resolve(config, game_spec())
    rng = np.random.default_rng(3)
    lineups = np.array([rng.choice(len(snap.teams()), 3, replace=False) for _ in range(25)])
    expected = sum(expected_component_points(resolved.rules[c], model.fits[c].mean[lineups].sum(axis=1),
                                             model.fits[c].cov[lineups[:, :, None], lineups[:, None, :]].sum(axis=(1, 2))
                                             + model.fits[c].sigma2) for c in COMPONENTS)
    fouls_term = snap.mean_fouls() if fouls == "event_mean" else 0.0
    assert np.allclose(model.value(lineups), expected + fouls_term, rtol=0, atol=1e-9)


# --- criterion 8 / Scenario D: positions follow turn_order --------------------------------------------------------


def test_criterion_8_seeds_1_and_8_have_their_own_turn_horizons_from_turn_order():
    log = Log(setup())
    log.captain(1, 1)
    view = log.view()
    order = turn_order(8, 2)
    first = alliance_plan.position_from_view(view, 1)
    eighth = alliance_plan.position_from_view(view, 8)  # the projected captain of seed 8
    assert (first.seed, eighth.seed) == (1, 8)
    assert first.turns_before == order.index(1) == 0
    assert eighth.turns_before == order.index(8) == 7
    horizons = {s: [i for i, x in enumerate(order) if x == s] for s in (1, 8)}
    assert horizons == {1: [0, 15], 8: [7, 8]}  # serpentine: seed 8 picks twice in a row, seed 1 waits 15 picks
    assert view.turns_before(1) == first.turns_before and view.turns_before(8) == eighth.turns_before
    for pos in (first, eighth):
        assert pos.team_number not in pos.available
    snap = snapshot(truth={i: v for i, v in enumerate(truths(24, 7).values(), start=1)})
    plans = {s: build_plan(snap, p) for s, p in ((1, first), (8, eighth))}
    assert (plans[1]["seed"], plans[1]["turns_before"]) == (1, 0)
    assert (plans[8]["seed"], plans[8]["turns_before"]) == (8, 7)  # each plan states its own horizon


# --- criterion 22 / Scenario R: joint uncertainty -----------------------------------------------------------------


def test_criterion_22_the_capped_value_uses_the_full_joint_variance_and_dropping_cross_terms_is_detectable():
    snap = snapshot(noise=6.0, matches_per_team=8, seed=21)
    model = planner._model(snap, planner.EstimatorPolicy())
    fit = model.fits["endgame"]
    rule = model.scoring.rules["endgame"]
    assert rule.cap_points is not None  # the synthetic endgame is capped (2 x climb)
    teams = list(range(len(fit.teams)))
    corr = fit.cov / np.sqrt(np.outer(np.diag(fit.cov), np.diag(fit.cov)))
    i, j = np.unravel_index(np.argmax(np.abs(corr - np.eye(len(teams)))), corr.shape)  # most correlated pair
    k = next(t for t in teams if t not in (i, j))
    lineup = np.array([[i, j, k]])
    a = np.zeros(len(teams))
    a[[i, j, k]] = 1.0
    full = float(a @ fit.cov @ a)
    diagonal = float(a @ np.diag(np.diag(fit.cov)) @ a)
    assert abs(full - diagonal) > 1e-6  # the cross-robot terms are not zero on these inputs
    mean = float(fit.mean[[i, j, k]].sum())
    with_terms = expected_component_points(rule, np.array([mean]), np.array([full + fit.sigma2]))[0]
    without = expected_component_points(rule, np.array([mean]), np.array([diagonal + fit.sigma2]))[0]
    used = sum(expected_component_points(model.scoring.rules[c], model.fits[c].mean[lineup].sum(axis=1),
                                         np.array([float(a @ model.fits[c].cov @ a) + model.fits[c].sigma2]))[0]
               for c in COMPONENTS) + model.fouls
    assert float(model.value(lineup)[0]) == pytest.approx(used, abs=1e-9)  # AS-1 uses a'Σa, cross terms included
    assert with_terms != pytest.approx(without, abs=1e-6)  # so dropping them would be detected
    # Monte Carlo reference for the capped component (high-run, its own MC error recorded)
    draws = np.random.default_rng(5).normal(mean, np.sqrt(full + fit.sigma2), 400_000)
    mc = np.minimum(draws, rule.cap_points)
    assert with_terms == pytest.approx(mc.mean(), abs=4 * mc.std() / np.sqrt(mc.size))


# --- criterion 23 / Scenario S: common random numbers ---------------------------------------------------------


def test_criterion_23_comparisons_of_lineups_sharing_members_use_common_random_numbers():
    snap = snapshot(seed=4)
    model = planner._model(snap, planner.EstimatorPolicy())
    teams = snap.teams()
    a, b = [teams[0], teams[1], teams[2]], [teams[0], teams[1], teams[3]]  # share two members
    common = planner._draws(model, "crn", 4000)
    out = planner._compare(model, common, a, b)
    other = planner._draws(model, "independent", 4000)
    va = planner._value_draws(model, np.array([[model.index[t] for t in a]]), common)
    vb_independent = planner._value_draws(model, np.array([[model.index[t] for t in b]]), other)
    vb_common = planner._value_draws(model, np.array([[model.index[t] for t in b]]), common)
    crn = va - vb_common
    assert out["delta_interval_80"] == [round(float(np.percentile(crn, 10)), 2), round(float(np.percentile(crn, 90)), 2)]
    assert out["p_delta_positive"] == round(float((crn > 0).mean()), 3)  # Δ is taken draw by draw (common draws)
    independent_width = float(np.percentile(va - vb_independent, 90) - np.percentile(va - vb_independent, 10))
    crn_width = out["delta_interval_80"][1] - out["delta_interval_80"][0]
    assert crn_width < independent_width  # the shared members' uncertainty cancels only with common draws
    assert out["outcome"] == "unresolved" and out["reason"] == "comparison_threshold_not_approved"


# --- criterion 19 / Scenario O: weak identifiability -----------------------------------------------------------


def _always_together_snapshot(seed=31):
    """24 synthetic teams; 9901 and 9902 are always on the same alliance, every match they play."""
    rng = np.random.default_rng(seed)
    truth = truths(24, seed)
    teams = sorted(truth)
    pair, others = (9901, 9902), [t for t in teams if t not in (9901, 9902)]
    rows = []
    for m in range(60):
        if m % 3 == 0:
            red = (*pair, int(rng.choice(others)))
            blue = tuple(int(x) for x in rng.choice([t for t in others if t not in red], 3, replace=False))
        else:
            six = [int(x) for x in rng.choice(others, 6, replace=False)]
            red, blue = tuple(six[:3]), tuple(six[3:])
        for color, group in (("red", red), ("blue", blue)):
            parts = {c: max(0.0, sum(truth[t][c] for t in group) + rng.normal(0, 6)) for c in COMPONENTS}
            rows.append(QualRow(f"9911syn_qm{m + 1}", (T0 + timedelta(minutes=7 * m)).isoformat(), color,
                                tuple(sorted(group)), round(parts["auto"], 1), round(parts["teleop"], 1),
                                round(parts["endgame"], 1), 0.0, round(sum(parts.values()), 1)))
    return EventSnapshot(event_key="9911syn", season=9911, start_date="2099-03-01",
                         as_of=(T0 + timedelta(hours=100)).isoformat(), qual_rows=rows, roster=teams,
                         ranks=None, provenance={"source": "SYNTHETIC test fixture"},
                         scoring_config=scoring_config().model_dump(mode="json"),
                         game_spec=game_spec().model_dump(mode="json"))


def test_criterion_19_two_robots_that_share_every_match_are_both_weakly_identified():
    fits = _always_together_snapshot().fit()
    for c in COMPONENTS:
        diag = {d.team: d for d in fits[c].diagnostics}
        for team in (9901, 9902):
            assert "weakly_identified" in diag[team].labels, (c, team, diag[team])
            assert diag[team].max_abs_corr > 0.5  # the reason: their estimates are strongly correlated


# --- criterion 18 / Scenario N: a backup robot is never part of an expected score ----------------------------


def test_criterion_18_a_backup_is_unavailable_and_never_in_a_lineup():
    log = Log(setup(n_teams=30, backup_robots=True))
    for s in range(1, 9):
        log.captain(s, s)
        log.pick(s, 8 + s)
    for s in range(8, 0, -1):
        log.pick(s, 25 - s)  # round two, serpentine: seed 8 picks 17 ... seed 1 picks 24
    log.add("backup", {"team": 25})
    view = log.view()
    assert not view.flagged and 25 in view.backups
    captain, outsider = (alliance_plan.position_from_view(view, t) for t in (1, 26))
    assert captain.mode == "no_remaining_turn" and outsider.mode == "non_captain"
    for pos in (captain, outsider):
        assert 25 not in pos.available and pos.unavailable[25] == "backup"
    truth = {i: v for i, v in enumerate(truths(30, 7).values(), start=1)}
    snap = snapshot(truth=truth, n_teams=30)
    plan = build_plan(snap, outsider)
    # backups are recorded only once every pick is made (draft_log), so no alliance has a turn left to value anyone
    assert outsider.other_alliances == () and plan["destinations"] == []
    with pytest.raises(planner.PlanWithheld) as refused:
        build_plan(snap, captain)
    assert refused.value.code == "no_remaining_turn"


# --- Scenario B, uncapped run -----------------------------------------------------------------------------------


def test_scenario_B_uncapped_redundancy_adds_its_full_contribution(tmp_path):
    """The same three robots as the capped Scenario B, with endgame uncapped: A's duplicated endgame now counts in
    full, and A (75 total) ranks above B (72 total), the reverse of the capped result."""
    our = {"auto": 10.0, "teleop": 20.0, "endgame": 15.0}
    a = {"auto": 20.0, "teleop": 40.0, "endgame": 15.0}
    b = {"auto": 20.0, "teleop": 52.0, "endgame": 0.0}
    t = truths(24, 11)
    t[9901], t[9902], t[9903] = our, a, b
    snap = snapshot(truth=t, noise=6.0, matches_per_team=16, seed=12)
    uncapped = scoring_config(endgame_cap_count=None)
    snap.scoring_config = uncapped.model_dump(mode="json")
    (tmp_path / "9911.json").write_text(uncapped.model_dump_json())
    available = [x for x in snap.teams() if x not in (9901, 9910)]
    plan = build_plan(snap, position(snap, 9901, members=[9901, 9910], available=available, picks=1),
                      scoring_dir=tmp_path)
    cards = {c["team_number"]: c for c in plan["cards"]}
    model = planner._model(snap, planner.EstimatorPolicy(), tmp_path)
    for team in (9902, 9903):  # uncapped: V is the plain sum of the three robots' means (plus fouls)
        idx = [model.index[x] for x in (9901, 9910, team)]
        additive = sum(float(model.fits[c].mean[idx].sum()) for c in COMPONENTS) + model.fouls
        assert cards[team]["expected_alliance_score"] == pytest.approx(additive, abs=0.06)
    assert cards[9902]["rank"] < cards[9903]["rank"]
    assert not any("capped" in s for s in cards[9902]["statements"])


# --- criterion 6 / Scenario C: the recorded first pick's list is the conditional list ------------------------------


def test_criterion_6_after_the_first_pick_the_list_equals_that_cards_conditional_list():
    snap = snapshot(seed=13)
    us = snap.teams()[0]
    first = build_plan(snap, position(snap, us))
    for card in first["cards"][:planner.TOP_K]:
        c = card["team_number"]
        after = build_plan(snap, position(snap, us, members=[us, c], picks=1,
                                          available=[t for t in snap.teams() if t not in (us, c)]))
        assert after["stage"] == "next_pick"
        assert [(x["team_number"], x["expected_alliance_score"]) for x in after["cards"]] == \
            [(x["team_number"], x["expected_alliance_score"]) for x in card["conditional_seconds"]]


# --- criterion 13 / Scenario K (backend): profile values equal the plan's ------------------------------------------


def test_criterion_13_each_cards_profile_has_the_same_estimates_as_the_card():
    snap = snapshot(seed=8)
    us = snap.teams()[0]
    plan = build_plan(snap, position(snap, us))
    for card in plan["cards"]:
        prof = team_profile(snap, card["team_number"], our_team=us)
        assert prof["team_number"] == card["team_number"] and prof["snapshot_id"] == plan["snapshot_id"]
        for c in COMPONENTS:
            p, k = prof["estimates"]["components"][c], card["robot"]["components"][c]
            assert (p["estimate"], p["sd"], p["prior_kind"], p["w_eff"]) == \
                (k["estimate"], k["sd"], k["prior_kind"], k["w_eff"])


# --- §9.4: the optimizer equals brute force -------------------------------------------------------------------


def test_section_9_4_the_first_pick_optimizer_equals_brute_force():
    snap = snapshot(n_teams=12, matches_per_team=12, seed=17)
    us = snap.teams()[0]
    plan = build_plan(snap, position(snap, us))
    model = planner._model(snap, planner.EstimatorPolicy())
    others = [t for t in snap.teams() if t != us]
    brute = {}
    for c, d in itertools.permutations(others, 2):  # every ordered pair, each lineup valued on its own
        v = float(model.value(np.array([[model.index[us], model.index[c], model.index[d]]]))[0])
        brute[c] = max(brute.get(c, -np.inf), v)
    expected = sorted(brute.items(), key=lambda kv: (-kv[1], kv[0]))
    assert [c["team_number"] for c in plan["cards"]] == [t for t, _ in expected]
    assert [c["expected_alliance_score"] for c in plan["cards"]] == [round(v, 1) for _, v in expected]


# --- Scenario H: missing scouting changes no scoring estimate and adds no defense points -----------------------------


def test_scenario_H_scouting_changes_no_scoring_estimate_or_value():
    plain = snapshot(seed=9)
    scouted = snapshot(seed=9)
    us = plain.teams()[0]
    a = build_plan(plain, position(plain, us))
    t = a["cards"][0]["team_number"]  # a listed candidate, with one scouting observation
    scouted.scouting = {t: {"defense": 4.5, "defense_n": 1, "feeding": None, "feeding_n": 0, "kind": "scouted",
                            "computed_at": T0.isoformat()}}
    b = build_plan(scouted, position(scouted, us))
    strip = lambda p: [(c["team_number"], c["expected_alliance_score"], c["robot"]) for c in p["cards"]]  # noqa: E731
    assert strip(a) == strip(b)  # σ̂ and V unaffected; defense contributes no points
    card = next(c for c in b["cards"] if c["team_number"] == t)
    assert card["scouting"]["defense"] == 4.5 and card["scouting"]["feeding"] is None


# Scenario M (a later sentinel match leaves the outputs unchanged) is a database test: tests/test_p11a_db.py
# test_real_data_scenario_M_a_later_sentinel_match_leaves_the_snapshot_unchanged. The cutoff lives in the builder's
# SQL, so a fake cursor would only test itself.


# --- DM4 / Scenario J: the offline plan equals the online plan on the same snapshot --------------------------------


def test_scenario_J_the_offline_cli_plan_equals_the_served_plan_on_the_same_snapshot(monkeypatch, tmp_path, capsys):
    from scripts import p11a_snapshot as cli

    log = Log(setup())
    log.captain(1, 1)
    view = log.view()
    truth = {i: v for i, v in enumerate(truths(24, 7).values(), start=1)}
    snap = snapshot(truth=truth)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    snap.save(folder / snapshot_filename(snap))
    log_file = tmp_path / "log.json"
    log_file.write_text(json.dumps([{"action_id": e.action_id, "seq": e.seq, "type": e.type, "payload": dict(e.payload),
                                     "override_reason": e.override_reason, "author_label": e.author_label}
                                    for e in log.entries]))
    out = tmp_path / "offline.json"
    assert cli.main(["plan", "--snapshot", str(folder / snapshot_filename(snap)), "--log", str(log_file),
                     "--team", "1", "--out", str(out)]) == 0
    offline = json.loads(out.read_text())

    row = (7, "uid", "9911syn", None, "tester")
    monkeypatch.setattr(live_draft, "load_view_with_previous", lambda database, context, record_id: (row, (view, None)))
    alliance_plan.clear_cache()
    online = alliance_plan.plan_for_record(None, SimpleNamespace(team_number=1, workspace_id=3), 7,
                                           snapshot_dir=str(folder))
    assert offline["status"] == online["status"] == "current"
    served = json.loads(P11APlanOut.model_validate(online["plan"]).model_dump_json())
    assert offline["plan"] == served  # identical, value for value


# --- D2: backup combinations are the global top 5 complete alliances -----------------------------------------------


@pytest.mark.parametrize("seed", [1, 3, 8])
def test_d2_backup_combinations_are_the_global_top_five_over_every_pair(seed):
    """Before 2026-11-11 the list came only from the top 5 cards x their top 3 seconds and was sorted by rounded
    values: on seed 3 it missed a top-5 alliance, and on seed 1 two near-ties were out of order."""
    snap = snapshot(seed=seed)
    us = snap.teams()[0]
    plan = build_plan(snap, position(snap, us))
    model = planner._model(snap, planner.EstimatorPolicy())
    others = [t for t in snap.teams() if t != us]
    values = {pair: float(model.value(np.array([[model.index[us]] + [model.index[t] for t in pair]]))[0])
              for pair in itertools.combinations(others, 2)}
    expected = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    assert [tuple(c["picks"]) for c in plan["backup_combinations"]] == [p for p, _ in expected]
    assert [c["expected_alliance_score"] for c in plan["backup_combinations"]] == [round(v, 1) for _, v in expected]


def test_d2_top_combinations_is_global_even_when_the_best_pairs_are_disjoint():
    values = {(1, 2): 50.0, (3, 4): 49.0, (5, 6): 48.0, (7, 8): 47.0, (9, 10): 46.0, (1, 3): 45.0, (2, 4): 44.0}
    values.update({(b, a): v for (a, b), v in list(values.items())})
    got = planner.top_combinations(values, 5)
    assert [c["picks"] for c in got] == [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]


# --- disclosures (A3.2, A3.5, A3.3/B5.3, B5.1, B5.2(b)) -----------------------------------------------------------


def test_the_plan_states_the_omitted_opponent_adjustment_and_the_independence_of_components():
    snap = snapshot()
    plan = build_plan(snap, position(snap, snap.teams()[0]))
    text = " | ".join(plan["known_limitations"])
    assert "No opponent adjustment" in text and "spec A3.5" in text
    assert "covariance across auto, teleop and endgame is not modelled" in text
    assert "alliance-level noise" in text
    assert planner.PER_ROBOT_CAP_NOTE not in plan["known_limitations"]  # no per-robot cap in this configuration


def test_a_per_robot_cap_is_disclosed_as_an_approximation_only_when_configured(tmp_path):
    data = scoring_config(approved=False).model_dump(mode="json")
    data["rules"][1].update({"per_robot_cap_action_id": "teleop_piece", "per_robot_cap_count": 30})
    config = approve(type(scoring_config())(**data))
    snap = snapshot()
    snap.scoring_config = config.model_dump(mode="json")
    (tmp_path / "9911.json").write_text(config.model_dump_json())
    plan = build_plan(snap, position(snap, snap.teams()[0]), scoring_dir=tmp_path)
    assert plan["known_limitations"][-1] == planner.PER_ROBOT_CAP_NOTE


def test_cards_say_the_prior_was_estimated_from_this_events_own_matches():
    snap = snapshot()  # no earlier event: every robot's prior is current_event_joint
    plan = build_plan(snap, position(snap, snap.teams()[0]))
    for card in plan["cards"]:
        assert all(v["prior_kind"] == "current_event_joint" for v in card["robot"]["components"].values())
        assert any(s.startswith("Prior estimated from this event's own matches (auto, teleop, endgame;")
                   for s in card["statements"])


# --- additive response fields (A3.2, A3.7, B5.6, B5.7, A7, G2) ------------------------------------------------------


def test_each_estimate_reports_its_prior_mean_and_sd_max_corr_and_label_reasons():
    snap = _always_together_snapshot()
    plan = build_plan(snap, position(snap, 9903, available=[t for t in snap.teams() if t != 9903]))
    model = planner._model(snap, planner.EstimatorPolicy())
    for card in plan["cards"]:
        for c, comp in card["robot"]["components"].items():
            fit = model.fits[c]
            assert comp["prior_kind"] == "current_event_joint" and comp["prior_sd"] > 0
            assert comp["prior_sd"] >= round(float(np.sqrt(fit.tau2)), 2) - 0.01  # sqrt(tau^2 + V_mu) >= tau
            assert comp["max_abs_corr"] is not None
            for label in comp["labels"]:
                assert any(r.startswith(f"{label}:") for r in comp["label_reasons"]), (label, comp["label_reasons"])
    pair = [c for c in plan["cards"] if c["team_number"] in (9901, 9902)]
    for card in pair:
        reasons = card["robot"]["components"]["teleop"]["label_reasons"]
        assert any(r.startswith("weakly_identified: max |corr|") for r in reasons)


def test_the_plan_records_its_monte_carlo_and_the_zero_defense_effect():
    snap = snapshot()
    plan = build_plan(snap, position(snap, snap.teams()[0]), draws=400)
    assert plan["monte_carlo"]["draws"] == 400 and plan["monte_carlo"]["p_delta_positive_mc_se_max"] == 0.025
    assert plan["defense_effect"] == {"status": "defense_effect_insufficient_data", "points": 0.0,
                                      "reason": plan["defense_effect"]["reason"]}
    P11APlanOut.model_validate(plan)


def test_the_profile_lists_exclusions_last_updated_and_the_config_behind_its_fit():
    from ml.alliance.contract import P11AProfileOut

    snap = snapshot()
    snap.exclusions = [{"match_key": "9911syn_qm99", "reason": "result_posted_after_as_of", "known_at": "2099"},
                       {"what": "scouting", "team_number": 9905, "reason": "computed after as_of"}]
    t = snap.teams()[2]
    snap.scouting = {t: {"defense": 3.0, "defense_n": 2, "feeding": None, "feeding_n": 0, "kind": "scouted",
                         "computed_at": (T0 + timedelta(hours=99)).isoformat(), "defense_agreement": 0.5,
                         "feeding_agreement": None, "defense_insufficient_data": False,
                         "feeding_insufficient_data": True}}
    prof = team_profile(snap, t, our_team=snap.teams()[0])
    P11AProfileOut.model_validate(prof)
    assert [e["reason"] for e in prof["provenance"]["exclusions"]] == ["result_posted_after_as_of",
                                                                         "computed after as_of"]
    assert prof["provenance"]["scoring_config_sha256"] == scoring_config().content_sha256()
    assert prof["provenance"]["game_spec_sha256"] == game_spec().sha256()
    assert prof["last_updated"] == (T0 + timedelta(hours=99)).isoformat()  # the scouting summary is newest
    assert prof["scouting"]["defense_agreement"] == 0.5 and prof["scouting"]["feeding_insufficient_data"] is True
    alone = team_profile(snap, snap.teams()[1])  # no alliance fit: no configuration was used
    assert alone["provenance"]["scoring_config_sha256"] is None
    assert alone["last_updated"] == max(r.time for r in snap.qual_rows)


# --- §7 caching and A5 participation ------------------------------------------------------------------------------


def test_section_7_the_fit_is_cached_per_snapshot_id_and_any_content_change_refits():
    from ml.alliance.snapshot import clear_fit_cache

    clear_fit_cache()
    snap = snapshot(seed=5)
    first = snap.fit()
    assert snap.fit() is first  # the same snapshot id: no refit
    changed = snapshot(seed=5)
    changed.qual_rows = changed.qual_rows[:-2]
    assert changed.snapshot_id() != snap.snapshot_id() and changed.fit() is not first
    strict = planner.EstimatorPolicy(n_min=6)
    assert snap.fit(strict) is not first  # another policy is another key


def test_a5_the_profile_reports_participation_and_surrogate_matches():
    from ml.alliance.contract import P11AProfileOut

    snap = snapshot()
    t = snap.teams()[4]
    played = [r.match_key for r in snap.qual_rows if t in r.teams]
    snap.provenance = {**snap.provenance, "surrogate_appearances": [
        {"match_key": played[0], "color": "red", "team_number": t},
        {"match_key": played[1], "color": "blue", "team_number": t + 1}]}
    prof = team_profile(snap, t)
    P11AProfileOut.model_validate(prof)
    assert prof["participation"]["matches_played"] == len(played) == prof["matches_played"]
    assert prof["participation"]["surrogate_matches"] == [played[0]]
