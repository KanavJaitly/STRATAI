# Audit 2026-11-26: baseline before any change

## Repository

- **Local `main`** was at `8cca235` (PR #47), 39 commits behind `origin/main`.
- **The audit is on a new local branch `audit/2026-11-26`** created from `origin/main` `34cefb5` (PR #60). Local `main`
  was not touched. Nothing is committed, pushed or merged.
- **Uncommitted work found and preserved:**
  - `docs/P11-P19Phases.md`: one stray `#` in "Integrity and completeness:#".
  - It looks accidental. It is kept as found, not reverted.
- **Stash:** `stash@{0}` (phase6/build recovery, 2026-11-02) is untouched.

## Databases

**Migration level of each database:**

| Database | Level | Note |
|---|---|---|
| `stratai` (serving) | 0011 | Never written by this audit |
| `stratai_test` | 0014 | Clone source, only read |
| `stratai_test_audit` | 0016 | NEW: cloned from `stratai_test` by template, 0015 and 0016 applied by `database.migrate` after checking `current_database()`. Used for the backend suite |
| `stratai_test_pit` | 0016 | NEW: disposable clone for the point-in-time perturbation tests. It is deliberately corrupted |

**Guard:** `database/migrate.py` on main still has no target guard. The guard (`database/target_guard.py`) exists only
on `p11a/recommendation-intelligence`.

## Tests on the unmodified upstream code (34cefb5)

**Backend.** Isolated `stratai_test_audit`, run in 4 parts (each under 45 minutes) plus `tests/test_config.py` on its
own. Command:
`pytest <part> -q -rsfE -p no:cacheprovider`

| Part | Passed | Failed | Skipped | xfailed | Seconds |
|---|---|---|---|---|---|
| part_00 (44 files) | 963 | 2 | 4 | 0 | 493 |
| part_01 (40) | 745 | 0 | 0 | 0 | 278 |
| part_02 (40) | 897 | 0 | 0 | 1 | 1,411 |
| part_03 (41) | 847 | 0 | 0 | 0 | 209 |
| test_config | 10 | 0 | 0 | 0 | 2 |
| **Total** | **3,462** | **2** | **4** | **1** | ~40 min |

The two failures are upstream drift:
1. **`test_api_foundation::test_exactly_the_intended_endpoints_are_exposed`:** `/workspace/team-events` was added by
   PR #58 without being pinned.
2. **`test_docs_contract::test_docs_document_every_migration_file`:** `0016_more_team_roles.sql` is not documented.

**Frontend.** Commands: `npx vitest run`, `npx tsc -b`, `npx oxlint src`, `npx vite build`.
- vitest: 280 passed, 6 skipped (37 files, 1 skipped), 47 s.
- tsc: exit 0.
- oxlint: 8 warnings (the known baseline).
- build: OK (chunk-size warning only).

## Startup

- **Local test API:** `python -m scripts.local_test_env --serve` (port 8765, `stratai_test`). This needs 0015 and 0016
  for the current auth code, which `stratai_test` does not have yet.
- **Web app:** `cd frontend; $env:STRATAI_API_URL='http://127.0.0.1:8765'; npm run dev`.
