# Browser Acceptance Results

**Manual results.** Steps 0.1-1.9 were run by the tester on 2026-10-12 against build `48d12ec`; the rest are not yet tested. Every other row starts as NOT TESTED. A row changes only when a person has observed
the result in a real browser: not from code inspection, unit or live jsdom tests, or the headless-Chrome smoke check.

| | |
|---|---|
| Checklist | `docs/browser_acceptance_checklist.md` (49 numbered steps; this file has 75 rows: steps 4.1-4.9 are recorded per season, plus cleanup 6.1) |
| Build under test | commit `48d12ec` (`8da41de` + this template) for steps 0.1-1.9 |
| Tester | Checklist Tester (Kanav) |
| Date | 2026-10-12 (paused after 1.9) |
| Browser and version | |
| OS, and the phone-width method (DevTools device toolbar or a real device) | |
| UI A → API | http://localhost:5173 → :8765, `stratai_test` (confirmed by 0.1-0.2: yes/no) |
| UI B → API | http://localhost:5174 → :8766, `stratai_test_2023`, **read-only, no write token entered** (confirmed by 0.1 and 0.3: yes/no) |

**Status values:**
- **PASS**: observed exactly as expected.
- **FAIL**: observed, and it differs. Describe it under Actual result and Notes, with a screenshot or the console
  output.
- **BLOCKED**: could not be performed (say why, e.g. a failed prerequisite step).
- **NOT TESTED**: not attempted.

The ruleset steps never include clicking **Approve**.

## Summary (fill in after testing)

| PASS | FAIL | BLOCKED | NOT TESTED | Total |
|---|---|---|---|---|
|  |  |  |  | 75 |

Defects (ID, step, short description):
- **D1** (step 1.9, build 48d12ec): processing attempts are counted and numbered from ledger lines (two per attempt). A retry is numbered #3, not #2, and the panel lists 2 entries per attempt.
  - Root cause: `data/manual_processing.py` `run()` (`len(lines) + 1`) and `status()` (raw lines).
  - Scope: display and numbering only. The failure reasons, retry, locking, duplicates and extraction are unaffected.
  - **Fixed in `341fa53`** (two regression tests). Re-checked in Chrome on `d919847`: a retry shows as #2.
- **D2** (found by automation, step 2.2): the ruleset worksheet used the most recent upload even when its processing
  had failed. It then showed no suggestions, and proposed the failed file's name as the manual title.
  - Fixed in `10476d7`: it now uses the latest successfully processed manual (two regression tests).
- **D3** (found by automation, step 5.5): a failed processing run showed only "failed"; the reason was visible only
  after expanding the attempt history.
  - Fixed in `f204e7d`: the latest failure is now an alert in the panel (component test).
- **D4** (found by automation, step 5.2): link-style buttons were about 18-20 px high and adjacent on a phone, below
  the 24 px minimum target size in WCAG 2.2.
  - Fixed in `f204e7d`: min-height 24 px, with spacing.

This is a product browser checklist only. It is not Phase 6 model validation or sign-off. P6-DM1 stays not met, and
M10 stays `not_validated`, whatever this checklist shows.

## 0. Setup

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 0.1 | T1 and T2 print their first line | T1: `STRATAI local test API: database stratai_test (isolated copy), http://127.0.0.1:8765`. T2: the same with `stratai_test_2023` and `:8766` | Not recorded at the time. The servers' terminal output is not available. | NOT TESTED | Needs verification. |
| 0.2 | Open http://localhost:5173/api/seasons | 2023 has `"events":0`; 2024, 2025 and 2026 have 190, 203 and 215 events; 2027 has 0 | Not recorded at the time. | NOT TESTED | Needs verification. |
| 0.3 | Open http://localhost:5174/api/seasons | 2023 has `"events":185`; the other seasons as in 0.2 | Not recorded at the time. | NOT TESTED | Needs verification. |
| 0.4 | Generate the synthetic PDFs:<br>`.venv\Scripts\python.exe -m scripts.local_test_env --checklist-files "$env:TEMP\stratai_checklist"` | Six files listed: `valid_2027`, `partial_2027`, `wrong_season_2026`, `no_year_2027`, `scanned`, `not_a_pdf` (all `.pdf`) | Not recorded at the time. | NOT TESTED | Recovered system evidence (after the fact; not a contemporaneous observation): the six files exist in %TEMP%\stratai_checklist, all timestamped 2026-10-12 17:33. Needs verification. |
| 0.5 | In UI A's header:<br>• Your name: `Checklist Tester` (exactly; cleanup relies on it)<br>• Write token: `local-test-token` | The access badge changes from "read-only (no valid token)" to a writable state | Not recorded at the time. | NOT TESTED | Recovered system evidence (after the fact; not a contemporaneous observation): the uploads in 1.2, 1.7 and 1.8 were stored with uploaded_by = 'Checklist Tester', and writes succeeded (the token was accepted). The badge itself was not recorded. Needs verification. |

## 1. `/manuals` (UI A, season 2027)

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 1.1 | Choose `not_a_pdf.pdf` with the **real file picker** | A red notice says it is not a PDF (missing `%PDF-` header). "Upload and process" stays disabled, and nothing is sent | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED |  |
| 1.2 | Choose `valid_2027.pdf`, enter Game name `SYNTHETICA`, then Upload and process | The file's sha256 shows before upload. Then: "Stored as manual #N; processing started." The status moves to **succeeded**, with a moving progress bar while running | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED | Recovered system evidence (after the fact; not a contemporaneous observation): manual #121 (valid_2027.pdf, sha256 c05d4d6e…) uploaded 17:37:18; attempt #1 succeeded. |
| 1.3 | Read the report | Identity `identified — the title pages name 2027`, revision 1.0; pages 6 (6 with text); suggestions 9; **no** warnings; the note says extraction is a review aid that approves nothing | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED |  |
| 1.4 | Extraction tabs: Suggestions, Sections, Topics, Page text | Every suggestion has a page number and the source text, and is labelled **Machine-extracted and unverified** | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED |  |
| 1.5 | Click a suggestion's **PDF** link, then "Open the original PDF" | Both open **in the browser's PDF viewer in a new tab, not as a download**. The PDF link opens at the cited page (compare with the page number) | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED |  |
| 1.6 | **Duplicate:** choose `valid_2027.pdf` again and upload | "This exact file is already manual #N. Nothing was replaced or duplicated." The versions list does not grow, and no new attempt appears | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED | Recovered system evidence (after the fact; not a contemporaneous observation): manual #121's ledger has one attempt only. |
| 1.7 | Upload `partial_2027.pdf` (game `SYNTHETICA`) | It succeeds with **4 warnings**: page 5 has no extractable text; no page mentions ranking points, alliance selection or playoffs | Not recorded: the tester's observation for this step has not been provided. Needs the tester's record. | NOT TESTED | Recovered system evidence (after the fact; not a contemporaneous observation): manual #122 (partial_2027.pdf, sha256 15b8e8c6…) uploaded 17:45:33; attempt #1 succeeded. |
| 1.8 | Upload `wrong_season_2026.pdf` | Status **failed**, `wrong_season`: the title pages name [2026], not the declared season 2027. The extraction is not shown | Tester (2026-10-12): an apparent processing-attempt count inconsistency was observed during this step. The step's other expected details (failed status, the wrong_season message, the extraction not shown) were not reported. | NOT TESTED | Performed, but its expected result was not reported, so it is not passed. The count inconsistency is recorded as a failure under 1.9, whose expected result defines the attempt count. Recovered system evidence (after the fact; not a contemporaneous observation): manual #123 (wrong_season_2026.pdf, sha256 0703f011…) uploaded 17:46:44; attempt #1 failed, wrong_season. |
| 1.9 | **Retry:** on that manual, click "Retry processing" | Attempt #2 also fails with `wrong_season`. "Processing attempts (2)" lists both. Nothing else changes | Tester (2026-10-12): both failed attempts remained visible; the checksum and the original PDF were unchanged; no successful extraction was shown. The attempt count and numbering did not match the expected 'Attempt #2' and 'Processing attempts (2)'. | FAIL | Defect D1 (see Summary). Build 48d12ec. Recovered system evidence (after the fact; not a contemporaneous observation): the ledger numbers the retry as attempt #3 (21:49:27), not #2. The panel lists raw ledger lines (two per attempt), so it shows 4 entries for 2 attempts. |
| 1.10 | Upload `no_year_2027.pdf` | Status **needs resolution**: the season could not be read. "Confirm this is the 2027 manual" is disabled until a note is typed |  | NOT TESTED |  |
| 1.11 | Type a note, then Confirm | Processing restarts and succeeds. Identity shows `resolved` |  | NOT TESTED |  |
| 1.12 | Upload `scanned.pdf` | Status **failed**, `unreadable_text`: only 0 of 3 pages have extractable text |  | NOT TESTED |  |
| 1.13 | Clear the write token | The upload form is replaced by "Enter a valid write token…"; the existing manuals stay visible. Re-enter the token afterwards |  | NOT TESTED |  |

## 2. `/rulesets` (UI A)

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 2.1 | Season **2026**, then **2025**, then **2024** | Each shows that season's **approved** version: its season field equals the selected season, with the reviewer named. No other season's ruleset appears |  | NOT TESTED |  |
| 2.2 | Season **2027**: open the worksheet | It starts from the 2026 approved ruleset:<br>• carried citations, tie rules and sections read `UNVERIFIED (carried from 2026)`;<br>• event lists are empty;<br>• the game name and manual identity come from the 2027 manual uploaded in section 1;<br>• the items to verify list suggestions with page numbers |  | NOT TESTED |  |
| 2.3 | "Edit as a new draft", then "Save as draft" | It is saved as a draft under `Checklist Tester`, and a warning counts the remaining UNVERIFIED markers |  | NOT TESTED |  |
| 2.4 | "Submit for review", then open the review form | The form shows the reviewer, read-only as `Checklist Tester`; a qualification field; the R1-R14 checkboxes; a sha256 field; and the red notice "still has N UNVERIFIED marker(s): it cannot be approved" |  | NOT TESTED |  |
| 2.5 | Tick every box, type a qualification, then paste a **wrong** sha256 | "Does not match the stored sha256." **Approve** is disabled |  | NOT TESTED |  |
| 2.6 | Paste the **correct** sha256 (shown on the page) | "Matches the stored sha256." **Approve is still disabled**, because markers remain. **Do not approve** |  | NOT TESTED |  |
| 2.7 | "Return with note" with an empty note, then with a note | It is disabled while the note is empty. With a note, the version returns to draft |  | NOT TESTED |  |

## 3. `/readiness` (UI A)

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 3.1 | Season **2027** | "No 2027 data is synced." The Human inputs section shows the 2027 manual from section 1 and the ruleset **not approved** |  | NOT TESTED |  |
| 3.2 | The Phase 6 tasks table | R1-R10 and M1-M4 are listed, each with an actor and a status:<br>• **R8 done** (the M8b pre-run record);<br>• **R1 ready for human** (a named, qualified reviewer);<br>• all others waiting for 2027 data or blocked.<br>The upload in section 1 changed **no** task |  | NOT TESTED |  |
| 3.3 | Done-means and wording | **P6-DM1 not met**, P6-DM2 met. Nothing says accepted, authorized or validated for a task that is not done. No button starts any run. The automation boundary lists approvals, authorizations, runs and serving changes as never automatic |  | NOT TESTED |  |
| 3.4 | Season **2026** | Coverage, features and reasons. **No** Phase 6 task list appears |  | NOT TESTED |  |

## 4. `/explorer` and season switching

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 4.1-2026 | **2026** (UI A; event `2026tuis`, team `9483`): For each season, open `/explorer` on its UI | Coverage tiles, feature badges (available, **limited** or unavailable, each with a reason) and the events table. Every event key starts with the selected year |  | NOT TESTED |  |
| 4.1-2025 | **2025** (UI A; event `2025isde1`, team `1690`): For each season, open `/explorer` on its UI | Coverage tiles, feature badges (available, **limited** or unavailable, each with a reason) and the events table. Every event key starts with the selected year |  | NOT TESTED |  |
| 4.1-2024 | **2024** (UI A; event `2024isde1`, team `1690`): For each season, open `/explorer` on its UI | Coverage tiles, feature badges (available, **limited** or unavailable, each with a reason) and the events table. Every event key starts with the selected year |  | NOT TESTED |  |
| 4.1-2023 | **2023** (UI B; event `2023isde1`, team `1574`): For each season, open `/explorer` on its UI | Coverage tiles, feature badges (available, **limited** or unavailable, each with a reason) and the events table. Every event key starts with the selected year |  | NOT TESTED |  |
| 4.2-2026 | **2026** (UI A; event `2026tuis`, team `9483`): Open the event. Check the **Teams** and **Matches** tabs, and the level filter | Team and match rows load. No season-mismatch banner |  | NOT TESTED |  |
| 4.2-2025 | **2025** (UI A; event `2025isde1`, team `1690`): Open the event. Check the **Teams** and **Matches** tabs, and the level filter | Team and match rows load. No season-mismatch banner |  | NOT TESTED |  |
| 4.2-2024 | **2024** (UI A; event `2024isde1`, team `1690`): Open the event. Check the **Teams** and **Matches** tabs, and the level filter | Team and match rows load. No season-mismatch banner |  | NOT TESTED |  |
| 4.2-2023 | **2023** (UI B; event `2023isde1`, team `1574`): Open the event. Check the **Teams** and **Matches** tabs, and the level filter | Team and match rows load. No season-mismatch banner |  | NOT TESTED |  |
| 4.3-2026 | **2026** (UI A; event `2026tuis`, team `9483`): Matches: "Win probability" on qm1 | 2026 and 2025: a red-alliance value with its validation badge; if that is `not validated`, it says "not a validated probability". 2024 and 2023 qm1: **Not available**, because no team has any prior evidence |  | NOT TESTED |  |
| 4.3-2025 | **2025** (UI A; event `2025isde1`, team `1690`): Matches: "Win probability" on qm1 | 2026 and 2025: a red-alliance value with its validation badge; if that is `not validated`, it says "not a validated probability". 2024 and 2023 qm1: **Not available**, because no team has any prior evidence |  | NOT TESTED |  |
| 4.3-2024 | **2024** (UI A; event `2024isde1`, team `1690`): Matches: "Win probability" on qm1 | 2026 and 2025: a red-alliance value with its validation badge; if that is `not validated`, it says "not a validated probability". 2024 and 2023 qm1: **Not available**, because no team has any prior evidence |  | NOT TESTED |  |
| 4.3-2023 | **2023** (UI B; event `2023isde1`, team `1574`): Matches: "Win probability" on qm1 | 2026 and 2025: a red-alliance value with its validation badge; if that is `not validated`, it says "not a validated probability". 2024 and 2023 qm1: **Not available**, because no team has any prior evidence |  | NOT TESTED |  |
| 4.4-2024 | **2024** (UI A; event `2024isde1`, team `1690`): 2024 qm20 and 2023 qm20 | 2024: a value with its status. 2023: **Not available**, no verified score-breakdown adapter for the season |  | NOT TESTED |  |
| 4.4-2023 | **2023** (UI B; event `2023isde1`, team `1574`): 2024 qm20 and 2023 qm20 | 2024: a value with its status. 2023: **Not available**, no verified score-breakdown adapter for the season |  | NOT TESTED |  |
| 4.5-2026 | **2026** (UI A; event `2026tuis`, team `9483`): **Event analysis** | It defaults to "as of" before the event (`<start date>T00:00:00+14:00`) with the note "Shown as of before the event began". It renders a ranked table, or an explained Not available |  | NOT TESTED |  |
| 4.5-2025 | **2025** (UI A; event `2025isde1`, team `1690`): **Event analysis** | It defaults to "as of" before the event (`<start date>T00:00:00+14:00`) with the note "Shown as of before the event began". It renders a ranked table, or an explained Not available |  | NOT TESTED |  |
| 4.5-2024 | **2024** (UI A; event `2024isde1`, team `1690`): **Event analysis** | It defaults to "as of" before the event (`<start date>T00:00:00+14:00`) with the note "Shown as of before the event began". It renders a ranked table, or an explained Not available |  | NOT TESTED |  |
| 4.5-2023 | **2023** (UI B; event `2023isde1`, team `1574`): **Event analysis** | It defaults to "as of" before the event (`<start date>T00:00:00+14:00`) with the note "Shown as of before the event began". It renders a ranked table, or an explained Not available |  | NOT TESTED |  |
| 4.6-2026 | **2026** (UI A; event `2026tuis`, team `9483`): Clear "As of", then Apply | A warning appears: shown as of now, not a historical test |  | NOT TESTED |  |
| 4.6-2025 | **2025** (UI A; event `2025isde1`, team `1690`): Clear "As of", then Apply | A warning appears: shown as of now, not a historical test |  | NOT TESTED |  |
| 4.6-2024 | **2024** (UI A; event `2024isde1`, team `1690`): Clear "As of", then Apply | A warning appears: shown as of now, not a historical test |  | NOT TESTED |  |
| 4.6-2023 | **2023** (UI B; event `2023isde1`, team `1574`): Clear "As of", then Apply | A warning appears: shown as of now, not a historical test |  | NOT TESTED |  |
| 4.7-2026 | **2026** (UI A; event `2026tuis`, team `9483`): **Qualification forecast** | The same pre-event default, and Teams and Matches tables. **It can take about 1.5 minutes**; the loading state must stay visible meanwhile |  | NOT TESTED |  |
| 4.7-2025 | **2025** (UI A; event `2025isde1`, team `1690`): **Qualification forecast** | The same pre-event default, and Teams and Matches tables. **It can take about 1.5 minutes**; the loading state must stay visible meanwhile |  | NOT TESTED |  |
| 4.7-2024 | **2024** (UI A; event `2024isde1`, team `1690`): **Qualification forecast** | The same pre-event default, and Teams and Matches tables. **It can take about 1.5 minutes**; the loading state must stay visible meanwhile |  | NOT TESTED |  |
| 4.7-2023 | **2023** (UI B; event `2023isde1`, team `1574`): **Qualification forecast** | The same pre-event default, and Teams and Matches tables. **It can take about 1.5 minutes**; the loading state must stay visible meanwhile |  | NOT TESTED |  |
| 4.8-2026 | **2026** (UI A; event `2026tuis`, team `9483`): **Ranking prediction** | The notice "always as of now … not a historical test", then the table or an explained Not available |  | NOT TESTED |  |
| 4.8-2025 | **2025** (UI A; event `2025isde1`, team `1690`): **Ranking prediction** | The notice "always as of now … not a historical test", then the table or an explained Not available |  | NOT TESTED |  |
| 4.8-2024 | **2024** (UI A; event `2024isde1`, team `1690`): **Ranking prediction** | The notice "always as of now … not a historical test", then the table or an explained Not available |  | NOT TESTED |  |
| 4.8-2023 | **2023** (UI B; event `2023isde1`, team `1574`): **Ranking prediction** | The notice "always as of now … not a historical test", then the table or an explained Not available |  | NOT TESTED |  |
| 4.9-2026 | **2026** (UI A; event `2026tuis`, team `9483`): Team page: "Strength", then "Metrics" | Strength shows a measures table, "As of before the event began", and validation badges. Metrics usually shows **Not available**: not computed for this event |  | NOT TESTED |  |
| 4.9-2025 | **2025** (UI A; event `2025isde1`, team `1690`): Team page: "Strength", then "Metrics" | Strength shows a measures table, "As of before the event began", and validation badges. Metrics usually shows **Not available**: not computed for this event |  | NOT TESTED |  |
| 4.9-2024 | **2024** (UI A; event `2024isde1`, team `1690`): Team page: "Strength", then "Metrics" | Strength shows a measures table, "As of before the event began", and validation badges. Metrics usually shows **Not available**: not computed for this event |  | NOT TESTED |  |
| 4.9-2023 | **2023** (UI B; event `2023isde1`, team `1574`): Team page: "Strength", then "Metrics" | Strength shows a measures table, "As of before the event began", and validation badges. Metrics usually shows **Not available**: not computed for this event |  | NOT TESTED |  |
| 4.10 | **Switch while on a page:** on 2026tuis, change the header season to 2024 | The banner says "This event is from 2026, but 2024 is selected", with a Switch button. Nothing from 2024 is mixed into this page |  | NOT TESTED |  |
| 4.11 | Go to `/explorer` (2024), then switch to 2025 | The table shows only 2025 events; no 2024 row remains after it loads. Repeat 2025 → 2026 |  | NOT TESTED |  |
| 4.12 | On UI A, select 2023 | "No 2023 data is synced. Sync the season to use its views." That is expected, because 2023 is on UI B |  | NOT TESTED |  |
| 4.13 | Reload the page | The selected season persists |  | NOT TESTED |  |
| 4.14 | Browse 4.1-4.11, then open `/manuals` and `/readiness` | Browsing created nothing: no new manual and no new attempt |  | NOT TESTED |  |

## 5. Layout, keyboard and errors

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 5.1 | Desktop width (≥1280 px): every page above | Readable, and nothing overlaps |  | NOT TESTED |  |
| 5.2 | Phone width: DevTools device toolbar (Ctrl+Shift+M), 390×844, on `/manuals`, `/rulesets`, `/readiness`, `/explorer`, every event tab and a team page | **No page-level horizontal scroll.** Wide tables scroll sideways inside their own box. The header wraps. Buttons are tappable |  | NOT TESTED |  |
| 5.3 | Phone width: the real file picker on `/manuals` | It opens, and the chosen file name and sha256 show |  | NOT TESTED |  |
| 5.4 | **Keyboard only** (Tab, Shift+Tab, Enter, Space, arrows):<br>• nav links;<br>• the season select (arrows change the season);<br>• name and token inputs;<br>• the file input (Enter or Space opens the picker);<br>• event tabs;<br>• Win probability;<br>• As of and Apply;<br>• review checkboxes;<br>• Return with note | Every control is reachable in a sensible order, with a **visible focus ring**, and works from the keyboard. No focus trap |  | NOT TESTED |  |
| 5.5 | Refusals are readable | Each failure and refusal in sections 1, 2 and 4 is visible as text, with its code. None is a blank or silent state |  | NOT TESTED |  |
| 5.6 | **API down:** stop T1 (Ctrl+C), reload `/explorer` on UI A, then restart T1 and reload | A visible error (not an empty page) while T1 is down. After the restart, the page works again |  | NOT TESTED |  |

## 6. Cleanup

| ID | Step | Expected | Actual result | Status | Notes / evidence |
|---|---|---|---|---|---|
| 6.1 | Run `.venv\Scripts\python.exe -m scripts.local_test_env --cleanup-checklist`, then stop T1-T4 | It prints counts of deleted `season_rulesets`, `game_spec_versions` and `game_manuals` rows created by `Checklist Tester` (stratai_test only) and scratch approval records; nothing else is touched |  | NOT TESTED |  |

---

## Automated results (separate from the manual results above)

| | |
|---|---|
| Build | commit `d919847` (the D1-D4 fixes included) |
| Browser | Google Chrome 155.0.8059.39 via Playwright 1.63.0 (`channel: 'chrome'`), headless; phone width is an emulated 390x844 viewport, not a real phone |
| Servers | the automation's own: API :8775 on `stratai_test`, API :8776 on `stratai_test_2023`; UI :5183 and :5184 through the Vite proxy. UI B was never given the write token |
| Identity and data | "Checklist Automation". Uploads are byte-distinct, run-stamped synthetic copies, never the tester's manuals. Synthetic ruleset drafts for 2.3-2.6 only, as authorized. Approve, Return and Confirm were never clicked |
| Run | `npx playwright test` in `frontend/`; 68 passed in 13.6 min (816 s with server start/stop); evidence (steps.jsonl, screenshots, report.json) in `C:/Dev/StratAI-artifacts/local_test/playwright_final_d919847` (outside the repository) |
| Status counts | automated PASS: 61, deferred: 1, manual verification required: 6 (of 68 rows) |

**Statuses:**
- **automated PASS / automated FAIL**: observed by the automation in Chrome.
- **manual verification required**: a human-only action or judgement. Any automated part is noted in the evidence;
  the row is not a pass.
- **deferred**: runs after the tester finishes.

**Build caveat.** The manual results above (0.1-1.9) were observed on build `48d12ec`, before the D1-D4 fixes. They
are not re-marked.

| ID | Automated status | Evidence |
|---|---|---|
| 0.1 | automated PASS | API A: STRATAI local test API: database stratai_test (isolated copy), http://127.0.0.1:8775; API B: STRATAI local test API: database stratai_test_2023 (isolated copy), http://127.0.0.1:8776; note: the automation runs its own servers on :8775/:8776 (the checklist names :8765/:8766), same databases |
| 0.2 | automated PASS | events per season: {"2023":0,"2024":190,"2025":203,"2026":215,"2027":0} |
| 0.3 | automated PASS | events per season: {"2023":185,"2024":190,"2025":203,"2026":215,"2027":0} |
| 0.4 | automated PASS | command output: valid_2027.pdf, partial_2027.pdf, wrong_season_2026.pdf, no_year_2027.pdf, scanned.pdf, not_a_pdf.pdf |
| 0.5 | automated PASS | name "Checklist Automation" (the automation's own identity); badge: read-only (no valid token) -> write token accepted |
| 1.10 | automated PASS | manual #203 (auto_no_year_2027.pdf): status "needs resolution"; Confirm disabled with no note, enabled with a note, disabled again when cleared; never clicked (1.11 is the tester's attestation); screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\1.10.png |
| 1.11 | manual verification required | Not automated: "Confirm this is the 2027 manual" is a named person's attestation. |
| 1.12 | automated PASS | manual #204 (auto_scanned.pdf): status "failed"; shown without expanding: "Attempt #1 failed: unreadable_text: only 0 of 3 pages have extractable text (a scanned manual?); OCR is not supported"; the history (1 attempt) lists the same reason; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\1.12.png |
| 1.13 | automated PASS | token cleared: the form is replaced by "Enter a valid write token…"; 15 uploaded versions still listed |
| 2.1-2026 | automated PASS | Approved: version 2 by Kanav Jaitly · sha256 7695b4a9f005…; the stored JSON's season = 2026 |
| 2.1-2025 | automated PASS | Approved: version 2 by Kanav Jaitly · sha256 0ad72856f82d…; the stored JSON's season = 2025 |
| 2.1-2024 | automated PASS | Approved: version 2 by Kanav Jaitly · sha256 6b3d22122709…; the stored JSON's season = 2024 |
| 2.2 | automated PASS | template from 2026; manual #206 supplies 3 page-cited suggestions; 17 "UNVERIFIED (carried from 2026)" markers; selection_variants and event_exclusions empty |
| 2.3 | automated PASS | warning: "17 value(s) still carry an UNVERIFIED (carried from …) marker. A draft…"; saved v5 (#720) as a draft authored by "Checklist Automation" (synthetic automation data, authorized for 2.3-2.6) |
| 2.4 | automated PASS | v5 (#720) submitted; reviewer read-only "Checklist Automation"; qualification field; R1-R14; sha256 field; "This version still has 17 UNVERIFIED marker(s): it cannot be approved. Return it…" |
| 2.5 | automated PASS | R1-R14 ticked, a synthetic qualification typed (never submitted), sha256 0x64: "Does not match the stored sha256."; Approve disabled; Approve never clicked |
| 2.6 | automated PASS | stored sha256 f9e9db8c502d… entered: "Matches the stored sha256."; Approve still disabled (markers); never clicked |
| 2.7 | manual verification required | automated part: PASS; v5 (#720): "Return with note" disabled with an empty note. Not clicked: the Return action is left to the tester |
| 3.1 | automated PASS | game manual: "#206 auto_valid_2027.pdf · succeeded · manage"; season ruleset: "draft · open" |
| 3.2 | automated PASS | statuses: {"R1":"your action","R2":"waiting for 2027 data","R3":"waiting for 2027 data","R4":"blocked","R5":"blocked","R6":"blocked","R7":"blocked","R8":"done","R9":"blocked","R10":"blocked","M1":"waiting for 2027 data","M2":"blocked","M3":"blocked","M4":"blocked"} |
| 3.3 | manual verification required | automated part: PASS; done-means: P6-DM1: not met / P6-DM2: met; buttons in the page body: 0; never automatic: game spec approval (P5-M8) / season ruleset approval (P6-M1) / every Phase 6 authorization, acceptance run, confirmation and review / model registration or serving changes; judgement left to the tester: whether any wording implies acceptance or authorization; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\3.3.png |
| 3.4 | automated PASS | 2026 readiness: coverage and features shown; no Phase 6 task table |
| 4.1-2026 | automated PASS | 213 event links, all 2026; features: available Events, teams and matches available Team EPA at an event (Statbotics) unavailable Team metrics (consistency, reliability; Phase 3) — team metrics have not been computed for this season's events available Team strength (EPA source) available Event analysis and ranking (P5-M4..M6) available Qualification forecast available Match win probability available Score components (P5-M7 adapters; u |
| 4.1-2025 | automated PASS | 203 event links, all 2025; features: available Events, teams and matches available Team EPA at an event (Statbotics) unavailable Team metrics (consistency, reliability; Phase 3) — team metrics have not been computed for this season's events available Team strength (EPA source) available Event analysis and ranking (P5-M4..M6) available Qualification forecast available Match win probability available Score components (P5-M7 adapters; u |
| 4.1-2024 | automated PASS | 190 event links, all 2024; features: available Events, teams and matches available Team EPA at an event (Statbotics) available Team metrics (consistency, reliability; Phase 3) available Team strength (EPA source) available Event analysis and ranking (P5-M4..M6) available Qualification forecast available Match win probability available Score components (P5-M7 adapters; used by the strategy model) |
| 4.1-2023 | automated PASS | 184 event links, all 2023; features: available Events, teams and matches unavailable Team EPA at an event (Statbotics) — no team EPA rows are synced for this season unavailable Team metrics (consistency, reliability; Phase 3) — team metrics have not been computed for this season's events limited Team strength (EPA source) — no score-breakdown adapter for 2023: an answer that needs this event's played matches is refused (season_not_su |
| 4.2-2026 | automated PASS | 32 team links; matches all/qualification/playoff = 79/64/15; no mismatch banner |
| 4.2-2025 | automated PASS | 29 team links; matches all/qualification/playoff = 73/58/15; no mismatch banner |
| 4.2-2024 | automated PASS | 31 team links; matches all/qualification/playoff = 78/62/16; no mismatch banner |
| 4.2-2023 | automated PASS | 25 team links; matches all/qualification/playoff = 65/50/15; no mismatch banner |
| 4.3-2026 | automated PASS | qm1: not validated red 0.95 (not a validated probability) · epa_incomplete |
| 4.3-2025 | automated PASS | qm1: approximately calibrated qualification red 0.95 |
| 4.3-2024 | automated PASS | qm1: Not available: No team in this match has any prior evidence (EPA, scoring history or scouting), so no prediction is served. (insufficient_features) |
| 4.3-2023 | automated PASS | qm1: Not available: No team in this match has any prior evidence (EPA, scoring history or scouting), so no prediction is served. (insufficient_features) |
| 4.4-2024 | automated PASS | qm20: not validated red 0.4 (not a validated probability) · epa_incomplete |
| 4.4-2023 | automated PASS | qm20: Not available: This season has no verified score-breakdown adapter, so its features are not built (never guessed). (season_not_supported) |
| 4.5-2026 | automated PASS | as of 2026-03-03T00:00:00+14:00; "Ordering model: raw_epa · as of 2026-03-03T00:00:00+14:00" after 18 s; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\4.5-2026.png |
| 4.5-2025 | automated PASS | as of 2025-02-23T00:00:00+14:00; "Ordering model: raw_epa · as of 2025-02-23T00:00:00+14:00" after 16 s; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\4.5-2025.png |
| 4.5-2024 | automated PASS | as of 2024-02-24T00:00:00+14:00; "Ordering model: raw_epa · as of 2024-02-24T00:00:00+14:00" after 14 s; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\4.5-2024.png |
| 4.5-2023 | automated PASS | as of 2023-02-26T00:00:00+14:00; "Ordering model: raw_epa · as of 2023-02-26T00:00:00+14:00" after 11 s; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\4.5-2023.png |
| 4.6-2026 | automated PASS | "Shown as of now: this past event is analysed with evidence from after it ended, so it is not a historical test." |
| 4.6-2025 | automated PASS | "Shown as of now: this past event is analysed with evidence from after it ended, so it is not a historical test." |
| 4.6-2024 | automated PASS | "Shown as of now: this past event is analysed with evidence from after it ended, so it is not a historical test." |
| 4.6-2023 | automated PASS | "Shown as of now: this past event is analysed with evidence from after it ended, so it is not a historical test." |
| 4.7-2026 | automated PASS | loading state visible at start: true; result "Teams" after 94 s |
| 4.7-2025 | automated PASS | loading state visible at start: true; result "Teams" after 81 s |
| 4.7-2024 | automated PASS | loading state visible at start: true; result "Teams" after 85 s |
| 4.7-2023 | automated PASS | loading state visible at start: true; result "Teams" after 68 s |
| 4.8-2026 | automated PASS | notice shown; result: rank team number predicted rating epa value source epa source event key epa withheld reason 1 9483 0.582 statbotics 2026 |
| 4.8-2025 | automated PASS | notice shown; result: Not available: The EPA source does not cover this event or season. (epa_source_incomplete) |
| 4.8-2024 | automated PASS | notice shown; result: Not available: The EPA source does not cover this event or season. (epa_source_incomplete) |
| 4.8-2023 | automated PASS | notice shown; result: Not available: The EPA source does not cover this event or season. (epa_source_incomplete) |
| 4.9-2026 | automated PASS | strength: Measure Value Status EPA total 83.4 (n=14) descriptive EPA auto 19.63 (n=14) descriptive EPA teleop 55.43 (n=14) descriptive EPA endgame 8.34 (n=14) descriptive; metrics: Not available: Team metrics have not been computed for this team at this event. (metrics_not_computed) |
| 4.9-2025 | automated PASS | strength: Measure Value Status EPA total 53.62 (n=6) descriptive EPA auto 17.01 (n=6) descriptive EPA teleop 31.29 (n=6) descriptive EPA endgame 5.32 (n=6) descriptive Av; metrics: Not available: Team metrics have not been computed for this team at this event. (metrics_not_computed) |
| 4.9-2024 | automated PASS | strength: Measure Value Status EPA total absent (no_prior_concluded_event_epa) descriptive EPA auto absent (no_prior_concluded_event_epa) descriptive EPA teleop absent (n; metrics: Not available: Team metrics have not been computed for this team at this event. (metrics_not_computed) |
| 4.9-2023 | automated PASS | strength: Measure Value Status EPA total absent (no_prior_concluded_event_epa) descriptive EPA auto absent (no_prior_concluded_event_epa) descriptive EPA teleop absent (n; metrics: Not available: Team metrics have not been computed for this team at this event. (metrics_not_computed) |
| 4.10 | automated PASS | "This event is from 2026, but 2024 is selected. Its data and rules are 2026's. Switch to 2026"; the page still shows 2026tuis (2026 data) |
| 4.11 | automated PASS | -> 2025: 203 links, all 2025; -> 2026: 213 links, all 2026 |
| 4.12 | automated PASS | "No 2023 data is synced. Sync the season to use its views." |
| 4.13 | automated PASS | 2025 selected, reloaded: still 2025 |
| 4.14 | automated PASS | manual ids:attempt counts and 2027 ruleset counts, before section 4 = after: true; snapshot: {"5183/2023":[],"5183/2024":[],"5183/2025":[],"5183/2026":[],"5183/2027":["121:1","122:1","123:2","171:1","172:1","173:2","196:1","197:1","198:2","199:1","200:1","201:1","202:1","203:1","204:1","205:2","206:1"],"5183/rulesets2027":6,"5184/2023":[],"5184/2024":[],"5184/2025":[],"5184/2026":[],"5184/2027":[],"5184/rulesets2027":0} |
| 5.1 | manual verification required | automated part: PASS; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-manuals.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-rulesets.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-readiness.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-explorer.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-event-teams.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-event-matches.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-event-analysis.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-event-forecast.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-event-ranking.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-team.png; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\5.1-explorer-2023.png; 1280x900: 11 views, none scrolls horizontally; readability and overlap: the tester's judgement from the screenshots or the browser |
| 5.2 | automated PASS | emulated 390x844 (isMobile, touch; not a real phone): 11 views; screenshots 5.2-*.png; no page-level horizontal scroll; wide tables scroll inside their own box; every button, tab, select and input is at least 24 px high |
| 5.3 | manual verification required | Not automated: the operating system's file dialog at phone width needs a person. |
| 5.4 | manual verification required | automated part: PASS; event: 49 of 49 visible controls reached by Tab; without a focus ring: none; order: Overview > Readiness & tasks > Historical seasons > Game manual > Season ruleset > Game spec > Team profiles > Human review > Season > Your name > Write token > ← 2026 events > Teams > Matches > Event analysis > Qualification forecast > Ranking prediction > 9483 > 6436 > 4481 > 9029 > 6431 > 3646 > 10428 > 9077 > 11244 > 7611 > 10308 > 9595 > 9233 > 11281 > 11416 > 8153 > 8242 > 8557 > 10043 > 11036 > 10050 > 5883 > 9132 > 9583 > 10141 > 10146 > 6064 > 11000 > 10064 > 7296 > 9601 > 4191; manuals: 57 of 57 visible controls reached by Tab; without a focus ring: none; order: Overview > Readiness & tasks > Historical seasons > Game manual > Season ruleset > Game spec > Team profiles > Human review > Season > Your name > Write token > Manual PDF > Game name > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open > Open the original PDF > Processing attempts (1) > Suggestions (9) > Sections (9) > Topics > Page text > p. 3 > PDF > p. 3 > PDF > p. 6 > PDF > p. 4 > PDF > p. 4 > PDF > p. 4 > PDF > p. 5 > PDF > p. 6 > PDF > p. 6 > PDF > enter the game spec > draft the season ruleset > see every remaining task; readiness: 14 of 14 visible controls reached by Tab; without a focus ring: none; order: Overview > Readiness & tasks > Historical seasons > Game manual > Season ruleset > Game spec > Team profiles > Human review > Season > Your name > Write token > manage > open > open; Enter on a focused tab selects it; ArrowDown on the season select changes it (2026 -> 2025); Space on the focused file input opens the file chooser; judgement left to the tester: whether the order is sensible and comfortable |
| 5.5 | automated PASS | explorer refusal: "Not available: No team in this match has any prior evidence (EPA, scoring history or scouting), so no prediction is served. (insufficient_features)"; processing failure (auto_scanned.pdf): status badge "failed"; the reason and its code visible without expanding "Processing attempts": true |
| 5.6 | automated PASS | API A stopped: "http_error (502): HTTP 502"; restarted (STRATAI local test API: database stratai_test (isolated copy), http://127.0.0.1:8775); the events table loads again |
| 6.1 | deferred | Run after the tester finishes: `--cleanup-checklist` (the tester's rows) and `--cleanup-checklist --actor "Checklist Automation"` (the automation's rows). |

Not checklist steps: setup and the D1 re-check.

| ID | Status | Evidence |
|---|---|---|
| 2.0-setup | automated PASS | manual #206 (auto_valid_2027.pdf, uploaded by "Checklist Automation") succeeded |
| D1-browser | automated PASS | manual #205 (auto_wrong_season_2026.pdf), build with the D1 fix: #1 failed by Checklist Automation · started 10/12/2026, 6:40:18 PM · finished 10/12/2026, 6:40:18 PM · wrong_season: the title pages name [2026], not the declared season 2027 / #2 failed by Checklist Automation · started 10/12/2026, 6:40:19 PM · finished 10/12/2026, 6:40:19 PM · wrong_season: the title pages name [2026], not the declared season 2027; screenshot: C:\Dev\StratAI-artifacts\local_test\playwright_final_d919847\D1-browser.png |
