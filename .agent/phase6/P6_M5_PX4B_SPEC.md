# PX-4b (versioned PX-4 on PX-1b + PX-2b): frozen specification, version 1 (2026-10-08)

**Frozen by the commit that introduces this file, before any PX-4b input or outcome exists.** A change is a new version, written before the run it governs.

**Authority:**
- D9 decision v1, proposal C2;
- approved by Kanav on 2026-10-08 (`decisions/P6_D9_PX1B_APPROVALS_C0_C4_2026-10-08.md`).

**What it replaces, and what it leaves alone:**
- It versions P6-M5 / P6-Q5 for PX-1b.
- The frozen PX-4 (P6-M5, held-out 2026) is unchanged and stays blocked.

## 1. Prerequisites (all required; the harness refuses otherwise)

1. PX-1b is accepted (`P6_M3_PX2B_SPEC.md` §1.1: FINAL-1 passed, plus Kanav's sha-matched confirmation).
2. `results/p6_px2b.json` exists with `passed: true`, together with its saved calibrator.
3. `results/p6_m1_ruleset_check_2027.json` (C0) exists, and an approved 2027 ruleset exists.

## 2. Population

**Intended population:** 2027 events whose bracket P6-M1 (C0 record) reproduces.

**Exclusions, each excluded and counted with its alliance count, never silently dropped:**
- **C2:** an event whose selection-time alliances are not all three members (FIRST Championship divisions), or whose listing the rules do not explain.
- **Leakage:** an event with any playoff match scheduled before its selection moment, counted as `playoff_before_selection_moment`. This is the same rule as PX-1b §1.

The intended and validated populations are both recorded.

**Sampling.** Every validated event is used: exact computation is cheap. If a run is projected to exceed 45 minutes, a seeded, stratified sample is fixed by a dated pre-run record **before** the run (P6-Q13).

## 3. Probabilities

- **Inputs:** for each event, the actual selection-time alliances (D-PX1-1 members) and selection-moment features.
- **Simulator:** the PX-3 exact simulator (`field_outcome`) on the event's approved bracket.
- **Candidate:** match probabilities = PX-2b-calibrated PX-1b (`px1b-v1` + `px2b_calibrator.json`).
- **Seed-only baseline:** the same simulator with the registered `playoff_px1b_seed_only` `px1b-v1` (the seed difference alone, fit on the same 2024–2026 rows as PX-1b), uncalibrated.
- **Insufficient data:** an event with an absent input is excluded and counted as `insufficient_data`.

**Labels:** winner and finalist seeds from the C0 2027 record.

## 4. Gate (P6-Q5, unchanged)

- **Requirement:** for **each** of P(win event) and P(reach finals), held-out 2027 log-loss strictly better than seed-only.
- **Test:** the paired event-bootstrap 95% CI of the per-alliance difference (PX-4b − seed-only) entirely below 0 (2,000 resamples, seed 20261010).
- **Reported, not gated:**
  - Brier score;
  - reliability bins (10 equal-width bins: count, mean predicted, observed rate).

## 5. Outcome, records and limits

- **Pass:** PX-4b's playoff-success probabilities may be served as `validated_playoff_success`, with the scope stated.
- **Fail:** `not_validated`, and D9 applies.
- **Record:** `results/p6_px4b.json`, write-once: commit, this spec's blob, population, counts, both gates, runtime.
- **Runtime:** one run, within the 45-minute budget.
- **Not changed after a result.**
