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
