# Phase 7 — Mid-Phase Audit (after P7-M5)

date: 2026-10-18
scope: P7-M1 .. P7-M5, across milestones (prompts/MASTER_BUILD.md "Mid-Phase Audit")
method: an independent read-only audit (duplication, cross-milestone contract consistency, stale docs, hidden
assumptions, interface stability, dependency direction, lock integrity) plus the full suite, the lock check and
the contract tests.

## Result: stable after fixes. No high-severity finding. 4 medium and 4 low findings, all resolved or recorded.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | medium | The lock tool, two tests and the examples mechanism silently assumed `API_PREFIX` is empty: with a prefix, `check` failed for all 19 data operations, and examples would break /openapi.json | The lock builds the app unmounted (a lock is about shapes); examples resolve prefix-aware; the test checks the declared default, not the environment; the config comment no longer suggests `/api/v1`; a new test runs the lock check and example attachment under `API_PREFIX=/api` |
| 2 | medium | A future `as_of` was refused on the POST routes (P7-D1) but silently accepted on strength, event analysis, qualification forecast and discovery matches, with the same in-progress-event exposure | **P7-D4:** one rule on every route (`parse_as_of`): more than 5 minutes ahead is `invalid_as_of` (already declared, so the lock is unchanged). Tested on all four GET routes; no existing test used a future `as_of` (full suite) |
| 3 | medium | The same condition got different codes on different families (no scheduled time; no competition level; omitted context), and check order differs | Documented as intentional in docs/phase7.md "Notes for API clients" (the table and the check order). The codes are locked earlier shapes or engine-driven |
| 4 | medium | Naming inside Phase 7: `state_prov` vs `state_province`; strategy model identity nullable where it never can be null | **P7-D4:** renamed to `state_province`; made non-nullable (relock recorded, 4 changed entries) |
| 5 | medium | docs/phase7.md stale: the locked-operations table stopped at M4; a contract-test row was missing and rows were out of order; the 422 rule ignored the FastAPI-default exception; the OpenAPI description was from Phase 4 | All fixed: M5 row and the relock history; row added and sorted by date; rule reworded with the exception; API_DESCRIPTION refreshed |
| 6 | low | Duplicated constants and helpers: model_not_loaded code x4 with differing builders; as_of descriptions x2 + 4 inline; problems-message joining x2; test stub served models x3 | Consolidated: `api.routes.common` (CODE_MODEL_NOT_LOADED, model_not_loaded_error, AS_OF_DESCRIPTION, problems_suffix); `tests/phase7_support.stub_served_model`. Pre-Phase 7 view label constants left as they are (acceptable) |
| 7 | low | Interface stability: 22 human-input operations unlocked; two validation vocabularies | Documented ("Notes for API clients"); the human-input lock is decided at P7-M9 (recorded in PHASE_STATUS) |
| 8 | low | Lock write not atomic | `write_lock` writes a temp file and uses `os.replace` |

## Verified fine (audit)
- Lock: 7 revisions, all well formed (now 8, with the P7-D4 relock). Relocks cite existing decisions with dates.
  operationIds are unique. `check` passes, including with `API_PREFIX` set.
- Dependency direction: no `ml` module imports `api`; no new `data`→`ml`/`api` imports in Phase 7.
- Shared helpers live once (`parse_as_of`, `require_writer`, the write-token header), and the re-exports work.
- `model_not_loaded` and `event_not_found` are 404 everywhere; every operation declares 500 and uses the envelope.
- The milestone status table, PHASE_STATUS and RUNNING_NOTES agree; the M1 erratum is reflected everywhere.

## Verification after fixes
- Full suite: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest -q --tb=line -p no:cacheprovider` -> 5 failed,
  2365 passed, 5 skipped (8:01); pytest exit 1 from the 5 baseline failures only (same tests by name); 0 regressions.
- `python -m scripts.phase7_contract_lock check` -> exit 0 (also with API_PREFIX=/api).
- Type check / lint: not configured.

## Carried to the Phase-Level Audit
- The scheduled_time availability proxy (shared with the feature assembler).
- Recommend latency growth with coach observations (more than about 300 would exceed the budget).
- Human-input routes: lock or document as unstable (P7-M9).
- Write-once result records (latency) need a committed tree.

## Decision
Stable. Proceed to P7-M6.
