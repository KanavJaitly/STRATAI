# P8-M3 — Team profile: acceptance record

status: CONDITIONALLY ACCEPTED on local evidence (2026-10-19); environment of record BLOCKED
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `TeamPage.test.tsx` 5 (including a match without a recorded winner, which is not counted as a loss) |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | page `team` OK: `/strength` 200 (0.14 s), `/metrics` 200; screenshot reviewed |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **Absent values show their reasons.** MET. A reason is mapped to plain text (D1.7) and stated once when the whole section shares it, e.g. "EPA withheld: no EPA yet: the team has no completed earlier event". Per the D1.7 ruling (2026-10-19), the raw served code is shown as visible secondary text after the plain words; this is tested and checked in a real browser.
- **Charts plot only served values,** with labelled axes and units and a text summary. MET:
  - each chart has `role=img` with a summary, and a data table;
  - missing points are listed as missing, never drawn as 0;
  - on narrow screens a chart scrolls rather than shrinking (min-width 420 px).
- **Played, won, tied and lost are counted explicitly,** and matches without a recorded winner are reported separately (R1-1).
