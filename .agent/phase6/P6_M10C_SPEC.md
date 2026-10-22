# P6-M10c (P6-M10 version 3): specification

**Status.**
- **Approved for pursuit by Kanav (2026-10-11).** Its form is fixed by his decisions (`decisions/P6_M10C_DECISIONS_2026-10-11.md`).
- **Frozen by `decisions/P6_M10C_FREEZE_2026-10-11.md`, at the blob that record names.** It governs M10c only.

**Unchanged by this specification:**
- the M10b spec (`d699afaf`), A1 (`a453eaba`), and every M10b record (DEV, calibrator, pins, audit);
- the draft `P6_M10C_SPEC_DRAFT.md` (blob `30bc747b`, kept as history);
- P6-M10 v1 and its failure.

**P6-M10 stays `not_validated`.** `p6m10-v1` stays served.

**What M10c changes from M10b:** only the calibration link (§1) and its fit (§3).
- **Unchanged (M10b §1–§2, §5):** the base, the probit index x, z(x), the source groups, the gate, its constants and the A1 population.
- **Different evidence:** DEV-c (§4) replaces DEV-M10b as M10c's development check.

## 1. Model

**Base.** The frozen `p6m10-v1` (sha256 `aded2c829a1f2edbd1ddb50e099b0e88df8a5cc4033efe0fa7270dae235fbf5f`), not refit.
- x = m / σ from its evaluation.
- z(x) = `log_ndtr(x) − log_ndtr(−x)`, with no clipping; a non-finite x is refused (`insufficient_data`), as M10b §1.

**Link.** g is the match's source group (§2); a_g > 0 and 0 ≤ ε ≤ 0.08:

- q_red = ε/2 + (1 − ε) · expit(a_g · z)
- q_blue = ε/2 + (1 − ε) · expit(−a_g · z), computed directly, never as 1 − q_red.

**ε is pooled across groups.** There are no group-specific ε values and no week-specific factors.

**Properties.** Each is tested (§8):

| Property | Statement |
|---|---|
| Symmetry | q_red + q_blue = 1 in real arithmetic; \|q_red + q_blue − 1\| ≤ 1e-12 in floating point (G3's tolerance) |
| Monotonicity | Strictly increasing in z, and so in x, wherever expit is not saturated. No ordering reversal within a match (M10b §1.1, C1). Ties only where expit saturates (\|a_g · z\| ≳ 37), as M10b |
| Bounds | q ∈ (ε/2, 1 − ε/2) in real arithmetic; in floating point, within one rounding where expit saturates. The internal probability is never clamped |
| Nesting | at ε = 0 the link equals M10b's |
| Display (P6-A5, unchanged) | "<5%" below 0.05, ">95%" above 0.95, otherwise 0.05 steps. Since ε/2 ≤ 0.04 < 0.05, "<5%" remains reachable. With ε > 0, q is never below ε/2, so the "<5%" bucket covers [ε/2, 0.05) |

**The bound is about display, not calibration.** The bound ε ≤ 0.08 keeps the display semantics and the P6-M13 M7 low-odds check possible. **It does not imply calibration.** Calibration is decided only by the §5 gate.

## 2. Groups, the prediction season, missing data

As M10b §2, unchanged.
- **Groups:** `same`, `prior` or `mixed`, from `MatchContext.prediction_season` and each team's D18 `epa_source_event_key` season.
- **Refusals** (`insufficient_data`): an absent prediction season, or an unresolvable or later-season source.
- **Inputs absent from the base:** v1's own refusal, passed through unchanged.
- **Never imputed.**

## 3. Fit

**Calibration rows** (production; fitting them is a separate authorization):
- M10b §3's set: the 2026 EPA-complete qualification rows of frame `frame_ab1adbf38b43c2f3` that the base scores, ties excluded.
- That is 12,215 rows, groups 5,439 / 4,132 / 2,644, fingerprint `cf205ad69ace9fdbe26c1a7e4751cae2a1d75e2b1ea82a225abde7c9d6ffba22`. Any difference is refused.

**Per row:** z_i; s_i = +1 if red won, −1 if blue won (ties are excluded, never encoded); and the group g_i.

**Parameters:** θ = (a_same, a_mixed, a_prior, ε).
- **Small groups.** A group with n_g < 200 has its slope fixed at a_G. a_G comes from the global two-parameter fit (a_G, ε_G) of the same objective on all calibration rows, which is always computed and recorded. The remaining slopes and ε are fit jointly.

**Objective:** the mean negative log-likelihood, computed stably:

  L(θ) = −(1/n) Σ_i ℓ_i,  with t_i = a_{g_i} · s_i · z_i
  ℓ_i = logaddexp( log(ε/2), log1p(−ε) + log_expit(t_i) ) for ε > 0;  ℓ_i = log_expit(t_i) for ε = 0

**Gradient:** analytic. With p_i = exp(ℓ_i):
  ∂L/∂a_g = −(1/n) Σ_{i∈g} (1 − ε) · σ(t_i) · σ(−t_i) · s_i · z_i / p_i
  ∂L/∂ε  = −(1/n) Σ_i (1/2 − σ(t_i)) / p_i

Each ratio is evaluated in log space where needed.

**Optimizer:**
1. **L-BFGS-B:** `scipy.optimize.minimize(L, x0, jac=True, method="L-BFGS-B", bounds=…, options={"gtol": 1e-10, "ftol": 1e-15, "maxiter": 1000, "maxcor": 10})`.
   - x0: every a = 1.0, ε = 0.02.
   - Bounds: a_g ∈ [0.05, 5.0]; ε ∈ [0, 0.08].
2. **Newton polish:** up to 20 steps from the L-BFGS-B solution.
   - Each step uses the analytic gradient and the central-difference Hessian (step 1e-6 per coordinate, symmetrized).
   - A step is accepted only if it keeps θ within the bounds and does not increase L; otherwise polishing stops.
   - Polishing stops early when ‖∇L‖∞ ≤ 1e-10.
3. **Deterministic,** with no randomness.

**Outcomes and checks,** in this order, all recorded:

| # | Check | Result if it fails |
|---|---|---|
| 1 | L-BFGS-B `success` true and `nit` < 1000 | refused: `optimizer_failed` |
| 2 | **Lower ε bound:** ε ≤ 1e-6 | outcome **`no_floor_identified`**. M10c equals M10b; no M10c candidate is produced. A fail, not a refusal of the data |
| 3 | Each a_g more than 1e-6 from 0.05 and 5.0; ε more than 1e-6 from 0.08 | refused: `solution_at_bound` (mis-specification; never clipped) |
| 4 | ‖∇L(θ*)‖∞ ≤ 1e-7 | refused: `not_stationary` |
| 5 | The smallest eigenvalue of the central-difference Hessian at θ* is > 1e-10 | refused: `not_unique` |

**On any refusal or `no_floor_identified`:**
- the write-once record names every failed check;
- nothing is registered;
- nothing is retried with other settings.

**Artifact (production only; a separate authorization):** registered write-once as `strategy_outcome_calibrator_m10c` `p6m10c-v1`, holding:
- θ, a_G, ε_G and the counts;
- each check and the Hessian eigenvalues;
- the base sha256, the fit-set fingerprint and this spec's blob.

**Pins:** an additive pin record `p6_m10c_pins.json`, committed before any 2027 data.

## 4. Development check DEV-c (diagnostic only; never acceptance)

**Question:** given the same base and the same calibration rows, does the M10c link improve on M10b's scalar link, on later rows of the same season?

**Run:** once, after this spec is frozen, and only with `decisions/p6_m10c_dev_authorization.json` (`authorized`, `authorized_by`, `date`, `scope: "DEV-c"`, `spec_blob`).

**Record:** `results/p6_m10c_dev.json`, write-once.

### 4.1 Base
- The v1 procedure (`P6_M10_MODEL_SPEC.md` §4, via `scripts.phase6_m10_fit.component_fit_set`), refit on **2024** rows of frame `frame_ab1adbf38b43c2f3`. Any other frame is refused.
- It must reproduce DEV-M10b's recorded base, with every β and every Σ entry within 1e-12. Otherwise the run is refused.
- It is not registered.

### 4.2 Population and classes (deterministic)
**Rows:** 2025 v1-population rows (qualification, EPA-complete, ties excluded and counted) that the base scores.
- Rows the base cannot score are excluded and counted.
- Rows refused by §2 are counted separately.
- `prediction_season` = 2025.

**Event type and week:** read from each event's current raw TBA event payload. **Fail-closed:** a missing payload, a non-integer `event_type`, or a non-integer `week` on a type 0/1/2/5 event refuses the run.

| Class | Definition | Rows (counted 2026-10-11 without outcomes) |
|---|---|---|
| **C** (calibration) | `event_type` ∈ {0, 1, 2, 5} and `week` ∈ {0, 1, 2, 3} | 6,086 scorable rows in 131 events |
| **E** (evaluation) | (`event_type` ∈ {0, 1, 2, 5} and `week` ≥ 4) or `event_type` ∈ {3, 4} (Championship, whose TBA `week` is null) | 4,985 scorable rows in 65 events |
| other | any other `event_type` | excluded and counted (none exist) |

### 4.3 Temporal ordering and leakage

The run refuses unless all of these hold:
1. no event has rows in both C and E;
2. max scheduled time over C < min scheduled time over E. Checked 2026-10-11: 2025-03-23 vs 2025-03-26;
3. the latest base-fit row (2024) is before the earliest C row;
4. no match key appears in both C and E.

**Fit isolation** (the gate's G4 input) is true exactly when 1–4 hold.

### 4.4 Fits on C
- **M10b form:** `ml.strategy.calibration.fit_calibrator`, unchanged, with M10b §3's checks.
- **M10c:** §3.
- Both use the identical rows, z, s and groups.

### 4.5 Evaluation on E

Both models are evaluated on the **identical** E rows: the rows both score. Any row only one model scores refuses the run.

**Gate:** `evaluate_calibration_gate`, unchanged, for each model.
- **Symmetry:** from both colour orders.
- **Order independence:** from reversed evaluation order.
- **Fit isolation:** from §4.3.

### 4.6 Diagnostics and the decision rule (predeclared)

Each diagnostic has a status of `pass`, `fail` or `unevaluable`. **An unevaluable diagnostic never counts as a pass.**

| Id | Diagnostic | `pass` | `fail` | `unevaluable` |
|---|---|---|---|---|
| D1 | the M10c fit on C | §3 succeeds with ε > 1e-6 | any refusal, or `no_floor_identified` | — |
| D2 | the M10b-form comparator fit on C | M10b §3 succeeds | — | the comparator fit is refused |
| D3 | G2 rejections | both G2 are evaluable, and M10c's ≤ the M10b form's, strictly fewer unless the M10b form has 0 | both are evaluable and the condition fails | either G2 is unevaluable, or D1/D2 are not `pass` |
| D4 | ECE | both are finite, and M10c's ≤ the M10b form's | both are finite and the condition fails | either is absent or not finite, or D1/D2 are not `pass` |

**Decision.**
- **`proceed`:** D1–D4 all `pass`.
- **`rule_not_met`:** any diagnostic is `fail`.
- **`unevaluable`:** otherwise.

**Only `proceed` permits asking Kanav to adopt M10c.**

**Reported, never gating:**
- each model's per-bin table, log-loss, Brier, and per-group calibration slopes;
- the raw base on E;
- θ, a_G, ε_G and the Hessian eigenvalues;
- the fingerprints of the base fit set, C and E;
- every count and exclusion.

**What DEV-c is.** It is consistency evidence, **never** independent acceptance evidence.
- 2025 C was DEV-M10b's calibration season, and the M10c design came from 2026.
- Within-season transfer is not the cross-season transfer 2027 needs.
- Group and week are confounded.
- E has about 500 rows per bin, so G2's power is lower than at 12k.

**A `proceed` does not authorize** registration, a production fit, pins, serving, or any change to the gate.

## 5. Gates (unchanged)

As M10b §5 and A1, exactly:
- `evaluate_calibration_gate`;
- N_BINS 10, MIN_BIN_COUNT 30, ALPHA 0.05, ECE_THRESHOLD 0.05, MIN_ELIGIBLE_BINS 2, TIE_TOLERANCE 1e-7, SYMMETRY_TOLERANCE 1e-12;
- G1–G4. G4 covers the base (2024–2025) and the calibrator (2026), both before every 2027 row;
- the A1 population: official events by raw TBA type 0–5, fail-closed.

## 6. 2027 acceptance and multiplicity

**Mechanics:** a run-once 2027 evaluation, as M10b §6:
- pins committed before any 2027 data;
- ordering evidence;
- the shared 2027 frame record;
- Kanav's authorization naming this blob;
- a write-once `p6_m10c_outcome_model.json`.

**Multiplicity (Kanav, 2026-10-11).**
- **If M10c is adopted,** M10c is the **sole primary candidate** for the 2027 P6-M10 acceptance test. M10b is preserved unchanged as historical evidence and is **not** evaluated on 2027.
- **No choosing between candidates:** two candidates are never evaluated on 2027 so that whichever passes can be chosen.
- **If M10c is not adopted,** M10b remains the frozen candidate.
- **Adoption** is Kanav's dated decision, made after DEV-c and before any 2027 data.

## 7. Served status and the serving guard

As M10b §7, applied to M10c's own records:
- the passed outcome record;
- Kanav's sha-matched confirmation;
- a passing P6-M13 parity rerun on the M10c identity, under a v3 rerun plan whose planted "different calibration" defect scales the AI path's slopes by 1.25.

Until all hold, `p6m10-v1` stays served (`not_validated`).

## 8. Tests

**Executable at freeze:** `tests/test_phase6_m10c_spec.py`, the link's math:
- symmetry, monotonicity and bounds (with floating-point handling);
- nesting;
- the stable likelihood;
- display reachability: "<5%" for any q in [ε/2, 0.05) at every ε ≤ 0.08; ">95%" for its mirror.

**With the implementation:**
- the fit's checks: bound, `no_floor_identified`, non-stationary, non-unique, optimizer failure, determinism;
- the gradient against finite differences;
- small-group fixing;
- DEV-c's class assignment (fail-closed), temporal and leakage refusals, identical-row comparison, each diagnostic status, and the decision rule;
- write-once records and the authorization;
- the end-to-end symmetry, ordering and display of the wrapper through the real `StrategyEngine`.

**Runtime:** DEV-c is closed-form plus 4-parameter fits on about 6k rows, a few minutes at most. The hard limit is 45 minutes.
