"""Phase 11: P11-FB2, the alliance-aware fallback rule (workspaces.draft_fb2; decision
.agent/phase11/decisions/P11_FB2_DECISION_2026-11-14.md, frozen before the code).

The pure tests use synthetic events only (teams 1-40 with strengths set by the test, seeded noise): nothing there is
evidence about any real team. One read-only test checks the row loader against a real event when an isolated
database copy holds it.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pytest

from ml.playoffs.selection import CandidateProfile, FactorValue
from tests.test_phase11_draft_log import Log, setup
from workspaces import draft_fb2 as fb2
from workspaces import draft_recommendations as rec

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / ".agent" / "phase11" / "decisions" / "P11_FB2_DECISION_2026-11-14.md"
# sha256 of ml/alliance/estimator.py as copied from p11a/recommendation-intelligence (git blob adb688c3)
ESTIMATOR_SHA256 = "47b6ccac4d931edae9b266f599f9f10573b936ee3a57a784fa030897b1bb8153"
CRLF, LF = bytes([13, 10]), bytes([10])


# --- synthetic events ------------------------------------------------------------------------------------------------


def synthetic_rows(strength: dict[int, tuple[float, float, float]], *, matches_each: int = 10, noise: float = 2.0,
                   seed: int = 7, breakdown: bool = True) -> fb2.EventRows:
    """Qualification alliance rows whose components are the sum of the three robots' strengths plus noise."""
    rng = random.Random(seed)
    teams = sorted(strength)
    rows: list[fb2.AllianceRow] = []
    for match in range(len(teams) * matches_each // 6):
        six = rng.sample(teams, 6)
        for k, trio in enumerate((tuple(six[:3]), tuple(six[3:]))):
            parts = {c: max(0, round(sum(strength[t][i] for t in trio) + rng.gauss(0, noise)))
                     for i, c in enumerate(fb2.COMPONENTS)}
            rows.append(fb2.AllianceRow(f"2030test_qm{match}_{k}", trio, sum(parts.values()),
                                        parts if breakdown else None))
    return fb2.EventRows(2030, tuple(rows), 0, 0, False)


def strengths(n: int = 30) -> dict[int, tuple[float, float, float]]:
    """Team t: auto t/3, teleop t, endgame t/3 (higher numbers stronger)."""
    return {t: (t / 3, float(t), t / 3) for t in range(1, n + 1)}


def factor(value, n=12, reason=None):
    return FactorValue(value, n, "descriptive" if value is not None else "insufficient_data", reason)


def profile(team, *, reliability=100.0, consistency=100.0, defense=None):
    absent = factor(None, None, "absent")
    return CandidateProfile(team, absent, absent, factor(reliability, reason=None if reliability is not None else "absent"),
                            factor(consistency, reason=None if consistency is not None else "absent"),
                            factor(defense, 3) if defense is not None else factor(None, 0, "no scouting observations"),
                            absent, absent, absent)


def estimates(values: dict[int, dict[str, float]], mode=fb2.MODE_COMPONENTS) -> fb2.EventEstimates:
    components = fb2.COMPONENTS if mode != fb2.MODE_TOTAL else (fb2.TOTAL,)
    return fb2.EventEstimates(mode, components, values, {}, fb2.benchmark(values, components),
                              None if mode == fb2.MODE_COMPONENTS else "a reason", 60)


def lists(log: Log, seed: int, team: int, est: fb2.EventEstimates, inputs: fb2.TeamInputs | None = None):
    view = log.view()
    return fb2.rank_for_alliance(view, seed, team, est, inputs or fb2.TeamInputs({}), rec._excluded(view, seed, team))


# --- the record is frozen, and the code matches it --------------------------------------------------------------------


def test_the_frozen_weights_are_the_records():
    text = RECORD.read_text(encoding="utf-8")
    assert "**Weights:** fit weight 0.5; consistency weight 0.25; K = 24." in text
    assert (fb2.FIT_WEIGHT, fb2.CONSISTENCY_WEIGHT, fb2.BENCHMARK_TEAMS) == (0.5, 0.25, 24)
    assert "`ρ(t) = (reliability(t) / 100) × (1 − 0.25 × (1 − consistency(t) / 100))`" in text


def test_the_estimator_is_the_unchanged_p11a_copy():
    data = (ROOT / "ml" / "alliance" / "estimator.py").read_bytes().replace(CRLF, LF)  # any checkout's endings
    assert hashlib.sha256(data).hexdigest() == ESTIMATOR_SHA256


# --- §2.3 estimates --------------------------------------------------------------------------------------------------


def test_component_mode_recovers_the_strength_order():
    est = fb2.estimate_event(synthetic_rows(strengths()), switch_passed=True)
    assert est.mode == fb2.MODE_COMPONENTS and est.components == fb2.COMPONENTS and est.mode_reason is None
    order = sorted(est.values, key=lambda t: -(est.total(t) or 0))
    assert set(order[:5]) <= set(range(24, 31)) and set(order[-5:]) <= set(range(1, 8))


def test_without_breakdowns_it_ranks_on_the_total_score_and_says_why():
    est = fb2.estimate_event(synthetic_rows(strengths(), breakdown=False), switch_passed=True)
    assert est.mode == fb2.MODE_TOTAL and est.components == (fb2.TOTAL,)
    assert est.mode_reason == "only 0 alliance row(s) have a score breakdown; 12 are needed"


def test_an_unsupported_season_ranks_on_the_total_score():
    rows = synthetic_rows(strengths())
    est = fb2.estimate_event(fb2.EventRows(2027, rows.rows, 0, 0, True), switch_passed=True)
    assert est.mode == fb2.MODE_TOTAL and "does not cover season 2027" in est.mode_reason


def test_too_few_rows_withholds_rather_than_guessing():
    rows = synthetic_rows(strengths(12), matches_each=1)
    assert len(rows.rows) < fb2.MIN_ROWS
    with pytest.raises(fb2.Fb2Unavailable, match="needs 12 alliance rows"):
        fb2.estimate_event(rows, switch_passed=True)


def test_before_the_switch_it_uses_epa_components_and_leaves_teams_without_them_unranked():
    est = fb2.estimate_event(synthetic_rows(strengths()), switch_passed=False,
                             epa={1: (1.0, 2.0, 3.0), 2: (2.0, None, 1.0)})
    assert est.mode == fb2.MODE_EPA and set(est.values) == {1}


def test_dq_rows_left_out_are_noted():
    rows = synthetic_rows(strengths())
    est = fb2.estimate_event(fb2.EventRows(2030, rows.rows, 2, 0, False), switch_passed=True)
    assert est.notes[0] == "2 alliance row(s) left out: TBA lists a disqualified team on them"


def test_the_benchmark_is_the_median_of_the_top_24():
    values = {t: {"auto": float(t), "teleop": 0.0, "endgame": 0.0} for t in range(1, 41)}
    assert fb2.benchmark(values, fb2.COMPONENTS)["auto"] == pytest.approx(statistics_median(range(17, 41)))


def statistics_median(xs) -> float:
    xs = sorted(xs)
    mid = len(xs) // 2
    return (xs[mid - 1] + xs[mid]) / 2 if len(xs) % 2 == 0 else xs[mid]


# --- §3-§7 ranking and cards -----------------------------------------------------------------------------------------


def field_values() -> dict[int, dict[str, float]]:
    """24 teams: 1 is our captain (strong teleop, no auto); 5 is an auto specialist and 6 a teleop specialist with the
    same estimated total; everyone else is middling."""
    values = {t: {"auto": 6.0, "teleop": 18.0, "endgame": 6.0} for t in range(1, 25)}
    values[1] = {"auto": 0.0, "teleop": 30.0, "endgame": 6.0}
    values[5] = {"auto": 16.0, "teleop": 18.0, "endgame": 6.0}
    values[6] = {"auto": 6.0, "teleop": 28.0, "endgame": 6.0}
    return values


def test_a_candidate_that_fills_the_alliance_gap_ranks_above_one_with_the_same_total():
    log = Log(setup())
    log.captain(1, 1)
    out = lists(log, 1, 1, estimates(field_values()))
    order = [c.team_number for c in out.ranked]
    assert order[:2] == [5, 6]
    card5 = out.ranked[0]
    assert out.gaps["auto"] == pytest.approx(6.0) and out.gaps["teleop"] == 0.0
    assert "Fills 6.0 of a 6.0-pt auto gap." in card5.reasons
    assert card5.rank_score == pytest.approx(36 + 40 + 0.5 * 6)  # members' total + Σ eff + 0.5 × fit
    assert card5.projected == pytest.approx(76.0) and card5.robots == (1, 5)
    assert card5.reasons[0] == "Projected alliance score 76.0 with teams 1, 5 (no fouls; not validated)."


def test_reliability_and_consistency_scale_the_contribution_and_absence_is_named_not_imputed():
    log = Log(setup())
    log.captain(1, 1)
    inputs = fb2.TeamInputs({5: profile(5, reliability=80.0, consistency=60.0),
                             6: profile(6, reliability=None, consistency=None)})
    out = lists(log, 1, 1, estimates(field_values()), inputs)
    cards = {c.team_number: c for c in out.projections}
    rho = 0.8 * (1 - 0.25 * 0.4)
    assert cards[5].fits[0].effective == pytest.approx(16.0 * rho)
    assert f"Reliability 80.0, consistency 60.0 (n = 12): counted at {rho:.2f}×." in cards[5].reasons
    assert "Reliability absent (absent): not adjusted for it." in cards[6].reasons
    assert "Consistency absent (absent): not adjusted for it." in cards[6].reasons
    assert cards[6].fits[1].effective == pytest.approx(28.0)  # factor 1: never imputed


def test_defense_is_shown_but_never_changes_the_order():
    log = Log(setup())
    log.captain(1, 1)
    plain = [c.team_number for c in lists(log, 1, 1, estimates(field_values())).projections]
    inputs = fb2.TeamInputs({t: profile(t, defense=4.5 if t == 24 else None) for t in range(1, 25)})
    out = lists(log, 1, 1, estimates(field_values()), inputs)
    assert [c.team_number for c in out.projections] == plain
    cards = {c.team_number: c for c in out.projections}
    assert "Defense 4.5/5 from 3 observations (descriptive; it does not change the ranking)." in cards[24].reasons
    assert "Defense: no scouting." in cards[5].reasons


def test_the_decline_flag_informs_only():
    log = Log(setup())
    log.captain(1, 1)
    out = lists(log, 1, 1, estimates(field_values()))
    flagged = {c.team_number: c.decline_flag for c in out.projections if c.decline_flag}
    # Alliance 1 picks first, so no captain acts before its turn: teams 2-8 are projected captains, not excluded.
    assert flagged == {t: f"May decline (projected captain of alliance {t})." for t in range(2, 9)}
    assert not out.excluded or all(t == 1 for t, _ in out.excluded)
    values = field_values()
    values[2] = {"auto": 20.0, "teleop": 30.0, "endgame": 10.0}  # the strongest team is a projected captain
    first = lists(log, 1, 1, estimates(values)).ranked[0]
    assert first.team_number == 2 and "May decline (projected captain of alliance 2)." in first.reasons


def test_a_low_ranked_recommendation_explains_its_rank():
    log = Log(setup())
    log.captain(1, 1)
    values = field_values()
    values[20] = {"auto": 18.0, "teleop": 30.0, "endgame": 10.0}  # qualification rank 20 of 24
    card = lists(log, 1, 1, estimates(values)).ranked[0]
    assert card.team_number == 20 and card.qualification_rank == 20
    assert "Qualification rank 20 of 24." in card.reasons
    assert ("Ranked in the lower half, but its estimated contribution is 1 of 24 at this event; qualification rank "
            "also reflects partners, schedule and ranking points.") in card.reasons


def test_a_projected_captain_plans_from_itself():
    log = Log(setup())
    log.captain(1, 1)
    out = lists(log, 4, 5, estimates(field_values()))  # team 5 is projected to captain alliance 4
    assert out.members == (5,)
    assert all(c.robots[0] == 5 for c in out.ranked)


def test_v_counts_the_best_three_robots_of_a_four_robot_alliance():
    log = Log(setup(n_teams=12, n_alliances=2, picks_per_alliance=3))  # serpentine turns: 1, 2, 2, 1, 1, 2
    log.captain(1, 1)
    log.pick(1, 5)
    log.captain(2, 2)
    log.pick(2, 6)
    log.pick(2, 7)
    log.pick(1, 8)
    view = log.view()
    assert view.acting_seed() == 1 and view.alliances[0] == (1, 5, 8)
    values = {t: {"auto": float(t), "teleop": 10.0, "endgame": 0.0} for t in range(1, 13)}
    card = next(c for c in lists(log, 1, 1, estimates(values)).projections if c.team_number == 12)
    assert card.members == (1, 5, 8) and card.robots == (12, 8, 5)  # team 1 is the weakest of the four
    assert card.projected == pytest.approx((12 + 10) + (8 + 10) + (5 + 10))


def test_ties_break_by_projection_then_rank_then_team_number():
    log = Log(setup())
    log.captain(1, 1)
    values = {t: {"auto": 6.0, "teleop": 18.0, "endgame": 6.0} for t in range(1, 25)}
    order = [c.team_number for c in lists(log, 1, 1, estimates(values)).ranked]
    assert order == [2, 3, 4, 5]  # identical estimates: qualification rank decides


def test_total_mode_cards_say_fouls_are_included_and_why():
    log = Log(setup())
    log.captain(1, 1)
    values = {t: {fb2.TOTAL: float(t)} for t in range(1, 25)}
    card = lists(log, 1, 1, estimates(values, fb2.MODE_TOTAL)).ranked[0]
    assert card.fouls_included and "(fouls included; not validated)" in card.reasons[0]
    assert card.reasons[-1] == "Ranked on the total score only: a reason."


def test_every_card_reason_comes_from_the_records_templates():
    log = Log(setup())
    log.captain(1, 1)
    starts = ("Projected alliance score ", "Estimated contribution ", "Fills ", "Adds nothing to your ",
              "Your alliance has no gap", "Reliability ", "Consistency ", "Defense", "May decline (",
              "Qualification rank ", "No qualification rank", "Ranked in the lower half", "Estimate labels: ",
              "Ranked on the total score only: ", "Ranked on EPA components: ", "Not recommended: ",
              "No estimate at this event")
    for card in lists(log, 1, 1, estimates(field_values())).projections:
        for line in card.reasons:
            assert line.startswith(starts), line


# --- the loader, on a real event (read-only) ---------------------------------------------------------------------------


def test_load_rows_reads_qualification_alliances_with_parity_on_a_real_event():
    from tests.test_live_epa import _isolated_db_name

    if _isolated_db_name() is None:
        pytest.skip("needs an isolated stratai_* database copy")
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from ml.playoffs.service import SelectionTimeUnavailable, event_selection_moment

    db = Database(DatabaseConfig(Settings().database_url))
    try:
        moment = event_selection_moment(db, "2024njfla")
    except SelectionTimeUnavailable:
        pytest.skip("2024njfla is not in this copy")
    rows = fb2.load_rows(db, "2024njfla", moment)
    assert rows.season == 2024 and not rows.unsupported_season and len(rows.rows) >= fb2.MIN_ROWS
    assert all(len(set(r.teams)) == 3 for r in rows.rows)
    with_parts = [r for r in rows.rows if r.components is not None]
    assert with_parts and all(sum(r.components.values()) <= r.total for r in with_parts)  # fouls are the rest
