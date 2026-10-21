# PX-2b (versioned PX-2 on PX-1b): frozen specification, version 1 (2026-10-08)

**Frozen by the commit that introduces this file, before any PX-2b input or outcome exists.** No 2027 data exists, and PX-1b is not accepted. A change is a new version, written before the run it governs.

**Authority:**
- D9 decision v1 (`decisions/P6_D9_PX1B_REPLACEMENT_V1.md`), proposal C1;
- approved by Kanav on 2026-10-08 (`decisions/P6_D9_PX1B_APPROVALS_C0_C4_2026-10-08.md`).

**What it replaces, and what it leaves alone:**
- It versions P6-M3 / P6-Q4 for PX-1b.
- The frozen PX-2 (`P6_M2_PX1_SPEC.md` §5, P6-Q4) is unchanged, stays bound to PX-1, and stays blocked.

## 1. Prerequisites (all required; the harness refuses otherwise)

1. **PX-1b is accepted**, both of:
   - `results/p6_px1b_gate_2027.json` exists with `passed: true` (PX-1b spec §6, FINAL-1);
   - Kanav's dated confirmation of that record, `decisions/p6_px1b_final1_confirmation.json`, with:
     - `confirmed: true`, `confirmed_by`, `date`;
     - `record: "p6_px1b_gate_2027.json"`;
     - `record_sha256` equal to the sha256 of that record file.
2. **The P6-M1 records exist** for the seasons used: `p6_m1_ruleset_check.json` (2024–2026) and `p6_m1_ruleset_check_2027.json` (C0).
3. **Approved rulesets exist** for 2026 and 2027.

## 2. Model, rows and slice

- **Model:** the registered, frozen `playoff_px1b` `px1b-v1` (fit 2024–2026; `p6_px1b_final_fit.json`), unchanged.
- **Rows:** PX-1b spec §1 rows of **2026** (calibration) and **2027** (evaluation). That includes, each counted:
  - `playoff_before_selection_moment`;
  - `scale_absent`;
  - the four-member, EPA-incomplete and P6-M1 exclusions.
- **Calibration slice:** the **temporally last 20%** of eligible 2026 rows, sorted by (`scheduled_time`, `match_key`): rows `[int(0.8 · n):]`.
  - This is P6-Q4's rule, moved from 2025 to 2026.
  - As in M7 and the original P6-Q4 note, the slice lies inside the model's training period.
- **Calibrator:** `SymmetricIsotonicCalibrator`, fit on PX-1b's raw outputs on the slice, from both perspectives (as in M7).

## 3. Gate (the P6-Q4 / M7 / D16 constants, unchanged)

`evaluate_calibration_gate` on the calibrated PX-1b probabilities of the held-out **2027** rows:

| | Requirement |
|---|---|
| **G1** | ECE < 0.05 |
| **G2** | 10 fixed bins; on bins with ≥ 30 predictions, an exact Poisson-binomial test; Holm at α = 0.05 |
| **G3** | symmetry \|q(r) + q(swap r) − 1\| ≤ 1e-12, and order independence |
| **G4** | fit isolation: every slice row precedes every 2027 row (max slice `scheduled_time` < min 2027 `scheduled_time`) |

**Pass** iff G1–G4 all pass.

## 4. Outcome, records and limits

- **Pass:** PX-1b + PX-2b probabilities may be served as `validated_playoff`.
- **Fail:** `not_validated` (`px2b_gate_failed`), and D9 applies.
- **Records:**
  - `results/p6_px2b.json`, write-once: commit, this spec's blob, row and exclusion counts, slice size, gate result, runtime;
  - the calibrator, saved beside the PX-1 artifacts as `px2b_calibrator.json`.
- **Runtime:** one run, within the 45-minute budget.
- **Not changed after a result.**
