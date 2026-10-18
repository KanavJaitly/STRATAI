phase: 7
branch: phase7/m0-spec (from main 4290a3d); nothing committed (commits wait for Sven's authorization)
current_milestone: P7-M9
status: ACCEPTED CONDITIONALLY at phase level by Sven Morais, 2026-10-18 (decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md). P7-M8 and the environment-of-record suite portion of P7-M9 are DEFERRED; P7-DM1 NOT met; P7-DM2 control in place, not yet routinely enforced. NOT full milestone completion
current_stage: Phase 7 conditionally accepted; deferred work open (risk register R1-R17); commit awaits explicit authorization
resume: (1) commit authorization; (2) P7-Q5 environment of record -> run the P7-M8 capture runbook (docs/phase7.md 'Examples'), remove the xfail, run the suite there, record it; (3) Phase 6 dependencies (P6-M1 rulesets + PX gates; PX records naming artifacts). Phase 8 only on explicit instruction, after the commit
spec: docs/P7Milestones.md (revision 2, FROZEN 2026-10-17; blobs in P7_M0_FREEZE.md)
decisions: .agent/phase7/P7_M0_DECISIONS.md (approved by Sven Morais 2026-10-17; P7-Q1..Q13 decided; R1..R19)
completed: [P7-M0, P7-M1, P7-M2, P7-M3, P7-M4, P7-M5, P7-M6, P7-M7]  # P7-M8 BLOCKED; P7-M9 awaiting human acceptance
accepted:
  - P7-M0: FROZEN 2026-10-17 (Sven Morais). Freeze record: P7_M0_FREEZE.md
  - P7-M1: ACCEPTED 2026-10-17 (M01_ACCEPTANCE.md)
  - P7-M2: ACCEPTED 2026-10-17 (M02_ACCEPTANCE.md)
  - P7-M3: ACCEPTED 2026-10-17 (M03_ACCEPTANCE.md); real-model check BLOCKED (environment)
  - P7-M4: ACCEPTED 2026-10-18 (M04_ACCEPTANCE.md)
  - P7-M5: ACCEPTED 2026-10-18 (M05_ACCEPTANCE.md); real P6-M10 artifact checks BLOCKED (environment)
  - P7-M6: ACCEPTED 2026-10-18 (M06_ACCEPTANCE.md); real output DEFERRED with P6-DM1 (P7-Q1)
  - P7-M7: ACCEPTED 2026-10-18 (M07_ACCEPTANCE.md); real-model output BLOCKED (environment)
  - P7-M8: NOT accepted; BLOCKED (environment), deferred by the phase decision (M08_ACCEPTANCE.md)
  - P7-M9: verifiable scope complete; environment-of-record suite deferred (M09_ACCEPTANCE.md)
  - PHASE 7: ACCEPTED CONDITIONALLY at phase level, Sven Morais 2026-10-18 (decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md)
blocked:
  - P7-M8 real examples: BLOCKED (environment, P7-Q5) (M08_ACCEPTANCE.md)
  - real-model checks P7-M3/M5/M7 and the P7-M9 full suite in the environment of record: BLOCKED (environment, P7-Q5)
human_decisions_required:
  - P7-Q5 environment of record: model registry folders ranking_xgb_v2/d18, win_prob_xgb_calibrated/d18, strategy_outcome_component/p6m10-v1; serving DB dump (migrations through 0011); production EPA source config/files
known_risks:
  - model-backed routes return model_not_loaded on Sven's machine (no ml_registry/, no ML_* pins)
  - local DB is an older snapshot (191 events; migrations to 0009; no 2025 data)
  - contract tests pin route sets and frozen P6 blobs (see PHASE_PLAN.md)
  - P6 acceptance (dependency) awaits Kanav's confirmation per its own record
pre_existing_issues:
  - P5 portability defect: p5_m2_adoption.json evidence_sha256 computed over CRLF bytes; test passes only on Windows checkouts (outside Phase 7 scope)
unresolved_issues: []
post_freeze_decisions:
  - P7-D1 (2026-10-17): no future as_of on the P7-M3 POST routes (decisions/P7_D1_NO_FUTURE_AS_OF.md)
  - P7-D2 (2026-10-18): discovery corrections (decisions/P7_D2_DISCOVERY_CORRECTIONS.md)
  - P7-D3 (2026-10-18): strategy corrections (decisions/P7_D3_STRATEGY_CORRECTIONS.md)
  - P7-D4 (2026-10-18): Mid-Phase Audit: no future as_of on any route; state_province; non-nullable strategy model identity (decisions/P7_D4_MID_PHASE_AUDIT.md)
  - P7-D5 (2026-10-18): alliance selection corrections, incl. one P6 engine fix (infeasible instead of assert) (decisions/P7_D5_SELECTION_CORRECTIONS.md)
  - P7-D6 (2026-10-18): Phase-Level Audit: min(now, scheduled_time) on scheduled-match routes; examples tooling under API_PREFIX (decisions/P7_D6_PHASE_AUDIT.md)
  - P7-D7 (2026-10-18, approved by Sven Morais): canonical playoff label validated_playoff_success for the pick list's event-level values; applied and relocked (decisions/P7_D7_PLAYOFF_LABEL.md)
risks_for_phase_audit:
  - scheduled_time as the availability proxy for results (shared with the feature assembler): late events, corrected scores
  - M1 erratum: vacuous route walks under FastAPI 0.141 (fixed 2026-10-18; criteria re-verified)
  - recommend latency grows ~0.025 s per coach observation at the event; >~300 would exceed the 10 s budget; unbounded
  - write-once results need a committed tree: p7_m5 latency record pending commit authorization
  - human-input routes unlocked: decide at P7-M9 (lock or document as unstable)
  - PX gate records carry no artifact sha256s: the pick list refuses even after gates pass until a record binds them (P7-D5 item 2)
  - pre-match report cost: two full recommendations + features built three times per report
  - round-3 adversarial review for M6/M7 did not run (org spend limit); rounds 1-2 complete
baseline:
  date: 2026-10-17
  where: Sven's machine, isolated stratai_test (cloned from local serving), main 4290a3d
  pytest: 2019 passed, 5 failed, 5 skipped (6.3 min)
  failures:
    - test_ml_features_score_breakdown::test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score (environment: local DB has no 2025 matches)
    - test_phase5_contract::test_p5_d3_adoption_record_matches_the_served_status_and_its_evidence (pre-existing P5 portability defect, see above)
    - test_phase6_rulesets::test_m1_reproduction_path_runs_on_real_events_with_injected_rulesets (environment: no real playoff events in local DB)
    - test_phase6_rulesets::test_m1_counts_ruleset_exclusions_and_records_the_variant_applied (environment: same)
    - test_phase6_rulesets::test_m8_future_playoff_sentinel_changes_no_selection_moment_input_and_is_removed (environment: reads C:/Dev/StratAI-artifacts Statbotics snapshot)
  mypy: not configured
  ruff: not configured
last_verification:
  date: 2026-10-18 (after P7-D7)
  pytest full: 2483 passed, 5 failed (same 5 as baseline), 5 skipped, 1 xfailed (strict, P7-M8 BLOCKED); pytest exit 1 from baseline failures only; 0 regressions (raw log local only, excluded from the commit)
  contract lock check: pass (24 operations; P7-D7 relock recorded)
  frozen blobs: P7Milestones 61de5046…, P7_M0_DECISIONS 548c28c6… (unchanged); docs/P6Milestones.md unchanged vs main
last_checkpoint: Phase 7 conditionally accepted (approval recorded verbatim); uncommitted
