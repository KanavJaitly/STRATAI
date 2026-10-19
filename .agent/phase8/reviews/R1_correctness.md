# Phase 8 independent review — contract and probability correctness

An independent subagent review (fresh context, read-only brief) of the uncommitted `phase8/build` working tree, returned 2026-10-19T03:36:54.604Z (UTC). Recorded verbatim from its final report. What was done about each finding: `REVIEW_DISPOSITION.md`.

---

## Phase 8 dashboard review: API contract and probability/label correctness
  
  I found no high or medium findings. The API contract and the probability handling are correct. I found 4 low-severity issues (3 mislead, 1 departs from the spec). `npx tsc -b` is clean and `npx vitest run` passes (18 files, 96 tests). I edited nothing and committed nothing.
  
  ### Confirmed findings
  
  **1. Low: a played match with no recorded winner is counted as a loss**
  - Where: `frontend/src/dashboard/pages/TeamPage.tsx:373-375,134` (in the concatenated listing I read, these are lines 123-125 and 134 of the file).
  - What happens: `HistoryView` computes `lost = played.length - wins - ties`. `MatchResultOut.winning_alliance` is `string | null` ("null only when the record has no winner").
  - Scenario: a played match with `winning_alliance: null` shows up in "N played: … lost". That turns a null into a loss.
  - Fix: count `losses` explicitly as `winning_alliance` equal to the opposing colour. Report the null-winner matches separately, e.g. "1 without a recorded winner".
  
  **2. Low: validation labels are not shown verbatim**
  - Where: `frontend/src/dashboard/display.tsx:24` renders `validation.status.replaceAll('_', ' ')`. The `title` (line 23) shows the explanation for known labels, so the raw code appears nowhere on the page.
  - Why it matters: P8-Q4 and P8-Milestones say labels are "shown verbatim / as served". `validated_playoff_success` and `validated_playoff` still render differently ("validated playoff success" vs "validated playoff"), so they are not merged. But the served string is not displayed.
  - Fix: render `{validation.status}` as-is, e.g. in `<code>`. Keep the plain-language text in the title or beside it.
  
  **3. Low: the `insufficient_features` explanation is wrong for one documented case**
  - Where: `frontend/src/dashboard/refusals.ts:29-30` (line 217 in the concatenated listing).
  - Scenario: `/predictions/matches/{m}/win-probability` returns 422 `insufficient_features` when "a match has no scheduled time" (`docs/phase7.md:353`). The UI then says "No evidence: every team involved has no features at all". The server's own message is still shown underneath.
  - Fix: change the explanation to cover both cases ("…or the match has no scheduled time").
  
  **4. Low: the report hardcodes a validation status the response does not carry there**
  - Where: `frontend/src/dashboard/pages/ReportPage.tsx:115-116`. The static text says roles are "evaluated by the not-validated P6-M10 model".
  - Why it matters: P8-M6 acceptance requires every field to trace to the response. This is a client-asserted label that would go stale if the served status changes. The odds next to it already show the served `validation` through `OddsView`.
  - Fix: drop "not-validated" from the static text, or take it from `plan.odds.validation.status`.
  
  ### Checked and found correct
  - **Endpoints and parameters:** I compared all 23 `DASHBOARD_ENDPOINTS` with `api_contract_lock.json`. Methods, paths, query params and request bodies all match.
    - `as_of` is sent only on routes that take it. The scheduled-match strategy routes and the match win-probability route correctly take none.
    - `configuration` is a repeated query key.
    - `match_context` is always set on hypothetical routes.
    - The draft state matches `DraftStateBody`.
    - The `Strategy`/`RobotPlan` editor rules (role, target, components, teleop needs the scoring role) mirror the engine. The server still validates.
    - The coach bodies match `docs/phase7.md`: `component` is omitted for `robot_unavailable`, the token goes only on writes, writes are never retried, and double submits are blocked by a ref guard.
    - The ranking endpoint is deliberately not called.
  - **`as_of`:** it is sent as `toISOString()` (a `Z` offset, which the docs allow) and URL-encoded. A future `as_of` is left to the server, and its refusal is shown.
  - **Probabilities:**
    - Strategy and playoff odds are only `StrategyOdds.display` strings.
    - M6/M7 values come only from `CalibratedWinProbability`. `Math.round(v*100)` on the 0.05 grid in [0.05, 0.95] is exact.
    - The unvalidated value is always tagged "Unvalidated model output", with its reason, a separate style (dashed or dotted) and "not a validated probability".
    - Validated and unvalidated values are never conflated. The legacy `red_win_probability` / `unvalidated_red_win_probability` fields are never read.
    - P6 odds and M6/M7 values never share a field or a panel.
    - Nothing compares probabilities; sorting is only over candidate factors and team numbers.
  - **Labels:** `PickListResponse.probability_status` is shown as served, and the two playoff labels have separate explanations.
  - **Nulls:** `Measure`, `FactorOut`, `score`, `value`, `result`, `recommended`, `baseline`, `display` and the optional arrays (`reasons`, `validation_flags`, `*_axes_used`, `components`) are all guarded. Absences render as "—" with a reason, never as 0. Charts list missing points rather than plotting zero. The `validation_status ?? 'descriptive'` fallback matches the server default (`ml/views/strength.py:95`).
  - **Pre-match report:**
    - All six `not_produced` items render as "not produced by any engine" absences with their `semantics`.
    - Nothing is derived; strategy roles come from `recommended`, or the labelled `baseline`.
    - The `absent_code` is shown for the win probability, the strategy and synergy.
    - The report's `as_of` and `side` are in the URL.
  - **Refusals:** every error code in the contract lock is mapped except `service_unavailable`, which falls back to a "failure" state that still shows the code, message and request id.
  - **Sample data:** the fixtures (`src/test/dashboardFixtures.ts`, `src/test/mockApi.ts`) are imported only by test files. No sample data ships in non-test code; the only literals are input placeholders.
  - **Fetch hooks:** `useResource` and `useOnDemand` abort on unmount or parameter change, ignore stale responses and never retry automatically. `http.ts` gives typed timeout, network and malformed-response errors.
