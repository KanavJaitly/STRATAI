# Phase 4 — Milestone 8 Acceptance: Bias, Symmetry & Leakage Audit

## Completed Milestone

Milestone 8 of `docs/P4Milestones.md`'s 13-milestone plan: `scripts/ml_bias_audit.py`,
one command running symmetry, order-invariance, no-strategy-leakage, as-of-feature
integrity, and label-shuffle leakage checks across the real Milestone 5/6 models.

**Accepted in full.** Unlike M4/M5/M6/M7, this milestone's own "Success looks like"
and "What to test" criteria require no real Statbotics/EPA data and no real held-out
season at all — every check operates on the real model classes' structural behavior
and synthetic data with a known ground truth. Nothing here is blocked by the ongoing
Statbotics outage recorded in `PHASE_STATUS.md`.

## Files Modified/Created

- `scripts/ml_bias_audit.py` (new) — `AuditCheck`, `AuditReport`, seven check
  functions, `run_full_audit`, CLI `main`.
- `tests/test_scripts_ml_bias_audit.py` (new) — 16 tests.

## Architectural Decisions

1. **Every check operates on the real `ml.models.ranking_xgb.RankingXGBModel` /
   `ml.models.win_prob.WinProbXGBModel` classes by default** (`run_full_audit`'s own
   default arguments), not stand-ins — a caller invoking `python -m scripts.ml_bias_audit`
   with no arguments audits the actual models this codebase ships, not a hypothetical.
2. **Symmetry and label-shuffle checks reuse the identical synthetic-data techniques
   already proven in `tests/test_ml_models_ranking_xgb.py` /
   `test_ml_models_win_prob.py`** (a "true skill" signal a model should recover, and a
   fixed-seed random permutation — not a naive reversal — to decouple team features
   from outcome), rather than inventing a second data-generation scheme. Consistency
   with already-validated fixtures was chosen over novelty.
3. **`check_no_strategy_leakage` and `check_as_of_feature_integrity` need no fitted
   model at all** — they assert directly against the live `TeamFeatures`/
   `MatchFeatureRow` pydantic schemas (a substring scan for disallowed field names;
   a direct attempt to construct a naive `as_of`). This makes both checks incapable of
   silently passing due to a model that happens not to exercise the vulnerable path —
   the guarantee is checked at the schema level, where it structurally must hold for
   every model, not empirically for one.
4. **The deliberately-broken fixtures are named for exactly what they violate, not
   generic "bad models"**: `_ConstantAsymmetricWinProbModel` (constant 0.9 output,
   fails `symmetry` and `label_shuffle_leakage_win_prob`) and `_ConstantRatingModel`
   (constant rating, fails `label_shuffle_leakage_ranking`) — each proves a specific
   named check has teeth, not just "the audit can fail somehow."
5. **`AuditReport.passed` is a strict `all()` over every check** — a partial pass
   (6 of 7 checks green) is reported as an overall FAIL, both in the CLI's exit code
   and in `report.passed`, so a caller cannot accidentally treat a partially-broken
   model as shippable by only checking a subset of the summary output.

## Tests Added & Executed

`tests/test_scripts_ml_bias_audit.py` — 16 tests:
- 2 protocol-conformance sanity checks (`RankingXGBModel`/`WinProbXGBModel` both
  satisfy `ml.backtest.harness.Model`).
- 7 tests confirming every individual check function passes against the real models.
- 1 test confirming `run_full_audit()`'s default call passes with exactly 7 checks.
- 5 tests confirming specific checks correctly FAIL against the two deliberately-broken
  fixtures (the milestone's own named "proves the audit has teeth" requirement),
  including `run_full_audit` itself reporting `passed=False` and naming the failed
  check when given a broken model factory.
- 1 test confirming the summary text mentions every check by name.

## Terminal Verification Status

```
python -m pytest tests/test_scripts_ml_bias_audit.py -v
16 passed in 6.34s
```

Direct CLI run against the real models:

```
python -m scripts.ml_bias_audit
Phase 4 Milestone 8 bias/leakage audit -- PASS
[PASS] symmetry: max |p(R,B) - (1-p(B,R))| across 25 random alliance pairs = 0.00e+00 (tolerance 1e-09)
[PASS] order_invariance_win_prob: ...
[PASS] order_invariance_rating: ...
[PASS] no_strategy_leakage: no disallowed field names found
[PASS] as_of_feature_integrity: MatchFeatureRow correctly refused a naive as_of
[PASS] label_shuffle_leakage_ranking: true-label correlation=0.798 (floor 0.6), shuffled-label correlation=0.167, collapse=0.631 (required >= 0.3)
[PASS] label_shuffle_leakage_win_prob: true-label |p-0.5|=0.499 (floor 0.15), shuffled-label |p-0.5|=0.033
```

Full repository suite, isolated (no concurrent background job):

```
python -m pytest -q
1141 passed, 2 warnings in 375.98s
```

Zero regressions against the 1125-passed baseline immediately prior (1141 = 1125 + 16 new).

## Issues Found During Implementation

None requiring a fix — the first working draft of every check passed against the real
models and correctly failed against both deliberately-broken fixtures on first run,
with one exception caught and fixed before any test was written: an early draft of
`_synthetic_win_prob_rows` attempted to reconstruct identical per-match feature values
across two separate passes (one to compute outcomes, one to build rows) by replaying a
fresh `random.Random` instance's call sequence up to the same point — needlessly
convoluted (O(n²) RNG calls) and fragile to read. Refactored to build each match's
alliance features exactly once and reuse them in both passes, before it was ever run
against real data.

## Remaining Known Risks

None new. This milestone does not touch, and is not affected by, the ongoing
Statbotics outage recorded in `PHASE_STATUS.md`. Its own coverage is intentionally
narrow — the five guarantee classes the milestone names by name — not a general
model-quality audit; M11's cross-season guard and M13's documentation contract tests
cover separate concerns this audit does not attempt.

## Roadmap Satisfaction

- "A single command demonstrates the unbiasedness guarantees instead of scattered
  ad-hoc checks" — `python -m scripts.ml_bias_audit`, one command, seven checks. ✅
- "Every future model must pass this audit before shipping" — `run_full_audit` accepts
  any `Model`-conformant factory via its own parameters, so a future M9+ model can be
  audited by the same script without modification. ✅
- "The audit is the deliverable; add a regression test that fails loudly if any
  guarantee breaks" — 16 tests, including direct assertions on `AuditCheck.passed`
  rather than only the human-readable summary text. ✅
- "Deliberately-leaky model fixture is caught by the audit (proves the audit has
  teeth)" — `_ConstantAsymmetricWinProbModel` / `_ConstantRatingModel`, each shown to
  fail the specific check it violates, plus `run_full_audit` itself reporting an
  overall FAIL. ✅

## Production Readiness

Ready to gate future models. `run_full_audit`'s `ranking_model_factory`/
`win_prob_model_factory` parameters mean a future M9+ model can be checked by passing
its constructor, with no change to this script required. The two schema-level checks
(`no_strategy_leakage`, `as_of_feature_integrity`) will also automatically re-verify
themselves against any future field added to `TeamFeatures`/`MatchFeatureRow`.

## Readiness for Next Milestone

M8 is fully accepted and unblocks nothing further — the phase's real blocker remains
Statbotics (M4/M5/M6/M7's real, dated numbers). Continuing dependency-independent
progress into M9 (alliance synergy scoring) next.
