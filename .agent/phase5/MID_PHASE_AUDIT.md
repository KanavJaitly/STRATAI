# Phase 5 mid-phase audit (after P5-M1, M3, M2, M4, M5, M7; before M6, M8, M9, M10) — 2026-10-03

## Full regression
- **Run on an isolated template copy (`stratai_test`), never the serving database.** The first attempt's
  command was malformed (an unsupported `--timeout` flag with stderr suppressed) and produced no result.
  It was rerun.
- **Result:** 1,732 passed, 3 skipped, **2 failed**, both in tests/test_metrics_docs_contract.py.
  1. `test_documented_endpoints_are_exactly_the_live_ones`:
     - The Phase 5 endpoints are not on the Phase 3 metrics page.
     - Fix: they are scoped out (`PHASE5_PATHS`), as Phase 4's ML endpoints are. Phase 5 documents them in
       docs/phase5.md and pins them in P5-M10's contract tests.
  2. `test_reliability_score_placeholder_caveat_reaches_the_served_schema`:
     - A real gap, not only a scoping one. The P5-M3 strength view and the P5-M4 team comparison serve Phase 3's
       interim `reliability_score` without its INTERIM caveat.
     - Fix: both endpoint descriptions now carry it, and P5-M10's contract test will pin it.
- **After the fixes:** the contract, API foundation, strength and event-analysis tests pass (106).

## Compile / type / lint
- `python -m compileall` over api, data, database, ml, scripts and tests: OK.
- No type checker or linter is configured in this repository, so those gates are not configured (as in Phase 4).

## Duplication search
- **`canonical` JSON in ml/ratings/live_snapshots.py duplicated `ml/ratings/d18_source._canonical`.** It now
  delegates (identical bytes, so snapshot ids are unchanged). `scripts/sync_statbotics_snapshot._canonical` is
  pinned Phase 4 evidence and left alone.
- **A test DB-isolation guard was duplicated** in tests/test_live_epa_root.py. It now reuses
  tests/test_live_epa._isolated_db_name.
- **`parse_as_of`** has one implementation (api/routes/strength.py), reused by the P5-M4 and P5-M5 routes.
- **API error helpers** have one implementation (api/routes/common.py).

## Spec conformance so far

| Milestone | Status | Note |
|---|---|---|
| P5-M1 | ACCEPTED | |
| P5-M3 | ACCEPTED | |
| P5-M4 | ACCEPTED | (b) measured: M5 v2 is served after the switch; (c) no improvement claimed |
| P5-M5 | ACCEPTED | (b) coverage 0.8532 is outside [0.75, 0.85], so the range is served `not_validated` |
| P5-M2 | NOT ACCEPTED | Open decision Q1. L3 and L4 passed (L4 on a labelled rerun after a sub-check defect) |
| P5-M7 | NOT ACCEPTED | Open decision Q2. (a) passed, 106,390 of 106,390 |

Every write-once record carries its commit and frame or snapshot hashes. No result was recomputed except the L4
rerun, whose superseded record is kept.

## Process deviations found
- **Committing while a long acceptance run was in progress would have corrupted provenance.** `write_once`
  records HEAD at the end of the run. Practice from P5-M4 on: no commits and no tracked-file edits while a
  recorded run is in progress. Untracked new files are safe.
- **P5-M3 missed pinning its new endpoint** in tests/test_api_foundation.py. Caught at P5-M2's regression and
  fixed.

## Remaining
- **P5-M6:** replay plus the `team_metrics` recompute during watch.
- **P5-M8 and P5-M9:** infrastructure, Q3 and the human inputs.
- **P5-M10.**
- **The phase-level audit.**
