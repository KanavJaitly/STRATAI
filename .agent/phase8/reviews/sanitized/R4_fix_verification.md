> **SANITIZED DERIVATIVE, NOT THE VERBATIM ORIGINAL.** This was made on 2026-10-19 from the local evidence
> file `.agent/phase8/reviews/R4_fix_verification.md` (git blob `dfd13fc77fd0896d08629a76f1b9643e57053547`). The original stays local as evidence and is
> excluded from the commit candidate; this derivative is the copy proposed for the commit. Only one thing changed: 2 local scratchpad path(s), which contained the machine's username
> and session id, were replaced with `<local-scratchpad>`. Every finding, verdict and other word is
> unchanged.

# Phase 8 independent review — verification of the R1–R3 fixes

An independent subagent (fresh context, read-only; no backend or DB commands) checked every R1–R3 finding against the code and tried to break the fixes. Returned 2026-10-19T04:04:04.618Z (UTC). Recorded verbatim. The response to its new issues is at the end of `REVIEW_DISPOSITION.md`.

---

## Phase 8 adversarial verification of the R1/R2/R3 findings (read-only)
  
  I edited, created, staged and committed nothing in the repo. I ran no backend, pytest or DB commands. My only output files are in `<local-scratchpad>/verify/`. `.agent/phase8/reviews/REVIEW_DISPOSITION.md` is referenced by the review files but did not exist when I checked, so I judged every finding from the code itself.
  
  **Bottom line:** 30 of the 40 items are fixed (R1 4/4, R2 13/18, R3 8/9, test gaps 5/9). The rest are partial or not fixed, and two of the fixes introduced new problems (new issues 1 and 2 below).
  
  ### Verdicts
  | # | Verdict | Evidence |
  |---|---|---|
  | R1-1 null winner counted as loss | FIXED | `TeamPage.tsx:139-152` counts losses explicitly and reports "N without a recorded winner". Test: `TeamPage.test.tsx:56`. |
  | R1-2 labels not verbatim | FIXED | `display.tsx:103-104` renders `{validation.status}`. Tests: `display.test.tsx:36` (`validated_playoff_success` and `validated_playoff` checked by exact text, with separate PX-4/PX-2 titles), `:47` (unknown label shown verbatim). |
  | R1-3 `insufficient_features` text | FIXED | `refusals.ts:29-31`. No test. |
  | R1-4 hardcoded "not-validated" | FIXED | `ReportPage.tsx:137-138`. Odds come from the served `OddsView`. |
  | R2-1 focus and page title | FIXED, with new issue 2 | `App.tsx:65-79`, `common.tsx:14-18`. Test: `App.test.tsx:41`. |
  | R2-2 explanation only in a tooltip | FIXED | Badge is a button with `aria-expanded`, `aria-describedby` and an inline explanation (`display.tsx:91-112`). Test: `display.test.tsx:113`. |
  | R2-3 closed `<details>` not printed | FIXED | `ReportPage.tsx:73-85` opens them on `beforeprint`. Test: `ReportPage.test.tsx:85`. |
  | R2-4 input borders too faint | FIXED | `--input-border` in `dashboard.css:9,14,19,21`. I computed about 3.7:1 (light) and 4.5:1 (dark) against the surface. |
  | R2-5 breadcrumb links look like text | FIXED | `dashboard.css:41`. |
  | R2-6 live regions and busy buttons | PARTIAL | Only the coach writes changed (status region always mounted, `aria-disabled`), and new issue 1 undercuts even that. Still unchanged: `PickListView` `aria-live` mounts with its content (`AlliancePage.tsx:166`), and so does `ComparisonResult` (`strategy.tsx:220`). "Evaluate side by side" (`strategy.tsx:200`), "Rank picks" (`AlliancePage.tsx:156`) and "Score synergy" (`:229`) still use `disabled` while busy, so focus is still dropped. |
  | R2-7 chart text at 390 px | PARTIAL | `.chart-svg{min-width:420px}` (`dashboard.css:131`) scales 11 px ticks to about 7.2 px. The data table is still collapsed by default. |
  | R2-8 heading order | FIXED | `StrengthView level={3}` (`TeamPage.tsx:59-65`, `ReportPage.tsx:224`). Not-produced items sit under their own h3 (`ReportPage.tsx:146,194`). |
  | R2-9 raw codes as explanations | PARTIAL | The `reasonText` map and plain refusal text are in. EPA reasons are stated once on TeamPage and the report. But the event "Team comparison" still repeats the reason in every EPA cell (`EventPage.tsx:143`), and the raw code is now visible nowhere (only in `title` and `data-reason`). R2 asked to keep it in small print. |
  | R2-10 tables clip at 390 px | PARTIAL | `.table-scroll > table.grid{display:table}`, a min-width and scroll shadows (`dashboard.css:161-174`). Tables outside `.table-scroll` still switch to `display:block` below 720 px: the chart data table (`charts.tsx:137`) and the EPA provenance table (`MatchPage.tsx:205`). |
  | R2-11 tab behaviour | PARTIAL | `replace:true` (`useTab.ts:14`) and `aria-controls` only on the active tab (`common.tsx:200`) are fixed. Arrowing across tabs still activates them and fetches each one's data. No test checks history or `replace`. |
  | R2-12 header height, tab overflow cue | FIXED | Session toggle and tab fade (`App.tsx:30-36`, `dashboard.css:60-63,141-148`). Minor: the fade still covers the last 24 px when the strip is scrolled fully right. |
  | R2-13 nav marks no item active | FIXED | `App.tsx:73,89`. Test: `App.test.tsx:54`. |
  | R2-14 repeated control names | FIXED | `EventPage.tsx:230`, `strategy.tsx:123`, `ReportPage.tsx:177`. |
  | R2-15 Liveness always green | FIXED | `StatusPage.tsx:19`. |
  | R2-16 warning not announced, button unexplained | FIXED | `AlliancePage.tsx:63` (`role=status`), `StrategyLabPage.tsx:84`. |
  | R2-17 Moment control on Teams tab | FIXED | A note is shown instead (`EventPage.tsx:60`). |
  | R2-18 empty coach editor | FIXED | Regression test `MatchPage.test.tsx:109`. |
  | R3-1 stale comparison | FIXED | The key includes `context` and `asOf` (`StrategyLabPage.tsx:102`). `comparedTitle` records what was sent (`strategy.tsx:150,203`). An in-flight compare is aborted on unmount. Tests: `StrategyLabPage.test.tsx:45,59`; both fail if `asOf`/`context` are dropped from the key. |
  | R3-2 synergy outlives its inputs | FIXED, no test | `key={asOf}` and reset on typing (`AlliancePage.tsx:71,228`). It shows `team_numbers` and `as_of` (`:232`). The section is not keyed on `eventKey` (low). |
  | R3-3 timed-out write invites a duplicate | FIXED, with new issue 1 | `timeoutMs: 0` for writes (`dashboard.ts:224`) and an unknown-outcome warning (`coachInputs.tsx:21-31`). Tests: `dashboard.test.ts:99`, `coachInputs.test.tsx:84`. |
  | R3-4 body read outside the timeout | FIXED, no test | `http.ts:54-68`. |
  | R3-5 Phase 5 reads have no timeout | FIXED, no test | `client.ts`: `timeoutMs: 0` only on `uploadManual`. |
  | R3-6 write-access check race | PARTIAL | A sequence guard fixes the race (`session.tsx:52-61`). There is no debounce or abort, so one probe is still sent per keystroke. No test. |
  | R3-7 Apply changes the moment | FIXED | `step={1}`, seconds kept, unchanged draft skipped (`asOf.tsx:122,129`, `asOfParams.ts:154`). Tests: `asOf.test.tsx:26,48`. |
  | R3-8 stale "Stored" confirmation | FIXED, but REGRESSED elsewhere | `key={JSON.stringify(coach)}` (`MatchPage.tsx:175`) clears it on edit, but causes new issue 1. No test. |
  | R3-9 hand-typed request bodies | FIXED except the coach bodies | Engine bodies use the generated types. The coach bodies are still hand-typed (`dashboard.ts:281-285`) although `CoachObservation` exists in `generated.ts:130`. |
  | Gap: no-token test too narrow | FIXED | It now iterates every method and asserts the list is complete (`dashboard.test.ts:43-77`). |
  | Gap: MatchPage coach save not checked | PARTIAL | The header and body are checked only in the isolated `coachInputs.test.tsx:71`. No MatchPage test edits the strategy and then checks the POST body, so passing `aiStrategy` instead of `coach` would go unnoticed. |
  | Gap: `RecordObservation` untested | FIXED | `coachInputs.test.tsx:28,45,57`. |
  | Gap: write refusals and no retry | MOSTLY FIXED | `write_not_authorized` and network-error single POST are tested. `invalid_coach_input` and the 5xx path are not. |
  | Gap: `StrategyLabPage`, `useOnDemand`, `useResource`, `AsOfControl` back/forward | FIXED | New test files and cases (listed in the test run). |
  | Gap: contract test ignores query keys | FIXED (read, not run) | `test_every_query_parameter_the_dashboard_sends_is_declared` checks both directions. `call()` also enforces it at runtime. |
  | Gap: smoke counts 422 `validation_error` as ok | FIXED | `phase8_live_smoke.py:141-142`. Its request bodies are still a hand copy (NOT FIXED, now documented). |
  | Gap: smoke coverage | NOT FIXED | The recorded `live_smoke.json` (23:54) still refuses every model route with `model_not_loaded`. Recommend and pick list are never timed. The writes hit only `writes_disabled`, never `write_not_authorized`. Only `eventAnalysis` was timed (8.24 s). |
  
  ### New confirmed issues (by severity)
  1. **Medium: the `SaveCoachStrategy` remount (the R3-8 fix) loses an in-flight write's outcome and re-enables Save mid-write.**
     - `key={JSON.stringify(coach)}` remounts the component on every editor change, and the editor is not locked while saving.
     - Scenario: the coach clicks Save. Writes now have no timeout, so it may be slow. The coach then toggles a checkbox. The old instance unmounts, so its result, its refusal (e.g. `write_not_authorized`) or its "may have been stored" warning is never shown.
     - The new instance has a fresh `inFlight` ref, so Save is active again. Toggling back to the same strategy gives the same key on a new instance, so an identical second record can be stored while the first is still pending.
     - Found by reading the code; I could not write a test without touching the repo. No test covers it.
  2. **Medium (accessibility): `.live-status:empty{display:none}` (`dashboard.css:175`) undoes the always-mounted live region.**
     - The coach status regions (`coachInputs.tsx:66,122`) render no child nodes when idle, so they match `:empty`. They are then `display:none` and out of the accessibility tree.
     - The first message makes the region appear together with its text, which is the same "inserted with its content" pattern R2-6 reported. jsdom cannot catch this.
  3. **Low-medium: stale `document.title` (new with the R2-1 fix).**
     - The `/inputs/*` pages (Overview, GameSpec, Profiles, Review) never set a title. After visiting e.g. System status, they keep "System status · STRATAI".
     - `ReportPage` sets its title only once the data arrives (`ReportPage.tsx:160`). While it loads, or when it is refused (e.g. `match_not_scheduled`), the tab keeps the previous page's title. Before this change the title was a generic but correct "STRATAI".
  4. **Low: one `reasonText` mapping overclaims.**
     - `no_prior_concluded_event_epa` becomes "no EPA yet: the team has no completed earlier event" (`labels.ts:44`).
     - The backend's meaning (`ml/ratings/live_epa.py:307`, `assembler.py:554-560`) is "no qualifying prior event with an available EPA". It also covers a team whose completed prior event has no servable EPA (no Statbotics row, or skipped as not yet available under `d18_skip`), so the UI states something false in those cases.
     - The other mappings match the backend: `not_scheduled_before_as_of` (`discovery.py:125`), `no_scheduled_time`, `not_played`, the `strength.py` codes (including `fewer_than_N`), the `insufficient_data:` prefix and both alliance-incomplete forms. Unknown reasons pass through verbatim.
     - Lookups use a plain object, so a reason of `constructor` or `toString` would return a function and its text would not render. The backend does not emit these today.
  5. **Low:** the busy coach buttons get no visual change from `aria-disabled` (only `button:disabled` is styled), apart from the "Saving…" text.
  6. **Low:** in browsers, the badge-button's accessible name includes the CSS `::after` " ⓘ", so it becomes "validated_playoff_success ⓘ". jsdom ignores generated content, which is why the test sees the bare label.
  
  ### Checked and found sound
  - **Badge button placement:** it is never nested inside another interactive element. The one `<summary>` use passes `interactive={false}` (`ReportPage.tsx:222`).
  - **`hideReason` usage is safe:**
    - On TeamPage, the parts' `absent_reason` always equals `withheld_reason` (backend `strength.py:176`), and that reason is stated once.
    - The report hides a reason only when all of an alliance's EPA cells share it, and then states it once (`ReportPage.tsx:109-135`). An empty shared reason hides nothing.
    - The "No roles" row states `absent_code` once.
  - **Tokens:** no read sends a token (the test covers every method).
  - **Write submission while busy:** clicks on an `aria-disabled` button are ignored by the synchronous `inFlight` guard (`coachInputs.tsx:37`), and Enter-submit goes through the same guard.
  - **Nulls:** no null renders as 0.
  - **Unvalidated probabilities** keep their separate styling and reason.
  
  ### Commands run (from `frontend/`)
  - `npx vitest run`: exit 0, 22 files, 121 tests passed.
  - `npx tsc -b`: exit 0, no output.
  - `npx oxlint`: exit 0, 10 warnings, 0 errors, none in `src/dashboard`, `api/dashboard.ts`, `api/http.ts` or `App.tsx`.
  - Read-only otherwise: grep/sed/cat over `frontend/src`, `ml/`, `api/`, `tests/` and `scripts/`, plus `python3 -I` to summarise `.agent/phase8/runs/live_smoke.json`.
  - Outputs are in `<local-scratchpad>/verify/` (`vitest.txt`, `tsc.txt`, `oxlint.txt`).
