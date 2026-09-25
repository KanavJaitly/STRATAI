"""Alliance synergy scoring: a documented, deterministic, explainable score
for how well three teams complement each other -- not merely how strong
each one is individually.

Phase 4 Milestone 9 (docs/P4Milestones.md). Explicitly NOT the pick-list
optimizer (Phase 6) -- this is the scoring primitive a future optimizer will
call, one alliance at a time. Pure function of team_metrics-shaped features
(ml.features.assembler.TeamFeatures) -- no model, no database, no fitting.

No stored "role" field exists anywhere in this codebase's schema (confirmed
before writing any code -- TeamFeatures has average_score/defense_score/
feeding_score/epa_auto/epa_teleop/epa_endgame, never a role label), so
"role fit" and "scoring-distribution complementarity" are both computed as
SHARE VECTORS: for one axis (say average_score), each team's share is its
own value divided by the three teams' combined total on that SAME axis --
a dimensionless [0, 1] proportion, never a raw value. This is what makes the
three components comparable at all: average_score (raw game points),
defense_score/feeding_score (0-5 scale), and epa_auto/epa_teleop/epa_endgame
(Statbotics' own units) have no shared unit, but "what share of this
alliance's total scoring capability comes from me" is unit-free and
comparable across axes.

Two independent share-vector groups, matching the milestone's own literal
three-part wording:

    1. role_fit: share vectors over (average_score, defense_score,
       feeding_score) -- do the three teams cover distinct FUNCTIONAL roles
       (scorer / defender / feeder), or is one function triple-covered while
       another goes entirely unaddressed?
    2. scoring_distribution: share vectors over (epa_auto, epa_teleop,
       epa_endgame) -- WITHIN scoring specifically, do the three teams cover
       distinct game phases, or are all three redundant teleop-only scorers?

Each is scored as 1 - mean pairwise cosine similarity of the three teams'
share vectors on that axis group: three identical share vectors (perfect
redundancy) give cosine similarity 1, so a score of 0; three vectors
pointing in maximally different directions give similarity 0, so a score
near 1. This is the concrete meaning of "synergy != sum of EPA": a change
to a team's share vector shape (not just its magnitude) moves this term.

An axis is only used if ALL THREE teams have that field's presence flag
True -- mirroring ml.models.baselines._alliance_epa_sum's existing "any
absence excludes the whole aggregate" precedent, applied per-axis rather
than blanket-across-every-axis, since average_score being absent for one
team should not also blank out an otherwise-computable epa_auto comparison.
An axis GROUP with zero usable axes reports its own term as None (no
fabricated 0.0) -- there is no way to assess complementarity across zero
comparable dimensions, and a lone usable axis reports the group's term as
exactly 0.0 (see _pairwise_cosine_diversity's own docstring for why: cosine
similarity of any two same-signed 1-D vectors is always 1, so one axis
alone can never demonstrate complementarity, which is real math, not an
approximation).

defense_feeding_coverage is scored differently, deliberately, per the
milestone's own separate wording ("defense/feeding coverage" as its own
component, not folded into role_fit): it is the mean of every PRESENT
defense_score/feeding_score value across the alliance (each on their native
0-5 scale, normalized to 0-1 by /5), never treating an absent value as 0 --
CLAUDE.md's "insufficient_data propagates" rule applied directly to this
component's own math, not merely documented as a caveat. coverage_present_
count (out of 6: 3 teams x 2 metrics) and the overall confidence field make
"we don't actually know this alliance's defense/feeding capability" visible
rather than indistinguishable from "we measured it and it's genuinely poor."

overall_score is a weighted combination of whichever of the three
components are not None, renormalizing the configured weights over only
the available components -- the same "excluded, not fabricated" discipline
ml.backtest.harness.run_ranking_backtest already applies to an event with no
final_ranks entry. overall_score is None only when literally none of the
three components could be computed at all (every team missing every field).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, Field

from ml.features.assembler import TeamFeatures

__all__ = [
    "SynergyWeights",
    "DEFAULT_SYNERGY_WEIGHTS",
    "AllianceSynergyScore",
    "alliance_synergy",
]


@dataclass(frozen=True)
class SynergyWeights:
    """Documented, configurable weights for overall_score's three
    components. Callers may supply their own; the defaults below are this
    milestone's own starting point, not a fitted or otherwise data-derived
    value -- there is no ground truth for "correct" alliance synergy to fit
    against, so these are a documented, reconstructable starting position a
    strategist can override, per the milestone's own "weights documented and
    configurable" instruction.
    """

    role_fit: float = 0.4
    scoring_distribution: float = 0.3
    defense_feeding_coverage: float = 0.3

    def __post_init__(self) -> None:
        for name, value in (
            ("role_fit", self.role_fit),
            ("scoring_distribution", self.scoring_distribution),
            ("defense_feeding_coverage", self.defense_feeding_coverage),
        ):
            if value < 0:
                raise ValueError(f"SynergyWeights.{name} must be >= 0, got {value}")
        if self.role_fit + self.scoring_distribution + self.defense_feeding_coverage <= 0:
            raise ValueError("at least one SynergyWeights component must be positive")


DEFAULT_SYNERGY_WEIGHTS = SynergyWeights()

_ROLE_FIT_AXES: tuple[tuple[str, str], ...] = (
    ("average_score", "average_score_present"),
    ("defense_score", "defense_score_present"),
    ("feeding_score", "feeding_score_present"),
)
_SCORING_DISTRIBUTION_AXES: tuple[tuple[str, str], ...] = (
    ("epa_auto", "epa_auto_present"),
    ("epa_teleop", "epa_teleop_present"),
    ("epa_endgame", "epa_endgame_present"),
)


class AllianceSynergyScore(BaseModel):
    """One alliance's full synergy breakdown -- every component an
    experienced strategist could reconstruct from this module's own
    documented formula, not a black-box number.
    """

    overall_score: float | None
    role_fit_term: float | None
    role_fit_axes_used: list[str] = Field(default_factory=list)
    scoring_distribution_term: float | None
    scoring_distribution_axes_used: list[str] = Field(default_factory=list)
    defense_feeding_coverage_term: float | None
    defense_feeding_coverage_present_count: int = Field(ge=0, le=6)
    confidence: float = Field(ge=0.0, le=1.0)


def _pairwise_cosine_diversity(vectors: list[list[float]]) -> float:
    """1 - mean pairwise cosine similarity across exactly three non-negative
    share vectors (all axes >= 0 by construction, since every source field
    here is itself non-negative). Three identical vectors give similarity 1
    (diversity 0, fully redundant). Three vectors on distinct, non-
    overlapping axes give similarity 0 (diversity 1, fully complementary).

    A single-axis (length-1) vector is mathematically always "similar" to
    any other single-axis vector of the same sign -- cosine similarity in
    one dimension collapses to exactly 1.0 regardless of magnitude, since
    both vectors point along the same one-dimensional line. This is real
    linear algebra, not an approximation this function chooses: with only
    one comparable axis, there is no notion of "differently shaped" left to
    measure, so diversity is correctly, structurally 0.0 in that case, and
    callers (see the module docstring) treat zero usable axes, not one, as
    the "nothing computable" case reported as None.
    """
    pairs = [(vectors[0], vectors[1]), (vectors[0], vectors[2]), (vectors[1], vectors[2])]
    similarities = []
    for a, b in pairs:
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            # A team with a zero vector on every usable axis (every present
            # value happened to be exactly 0.0) contributes no directional
            # information -- treated as maximally dissimilar to avoid
            # dividing by zero, documented here rather than silently
            # producing a NaN.
            similarities.append(0.0)
            continue
        dot = sum(x * y for x, y in zip(a, b))
        similarities.append(dot / (norm_a * norm_b))
    return 1.0 - (sum(similarities) / len(similarities))


def _axis_group_term(
    teams: tuple[TeamFeatures, TeamFeatures, TeamFeatures], axes: tuple[tuple[str, str], ...],
) -> tuple[float | None, list[str]]:
    """Share-vector diversity across whichever axes ALL THREE teams have
    present, for one axis group (role_fit's three functional axes, or
    scoring_distribution's three EPA-component axes).

    Returns (term, axes_used) -- term is None if zero axes are usable
    (nothing to compare), matching every other "excluded, not fabricated"
    aggregate in this codebase.
    """
    usable_axes: list[tuple[str, str]] = []
    for value_field, present_field in axes:
        if all(getattr(team, present_field) for team in teams):
            usable_axes.append((value_field, present_field))

    if not usable_axes:
        return None, []

    axis_names = [value_field for value_field, _ in usable_axes]
    totals = {
        value_field: sum(getattr(team, value_field) for team in teams)
        for value_field, _ in usable_axes
    }
    share_vectors: list[list[float]] = []
    for team in teams:
        vector = []
        for value_field, _ in usable_axes:
            total = totals[value_field]
            value = getattr(team, value_field)
            vector.append(0.0 if total == 0.0 else value / total)
        share_vectors.append(vector)

    return _pairwise_cosine_diversity(share_vectors), axis_names


def _defense_feeding_coverage_term(
    teams: tuple[TeamFeatures, TeamFeatures, TeamFeatures],
) -> tuple[float | None, int]:
    """Mean of every PRESENT defense_score/feeding_score across the
    alliance, each normalized to [0, 1] by /5 (both fields' documented
    native scale, data/metrics/schemas.py). Absent values are excluded from
    the mean entirely -- never averaged in as 0.0. present_count is out of
    6 (3 teams x 2 metrics), reported alongside the term so a caller can
    see exactly how much real evidence the term reflects.
    """
    present_values: list[float] = []
    present_count = 0
    for team in teams:
        if team.defense_score_present:
            assert team.defense_score is not None
            present_values.append(team.defense_score / 5.0)
            present_count += 1
        if team.feeding_score_present:
            assert team.feeding_score is not None
            present_values.append(team.feeding_score / 5.0)
            present_count += 1

    if not present_values:
        return None, 0
    return sum(present_values) / len(present_values), present_count


def alliance_synergy(
    team_a: TeamFeatures, team_b: TeamFeatures, team_c: TeamFeatures, *, weights: SynergyWeights = DEFAULT_SYNERGY_WEIGHTS,
) -> AllianceSynergyScore:
    """Score one three-team alliance's synergy -- deterministic, explainable,
    and never fabricating a value for data that is genuinely absent. See the
    module docstring for the full formula and rationale.
    """
    teams = (team_a, team_b, team_c)

    role_fit_term, role_fit_axes = _axis_group_term(teams, _ROLE_FIT_AXES)
    scoring_distribution_term, scoring_distribution_axes = _axis_group_term(teams, _SCORING_DISTRIBUTION_AXES)
    coverage_term, coverage_present_count = _defense_feeding_coverage_term(teams)

    components = [
        (weights.role_fit, role_fit_term),
        (weights.scoring_distribution, scoring_distribution_term),
        (weights.defense_feeding_coverage, coverage_term),
    ]
    available = [(weight, term) for weight, term in components if term is not None]

    if not available:
        overall_score = None
    else:
        weight_sum = sum(weight for weight, _ in available)
        overall_score = (
            sum(weight * term for weight, term in available) / weight_sum if weight_sum > 0 else None
        )

    # Confidence: how much of the three components' own possible evidence is
    # actually present -- an equally-weighted average of each component's own
    # completeness, not the overall_score itself (a low-confidence score and
    # a low score are different claims, and conflating them would silently
    # assert certainty about something this module could not actually verify).
    role_fit_completeness = len(role_fit_axes) / len(_ROLE_FIT_AXES)
    scoring_distribution_completeness = len(scoring_distribution_axes) / len(_SCORING_DISTRIBUTION_AXES)
    coverage_completeness = coverage_present_count / 6.0
    confidence = (role_fit_completeness + scoring_distribution_completeness + coverage_completeness) / 3.0

    return AllianceSynergyScore(
        overall_score=overall_score,
        role_fit_term=role_fit_term, role_fit_axes_used=role_fit_axes,
        scoring_distribution_term=scoring_distribution_term, scoring_distribution_axes_used=scoring_distribution_axes,
        defense_feeding_coverage_term=coverage_term, defense_feeding_coverage_present_count=coverage_present_count,
        confidence=confidence,
    )
