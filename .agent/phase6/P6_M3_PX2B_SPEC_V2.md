# PX-2b specification, version 2: PROPOSED (not adopted; does not govern anything until Kanav approves this exact blob)

**Proposed 2026-10-08,** after the C1 audit (`decisions/P6_PX2B_C1_AUDIT_2026-10-08.md`) found that v1 calibrates on in-sample predictions.
- **On approval:** this version supersedes `P6_M3_PX2B_SPEC.md` (v1, blob `1833a213…`, `021e6ea`) for PX-2b.
- **v1 is kept unchanged as the record.**
- **Timing:** this text must be approved, and the calibration-base model fit (§2.2), **before any 2027 evaluation input or outcome exists**. Today none exists.

**What exists while this is written:**
- all 2024–2026 rows and outcomes (observed);
- `px1b-v1` (trained on 2024–2026, including the slice).

**What does not exist:** any 2027 data, PX-1b acceptance, any PX-2b calibrator or calibration-base model.

**Changed from v1:** only §2.2, where the predictions the calibrator is fit on come from. Everything else is v1's, verbatim in substance.

## 1. Prerequisites (unchanged from v1 §1)

1. PX-1b is accepted: `p6_px1b_gate_2027.json` passed, plus Kanav's sha-matched confirmation.
2. The 2024–2026 and 2027 P6-M1 records exist.
3. Approved 2026 and 2027 rulesets exist.
4. **New, structural, checked by the run:** the calibration-base model of §2.2 exists, registered write-once, and its recorded fit set satisfies §2.2's isolation conditions.

## 2. Model, rows, slice and calibrator

**2.1 Unchanged from v1:**
- the evaluated model is the frozen `playoff_px1b` `px1b-v1`;
- the rows are PX-1b spec §1 rows (with its counted exclusions) of 2026 and 2027;
- the **calibration slice** is the temporally last 20% of eligible 2026 rows, sorted by (`scheduled_time`, `match_key`), rows `[int(0.8 · n):]`. Today that is 526 rows from 40 events, `2026mibig_sf8m1` … `2026iscmp_f1m2` (`diagnostics/px2b_c1_slice_provenance.json`).

**2.2 Out-of-sample calibration predictions (changed).** This is M7's frozen procedure (`fit_calibrated_win_prob_model`: model on the earlier rows, calibrator on the later held-out rows), applied to PX-1b.

- **Calibration-base model,** `playoff_px1b_calbase` `px2b-v2`:
  - fit exactly by PX-1b spec §2–§4 (normalization, column rules, round interactions, RMS scaling, no intercept, C = 1.0, lbfgs);
  - fit on the eligible PX-1b §1 rows of 2024–2026 that are **both**:
    - (a) `scheduled_time` strictly earlier than the slice's first row;
    - (b) from **no event that has a slice row**. 11 events straddle the cut; their pre-cut rows are excluded, so no event contributes to both the fit and the slice.
  - Registered write-once with its fit-set fingerprint and its match-key list, **before any 2027 playoff data exists** (the fit refuses otherwise).
- **Isolation assertions,** recorded; the run refuses if any fails:
  - fit set ∩ slice = ∅;
  - fit-set events ∩ slice events = ∅;
  - max fit `scheduled_time` < min slice `scheduled_time`.
- **Calibrator:**
  - `SymmetricIsotonicCalibrator`, from both perspectives as in M7;
  - fit on the **calibration-base model's** raw predictions of the slice. These are out-of-sample: the base model never saw those rows or their events.
- **Application:** the calibrator is applied to **`px1b-v1`'s** raw predictions. `px1b-v1` stays the evaluated, accepted model.
  - **Disclosed approximation:** `px1b-v1` was fit on more data than the base model, so its raw outputs may be slightly sharper.
  - The PX-2b gate on held-out 2027 measures the resulting calibration directly, so the approximation cannot pass unseen.

**Considered and not proposed:** serving the base model + calibrator instead of `px1b-v1`. That would replace the model FINAL-1 accepts.

## 3. Gate (unchanged from v1 §3: the P6-Q4 / M7 / D16 constants)

On the calibrated `px1b-v1` probabilities of the held-out 2027 rows:
- **G1:** ECE < 0.05.
- **G2:** 10 fixed bins; on bins with ≥ 30 predictions, an exact Poisson-binomial test; Holm at α = 0.05.
- **G3:** symmetry ≤ 1e-12, and order independence.
- **G4:** every slice row precedes every 2027 row.

**Pass** iff G1–G4 all pass. The §2.2 isolation assertions are preconditions of the run, not gate criteria.

## 4. Outcome, records and limits (as v1, plus the base-model provenance)

- **Pass:** PX-1b + PX-2b may be served as `validated_playoff`.
- **Fail:** `not_validated` (`px2b_gate_failed`), and D9 applies.
- **Record:** `results/p6_px2b.json`, write-once, also carrying:
  - this spec's blob;
  - the base model's registry tag, fingerprint and isolation assertions.
- **The calibrator:** `px2b_calibrator.json`.
- **Runtime:** one run, within the 45-minute budget.
- **Not changed after a result.**

## 5. Implementation needed on approval (not done)

- The `px2b` path in `scripts/phase6_playoff_track.py` (`b965210`) currently implements v1 and must be changed to §2.2.
- A one-time fit of the base model is needed (2024–2026 data only).
- Tests on synthetic data must prove:
  - the isolation assertions;
  - that the calibrator's inputs come from the base model;
  - that the gate is unchanged.
