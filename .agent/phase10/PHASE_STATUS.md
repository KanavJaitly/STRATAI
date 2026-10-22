phase: 10
branch: phase8/build at 45859dc. Nothing staged or committed; no Git publication authorized
status: IN PROGRESS (2026-10-21). Phase 9 is conditionally accepted (Sven Morais, 2026-10-20), and Phase 10 is authorised
spec: docs/P10Milestones.md revision 1, RATIFIED by Sven Morais 2026-10-21 (criteria unchanged; decisions/P10_HUMAN_DECISIONS_2026-10-21.md). Blobs in P10_M0_FREEZE.md, rechecked 2026-10-21: unchanged
decisions:
  - P10_M0_DECISIONS.md (P10-Q1..Q8)
  - decisions/P10_D1_CONNECTION_POOLING_PROPOSAL_2026-10-21.md (the proposal)
  - decisions/P10_HUMAN_DECISIONS_2026-10-21.md (Sven: B as an experiment; P10-Q9 approved; spec ratified)
  - decisions/P10_D1_EXPERIMENT_RESULT_2026-10-21.md (B REJECTED on criteria 1a/1b/2; option A retained)
milestones:
  - P10-M0: spec, decisions and baseline recorded (working freeze)
  - P10-M1: IMPLEMENTED and verified locally; NOT fully accepted (failing-first evidence only partly recorded). 413 declared (P10-Q9, relocked additively) (M01_ACCEPTANCE.md)
  - P10-M2: criteria MET on local evidence (5 of 5 H4.1 runs pass) with recorded limitations (M02_ACCEPTANCE.md)
  - P10-M3: profiling COMPLETE; option-B experiment REJECTED, option A retained (M03_STATUS.md)
  - P10-M4 (three-season backtest, calibration), M5 (alliance selection vs playoffs), M6 (defense/feeding spot checks): BLOCKED (P10-Q2..Q4); not started
  - P10-M7: docs/phase10.md started; audit and acceptance not yet done
done_means:
  - P10-DM1 (three seasons backtest cleanly): NOT MET, BLOCKED (no 2022/2023 data or support, no models)
  - P10-DM2 (calibration holds across seasons): NOT MET, BLOCKED (and P4-M7 already failed on 2026)
  - P10-DM3 (survives a simulated event without stale data or crashes): MET for the local configuration only. The production configuration (models, D18/live EPA) is CARRIED to the environment of record
reviews: reviews/R1_M1_M2_ADVERSARIAL_2026-10-21.md (13 findings + the suspend finding; all accepted)
trials: runs/m2_trials/TRIAL_INVENTORY.md (every run; 4 VM-suspended runs are environment-invalid), runs/m2_h4/, runs/m2_h41/
final_checks (2026-10-21):
  backend (latest, option A restored, P10-Q9 applied): exit 1; 2751 passed, 4 failed (the 4 identified baseline failures; 0 regressions), 5 skipped, 1 xfailed (runs/backend_final_p10_d1_restored.txt). NOT passing
  backend (previous): exit 1; 2750 passed, the same 4 failed (runs/backend_final_p10_m1m2.txt)
  focused: test_phase10_hardening 23, test_phase10_snapshot 12, test_phase10_stress_harness 17, test_database_connection 2 (all pass)
  frontend: vitest 173 passed exit 0, tsc 0, oxlint 8 baseline warnings, build 0 (no frontend change in Phase 10)
  contract: lock relocked for P10-Q9 (25 operations, 0 changed / 22 added leaves); check 0; types --check 0; zero-LLM static scan []
risks: RISK_REGISTER.md (P10-R1..R7, P10-Q9, the carried items)
environment_note: the ChromeOS VM suspends when the host sleeps; keep it awake for long runs (P10-R1)
