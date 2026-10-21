# Approvals of proposals C0–C4 (D9 decision v1, Part C): Kanav, 2026-10-08

**What was approved.** On 2026-10-08 Kanav approved all five proposals in `P6_D9_PX1B_REPLACEMENT_V1.md` Part C (C0, C1, C2, C3, C4), together, as one explicit, dated authorization. Each approval is recorded below in its own section, so its scope and restrictions stay auditable.

**Basis:** the proposals are quoted from D9 v1 Part C, which is unchanged.

**Restrictions on all five approvals:**
- **Preparatory work only.** None of them declares PX-1 or PX-1b accepted, bypasses D9, or authorizes any evaluation that its frozen prerequisites still block.
- **Freeze before outcomes.** Every new specification is frozen before the outcomes it governs are evaluated.
- **No 2026 holdout.** 2026 is never used as an untouched final holdout.
- **No weakening.** No acceptance criterion is weakened, and no frozen methodology is modified, to force a pass.
- **Unchanged statuses:** PX-1 is `not_validated`; PX-1b is an unaccepted candidate; P6-M10 is failed; Phase 6 and M14 are incomplete.
- **Operating limits:** the 45-minute limit; isolated `stratai_test` only; never the serving database or `.gitignore`; no push, merge or amend.

## C0: extend the P6-M1 reproduction check to 2027 events (APPROVED)
- **Scope:** prepare and test (synthetic data) a 2027 run of the existing P6-M1 check, `run_m1` restricted to season 2027.
- **Unchanged frozen rules:** exclusions, reproduction, the captain-rule check and the 10% escalation.
- **Record:** a separate write-once `p6_m1_ruleset_check_2027.json`. The 2024–2026 record is untouched.
- **Restrictions:**
  - The real 2027 run needs an approved 2027 ruleset (human-entered from the 2027 manual; a named, qualified reviewer) and 2027 playoff data. It refuses without them.
  - Nothing about 2027 rules is entered or inferred by this work.

## C1: PX-2b calibration specification (APPROVED)
- **Scope:** prepare and freeze `.agent/phase6/P6_M3_PX2B_SPEC.md`:
  - P6-Q4's constants unchanged;
  - the calibration slice is the temporally last 20% of 2026 eligible PX-1b playoff rows;
  - the gate is on held-out 2027;
  - the model is the frozen `px1b-v1`.
- **Restrictions:** PX-2b does not run before PX-1b is accepted: FINAL-1 passed, plus Kanav's dated confirmation (D9 v1 Part B).

## C2: PX-4b specification (APPROVED)
- **Scope:** prepare and freeze `.agent/phase6/P6_M5_PX4B_SPEC.md`:
  - P6-Q5's gate unchanged, for P(win event) and P(reach finals) vs seed-only;
  - log-loss, with the event-bootstrap CI excluding 0;
  - held-out 2027 events;
  - PX-1b + PX-2b probabilities.
- **Restrictions:** PX-4b does not run before PX-2b has passed.

## C3: P6-M8b specification (APPROVED)
- **Scope:** prepare and freeze `.agent/phase6/P6_M8B_SPEC.md`, preserving P6-Q1's DM1 definition unchanged, on a seeded, stratified sample of 2027 events.
- **Restrictions:**
  - **M8b does not execute** until all of these hold:
    1. PX-4b has passed;
    2. its own dated pre-run record exists, written and committed before the run;
    3. a named mentor's agreement is confirmed, in writing, in that record.
  - DM1 is decided only after that mentor's review of every miss.
  - Mr. Biery is the proposed mentor. His agreement and review are not confirmed and must not be presumed or fabricated.

## C4: PX-1b harness pointers (APPROVED)
- **Scope:** prepare the playoff-track harness so that the PX-2b, PX-4b and M8b runs point at:
  - PX-1b's acceptance records;
  - the `px1b-v1` registry entries;
  - the PX-2b calibrator;
  - the 2027 records.

  Test the pointers with synthetic data. The frozen PX-1 chain (`m3`, `m5`, `m8`, `m8-review`) stays the default, with its prerequisites unchanged.
- **Restrictions:** the pointers enforce every prerequisite above. Nothing in C4 runs a blocked evaluation.

## Still outstanding after these approvals

1. **Confirmation of D9 v1 as a whole.** Kanav approved Part C's proposals; confirming Parts A and B as written has not been stated separately.
2. **Every human input named in C0–C3:**
   - the 2027 ruleset and its review;
   - Kanav's dated confirmation of a FINAL-1 record;
   - the M8b pre-run record;
   - a named mentor's confirmed agreement and review.
