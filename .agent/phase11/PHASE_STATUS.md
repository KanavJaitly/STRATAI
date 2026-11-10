# Phase 11: status

```yaml
phase: 11
title: Live alliance selection (manual draft tracking and a dynamic picklist)
spec: docs/P11-P19Phases.md §5 (document status PROPOSED; Phase 11 started on the owner's instruction, 2026-11-04)
status: VERIFIED ON AN ISOLATED REAL-DATA COPY, NOT ACCEPTED (2026-11-09)
committed: >-
  2026-11-04 implementation on main (3757d2a). 2026-11-09 verification and fixes on branch phase11/verification
  (PR #44), committed and pushed on Sven's authorization; not merged.
current_stage: awaiting human acceptance (the owners' decision)

verification_environment (2026-11-09, Sven's machine):
  database: >-
    stratai_test_p11, a template clone of stratai_test_handoff (the D18 handoff restore: 2024-2026, 608 events),
    migrated through 0014. The source stayed at 0011 and was never written. Every command ran through a wrapper that
    refused to run unless the server reported current_database() = stratai_test_p11.
  rulesets: >-
    the approved P6-M1 v2 rulesets (ids 4-6, 2026-10-08) restored into the copy from
    .agent/phase6/decisions/P6_M1_APPROVAL_<season>_v2.json. Each content hash was checked against the approval
    record, and each row's review_note says it is a restore, not a new approval.
  models: the pinned d18 ranking and win-probability models (sha256-checked at load); the D18 EPA source loaded.

work_units:
  W1 draft log (workspaces/draft_log.py):                 implemented; fixtures-tested; exercised by the real-data replay
  W2 migrations 0013 + 0014:                              applied to stratai_test_p11; 0014 fixes a defect found there (below)
  W3 service (workspaces/live_draft.py):                  DB tests run and pass
  W4 recommendations (workspaces/draft_recommendations.py): fixtures + real-data replay (5,632 calls, none unavailable)
  W5 API (10 ops, locked, classified, path-pinned):       DB route tests run and pass; contract lock unchanged
  W6 frontend (/alliance-selection/live):                 vitest, tsc, lint, build; real browser at tablet size
  W7 replay harness (scripts/phase11_replay.py):          run on real data; comparison defect fixed (below)
  W8 docs:                                                docs/phase11.md, team_workspaces.md, data_pipeline.md (0014)

defects_found_and_fixed (2026-11-09, PR #44):
  - Migration 0013's author foreign keys were checked immediately, so deleting any workspace that had recorded a draft
    action failed (ForeignKeyViolation) before the cascade removed its actions. Migration 0014 makes them DEFERRABLE
    INITIALLY DEFERRED. Deleting an author without the workspace is still refused. Regression test:
    test_a_workspace_takes_its_history_with_it_but_an_author_alone_cannot_be_deleted. It also caused every DB test
    after the first to error at cleanup.
  - The replay compared the record with every team TBA lists on an alliance. TBA appends a playoff backup robot as a
    4th team (15 of 29 events in the wide sample), so 4 of the 6 prescribed events were reported as mismatches although
    their selections matched exactly. The comparison now covers the captain and picks_per_alliance picks, and notes
    each later team. Tests: a later team is noted, and a wrong selected team is still a mismatch.
  - /alliance-selection/live was outside the app's team-workspace area, so it showed the public pages' "Your name /
    Write token" bar and the "Strategy dashboard" label. Fixed in App.tsx; page test added.

human_decisions:
  recorded: decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md (Q1 = b with P11-FB1 frozen; Q2 configurable/off; Q3 <= 2 s p95; Q4 alliance_selection)
  implementation_notes: decisions/P11_IMPLEMENTATION_NOTES_2026-11-04.md
  commit_push: authorized by Sven, 2026-11-09 (PR #44)
  open:
    - human acceptance of Phase 11
    - approval of docs/P11-P19Phases.md as a whole (only Phase 11 was started)
    - whether to add Phase 11-19 entries to docs/ROADMAP.md (§14)
    - applying 0014 to the local serving database (at 0013 since the incident below), and 0012-0014 to any deployment

definition_of_success:
  P11-DM1 (replayed real event, pool and picks exact, no unavailable team): MET on the isolated real-data copy.
    results/p11_replay_20261109_235757.json (prescribed: --per-season 2, seed 20261104): 6 of 6 events pass.
    results/p11_replay_wide_30events_20261109.json (--per-season 10): 29 of 29 replayed events pass; 2026tuis4 skipped
    (event_excluded by the approved 2026 ruleset). 0 overrides, 0 unavailable teams recommended.
  P11-DM2 (ordered attributed history; any point reconstructible): MET. Every prefix replayed to its recorded state in
    all 35 replayed events; the DB tests show append-only, undo and correction kept in the history.
  P11-DM3 (never presented current when stale/refused; status not raised): MET on the page tests and in a real browser
    (two tablets: the second showed "Stale: these reflect record #7, not #8" until its poll caught up, ~1.2 s).

acceptance_criteria:
  1 validation and overrides:    PASS (fixtures; DB test_recording_follows_the_rules_and_an_override_is_kept)
  2 immediate pool update:       PASS (fixtures; replay checks after every action)
  3 recalculation tracks seq:    PASS (fixtures, page tests; replay: every recommendation cites the current record_seq)
  4 undo/correction equivalence: PASS (fixtures; DB test; real browser: the undone entry kept and marked superseded)
  5 permissions by role:         PASS (DB test_permissions_are_enforced_on_every_route_as_each_role, delegation test)
  6 team isolation:              PASS (DB test_another_team_cannot_read_or_change_the_record)
  7 unchanged contracts:         PASS (phase7_contract_lock check: changed [], added [])
  8 gates respected (P11-Q1):    PASS (the engine refuses: P6 gates unmet; P11-FB1 served not_validated with no probability)
  9 tablet usability:            PASS in a real browser at 820x1180 (touch): one-tap captain, tap-a-tile then the action,
                                 large tiles, history with undo/correct; record an action ~0.2-0.4 s

timing (P11-Q3, <= 2 s at p95):
  replay, 29 events, real engine/ordering/models: cold first call <= 1.05 s, warm p95 <= 0.0044 s.

independent_review:
  adversarial review (2026-11-04): 11 findings, all fixed with regression tests (implementation notes §7)

incidents:
  - INCIDENT_2026-11-09_0010-0013_on_serving.md: an unguarded command applied 0010-0013 to the local serving database
    (additive, 0 rows). KEPT by Sven. Not a verification result. The p11a migration guard (d51d626) would prevent it.

known_risks:
  - Decline timing is not reconstructible from TBA (0 declines recorded in 2024-2026); the replay records declines
    against alliance 1, early.
  - TBA's backup field is null for every 2024-2026 alliance, so backup actions are covered by fixtures and DB tests
    only, not by the replay.
  - The verification ran on one local machine, not the environment of record; no deployed database has 0012-0014.
  - The P11-FB1 fallback is not_validated by design; the 2027 holdout is untouched.

last_verification (2026-11-09, Sven's machine, DATABASE_URL -> isolated stratai_test_p11):
  phase11_python: 75 passed (the 16 DB-backed API tests run for the first time), plus 3 new tests in PR #44.
  backend_full_suite: 3,361 passed, 15 skipped, 1 xfailed; 9 failed (33.5 min; exit 1). The suite does NOT pass.
    0 are regressions:
    - test_docs_document_every_migration_file: ran while 0014 was being documented; passes since.
    - test_a_pinned_version_requires_its_artifact_sha256 [ranking, win_prob] and
      test_readiness_for_a_historical_season_reports_real_coverage_without_phase6_tasks: environment. The run
      exported the d18 model pins; all three pass with them unset.
    - test_phase6_m10b, test_phase6_pins, test_phase6_px1b, test_phase6_rulesets (one each): environment. They read
      artifacts at C:/Dev/StratAI-artifacts/... (the Windows build machine's path).
    - test_phase6_g3::test_the_real_v2_record_is_additive_when_present: a committed Phase 6 record's file hash. It is
      unchanged by this work (no .agent/phase6 or test change vs main); a Phase 6 record baseline.
  frontend: vitest 240 passed, 6 skipped; tsc 0; oxlint 8 warnings (baseline); build 0
  audits: phase7_contract_lock check unchanged; phase9_zero_llm_audit ok (no unclassified operations)

next_steps:
  1. Human acceptance (Kanav and Sven).
  2. Merge PR #44, then, when authorized, apply 0012-0014 to a deployment.
```
