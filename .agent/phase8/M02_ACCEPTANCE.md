# P8-M2 — Event dashboard: acceptance record

status: CONDITIONALLY ACCEPTED on local evidence (2026-10-19); model-backed parts seen as refusals only; environment of record BLOCKED
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `EventsPage.test.tsx` 5, `EventPage.test.tsx` 5, `EventPage.history.test.tsx` 2 (D1.6: tab history) |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | pages `events`, `event`, `event_teams`, `event_matches` and `event_forecast` OK. Analysis and forecast return `model_not_loaded` (declared) at the default moment. Analysis before the switch point is served with raw EPA: 200 in 8.24 s |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **Each section is fed by its route.** MET. Tabs fetch on first visit:
  - Rankings and contenders: `/analysis`;
  - Teams: `/teams`;
  - Matches: `/matches`;
  - Forecast: `/qualification-forecast`.
- **`model_not_loaded` and `epa_source_*` render as unavailable states, with the reason.** MET: there are fixture tests, and live, `model_not_loaded` is shown with its code.
- **The ordering shows its model (raw EPA / M5 v2) and the switch point.** MET in fixtures. Live, at a moment before the switch point (the smoke probe), the API serves the raw-EPA ordering.

## Gaps
- The M5 v2 ordering and the forecast are not seen with a real model (environment of record).
