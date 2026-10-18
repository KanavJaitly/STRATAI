# P7-M9 — Documentation, contract tests and sign-off: acceptance record

status: the scope verifiable on this machine is COMPLETE. Two of its acceptance criteria are not met here:
- the full suite in the environment of record is BLOCKED (environment, P7-Q5; the same blocker as P7-M8);
- phase acceptance by Sven Morais or Kanav is PENDING. A proposal is in
  decisions/P7_PHASE_ACCEPTANCE_PROPOSED_2026-10-18.md (renamed on approval, see the addendum).

spec: docs/P7Milestones.md P7-M9 (frozen)
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Scope (spec) and evidence
- **docs/phase7.md complete for every endpoint** (method, path, parameters, body, response fields and semantics,
  success and error codes, missing-data behaviour, examples, dependencies): DONE, with examples BLOCKED.
  - An independent docs-completeness review compared all 22 in-scope operations against the live OpenAPI document.
  - Its gaps were fixed: the pick-list codes; the coach-write 201 bodies and schemas; the assess body; the ranking,
    synergy and win-probability fields and missing-data rules; strength's missing-data rules; a dependency table;
    stale text.
  - Examples: the runbook and tooling are documented; real captures are BLOCKED (P7-M8).
- **The shape lock covers every core endpoint:** DONE. 24 operations: the 22 in scope plus the two probes.
  `python -m scripts.phase7_contract_lock check` exits 0.
- **Phase-Level Audit:** DONE (PHASE_ACCEPTANCE.md). Its Phase 7 findings are fixed under P7-D6, and every fix has a
  regression test that fails with the fix removed (see below).
- **Phase Acceptance Review:** DONE (PHASE_ACCEPTANCE.md). Its findings outside Phase 7 are in the risk register,
  with owners.
- **PHASE_ACCEPTANCE.md:** WRITTEN.

## Acceptance criteria (spec)
- **P7-DM1 (with refusal-only features reported as such) and P7-DM2 evaluated honestly:** DONE.
  - DM1: NOT MET. There are no examples, and alliance selection is refusal-only, deferred with P6-DM1.
  - DM2: a checkable control exists; it is not yet demonstrated as an enforced, committed, routine check.
- **The full suite on an isolated copy in the environment of record, with any environment-only failures named:**
  BLOCKED (environment).
  - The run on Sven's machine (isolated stratai_test, not the environment of record): 5 failed, 2483 passed,
    5 skipped, 1 xfailed; pytest exit 1.
  - The 5 failures are the named baseline failures; 0 regressions.
- **Phase acceptance by Sven Morais or Kanav:** PENDING. Not recorded as given.

## Regression evidence for the P7-D6 audit fixes (2026-10-18)
Each fix's test passes with the fix in place, and fails when the pre-fix behaviour is planted back. The planted
files were restored byte-identical (verified with `cmp`).

| P7-D6 item | Fix | Test | Planted pre-fix behaviour | Result |
|---|---|---|---|---|
| 1a | strategy match routes at min(now, scheduled) | test_phase7_strategy_api::test_an_upcoming_match_is_evaluated_now_never_at_its_future_time | context at the scheduled time | 1 failed |
| 1b | match win probability at min(now, scheduled) | test_phase7_pre_match_report_api::test_an_upcoming_match_is_predicted_now_never_at_its_future_time | moment = scheduled_time | 1 failed |
| 2 | examples tooling under API_PREFIX | test_phase7_examples::test_capture_and_validation_work_under_an_api_prefix | served_path ignores the prefix | 1 failed |
| 3 | smaller corrections (imports, next_captain, docs, .env.example, comment, row reuse) | AST unused-import scan clean; test_phase7_alliance_selection_api (67 tests, including the captain-rule state) | — | covered by the suites |

The three tests existed before the final full run started (file times 15:40–15:41; the run ended at 15:57 after
about 10.4 minutes), so they are part of its 2483 passed.

## Decision
NOT fully accepted: the environment-of-record suite is BLOCKED and human phase acceptance is PENDING. Everything else
in P7-M9's scope is complete, with the evidence above.

## Addendum (2026-10-18): phase acceptance recorded
Sven Morais approved conditional phase-level acceptance on 2026-10-18
(`decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md`, the former `P7_PHASE_ACCEPTANCE_PROPOSED_2026-10-18.md`, renamed on
approval; his decision is recorded verbatim). That closes P7-M9's "phase acceptance by Sven Morais or Kanav"
criterion, conditionally.
- The environment-of-record full-suite criterion stays DEFERRED, with P7-M8.
- This record's text above is kept as it was at writing.
