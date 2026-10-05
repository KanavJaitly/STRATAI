"""Synthetic fixtures for Phase 6 tests. Not real data, not evidence for any milestone."""

from __future__ import annotations

from ml.features.assembler import TeamFeatures


def team(number: int, auto: float | None = 5.0, teleop: float | None = 20.0, endgame: float | None = 5.0, *,
         epa_scale: float | None = 10.0, score_scale: float | None = 20.0, **extra) -> TeamFeatures:
    """A TeamFeatures with EPA components and causal scales; every other value absent."""
    present = all(v is not None for v in (auto, teleop, endgame))
    total = (auto + teleop + endgame) if present else None
    values = dict(
        team_number=number,
        epa_total=total, epa_total_present=total is not None,
        epa_auto=auto, epa_auto_present=auto is not None,
        epa_teleop=teleop, epa_teleop_present=teleop is not None,
        epa_endgame=endgame, epa_endgame_present=endgame is not None,
        average_score_present=False, score_stddev_present=False, consistency_rating_present=False,
        reliability_score_present=False, matches_considered=0, matches_used=0,
        average_auto_points_present=False, auto_points_matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
        score_scale=score_scale, score_scale_present=score_scale is not None,
        epa_scale=epa_scale, epa_scale_present=epa_scale is not None,
        epa_value_source="statbotics" if present else None,
        epa_source_event_key="2099fixture" if present or epa_scale is not None else None,
        epa_withheld_reason=None if present or epa_scale is not None else "fixture_withheld",
    )
    values.update(extra)
    return TeamFeatures(**values)


# A fitted-looking parameter set for unit tests only (not the registered P6-M10 artifact).
FIXTURE_BETA = {"auto": 0.9, "teleop": 0.8, "endgame": 0.7}
FIXTURE_SIGMA = [[0.10, 0.02, 0.0, 0.0], [0.02, 0.50, 0.05, 0.0], [0.0, 0.05, 0.08, 0.0], [0.0, 0.0, 0.0, 0.06]]
