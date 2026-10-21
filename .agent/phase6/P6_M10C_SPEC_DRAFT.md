# P6-M10c (P6-M10 version 3): DRAFT specification. PROPOSED, NOT ADOPTED, NOT FROZEN

**Status: a draft for Kanav's review.**
- It governs nothing until Kanav approves **this exact blob**; approval freezes it.
- Implementation, any fit and any evaluation each need a further, separate authorization.
- **Nothing in this draft has been fit or evaluated on any data.**

**Basis:** `decisions/P6_M10_POST_DEV_DIAGNOSIS_2026-10-11.md`, alternative A1.

**Unchanged and not superseded by this draft:**
- the frozen M10b spec (`P6_M10B_SPEC.md`, blob `d699afaf`) and A1 (`a453eaba`);
- every M10b record (DEV, calibrator, pins);
- P6-M10 v1 and its failure.

**P6-M10 stays `not_validated`.** `p6m10-v1` stays served.

**What M10c changes relative to M10b: only the calibration link (§1).**

| Unchanged from M10b | Section |
|---|---|
| The base (`p6m10-v1`, `aded2c82…`, not refit) | §1 |
| The probit index x and the stable log-odds z(x) | §1 |
| The source groups and `prediction_season` | §2 |
| The calibration population (v1's 12,215 2026 rows) | §3 |
| The gate, its constants and the A1 population | §5 |

## 1. Model

**The link.** With g the source group of the match, z = log_ndtr(x) − log_ndtr(−x) and s = +1 for red:

- q_red = ε/2 + (1 − ε) · expit(a_g · z)
- q_blue = ε/2 + (1 − ε) · expit(−a_g · z), computed directly, never as 1 − q_red.

**Meaning:**
- **ε (the upset floor):** the share of matches whose outcome is unrelated to the strength gap (breakdowns, disconnections, fouls), each decided as a coin flip.
- **a_g:** the group's log-odds slope, as in M10b.

**Properties.** Each holds for a_g > 0 and 0 ≤ ε < 1, and the spec tests check each:

| Property | Statement |
|---|---|
| Exact symmetry | q_red(z) + q_blue(z) = 1 in real arithmetic; in floating point the error is a few rounding units, tested ≤ 1e-12 (G3's tolerance) |
| Strictly increasing in z | so in x. No ordering reversal within a match: the C1 statement of M10b §1.1 carries over. Ties occur only where expit saturates, as in M10b |
| Bounded | q ∈ (ε/2, 1 − ε/2) in real arithmetic; in floating point, within one rounding where expit saturates. The internal probability is never clamped |
| Nested | at ε = 0, M10c is M10b exactly |

## 2. Groups and the prediction season

As M10b §2, unchanged: `same` / `prior` / `mixed` from `prediction_season` and the D18 `epa_source_event_key` seasons, with the same refusals.

## 3. Fit

**Calibration set:** as M10b §3. These are v1's 12,215 2026 rows, and the fingerprint must equal `cf205ad69ace9fdb…` (M10b's).

**Parameters:** θ = (a_same, a_mixed, a_prior, ε), fit jointly. ε is **pooled across groups**: the prior group's tails are too small for a per-group ε.

**Objective.** The mean negative log-likelihood of the observed outcome, computed stably:

  L(θ) = −mean_i log( ε/2 + (1 − ε) · expit(a_{g_i} · s_i · z_i) )

  with log(ε/2 + (1 − ε)·σ(t)) = logaddexp(log(ε/2), log(1 − ε) + log_expit(t)) for ε > 0, and log_expit(t) for ε = 0.

**Optimizer.** `scipy.optimize.minimize(method="L-BFGS-B")`:

| Setting | Value |
|---|---|
| Bounds | a_g ∈ [0.05, 5.0]; **ε ∈ [0, 0.08]** |
| Start | a_g = 1, ε = 0.02 |
| Options | `gtol` 1e-10, `ftol` 1e-15, `maxiter` 1000 |
| Determinism | deterministic |

**Why ε ≤ 0.08.** It keeps the floor ε/2 ≤ 0.04 below the 0.05 display step, so "<5%" stays reachable. P6-A5's display and the P6-M13 M7 low-odds check both need that. The bound comes from display semantics, not from results.

**Checks.** Every one must pass:
1. `success` is true, and `nit` < 1000;
2. each a_g is more than 1e-6 from both bounds;
3. ε is more than 1e-6 from 0.08 (an upper-bound solution is mis-specification, and is refused);
4. the projected gradient norm is ≤ 1e-7;
5. the Hessian at θ* is positive definite (smallest eigenvalue > 1e-10; analytic, or central differences with step 1e-5): a unique minimum.

**If ε is within 1e-6 of 0:** no upset floor is identified. M10c then equals M10b, so it adds nothing. It is recorded, no M10c candidate is registered, and M10b stands as frozen.

**Fallback:** a group with n_g < 200 shares one slope a_G, fit jointly with ε. The 2026 counts are 5,439 / 4,132 / 2,644, so no fallback is expected.

**On any refusal:** nothing is registered, and nothing is retried with other settings.

**Artifact:** registered write-once as `strategy_outcome_calibrator` `p6m10c-v1`, holding:
- θ and the counts;
- the checks and the Hessian eigenvalues;
- the base sha256, the fit-set fingerprint and this spec's blob.

**Pins:** an additive pin record `p6_m10c_pins.json`, committed **before any 2027 data**, as for M10b.

## 4. Development check DEV-c (diagnostic only; never acceptance)

**Question:** given the same base and the same calibration rows, does the upset floor improve on M10b's scalar form?

**Data not used to design M10c.** The design came from 2026. 2025's later weeks were never examined bin by bin.
- **Base:** the v1 procedure refit on 2024 only, as DEV-M10b. It must reproduce the DEV record's β and Σ within 1e-12. It is not registered.
- **Calibration:** both forms (M10b's scalar, and M10c) are fit on **2025 weeks 0–3**: about 6,150 non-tie EPA-complete qualification rows, counted 2026-10-11 without reading outcomes. The TBA `week` comes from the raw event payload; if it is missing, the run refuses.
- **Evaluation:** both forms on **2025 weeks 4–5 plus the Championship** (types 3/4): about 4,985 rows. Unchanged gate function.
- **Proceed rule.** Each part has an explicit pass, fail or unevaluable status, and an unevaluable part never passes. **All must pass:**
  1. the M10c fit succeeds, with ε > 0;
  2. M10c G2 rejections ≤ the M10b form's on the same rows, and strictly fewer unless the M10b form has 0;
  3. M10c ECE ≤ the M10b form's ECE.
- **Otherwise M10c stops**, and M10b stands.
- **Record:** `results/p6_m10c_dev.json`, write-once, with every fingerprint, both forms' bins, and per-group slopes.

**Limitations, recorded in the result:**
- Within-season transfer (early → late weeks) is not the 2025 → 2026 → 2027 season transfer.
- Group and week are confounded.
- About 500 rows per bin, so G2 has less power than at 12k.

## 5. Gates

Identical to M10b §5 and A1:
- `evaluate_calibration_gate`, unchanged, with every constant;
- G1 to G4, with G4 covering both fit sets: the base on 2024–2025, the calibrator on 2026, all strictly before every evaluated 2027 row;
- the A1 population: official events, by raw TBA type 0–5, fail-closed.

**No threshold, constant or population change.**

## 6. 2027 acceptance and multiplicity

The run-once 2027 evaluation mirrors M10b §6: pins, ordering evidence, a frame (shared with M10b's `frame-2027` record if both run), Kanav's authorization naming this blob, and a write-once `p6_m10c_outcome_model.json`.

**Multiplicity: Kanav decides before any 2027 data.** Testing two candidates on the one 2027 holdout must not double the chance of a false pass.

| Option | Meaning |
|---|---|
| **(a) Supersede (recommended if DEV-c proceeds)** | M10c replaces M10b as the only 2027 candidate. M10b's records are kept unchanged and marked superseded, never run. One test, no multiplicity |
| **(b) Primary plus secondary** | A primary candidate is declared before 2027. Only the primary's pass can switch serving. The secondary's result is reported only |

## 7. Served status and the serving guard

As M10b §7, applied to M10c's own records:
- a passed outcome record;
- Kanav's sha-matched confirmation;
- a passing P6-M13 parity rerun on the M10c identity.

**The parity rerun needs a v3 rerun plan.** Its planted "different calibration" defect scales the AI path's a_g by 1.25. The floor ε/2 ≤ 0.04 keeps the M7 low-odds context reachable.

**Until all hold, `p6m10-v1` stays served.** The status table (baseline only `validated`; strategies, observations and playoffs unchanged) is as in M10b.

## 8. Tests

**Executable now, against the math only (no production code):** `tests/test_phase6_m10c_spec.py`.
- symmetry ≤ 1e-12 across a and ε;
- strict monotonicity in z;
- the bounds;
- nesting at ε = 0 (equals M10b's link);
- the stable log-likelihood equals the naive form where both are finite;
- the floor is below 0.05 at the ε bound.

**Pre-registered, implemented only after freezing and implementation approval:**
- the M10b test set, adapted (T-GROUP, T-FIT with the Hessian and ε-boundary cases, T-WRAP, T-GATE, T-RUN, T-SERVE);
- DEV-c's week split and fail-closed week lookup.

## 9. Decisions for Kanav

1. Proceed with M10c at all, or keep M10b (A0) alone.
2. The ε bound [0, 0.08], and pooling ε across groups.
3. DEV-c's design: the 2025 weeks 0–3 / weeks 4–5 + Championship split, the M10b-form comparator, and the proceed rule.
4. Multiplicity: (a) supersede, or (b) primary plus secondary.
5. Then approve this exact blob, to freeze it. Implementation is a separate authorization.

**Season drift (§1.3 of the diagnosis) is not addressed by M10c.** A calibrator fit on 2026 may still mis-scale 2027, whatever its shape.
