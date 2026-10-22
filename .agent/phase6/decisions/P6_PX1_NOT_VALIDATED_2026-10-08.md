# PX-1 (P6-M2): accepted as `not_validated`, Kanav, 2026-10-08

**Decision (Kanav).** The PX-1 result stands as recorded: PX-1 is `not_validated` under the current frozen specification.
- No forced acceptance, no rerun to seek another outcome, and no change to thresholds, metrics, CI procedure, populations or criteria.
- Phase 6 and the P6-M14 sign-off stay **incomplete**.

**Preserved, unchanged:**
- `.agent/phase6/results/p6_m2_px1.json` (write-once, at `7574d50`);
- `.agent/phase6/P6_M2_PX1_FAILURE.md` (`effb290`).

## Verification that the record matches the frozen P6-Q3 gate (read-only; nothing rerun)

| Frozen requirement (`P6_M2_PX1_SPEC.md` §4, blob `24b427f2…`, identical to the recorded `spec_blob`) | Record | Holds |
|---|---|---|
| PX-1 (uncalibrated) vs M6/M7 `win_prob_xgb_calibrated` `d18` and vs the seed-only logistic, on the same rows | both comparisons: 2,632 held-out 2026 rows, 194 events, 0 `insufficient_data` | yes |
| A paired event-bootstrap 95% CI of the per-match log-loss difference (PX-1 − baseline); 2,000 resamples; seed 20261010 | `paired_log_loss_gate` → `event_bootstrap_mean_ci` (DEFAULT_RESAMPLES 2000, level 0.95); recorded resamples 2000, seed 20261010 | yes |
| Pass iff the CI lies entirely below 0, for **each** comparison | `passed = ci_high < 0`. vs M6/M7: mean +0.0820 = 0.6419 − 0.5599, CI [+0.0234, +0.1481]. vs seed-only: +0.1234 = 0.6419 − 0.5185, CI [+0.0634, +0.1891] | yes: **both FAIL** |

**No concrete implementation or evaluation defect was found.** The failure is the frozen gate's outcome. No defect is assumed because the model failed.

## Status under the frozen specification

| Item | Status |
|---|---|
| P6-M1 | recorded; rulesets approved (ids 4–6), 0 reproduction failures, no escalation |
| P6-M2 PX-1 | **FAILED P6-Q3, accepted as `not_validated`** |
| P6-M3 PX-2, P6-M5 PX-4 | **not run**: stopped by D9 while PX-1 is failed |
| P6-M6 (b) | measured (non-gating); run 1 kept, rerun1 with the frozen per-slot / CI / baseline outputs |
| P6-M8 / P6-DM1 | **not run**: needs PX-4. The pre-run record (`36b52c7`) and the leakage sentinel are retained. **Mr. Biery's agreement and review remain outstanding** |
| P6-M10 | FAILED its gate (2026-10-05), separately; unchanged |
| P6-DM1 | **NOT MET** |
| P6-DM2 | MET (`p6_m13_parity_audit_rerun1.json`) |
| Phase 6 / P6-M14 sign-off | **incomplete** |

## The 2026 holdout

The 2026 holdout has been examined for PX-1, and earlier for P6-M10. Any redesign chosen or tuned with knowledge of these results **cannot be validated on 2026**, and must not be presented as validated on it.

A future redesign is a **separate, separately pre-registered effort**, outside this frozen Phase 6 run. It would need:
1. a new frozen specification written before any fit;
2. explicit development-data boundaries;
3. a leakage policy;
4. a genuinely independent validation population not yet observed, for example the 2027 season, collected after the specification is frozen.

No new acceptance gate is defined here. The current P6-Q3 gate remains unsatisfied.
