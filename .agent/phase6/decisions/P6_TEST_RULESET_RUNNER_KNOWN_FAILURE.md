# Known test failure: `test_runner_refuses_without_approved_rulesets` (documented 2026-10-08)

**Status: failing, not changed.**

**Test:** `tests/test_phase6_rulesets.py::test_runner_refuses_without_approved_rulesets` asserts that `scripts.phase6_playoff_track.require_rulesets(database)` raises `Blocked` with exit code 2.

## Why it fails

- **The fixture's real guarantee:** `database` cleans only the synthetic season 9997 (`DELETE FROM season_rulesets WHERE season = 9997`).
- **The test's actual assumption:** `stratai_test` holds **no** approved real 2024–2026 rulesets.
- **When that assumption held:** the test was written on 2026-10-05 (`27dd14a`), when no real ruleset was approved anywhere.
- **What changed:**
  - On 2026-10-08 Kanav approved the 2024–2026 v2 rulesets on serving (ids 4–6; `c782fc1`).
  - `stratai_test` was then rebuilt as a clone of serving (`phase5_isolated_db --replace`) for the P6-M1/PX-1 runs.
  - So the clone holds approved rulesets for every season `require_rulesets` needs. It returns them instead of raising.
- **Conclusion:** the code is right to return them. The test depends on database state it does not establish.

## Evidence that it predates the PX-1 audit changes

- **Same failure before the audit:** in a temporary worktree at `2c3ac80` (before any audit change), against the same `stratai_test`: `1 failed` with `DID NOT RAISE Blocked`.
- **Same failure after the audit:** the identical failure at `28a89e4`.
- **`require_rulesets` itself:** no audit commit touches it.
- **Reporting correction:** the batch run before committing `28a89e4` was **71 passed, 1 failed**. It was not a passing batch.

## Proposed fixture correction (proposal only; not implemented)

Make the test establish its own precondition instead of relying on the clone's state. Inside one transaction, rolled back at the end (or a dedicated empty `stratai_test_<suffix>` copy):
1. remove (or un-approve) the approved 2024–2026 rows;
2. assert `require_rulesets` raises `Blocked` with exit code 2;
3. assert the real rows are restored afterwards.

**Regression test:** the same test, run against a clone that **does** hold approved rulesets (today's `stratai_test`), must pass. A second assertion, that `require_rulesets` returns the three approved seasons when they exist, pins the other branch.

This would change test code, so it is a separate, focused change for Kanav's go-ahead. It must not weaken `tests/db_guard.py`.
