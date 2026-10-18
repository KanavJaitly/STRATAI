# P6-M13 run 1 — FAILED (kept); two objectively demonstrated defects (D9)

2026-10-05. This file is a failure record, not an acceptance record.

**Run 1:** `.agent/phase6/results/p6_m13_parity_audit.json`, write-once, kept unchanged. It ran under the plan `.agent/phase6/decisions/P6_M13_AUDIT_PLAN.md`, at commit `69ce11f`. **Result: P6-DM2 not met.**

## What failed

| Check | Result | Cause |
|---|---|---|
| Real engine, M3 order invariance | **FAIL** on `2026mimar_qm51`: 0.7203455595554858 vs 0.7203455595554857 when the teams are reordered | **Implementation defect (model).** `alliance_means` summed capabilities with plain floating-point addition in the order the teams arrive, so reordering the teams changed the last bit. The frozen model specification (§2) defines the alliance mean as a sum over the alliance's teams, which is order-free. The code did not honour that |
| Planted `different_missing_data_handling` | **not caught by its target check** (M6) | **Harness defect (planted fixture).** The planted engine imputed only a missing EPA scale. The real missing-input context (`2026mndu2_qm1`) lacks the causal *score* scale, so the planted imputation never triggered. It was flagged only by S3 and by the M3 defect above |

Every other check passed on the real engine, including M1 bit-identity on 20 cases, M2 exhaustive maximum, M4, M5, M6 and M7. Every other planted defect was caught by its target check.

## Not a parity breach

The M3 difference is symmetric floating-point rounding. It depends on team order, not on where a strategy came from, and it applies identically to both paths (M1 passed bit for bit). It is still a defect against the frozen specification and against the audit's invariance requirement.

## Fixes (objectively demonstrated defects only; no check, threshold, sample or methodology changed)

1. `ml/strategy/outcome.alliance_means` sums each component with `math.fsum`, which is correctly rounded and therefore independent of order. This is the specification's order-free sum. The model's parameters, inputs and formula are unchanged. Probabilities change by at most a few units in the last place.
   - The recorded P6-M10 evaluation was computed before this fix. At that magnitude its gate result cannot change, and its record is kept as is.
2. The planted missing-data defect now imputes **every** absent model input: EPA components, the EPA scale and the score scale. That is the defect it is meant to represent.

## Rerun

Run 1 is kept, and **one** labelled rerun is made: `p6_m13_parity_audit_rerun1.json`, with `supersedes`.
- **Same plan, contexts, seed and checks**, at the commit containing these fixes and their regression tests.
- **Regression tests:**
  - order invariance of `alliance_means` with ULP-sensitive values;
  - the planted missing-data defect caught when only the score scale is absent.
