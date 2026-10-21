# Phase 9 — verified baseline (2026-10-20, before any Phase 9 code)

## Repository
- **Branch:** `phase8/build`, HEAD `45859dc` (equal to `main` `111bc04` in content; `main` = PR #34 merge).
- **Staged:** nothing.
- **Working tree:** the uncommitted Phase 8 closeout (17 modified tracked files; 3 new files: the P8-D3 draft, the
  closeout record, the R9 test), plus the 9 deliberately untracked local evidence files (4 Phase 7 run logs,
  3 Phase 8 run-log originals, 2 review originals).
- **Work location:** Phase 9 work is done on top of this working tree. Nothing is committed (no authorization).

## Runtime
- **Python and Node:** Python 3.11.2 (`venv/`); Node 24.17.0.
- **Machine:** 8 CPUs, 6 GB RAM, about 6 GB free disk.
- **Database:** PostgreSQL 18.4 on localhost. Databases `stratai` (serving) and `stratai_test` (isolated). Tests use
  `stratai_test` only.
- **No trained models:** `ml_registry/` is **absent**, and every pinned model version tag is unset, so the
  model-backed routes answer `model_not_loaded`.
- **No LLM access:** **no LLM credential** of any kind (no `ANTHROPIC_API_KEY`, no `ant` CLI, no stored profile).
  The `anthropic` SDK was not installed; Phase 9 installed `anthropic` 1.16.0 (P9-M3).
- **Missing packages:** pandas, OR-Tools and redis are not installed.
- **Pre-existing manifest gap (found, not changed):** `requirements.txt` does not list `scipy`, although `ml/`
  imports it.

## Test baseline
| Check | Command | Result |
|---|---|---|
| Backend full suite | `DATABASE_URL=<…/stratai_test> venv/bin/python -m pytest tests -q -p no:cacheprovider` | **exit 1: 2,489 passed, 5 failed, 5 skipped, 1 xfailed** (13 min 52 s). The 5 failures are the known baseline tests, by name, as at Phase 8 close. The log is `runs/backend_baseline_p9.txt` (paths sanitized) |
| Frontend tests | `cd frontend && npx vitest run` | 165 tests in 28 files. **7 runs: 5 passed in full, 2 failed** (5 failures, then 1). Both failing runs were slow cold starts after a machine restart (88 s against about 30 s); the failure seen was the axe-heavy ReportPage test timing out. This is new evidence for P8-R14, carried as P9-R5 |
| Type check | `npx tsc -b` | exit 0 |
| Lint | `npx oxlint` | 8 warnings, all in Phase 5 files (baseline) |
| Contract lock | `venv/bin/python -m scripts.phase7_contract_lock check` | unchanged (24 operations), checked in the Phase 8 closeout |

**The 5 known backend baseline failures:**
- `test_ml_features_score_breakdown.py::test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score`
- `test_phase5_contract.py::test_p5_d3_adoption_record_matches_the_served_status_and_its_evidence`
- `test_phase6_rulesets.py::test_m1_reproduction_path_runs_on_real_events_with_injected_rulesets`
- `test_phase6_rulesets.py::test_m1_counts_ruleset_exclusions_and_records_the_variant_applied`
- `test_phase6_rulesets.py::test_m8_future_playoff_sentinel_changes_no_selection_moment_input_and_is_removed`
