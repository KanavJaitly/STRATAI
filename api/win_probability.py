"""The M6/M7 (`win_prob_xgb_calibrated`) win probability for one match feature row: one evaluation, shared by every
route that serves it (P7-A3: the pre-match report reuses this, never a route).

The model's output goes through the display rule (`ml.calibration.display.display_probability`), and is gated by
M7's evaluated population (`api.contract.m6m7_unvalidated_reason`). Moved here unchanged from
api.routes.predictions in P7-M7; the predictions goldens (tests/test_phase7_predictions_regression.py) pin the
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.contract import CalibratedWinProbability, ServedModelInfo, calibrated_win_probability, m6m7_unvalidated_reason
from api.ml_loading import ServedModel
from ml.calibration.display import display_probability
from ml.features.assembler import MatchFeatureRow, TeamFeatures


class NoFeatures(Exception):
    """Every team involved has zero real features: no prediction is built from no evidence."""


def team_features_fully_absent(team_features: TeamFeatures) -> bool:
    """True if literally none of a team's optional features are present -- the API-level "no real evidence at all"
    case, distinct from thin-but-real data (which the underlying models already handle gracefully)."""
    return not any((
        team_features.epa_total_present, team_features.epa_auto_present,
        team_features.epa_teleop_present, team_features.epa_endgame_present,
        team_features.average_score_present, team_features.average_auto_points_present,
        team_features.defense_score_present,
        team_features.feeding_score_present,
    ))


def served_model_info(served: ServedModel) -> ServedModelInfo:
    return ServedModelInfo(**served.identity())


@dataclass(frozen=True)
class M6M7Value:
    """One displayed M6/M7 value, with the reason it is outside M7's evaluated population (None when inside)."""

    shown: float
    unvalidated_reason: str | None
    model: ServedModelInfo

    def calibrated(self) -> CalibratedWinProbability:
        return calibrated_win_probability(self.shown, self.unvalidated_reason, self.model)


def evaluate_m6m7(served: ServedModel, row: MatchFeatureRow, scope: str) -> M6M7Value:
    """The displayed, gated M6/M7 value for `row` in `scope` (qualification, playoff or unspecified). Raises
    NoFeatures when every team involved has zero real features."""
    teams = (*row.red_teams, *row.blue_teams)
    if teams and all(team_features_fully_absent(team) for team in teams):
        raise NoFeatures()
    shown = display_probability(served.model.predict_win_prob(row))
    return M6M7Value(shown, m6m7_unvalidated_reason(scope, row.red_teams, row.blue_teams), served_model_info(served))


__all__ = ["M6M7Value", "NoFeatures", "evaluate_m6m7", "served_model_info", "team_features_fully_absent"]
