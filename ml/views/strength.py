"""P5-M3 team and robot strength view (docs/P5Milestones.md, frozen P5-M0).

One team, one event, one as_of. Every number is computed exactly as Phase 3/4
compute it -- no new aggregation or statistic:

* EPA, Phase 3 scoring statistics, the event's auto points and defense/feeding come
  from ml.features.assembler.build_team_features, the same object the models read.
* Good/average/bad-day counts are Phase 3's classify_match_days applied to the same
  point-in-time scores build_team_features used.
* "Season-to-date auto points" is the Phase 4 per-event auto-points feature applied
  to each of the team's season events before as_of, listed per event. They are not
  pooled, because a pooled season average would be a new aggregate.

Why not team_metrics: that table is a current-state snapshot (docs/ml_models.md §1),
so reading it for a past as_of would leak later matches. The point-in-time
recomputation through the same Phase 3 functions is used instead.

Every numeric field carries its n and an uncertainty: an SD where Phase 3/4 report
one, otherwise an explicit "none" with the reason. An absent value is null, with the
reason it is absent. Every EPA value carries its provenance (epa_value_source,
epa_source_state, source event).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE
from data.metrics.schemas import MIN_MATCHES_FOR_STDDEV
from data.metrics.statistics import classify_match_days
from database.connection import Database
from ml.features.assembler import (
    TeamFeatures,
    build_team_features,
    point_in_time_auto_points,
    point_in_time_scores,
)
from ml.features.scale import ScaleLookup
from ml.ratings.provider import PointInTimeEpaProvider

DESCRIPTIVE = "descriptive"
DEFINITION_PENDING = "descriptive_definition_pending"  # Phase 3 M14: defense definition decision open
NOT_VALIDATED = "not_validated"  # feeding: no feeding data at collection time (Phase 3 M14)

NO_MATCHES = "no_completed_matches_before_as_of"
TOO_FEW_MATCHES = f"fewer_than_{MIN_MATCHES_FOR_STDDEV}_completed_matches_before_as_of"
UNDEFINED = "undefined_for_these_scores"
NO_BREAKDOWN = "no_matches_with_a_score_breakdown_before_as_of"
INSUFFICIENT_OBSERVATIONS = f"insufficient_data: fewer than {MIN_OBSERVATIONS_FOR_SCORE} scouting observations"

EPA_N_KIND = "canonical_completed_matches_at_source_event"
NONE_EPA = "the EPA source publishes a point estimate; no SD exists in canonical data"
NONE_STAT = "Phase 3/4 report no uncertainty for this statistic"
NONE_SCOUTING = "Phase 3 reports agreement (shown separately), not an SD"


class Uncertainty(BaseModel):
    kind: Literal["sd", "none"]
    value: float | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Uncertainty":
        if (self.kind == "sd") != (self.value is not None) or (self.kind == "none") != (self.reason is not None):
            raise ValueError("an SD uncertainty needs a value; a 'none' uncertainty needs a reason")
        return self


class Measure(BaseModel):
    value: float | None
    n: int
    uncertainty: Uncertainty
    absent_reason: str | None = None

    @model_validator(mode="after")
    def _absent_has_reason(self) -> "Measure":
        if (self.value is None) != (self.absent_reason is not None):
            raise ValueError("a measure is either present, or absent with a reason")
        return self


class EpaView(BaseModel):
    total: Measure
    auto: Measure
    teleop: Measure
    endgame: Measure
    epa_value_source: str | None
    epa_source_state: str | None
    source_event_key: str | None
    withheld_reason: str | None
    n_kind: str = EPA_N_KIND
    validation_status: str = DESCRIPTIVE


class ScoringView(BaseModel):
    average_score: Measure
    score_stddev: Measure
    consistency_rating: Measure
    reliability_score: Measure
    good_day_count: Measure
    average_day_count: Measure
    bad_day_count: Measure
    matches_considered: int
    validation_status: str = DESCRIPTIVE


class EventAutoPoints(BaseModel):
    event_key: str
    average_auto_points: Measure


class AutoPointsView(BaseModel):
    this_event: Measure
    season_by_event: list[EventAutoPoints]
    validation_status: str = DESCRIPTIVE


class ScoutingView(BaseModel):
    score: Measure
    agreement: Measure
    contributing_sources: list[str]
    validation_status: str


class TeamStrengthView(BaseModel):
    team_number: int
    event_key: str
    as_of: datetime
    epa: EpaView
    scoring: ScoringView
    auto_points: AutoPointsView
    defense: ScoutingView
    feeding: ScoutingView


def _none(reason: str) -> Uncertainty:
    return Uncertainty(kind="none", reason=reason)


def _measure(value: float | None, n: int, uncertainty: Uncertainty, absent: str) -> Measure:
    return Measure(value=value, n=n, uncertainty=uncertainty, absent_reason=None if value is not None else absent)


def _scoring_absent(matches_used: int) -> str:
    if matches_used == 0:
        return NO_MATCHES
    if matches_used < MIN_MATCHES_FOR_STDDEV:
        return TOO_FEW_MATCHES
    return UNDEFINED


_SOURCE_EVENT_MATCHES_SQL = """
SELECT COUNT(*) FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
WHERE mt.team_number = %s AND m.event_key = %s AND m.scheduled_time IS NOT NULL
  AND (CASE WHEN mt.alliance_color = 'red' THEN m.score_red ELSE m.score_blue END) IS NOT NULL
"""
# The team's events this season with at least one completed match before as_of.
_SEASON_EVENTS_SQL = """
SELECT m.event_key FROM match_teams mt JOIN matches m ON m.match_key = mt.match_key
WHERE mt.team_number = %(team)s AND m.season = %(season)s AND m.scheduled_time IS NOT NULL
  AND m.scheduled_time < %(as_of)s
  AND (CASE WHEN mt.alliance_color = 'red' THEN m.score_red ELSE m.score_blue END) IS NOT NULL
GROUP BY m.event_key ORDER BY MIN(m.scheduled_time), m.event_key
"""


def _epa_view(database: Database, features: TeamFeatures) -> EpaView:
    n = 0
    if features.epa_source_event_key is not None:
        with database.cursor() as cursor:
            cursor.execute(_SOURCE_EVENT_MATCHES_SQL, (features.team_number, features.epa_source_event_key))
            n = cursor.fetchone()[0]
    absent = features.epa_withheld_reason or ""
    values = (features.epa_total, features.epa_auto, features.epa_teleop, features.epa_endgame)
    total, auto, teleop, endgame = (_measure(v, n, _none(NONE_EPA), absent) for v in values)
    return EpaView(total=total, auto=auto, teleop=teleop, endgame=endgame,
                   epa_value_source=features.epa_value_source, epa_source_state=features.epa_source_state,
                   source_event_key=features.epa_source_event_key, withheld_reason=features.epa_withheld_reason)


def _scoring_view(features: TeamFeatures, scores: list[int]) -> ScoringView:
    used = features.matches_used
    absent = _scoring_absent(used)
    days = classify_match_days(scores)
    sd = Uncertainty(kind="sd", value=features.score_stddev) if features.score_stddev is not None else _none(
        TOO_FEW_MATCHES if used else NO_MATCHES)
    reliability_absent = absent if used else NO_MATCHES

    def day(key: str) -> Measure:
        return _measure(None if days is None else float(days[key]), used, _none(NONE_STAT), absent)

    return ScoringView(
        average_score=_measure(features.average_score, used, sd, NO_MATCHES),
        score_stddev=_measure(features.score_stddev, used, _none(NONE_STAT), absent),
        consistency_rating=_measure(features.consistency_rating, used, _none(NONE_STAT), absent),
        reliability_score=_measure(features.reliability_score, features.matches_considered, _none(NONE_STAT),
                                   reliability_absent),
        good_day_count=day("good"), average_day_count=day("average"), bad_day_count=day("bad"),
        matches_considered=features.matches_considered,
    )


def _scouting_view(score: float | None, agreement: float | None, count: int, sources: list[str],
                   status: str) -> ScoutingView:
    return ScoutingView(
        score=_measure(score, count, _none(NONE_SCOUTING), INSUFFICIENT_OBSERVATIONS),
        agreement=_measure(agreement, count, _none(NONE_STAT), INSUFFICIENT_OBSERVATIONS),
        contributing_sources=sources, validation_status=status)


def build_team_strength(
    database: Database, team_number: int, event_key: str, as_of: datetime,
    *, epa_provider: PointInTimeEpaProvider, scale_lookup: ScaleLookup | None = None,
) -> TeamStrengthView:
    """The P5-M3 view; every value equals what build_team_features computes."""
    scales = scale_lookup or ScaleLookup(database)
    features = build_team_features(database, team_number, event_key, as_of, epa_provider=epa_provider,
                                   scale_lookup=scales)
    scores, _ = point_in_time_scores(database, team_number, event_key, as_of)
    season = scales.event_season(event_key)
    season_by_event: list[EventAutoPoints] = []
    if season is not None:
        with database.cursor() as cursor:
            cursor.execute(_SEASON_EVENTS_SQL, {"team": team_number, "season": season, "as_of": as_of})
            event_keys = [row[0] for row in cursor.fetchall()]
        for key in event_keys:
            mean, n = point_in_time_auto_points(database, team_number, key, as_of)
            season_by_event.append(EventAutoPoints(event_key=key, average_auto_points=_measure(
                mean, n, _none(NONE_STAT), NO_BREAKDOWN)))
    return TeamStrengthView(
        team_number=team_number, event_key=event_key, as_of=as_of,
        epa=_epa_view(database, features),
        scoring=_scoring_view(features, scores),
        auto_points=AutoPointsView(
            this_event=_measure(features.average_auto_points, features.auto_points_matches_used, _none(NONE_STAT),
                                NO_BREAKDOWN),
            season_by_event=season_by_event),
        defense=_scouting_view(features.defense_score, features.defense_agreement,
                               features.defense_observation_count, list(features.contributing_scouting_sources),
                               DEFINITION_PENDING),
        feeding=_scouting_view(features.feeding_score, features.feeding_agreement,
                               features.feeding_observation_count, list(features.contributing_scouting_sources),
                               NOT_VALIDATED),
    )


def matches_features(view: TeamStrengthView, features: TeamFeatures) -> list[str]:
    """Fields where the view differs from build_team_features' TeamFeatures (empty = exact equality)."""
    pairs = {
        "epa_total": (view.epa.total.value, features.epa_total), "epa_auto": (view.epa.auto.value, features.epa_auto),
        "epa_teleop": (view.epa.teleop.value, features.epa_teleop),
        "epa_endgame": (view.epa.endgame.value, features.epa_endgame),
        "epa_value_source": (view.epa.epa_value_source, features.epa_value_source),
        "epa_source_state": (view.epa.epa_source_state, features.epa_source_state),
        "epa_source_event_key": (view.epa.source_event_key, features.epa_source_event_key),
        "epa_withheld_reason": (view.epa.withheld_reason, features.epa_withheld_reason),
        "average_score": (view.scoring.average_score.value, features.average_score),
        "score_stddev": (view.scoring.score_stddev.value, features.score_stddev),
        "consistency_rating": (view.scoring.consistency_rating.value, features.consistency_rating),
        "reliability_score": (view.scoring.reliability_score.value, features.reliability_score),
        "matches_used": (view.scoring.average_score.n, features.matches_used),
        "matches_considered": (view.scoring.matches_considered, features.matches_considered),
        "average_auto_points": (view.auto_points.this_event.value, features.average_auto_points),
        "auto_points_matches_used": (view.auto_points.this_event.n, features.auto_points_matches_used),
        "defense_score": (view.defense.score.value, features.defense_score),
        "defense_agreement": (view.defense.agreement.value, features.defense_agreement),
        "defense_observation_count": (view.defense.score.n, features.defense_observation_count),
        "feeding_score": (view.feeding.score.value, features.feeding_score),
        "feeding_agreement": (view.feeding.agreement.value, features.feeding_agreement),
        "feeding_observation_count": (view.feeding.score.n, features.feeding_observation_count),
    }
    return sorted(name for name, (a, b) in pairs.items() if a != b)
