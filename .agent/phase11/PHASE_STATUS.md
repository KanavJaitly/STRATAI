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

# P11A (recommendation intelligence): status

```yaml
spec: docs/P11-RecommendationIntelligence.md (PROPOSED, NOT APPROVED; unchanged)
authorization: decisions/P11A_IMPLEMENTATION_START_2026-11-06.md (implementation only)
status: STAGES 1-3 IMPLEMENTED (foundation, plan, offline snapshot); NOT VALIDATED; NOT ACCEPTED; NOT COMPLETE
committed: false
serving_effect: every real event's plan is withheld (scoring_config_not_approved): no season configuration exists

built:
  scoring configuration (B4):      ml/alliance/scoring_config.py; data/season_scoring/ empty
  estimator (A3):                  ml/alliance/estimator.py
  planner (B5, B6, C, D, E):       ml/alliance/planner.py
  profile (G2):                    ml/alliance/profile.py
  snapshot (§14):                  ml/alliance/snapshot.py (DB builder UNVERIFIED: no PostgreSQL)
  Phase 11 adapter:                workspaces/alliance_plan.py
  API (2 ops, additive, locked):   GET …/drafts/{record_id}/plan, GET …/drafts/{record_id}/teams/{team_number}/profile
  CLI:                             scripts/p11a_snapshot.py (export read-only, UNVERIFIED; plan/profile offline)
  web:                             frontend/src/workspace/ExpectedScorePlan.tsx (closed by default)
  setting:                         P11A_SNAPSHOT_DIR (data/config.py, .env.example)

gated (not served as validated or enabled): win probability; synergy bonuses; validated per-robot contributions;
  playoff-bias correction; probabilistic availability; unapproved scoring; calibrated intervals; δ/π decisions;
  causal claims; anomaly flags (G2 bound not approved)

last_verification (2026-11-06, this machine, no PostgreSQL):
  p11a: 46 passed (incl. 4 run under sandbox-exec with the network denied, with a positive control)
  backend_full_suite: 2,653 passed, 763 skipped, 1 xfailed; 8 failed, 4 errors (19.5 min)
    - 1 failure was P11A's (the team-private locked-op count in test_phase7_examples); fixed, file passes.
    - the other 7 fail identically on a clean export of HEAD (baseline: Phase 6 records, Phase 9 LLM SDK).
    - the 4 errors are DB connection errors (no PostgreSQL). The suite does NOT pass on this machine.
  frontend: vitest 243 passed, 6 skipped (35 files, 1 skipped); tsc 0; oxlint 8 (baseline); build 0
  contract lock: 37 operations, 0 changed leaves; types regenerated (--check 0)

not_run: DB-backed snapshot export on real data; API route tests with a session (need PostgreSQL); real-event
  timing; any validation of P11A recommendations (needs approved configurations and E5)
```

# P11A hardening (2026-11-06): status

```yaml
record: decisions/P11A_HARDENING_2026-11-06.md
stage_4: not begun
done:
  collapse_check: investigated (research/p11a_hardening); now a non-authoritative screen; only a degenerate fit withholds
  availability: one shared definition (draft_recommendations.selectable_teams); random-draft agreement test
  runtime_contract: ml/alliance/contract.py, validated by the API and the CLI; tampered responses become 500
  profile: fully typed (observed, estimates, uncertainty, n, prior influence, scouting, provenance, timestamps)
  trust_root: only a registered approved configuration in data/season_scoring counts (found: self-attested approval)
  leakage: delayed results, late scouting summaries and late rankings excluded from snapshots
  determinism: identical-lineup comparisons no longer report float noise
prepared_not_run:
  postgres: docs/p11a_verification.md, scripts/p11a_db_preflight.py, tests/test_p11a_db.py (skip without PostgreSQL)
  e5: research/p11a_e5 (harness tested on synthetic data; PROTOCOL.json is a DRAFT, not registered)

last_verification (2026-11-06, this machine, no PostgreSQL):
  p11a: all P11A test files pass (contract, availability, snapshot builder, E5 harness, offline under sandbox-exec)
  backend_full_suite: 2,694 passed, 773 skipped, 1 xfailed; 8 failed, 4 errors (21 min). Not passing.
    - 7 failures fail identically on a clean export of HEAD (Phase 6 records, Phase 9 LLM SDK).
    - test_phase6_px2b_v2::test_px2b_v2_calibrates_out_of_sample_and_evaluates_the_candidate is intermittent: it
      failed 3 of 6 runs on a clean export of HEAD (float equality), so it is not a regression.
    - 4 errors: database connection refused (no PostgreSQL).
  frontend: vitest 243 passed, 6 skipped; tsc -b 0; oxlint 8 (baseline); build 0
  contract_lock: 37 operations; P11A relocked under the hardening decision; no other entry changed

blockers: PostgreSQL copy; approved and registered 2024-2026 scoring configurations; P11A-Q10 and the other E5
  decisions; E5 registration
```
