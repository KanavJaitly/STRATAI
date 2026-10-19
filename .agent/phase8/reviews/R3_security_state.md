# Phase 8 independent review — security, async state and test teeth

An independent subagent review (fresh context, read-only brief) of the uncommitted `phase8/build` working tree, returned 2026-10-19T03:38:40.068Z (UTC). Recorded verbatim from its final report. What was done about each finding: `REVIEW_DISPOSITION.md`.

---

## Phase 8 frontend review: security, reliability and test quality
  
  I found no high-severity problems. The write token is handled correctly and I found no XSS or open-redirect path. The confirmed findings are about stale results being shown as current, the risk of a duplicate coach write after a client-side timeout, and weak tests. I edited no files. `npx vitest run` passes (18 files, 96 tests), `npx tsc -b` is clean, and `npx vite build` succeeds with no source maps.
  
  ### Findings
  
  **1. Medium: a strategy comparison from an earlier moment or context is shown as current.** `frontend/src/dashboard/pages/StrategyLabPage.tsx:102`, `dashboard/strategy.tsx:208`
  - **Cause:** the workbench key is `${side}:${red}:${blue}` and does not include `asOf` or `context`, so `useOnDemand`'s `comparison.result` survives a change of moment or context.
  - **Scenario:** the user evaluates side by side, then applies a new `as_of` (or switches qualification to playoff). The recommendation reloads, but the old comparison stays under "Same model, same inputs".
  - **It also gets mislabelled:** while the new recommendation loads, `rec` is null, so `firstTitle` becomes "Baseline" although `result.first` was the AI recommendation.
  - **An older answer can still land:** a compare already in flight when the moment changes is not aborted, so it arrives later and is displayed.
  - **Fix:** add `asOf` and `context` to the key. Take `firstTitle` from what was actually sent, not from the current `rec`.
  
  **2. Low–Medium: synergy results outlive their inputs.** `dashboard/pages/AlliancePage.tsx:214-231`
  - The `SynergySection` result persists after `as_of` or the team text changes.
  - `SynergyView` shows neither `as_of` nor `team_numbers`, so a result for the old moment or teams passes for the new one.
  - **Fix:** reset on `asOf` or `teams` change (e.g. `key={asOf}`) and show `data.as_of` and `data.team_numbers`.
  
  **3. Medium: a timed-out coach write invites a duplicate.** `api/dashboard.ts:112,184,187`, `dashboard/refusals.ts:95`
  - Coach writes use the default 30 s timeout.
  - **Scenario:** the database is slow or locked. The client aborts at 30 s, but the server finishes and stores the record. The notice says "The API did not answer in time. **Retry.**" and the button is enabled again. The coach clicks and a second, non-idempotent record is stored (P8-Q8 says the writes are not idempotent).
  - The same applies to `network_error` after the request was sent.
  - **Fix:** use `timeoutMs: 0` (or a much longer timeout) for `write: true`. Show write-specific text for `timeout` and `network_error`: "the write may have been stored; check before submitting again".
  
  **4. Low: the timeout and cancellation stop covering the request once the headers arrive.** `api/http.ts:62-66`
  - The `finally` block clears the timer and removes the caller's abort listener before `response.text()`.
  - A response body that stalls hangs past the timeout, and a caller abort no longer cancels the download.
  - An error while reading the body (e.g. a connection reset) is thrown as a raw `TypeError`, not an `ApiRequestError`, so `ResourceView` shows no Retry button.
  - **Fix:** read and parse the body inside the guarded section, and map body-read errors to `network_error`.
  
  **5. Low: Phase 5 reads have no timeout.** `api/client.ts:98`
  - `timeoutMs: 0` is applied to every Phase 5 call, including GETs. The reason given is only the manual upload.
  - If the API hangs, the human-input pages show "Loading…" forever.
  - **Fix:** disable the timeout for `uploadManual` only.
  
  **6. Low: the write-access check can race.** `state/session.tsx:52-62`
  - `refreshAccess` runs on every keystroke in the token field and has no stale-response guard.
  - A late response for an earlier, partial token can leave `token_accepted` true while the token in memory is wrong, or the reverse.
  - Only the WriteGate UI is affected; the server still refuses.
  - **Fix:** use a sequence number or an AbortController, and debounce.
  
  **7. Low: Apply silently changes the moment.** `dashboard/asOf.tsx:12,16`
  - `isoToLocalInput` drops seconds, so a URL `as_of` of `…:30:45Z` shows as `…:30`.
  - Pressing Apply re-sends it as `:30:00`, a different moment from the one in the shared link.
  - **Fix:** add `step="1"` and keep the seconds, or skip `setAsOf` when the draft has not changed.
  
  **8. Low: a stale "Stored" confirmation.** `dashboard/coachInputs.tsx:51`
  - After a save, "Stored by X (sha…)" stays visible while the coach keeps editing the strategy, which suggests the current edits are saved.
  - **Fix:** clear `write.result` when the strategy prop changes, or compare the stored `strategy_sha256` with the current strategy.
  
  **9. Low: request bodies are typed by hand.** `api/dashboard.ts:168ff`
  - The file header says request types come from `generated.ts`. In fact the bodies are hand-written, although `RecommendBody`, `CompareBody`, `AssessBody`, `DraftStateBody`, `Hypothetical*Body`, `AllianceSynergyRequestBody` and `WinProbabilityByAlliancesRequestBody` exist there.
  - They match today, but tsc would not catch drift.
  - **Fix:** type the bodies with the generated interfaces.
  
  ### Test-strength gaps (confirmed by reading the tests)
  
  **Tests that exist but are too narrow**
  - `api/dashboard.test.ts:30-39`: "no token on reads" checks only `events` and `matchRecommend`. Accidentally adding `write: true` to `pickList`, `hypotheticalCompare` and so on would pass. Iterate over every `dashboardApi` method except the two coach writes.
  - `MatchPage.test.tsx:88-107` (coach save) never checks the POST's `X-StratAI-Write-Token` header or its body. Saving `aiStrategy` instead of the edited `coach`, or a wrong `match_key` or author, would pass. Assert the header and the body after an edit.
  
  **Code with no test**
  - **`RecordObservation`:** no test at all, including the `observed_at` local-to-ISO conversion, `component` being sent only for `component_unavailable`, and refusal display.
  - **Write refusals:** nothing checks that `write_not_authorized` or `invalid_coach_input` is shown, or that exactly one POST is made after a 5xx or timeout (no retry).
  - **`StrategyLabPage`:** no test file. A test would have caught finding 1.
  - **`useOnDemand`:** no tests (newer run supersedes older; `reset` aborts).
  - **`useResource`:** no test for abort on unmount, or for reload keeping the previous data.
  - **`AsOfControl`:** syncing the draft from the URL on back/forward is untested.
  
  **Contract test** (`tests/test_phase8_frontend_contract.py`)
  - It checks only (method, path), not query parameter names.
  - FastAPI ignores unknown query parameters, so if `as_of` or `configuration` were renamed on either side, views would silently show "now" while claiming a moment.
  - **Fix:** assert that each query key the dashboard sends is declared for its operation. They all match today.
  
  **Smoke script** (`scripts/phase8_live_smoke.py:140`)
  - It counts any declared 4xx code as ok. The strategy and prediction POSTs declare `validation_error` and `invalid_strategy` under 422, so a smoke request with a wrong body shape still reports ok. Treat 422 `validation_error` as a failure.
  - Its request bodies (`calls()`) are a hand copy of the dashboard's, so it does not test what the frontend actually sends.
  - **Weak coverage in the recorded run:** in `.agent/phase8/runs/live_smoke.json`, every model-backed route was refused with `model_not_loaded` in 0.02 s or less.
    - Analysis and recommend were never timed or exercised, and `pickList` stopped at `not_approved`. The slowest real call was `candidates` at 3.8 s.
    - So "analysis about 8 s and recommend about 2 s fit within 30 s" is plausible but not shown by this smoke, and the bracket-simulator pick list is not timed at all.
    - The coach writes were checked only as `writes_disabled`; the `write_not_authorized` path was never run.
  
  ### What is sound
  - **Write token:** held in module memory only; the field is `type=password`, `autoComplete=off`. Only the actor name and season go to localStorage.
    - It is never put in a URL and nothing logs it (no `console` calls).
    - The dashboard sends it only on the two coach writes. The Phase 5 client sends it on non-GETs plus the deliberate `write-access` probe.
  - **Build output:** `frontend/dist` has no token, no `VITE_*` secrets and no source maps.
  - **XSS:** there is no `dangerouslySetInnerHTML`. All API strings render as React text.
    - Route links encode keys with `encodeURIComponent` (`routing.ts`, `dashboardPath`, `buildPath`). The only data-built `href` is a numeric manual id (Phase 5).
    - The share URL is shown as text.
  - **Open redirects:** none; nothing navigates to a URL taken from data.
  - **`useResource`:** aborts on key change, reload and unmount, ignores stale responses (current flag plus token), never retries automatically, and its stale-overwrite test would catch removal of the guard.
  - **No render loops:** the setState-during-render patterns in `AsOfControl`, `StrategyWorkbench` and `EventPage`'s `useVisited` all converge after one extra render.
  - **Coach writes:** a synchronous `inFlight` ref plus a disabled button stop a double submit, and there is no automatic retry.
  - **`phase8_live_smoke.py` never writes:** it sends no token, and the server's `require_writer` dependency fails closed before the handler runs. The only DB-writing routes are the coach and human-input ones; it calls only reads otherwise.
    - Residual risk: if a fronting proxy injected the write header, the script's valid payloads would be stored. Point it at the API directly.
  - **`phase8_generate_api_types.py`:** deterministic and dependency-free, it escapes `*/` in doc comments, and its drift is checked by the contract test.
