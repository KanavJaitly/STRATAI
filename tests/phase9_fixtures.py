"""Synthetic pre-match reports for the Phase 9 tests. Every value here is SYNTHETIC (event 2099test, teams 9901-9906).

Each builder returns the JSON form of a report validated by the real response model
(api.routes.pre_match_report.PreMatchReportResponse), so the fixtures cannot drift from the served shape.
"""

from __future__ import annotations

import copy
from typing import Any

from api.routes.pre_match_report import PreMatchReportResponse

EVENT, MATCH = "2099test", "2099test_qm1"
RED, BLUE = [9901, 9902, 9903], [9904, 9905, 9906]
AS_OF = "2099-03-01T10:00:00Z"


def measure(value: float | None, n: int = 6, reason: str | None = None, sd: float | None = None) -> dict[str, Any]:
    return {"value": value, "n": n, "absent_reason": None if value is not None else (reason or "insufficient_data"),
            "uncertainty": {"kind": "sd" if sd is not None else "none", "value": sd,
                            "reason": None if sd is not None else "not computed"}}


def strength(team: int, epa: tuple[float, float, float, float] | None, defense: float | None) -> dict[str, Any]:
    parts = dict(zip(("total", "auto", "teleop", "endgame"), epa)) if epa else {}
    return {
        "team_number": team, "event_key": EVENT, "as_of": AS_OF,
        "epa": {**{k: measure(parts.get(k), 1, "no_prior_concluded_event_epa") for k in ("total", "auto", "teleop", "endgame")},
                "epa_value_source": "statbotics" if epa else None, "epa_source_state": "current" if epa else "withheld_no_prior_event",
                "source_event_key": "2099prior" if epa else None,
                "withheld_reason": None if epa else "no_prior_concluded_event_epa",
                "n_kind": "matches_at_source_event", "validation_status": "descriptive"},
        "scoring": {"average_score": measure(61.25, 6, sd=12.5), "score_stddev": measure(12.5, 6),
                    "consistency_rating": measure(79.6, 6), "reliability_score": measure(100.0, 6),
                    "good_day_count": measure(2.0, 6), "average_day_count": measure(3.0, 6),
                    "bad_day_count": measure(1.0, 6), "matches_considered": 6, "validation_status": "descriptive"},
        "auto_points": {"this_event": measure(14.0, 6), "season_by_event": [], "validation_status": "descriptive"},
        "defense": {"score": measure(defense, 3, "insufficient_data: fewer than 2 scouting observations"),
                    "agreement": measure(0.5 if defense is not None else None, 3), "contributing_sources": [],
                    "validation_status": "descriptive_definition_pending"},
        "feeding": {"score": measure(None, 0, "insufficient_data: fewer than 2 scouting observations"),
                    "agreement": measure(None, 0), "contributing_sources": [], "validation_status": "not_validated"},
    }


def _robots(teams: list[int], opponents: list[int]) -> dict[str, Any]:
    return {"vocabulary": "p6-strategy-v1", "robots": [
        {"team_number": teams[0], "role": "scoring", "components": ["auto", "teleop", "endgame"], "defense_target": None, "feed_target": None},
        {"team_number": teams[1], "role": "defense", "components": ["auto", "endgame"], "defense_target": opponents[1], "feed_target": None},
        {"team_number": teams[2], "role": "feeding", "components": ["auto", "endgame"], "defense_target": None, "feed_target": teams[0]}]}


def report_with_models() -> dict[str, Any]:
    """Every engine part present: validated M6/M7 value, a recommended strategy per side, synergy for red."""
    sides = []
    for side, ours, theirs in (("red", RED, BLUE), ("blue", BLUE, RED)):
        assessment = {"strategy": _robots(ours, theirs), "opponent_strategy": _robots(theirs, ours),
                      "odds": {"display": "65%" if side == "red" else "35%",
                               "validation": {"status": "not_validated", "reasons": ["strategy_effect_unmeasured"], "evidence": None}}}
        sides.append({"side": side, "recommended": assessment, "baseline": assessment, "vs_baseline_label": "within one display step",
                      "candidates_evaluated": 21952, "selection_note": "maximum of many model estimates", "unavailable_reasons": []})
    report = base_report()
    report["win_probability"] = {
        "probability_scope": "qualification", "absent_code": None, "absent_reason": None, "source": "synthetic",
        "value": {"validated_value": 0.6, "unvalidated_value": None, "unvalidated_reason": None, "rounding": 0.05,
                  "calibration_status": "m7_gate_failed",
                  "validation": {"status": "approximately_calibrated_qualification", "reasons": [], "evidence": None},
                  "model": {"model_type": "win_prob_xgb_calibrated", "model_version": "synthetic", "model_version_tag": "syn",
                            "model_sha256": "0" * 64, "training_dataset_hash": "0" * 64, "provenance": {}}}}
    report["strategy"] = {"model": {"model_type": "strategy_outcome_component", "model_version": "synthetic", "model_version_tag": "syn",
                                    "model_sha256": "0" * 64, "spec_sha256": "0" * 64},
                          "context": {"match_key": MATCH, "event_key": EVENT, "as_of": AS_OF,
                                      "match_context": "qualification", "competition_level": "qualification",
                                      "red_team_numbers": RED, "blue_team_numbers": BLUE,
                                      "coach_observations_applied": 2, "coach_observations_invalid_ignored": 0},
                          "sides": sides, "absent_code": None, "absent_reason": None, "source": "synthetic"}
    return validated(report)


def base_report() -> dict[str, Any]:
    """Models not loaded (the local state): win probability and strategy absent; blue synergy absent."""
    teams = [{"team_number": t, "alliance": "red", "strength": strength(t, (31.5, 8.25, 19.0, 4.25), 3.5),
              "validation": {"status": "descriptive", "reasons": ["reliability_interim"], "evidence": None}} for t in RED]
    teams += [{"team_number": t, "alliance": "blue", "strength": strength(t, None, None),
               "validation": {"status": "descriptive", "reasons": [], "evidence": None}} for t in BLUE]
    return {
        "match_key": MATCH, "event_key": EVENT, "competition_level": "qualification",
        "scheduled_time": "2099-03-01T11:00:00Z", "as_of": AS_OF, "as_of_source": "requested",
        "red_team_numbers": RED, "blue_team_numbers": BLUE,
        "epa": {"epa_source": "statbotics", "evaluated_configuration": False, "provenance": {}, "adoption": None, "validation_flags": []},
        "teams": teams,
        "synergy": [
            {"alliance": "red", "team_numbers": RED, "absent_code": None, "absent_reason": None,
             "validation": {"status": "not_validated_against_outcomes", "reasons": [], "evidence": None},
             "score": {"overall_score": 0.42, "role_fit_term": 0.3, "role_fit_axes_used": ["auto"], "scoring_distribution_term": 0.5,
                       "scoring_distribution_axes_used": ["auto"], "defense_feeding_coverage_term": None,
                       "defense_feeding_coverage_present_count": 0, "confidence": 0.5}},
            {"alliance": "blue", "team_numbers": BLUE, "score": None, "absent_code": "alliance_incomplete",
             "absent_reason": "synthetic: fewer than three teams with inputs",
             "validation": {"status": "not_validated_against_outcomes", "reasons": [], "evidence": None}}],
        "win_probability": {"probability_scope": "qualification", "value": None, "absent_code": "model_not_loaded",
                            "absent_reason": "win_prob_xgb_calibrated (M6/M7) is not pinned/loadable", "source": "synthetic"},
        "strategy": {"model": None, "context": None, "sides": [], "absent_code": "model_not_loaded",
                     "absent_reason": "the P6-M10 strategy model is not pinned/loadable", "source": "synthetic"},
        "not_produced": {k: {"value": None, "reason": "not_produced_by_any_engine", "semantics": f"synthetic semantics of {k}"}
                         for k in ("strengths_and_weaknesses", "defensive_threats", "key_risks", "predicted_flow",
                                   "critical_matchups", "key_success_factors")},
    }


def validated(report: dict[str, Any]) -> dict[str, Any]:
    return PreMatchReportResponse.model_validate(copy.deepcopy(report)).model_dump(mode="json")


def local_report() -> dict[str, Any]:
    return validated(base_report())


def unvalidated_win_report() -> dict[str, Any]:
    report = report_with_models()
    report["win_probability"]["value"].update(validated_value=None, unvalidated_value=0.75, unvalidated_reason="playoff_scope")
    report["win_probability"]["value"]["validation"] = {"status": "not_validated", "reasons": ["playoff_scope"], "evidence": None}
    return validated(report)
