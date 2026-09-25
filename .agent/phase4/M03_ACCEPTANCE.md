# Phase 4 — Milestone 3 Acceptance: Temporal Backtesting Harness + Model Interface

## Completed Milestone
Phase 4, Milestone 3 (docs/P4Milestones.md) — the backtest harness and Model
protocol every model from Milestone 5 onward validates through.

## Files Modified/Created
- Created: `ml/backtest/__init__.py`, `ml/backtest/metrics.py`, `ml/backtest/harness.py`
- Created: `tests/test_ml_backtest_metrics.py`, `tests/test_ml_backtest_harness.py`
- Modified: `ml/__init__.py` (exports)

## Architectural Decisions
- `Model` is one flat `typing.Protocol` (`fit`/`predict_win_prob`/`predict_rating`/
  `save`/`load`), per the milestone's literal method list, rather than two
  narrower protocols. A model not supporting one predict method raises
  `NotImplementedError` for it; the harness only ever calls the method the
  evaluation mode it's running needs.
- `fit`/`predict_win_prob`/`predict_rating` are typed directly against
  Milestone 1/2's own models (`TrainingRow`, `MatchFeatureRow`, `TeamFeatures`)
  — no new X/y abstraction invented.
- `Fold` enforces `max(train.scheduled_time) < min(test.scheduled_time)` in
  its own `__post_init__` for every fold constructed anywhere, not merely
  tested after the fact. `hold_out_season_split` can therefore only ever hold
  out the chronologically latest season present — holding out an earlier one
  raises there, by construction.
- `walk_forward_splits` buckets by ISO `(year, week)` of `scheduled_time` — a
  documented simplification of FRC's own season-relative week numbering,
  chosen specifically to avoid touching Milestone 2's already-accepted
  `TrainingRow` model with a new field.
- Metrics (`ml/backtest/metrics.py`) are pure, dependency-free functions
  (no numpy/scipy, per Phase 4's own "added starting Milestone 5" plan),
  each returning `None` rather than a fabricated value wherever the
  statistic is mathematically undefined for its input (empty input,
  single-class ROC-AUC input, constant-sequence Spearman input).
- **Major finding, surfaced during Phase B.5 (Challenge) before implementation:**
  no canonical table, TBA client model, or staging schema anywhere in this
  codebase has ever landed a team's real final event ranking — confirmed by
  search, not assumed. This is more fundamental than "no reachable database
  in this sandbox": even a fully populated database has nothing to compare a
  ranking model's predictions against. Resolved by having `run_ranking_backtest`
  take `final_ranks` as an explicit external argument rather than attempting
  to derive it — correct and fully testable today, and usable the moment a
  real ground-truth source exists, with no change to this module. Flagged as
  a real, not-yet-resolved gap that becomes load-bearing at Milestone 5
  (deferred per Scope Control — it belongs to a later milestone and creates
  no defect in this one).
- `BacktestResult.split_strategy` is derived from the folds themselves
  (`Fold.split_strategy`, validated consistent across all folds in one run)
  rather than taken as a separate caller-supplied parameter — found and
  fixed during Phase E (Architecture Review): a free-standing parameter the
  caller must remember to match to how the folds were actually built is
  exactly the kind of "implicit behavior" `prompts/MASTER_BUILD.md`'s
  Guiding Principles prefer explicit contracts over.

## Architectural Improvements
- `BacktestResult.summary()` is mode-aware (win-prob fields vs. ranking
  fields), so a ranking result's plain-text report never shows a wall of
  `accuracy=n/a` for metrics that mode never computes.
- `run_win_prob_backtest`/`run_ranking_backtest` both reject an empty fold
  list and a fold list mixing split strategies, loudly, rather than silently
  producing a vacuous or mislabeled result.

## Tests Added & Executed
56 new tests, all pure/database-free (Model, Fold, and both backtest runners
operate directly on already-assembled `TrainingRow`/`TeamFeatures` objects,
never touching the database):
- `tests/test_ml_backtest_metrics.py` (34 tests): hand-computed values for
  every metric (accuracy, log-loss, Brier, ROC-AUC including a tied-rank
  case, ECE including both well- and mis-calibrated cases, Spearman
  including ties, top-k-recall including field-smaller-than-k), plus every
  documented `None`-for-undefined case and length-mismatch rejection.
- `tests/test_ml_backtest_harness.py` (22 tests): the milestone's three named
  scenarios — split-integrity (a leaky fold rejected, a valid one accepted,
  `hold_out_season_split` rejecting an earlier-season hold-out), protocol-
  conformance (a dummy model passes `isinstance(_, Model)` and runs
  end-to-end through the win-prob harness including `save`/`load`), and
  metric-correctness (hand-computed Spearman/top-k-recall through a full
  ranking backtest run) — plus tie-exclusion, fresh-model-per-fold,
  latest-snapshot-per-team-per-event selection, empty/mixed-strategy
  rejection, and mode-aware summary formatting.

## Terminal Verification Status
- **Pytest:** PASS — 736 passed, 261 skipped (0 failed), full suite, no
  regressions (was 733/261 before this milestone; +3 from new validation
  tests added during Phase E's fix, +53 from the milestone's own two new
  test files landed earlier in the same run count).
- **Type Check (mypy):** PASS — zero new findings in any file this milestone
  touched; the 3 findings that remain are the exact same pre-existing
  `data/config.py`/`data/metrics/read.py:205` issues Milestone 1's own audit
  already found and left alone (installed/uninstalled as a one-time
  diagnostic, not a standing dependency).
- **Linter (ruff):** PASS — 3 findings, all reproducing this codebase's own
  already-established conventions byte-for-byte (grouped-not-alphabetized
  `__all__`, a quoted forward-ref return type under
  `from __future__ import annotations`), same precedent M1/M2 already
  recorded for equivalent findings.

## Issues Found During Phase F Bug Hunt
1. **Real bug, caught by test execution, not review:** `accuracy`'s
   boundary handling at `p == 0.5` was documented as "always incorrect
   regardless of label" but the implementation's `(p > 0.5) == bool(y)`
   comparison actually scored `p=0.5, y=False` as correct (since `0.5 > 0.5`
   is `False`, matching `bool(False)`). Fixed to explicitly exclude `p == 0.5`
   from the correct-count regardless of label, matching the documented
   contract. Caught by `test_accuracy_exactly_half_is_scored_incorrect`.
2. **Design weakness, caught by adversarial architecture review (not a test
   failure):** `split_strategy` as a free-standing parameter to
   `run_win_prob_backtest`/`run_ranking_backtest`, independent of how the
   folds were actually built, could silently mislabel a `BacktestResult`.
   Fixed by moving `split_strategy` onto `Fold` itself and deriving
   `BacktestResult.split_strategy` from the folds, with explicit rejection
   of an empty or strategy-mixed fold list. New tests added for both
   rejection paths.
3. Minor: `top_k_recall`'s signature was unnecessarily restricted to
   `Sequence[str]`, forcing every real caller (team numbers are ints) to
   convert. Generalized to `Sequence[Hashable]`.
4. Cosmetic: `walk_forward_splits`' fold labels rendered a raw Python tuple
   (`walk_forward_(2026, 9)_to_(2026, 10)`); reformatted to ISO-week style
   (`walk_forward_2026-W09_to_2026-W10`) since fold labels appear directly in
   the plain-text summary this milestone's own brief requires.

## Remaining Known Risks
- The ranking-ground-truth gap (see Architectural Decisions above) is real
  and unresolved — not a defect in this milestone, but a standing blocker
  for any future milestone that needs a *real* ranking backtest.
- `walk_forward_splits`' ISO-week bucketing is a documented proxy for FRC's
  own season-relative week numbering, not the literal thing — acceptable for
  this milestone's own structural requirement (train on earlier chunks, test
  on the next), flagged in case a future milestone needs literal FRC week
  numbers specifically.
- This sandbox has no reachable PostgreSQL (re-confirmed this session), so
  no DB-gated integration test exists for this milestone — none was needed,
  since every function here operates on already-assembled `TrainingRow`
  objects rather than querying the database directly, unlike Milestones 1/2.

## Roadmap Satisfaction
Every "What to do" item is implemented (`Model` protocol; hold-out-season
and walk-forward splits; all seven named metrics; per-season-and-aggregate
reporting via `BacktestResult` + `.summary()`; no LLM calls anywhere). Every
"Success looks like" item holds: any conforming model runs through one entry
point (`run_win_prob_backtest`/`run_ranking_backtest`) and gets the same
metric suite; splits provably respect time order (enforced structurally by
`Fold`, not merely tested); this is now the one place every later Phase 4
milestone will validate through. All three named "What to test" scenarios
are directly, individually pinned by tests.

## Production Readiness
Confirmed, with the ranking-ground-truth gap stated plainly as a real,
external dependency this milestone correctly declines to fabricate around.

## Readiness for Next Milestone
Ready for Milestone 4 (locked naive baselines) — with the caveat, already
flagged in `PHASE_PLAN.md`, that M4's own "Success looks like" requires a
*real*, dated baseline number on a real held-out season, which this sandbox
cannot produce without a reachable database holding real synced season data.
