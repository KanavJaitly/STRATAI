# Phase 7 — conditional phase acceptance decision (2026-10-18)

**Status: APPROVED, conditional phase-level acceptance.** Approved by Sven Morais on 2026-10-18; his approval is
recorded verbatim in the Approval section at the end.
- Prepared by Claude Code at Sven's direction (2026-10-18: "Prepare Phase 7 for conditional phase-level
  acceptance, with M8 and the environment-of-record portion of M9 deferred"). It was then reviewed and approved by
  him.
- This is acceptance with deferred work, as with Phase 6's P6-DM1. It is NOT full milestone completion, and NOT
  fulfillment of every done-means criterion.
- MASTER_BUILD's Phase Acceptance Gate is not satisfied on its own terms, because P7-M8 is not accepted. The phase
  is accepted by this human decision, with that unmet item deferred.

## Governance basis
- **P7-M9 (frozen spec):** "Phase acceptance by Sven Morais or Kanav". Sven holds the same decision-making authority
  as Kanav for Phase 7 (P7_M0_DECISIONS.md, P7_M0_FREEZE.md).
- **prompts/MASTER_BUILD.md's Phase Acceptance Gate** requires every milestone to be accepted. P7-M8 is not, so
  the gate does not pass on its own terms. Only a human decision can accept the phase with a deferred milestone.
  Nothing in MASTER_BUILD lets the agent grant this.
- **Precedent:** `.agent/phase6/decisions/P6_PHASE_ACCEPTANCE_2026-10-17.md`. Phase 6 was accepted with P6-DM1
  deferred, by Kanav's decision. Its result records were left unedited, and the deferred work stayed open and owned.

## Decision (as approved)
**Phase 7 is accepted conditionally, at phase level.** P7-M8 and the environment-of-record portion of P7-M9 are
deferred. This is NOT full milestone completion, and NOT fulfillment of every done-means criterion.

**Milestones:**
- **P7-M0:** frozen (P7_M0_FREEZE.md). The frozen blobs are unchanged.
- **P7-M1 … P7-M7:** accepted on their recorded evidence (M01–M07_ACCEPTANCE.md). Their environment-dependent
  sub-checks stay OPEN:
  - M3: the real-model check;
  - M5: the real P6-M10 artifact checks;
  - M7: the real-model output.
- **P7-M6:** callable, and refusal-only. Its real output is deferred with P6-DM1 (P7-Q1). The playoff label is
  decided (P7-D7, approved 2026-10-18, applied and relocked).
- **P7-M8: BLOCKED, deferred, not accepted.** Real production examples have not been captured, and
  `docs/api_examples/` does not exist. The strict xfail
  `tests/test_phase7_examples.py::test_every_operation_in_scope_has_its_required_examples` remains until the capture
  runbook has run successfully.
- **P7-M9:** the documentation, contract-test, audit and review work is complete as far as it was verified locally
  (M09_ACCEPTANCE.md). Its environment-of-record full-suite requirement is DEFERRED with P7-M8, because it has the
  same blocker.

**Done-means:**
- **P7-DM1: NOT MET.** All seven core features are callable, but real documented examples are absent, and alliance
  selection is refusal-only under P6-DM1, as are playoff-context strategy odds.
- **P7-DM2: a contract-lock control exists.** `docs/api_contract_lock.json` covers 24 operations, it is pinned by
  `tests/test_phase7_contract.py`, and `python -m scripts.phase7_contract_lock check` exits 0. Routine automatic
  enforcement is NOT yet demonstrated: nothing is committed, and no CI runs it.

**Test evidence (isolated stratai_test on Sven's machine; not the environment of record):**
- Latest full suite before P7-D7: 2,483 passed, 5 failed, 5 skipped, 1 xfailed; **pytest exit code 1**. The suite
  is not passing.
- After P7-D7 (the latest): 2,483 passed, 5 failed, 5 skipped, 1 xfailed; **pytest exit code 1**. The counts are
  identical; 0 regressions.
- The 5 failures are the known baseline failures, each tracked separately:
  - `test_ml_features_score_breakdown::test_adapter_resolves_every_real_alliance_breakdown...`: no 2025 data locally;
  - `test_phase5_contract::test_p5_d3_adoption_record...`: the pre-existing Phase 5 CRLF hash defect (R16);
  - `test_phase6_rulesets::test_m1_reproduction_path...` and `::test_m1_counts_ruleset_exclusions...`: no real
    playoff events locally;
  - `test_phase6_rulesets::test_m8_future_playoff_sentinel...`: a Windows artifact path.
- The 1 xfail is the deliberate strict P7-M8 completeness check.
- Type check and lint are not configured.

**Open items, with owners (risk register R1–R17 in PHASE_ACCEPTANCE.md):**
- **Environment-dependent checks (R1; Sven / Kanav):**
  - provide the registry folders `ranking_xgb_v2/d18`, `win_prob_xgb_calibrated/d18` and
    `strategy_outcome_component/p6m10-v1`, sha256-verified against `.agent/production/d18_model_registration.json`
    and `.agent/phase6/results/p6_m10_fit.json`;
  - provide a serving-DB dump through migration 0011, and the production EPA configuration;
  - then run the "Examples (P7-Q4)" runbook in docs/phase7.md, remove the xfail, run the full suite in that
    environment, and record it.
- **Phase 6 dependencies:**
  - R4 (Kanav / a named FRC reviewer): approve the P6-M1 rulesets and run the PX gates;
  - R3 (P6 track owner): have the PX gate records name the evaluated artifacts;
  - P6 track owner: optionally align `scripts/phase6_playoff_track.py:542` with P7-D7.
- **R17 (Sven):** commit the work so the lock is the baseline. CI is outside Phase 7.
- **R6–R12:** platform hardening (Phase 10) and the Phase 5 game-manual filename defect. These are tracked, and
  were not fixed in Phase 7.

**What this decision does not change:**
- No acceptance record or test result is edited to say passed.
- Deferred and blocked items stay open with their owners.
- Nothing downstream may present alliance-selection or playoff probabilities as validated.

**Before Phase 8:** the label is decided (P7-D7). The work must be committed with the user's authorization before
frontend types are frozen against the lock. Phase 8 is not started.

## Approval (recorded verbatim, 2026-10-18)
Decided by: Sven Morais
Date: 2026-10-18

Decision: Approved, conditional phase-level acceptance.

I accept Phase 7 at phase level as set out in this record, with P7-M8 (real request/response examples) and the
environment-of-record full-suite portion of P7-M9 deferred. This is not full milestone completion and does not
constitute fulfillment of every done-means criterion.

- P7-M8 remains blocked until real production examples are captured in the environment of record and its strict
  xfail is removed.
- P7-DM1 is not met: real examples are absent, and alliance selection remains refusal-only under P6-DM1.
- P7-DM2 has a contract-lock control, but routine automatic enforcement has not yet been demonstrated.
- The latest full suite is 2,483 passed, 5 failed (the known baseline failures, tracked separately), 5 skipped, and
  1 xfailed, with pytest exit code 1.

Environment-dependent checks, the Phase 6 dependencies, the Phase 10 hardening items, and the Phase 5 game-manual
filename defect remain open, with the owners and follow-ups recorded in the risk register (R1–R17).

I confirm that I hold the same decision-making authority as Kanav for this approval.
