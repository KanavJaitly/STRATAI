# P8-M4 — Match strategy view: acceptance record

status: CONDITIONALLY ACCEPTED on local evidence (2026-10-19); no AI strategy on real data; NO successful live coach submission
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `MatchPage.test.tsx` 9, `StrategyLabPage.test.tsx` 3, `coachInputs.test.tsx` 7, `liveRegions.test.tsx` 2 |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | pages `match` and `strategy_lab` OK. Every strategy route returns `model_not_loaded` (declared); the M6/M7 routes return `model_not_loaded`. Coach writes without a token return 403 `writes_disabled`. **A successful coach write against the live API was deliberately not performed**, so no rows were stored in `stratai_test` |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **Both paths are shown identically.** MET in fixtures: one `compare` call; both sides go through the same `AssessedStrategy`; the label is shown verbatim, with "Same model, same inputs".
- **`selection_note` is shown.** MET (fixture test).
- **A playoff context and missing inputs render the engine's null odds with reasons.** MET in fixtures (`OddsView` "No probability" plus reasons).
- **Writes are gated.** MET:
  - `WriteGate`;
  - a token header only on the two writes (enumerated test);
  - body equality is tested;
  - a double click stores once;
  - a refusal (`write_not_authorized`) is shown, with no second POST;
  - after a network failure, a "may have been stored" warning is shown and nothing is retried;
  - there is no client timeout on writes (D1.5).
- **`model_not_loaded` renders as unavailable.** MET, live and in fixtures.
- **A save in flight survives edits** (R4-1). Regression tests are proven against the planted bugs (`reviews/REVIEW_DISPOSITION.md`): it stays busy, there is no second POST, and the outcome says that later edits are unsaved. Tested. The saved body is the edited coach strategy, asserted through the match page.
- **A stale comparison is cleared when the moment or context changes** (R3-1). Tested; a planted bug made the 2 tests fail.
- **Regression:** a real bug, the coach editor staying empty when the alliances loaded late, was fixed and is tested.

## Gaps
- No real strategy model is available, so the AI recommendation, compare and odds were never seen on real data.
- A live successful coach write was not run.
