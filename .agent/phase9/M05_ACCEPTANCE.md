# P9-M5 — Dashboard briefing panel: acceptance record

status: ACCEPTED on fixture evidence (2026-10-20); not checked in a browser against the live API in this phase

| Verification state | Result |
|---|---|
| Implemented | `frontend/src/dashboard/briefing.tsx`, `briefingText.ts`, the panel on `ReportPage.tsx`, `dashboardApi.briefing` |
| Tested (synthetic) | `briefing.test.tsx`: 8 passed. Fetched only on request, with the report's own `as_of` parameter, with a notice if the moments differ. "Fixed layout" gives the reason in words and as a code, and says whether a model was called. "Arranged by a language model" names the model. Text is rendered as text (an `<img>` payload stays text). Refusals are shown. Axe is clean in both modes (review R2 C8 fixed) |
| Frontend suite (final) | vitest 173 passed (29 files), exit 0; tsc 0; oxlint 8 warnings (the baseline; a new one was removed by moving `fallbackText` to its own module); build 0 |
| Accepted | YES, on fixtures |

## Acceptance criteria
- **Both modes and an unavailable briefing are tested, with axe.** MET.
- **The print layout keeps the briefing.** MET once it is loaded: the panel prints. Before it is requested it is `no-print`, so an unrequested button is not printed. This is a deliberate reading: the briefing is fetched on request (P9-R7).
- **It never replaces or alters served values.** MET. It is a separate section. The report footer says the report has no LLM-written item and the briefing can only be arranged by one.
