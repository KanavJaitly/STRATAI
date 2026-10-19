# Phase 8 — environment and dependency assessment (2026-10-18)

## Repository
- Branch `phase8/build`, created from `origin/main` `7c678eb` (the PR #32 merge; Phase 7 commit `c1404cf` is in the
  history).
- Its upstream is unset deliberately, so a push can never target main by accident.
- The untracked `.agent/phase7/runs/` (4 Phase 7 logs) is preserved and untouched.
- `docs/P8Milestones.md` was empty (0 lines) in main; revision 1 is written in P8-M0.

## Toolchain
- Node v24.17.0, npm 11.13.0. `npm ci` in `frontend/` installed 110 packages (lockfile; `node_modules` and `dist`
  are git-ignored).
- **Frontend baseline before Phase 8:**

  | Check | Command | Result |
  |---|---|---|
  | Tests | `npx vitest run` | 6 files, 32 tests passed; exit 0 |
  | Type check | `npx tsc -b` | exit 0 |
  | Lint | `npx oxlint` | 0 errors, 8 warnings (all in Phase 5 files); exit 0 |
  | Build | `npx vite build` | exit 0 (JS 315.99 kB, gzip 96.15 kB) |

- Formatting: no formatter is configured (no prettier, no eslint).
- Python venv: `venv/bin/python`. The backend full-suite baseline is in `runs/backend_baseline.txt`; the recorded
  Phase 7 value is 2,483 passed, 5 failed, 5 skipped, 1 xfailed, pytest exit 1.

## Live API (local, NOT the environment of record)
- Started with `DATABASE_URL=<.../stratai_test> EPA_SOURCE=statbotics API_PORT=8765 venv/bin/python -m api`, i.e.
  the isolated test copy and the reference Statbotics EPA source. The serving database is never used.
- Data: the 2026 season has 1 event (`2026mrcmp`), 2025 has none, 2024 has several.
- **Observed (2026mrcmp):**

  | Route | Result |
  |---|---|
  | teams, matches | 200 |
  | metrics, strength | 200 |
  | candidates | 200 (about 3.4 s) |
  | pre-match report | 200, with its model parts absent |
  | analysis | 200 with `as_of` before the switch point (raw EPA, about 8 s); otherwise 404 `model_not_loaded` (M5 v2) |
  | qualification forecast, win probability | 404 `model_not_loaded` (M6/M7) |
  | strategy | 404 `model_not_loaded` (P6-M10) |
  | pick list | 409 `not_approved` |

## Blocked here (environment, P7-Q5)
- **Real-model output:** M5 v2, M6/M7, P6-M10 and PX. Every view's success path for these is fixture-tested only.
- **The production EPA source configuration.**
- **Approved P6-M1 rulesets:** the pick-list success path.
