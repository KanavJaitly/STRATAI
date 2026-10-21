# Audit of the P6-M10b draft spec (2026-10-10): corrections proposed, not applied

**Audited:** `.agent/phase6/P6_M10B_SPEC_DRAFT.md`, blob `b9dea322dc71a8901e58a32686eacd2a0de7d091` (`a035af6`). The draft is **not modified**.

**Compared against:**
- `P6_M10_MODEL_SPEC.md` (blob `5f838613…`);
- `ml/strategy/engine.py`, `ml/strategy/outcome.py`, `ml/calibration/gate.py`, `ml/features/assembler.py`.

**No fit, evaluation or registration.** The M10 v1 records are untouched (single commits).

## 1. Strategy ordering

**How STRATAI uses M10:** every ranking or comparison happens **within one `MatchContext`**, meaning the same six teams and the same side.
- `StrategyEngine.recommend`: `assessed.sort(key=(-p_ours, changes_from_baseline, canonical_json))`.
- `StrategyEngine.compare`: two strategies, same context.
- `compare_odds(best, baseline)`: same context.

No HTTP strategy route exists (P6-A1), and no code ranks M10 probabilities across matches. (M12 and M13 pool metrics across matches; they do not rank.)

**The group is a property of the six teams' EPA sources, never of a strategy.** So all candidates in a context share one a_r, and q = σ(a_r·z) is strictly increasing in the probit index x = m/s.

| Comparison | What the calibrator can do |
|---|---|
| **Within a context** (everything presented) | **No reversal** of any strictly ordered pair, in exact arithmetic |
| **In floating point** | Pairs can only **collapse to a tie** where q saturates (within about 1e-16 of 0 or 1). The existing deterministic tie-break then applies. v1 already has the same saturation (p = 1.0 exactly once \|m/s\| ≳ 8.3) |
| **Across contexts, under C-R** | Predictions from different groups **can** reorder (the intended correction). Nothing in STRATAI presents such an ordering. Under C-G no reordering occurs |
| **The displayed odds difference** (recommended vs baseline) | It **changes size**: multiplied in log-odds by a_r (about 1.0–1.3). That is not inflation in the P6-DM2 sense, because the same function serves the AI and the coach. But non-baseline strategy effects are unmeasured (`strategy_effect_unmeasured`), so the larger shown difference must stay labelled `not_validated` |

**Draft error:** §1 says "a_r > 0 keeps the ordering, so strategy rankings are unchanged". That is true only within a context, and only up to floating-point saturation. **Correction C1** below.

**Additional defect:** the draft clips p to [1e-12, 1 − 1e-12] before the logit. M10's p = Φ(m/s) passes 1e-12 once |m/s| ≈ 7. Clipping would **create** ties among lopsided candidates that v1 ranks strictly, which can change the recommended strategy. **Correction C2:** compute z from x directly, without clipping.

## 2. Group definitions (prediction-time only)

- **The draft is underspecified.** `TeamFeatures` carries `epa_source_event_key` but **not** the prediction's own season or event.
- **Correction C3:** the group must take the prediction's season as an **explicit input**, the season of the event the context is assembled for, and refuse without it.
- **No missing case is reachable.** v1 already refuses (`insufficient_data`) whenever any team lacks an EPA component, `epa_scale` or `score_scale`. `epa_scale` is `None` when the source key is missing, or when it is a later season (`ScaleLookup.feature_scales`). So whenever M10 predicts, all six source keys resolve to a season.

## 3. Calibration fit (proposed exact text, C4)

- **Fit target:** z = log Φ(x) − log Φ(−x) (`scipy.special.log_ndtr`), finite and strictly increasing. a_r minimizes the mean log-loss of σ(a·z) over the group's calibration rows, with ties excluded.
- **Bounds and uniqueness:** a ∈ **[0.05, 5.0]** (closed). The loss is convex in a, so the minimizer is unique. It is found by bounded scalar minimization with tolerance 1e-10. **A solution at a bound is refused** (a mis-specification signal for Kanav) and never clipped silently.
- **Symmetry:** with no intercept, q(1−p) = 1−q(p) exactly. The objective is invariant under (z, y) → (−z, 1−y), so perspective augmentation would give the identical a.
- **Fallback:** decided only by the **calibration set's** per-group counts. A group with < 200 rows uses a_G, fit by the same rule on all calibration rows. It is deterministic and can never consult acceptance outcomes. 2026 counts are 5,439 / 4,132 / 2,644, so no fallback is expected.

## 4. Development check

**Confirmed:** it is diagnostic only, never independent acceptance evidence (2026 motivated the design), and its rule is fixed before it runs.

**Two corrections:**
- **C5, the proceed rule:** "fewer G2-rejected bins" is impossible to meet if raw already has 0. Proposed rule: calibrated G2 rejections ≤ raw, and strictly fewer unless raw has 0; and ECE ≤ raw ECE.
- **C6, scope:** state that DEV tests the **procedure** (a base fit on 2024 only), not the v2 artifact.

## 5. Acceptance gates

**Preserved:** G1 (ECE < 0.05), G2 (10 bins, ≥ 30 per bin, exact Poisson-binomial, Holm α = 0.05) and G3 (≤ 1e-12, order independence).

**Corrections:**
- **C7, cite the function:** cite `ml.calibration.gate.evaluate_calibration_gate` unchanged, including `MIN_ELIGIBLE_BINS = 2` and `TIE_TOLERANCE = 1e-7`.
- **C8, flag two changes the draft calls "unchanged":**
  - **G4:** v1 reads "fit rows only from 2024–2025, every fit row before every evaluated row"; v2 must admit 2026 calibration rows;
  - **the population:** v1 reads "held-out 2026 … in the same D18 frame". v2 needs 2027 rows in a **new frame**, built by the same procedure from the pinned 2027 EPA source, with its content hash recorded.

  Both are necessary, and must be stated as **changes for approval**.
- **C9, restate the served-status table:** restate v1 §6 for v2. Baseline odds become `validated` only after a gate pass + confirmation + parity rerun. Non-baseline strategies, coach observations and playoff contexts are unchanged. Display (P6-A5) is unchanged.

**Unchanged:** the original failure record (`30dcf55`).

## 6. 2027 acceptance (confirmed, with additions)

**Population:** 2027 official-season, EPA-complete, qualification matches. Ties and `model_input_absent` are excluded and counted; early-season matches without a causal scale fall into the latter.

**Point in time:** v1 §1 inputs at each match's `as_of` (D18 EPA from strictly earlier events); the group from source keys only.

**Required pins:**
- the base sha `aded2c82…`;
- the calibrator sha (registered and pinned before any 2027 data);
- the spec blob;
- M6/M7 via `load_m6m7`;
- the 2027 EPA source (the same record as PX FINAL-1);
- the 2027 frame content hash.

**Ordering:** the calibrator's pin commit must be a strict ancestor of the commit that records the 2027 frame (the git-time limitation applies).

**Write-once and run-once:** `p6_m10b_outcome_model.json`; a second run is refused.

**Prerequisites:**
- 2027 complete and synced;
- the pinned 2027 EPA source;
- the 2027 frame;
- **Kanav's run authorization** (C10: add a decision file, as for FINAL-1).
- No 2027 ruleset is needed (qualification only).

**After a pass, mandatory before v2 replaces v1 in serving:**
- Kanav's dated, sha-matched confirmation;
- **and** a passing P6-M13 parity rerun on v2.

The draft says "only after"; **C11** makes the serving switch refuse in code without both.

## Recommendation: C-R, with corrections C1–C11

| | C-R (per group) | C-G (global) |
|---|---|---|
| **Fixes the group mixture** | yes. Same / mixed / prior slopes on 2026 are 1.32 / 1.00 / 0.96 (training: 1.43 / 1.20 / 0.90) | no. A global factor of about 1.11 would leave same-season under-confident and push prior-season over-confident |
| **Presented ordering** | within context: identical to C-G | within context: identical |
| **Cross-context ordering** | can change (intended; not presented) | unchanged |
| **Parameters** | 3, each with ≥ 2,600 rows | 1 |
| **Transfer risk** | per-group factors drifted between seasons (see above) | the global factor drifted (1.27 → 1.11) and depends on the group mix |

Both bet that 2026's mapping carries over to 2027. **C-R is recommended:** it targets the strongest measured effect at negligible variance cost, and its only ordering difference is not presented.
