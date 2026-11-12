"""P11A response contract: the one set of types every P11A output passes through (API routes and the offline CLI).

**Why one module.** Labels are enforced by these types at runtime, not by convention:
- the API's `response_model` validates every response (FastAPI raises, giving a 500, rather than serving an invalid
  one);
- `scripts/p11a_snapshot.py` validates through the same types before it writes anything.

So no construction path can serve a plan labelled `validated`, `calibrated` or `approved`, or without its labels.

**The pins** (`Literal`, required, no default):
- `validation_status: not_validated`;
- `interval_status: not_calibrated`;
- `thresholds_status: candidate_unapproved`;
- comparison `outcome: unresolved`;
- `win_probability.status: not_available`;
- `availability_model: not_modelled`;
- `objective: expected_alliance_score`, `unit: points`;
- `experimental: true`.

Changing any of them is a contract change: a relock with a recorded decision.

**What validation guarantees.**
- Fields not declared here are dropped, never served (pydantic ignores them, and the response is serialized from the
  model).
- No field is typed as a free-form dictionary except `versions` (string to string or null).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Component = Literal["auto", "teleop", "endgame"]


class P11ACodeMessage(BaseModel):
    code: str
    message: str


class P11ATeamReason(BaseModel):
    team_number: int
    reason: str


# --- shared ---------------------------------------------------------------------------------------------------------


class P11AComponentOut(BaseModel):
    estimate: float = Field(description="Estimated points this robot adds to its alliance's component (not validated).")
    sd: float = Field(description="Posterior SD of the estimate (estimation uncertainty only; not calibrated).")
    kind: Literal["estimated"]
    prior_kind: Literal["prior_event_individual", "current_event_joint"]
    w_eff: float = Field(description="Share of the estimate that comes from this event's data (1 - posterior/prior "
                                     "variance); 1 - w_eff is the prior's influence.")
    labels: list[str]
    prior_mean: float | None = Field(default=None, description="The prior's mean (spec A3.2). For current_event_joint: "
                                                               "the event population mean estimated jointly from this "
                                                               "event's matches.")
    prior_sd: float | None = Field(default=None, description="The prior's SD. For current_event_joint: sqrt(tau^2 + "
                                                             "V_mu), with V_mu the population mean's uncertainty.")
    max_abs_corr: float | None = Field(default=None, description="Largest |correlation| of this estimate with another "
                                                                 "robot's (spec A3.7).")
    label_reasons: list[str] | None = Field(default=None, description="Each label with the threshold comparison that "
                                                                      "set it (candidate thresholds, unapproved).")


class P11ARobotOut(BaseModel):
    team_number: int
    components: dict[Component, P11AComponentOut]
    labels: list[str]
    n: int | None = Field(description="Qualification alliance rows this robot played at the event.")
    partners: int | None = Field(default=None, description="Distinct alliance partners at the event.")


class P11ACollapseScreenOut(BaseModel):
    ratio: float | None = Field(description="sigma_hat^2 / var(y).")
    threshold: float
    flagged: bool
    status: Literal["non_authoritative"]
    note: str


class P11AFitDiagnosticsOut(BaseModel):
    sigma2: float = Field(description="Fitted alliance-level residual variance (points^2).")
    tau2: float = Field(description="Fitted between-robot variance (points^2).")
    rows: int
    degenerate: bool = Field(description="sigma^2 on the optimizer's lower bound; a degenerate fit withholds plans.")
    sigma2_zero_lr: float | None = Field(description="Profile REML likelihood ratio for sigma^2 = 0, capped at 100.")
    residual_df: int | None
    collapse_screen: P11ACollapseScreenOut


class P11AWithheldOut(BaseModel):
    status: Literal["withheld"]
    reason: str


class P11AWinProbabilityOut(BaseModel):
    status: Literal["not_available"]
    reason: str


# --- the plan ---------------------------------------------------------------------------------------------------------


class P11ATeamScoreOut(BaseModel):
    team_number: int
    expected_alliance_score: float


class P11ACardOut(BaseModel):
    rank: int
    team_number: int
    expected_alliance_score: float = Field(description="Expected points of the best three-robot lineup; not a chance "
                                                       "of winning.")
    estimation_interval_80: list[float] = Field(description="Estimation uncertainty of the expected score only; not a "
                                                            "prediction interval; not calibrated.")
    interval_note: str
    lineup: list[int]
    robot: P11ARobotOut
    availability: Literal["confirmed_available"]
    statements: list[str]
    scouting: P11AScoutingOut | None
    conditional_seconds: list[P11ATeamScoreOut] | None = None
    lineup_gain: float | None = None


class P11AComparisonOut(BaseModel):
    a: int
    b: int
    compared: str
    p_delta_positive: float | None = Field(description="Share of estimation draws in which a's expected score exceeds "
                                                       "b's; null when both cards have the same lineup.")
    delta_mean: float
    delta_interval_80: list[float]
    outcome: Literal["unresolved"] = Field(description="Always unresolved until delta and pi are approved (B6).")
    reason: Literal["comparison_threshold_not_approved", "same_lineup"]


class P11ACombinationOut(BaseModel):
    picks: list[int]
    expected_alliance_score: float


class P11ADestinationOut(BaseModel):
    seed: int
    members: list[int]
    expected_alliance_score: float | None = None
    lineup: list[int] | None = None
    status: Literal["withheld"] | None = None
    reason: str | None = None


class P11AMonteCarloOut(BaseModel):
    draws: int
    seed_basis: str
    p_delta_positive_mc_se_max: float = Field(description="Upper bound of the Monte Carlo SE of p_delta_positive.")
    note: str


class P11ADefenseEffectOut(BaseModel):
    status: Literal["defense_effect_insufficient_data"]
    points: Literal[0.0] = Field(description="Defense and feeding add no points until a measured effect exists.")
    reason: str


class P11AAvailabilityOut(BaseModel):
    confirmed_available: list[int]
    confirmed_unavailable: list[P11ATeamReason]
    no_estimate: list[int]
    predicted: None = Field(default=None, description="Availability before your turn is not modelled (always null).")


class P11APlanOut(BaseModel):
    snapshot_id: str
    record_seq: int
    event_key: str
    as_of: str
    mode: Literal["captain", "on_alliance", "projected_captain", "non_captain"]
    seed: int | None
    members: list[int]
    picks_remaining: int
    turns_before: int | None
    objective: Literal["expected_alliance_score"]
    unit: Literal["points"]
    win_probability: P11AWinProbabilityOut
    validation_status: Literal["not_validated"]
    interval_status: Literal["not_calibrated"]
    thresholds_status: Literal["candidate_unapproved"]
    availability_model: Literal["not_modelled"]
    availability: P11AAvailabilityOut
    fit_diagnostics: dict[Component, P11AFitDiagnosticsOut]
    versions: dict[str, str | None]
    known_limitations: list[str]
    stage: Literal["first_pick", "next_pick", "fourth_member"] | None = None
    cards: list[P11ACardOut] | None = None
    comparisons: list[P11AComparisonOut] | None = None
    backup_combinations: list[P11ACombinationOut] | None = None
    combinations_note: str | None = None
    destinations: list[P11ADestinationOut] | None = None
    invitation_likelihood: P11AWithheldOut | None = None
    note: str | None = None
    monte_carlo: P11AMonteCarloOut | None = None
    defense_effect: P11ADefenseEffectOut | None = None


# --- the profile ------------------------------------------------------------------------------------------------------


class P11ARankOut(BaseModel):
    value: int | None
    status: Literal["observed", "not_available"]
    fetched_at: str | None = Field(description="When the ranking was fetched (at or before as_of).")


class P11AResidualOut(BaseModel):
    residual: float = Field(description="Alliance points minus the fit's expectation (the alliance's, never the "
                                        "robot's).")
    z: float


class P11AAnomalyOut(BaseModel):
    status: Literal["not_flagged"]
    reason: str


class P11AMatchOut(BaseModel):
    match_key: str
    time: str
    color: Literal["red", "blue"]
    partners: list[int]
    kind: Literal["observed_alliance"]
    auto: float
    teleop: float
    endgame: float
    fouls: float
    alliance_residual: dict[Component, P11AResidualOut] | None
    anomaly: P11AAnomalyOut | None


class P11AConsistencyOut(BaseModel):
    kind: Literal["observed_alliance"]
    alliance_points_mean: float | None
    alliance_points_sd: float | None
    n: int


class P11AEstimatesOut(P11ARobotOut):
    validation_status: Literal["not_validated"]
    note: str


class P11APriorComponentOut(BaseModel):
    mean: float
    variance: float


class P11APriorOut(BaseModel):
    kind: Literal["estimated"]
    source_event: str
    end_date: str
    components: dict[Component, P11APriorComponentOut]


class P11AScoutingOut(BaseModel):
    kind: Literal["scouted"]
    defense: float | None = Field(description="Scouted defense quality (0-5), not points.")
    defense_n: int
    feeding: float | None = Field(description="Scouted feeding quality (0-5), not points.")
    feeding_n: int
    computed_at: str | None = None
    defense_agreement: float | None = Field(default=None, description="Scout agreement on defense (team_metrics; "
                                                                       "lower is closer agreement).")
    feeding_agreement: float | None = Field(default=None, description="Scout agreement on feeding.")
    defense_insufficient_data: bool | None = Field(default=None, description="Fewer observations than the minimum "
                                                                             "(team_metrics).")
    feeding_insufficient_data: bool | None = None


class P11AAllianceFitOut(BaseModel):
    with_team: int
    expected_alliance_score: float
    lineup: list[int]
    unit: Literal["points"]
    note: str


class P11AExclusionOut(BaseModel):
    what: str | None = None
    match_key: str | None = None
    color: str | None = None
    team_number: int | None = None
    reason: str
    known_at: str | None = None


class P11AProvenanceOut(BaseModel):
    source: str | None = None
    built_at: str | None = None
    ranking_fetched_at: str | None = None
    prior_events: list[str] = []
    snapshot_version: str | None = None
    exclusions: list[P11AExclusionOut] | None = Field(default=None, description="What the snapshot left out, and why.")
    scoring_config_sha256: str | None = Field(default=None, description="The configuration behind alliance_fit.")
    game_spec_sha256: str | None = None


class P11AProfileOut(BaseModel):
    team_number: int
    event_key: str
    snapshot_id: str
    as_of: str = Field(description="Only data before this time is in the snapshot.")
    data_through: str | None = Field(description="Time of the latest qualification match in the snapshot.")
    validation_status: Literal["not_validated"]
    thresholds_status: Literal["candidate_unapproved"]
    rank: P11ARankOut
    matches_played: int
    matches: list[P11AMatchOut]
    consistency: P11AConsistencyOut
    estimates: P11AEstimatesOut | None
    estimates_absent_reason: str | None
    fit_diagnostics: dict[Component, P11AFitDiagnosticsOut] | None
    prior: P11APriorOut | None
    prior_absent_reason: str | None
    scouting: P11AScoutingOut | None
    scouting_absent_reason: str | None
    alliance_fit: P11AAllianceFitOut | None
    alliance_fit_absent_reason: str | None
    strengths_and_weaknesses_absent_reason: str
    last_updated: str | None = Field(default=None, description="The newest input time behind this profile (latest "
                                                               "match, ranking fetch or scouting summary; all at or "
                                                               "before as_of).")
    provenance: P11AProvenanceOut


# --- envelopes --------------------------------------------------------------------------------------------------------


class _P11AEnvelope(BaseModel):
    record_id: int
    record_seq: int = Field(description="The record version this reflects.")
    computed_at: datetime
    source: Literal["p11a_expected_score_plan"]
    experimental: Literal[True]
    relation_to_recommendations: str
    status: Literal["current", "withheld"]
    withheld: P11ACodeMessage | None
    timing_ms: dict[str, float]


class AlliancePlanOut(_P11AEnvelope):
    plan: P11APlanOut | None


class TeamProfileOut(_P11AEnvelope):
    profile: P11AProfileOut | None


P11ACardOut.model_rebuild()

__all__ = ["AlliancePlanOut", "P11APlanOut", "P11AProfileOut", "TeamProfileOut"]
