# D9 decision, version 1: PX-1b as the candidate replacement for PX-1 (2026-10-08)

**Policy (Kanav, 2026-10-08):** PX-1b may be recognized as the candidate replacement playoff model for future evaluation. It **must not be treated as accepted today**. PX-2, PX-4 and P6-M8 remain blocked wherever their frozen dependencies require a validated playoff model.

**Parts of this record:**
- **Part A:** records that policy.
- **Part B:** states what follows from the frozen specifications.
- **Part C:** sets out the proposals that need Kanav's **explicit approval before any execution**. A proposal is not adopted by being written here.

**What this record does not change:**
- P6-Q3, the PX-1 specification (`P6_M2_PX1_SPEC.md`, blob `24b427f2…`) or its amendment A1;
- the PX-1b specification (`P6_M2_PX1B_SPEC.md`, blob `80201eb0…`, frozen at `ca13e98`);
- the D9 rule;
- any result;
- any code. `scripts/phase6_playoff_track.py` still requires a passing `p6_m2_px1.json` before PX-2.

## Part A: status today

| Model | Status | Evidence |
|---|---|---|
| **PX-1** | **`not_validated`** under its original frozen protocol. Both runs FAILED the P6-Q3 gate | `p6_m2_px1.json` (run 1); `p6_m2_px1_rerun1.json` (after two defect fixes); `P6_M2_PX1_FAILURE.md`; `decisions/P6_PX1_NOT_VALIDATED_2026-10-08.md`; `decisions/P6_PX1_AUDIT_DEFECTS_2026-10-08.md` |
| **PX-1b** | **Frozen candidate; development-only evidence; NOT accepted.** Recognized as the candidate replacement for future evaluation (this record) | Spec v1 (`ca13e98`); DEV-1 (2024 → 2025) `p6_px1b_dev.json`: DV1 and DV2 met, a development result only; final candidate `p6_px1b_final_fit.json` (`px1b-v1`, fit 2024–2026, fingerprint `52a4d7f0…`); FINAL-1 **not evaluated** |

**PX-1b's status today does not satisfy any prerequisite.**
- DEV-1 is not an acceptance test.
- 2026 is not a PX-1b holdout: it is PX-1b's training data and was already observed for PX-1.

## Part B: conditions for PX-1b to become the accepted replacement prerequisite

**All of these are required:**
1. **FINAL-1 is run once, exactly as PX-1b spec §6 freezes it.**
   - **Candidate:** the registered `playoff_px1b` / `playoff_px1b_seed_only` `px1b-v1`, unchanged.
   - **Rows:** held-out **2027** rows built under spec §1, including the `playoff_before_selection_moment` and `scale_absent` exclusions, each counted.
   - **Run:** once, after the 2027 season's events are complete and synced, on Kanav's instruction.
2. **FINAL-1 passes against the frozen baselines** (the P6-Q3 form, unchanged). PX-1b's held-out 2027 log-loss must be strictly better than **both** of:
   - (a) M6/M7 `win_prob_xgb_calibrated` `d18` (registry sha256 `c76d3299…`), applied to the same selection-moment features;
   - (b) the seed-only comparator `playoff_px1b_seed_only` `px1b-v1` (the seed difference alone, fit on the same 2024–2026 rows).

   For each comparison, the paired event-bootstrap 95% CI of the difference must lie entirely below 0 (2,000 resamples, seed 20261010).
3. **FINAL-1's prerequisites exist before the run.**
   - (a) 2027 playoff data in the isolated database;
   - (b) an approved 2027 P6-M1 ruleset, entered from the 2027 manual and approved by a named, qualified reviewer;
   - (c) the P6-M1 reproduction check for 2027 events: an extension of `run_m1`, needing its own approval (proposal C0);
   - (d) a D18 EPA source covering 2027.
4. **Kanav's dated confirmation of the FINAL-1 record.** The record must be provenance-complete, with no open defect.
   - Only then does PX-1b become the accepted replacement prerequisite.
   - Even then, it is a prerequisite only for the **versioned** dependent specifications in Part C, never for the frozen PX-1-based ones.

**If FINAL-1 fails:** D9 applies.
- PX-1b is recorded `not_validated`.
- The playoff track stays stopped.
- A further replacement needs a new versioned specification and a new untouched holdout (2028 or later).

## Part B (continued): consequences for PX-2, PX-4 and P6-M8

**Before PX-1b acceptance (today):**

| Milestone | Frozen dependency | Status |
|---|---|---|
| **P6-M3 PX-2** | depends on P6-M2 (P6-Q3 pass); P6-Q4 calibration slice = the last 20% of **2025**; gate on **2026** | **BLOCKED** (D9): PX-1 failed. PX-1b cannot stand in, since the frozen PX-2 is defined on PX-1 and on 2026 |
| **P6-M5 PX-4** | depends on "P6-M3 passed", P6-M4; P6-Q5 held-out **2026** | **BLOCKED** (D9) |
| **P6-M8 / P6-DM1** | depends on P6-M5 and P6-M7; P6-Q1 population = held-out **2026** events; dated pre-run record (`36b52c7`); named-mentor review | **BLOCKED** (D9). Mr. Biery's agreement and review are **outstanding** and must not be presumed |

**Also unchanged:**
- P6-M7's playoff probabilities and playoff-context strategy odds stay `not_validated`.
- **P6-M10 remains FAILED** (its own gate); PX-1b does not affect it.
- P6-DM1 is not met. Phase 6 and M14 are incomplete.

**After PX-1b acceptance (Part B conditions 1–4 met), PX-2, PX-4 and M8 still cannot run under their frozen specifications:**
- Each frozen spec names PX-1.
- Each evaluates on **2026**. 2026 is inside PX-1b's training data and is not independent of it: PX-1b's final fit used 2026 playoff outcomes, so an M8 or PX-4 evaluation on 2026 events would be in-sample.
- Running them therefore requires the versioned specifications proposed in Part C, each frozen **before** any 2027 outcome is evaluated and each explicitly approved.

## Part C: proposals (NOT adopted; each needs Kanav's explicit, dated approval before execution)

| Id | Proposal | Why it is needed |
|---|---|---|
| **C0** | Extend P6-M1's reproduction check (`run_m1`) to 2027 events, under the same frozen rules | FINAL-1 condition 3(c); the frozen M1 record covers 2024–2026 only |
| **C1: PX-2b** | A versioned PX-2 spec on PX-1b. The P6-Q4 constants are unchanged (ECE < 0.05; 10 bins; per-bin exact Poisson-binomial test, ≥ 30 per bin; Holm α = 0.05; symmetry 1e-12; fit isolation). **Calibration slice = the temporally last 20% of 2026 eligible playoff matches** (inside PX-1b's training period, as G4 allowed for the original). **Gate on held-out 2027.** Prerequisite: an accepted PX-1b | The frozen P6-Q4 is defined on PX-1, a 2025 slice and a 2026 gate |
| **C2: PX-4b** | A versioned PX-4 spec: the P6-Q5 gate unchanged (P(win event) and P(reach finals) vs seed-only, log-loss, event-bootstrap CI excluding 0) on **held-out 2027 events**, with PX-1b + PX-2b probabilities. Prerequisite: PX-2b passed | The frozen P6-Q5 holdout is 2026 |
| **C3: P6-M8b** | A versioned P6-DM1 run: the P6-Q1 definition unchanged (winner and finalist; captain plus at least one pick among the top 2 contenders; > 50% pooled; event-bootstrap CI; raw-EPA-draft and actual-seed baselines), on a seeded, stratified population of **2027 events**. It needs a **new dated pre-run record** (P6-Q13) written before any result, and the review of a **named mentor whose agreement is confirmed**. Prerequisite: PX-4b passed | The frozen P6-Q1 population is 2026 events, now in PX-1b's training data. The existing M8 pre-run record names 2026 |
| **C4: harness** | Point the playoff-track prerequisites at PX-1b's records and registry tag only for the C1–C3 runs, keeping the frozen PX-1 chain intact | Today's code requires `p6_m2_px1.json` passed and loads `px1-v1` |

**Order and timing.**
- C1–C3 must be written and frozen **before** any 2027 outcome is evaluated.
- C0 and C4 are code changes made under those approved specs.
- None of C0–C4 is implemented by this record.

## Approvals still needed (explicit, dated)

1. **Confirmation of this record as D9 decision v1.** It reflects the stated policy; confirming it adopts Parts A and B as written.
2. **C0–C4,** each individually, before any work on it.
3. **At FINAL-1 time:** confirmation of the FINAL-1 record (Part B, condition 4).
4. **For C3:** a named mentor's confirmed agreement (Mr. Biery is proposed, not confirmed), and that mentor's review.
