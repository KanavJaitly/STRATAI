# Phase 11: status

```yaml
phase: 11
title: Live alliance selection (manual draft tracking and a dynamic picklist)
spec: docs/P11-P19Phases.md §5 (document status PROPOSED; Phase 11 started on the owner's instruction, 2026-11-04)
status: IMPLEMENTED, NOT ACCEPTED
committed: false        # nothing committed or pushed (§3.7)
current_stage: blocked on environment (PostgreSQL) for DB-backed verification and the real-data replay

work_units:
  W1 draft log (workspaces/draft_log.py):                 implemented; fixtures-tested
  W2 migration 0013:                                      implemented; NOT applied anywhere (no PostgreSQL here)
  W3 service (workspaces/live_draft.py):                  implemented; DB tests written, NOT run
  W4 recommendations (workspaces/draft_recommendations.py): implemented; fixtures-tested
  W5 API (10 ops, locked, classified, path-pinned):       implemented; contract tests pass; DB route tests NOT run
  W6 frontend (/alliance-selection/live):                 implemented; vitest, tsc, lint and build pass
  W7 replay harness (scripts/phase11_replay.py):          implemented; fixtures-tested; NOT run on real data
  W8 docs:                                                docs/phase11.md, team_workspaces.md, data_pipeline.md, phase7.md, CLAUDE.md

human_decisions:
  recorded: decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md (Q1 = b with P11-FB1 frozen; Q2 configurable/off; Q3 <= 2 s p95; Q4 alliance_selection)
  implementation_notes: decisions/P11_IMPLEMENTATION_NOTES_2026-11-04.md
  open:
    - approval of docs/P11-P19Phases.md as a whole (only Phase 11 was started)
    - whether to add Phase 11-19 entries to docs/ROADMAP.md (§14)
    - commit / push authorization

definition_of_success:
  P11-DM1 (replayed real event, pool and picks exact, no unavailable team): NOT MET (real-data replay not run)
  P11-DM2 (ordered attributed history; any point reconstructible):        MET on fixtures; DB path not run
  P11-DM3 (never presented current when stale/refused; status not raised): MET on fixtures and the page tests

acceptance_criteria:
  1 validation and overrides:  fixtures + API tests written (API not run)
  2 immediate pool update:     fixtures (incl. captain_may_accept_higher_alliance=False after review)
  3 recalculation tracks seq:  fixtures + page tests
  4 undo/correction equivalence: fixtures; API test written
  5 permissions by role:       API test written, NOT run
  6 team isolation:            API test written, NOT run
  7 unchanged contracts:       PASS (phase7_contract_lock check; 25 pre-Phase 11 entries unchanged)
  8 gates respected (P11-Q1):  fixtures (engine refusal served beside the not_validated fallback)
  9 tablet usability:          page built (tiles, one-tap captain); real-browser run NOT done

independent_review:
  adversarial review (2026-11-04): 11 findings, all fixed with regression tests (implementation notes §7)

known_risks:
  - No PostgreSQL on the build machine: DB tests and the replay are unexecuted, so DB-level defects may remain.
  - Decline timing is not reconstructible from TBA; the replay records declines against alliance 1, early.
  - P11-Q3: only the warm path with faked engine/ordering is measured (p95 < 0.2 s); the real cold/warm timing
    needs the replay on an isolated copy.
  - XGBoost 2.1.4 in this .venv (no system OpenMP); the pinned models were not loaded here.

last_verification (2026-11-04, this machine, DATABASE_URL -> unreachable stratai_test):
  backend_full_suite: 2,605 passed, 763 skipped, 1 xfailed; 10 failed + 4 errors (20 min run).
    - 2 failures were Phase 11's (the 413 count, the Phase 6 route-ownership pin). Both are fixed and pass
      (implementation notes §8).
    - The other 8 failures fail identically on a clean export of main on this machine. They are an environment
      baseline (Phase 6 artifact/record tests, Phase 9 LLM SDK tests), not regressions.
    - The 4 errors are DB connection errors at fixture setup (no PostgreSQL).
    - The suite does NOT pass on this machine.
  phase11_python: 59 passed, 15 skipped (DB)
  contract_docs_phase11_set: 208 passed, 65 skipped, 1 xfailed (the strict P7-M8 check)
  frontend: vitest 239 passed, 6 skipped (34 files passed, 1 skipped); tsc 0; oxlint 8 warnings (baseline); build 0

next_steps:
  1. Provide an isolated stratai_test_<suffix> with migrations through 0013 and real 2024-2026 data, then:
     pytest tests/test_phase11_live_draft_api.py; python -m scripts.phase11_replay --per-season 2
  2. A real-browser run of a replayed draft on a tablet-sized viewport.
  3. Human acceptance.
```
