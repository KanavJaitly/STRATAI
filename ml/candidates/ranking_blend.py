"""RANK-BLEND-v1: prior EPA blended with the in-event average, for event rankings. A RESEARCH CANDIDATE, not served.

Frozen spec: .agent/model_candidates/RANK-BLEND-v1.md (audit 2026-11-26, workstream 2). Any change to the definition
below is a new candidate version.

**Definition.** For one team at one decision snapshot (ml/backtest/ranking_midpoint.py: the team's k-th qualification
match at the event, k = ceil(n/2) for the primary midpoint rule):

    rating = mean of the available values among { epa_total, average_score / 3 }

- `epa_total`: the team's as-of EPA from its latest strictly earlier event (D13/D18), in that source's points;
- `average_score / 3`: the team's mean alliance score in its qualification matches at this event strictly before
  the snapshot match (Phase 3's average_score), divided by the three robots of an alliance;
- one value missing: the other alone. A rookie or a team with no earlier event has no EPA. At the first snapshot,
  no team has an in-event average;
- both missing: no rating. The team is ranked last (the evaluation's convention: rating MISSING).

Equal weights, unfitted: nothing here was estimated on any season. Both inputs are fields of the snapshot's
TeamFeatures, built as of the snapshot match's scheduled time, so the rating uses no information from that match or
any later one.

**Known limitation (kept, not fixed, to match what the audit measured):** the two values are raw points. When a team's
EPA comes from an earlier season (early in a season), its units differ from the in-event average. A scale-normalized
blend would be a new candidate with its own spec.
"""

from __future__ import annotations

import statistics

from ml.features.assembler import TeamFeatures

CANDIDATE_ID = "RANK-BLEND-v1"
ROBOTS_PER_ALLIANCE = 3
MISSING = -1e9  # ranked last by the evaluation (ml.backtest.ranking_midpoint.evaluate_ranking sorts by rating)


def blend_inputs(team: TeamFeatures) -> list[float]:
    """The available inputs, in a fixed order: EPA, then the in-event per-robot average."""
    values = []
    if team.epa_total is not None:
        values.append(float(team.epa_total))
    if team.average_score is not None:
        values.append(team.average_score / ROBOTS_PER_ALLIANCE)
    return values


def blend_rating(team: TeamFeatures) -> float | None:
    """The candidate's rating, or None when the team has neither input."""
    values = blend_inputs(team)
    return statistics.fmean(values) if values else None


def blend_rating_for_evaluation(team: TeamFeatures) -> float:
    """blend_rating with MISSING for no rating, the form evaluate_ranking takes."""
    rating = blend_rating(team)
    return MISSING if rating is None else rating


__all__ = ["CANDIDATE_ID", "MISSING", "blend_inputs", "blend_rating", "blend_rating_for_evaluation"]
