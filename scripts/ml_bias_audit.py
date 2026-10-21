"""One command demonstrating Phase 4's unbiasedness guarantees, replacing
scattered ad-hoc checks with a single audit every future model must pass.

Phase 4 Milestone 8 (docs/P4Milestones.md). Runs, across the real M5/M6
models:

1. Symmetry -- win-prob model: swap(red, blue) => p -> 1-p, exactly.
2. Order-invariance -- repeated/reordered calls to identical input give
   identical output, for both the ranking and win-prob models.
3. No-strategy-leakage -- no field on TeamFeatures/MatchFeatureRow encodes a
   recommendation source, a coach-vs-AI distinction, or anything beyond
   red/blue's own structural alliance-color meaning.
4. As-of-feature integrity -- MatchFeatureRow still structurally refuses a
   naive (non-timezone-aware) as_of, confirming Milestone 1's point-in-time
   schema guarantee is unweakened by anything built since.
5. Label-shuffle leakage -- on synthetic data with a known ground-truth
   skill signal, a model fit on correctly-labeled data recovers a strong
   correlation with that signal; the SAME model class fit on the same data
   with outcomes shuffled should not (see ml.models.ranking_xgb/win_prob's
   own test suites, which this reuses the identical technique from).

This audit is the deliverable itself, per the milestone's own wording -- it
does not conclude Milestone 8 is accepted merely by existing; it must
report every check passing against the real models, AND
tests/test_scripts_ml_bias_audit.py must prove it actually fails when
handed a deliberately-broken model (_ConstantAsymmetricWinProbModel), or
the audit would have no teeth.

Usage: python -m scripts.ml_bias_audit
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.backtest.harness import Model
from ml.backtest.metrics import spearman_correlation
from ml.dataset.builder import LABEL_BLUE_WIN, LABEL_RED_WIN, TrainingRow
from ml.features.assembler import EPA_WITHHELD_NO_PRIOR_EVENT, MatchFeatureRow, TeamFeatures
from ml.models.ranking_xgb import RankingXGBModel
from ml.models.win_prob import WinProbXGBModel

__all__ = [
    "AuditCheck",
    "AuditReport",
    "check_as_of_feature_integrity",
    "check_label_shuffle_leakage_ranking",
    "check_label_shuffle_leakage_win_prob",
    "check_no_strategy_leakage",
    "check_order_invariance_rating",
    "check_order_invariance_win_prob",
    "check_win_prob_symmetry",
    "run_full_audit",
]

_T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
_NUM_TEAMS = 24

# Fields that would encode a recommendation source or coach-vs-AI
# distinction if any of them ever appeared -- checked structurally against
# the real, live schema below, not asserted from memory of what the schema
# used to contain.
_DISALLOWED_FIELD_SUBSTRINGS = ("strategy", "recommendation", "coach", "proposer", "proposal", "source_type")


@dataclass(frozen=True)
class AuditCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class AuditReport:
    checks: tuple[AuditCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def summary(self) -> str:
        lines = [f"Phase 4 Milestone 8 bias/leakage audit -- {'PASS' if self.passed else 'FAIL'}", ""]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"[{status}] {check.name}: {check.detail}")
        return "\n".join(lines)


def _team_features(team_number: int, *, average_score: float | None = None) -> TeamFeatures:
    return TeamFeatures(
        team_number=team_number,
        epa_total_present=False, epa_auto_present=False, epa_teleop_present=False, epa_endgame_present=False,
        epa_source_event_key=None, epa_withheld_reason=EPA_WITHHELD_NO_PRIOR_EVENT,
        average_score=average_score, average_score_present=average_score is not None,
        score_stddev_present=False, consistency_rating_present=False, reliability_score_present=False,
        matches_considered=5, matches_used=5,
        average_auto_points_present=False, auto_points_matches_used=0,
        defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
        feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
    )


def _random_alliance(rng: random.Random, base: int) -> list[TeamFeatures]:
    return [_team_features(base + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)]


def _match_features(red_teams: list[TeamFeatures], blue_teams: list[TeamFeatures]) -> MatchFeatureRow:
    return MatchFeatureRow(
        match_key="9995zzzaudit_qm1", as_of=_T0, event_key="9995zzzaudit", season=9995,
        red_teams=red_teams, blue_teams=blue_teams,
    )


def _skill(team_index: int) -> float:
    return 20.0 + 2.0 * team_index


def _synthetic_win_prob_rows(count: int = 80, *, shuffle: bool = False) -> list[TrainingRow]:
    """A synthetic dataset where the stronger alliance (higher summed
    average_score) tends to win -- real, deterministic signal. shuffle=True
    keeps every match's own team composition identical but reassigns each
    match's outcome from a different match via a fixed-seed random
    permutation, decoupling team features from outcome for the label-shuffle
    leakage check (see ml.models.win_prob's own test suite for why a simple
    reversal was tried first and rejected: this fixture's smooth,
    index-linked composition lets a plain reversal still correlate).
    """
    rng = random.Random(2026)
    alliances = [
        (
            [_team_features(9800 + match_index * 6 + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)],
            [_team_features(9800 + match_index * 6 + 3 + i, average_score=rng.uniform(10.0, 60.0)) for i in range(3)],
        )
        for match_index in range(count)
    ]
    outcomes = [
        LABEL_RED_WIN if sum(t.average_score for t in red) > sum(t.average_score for t in blue) else LABEL_BLUE_WIN
        for red, blue in alliances
    ]

    outcome_indices = list(range(count))
    if shuffle:
        random.Random(4242).shuffle(outcome_indices)

    rows: list[TrainingRow] = []
    for match_index, (red_teams, blue_teams) in enumerate(alliances):
        label = outcomes[outcome_indices[match_index]]
        score_red, score_blue = (100, 80) if label == LABEL_RED_WIN else (80, 100)
        rows.append(TrainingRow(
            match_key=f"9995zzzaudit_qm{match_index + 1}", event_key="9995zzzaudit", season=9995,
            comp_level="qualification", set_number=None, match_number=match_index + 1,
            scheduled_time=_T0 + timedelta(hours=match_index), label=label,
            score_margin=score_red - score_blue, score_red=score_red, score_blue=score_blue,
            red_teams=red_teams, blue_teams=blue_teams,
            red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
        ))
    return rows


def _synthetic_ranking_rows(count: int = 60, *, shuffle: bool = False) -> list[TrainingRow]:
    rows: list[TrainingRow] = []
    outcomes: list[tuple[str, int, int, int]] = []
    for match_index in range(count):
        red_indices = [(match_index + offset) % _NUM_TEAMS for offset in (0, 1, 2)]
        blue_indices = [(match_index + offset) % _NUM_TEAMS for offset in (12, 13, 14)]
        margin = round(sum(_skill(i) for i in red_indices) - sum(_skill(i) for i in blue_indices))
        label = LABEL_RED_WIN if margin > 0 else LABEL_BLUE_WIN
        score_red, score_blue = 100 + max(margin, 0), 100 + max(-margin, 0)
        outcomes.append((label, margin, score_red, score_blue))

    outcome_indices = list(range(count))
    if shuffle:
        random.Random(1234).shuffle(outcome_indices)

    for match_index in range(count):
        red_indices = [(match_index + offset) % _NUM_TEAMS for offset in (0, 1, 2)]
        blue_indices = [(match_index + offset) % _NUM_TEAMS for offset in (12, 13, 14)]
        red_teams = [_team_features(9800 + i, average_score=_skill(i)) for i in red_indices]
        blue_teams = [_team_features(9800 + i, average_score=_skill(i)) for i in blue_indices]
        label, margin, score_red, score_blue = outcomes[outcome_indices[match_index]]
        rows.append(TrainingRow(
            match_key=f"9996zzzaudit_qm{match_index + 1}", event_key="9996zzzaudit", season=9996,
            comp_level="qualification", set_number=None, match_number=match_index + 1,
            scheduled_time=_T0 + timedelta(hours=match_index), label=label,
            score_margin=margin, score_red=score_red, score_blue=score_blue,
            red_teams=red_teams, blue_teams=blue_teams,
            red_surrogate_team_numbers=[], blue_surrogate_team_numbers=[], dq_status_known=True,
        ))
    return rows


def check_win_prob_symmetry(model_factory: Callable[[], Model], *, trials: int = 25, tolerance: float = 1e-9) -> AuditCheck:
    """swap(red, blue) => p -> 1-p, exactly, across many random alliances."""
    model = model_factory()
    model.fit(_synthetic_win_prob_rows(count=60))
    rng = random.Random(7)
    max_violation = 0.0
    for trial in range(trials):
        red = _random_alliance(rng, 9800 + trial * 10)
        blue = _random_alliance(rng, 9900 + trial * 10)
        p_forward = model.predict_win_prob(_match_features(red, blue))
        p_swapped = model.predict_win_prob(_match_features(blue, red))
        max_violation = max(max_violation, abs(p_forward - (1.0 - p_swapped)))
    passed = max_violation <= tolerance
    return AuditCheck(
        "symmetry", passed,
        f"max |p(R,B) - (1-p(B,R))| across {trials} random alliance pairs = {max_violation:.2e} "
        f"(tolerance {tolerance:.0e})",
    )


def check_order_invariance_win_prob(model_factory: Callable[[], Model]) -> AuditCheck:
    model = model_factory()
    model.fit(_synthetic_win_prob_rows(count=60))
    rng = random.Random(11)
    red, blue = _random_alliance(rng, 9800), _random_alliance(rng, 9900)
    match = _match_features(red, blue)
    p1 = model.predict_win_prob(match)
    model.predict_win_prob(_match_features(_random_alliance(rng, 9950), _random_alliance(rng, 9960)))
    p2 = model.predict_win_prob(match)
    passed = p1 == p2
    return AuditCheck("order_invariance_win_prob", passed, f"repeated call to identical input: {p1} vs {p2}")


def check_order_invariance_rating(model_factory: Callable[[], Model]) -> AuditCheck:
    model = model_factory()
    model.fit(_synthetic_ranking_rows(count=40))
    team = _team_features(9800, average_score=_skill(5))
    r1 = model.predict_rating(team)
    model.predict_rating(_team_features(9950, average_score=_skill(2)))
    r2 = model.predict_rating(team)
    passed = r1 == r2
    return AuditCheck("order_invariance_rating", passed, f"repeated call to identical input: {r1} vs {r2}")


def check_no_strategy_leakage() -> AuditCheck:
    offending: list[str] = []
    for schema in (TeamFeatures, MatchFeatureRow):
        for field_name in schema.model_fields:
            lowered = field_name.lower()
            if any(bad in lowered for bad in _DISALLOWED_FIELD_SUBSTRINGS):
                offending.append(f"{schema.__name__}.{field_name}")
    passed = not offending
    detail = "no disallowed field names found" if passed else f"disallowed fields found: {offending}"
    return AuditCheck("no_strategy_leakage", passed, detail)


def check_as_of_feature_integrity() -> AuditCheck:
    """MatchFeatureRow must still structurally refuse a naive as_of --
    confirms Milestone 1's point-in-time schema guarantee has not been
    weakened by anything built since."""
    try:
        MatchFeatureRow(
            match_key="9995zzzaudit_qm1", as_of=datetime(2026, 3, 1, 10, 0),  # naive, deliberately
            event_key="9995zzzaudit", season=9995, red_teams=[], blue_teams=[],
        )
    except ValueError:
        return AuditCheck("as_of_feature_integrity", True, "MatchFeatureRow correctly refused a naive as_of")
    return AuditCheck("as_of_feature_integrity", False, "MatchFeatureRow accepted a naive as_of -- schema guarantee weakened")


def check_label_shuffle_leakage_ranking(
    model_factory: Callable[[], Model], *, correlation_floor: float = 0.6, collapse_margin: float = 0.3,
) -> AuditCheck:
    true_model = model_factory()
    true_model.fit(_synthetic_ranking_rows(count=60, shuffle=False))
    shuffled_model = model_factory()
    shuffled_model.fit(_synthetic_ranking_rows(count=60, shuffle=True))

    true_skill = [_skill(i) for i in range(_NUM_TEAMS)]
    true_predicted = [true_model.predict_rating(_team_features(9800 + i, average_score=_skill(i))) for i in range(_NUM_TEAMS)]
    shuffled_predicted = [shuffled_model.predict_rating(_team_features(9800 + i, average_score=_skill(i))) for i in range(_NUM_TEAMS)]

    true_correlation = spearman_correlation(true_predicted, true_skill) or 0.0
    shuffled_correlation = spearman_correlation(shuffled_predicted, true_skill) or 0.0
    passed = true_correlation >= correlation_floor and (true_correlation - shuffled_correlation) >= collapse_margin
    return AuditCheck(
        "label_shuffle_leakage_ranking", passed,
        f"true-label correlation={true_correlation:.3f} (floor {correlation_floor}), "
        f"shuffled-label correlation={shuffled_correlation:.3f}, "
        f"collapse={true_correlation - shuffled_correlation:.3f} (required >= {collapse_margin})",
    )


def check_label_shuffle_leakage_win_prob(
    model_factory: Callable[[], Model], *, min_prob_gap: float = 0.15,
) -> AuditCheck:
    """A strong-vs-weak alliance probe: the true-label model should favor a
    clearly-stronger alliance well above 0.5; a model fit on shuffled
    outcomes should show much less (or no) such preference."""
    true_model = model_factory()
    true_model.fit(_synthetic_win_prob_rows(count=80, shuffle=False))
    shuffled_model = model_factory()
    shuffled_model.fit(_synthetic_win_prob_rows(count=80, shuffle=True))

    strong_red = [_team_features(9800 + i, average_score=55.0) for i in range(3)]
    weak_blue = [_team_features(9900 + i, average_score=15.0) for i in range(3)]
    match = _match_features(strong_red, weak_blue)

    true_p = true_model.predict_win_prob(match)
    shuffled_p = shuffled_model.predict_win_prob(match)
    true_gap = abs(true_p - 0.5)
    shuffled_gap = abs(shuffled_p - 0.5)
    passed = true_gap >= min_prob_gap and true_gap > shuffled_gap
    return AuditCheck(
        "label_shuffle_leakage_win_prob", passed,
        f"true-label |p-0.5|={true_gap:.3f} (floor {min_prob_gap}), shuffled-label |p-0.5|={shuffled_gap:.3f}",
    )


def run_full_audit(
    ranking_model_factory: Callable[[], Model] = RankingXGBModel,
    win_prob_model_factory: Callable[[], Model] = WinProbXGBModel,
) -> AuditReport:
    checks = (
        check_win_prob_symmetry(win_prob_model_factory),
        check_order_invariance_win_prob(win_prob_model_factory),
        check_order_invariance_rating(ranking_model_factory),
        check_no_strategy_leakage(),
        check_as_of_feature_integrity(),
        check_label_shuffle_leakage_ranking(ranking_model_factory),
        check_label_shuffle_leakage_win_prob(win_prob_model_factory),
    )
    return AuditReport(checks)


def main() -> int:
    report = run_full_audit()
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
