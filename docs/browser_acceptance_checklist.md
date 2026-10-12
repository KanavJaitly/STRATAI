# Browser Acceptance Checklist: Manuals, Rulesets, Readiness, Explorer

For a person checking STRATAI in a real browser on the local test environment (2026-10-12). Browser acceptance is
**not** claimed until a person has completed this list.
- Background: `docs/game_manual_manager.md`.
- Expected time: about 60-90 minutes.

**What is not touched.** Everything runs on the isolated copies (`stratai_test`, `stratai_test_2023`) and a scratch
upload store. Nothing here touches the serving database, a model, or a Phase 6 record.

**Never click Approve.** Every ruleset step stops before approval: an approval, even on the test copy, is a recorded
human act.

Record each step as Pass or Fail, with a note. Note the browser and its version.

---

## 0. Setup

### 0.1 Launch

Use PowerShell, from `C:\Dev\StratAI`, with four terminals:

| # | Command | Serves |
|---|---|---|
| T1 | `.venv\Scripts\python.exe -m scripts.local_test_env --serve` | API on **stratai_test** (2024-2026, 2027), http://127.0.0.1:8765 |
| T2 | `.venv\Scripts\python.exe -m scripts.local_test_env --serve --database stratai_test_2023 --port 8766` | API on **stratai_test_2023** (2023 copy), http://127.0.0.1:8766 |
| T3 | `cd frontend; $env:STRATAI_API_URL = 'http://127.0.0.1:8765'; npx vite --port 5173 --strictPort` | **UI A**, http://localhost:5173, on T1 |
| T4 | `cd frontend; $env:STRATAI_API_URL = 'http://127.0.0.1:8766'; npx vite --port 5174 --strictPort` | **UI B**, http://localhost:5174, on T2 (2023 only) |

- Use the Vite proxy as shown, not `VITE_API_BASE`. Cross-origin, the browser would refuse the write-token header, and
  uploads would fail.
- UI B shares the scratch upload store, so keep it **read-only**: never enter the write token on :5174.

### 0.2 Confirm each server's database before testing

| ID | Check | Expected | ☐ |
|---|---|---|---|
| 0.1 | T1 and T2 print their first line | T1: `STRATAI local test API: database stratai_test (isolated copy), http://127.0.0.1:8765`. T2: the same with `stratai_test_2023` and `:8766` | ☐ |
| 0.2 | Open http://localhost:5173/api/seasons | 2023 has `"events":0`; 2024, 2025 and 2026 have 190, 203 and 215 events; 2027 has 0 | ☐ |
| 0.3 | Open http://localhost:5174/api/seasons | 2023 has `"events":185`; the other seasons as in 0.2 | ☐ |

### 0.3 Test files and identity

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 0.4 | Generate the synthetic PDFs:<br>`.venv\Scripts\python.exe -m scripts.local_test_env --checklist-files "$env:TEMP\stratai_checklist"` | Six files listed: `valid_2027`, `partial_2027`, `wrong_season_2026`, `no_year_2027`, `scanned`, `not_a_pdf` (all `.pdf`) | ☐ |
| 0.5 | In UI A's header:<br>• Your name: `Checklist Tester` (exactly; cleanup relies on it)<br>• Write token: `local-test-token` | The access badge changes from "read-only (no valid token)" to a writable state | ☐ |

---

## 1. `/manuals` (UI A, season **2027**)

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 1.1 | Choose `not_a_pdf.pdf` with the **real file picker** | A red notice says it is not a PDF (missing `%PDF-` header). "Upload and process" stays disabled, and nothing is sent | ☐ |
| 1.2 | Choose `valid_2027.pdf`, enter Game name `SYNTHETICA`, then Upload and process | The file's sha256 shows before upload. Then: "Stored as manual #N; processing started." The status moves to **succeeded**, with a moving progress bar while running | ☐ |
| 1.3 | Read the report | Identity `identified — the title pages name 2027`, revision 1.0; pages 6 (6 with text); suggestions 9; **no** warnings; the note says extraction is a review aid that approves nothing | ☐ |
| 1.4 | Extraction tabs: Suggestions, Sections, Topics, Page text | Every suggestion has a page number and the source text, and is labelled **Machine-extracted and unverified** | ☐ |
| 1.5 | Click a suggestion's **PDF** link, then "Open the original PDF" | Both open **in the browser's PDF viewer in a new tab, not as a download**. The PDF link opens at the cited page (compare with the page number) | ☐ |
| 1.6 | **Duplicate:** choose `valid_2027.pdf` again and upload | "This exact file is already manual #N. Nothing was replaced or duplicated." The versions list does not grow, and no new attempt appears | ☐ |
| 1.7 | Upload `partial_2027.pdf` (game `SYNTHETICA`) | It succeeds with **4 warnings**: page 5 has no extractable text; no page mentions ranking points, alliance selection or playoffs | ☐ |
| 1.8 | Upload `wrong_season_2026.pdf` | Status **failed**, `wrong_season`: the title pages name [2026], not the declared season 2027. The extraction is not shown | ☐ |
| 1.9 | **Retry:** on that manual, click "Retry processing" | Attempt #2 also fails with `wrong_season`. "Processing attempts (2)" lists both. Nothing else changes | ☐ |
| 1.10 | Upload `no_year_2027.pdf` | Status **needs resolution**: the season could not be read. "Confirm this is the 2027 manual" is disabled until a note is typed | ☐ |
| 1.11 | Type a note, then Confirm | Processing restarts and succeeds. Identity shows `resolved` | ☐ |
| 1.12 | Upload `scanned.pdf` | Status **failed**, `unreadable_text`: only 0 of 3 pages have extractable text | ☐ |
| 1.13 | Clear the write token | The upload form is replaced by "Enter a valid write token…"; the existing manuals stay visible. Re-enter the token afterwards | ☐ |

---

## 2. `/rulesets` (UI A)

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 2.1 | Season **2026**, then **2025**, then **2024** | Each shows that season's **approved** version: its season field equals the selected season, with the reviewer named. No other season's ruleset appears | ☐ |
| 2.2 | Season **2027**: open the worksheet | It starts from the 2026 approved ruleset:<br>• carried citations, tie rules and sections read `UNVERIFIED (carried from 2026)`;<br>• event lists are empty;<br>• the game name and manual identity come from the 2027 manual uploaded in section 1;<br>• the items to verify list suggestions with page numbers | ☐ |
| 2.3 | "Edit as a new draft", then "Save as draft" | It is saved as a draft under `Checklist Tester`, and a warning counts the remaining UNVERIFIED markers | ☐ |
| 2.4 | "Submit for review", then open the review form | The form shows the reviewer, read-only as `Checklist Tester`; a qualification field; the R1-R14 checkboxes; a sha256 field; and the red notice "still has N UNVERIFIED marker(s): it cannot be approved" | ☐ |
| 2.5 | Tick every box, type a qualification, then paste a **wrong** sha256 | "Does not match the stored sha256." **Approve** is disabled | ☐ |
| 2.6 | Paste the **correct** sha256 (shown on the page) | "Matches the stored sha256." **Approve is still disabled**, because markers remain. **Do not approve** | ☐ |
| 2.7 | "Return with note" with an empty note, then with a note | It is disabled while the note is empty. With a note, the version returns to draft | ☐ |

---

## 3. `/readiness` (UI A)

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 3.1 | Season **2027** | "No 2027 data is synced." The Human inputs section shows the 2027 manual from section 1 and the ruleset **not approved** | ☐ |
| 3.2 | The Phase 6 tasks table | R1-R10 and M1-M4 are listed, each with an actor and a status:<br>• **R8 done** (the M8b pre-run record);<br>• **R1 ready for human** (a named, qualified reviewer);<br>• all others waiting for 2027 data or blocked.<br>The upload in section 1 changed **no** task | ☐ |
| 3.3 | Done-means and wording | **P6-DM1 not met**, P6-DM2 met. Nothing says accepted, authorized or validated for a task that is not done. No button starts any run. The automation boundary lists approvals, authorizations, runs and serving changes as never automatic | ☐ |
| 3.4 | Season **2026** | Coverage, features and reasons. **No** Phase 6 task list appears | ☐ |

---

## 4. `/explorer` and season switching

The event and team pages to use:

| Season | UI | Event | Team | Matches to check |
|---|---|---|---|---|
| 2026 | A | `/explorer/events/2026tuis` | `/explorer/teams/9483` | qm1 |
| 2025 | A | `/explorer/events/2025isde1` | `/explorer/teams/1690` | qm1 |
| 2024 | A | `/explorer/events/2024isde1` | `/explorer/teams/1690` | qm1, qm20 |
| 2023 | **B** | `/explorer/events/2023isde1` | `/explorer/teams/1574` | qm1, qm20 |

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 4.1 | For each season, open `/explorer` on its UI | Coverage tiles, feature badges (available, **limited** or unavailable, each with a reason) and the events table. Every event key starts with the selected year | ☐ |
| 4.2 | Open the event. Check the **Teams** and **Matches** tabs, and the level filter | Team and match rows load. No season-mismatch banner | ☐ |
| 4.3 | Matches: "Win probability" on qm1 | 2026 and 2025: a red-alliance value with its validation badge; if that is `not validated`, it says "not a validated probability". 2024 and 2023 qm1: **Not available**, because no team has any prior evidence | ☐ |
| 4.4 | 2024 qm20 and 2023 qm20 | 2024: a value with its status. 2023: **Not available**, no verified score-breakdown adapter for the season | ☐ |
| 4.5 | **Event analysis** | It defaults to "as of" before the event (`<start date>T00:00:00+14:00`) with the note "Shown as of before the event began". It renders a ranked table, or an explained Not available | ☐ |
| 4.6 | Clear "As of", then Apply | A warning appears: shown as of now, not a historical test | ☐ |
| 4.7 | **Qualification forecast** | The same pre-event default, and Teams and Matches tables. **It can take about 1.5 minutes**; the loading state must stay visible meanwhile | ☐ |
| 4.8 | **Ranking prediction** | The notice "always as of now … not a historical test", then the table or an explained Not available | ☐ |
| 4.9 | Team page: "Strength", then "Metrics" | Strength shows a measures table, "As of before the event began", and validation badges. Metrics usually shows **Not available**: not computed for this event | ☐ |
| 4.10 | **Switch while on a page:** on 2026tuis, change the header season to 2024 | The banner says "This event is from 2026, but 2024 is selected", with a Switch button. Nothing from 2024 is mixed into this page | ☐ |
| 4.11 | Go to `/explorer` (2024), then switch to 2025 | The table shows only 2025 events; no 2024 row remains after it loads. Repeat 2025 → 2026 | ☐ |
| 4.12 | On UI A, select 2023 | "No 2023 data is synced. Sync the season to use its views." That is expected, because 2023 is on UI B | ☐ |
| 4.13 | Reload the page | The selected season persists | ☐ |
| 4.14 | Browse 4.1-4.11, then open `/manuals` and `/readiness` | Browsing created nothing: no new manual and no new attempt | ☐ |

---

## 5. Layout, keyboard and errors

| ID | Step | Expected | ☐ |
|---|---|---|---|
| 5.1 | Desktop width (≥1280 px): every page above | Readable, and nothing overlaps | ☐ |
| 5.2 | Phone width: DevTools device toolbar (Ctrl+Shift+M), 390×844, on `/manuals`, `/rulesets`, `/readiness`, `/explorer`, every event tab and a team page | **No page-level horizontal scroll.** Wide tables scroll sideways inside their own box. The header wraps. Buttons are tappable | ☐ |
| 5.3 | Phone width: the real file picker on `/manuals` | It opens, and the chosen file name and sha256 show | ☐ |
| 5.4 | **Keyboard only** (Tab, Shift+Tab, Enter, Space, arrows):<br>• nav links;<br>• the season select (arrows change the season);<br>• name and token inputs;<br>• the file input (Enter or Space opens the picker);<br>• event tabs;<br>• Win probability;<br>• As of and Apply;<br>• review checkboxes;<br>• Return with note | Every control is reachable in a sensible order, with a **visible focus ring**, and works from the keyboard. No focus trap | ☐ |
| 5.5 | Refusals are readable | Each failure and refusal in sections 1, 2 and 4 is visible as text, with its code. None is a blank or silent state | ☐ |
| 5.6 | **API down:** stop T1 (Ctrl+C), reload `/explorer` on UI A, then restart T1 and reload | A visible error (not an empty page) while T1 is down. After the restart, the page works again | ☐ |

---

## 6. Cleanup

Run `.venv\Scripts\python.exe -m scripts.local_test_env --cleanup-checklist`.

It deletes, in `stratai_test` only, the manuals, ruleset drafts and specs created by `Checklist Tester`, plus any
scratch approval record naming them. It prints the counts. Then stop T1-T4.

**Sign-off:** browser and version; date; the person; each failed step's ID with a note.
