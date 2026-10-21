# Game Manual Manager, Season Readiness and the Historical Season Testing Center

Written 2026-10-12 for the people who run STRATAI and the engineers who maintain it. It covers:
- how a season's game manual enters STRATAI;
- what the system does with it automatically;
- what only a person may decide;
- how 2023-2026 can be exercised end to end on real data.

**It changes no Phase 6 fact.** Phase 6 was accepted on 2026-10-17 with P6-DM1 deferred, and P6-DM1 is still not met
(see `docs/phase6.md` and `.agent/phase6/PHASE_STATUS.md`).

---

## 1. Dependency map

Which features consume game-manual information, which consume season data, and which need a person's approval. This
is the same list the readiness report computes per season (`data/readiness.py`, `features()` and `TASKS`), so the
page and this table cannot drift apart.

| Feature | Game-manual information | Season data | Human approval |
|---|---|---|---|
| Events, teams, matches (explorer) | no | TBA events, matches, match teams | no |
| Team EPA at an event | no | Statbotics `team_event_stats` | no |
| Team metrics (Phase 3) | no | matches; scouting observations for defense/feeding | no (scouting is human-entered) |
| Team strength (P5-M3) | no | the EPA source; matches; score breakdowns (adapter) | no |
| Event analysis and ranking (P5-M4..M6) | no | EPA source, pinned ranking model, breakdowns | serving pins only |
| Qualification forecast (P5-M5) | no | EPA source, pinned win-probability model | serving pins only |
| Match win probability | no | EPA source, pinned win-probability model | serving pins only |
| Score components (P5-M7) | no (the adapter is engineered from real match payloads) | TBA score breakdowns | engineering verification |
| Game manual processing (this page) | **the uploaded PDF** | no | no: extraction only |
| Game analysis and design recommendations (P5-M8/M9) | **an approved game spec**, entered by a person from the manual | no | **yes**: a reviewer approves the spec |
| Alliance-selection and playoff rules (P6-M1) | **an approved season ruleset**, entered by a person from the manual | no | **yes**: a named, qualified FRC reviewer (R1-R14, R15 record) |
| Phase 6 2027 runs (FINAL-1, PX-2b, PX-4b, M8b, M10b, parity) | the approved 2027 ruleset (read by the runs) | 2027 matches; the pinned 2027 EPA source | **yes**: every authorization, confirmation and review (tasks R1-R10, M1-M4) |

The manual itself never feeds a model or a Phase 6 run. Only a person's reviewed and approved entry does: the game
spec (P5-M8, "human-entered spec; no LLM parses the manual") or the season ruleset (P6-M1).

---

## 2. The upload experience (Manuals page, `/manuals`)

1. **Choose the season** in the header (2023-2027). Every page follows it.
2. **Pick the PDF and name the game.** The browser checks the file before anything is sent:
   - the file type is PDF;
   - it begins with `%PDF-`;
   - it is between 1 byte and 100 MB (the server's own limit, `data/human_inputs.py` `MAX_MANUAL_BYTES`).

   It shows the file's sha256, computed locally.
3. **Upload and process.** The server validates the file again and hashes it. It stores the file write-once under
   its sha256, and returns the stored hash, which the page compares with its own; a mismatch is shown as an error.
   Processing then starts automatically.
4. **Progress and status.** The panel shows:
   - identity: the declared and detected season, and the detected version or revision;
   - pages, size and hash;
   - the status: `not_started`, `running`, `succeeded`, `failed` or `needs_resolution`;
   - warnings, errors and every attempt.

   While processing runs, the page polls every 1.5 s.
5. **Failure and retry.** A failure records its reason (`hash_mismatch`, `unreadable_text`, `malformed_pdf`, `encrypted_pdf`,
   `wrong_season`, …) and releases its lock. **Retry** starts a new attempt; earlier attempts stay in the history.
6. **Ambiguous identity.** If the PDF names several seasons, or none, processing stops at `needs_resolution`. A
   person then confirms the season, which must equal the declared season. The confirmation is recorded write-once,
   and processing continues. A manual detected as another season is `wrong_season` and is never processed under the
   declared one.
7. **Review the extraction.** The extraction has four tabs:
   - **suggestions**: auto/teleop durations, alliance count, point values, ranking points and the playoff format,
     each with its page and the text it came from;
   - **sections**;
   - **topics**: match play, scoring, ranking points, alliance selection, playoffs; a missing expected topic is a
     warning;
   - **page text**.

   Every page reference opens the stored PDF at that page. Everything is labelled **machine-extracted and
   unverified**: it is a reading aid, never a value of record.
8. **Dependent features and the next human steps** are listed under the manual. The next steps are to enter and
   approve the game spec (`/game`) and the season ruleset (`/rulesets`).

### The pipeline (`data/manual_processing.py`, `manual-proc-v1`)

The steps, in order:
1. Validate.
2. Re-read the stored file and check its sha256 against the database row. A mismatch is `hash_mismatch`, and nothing
   is processed.
3. Extract the text of every page with pypdf, up to 1000 pages. If fewer than 50% of pages have text, the PDF is
   refused as `unreadable_text` (scanned images cannot be reviewed against page text).
4. Detect the season and version.
5. Index sections and topics.
6. Suggest values.
7. Run the checks.
8. Write the readiness report.

**Idempotent, by construction:**
- the ledger is keyed by the file's sha256 and the processor version;
- a run that already succeeded is not repeated;
- the same file uploaded twice is one manual;
- a concurrent start finds the lock and reports `running`; a lock older than 30 min is stale and may be taken over.

**Deterministic:** the same file gives byte-identical `extraction.json` and `report.json`, and both are write-once.

Processing writes nothing to any canonical table, model, registry or Phase 6 record.

### Storage

| What | Where |
|---|---|
| The uploaded PDF (write-once, named by sha256) | `<ARTIFACT_STORE_DIR>/game_manuals/<season>/<sha256>.pdf`; the row is in `game_manuals` |
| Processing ledger | `<ARTIFACT_STORE_DIR>/manual_processing/<sha256>/manual-proc-v1/`:<br>• `extraction.json`, `report.json` (write-once);<br>• `attempts.jsonl` (append-only);<br>• `identity.json`, `identity_resolution.json` (write-once);<br>• `lock` |
| Draft and approved rulesets | `season_rulesets` (versioned, sha256 of the canonical JSON) |
| A web approval's P6-M1 record (R15) | `<RULESET_APPROVAL_RECORD_DIR>/P6_M1_APPROVAL_<season>_v<version>.json`, write-once; default `.agent/phase6/decisions/` |
| Game specs | `game_spec_versions` (unchanged P5-M8 workflow) |

`ARTIFACT_STORE_DIR` defaults to `../StratAI-artifacts/uploads`. The local test environment uses a scratch directory
(section 6).

---

## 3. From manual to approved ruleset (Rulesets page, `/rulesets`)

1. **Worksheet.**
   - `GET /human-inputs/seasons/{season}/ruleset-worksheet` starts the season's draft from the latest earlier approved
     ruleset.
   - Every carried citation, tie rule and section is marked `UNVERIFIED (carried from <season>)`. The event lists are
     emptied.
   - It is given the uploaded manual's game name and identity, and lists each value to verify next to the
     extraction's suggestions and pages.
   - The worksheet is not saved.
2. **Draft.** A person edits the JSON and saves it under their name. The page counts the remaining markers.
3. **Submit**, then **review.** The reviewer:
   - gives a name and qualification;
   - ticks R1-R14 (`GET /human-inputs/ruleset-review-checklist`);
   - types the draft's full sha256.

   Approve is disabled while any marker remains. Return needs a note.
4. **Approval.** The server checks, in this order:
   1. the reviewer, qualification, R1-R14 and the sha256;
   2. that no `UNVERIFIED (carried from` marker remains (`unverified_content`);
   3. that the R15 record path does not already exist.

   Only then does it approve, and it writes the write-once R15 record. A refusal changes nothing.

Every write needs the server-side write token (`X-StratAI-Write-Token`). The browser holds only what the person types;
no credential is in the client bundle.

---

## 4. How consumption and approval are enforced

- **No route can approve without a person.** Approval endpoints take the reviewer's name, qualification, the
  checklist and the full sha256 (`data/rulesets.py` `review_ruleset`, `_approval_record`). Machine-extracted values
  enter a ruleset only through a person's draft, and carried markers block approval.
- **Processing authorizes nothing.** `data/manual_processing.py` writes only its own ledger. The readiness report
  marks every Phase 6 task `never_by_manual_upload: true`. Its `automation_boundary` lists what is automatic and what
  never is.
- **No Phase 6 HTTP routes (P6-A1).** The new routes contain none of `strategy|alliance-selection|pick-list|playoff`
  (`tests/test_phase6_contract.py`), and the explorer reads only existing GET routes
  (`tests/test_frontend_api_contract.py`).
- **The endpoint set is pinned** (`tests/test_api_foundation.py`). The 16 new paths were added there deliberately.
- **Serving is unchanged.** Nothing here registers a model, changes a pin, or writes a canonical table. Historical
  analysis endpoints are the existing frozen ones.
- **Historical seasons never invoke 2027 processing.** Browsing writes nothing and calls no `/processing` route
  (`frontend/src/pages/ExplorerPages.test.tsx`). Phase 6 tasks appear only in 2027's readiness.

---

## 5. 2027: readiness, tasks and resuming from blockers

`/readiness` with 2027 selected lists the Phase 6 tasks from `.agent/phase6/P6_2027_AUTHORIZATION_REQUESTS.md`:
- R1-R10 (ruleset, EPA pin, C0 check, FINAL-1, PX-2b/PX-4b, M8b, miss review);
- M1-M4 (the M10b frame, run, confirmation and parity rerun).

**Status.** Each task's status is derived only from what exists: the approved ruleset, 2027 matches, and each task's
write-once record (with its pass key, for runs). The statuses are:
- `done`;
- `failed`;
- `ready_for_human`;
- `ready_to_run`;
- `blocked`;
- `waiting_for_2027_data`.

**Done-means.** The page shows P6-DM1 and P6-DM2 as computed by `scripts/phase6_done_means.py`. DM1 is not met.

**Resuming:** `python -m scripts.phase6_resume [--run]`, on an isolated copy.
- It runs only the allow-listed automatic preparation: R3, the C0 ruleset reproduction check
  (`phase6_playoff_track m1-2027`).
- R3 runs only when the 2027 ruleset is approved, 2027 matches exist, and its record does not exist yet.
- Everything else is printed as a task for the named person.
- The allow-list is pinned to the readiness report's automatic tasks (`tests/test_phase6_resume.py`).

On 2026-10-12 it runs nothing: R8 is done, R1 waits for a qualified reviewer, and every other task waits for R1 or
2027 data.

**What the 2027 manual upload does:** extraction and the readiness report, nothing else. It never authorizes or
starts any of the following:
- FINAL-1, PX-2b, PX-4b or M8b;
- the M8b miss review;
- M10b acceptance, confirmation or the parity rerun;
- any serving change.

---

## 6. Historical Season Testing Center (`/explorer`, `/readiness`)

### Pages

- **Explorer** (`/explorer`):
  - the season's coverage: events, played matches, teams, EPA rows, metrics rows, scouting, freshness and the
    score-breakdown adapter;
  - feature availability (available, **limited**, or unavailable, with reasons);
  - a searchable events table.
- **Event** (`/explorer/events/:key`): teams, matches (with per-match pre-match win probability), event analysis,
  qualification forecast and ranking prediction. A banner warns when the event's season differs from the selected
  one.
- **Team** (`/explorer/teams/:n`): the team's events in the selected season, with strength and metrics on demand.

**Point in time.** A past event's analysis, forecast and team strength default to **before the event began**: the
earliest local midnight of its start date anywhere (UTC+14). They therefore use only evidence available then. The
person can clear the field for "now", and the page then warns that it is not a historical test. The ranking prediction
endpoint takes no "as of" (frozen Phase 4 behaviour), and its tab says so.

**Season isolation.** Switching the season remounts the page and re-fetches. No earlier season's data is shown,
which is tested.

### The local test environment

```
# PowerShell, from the repository root; four terminals
.venv\Scripts\python.exe -m scripts.local_test_env --serve                                           # API :8765 on stratai_test (2024-2026, 2027)
.venv\Scripts\python.exe -m scripts.local_test_env --serve --database stratai_test_2023 --port 8766  # API :8766 on stratai_test_2023 (2023)
cd frontend; $env:STRATAI_API_URL = 'http://127.0.0.1:8765'; npx vite --port 5173 --strictPort    # UI http://localhost:5173
cd frontend; $env:STRATAI_API_URL = 'http://127.0.0.1:8766'; npx vite --port 5174 --strictPort    # UI http://localhost:5174 (2023)
```

It pins:
- the evaluated D18 models, by sha256;
- the D18 Statbotics snapshot as the EPA source;
- a scratch upload store, approval-record directory and write token.

It refuses any database but the two isolated copies.

The UI must reach the API through Vite's `/api` proxy (`STRATAI_API_URL`), not cross-origin with `VITE_API_BASE`. The
API's CORS list deliberately does not admit the write-token header, so cross-origin writes (uploads, approvals) fail.

**Why 2023 has its own copy.** `ml.ratings.provider.read_team_event_facts` reads every event in the database. With
2023 in `stratai_test`, 2023 team-events became D13 prior-event candidates for:
- 3,076 2024 team-events;
- 38 2025 team-events;
- 5 2026 team-events.

Their frozen D18 lookups changed from "no prior event, withheld" to `epa_source_incomplete`. 2023 was therefore moved
to `stratai_test_2023` on 2026-10-12, and `stratai_test` was restored exactly to its pre-sync state (section 8).

**Production note.** The same holds for the serving database: syncing 2023 into it would change 2024+ D18 lookups.
Do not, without a decision.

### Feature-by-season matrix (2026-10-12, real data)

The sources are the readiness report of each instance (`stratai_test` for 2024-2027, `stratai_test_2023` for 2023)
and the live UI run (section 7). For historical seasons, "shown" means the real UI rendered a real answer with its
own validation status. It is not a claim of validation.

| Feature | 2023 | 2024 | 2025 | 2026 | 2027 |
|---|---|---|---|---|---|
| Data synced (events / played matches / teams) | 185 / 16,316 / 3,290 | 190 / 16,977 / 3,477 | 203 / 17,846 / 3,690 | 215 / 18,372 / 3,709 | none |
| Events, teams, matches | yes (UI tested) | yes (UI tested) | yes (UI tested) | yes (UI tested) | no data |
| Team EPA (Statbotics rows) | **no**: Statbotics returned 500/503 during the 2023 sync, and the D18 snapshot covers 2024-2026 | yes (7,664) | yes (8,072) | yes (8,286) | no |
| Team metrics (Phase 3) | not computed | 42 rows only | not computed | not computed | no |
| Team strength (pre-event) | **limited**: shown; no EPA; in-event answers refused `season_not_supported` | shown | shown | shown | no data |
| Event analysis (pre-event) | **limited**: shown, as above | shown | shown | shown | no data |
| Qualification forecast (pre-event) | **limited**: shown, as above | shown | shown | shown | no data |
| Match win probability (pre-match) | **limited**: the first match is `insufficient_features`; later matches `season_not_supported` | shown (`not_validated`); a season's first match is `insufficient_features` | shown | shown | no matches |
| Ranking prediction | "as of now" only (not a historical test) | same | same | same | no data |
| Score components (adapter) | **no adapter** (engineering, from real 2023 payloads) | yes | yes | yes | after 2027 matches |
| Season ruleset (P6-M1) | none approved | approved | approved | approved | **R1: awaiting a qualified reviewer** |
| Game spec (P5-M8) | none | none | none | none | none |
| Game manual processing | none uploaded | none | none | none | awaiting the 2027 manual |

---

## 7. What was tested, and how

| Workflow | How | Result |
|---|---|---|
| Upload → automatic processing → extraction review | backend tests (29+), frontend component tests, and a **live** run of the real UI against the local API (a SYNTHETIC 2099 PDF) | pass |
| Invalid file, wrong season, ambiguous season with resolution, unreadable PDF, tampered file (hash mismatch, then retry), duplicate upload, concurrent start, stale lock, write-once ledger | backend tests | pass |
| Draft → submit → review (incomplete review, sha mismatch, markers, existing R15 record refused before approving) → approval writes R15 | backend tests (record to a temporary directory) and frontend component tests | pass |
| Season switching, no stale data, no writes while browsing, no `/processing` calls | frontend component tests | pass |
| 2023-2026: explorer → event → teams → matches → win probability → analysis → forecast → team strength | **live** run of the real UI (jsdom) against the local API on real data | pass (outcomes in section 6) |
| 2027 readiness: tasks listed, no data | live run and backend tests | pass |
| The resume command runs only R3, only when ready | `tests/test_phase6_resume.py` | pass |

**Still needs a person in a real browser.** The live run renders the real React app in jsdom, not in a browser, and no
browser automation (Playwright or similar) is installed in this project. A person should check, in a real browser:
- layout and CSS at desktop and phone widths;
- the real file picker and drag-and-drop;
- opening a page reference in the browser's PDF viewer (`#page=N`);
- the progress display during a long real manual;
- keyboard navigation.

The step-by-step list is `docs/browser_acceptance_checklist.md`. Browser acceptance is not claimed until a person has
completed it.

**Pre-acceptance pass (2026-10-12).** A headless-Chrome layout smoke check over the DevTools protocol covered 12 views
at 1280 px and 390 px. It found no page-level horizontal scroll and no error alerts. It is a smoke check, not
acceptance.

Two real defects were fixed:
- the manual's file endpoint sent `Content-Disposition: attachment`, so the browser downloaded the PDF and page links
  (`#page=N`) could not open at the cited page;
- a filename with a non-Latin-1 character (an en dash) made the download a 500.

It is now `inline`, with an RFC 6266 ASCII fallback plus a UTF-8 `filename*` and `nosniff`
(`tests/test_human_inputs.py`).

The qualification forecast takes about 80-90 s for a 79-match event on the test machine (the frozen P5-M5 endpoint;
not changed).

**Run the live check:**
```
STRATAI_LIVE_API=1 STRATAI_LIVE_SEASONS=2026,2025,2024 VITE_API_BASE=http://127.0.0.1:8765 npx vitest run src/live
STRATAI_LIVE_API=1 STRATAI_LIVE_SEASONS=2023 STRATAI_LIVE_HISTORY_ONLY=1 VITE_API_BASE=http://127.0.0.1:8766 npx vitest run src/live
```

---

## 8. 2026-10-12 record: the 2023 sync was reversed in stratai_test

This session synced TBA 2023 (185 events, pipeline runs 7663-7847) into `stratai_test` on 2026-10-11, and then found
the D13 interaction described in section 6. The fix:

1. `CREATE DATABASE stratai_test_2023 TEMPLATE stratai_test` kept 2023 (and a full copy of that state).
2. One transaction removed exactly what runs 7663-7847 added:
   - 17,900 raw payloads and their lineage;
   - 185 events, 16,342 matches and 98,052 match teams;
   - 175 new teams;
   - 555 watermarks and the 185 runs.
3. The same transaction:
   - made the 1,198 superseded team payloads current again;
   - rebuilt 99 changed canonical team rows from them with the normal TBA normalizer.
4. It was verified before committing:
   - the 2023-2026 counts;
   - the 2024-2026 matches fingerprint;
   - the teams fingerprint (4,240 teams);
   - the one-current-version invariant.

After committing, the full pre-sync baseline, including the 2024-2026 `team_event_stats` fingerprint, is identical,
and no 2024-2026 team-event has a 2023 prior event.

**Record:** `.agent/stratai_test/2023_reversal_2026-10-12.json`, with the exact script as executed
(`.py`, sha256 in the record). The serving database was not accessed.

**Not restored:** the `teams.last_updated` timestamps of the 1,198 superseded teams (no fingerprint or reader uses
them) and the consumed id sequence values.

---

## 9. API reference

**The historical explorer.** These routes are read-only and return real rows of the configured database. They are
pinned to this list by `tests/test_manual_manager.py`.
- `GET /explorer/seasons`: every supported season with its coverage.
- `GET /explorer/seasons/{season}/events`: the season's events, with match and played counts.
- `GET /explorer/events/{event_key}/teams`: the event, its teams, their synced EPA and record, and whether metrics exist.
- `GET /explorer/events/{event_key}/matches`: the event's matches, with alliances and scores.
- `GET /explorer/teams/{team_number}/seasons/{season}`: a team's events in one season.

**Game manuals, rulesets and readiness.** These are the `/human-inputs/...` routes. They are listed in
`docs/phase5.md` under "Routes", with the other human-input routes. Every write needs `X-StratAI-Write-Token`.

**Analyses the explorer calls.** These are the existing, unchanged routes:
- `/teams/{n}/events/{key}/strength`;
- `/teams/{n}/events/{key}/metrics`;
- `/events/{key}/analysis`;
- `/events/{key}/qualification-forecast`;
- `/predictions/events/{key}/ranking`;
- `/predictions/matches/{key}/win-probability`.

**Refusals.** A route that builds features for a season without a score-breakdown adapter answers 422
`season_not_supported` (2026-10-12; previously an unhandled 500).
