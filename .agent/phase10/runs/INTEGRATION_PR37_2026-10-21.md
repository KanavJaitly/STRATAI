# Integration of main (PR #36 + PR #37) into phase8/build (2026-10-21)

**What happened.** The maintainers merged two PRs into `main`:
- PR #36: our `555162c`;
- PR #37: `phase6/build`, 75 local commits from 2026-10-08..12. It added the historical explorer, the game-manual
  manager, ruleset entry and review, readiness, PX-1b/PX-2b and M10b/M10c, the `pypdf` dependency, and frontend
  changes.

`phase8/build` was then committed (`2e82570`: the P10-D1 experiment and the option-A restore) and merged with
`origin/main` (`02736e6`). **There were no conflicts.** `CLAUDE.md` merged automatically, keeping both sides.

**Environment for the merged code:**
- `pip install "pypdf>=5,<7"` installed 6.21.2 (from `requirements.txt`);
- `npm ci` in `frontend/`.

There are no new migrations.

## What the merged code broke, and the fixes

Each was found by the existing contract tests on the combined code. Each is in #37's new routes, not in the work
merged from this branch.

| Failure | Fix |
|---|---|
| `test_phase9_zero_llm.py::test_every_served_operation_is_classified`: 18 new operations unclassified | Classified in `scripts/phase9_zero_llm_audit.py` `OPERATION_CLASSES` as `not_output`: 5 historical-explorer reads, 13 game-manual and ruleset human-input routes. The static scan and the import check stay clean (none imports an LLM SDK) |
| `test_phase7_contract.py`: `every_operation_declares_500_and_only_envelope_errors` and `validation_error_is_declared_exactly_where_it_can_happen`. The 18 routes declared no 500, declared 4xx without codes, or kept FastAPI's own 422 | **Declaration only.** `api/routes/manual_manager.py` gets an `_errors(...)` helper mirroring `api/routes/human_inputs.py`. Each route declares the codes its calls can raise, derived statically from the data functions it calls (`mp.*`, `rs.*`, `ruleset_worksheet`), plus the write-token refusals on write routes. `api/routes/explorer.py` declares `invalid_input`, `event_not_found` and `team_not_found` where raised. No runtime behaviour changed |
| `test_phase8_frontend_contract.py::test_the_generated_types_are_current` | `python -m scripts.phase8_generate_api_types` (the prescribed workflow); `--check` exit 0 |

**Noted, not changed:** `get_processing` (`mp.status`) and `get_readiness` (`rd.season_readiness`) call their data
functions without `_call`. A `ManualProcessingError` there would surface as a 500, not a 4xx, so no 4xx is
declared for them. Changing that would be a behaviour change in #37's code; it is left for its owner.

## Results on the merged code (after the fixes)

| Check | Result |
|---|---|
| Lock | `check` exit 0. No locked entry changed; #37's routes are not locked |
| Types | `--check` exit 0 |
| Zero-LLM | 0 unclassified operations; static violations `[]` |
| Focused contract and Phase 9/10 suite | All pass, except `test_manual_manager.py` (below) |
| Frontend | vitest 201 passed, 6 skipped (exit 0); tsc 0; oxlint 8 warnings (baseline), 0 errors; build 0 |
| **Full backend suite** (`backend_merged_pr37_2026-10-21.txt`) | **Exit 1:** 3,233 passed, **14 failed**, 18 skipped, 1 xfailed |

## The 14 failures, classified

| Group | Tests | Evidence | Regression? |
|---|---|---|---|
| The 4 identified baseline failures | `test_ml_features_score_breakdown` (adapter); `test_phase6_rulesets` ×3 (m1_reproduction, m1_counts, m8_sentinel) | Unchanged since Phase 9 | No |
| Pre-existing on `main`: manual manager | `test_manual_manager.py` ×6 (the worksheet ×4, readiness, the 2025 explorer case) | Identical on a pristine `origin/main` worktree. Cause: `stratai_test` has 0 `season_rulesets` rows and 0 events from 2025 (the worksheet answers `404 not_found`: "no approved ruleset from a season before …") | No: environment data |
| Pre-existing on `main`: Phase 6 environment-of-record checks | `test_phase6_g3::test_the_real_v2_record_is_additive_when_present`, `test_phase6_m10b::test_the_real_final_run_is_blocked_today`, `test_phase6_pins::test_final1_lists_the_pin_record_and_refuses_an_altered_model`, `test_phase6_px1b::test_gate_2027_refuses_while_its_prerequisites_are_missing` | Identical on a pristine `origin/main` worktree. They read the Windows artifacts (`C:/Dev/StratAI-artifacts/ml_registry/...`). g3 compares a record's sha256 that differs on this checkout (probably line endings, like the fixed R16) | No: environment |

**0 regressions from the integration.** The suite does not pass. Its failures all need the environment of record or
data that `stratai_test` lacks.
