# P6-M10b (P6-M10 version 2): DRAFT specification, revision 2. PROPOSED, NOT ADOPTED, NOT FROZEN

**Status: a draft for Kanav's review.**
- It governs nothing until Kanav approves **this exact blob**.
- Approval freezes it. Only then may implementation, fitting or evaluation begin.

**History, kept unchanged:**
- draft revision 1, `P6_M10B_SPEC_DRAFT.md` (blob `b9dea322dc71a8901e58a32686eacd2a0de7d091`, `a035af6`);
- its audit, `decisions/P6_M10B_SPEC_DRAFT_AUDIT_2026-10-10.md` (`9a37e22`).

**Authority:** Kanav, 2026-10-10. Choice **C-R** (per-source-group calibration) approved; corrections C1–C11 to be incorporated; drafting only.

**Unchanged:**
- P6-M10 v1: `P6_M10_MODEL_SPEC.md` (blob `5f838613…`), model `p6m10-v1` (sha256 `aded2c82…`), and its failed result (`30dcf55`).
- **P6-M10 stays `not_validated`** until this protocol yields a legitimate pass, a confirmation and a parity rerun (§7).

## 1. Model

**Base.** The frozen `p6m10-v1`, loaded only with its pinned sha256 `aded2c82…` and **not refit**.
- For a match context and its strategies, the base gives the mean difference m and σ (`OutcomeEvaluation.mean_difference`, `.sigma`).
- The **probit index** is x = m / σ. v1's raw output is Φ(x).

**Stable log-odds (C2).** There is no probability clipping anywhere.

z(x) = `scipy.special.log_ndtr(x) − scipy.special.log_ndtr(−x)`

- **Exact:** this is exactly logit(Φ(x)) in real arithmetic.
- **Finite:** z is finite for every finite x (for example |z(±40)| ≈ 804).
- **Strictly increasing,** and **antisymmetric bit for bit:** z(−x) = −z(x), since IEEE subtraction is exactly antisymmetric.
- **Refusals:** a non-finite x (σ ≤ 0, NaN) is refused as `insufficient_data`.

**Calibrated output (C-R).** For group g (§2) with factor a_g (§3):
- q_red = `scipy.special.expit(a_g · z(x))`;
- q_blue = `expit(−a_g · z(x))`, computed directly, never as 1 − q_red.

**Where it is applied (C1, C9).** Inside the **single** evaluation function, a v2 wrapper around `ComponentOutcomeModel.evaluate`.
- It is used identically by the AI path (`StrategyEngine.recommend` → `assess`) and the coach path (`assess`/`compare`), as P6-Q10 requires.
- The recommender, display and comparison code never see v1's raw probabilities when v2 is served.

### 1.1 Ordering and tie-break properties (C1; exact statement)

**Within one match context** (the six teams and the side are fixed; this is every comparison STRATAI presents: `recommend`, `compare`, `compare_odds`):
- All candidates share one group g, so one a_g > 0.
- **Real arithmetic:** q is strictly increasing in x. So q_i > q_j ⇔ x_i > x_j, and **no ordering reversal is possible**.
- **Floating point:** `log_ndtr` and `expit` are monotone non-decreasing. A strictly ordered pair can only **collapse to equal q** where expit saturates (|a_g·z| ≳ 37, a probability within about 1e-16 of 0 or 1); it can never reverse.
- **Ties** (equal q) are broken by the **unchanged** recommender key: `(-p_ours, changes_from_baseline(), canonical_json())`.

**Relative to v1** (also floating point):
- **Pairs v1 orders strictly:** v2 never reverses them. They may tie only at v2 saturation.
- **Pairs v1 ties** (v1's Φ saturates to exactly 1.0 or 0.0 once |x| ≳ 8.3): v2 may order them by x where a_g·z is below saturation. That is deterministic and follows the same x ordering.

**Across contexts:** under C-R, predictions in different groups can reorder. No STRATAI feature ranks M10 probabilities across contexts (no Phase 6 HTTP strategy route; P6-A1).

**Displayed differences** (for example the recommended strategy against the baseline):
- They change size by the factor a_g in log-odds.
- The same function serves the AI and the coach, so parity (P6-DM2) is unaffected.
- Non-baseline strategies stay `not_validated` (`strategy_effect_unmeasured`) whatever their displayed difference (§7).

## 2. Prediction season and source groups (C3)

**`prediction_season` (required input).** The season of the event for which the context's `TeamFeatures` were assembled.
- **For frame rows** (calibration, development, acceptance): the row's `season`.
- **For live contexts:** `events.season` of the `event_key` passed to the feature assembler, supplied by the caller with the context.
- **If absent:** refused (`insufficient_data`, reason `prediction_season_absent`). It is never inferred.

**Source season of team t.** `events.season` of `TeamFeatures.epa_source_event_key`.
- **Static metadata:** the event's season never changes.
- **Point in time:** D18 chooses the key at the context's `as_of`, as the latest concluded event strictly before `as_of`. Nothing after `as_of` can affect it.

**The six teams.** The context's three red and three blue teams, regardless of strategy weights or coach observations.

**Group assignment:**

| Group | Condition |
|---|---|
| `same` | all six source seasons equal `prediction_season` |
| `prior` | all six are earlier than `prediction_season` |
| `mixed` | otherwise (some equal, some earlier) |

**Refused** (`insufficient_data`):
- **any source key unresolvable, or a source season later than `prediction_season`.** This is unreachable whenever v1 predicts, because v1 already refuses when `epa_scale` is absent, and `ScaleLookup.feature_scales` gives `epa_scale = None` for a missing or later-season source. It is kept as an explicit refusal anyway.

## 3. Calibration fit (C4; run once, before any 2027 data exists)

**Calibration set.**
- **Rows:** the 2026 EPA-complete qualification rows of the D18 frame `frame_ab1adbf38b43c2f3`, with every v1 §1 input present and ties excluded. These are the 12,215 rows v1 evaluated.
- **Per row:** x from the frozen base, z = z(x), group g, and s = +1 if red won, −1 otherwise.
- **The fit set's fingerprint is recorded.**

**Objective, per group g with n_g ≥ 200:**

L_g(a) = (1/n_g) · Σ softplus(−a · s_i · z_i), where softplus(t) = `numpy.logaddexp(0, t)`

- This is the mean log-loss of q = expit(a·z), computed stably.
- **Bounds:** a ∈ [0.05, 5.0].
- **Global factor:** a_G is fit by the same rule on **all** calibration rows. It is always computed and recorded, and it is used for any group with n_g < 200.
- **Fallback depends on calibration counts only:** the fallback is decided by the calibration set's per-group counts alone, so it is deterministic and **never** depends on any acceptance-population outcome. The 2026 counts are same 5,439, mixed 4,132 and prior 2,644, so no fallback is expected.

**Optimizer:** `scipy.optimize.minimize_scalar(L_g, bounds=(0.05, 5.0), method="bounded", options={"xatol": 1e-10, "maxiter": 500})`. It is deterministic.

**Convergence and refusal checks.** Every factor must pass all of them:
1. `result.success` is true and `result.nit` < 500;
2. **not at a bound:** |a* − 0.05| > 1e-6 and |a* − 5.0| > 1e-6. A bound solution signals mis-specification and is **refused**, never clipped;
3. **stationarity:** |L'(a*)| ≤ 1e-8, where L'(a) = −(1/n) Σ s_i z_i · expit(−a s_i z_i);
4. **strict convexity, so a unique minimum:** L''(a*) > 1e-12, where L''(a) = (1/n) Σ z_i² · expit(a s_i z_i) · expit(−a s_i z_i). A flat objective (all z ≈ 0) is refused as non-unique.

**If any check fails:**
- no calibrator is registered;
- a refusal record names the failing check and goes to Kanav;
- no retry with other settings is made.

**Symmetry.** There is no intercept, so q(B,R) = 1 − q(R,B) exactly in real arithmetic (G3 checks it numerically). L_g is invariant under (z, s) → (−z, −s), so augmenting both perspectives would give the identical a.

**Artifact and pin.**
- Registered write-once as `strategy_outcome_calibrator` `p6m10b-v1`, holding {a_same, a_mixed, a_prior, a_G, n per group, the checks, the base sha256, the fit-set fingerprint, this spec's blob}.
- Its file sha256 goes into an additive pin record `p6_m10b_pins.json`, committed **before** any 2027 data exists. Creating either one is refused once 2027 data exists.

## 4. Development check DEV-M10b (C5, C6). DIAGNOSTIC ONLY; never acceptance

**Scope (C6):** it tests the **procedure**, not the v2 artifact. Its base is a separate fit on 2024 only.

**Procedure:**
1. Refit the v1 procedure (`P6_M10_MODEL_SPEC.md` §4) on **2024** rows only.
2. Fit the §3 calibrator on **2025** rows.
3. Evaluate the raw and calibrated predictions on **2026** with `evaluate_calibration_gate`.

**Proceed rule (C5).** Fixed here, before any run. **All three** must hold:
- (i) the §3 fit succeeds (no refusal);
- (ii) calibrated G2 rejections ≤ raw G2 rejections, and **strictly fewer unless raw has 0**;
- (iii) calibrated ECE ≤ raw ECE.

**Otherwise v2 stops.** There is no FINAL run, and a new version would be needed.

**What it can and cannot show.** 2026 motivated this design. A DEV result is therefore consistency evidence, **never** independent acceptance evidence.

**Record:** `results/p6_m10b_dev.json`, write-once.

## 5. Gates (C7, C8)

**Function, unchanged (C7):** `ml.calibration.gate.evaluate_calibration_gate`, with its constants as they stand:
- `N_BINS = 10`
- `MIN_BIN_COUNT = 30`
- `ALPHA = 0.05`
- `ECE_THRESHOLD = 0.05`
- `MIN_ELIGIBLE_BINS = 2`
- `TIE_TOLERANCE = 1e-7`
- `SYMMETRY_TOLERANCE = 1e-12`

**Preserved exactly from v1 §5:**

| | Requirement |
|---|---|
| **G1** | ECE < 0.05 |
| **G2** | exact Poisson-binomial per-bin test, Holm α = 0.05, 10 fixed bins, bins with ≥ 30 predictions |
| **G3** | \|q(R,B) + q(B,R) − 1\| ≤ 1e-12, with order independence |

**Pass iff all four pass.** No constant may change after any result.

**Proposed changes, each for Kanav's explicit approval (C8):**

| Item | v1 text (`P6_M10_MODEL_SPEC.md` §5) | Proposed v2 | Why it is necessary |
|---|---|---|---|
| **G4 fit isolation** | "fit rows only from 2024–2025, and every fit row strictly before every evaluated row" | "base-fit rows only from 2024–2025 **and calibrator-fit rows only from 2026**; every fit row strictly before every evaluated 2027 row" | v2 has a second fit set |
| **Evaluation population** | "held-out 2026 EPA-complete qualification matches in the same D18 frame" | "2027 EPA-complete qualification matches of official events, in a **2027 D18 frame** built by the same procedure (`ml.dataset.builder.build_training_frame` with the D18 provider over the pinned 2027 EPA source), its content hash recorded" | 2026 is observed; the existing frame has no 2027 rows |

**Exclusions, unchanged:**
- ties (as M7);
- matches the model cannot score: a §1 input absent, including no causal scale.

`prediction_season_absent` cannot occur for frame rows.

**Reported, not gated:**
- log-loss, Brier and ECE;
- the paired log-loss vs M6/M7 `d18` on the same rows (event bootstrap, 2,000 resamples, seed 20261005, as v1);
- raw-v1 metrics on the same rows;
- per-group calibration slopes and counts.

## 6. 2027 acceptance run (C10). Once only

**Population:** §5 (the proposed v2 text). Inputs are the v1 §1 inputs at each match's `as_of`, with D18 EPA from strictly earlier concluded events. Groups come from §2 only.

**Pins, verified before any data is read** (any mismatch is refused):
- the base sha256 `aded2c82…`;
- the calibrator sha256 from `p6_m10b_pins.json`;
- this spec's frozen blob;
- M6/M7 via `load_m6m7`;
- the 2027 EPA source record (`p6_px1b_epa_source_2027.json`: manifest and chain sha256, covers 2027);
- the 2027 frame's content hash, in a committed write-once frame record.

**Ordering evidence:** the commit that added `p6_m10b_pins.json` must be a **strict ancestor** of the commit that added the 2027 frame record. Local git commit times are self-asserted (`P6_PX1B_REGISTRATION_EVIDENCE_AUDIT_2026-10-10.md`).

**Authorization (C10):** `decisions/p6_m10b_authorization.json`, written by Kanav, with:
- `authorized: true`, `authorized_by`, `date`;
- `scope: "P6-M10b"`, `season: 2027`;
- `season_complete_and_synced: true`;
- `spec_blob` (this spec's frozen blob).

**Prerequisites:**
- this spec frozen;
- DEV-M10b proceeded;
- the calibrator pinned;
- 2027 complete and synced;
- the pinned 2027 EPA source;
- the 2027 frame;
- the authorization file.

No 2027 ruleset is needed (qualification only).

**Run-once and write-once:**
- the record is `results/p6_m10b_outcome_model.json`;
- the run refuses if it exists;
- `write_once` never overwrites;
- all checks run before any data is read.

**On a fail:** D9 applies. v2 is recorded `not_validated`, and a further version needs an untouched population (2028).

## 7. Served status and the serving switch (C9, C11)

| Case | `validation_status` when v2 is served |
|---|---|
| Baseline strategy for both alliances, no coach observations, qualification context | `validated` only if the §7 guard passes; otherwise **v1 stays served** with `not_validated` (`p6_m10_gate_failed`) |
| Any non-baseline strategy | `not_validated` (`strategy_effect_unmeasured`), plus `insufficient_data` for defense/feeding roles (P6-Q11, P6-Q12) |
| Any coach observation applied | `not_validated` (`coach_observation_effect_unmeasured`) |
| Playoff context | refused (`playoff_model_unavailable`), as v1 |

**Display (P6-A5), unchanged:** "<5%" and ">95%" at the ends, otherwise the 0.05 step. The internal probability is never clamped.

**Serving-switch guard (C11),** enforced in the code that selects the served strategy model. v2 replaces v1 **only if all hold**:
1. `results/p6_m10b_outcome_model.json` exists with `passed: true`.
2. Kanav's confirmation `decisions/p6_m10b_confirmation.json`:
   - `confirmed: true`, `confirmed_by`, `date`;
   - `record: "p6_m10b_outcome_model.json"`;
   - `record_sha256` equal to that file's sha256.
3. A **passing P6-M13 parity rerun on v2**, `results/p6_m13_parity_audit_m10b.json`:
   - `p6_dm2_met: true`;
   - the audited model identity equal to v2 (base sha256 + calibrator sha256);
   - the P6-DM2 procedure unchanged.

**If any of these is missing or mismatched:** v1 is served with its current status. The guard is never bypassed by configuration.

## 8. Tests

**Executable now; specification checks with no production code:** `tests/test_phase6_m10b_spec.py`.
- gate-constant preservation;
- the §1 stable log-odds formula: finite, monotone, exactly antisymmetric, and no clipping ties;
- G3-style symmetry across a;
- within-match ordering and tie-break against the real v1 `StrategyEngine` sort key.

**Pre-registered, implemented with the code once this spec is frozen and implementation is authorized:**

| Id | Test |
|---|---|
| T-GROUP | group assignment for `same` / `prior` / `mixed`; refusal on an absent `prediction_season`, an unresolvable source or a later-season source; strategy and observations do not change the group |
| T-FIT | refusal at either bound, on a failed or non-converged optimizer, on a non-stationary point, and on a flat (non-unique) objective; fallback to a_G when n_g < 200; determinism |
| T-WRAP | calibration applied inside the single evaluation function for both the AI and coach paths; ordering, tie-break and symmetry through the real engine |
| T-GATE | the unchanged gate function and constants are used; G4 checks both fit sets |
| T-RUN | each prerequisite refused; pins, ordering evidence, run-once and write-once |
| T-SERVE | the switch refuses with no record, `passed: false`, no or mismatched confirmation, no parity rerun, or a parity rerun on another model identity; it serves v2 only with all three |

**Runtime:** every test and run is within the 45-minute limit. DEV-M10b and the FINAL run are closed-form plus 1-D fits on about 12k–15k rows, a few minutes at most.

## 9. Remaining items for Kanav

1. Approve the §5 changes to G4 and the evaluation population (C8).
2. Approve the §3 numerical constants: bounds [0.05, 5.0], `xatol` 1e-10, stationarity 1e-8, convexity 1e-12, n_min 200.
3. Approve the §7 guard's parity-record name and identity rule.
4. Then approve this exact blob to freeze it. Implementation authorization is separate.
