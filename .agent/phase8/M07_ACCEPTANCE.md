# P8-M7 — Cross-cutting quality: acceptance record

status: CONDITIONALLY ACCEPTED on local checks (2026-10-19); accessibility items (P8-R9) and A4 print (P8-R11) still OPEN
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | axe checks in the page tests (color-contrast and region are off in jsdom; contrast was computed separately by review R2, and the app-shell test enables region) |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | `scripts/phase8_live_smoke.py`: 24 API calls + 11 browser pages, ALL OK, exit 0 |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **axe reports no violations in the tested views.** MET in jsdom. Colour contrast was computed from the tokens by R2 and passes AA, except `--border`, which is now fixed with the `--input-border` token.
- **The live smoke records each operation's result.** MET (`runs/live_smoke.json`).
  - A 422 `validation_error` now fails the run.
  - A pre-switch-point analysis probe times a real model-free path.
  - Limitation (R3): the smoke's request bodies are its own copy, not the frontend's; the frontend's own requests are covered by the Vitest tests.
- **Every gap is recorded.** See below and `RISK_REGISTER.md`.

## Accessibility (review R2): fixed
- focus moves to `main` on navigation, and the page title comes from the h1 (tested);
- label explanations are reachable (tested);
- the Events navigation is current inside event, match and report pages;
- breadcrumbs are styled as links;
- input borders have at least 3:1 contrast;
- the coach-write status regions are persistent, and `aria-disabled` is used while busy;
- heading order is corrected;
- tables scroll with an edge cue instead of clipping;
- charts have a min-width and scroll;
- tabs use `replace`, and `aria-controls` is on the active tab only;
- link and control names are unique;
- the liveness tone follows the status;
- hints and the Teams-tab note are always shown;
- the session bar is a disclosure on phones, and the tab strip fades at the edge.

## Not done (P8-R9; corrected 2026-10-19 final audit to match the risk register, which lists five items)
- The tablist still activates automatically on arrow keys, which can fetch a slow tab.
- There is no sticky first column.
- The loading text, the comparison result and the pick list still use live regions that mount together with their content (only the coach writes were converted).
- The Evaluate, Rank-picks and Score-synergy buttons use `disabled` while busy, so focus drops.
- Chart tick text is about 7 px on phones (the values are in each chart's data table).
- A4 printing has not been verified with a PDF renderer (P8-R11).

## Performance
- One fetch per resource per key, and tabs fetch on first visit.
- Bundle: JS 418.74 kB (gzip 120.83 kB), CSS 16.07 kB, no source maps (`runs/frontend_build.txt`).
- Test reliability: with `maxWorkers: '50%'` (2026-10-19), 6 of 6 full runs passed (145 tests). Before it, there were intermittent failures under oversubscription (P8-R14).
- Slow routes live: candidates 3.74 s; analysis (raw EPA path) 8.24 s.

## Closeout 2026-10-19
- **The "Not done" items above are now fixed** (P8-R9 closed): manual tab activation, persistent status regions, `aria-disabled` plus a guard, a sticky first column, readable chart ticks.
- **Checks:** each has a test proven against the old code and was checked in real Chromium.
- **A4 print:** fixed and verified locally (P8-R11 open only for the model-populated content).
- **Frontend:** 165 passed, 3 of 3 runs.
