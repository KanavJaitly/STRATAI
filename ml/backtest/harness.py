"""Temporal backtesting harness + model interface.

Phase 4 Milestone 3 (authoritative plan, docs/P4Milestones.md). "This is the
single gate everything after Phase 4 validates through" -- the milestone's
own words, and the reason this module refuses to guess anywhere a real
answer instead requires input it does not have.

Model protocol
==============
fit/predict_win_prob/predict_rating/save/load, exactly as named in the
milestone brief, as one flat typing.Protocol rather than two narrower ones.
A model built for ranking (Milestone 5) is not required to implement
predict_win_prob meaningfully, and a model built for win probability
(Milestone 6) is not required to implement predict_rating meaningfully --
each raises NotImplementedError for the capability it does not have. This
keeps "any conforming model runs through one entry point" literally true:
the harness always calls the same five-method shape, and simply never calls
the method a given evaluation mode does not need.

fit/predict_win_prob/predict_rating are typed directly against Milestone 1's
and Milestone 2's own models (TrainingRow, MatchFeatureRow, TeamFeatures) --
no new "X/y" abstraction invented here, so a model implementation extracts
whatever it needs from data these two milestones already assembled.

Split integrity
================
Fold is the one place "no future data in any train fold" is enforced, not
merely tested for after the fact: its own __post_init__ raises if
max(train.scheduled_time) >= min(test.scheduled_time), for every fold this
module ever constructs. That is a real, non-obvious constraint on hold_out_
season_split specifically: holding out an EARLIER season while training on a
LATER one would violate it, so hold_out_season_split can only ever hold out
the chronologically last season present in the data -- attempting to hold
out an earlier one raises here, at construction, not silently after
producing a leaky split. walk_forward_splits' week-ordered construction
satisfies the same guarantee by the way weeks are built (non-overlapping,
strictly increasing), and still passes through the identical assertion.

The genuinely-unresolved gap this milestone's own research surfaced
====================================================================
"Ranking metrics (Spearman vs final rank, top-8 recall)" needs each team's
REAL final event ranking as ground truth to evaluate against. No canonical
table, no TBA client model, anywhere in this codebase has ever landed a
team's final event rank -- confirmed by searching every migration and every
client/staging schema, not assumed. TBA's real API does expose event
rankings (a well-known, separate endpoint from the ones this pipeline
already calls), but nothing here fetches or stores them. This is more
fundamental than "no reachable database in this sandbox": even with a fully
populated, reachable database, there is currently nothing to compare a
ranking model's predictions against.

This module does not solve that -- ingesting a new TBA endpoint into a new
canonical table is Phase 2/3-shaped infrastructure work, not something this
milestone's own brief asks for, and inventing it now would be exactly the
scope expansion prompts/MASTER_BUILD.md's "Scope Control" section forbids
for an issue that "belongs clearly to a later milestone but creates no
current defect." Instead, run_ranking_backtest takes final_ranks as an
explicit, externally-supplied argument (event_key -> {team_number: rank}),
so the harness is fully correct and fully testable today against
hand-constructed ground truth, and becomes usable against real data the
moment a real source for it exists -- without this module changing at all.
Milestone 5 (the first milestone that needs a REAL ranking backtest to claim
"beats baseline") is where this gap actually becomes blocking, and it is
flagged prominently there rather than silently deferred without a trace.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, Self, runtime_checkable

from pydantic import BaseModel

from ml.backtest.metrics import (
    accuracy,
    brier_score,
    expected_calibration_error,
    log_loss,
    roc_auc,
    spearman_correlation,
    top_k_recall,
)
from ml.dataset.builder import LABEL_RED_WIN, LABEL_TIE, TrainingRow
from ml.features.assembler import MatchFeatureRow, TeamFeatures

__all__ = [
    "MODE_RANKING",
    "MODE_WIN_PROB",
    "SPLIT_HOLD_OUT_SEASON",
    "SPLIT_WALK_FORWARD",
    "BacktestResult",
    "Fold",
    "FoldMetrics",
    "Model",
    "hold_out_season_split",
    "run_ranking_backtest",
    "run_win_prob_backtest",
    "walk_forward_splits",
]

MODE_WIN_PROB = "win_prob"
MODE_RANKING = "ranking"

SPLIT_HOLD_OUT_SEASON = "hold_out_season"
SPLIT_WALK_FORWARD = "walk_forward"


@runtime_checkable
class Model(Protocol):
    """The uniform interface every StratAI model conforms to, per this
    milestone's own named methods. See the module docstring for why both
    predict_* methods live on one protocol rather than two.
    """

    def fit(self, training_rows: Sequence[TrainingRow]) -> None:
        """Train (or retrain) this model instance on these labeled rows."""
        ...

    def predict_win_prob(self, match_features: MatchFeatureRow) -> float:
        """P(red wins) for one match's point-in-time features. Raise
        NotImplementedError if this model does not support win-probability
        prediction."""
        ...

    def predict_rating(self, team_features: TeamFeatures) -> float:
        """A single team's predicted strength/rating. Raise
        NotImplementedError if this model does not support rating
        prediction."""
        ...

    def save(self, path: Path) -> None:
        """Persist this model's fitted state to path."""
        ...

    @classmethod
    def load(cls, path: Path) -> Self:
        """Restore a model previously written by save()."""
        ...


@dataclass(frozen=True)
class Fold:
    """One train/test split. Every Fold that exists is temporally safe by
    construction -- see the module docstring's "Split integrity" section.

    split_strategy (SPLIT_HOLD_OUT_SEASON or SPLIT_WALK_FORWARD) travels with
    the fold rather than being supplied separately by whoever calls
    run_win_prob_backtest/run_ranking_backtest -- a free-standing "which
    strategy was this" parameter on the run_* functions would be nothing
    more than a label the caller has to remember to keep in sync with
    whichever split function they actually called, and a mismatch there
    would silently mislabel BacktestResult.summary() without anything
    catching it. Carrying it on the Fold itself makes that impossible: the
    run_* functions derive BacktestResult.split_strategy directly from the
    folds they were handed.
    """

    label: str
    train_rows: list[TrainingRow]
    test_rows: list[TrainingRow]
    split_strategy: str

    def __post_init__(self) -> None:
        if self.train_rows and self.test_rows:
            max_train = max(row.scheduled_time for row in self.train_rows)
            min_test = min(row.scheduled_time for row in self.test_rows)
            if not max_train < min_test:
                raise ValueError(
                    f"Fold {self.label!r} violates temporal ordering: "
                    f"max(train.scheduled_time)={max_train} is not strictly before "
                    f"min(test.scheduled_time)={min_test}"
                )


def hold_out_season_split(rows: Sequence[TrainingRow], held_out_season: int) -> Fold:
    """Train on every season except held_out_season, test on held_out_season.

    Raises ValueError if held_out_season has no rows (nothing to test) or if
    holding it out would leave nothing to train on -- both caller errors, not
    silent empty folds. Fold's own __post_init__ additionally raises if
    held_out_season is not actually the chronologically last season present:
    holding out an earlier season while training on a later one would put
    future data in the train fold, exactly what this milestone's brief
    forbids.
    """
    train_rows = [row for row in rows if row.season != held_out_season]
    test_rows = [row for row in rows if row.season == held_out_season]
    if not test_rows:
        raise ValueError(f"held_out_season={held_out_season} has no matching rows to test on")
    if not train_rows:
        raise ValueError(f"holding out season={held_out_season} would leave no rows to train on")
    return Fold(
        label=f"hold_out_season_{held_out_season}", train_rows=train_rows, test_rows=test_rows,
        split_strategy=SPLIT_HOLD_OUT_SEASON,
    )


def _iso_week_key(dt: datetime) -> tuple[int, int]:
    """(ISO year, ISO week number) of a scheduled_time.

    A documented simplification, not FRC's own official "Week 0/Week 1..."
    labeling (which counts weeks relative to that season's kickoff date, not
    the calendar's ISO week structure) -- chosen because TrainingRow carries
    no event start_date/season-relative week number today, and deriving one
    would mean either a new field on Milestone 2's already-accepted model or
    a second join back to `events`. ISO week is a simple, deterministic,
    already-available proxy for "which chunk of the season did this match
    happen in", sufficient for a walk-forward split's own requirement
    (train on earlier chunks, test on the next one) without needing FRC's
    literal week numbering to be correct.
    """
    iso = dt.isocalendar()
    return (iso.year, iso.week)


def walk_forward_splits(rows: Sequence[TrainingRow]) -> list[Fold]:
    """One fold per week boundary: train on weeks 1..k, test on week k+1,
    for every k from 1 to (number of distinct weeks - 1).

    Weeks with zero rows do not appear (there is nothing to bucket), so the
    produced folds are exactly the boundaries between weeks that actually
    have data. Returns an empty list if rows span fewer than 2 distinct
    weeks -- there is no boundary to walk forward across.
    """
    by_week: dict[tuple[int, int], list[TrainingRow]] = {}
    for row in rows:
        by_week.setdefault(_iso_week_key(row.scheduled_time), []).append(row)

    ordered_weeks = sorted(by_week.keys())
    folds: list[Fold] = []
    for k in range(1, len(ordered_weeks)):
        train_weeks = ordered_weeks[:k]
        test_week = ordered_weeks[k]
        train_rows = [row for week in train_weeks for row in by_week[week]]
        test_rows = by_week[test_week]
        folds.append(Fold(
            label=f"walk_forward_{_format_week(ordered_weeks[k - 1])}_to_{_format_week(test_week)}",
            train_rows=train_rows, test_rows=test_rows, split_strategy=SPLIT_WALK_FORWARD,
        ))
    return folds


def _format_week(week_key: tuple[int, int]) -> str:
    year, week = week_key
    return f"{year}-W{week:02d}"


def _match_features(row: TrainingRow) -> MatchFeatureRow:
    """The point-in-time feature view of a TrainingRow, with the label
    stripped away -- exactly what a model's predict_win_prob may see.
    Constructing this from TrainingRow's own already-assembled red_teams/
    blue_teams (Milestone 1's output) rather than re-querying anything.
    """
    return MatchFeatureRow(
        match_key=row.match_key, as_of=row.scheduled_time, event_key=row.event_key, season=row.season,
        red_teams=row.red_teams, blue_teams=row.blue_teams,
    )


def _common_season(rows: Sequence[TrainingRow]) -> int | None:
    """The one season every row shares, or None if rows is empty or spans more than one season."""
    seasons = {row.season for row in rows}
    return next(iter(seasons)) if len(seasons) == 1 else None


class FoldMetrics(BaseModel):
    """One fold's (or the aggregate's) metric suite. Every metric is
    Optional and independently None exactly when ml.backtest.metrics itself
    reports that statistic as undefined for that fold's data -- never
    silently coerced to a fabricated 0.0.
    """

    fold_label: str
    season: int | None
    row_count: int
    excluded_count: int
    accuracy: float | None = None
    log_loss: float | None = None
    brier_score: float | None = None
    roc_auc: float | None = None
    calibration_error: float | None = None
    spearman: float | None = None
    top_k_recall: float | None = None


class BacktestResult(BaseModel):
    """The structured result of one run_win_prob_backtest or
    run_ranking_backtest call: one FoldMetrics per fold, plus one pooled
    aggregate across every fold's evaluated rows -- "report per-season and
    aggregate", per the milestone's own text.
    """

    mode: str
    split_strategy: str
    folds: list[FoldMetrics]
    aggregate: FoldMetrics

    def summary(self) -> str:
        """A plain-text report. No LLM call anywhere in its construction --
        this is pure string formatting over already-computed numbers, per
        this milestone's own "No LLM calls" instruction and CLAUDE.md's
        standing "core engine = no LLM API calls" constraint.
        """
        lines = [f"Backtest: {self.mode} ({self.split_strategy})"]
        fields = _WIN_PROB_SUMMARY_FIELDS if self.mode == MODE_WIN_PROB else _RANKING_SUMMARY_FIELDS
        for fold in self.folds:
            lines.append(f"  {fold.fold_label}: {_format_fold_metrics(fold, fields)}")
        lines.append(f"  aggregate: {_format_fold_metrics(self.aggregate, fields)}")
        return "\n".join(lines)


def _format_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


# Which FoldMetrics fields summary() prints, per mode -- a ranking result
# never sets accuracy/log_loss/brier_score/roc_auc/calibration_error (they
# are win-prob-only concepts), and a win-prob result never sets spearman/
# top_k_recall, so printing the other mode's fields would only ever show a
# wall of "n/a" that means "not applicable to this mode", not "undefined for
# this fold's data" -- two different things this summary keeps distinct by
# simply not printing the inapplicable ones at all.
_WIN_PROB_SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("accuracy", "accuracy"), ("log_loss", "log_loss"), ("brier_score", "brier"),
    ("roc_auc", "roc_auc"), ("calibration_error", "ece"),
)
_RANKING_SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("spearman", "spearman"), ("top_k_recall", "top_k_recall"),
)


def _format_fold_metrics(fold: FoldMetrics, fields: tuple[tuple[str, str], ...]) -> str:
    parts = [f"n={fold.row_count}"]
    if fold.excluded_count:
        parts.append(f"excluded={fold.excluded_count}")
    for attr_name, display_name in fields:
        parts.append(f"{display_name}={_format_metric(getattr(fold, attr_name))}")
    return ", ".join(parts)


def _require_consistent_split_strategy(folds: Sequence[Fold]) -> str:
    if not folds:
        raise ValueError("at least one fold is required -- an empty fold list evaluates nothing")
    strategies = {fold.split_strategy for fold in folds}
    if len(strategies) > 1:
        raise ValueError(
            f"folds mix split strategies {sorted(strategies)!r} -- a single backtest run must use one "
            "strategy consistently, not a combination of hold-out-season and walk-forward folds"
        )
    return next(iter(strategies))


def run_win_prob_backtest(model_factory: Callable[[], Model], folds: Sequence[Fold]) -> BacktestResult:
    """Fit a fresh model per fold on its train_rows, evaluate predict_win_prob
    on its test_rows, and report accuracy/log-loss/Brier/ROC-AUC/ECE per fold
    plus a pooled aggregate.

    Tie-labeled rows are excluded from evaluation, counted, and reported
    (FoldMetrics.excluded_count) rather than silently dropped or forced into
    a binary label: "P(red beats blue)" has no natural target value for a
    match that was a genuine tie, and coercing one would corrupt the exact
    metrics this milestone exists to make trustworthy.

    model_factory is called once per fold (not once total) so each fold's
    model is trained only on that fold's own train_rows -- reusing one
    already-fit model instance across folds would let a later fold's
    evaluation be influenced by an earlier fold's future data, precisely the
    leakage this milestone's split-integrity guarantee exists to prevent.

    Raises ValueError if folds is empty (nothing to evaluate) or mixes more
    than one split_strategy (a single backtest run reporting one
    BacktestResult.split_strategy must have gotten every fold from the same
    kind of split -- see Fold's own docstring for why this is derived rather
    than caller-supplied).
    """
    split_strategy = _require_consistent_split_strategy(folds)
    fold_metrics: list[FoldMetrics] = []
    all_predictions: list[float] = []
    all_labels: list[bool] = []
    total_excluded = 0

    for fold in folds:
        model = model_factory()
        model.fit(fold.train_rows)

        predictions: list[float] = []
        labels: list[bool] = []
        excluded = 0
        for row in fold.test_rows:
            if row.label == LABEL_TIE:
                excluded += 1
                continue
            predictions.append(model.predict_win_prob(_match_features(row)))
            labels.append(row.label == LABEL_RED_WIN)

        fold_metrics.append(FoldMetrics(
            fold_label=fold.label, season=_common_season(fold.test_rows),
            row_count=len(predictions), excluded_count=excluded,
            accuracy=accuracy(predictions, labels), log_loss=log_loss(predictions, labels),
            brier_score=brier_score(predictions, labels), roc_auc=roc_auc(predictions, labels),
            calibration_error=expected_calibration_error(predictions, labels),
        ))
        all_predictions.extend(predictions)
        all_labels.extend(labels)
        total_excluded += excluded

    aggregate = FoldMetrics(
        fold_label="aggregate", season=None, row_count=len(all_predictions), excluded_count=total_excluded,
        accuracy=accuracy(all_predictions, all_labels), log_loss=log_loss(all_predictions, all_labels),
        brier_score=brier_score(all_predictions, all_labels), roc_auc=roc_auc(all_predictions, all_labels),
        calibration_error=expected_calibration_error(all_predictions, all_labels),
    )
    return BacktestResult(mode=MODE_WIN_PROB, split_strategy=split_strategy, folds=fold_metrics, aggregate=aggregate)


def _team_features_by_event(rows: Sequence[TrainingRow]) -> dict[str, dict[int, TeamFeatures]]:
    """Group a fold's test rows into event_key -> {team_number: latest-seen TeamFeatures}.

    A team typically appears in several of an event's matches; its most
    recent (by scheduled_time) TeamFeatures snapshot within these rows is the
    representative rating input -- the state of knowledge closest to the
    event's actual conclusion, without looking past it (every row here
    already comes from a Fold's test_rows, so nothing beyond this fold's own
    temporal boundary is visible).
    """
    latest: dict[str, dict[int, tuple[datetime, TeamFeatures]]] = {}
    for row in rows:
        for team_features in (*row.red_teams, *row.blue_teams):
            event_teams = latest.setdefault(row.event_key, {})
            existing = event_teams.get(team_features.team_number)
            if existing is None or row.scheduled_time > existing[0]:
                event_teams[team_features.team_number] = (row.scheduled_time, team_features)
    return {
        event_key: {team_number: features for team_number, (_, features) in teams.items()}
        for event_key, teams in latest.items()
    }


def run_ranking_backtest(
    model_factory: Callable[[], Model], folds: Sequence[Fold], final_ranks: Mapping[str, Mapping[int, int]],
    *, top_k: int = 8,
) -> BacktestResult:
    """Fit a fresh model per fold, predict_rating for every team seen in that
    fold's test events, and compare the predicted ordering against
    final_ranks's real ranking, per event (rank is only meaningful within one
    event's own field), then average per-event Spearman/top-k-recall into a
    per-fold ("per-season", when a fold's test rows are one season) figure.

    final_ranks maps event_key -> {team_number: rank} (rank 1 = the actual
    winner of the ranking, ascending). See this module's own docstring for
    why this must be supplied externally rather than derived: no data source
    in this codebase has ever landed a team's real final event rank.

    An event in the fold with no entry in final_ranks is skipped for that
    event (there is nothing to score it against) and does not silently
    count as a zero -- it is absent from both the numerator and denominator
    of the per-fold average, exactly the same "excluded, not fabricated"
    discipline run_win_prob_backtest applies to ties.

    Raises ValueError if folds is empty or mixes split strategies -- see
    run_win_prob_backtest's identical guarantee via
    _require_consistent_split_strategy.
    """
    split_strategy = _require_consistent_split_strategy(folds)
    fold_metrics: list[FoldMetrics] = []
    all_spearman: list[float] = []
    all_recall: list[float] = []
    total_row_count = 0
    total_excluded = 0

    for fold in folds:
        model = model_factory()
        model.fit(fold.train_rows)

        teams_by_event = _team_features_by_event(fold.test_rows)
        fold_spearman: list[float] = []
        fold_recall: list[float] = []
        scored_events = 0
        skipped_events = 0

        for event_key, team_features_by_number in teams_by_event.items():
            actual_ranks = final_ranks.get(event_key)
            if not actual_ranks:
                skipped_events += 1
                continue

            team_numbers = [t for t in team_features_by_number if t in actual_ranks]
            if len(team_numbers) < 2:
                skipped_events += 1
                continue

            predicted_ratings = {t: model.predict_rating(team_features_by_number[t]) for t in team_numbers}
            predicted_order = sorted(team_numbers, key=lambda t: predicted_ratings[t], reverse=True)
            actual_order = sorted(team_numbers, key=lambda t: actual_ranks[t])

            spearman = spearman_correlation(
                [predicted_ratings[t] for t in team_numbers],
                [-actual_ranks[t] for t in team_numbers],
            )
            if spearman is not None:
                fold_spearman.append(spearman)
            recall = top_k_recall(predicted_order, actual_order, k=top_k)
            if recall is not None:
                fold_recall.append(recall)
            scored_events += 1

        fold_metrics.append(FoldMetrics(
            fold_label=fold.label, season=_common_season(fold.test_rows),
            row_count=scored_events, excluded_count=skipped_events,
            spearman=(sum(fold_spearman) / len(fold_spearman)) if fold_spearman else None,
            top_k_recall=(sum(fold_recall) / len(fold_recall)) if fold_recall else None,
        ))
        all_spearman.extend(fold_spearman)
        all_recall.extend(fold_recall)
        total_row_count += scored_events
        total_excluded += skipped_events

    aggregate = FoldMetrics(
        fold_label="aggregate", season=None, row_count=total_row_count, excluded_count=total_excluded,
        spearman=(sum(all_spearman) / len(all_spearman)) if all_spearman else None,
        top_k_recall=(sum(all_recall) / len(all_recall)) if all_recall else None,
    )
    return BacktestResult(mode=MODE_RANKING, split_strategy=split_strategy, folds=fold_metrics, aggregate=aggregate)
