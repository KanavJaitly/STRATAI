# Phase 8 — commit candidate (regenerated 2026-10-19, final audit)

**Nothing is staged or committed. This is for Sven Morais's review; any `git add`, commit, push or PR needs his explicit**
**authorization.** Do not run `git add -A`: stage the INCLUDE paths explicitly, e.g. from this list.

**Source:** `git diff HEAD --name-only` (15 modified tracked files) and `git ls-files --others --exclude-standard` (100 untracked, including this file). Staged at generation: 0. Inventory: 115 files = 106 INCLUDE + 9 EXCLUDE.

**Scan of every INCLUDE file:**
- no `.env` secret value and no database password;
- no username or home-directory path.

**Never staged:** `frontend/dist/` (build output), `frontend/node_modules/`, `.pytest_cache/`, `__pycache__/` and `.env`.
All are ignored by `.gitignore`.

## INCLUDE (106)

| File | Git state | Category |
|---|---|---|
| `.agent/phase8/COMMIT_CANDIDATE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/ENVIRONMENT.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M00_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M01_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M02_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M03_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M04_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M05_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M06_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/M07_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/P8_M0_DECISIONS.md` | new (untracked) | frozen specification / integrity record |
| `.agent/phase8/P8_M0_FREEZE.md` | new (untracked) | frozen specification / integrity record |
| `.agent/phase8/PHASE_ACCEPTANCE.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/PHASE_ACCEPTANCE_PROPOSAL_2026-10-19.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/PHASE_PLAN.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/PHASE_STATUS.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/RISK_REGISTER.md` | new (untracked) | acceptance / status / risk / plan record |
| `.agent/phase8/decisions/P8_D1_IMPLEMENTATION_DEVIATIONS_2026-10-18.md` | new (untracked) | decision record |
| `.agent/phase8/decisions/P8_D2_RULINGS_AND_DEVIATION_DISPOSITIONS_2026-10-19.md` | new (untracked) | decision record |
| `.agent/phase8/decisions/P8_Q6_DECISION_2026-10-19.md` | new (untracked) | decision record |
| `.agent/phase8/decisions/P8_Q6_REPORT_COMPLETENESS_BRIEF_2026-10-19.md` | new (untracked) | decision record |
| `.agent/phase8/reviews/R1_correctness.md` | new (untracked) | review evidence |
| `.agent/phase8/reviews/R3_security_state.md` | new (untracked) | review evidence |
| `.agent/phase8/reviews/REVIEW_DISPOSITION.md` | new (untracked) | review evidence |
| `.agent/phase8/reviews/sanitized/R2_accessibility_ux.md` | new (untracked) | sanitized evidence (derivative) |
| `.agent/phase8/reviews/sanitized/R4_fix_verification.md` | new (untracked) | sanitized evidence (derivative) |
| `.agent/phase8/runs/contract_lock.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/contract_tests.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/frontend_build.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/frontend_oxlint.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/frontend_tsc.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/live_smoke.json` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/live_smoke.txt` | new (untracked) | run output (evidence) |
| `.agent/phase8/runs/sanitized/backend_baseline.txt` | new (untracked) | sanitized evidence (derivative) |
| `.agent/phase8/runs/sanitized/backend_final.txt` | new (untracked) | sanitized evidence (derivative) |
| `.agent/phase8/runs/sanitized/frontend_vitest.txt` | new (untracked) | sanitized evidence (derivative) |
| `.agent/phase8/runs/types_check.txt` | new (untracked) | run output (evidence) |
| `CLAUDE.md` | modified (tracked) | documentation |
| `RUNNING_NOTES.md` | modified (tracked) | documentation |
| `docs/P8Milestones.md` | modified (tracked) | frozen specification / integrity record |
| `docs/phase8.md` | new (untracked) | documentation |
| `frontend/.oxlintrc.json` | modified (tracked) | frontend config / documentation |
| `frontend/README.md` | modified (tracked) | frontend config / documentation |
| `frontend/index.html` | modified (tracked) | frontend config / documentation |
| `frontend/package-lock.json` | modified (tracked) | frontend config / documentation |
| `frontend/package.json` | modified (tracked) | frontend config / documentation |
| `frontend/src/App.test.tsx` | new (untracked) | test |
| `frontend/src/App.tsx` | modified (tracked) | source |
| `frontend/src/api/client.phase8.test.ts` | new (untracked) | test |
| `frontend/src/api/client.ts` | modified (tracked) | source |
| `frontend/src/api/dashboard.test.ts` | new (untracked) | test |
| `frontend/src/api/dashboard.ts` | new (untracked) | source |
| `frontend/src/api/generated.ts` | new (untracked) | source |
| `frontend/src/api/http.test.ts` | new (untracked) | test |
| `frontend/src/api/http.ts` | new (untracked) | source |
| `frontend/src/components/useOnDemand.test.tsx` | new (untracked) | test |
| `frontend/src/components/useOnDemand.ts` | new (untracked) | source |
| `frontend/src/components/useResource.test.tsx` | new (untracked) | test |
| `frontend/src/components/useResource.ts` | new (untracked) | source |
| `frontend/src/dashboard/asOf.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/asOf.tsx` | new (untracked) | source |
| `frontend/src/dashboard/asOfParams.ts` | new (untracked) | source |
| `frontend/src/dashboard/charts.tsx` | new (untracked) | source |
| `frontend/src/dashboard/coachInputs.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/coachInputs.tsx` | new (untracked) | source |
| `frontend/src/dashboard/common.tsx` | new (untracked) | source |
| `frontend/src/dashboard/display.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/display.tsx` | new (untracked) | source |
| `frontend/src/dashboard/labels.ts` | new (untracked) | source |
| `frontend/src/dashboard/liveRegions.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/AlliancePage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/AlliancePage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/EventPage.history.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/EventPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/EventPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/EventsPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/EventsPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/MatchPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/MatchPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/NotFoundPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/ReportPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/ReportPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/StatusPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/StatusPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/StrategyLabPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/StrategyLabPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/pages/TeamPage.test.tsx` | new (untracked) | test |
| `frontend/src/dashboard/pages/TeamPage.tsx` | new (untracked) | source |
| `frontend/src/dashboard/refusals.ts` | new (untracked) | source |
| `frontend/src/dashboard/routing.ts` | new (untracked) | source |
| `frontend/src/dashboard/strategy.tsx` | new (untracked) | source |
| `frontend/src/dashboard/strategyModel.ts` | new (untracked) | source |
| `frontend/src/dashboard/useTab.ts` | new (untracked) | source |
| `frontend/src/main.tsx` | modified (tracked) | source |
| `frontend/src/pages/OverviewPage.tsx` | modified (tracked) | source |
| `frontend/src/pages/OverviewPage.unknownInput.test.tsx` | new (untracked) | test |
| `frontend/src/state/session.race.test.tsx` | new (untracked) | test |
| `frontend/src/state/session.tsx` | modified (tracked) | source |
| `frontend/src/styles/dashboard.css` | new (untracked) | source |
| `frontend/src/test/dashboard.tsx` | new (untracked) | test |
| `frontend/src/test/dashboardFixtures.ts` | new (untracked) | test |
| `frontend/src/test/mockApi.ts` | modified (tracked) | test |
| `frontend/vite.config.ts` | modified (tracked) | frontend config / documentation |
| `scripts/phase8_generate_api_types.py` | new (untracked) | source |
| `scripts/phase8_live_smoke.py` | new (untracked) | source |
| `tests/test_phase8_frontend_contract.py` | new (untracked) | test |

## EXCLUDE (9)

| File | Git state | Category | Why |
|---|---|---|---|
| `.agent/phase7/runs/m6m7_full.txt` | new (untracked) | Phase 7 local run log (unrelated) | the Phase 7 local run log; preserved and unrelated to Phase 8 |
| `.agent/phase7/runs/phase_final.txt` | new (untracked) | Phase 7 local run log (unrelated) | the Phase 7 local run log; preserved and unrelated to Phase 8 |
| `.agent/phase7/runs/phase_final_d7.txt` | new (untracked) | Phase 7 local run log (unrelated) | the Phase 7 local run log; preserved and unrelated to Phase 8 |
| `.agent/phase7/runs/phase_full.txt` | new (untracked) | Phase 7 local run log (unrelated) | the Phase 7 local run log; preserved and unrelated to Phase 8 |
| `.agent/phase8/reviews/R2_accessibility_ux.md` | new (untracked) | review evidence | original contains local path or username; kept as local evidence; the commit uses `.agent/phase8/reviews/sanitized/R2_accessibility_ux.md` |
| `.agent/phase8/reviews/R4_fix_verification.md` | new (untracked) | review evidence | original contains local path or username; kept as local evidence; the commit uses `.agent/phase8/reviews/sanitized/R4_fix_verification.md` |
| `.agent/phase8/runs/backend_baseline.txt` | new (untracked) | run output (evidence) | original contains local path or username; kept as local evidence; the commit uses `.agent/phase8/runs/sanitized/backend_baseline.txt` |
| `.agent/phase8/runs/backend_final.txt` | new (untracked) | run output (evidence) | original contains local path or username; kept as local evidence; the commit uses `.agent/phase8/runs/sanitized/backend_final.txt` |
| `.agent/phase8/runs/frontend_vitest.txt` | new (untracked) | run output (evidence) | original contains local path or username; kept as local evidence; the commit uses `.agent/phase8/runs/sanitized/frontend_vitest.txt` |

**Why each category belongs to Phase 8:**
- **Source and test:** the dashboard, its API client and generated types, the shared fetch core, the Phase 5 changes recorded as D1.2, D1.3 and D1.4, and the type-generation and live-smoke scripts.
- **Frozen specification:** revision 1 of the spec and its decisions, with the integrity record.
- **Decisions, acceptance, status and risk records:** the Phase 8 governance trail. This includes the superseded proposal, kept as history.
- **Review evidence:** the R1 and R3 originals, the sanitized R2 and R4, and the dispositions.
- **Run output:** command results that the acceptance record cites, with sanitized copies where the original contains local paths.
- **Documentation:** `docs/phase8.md`, the frontend README, and the project status in `CLAUDE.md` and `RUNNING_NOTES.md`.
