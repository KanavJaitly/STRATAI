# P6-M10b (P6-M10 version 2): DRAFT specification. PROPOSED, NOT ADOPTED, NOT FROZEN

**Status: a draft for Kanav's review.** It governs nothing until Kanav approves this exact blob. Approval freezes it, then implementation follows; nothing is fit or evaluated before that.

**Unchanged:**
- P6-M10 v1 (`P6_M10_MODEL_SPEC.md`, blob `5f838613…`; model `p6m10-v1`, sha256 `aded2c82…`) and its failed result are kept unchanged.
- **P6-M10 stays `not_validated`** until this protocol yields a legitimate passing result.

**Evidence:** `decisions/P6_M10_REDESIGN_INVESTIGATION_2026-10-10.md`.

**What it changes:** v2 adds **one** component to v1, a symmetric calibration stage. Every other part of v1 is unchanged.

## 1. Model

- **Base:** the frozen `p6m10-v1`, unchanged. It is loaded by its pinned sha256 `aded2c82…` and is **not refit** (fit on 2024–2025, spec v1 §4). Its raw output is p = Φ(m/s).
- **Regime of a match,** known at prediction time from each team's `epa_source_event_key` season versus the match season:
  - `same`: all six EPA sources come from the match's season;
  - `prior`: all six come from an earlier season;
  - `mixed`: otherwise.
- **Calibrator (proposed: C-R):** a symmetric temperature per regime, q = σ(a_r · logit p).
  - **No intercept**, so q(1 − p) = 1 − q(p) exactly. Antisymmetry is preserved.
  - **a_r > 0** keeps the ordering, so strategy rankings are unchanged.
  - **The alternative for Kanav's choice (C-G):** one global a. Kanav picks C-R or C-G **before** approval. The other is not run.
- **Strategy parity:** q depends only on p and the regime, and the regime is a property of the teams' EPA sources, never of a strategy. The calibrator is therefore strategy-agnostic. (P6-Q8's defense/feeding rule is untouched.)

## 2. Populations (temporal rules)

| Role | Population | Constraint |
|---|---|---|
| Base fit | 2024–2025 EPA-complete qualification (v1 §4, unchanged) | already fit; not touched |
| **Calibrator fit** | **2026 EPA-complete qualification** matches in the D18 frame `frame_ab1adbf38b43c2f3`, with v1 §5's exclusions (ties; model input absent) | out-of-sample for the base. Observed, but never v2's acceptance data. Every row precedes every 2027 row |
| **Acceptance (FINAL)** | **2027 EPA-complete qualification** matches of the official season, assembled point-in-time (D18 semantics) from a pinned 2027 EPA source, with the same exclusions, each counted | untouched. Evaluated **once**, after the 2027 season is complete and synced, on Kanav's written authorization |

## 3. The calibrator fit (once, before any 2027 data exists)

- **Estimator:** a_r = argmin over a ∈ (0, 5] of the log-loss of σ(a · logit p_i) over the regime's calibration rows. It is computed deterministically by bounded scalar minimization; p is clipped to [1e-12, 1 − 1e-12].
- **Minimum size:** a regime with fewer than 200 calibration rows uses the global a instead. The 2026 counts are same 5,439, mixed 4,132 and prior 2,644, so none falls back.
- **Registration:** registered write-once as `strategy_outcome_calibrator` `p6m10b-v1`, with the calibration-set fingerprint, the base sha256 and this spec's blob. It is sha-pinned in an additive pin record **before** any 2027 data exists, and refused if 2027 data exists.

## 4. Development check DEV-M10b (pre-registered; development evidence, not acceptance)

- **Procedure:** refit the v1 procedure on **2024 only**, fit the same calibrator form on **2025**, and evaluate raw and calibrated predictions on **2026**.
- **Reported:** G1–G4, ECE, the calibration slope per regime, and the fitted a_r for 2025 and 2026 (stability).
- **Proceed iff both hold:** the calibrated predictions have **fewer G2-rejected bins** than raw, and **ECE ≤ raw ECE**.
  - Otherwise v2 does not proceed, and a new version would be needed.
  - 2026 motivated this design, so DEV-M10b is consistency evidence only.

## 5. Acceptance gate (the P6-Q9 / M7 / D16 constants, unchanged)

On the 2027 population, using the calibrated q:

| | Requirement |
|---|---|
| **G1** | ECE < 0.05 |
| **G2** | 10 fixed bins; on bins with ≥ 30 predictions, an exact Poisson-binomial test; Holm at α = 0.05 |
| **G3** | symmetry ≤ 1e-12, and order independence |
| **G4** | fit isolation: every base-fit and calibrator-fit row precedes every 2027 row |

**Pass iff G1–G4 all pass.** No gate constant is changed, and none may be changed after a result.

**Reported, not gated:**
- the paired log-loss vs M6/M7 `d18` on the same rows (event bootstrap, 2,000 resamples, seed 20261005, as v1);
- Brier;
- per-regime calibration slopes;
- raw-v1 (uncalibrated) metrics on the same rows, for comparison.

## 6. Leakage and integrity checks (the run refuses if any fails)

- **Pinned artifacts:**
  - the base sha256 `aded2c82…`;
  - the calibrator sha256 (from its pin);
  - this spec's blob;
  - M6/M7 `d18` via `load_m6m7`.
- **No 2027 row in any fit set:**
  - the calibrator's fingerprint and its season set equal 2026 only;
  - the base fit is 2024–2025 (record `p6_m10_fit.json`).
- **Point in time:** every input is assembled at the match's `as_of` (the v1 §1 inputs, D18 EPA); the regime comes from EPA source keys only.
- **Ordering:** registration evidence for the calibrator, as for PX-1b. Its pin commit must be a strict ancestor of the commit that records the 2027 population. Local git times are self-asserted (`P6_PX1B_REGISTRATION_EVIDENCE_AUDIT_2026-10-10.md`).
- **Run once:** the record is write-once, and a second run is refused.

## 7. Outcome and dependencies

- **Pass:** P6-M10 baseline odds may be served `validated` **only after**:
  1. Kanav's dated, sha-matched confirmation of the result;
  2. **a P6-M13 parity audit re-run on v2**, the P6-DM2 procedure unchanged, which must pass before v2 replaces v1 in serving.
- **Fail:** D9 applies. v2 is recorded `not_validated`, and a further version needs a new untouched population (2028).
- **Prerequisites shared with PX-1b FINAL-1:** 2027 data, a pinned 2027 EPA source, and causal scales for 2027.

## 8. Decisions requested from Kanav before freezing

1. **C-R (per-regime temperature) or C-G (global).** Recommended: C-R.
2. **Approve the calibration population (2026), the 2027 acceptance population, and DEV-M10b's proceed rule.**
3. **Approve the post-pass requirement of a v2 parity audit.**
4. **Note:** v2 keeps v1's attenuated base (cause 1) and corrects it after the fact. Options A, B and D remain possible future versions and are not pursued here.
