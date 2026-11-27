# Final verification — audit follow-up workstreams (2026-11-26/27)

Every database check ran on isolated copies: `stratai_test_audit`, `stratai_test_pit2` and `stratai_test_pit3`
(disposable, migrated to 0016), and `stratai_dev_fresh`. `stratai` (serving) and `stratai_test` were not modified.

## Backend

**Full suite** on `stratai_test_audit`, in 4 parts, each under 45 minutes, plus `tests/test_config.py` alone:
| Part | Result | Time |
|---|---|---|
| 1 | 947 passed, 4 skipped | 7 min |
| 2 | 748 passed, **1 failed** (fixed, below) | 4 min |
| 3 | 952 passed, 1 xfailed (the strict P7-M8 completeness check, as before) | 23 min |
| 4 | 880 passed | 4 min |
| test_config | 10 passed | — |

In total, 3,537 passed and 1 failed. The failure was fixed: `tests/test_phase10_hardening.py` was re-run alone,
24 passed. Every part stayed under 45 minutes. The suite's baseline after the audit was 3,459 passed; the 79 added
tests are from the workstreams.

**One regression found and fixed:** `tests/test_phase10_hardening.py` pins the number of operations that declare 413
at 42. Workstream 8 added two, its preview and its import, both correctly declared. The pin is now 44, and the check
that declared equals body-taking is separate.

**Targeted runs during the work:**

| Area | Result |
|---|---|
| Auth and proxy (`test_workspaces_api`, frontend workspace contract, API foundation) | 97 passed |
| CSV upload | 12 passed |
| Optimizer foundation | 19 passed |
| Candidates | 11 passed |
| Validation scope | 7 passed |
| Local dev DB | 4 passed |
| Personal-data guards and ScoutRadioz suites | 83 passed |
| Related suites after workstream 8 | 249 passed |
| On the rewritten branch, in a separate worktree (scouting, upload, docs contract, candidates, optimizer) | 186 passed |

## Frontend

- vitest: 280 passed, 6 skipped (36 files)
- `tsc -b`: 0
- oxlint: 8 warnings, the baseline (none new)
- production build: 0

## Contract and audits

- `phase7_contract_lock check`: no changed or added leaves.
- `phase8_generate_api_types --check`: 0. It was regenerated for workstream 8, with additions only.
- `phase9_zero_llm_audit`: ok. The new operations are classified.

## Point-in-time regression

The audit's perturbation harness (`results/scripts/pit_invariance.py`, pointed at fresh copies). Every fact after a
cutoff was corrupted, and every output pinned to that cutoff was captured again:

| Run | Cutoff-pinned outputs | Changed | Selection-moment outputs (should change) |
|---|---|---|---|
| Earlier events (`stratai_test_pit2`) | 66 | **0** | 53 of 57 changed |
| Later events (`stratai_test_pit3`) | 66 | **0** | 52 of 57 changed |

This matches the audit: 132 of 132 unchanged and 105 changed. Workstream 3's new label rule reads each event's last
scheduled qualification match, and it introduced no leak.

## Migrations

No workstream adds a migration. Migrations 0001–0016 were applied from scratch on three disposable copies
(`stratai_dev_fresh`, `stratai_test_pit2`, `stratai_test_pit3`), each checked by `current_database()` first.

## Manual and end-to-end checks

`stratai_dev_fresh` was served with `local_test_env --serve`:
- sign-up as admin and as base, and a wrong code (403);
- sign-out and sign-in, and a wrong password (401);
- a base member refused team-private routes (403), and an admin allowed;
- 190 events for 2024, and analysis 200.
