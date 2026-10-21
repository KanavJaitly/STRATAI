phase: 8
branch: phase8/build, tracking origin/phase8/build. The Phase 8 commit a5bc422 (parent 7c678eb; 106 reviewed files) was committed and pushed with Sven's authorization, and merged into main via PR #33 on 2026-10-19 (merge commit 12a2954)
current_milestone: P8-M8 (documentation, audit, acceptance proposal)
status: CONDITIONALLY ACCEPTED, NOT FULLY COMPLETE (confirmed by Sven Morais on 2026-10-19, PHASE_ACCEPTANCE.md §7; the MASTER_BUILD gate is not satisfied on its own terms); committed as a5bc422 and merged to main via PR #33 (2026-10-19). Merging records the work; it does not complete the phase: DM2 is deferred and the open risks stand
spec: docs/P8Milestones.md (revision 1, the agent's working freeze; baseline and deviations D1.1-D1.9 ratified 2026-10-19 per Sven Morais (P8-D2); blobs in P8_M0_FREEZE.md, unchanged and rechecked in the final audit)
decisions:
  - P8_M0_DECISIONS.md (P8-Q1..Q13, frozen; Q6 since decided, see below)
  - decisions/P8_D1_IMPLEMENTATION_DEVIATIONS_2026-10-18.md (the proposal record, revision 2; superseded for the dispositions by P8-D2)
  - decisions/P8_Q6_REPORT_COMPLETENESS_BRIEF_2026-10-19.md (options A-D)
  - decisions/P8_Q6_DECISION_2026-10-19.md (DECIDED: Option C now, then D; DM2 deferred)
  - decisions/P8_D2_RULINGS_AND_DEVIATION_DISPOSITIONS_2026-10-19.md (rulings D1.2/D1.7; D1.1-D1.9 ratified; authoritative)
milestones:
  - P8-M0: frozen-spec baseline intact; D1.1-D1.9 ratified (P8-D2)
  - P8-M1..M5, M7: CONDITIONALLY ACCEPTED on local evidence; environment of record BLOCKED
  - P8-M6: report UI ACCEPTED; P8-DM2 NOT MET, DEFERRED
  - P8-M8: docs/phase8.md, frontend/README.md, PHASE_ACCEPTANCE.md (the conditional-acceptance record, with the final audit of 2026-10-19); confirmed by Sven Morais on 2026-10-19
done_means:
  - P8-DM1 (every view runs off the real API endpoints): MET against the local API only (live smoke ALL OK); not verified in the environment of record (P7-Q5)
  - P8-DM2 (pre-match report complete and shareable as-is): NOT MET, DEFERRED (P8-Q6 decided: C now, then D); shareable locally
reviews: reviews/R1..R4 (verbatim, local evidence; the R2 and R4 originals contain local paths and are excluded from the commit candidate), reviews/sanitized/ (sanitized derivatives of R2 and R4 for the commit), reviews/REVIEW_DISPOSITION.md
blocked:
  - real-model verification of every view (P7-Q5, environment of record)
human_decisions_required:
  - approve, amend or reject P8-D3 (predicted_flow: the interpretation, the derivation rule, and the locked-entry contract change); nothing is implemented until it is approved
  - each later Option D derivation step for P8-Q6 (none started)
  - authorize any commit of the closeout changes
risks: RISK_REGISTER.md (P8-R1..R15; R7, R8, R9, R12 and R13 resolved; R11 open only for model-populated print; the rest open)
closeout_2026-10-19 (uncommitted): R11 fixed and verified locally, R7 verified, R9 fixed and verified; P8-D3 predicted_flow PROPOSED (not implemented). Evidence: runs/closeout_2026-10-19.md
baselines:
  frontend (before Phase 8): vitest 32 passed (6 files), exit 0; tsc -b exit 0; oxlint 0 errors, 8 warnings; vite build exit 0
  backend: runs/backend_baseline.txt (2483 passed, 5 failed, 5 skipped, 1 xfailed; exit 1)
final_checks: PHASE_ACCEPTANCE.md sections 3 and 6 (final audit 2026-10-19: frontend 157 passed / 27 files, 3 of 3 runs, 9 of 9 since maxWorkers; live smoke ALL OK (fresh); tsc 0; oxlint 8 baseline warnings; build 0; contract 9 passed; lock unchanged; live smoke ALL OK; backend exit 1: 2489 passed, 5 baseline failures, 5 skipped, 1 xfailed)
live_api (local): DATABASE_URL=<.../stratai_test> EPA_SOURCE=statbotics API_PORT=8765 venv/bin/python -m api
live_app (local): cd frontend && STRATAI_API_URL=http://127.0.0.1:8765 npm run dev
recovery:
  - frontend deps: cd frontend && npm ci
  - frontend checks: npx vitest run; npx tsc -b; npx oxlint; npm run build
  - types: venv/bin/python -m scripts.phase8_generate_api_types [--check] (the drift test is in tests/test_phase8_frontend_contract.py)
  - contract: venv/bin/python -m pytest tests/test_phase8_frontend_contract.py tests/test_frontend_api_contract.py -q -p no:cacheprovider
  - lock: venv/bin/python -m scripts.phase7_contract_lock check
  - live smoke: venv/bin/python -m scripts.phase8_live_smoke --api http://127.0.0.1:8765 --season 2026 --app http://127.0.0.1:5173 --chrome <chrome-headless-shell> --out .agent/phase8/runs/live_smoke.json
  - backend: DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest tests -q -p no:cacheprovider (never concurrently with another DB-backed run)
