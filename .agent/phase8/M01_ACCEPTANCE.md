# P8-M1 — Frontend foundation: acceptance record

status: CONDITIONALLY ACCEPTED on local evidence (2026-10-19, as directed by Sven Morais; see PHASE_ACCEPTANCE.md); environment of record BLOCKED
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `http.test.ts` 9, `dashboard.test.ts` 8, `client.phase8.test.ts` 6, `useResource.test.tsx` 5, `useOnDemand.test.tsx` 3, `display.test.tsx` 15, `App.test.tsx` 10 (including the legacy-path redirects and the Overview links), `OverviewPage.unknownInput.test.tsx` 1 (the D1.2 ruling), `session.race.test.tsx` 1 (D1.4), `StatusPage.test.tsx` 2, `asOf.test.tsx` 3 |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | yes: `runs/live_smoke.json`, `/health` and `/ready` 200, status page rendered |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **The types drift test passes.** MET:
  - `scripts/phase8_generate_api_types.py --check` exits 0;
  - `tests/test_phase8_frontend_contract.py::test_the_generated_types_are_current` passes.
- **The endpoint contract test passes.** MET, through a separate registry and test (P8-D1 D1.1):
  - `tests/test_phase8_frontend_contract.py`: 6 passed;
  - `tests/test_frontend_api_contract.py`: 3 passed, unchanged.
- **Client behaviour is tested** (abort, timeout, stale, envelope, network, malformed). MET:
  - `http.test.ts` covers the envelope, network, timeout (including during the body read), malformed and abort cases;
  - `useResource.test.tsx` covers stale responses, abort on unmount and reload keeping data;
  - `useOnDemand.test.tsx` covers supersede, reset and unmount;
  - `dashboard.test.ts` checks that no read sends the token (all 21 non-write methods, enumerated), that the write header and body go out, the query-parameter guard, and that writes have no client timeout.
- **The existing human-input pages and their 32 tests are unchanged.** MET: the 32 tests are byte-identical and pass.
  - The routes moved under `/inputs` with redirects (D1.2). The redirects and the Overview's old-path links are tested, and checked in a real browser.
  - `client.ts` now uses the shared core (D1.3). Reads time out after 30 s. Writes and the upload never time out: this was corrected on 2026-10-19 after the first build timed writes out, and `client.phase8.test.ts` covers it.

## Notes
- **Refusals:** the refusal map is `src/dashboard/refusals.ts`, and absence reasons are mapped in `src/dashboard/labels.ts` (D1.7).
- **URL state:** `as_of` (to the second; Apply with no change keeps the exact URL instant), `tab` (replace, D1.6), `season`, `side`, `config` and the pairing.
