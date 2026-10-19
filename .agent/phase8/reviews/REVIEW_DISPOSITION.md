# Phase 8 — what was done about each review finding

There were three independent reviews (subagents with fresh context and a read-only brief). They ran on 2026-10-19
between 03:36 and 03:39 UTC (2026-10-18 local), and each report is recorded verbatim in this folder. A fourth review
then verified the fixes; its result is in `R4_fix_verification.md`.

**Severity totals:**
- R1: 4 low.
- R2: 3 high, 8 medium, 7 low.
- R3: 2 medium, 1 low–medium, 6 low, plus test gaps.

## R1 — contract and probability correctness

| # | Finding | Disposition |
|---|---|---|
| 1 | A null winner is counted as a loss | FIXED. Losses are counted explicitly and no-winner matches are reported separately; `TeamPage.test.tsx` covers it |
| 2 | Labels are not verbatim | FIXED. The raw `validation.status` is shown, and the tests assert the verbatim labels |
| 3 | The `insufficient_features` text | FIXED. The text now covers the no-scheduled-time case |
| 4 | Hardcoded "not-validated" in the report | FIXED. Removed; the served status shows through `OddsView` |

## R2 — accessibility and UX

| # | Finding | Disposition |
|---|---|---|
| 1 | No focus or title on navigation | FIXED. `useFocusMainOnNavigation`, and `PageHeader` sets `document.title` from the h1; the report sets its own title. Covered by `App.test.tsx` |
| 2 | The label explanation is only in a tooltip | FIXED. The badge is a toggle button with an inline explanation and `aria-describedby`; `display.test.tsx` covers it. Badges were moved out of headings |
| 3 | Closed `<details>` don't print | FIXED. They open on `beforeprint` and are restored on `afterprint`; `ReportPage.test.tsx` covers it |
| 4 | Input border contrast | FIXED. New `--input-border` token, `#7b8594` light and `#7d8796` dark. Computed (WCAG formula): 3.73:1 on the light surface, 3.48:1 on the light background, 4.55:1 and 5.03:1 in dark |
| 5 | Breadcrumb links look like text | FIXED. `.crumbs a` has the accent colour and an underline |
| 6 | Live regions mount with their content; `disabled` drops focus | PARTIAL. The coach writes now have persistent status regions and use `aria-disabled` (tested). Still open: the loading text, the comparison and the pick list (P8-R9) |
| 7 | Charts unreadable at 390 px | FIXED. Min-width 420 px inside a scroll box |
| 8 | Heading order | FIXED. `StrengthView` takes a `level` prop (h3 in the report), and the not-produced items are grouped under an h3 |
| 9 | Raw codes everywhere; jargon | FIXED. `reasonText` gives plain words and keeps the raw reason in `title`/`data-reason`; a shared reason is stated once; the stray "·" is gone; the `model_not_loaded` wording is plainer (P8-D1 D1.7) |
| 10 | Tables clip with no cue | FIXED (no sticky column). Tables stay `display:table` inside `.table-scroll`, with a min-width, scroll shadows and `break-word` |
| 11 | Tab behaviour | PARTIAL. Fixed: `replace:true`, and `aria-controls` only on the active tab. Still open: tabs activate automatically (P8-R9) |
| 12 | Header height on phones; tab overflow | FIXED. The session bar is a disclosure at ≤600 px, and the tab strip fades at its edge |
| 13 | No active nav item on sub-pages | FIXED. Events is current on `/`, `/events/`, `/matches/`, `/report/`; covered by `App.test.tsx` |
| 14 | Repeated link and control names | FIXED. The Report links, component checkboxes and report radios now have unique names |
| 15 | The liveness badge is always green | FIXED. Its tone follows the status |
| 16 | The config warning is not announced; the lab hint is hidden | FIXED. The warning is in a `role=status` container, and the hint is always shown |
| 17 | The moment control on the Teams tab | FIXED. A note says the roster does not depend on the moment |
| 18 | Possible empty coach editor | CONFIRMED AND FIXED. It was a real bug (alliances arriving after mount); a regression test was proven against the planted bug |
| — | The Defense/Feeding table has no caption | FIXED |

## R3 — security, async state, test strength

| # | Finding | Disposition |
|---|---|---|
| 1 | A stale comparison is shown as current | FIXED. The workbench key now includes `context` and `asOf`, and `comparedTitle` records what was sent. `StrategyLabPage.test.tsx` covers it; a planted bug made it fail |
| 2 | Synergy outlives its inputs | FIXED. Keyed by `asOf`, reset when the teams are edited, and shows its teams and `as_of` |
| 3 | A timed-out write invites a duplicate | FIXED. Writes have no client timeout, and a network failure or timeout shows a "may have been stored" warning; covered by `dashboard.test.ts` and `coachInputs.test.tsx` |
| 4 | The timeout doesn't cover the body read | FIXED. The body read is inside the guarded section; covered by `http.test.ts` |
| 5 | Phase 5 reads have no timeout | FIXED. Reads time out after 30 s. *Corrected 2026-10-19:* the first fix also timed out Phase 5 **writes**, which could invite a duplicate of a write the server had stored. Now only GETs time out; writes and the upload wait for the server, as before Phase 8 (D1.3). Tested in `client.phase8.test.ts`, which fails if the fix is removed |
| 6 | The write-access check can race | PARTIAL (agrees with R4). A sequence guard in `session.tsx` fixes the wrong-state race (D1.4). There is no debounce and no test |
| 7 | Apply silently changes the moment | FIXED. Seconds are kept (`step=1`), and Apply with no change is a no-op; `asOf.test.tsx` covers it |
| 8 | A stale "Stored" confirmation | FIXED differently after R4-1. The first fix keyed the component by the strategy, which caused R4-1. Now the component stays mounted, and an outcome after edits says "your edits since then are not saved". Tested in `coachInputs.test.tsx` and `MatchPage.test.tsx` |
| 9 | Request bodies typed by hand | FIXED. They use the generated request-body interfaces |
| T | Test gaps | ADDED. Token checks on every read method; the coach-save header and body; `RecordObservation` (ISO, component, refusal); write refusal and network-failure handling with a single POST; `StrategyLabPage`; `useOnDemand`; `useResource` abort and reload; `AsOfControl`; a query-parameter contract test and a runtime guard; the smoke now fails on a 422 `validation_error` and adds a model-free analysis probe |
| — | The smoke's request bodies are its own copy | OPEN. Recorded as P8-R10 |

## R4: fix verification. What was done about its findings

R4 judged 30 of the 40 items FIXED. Its partial items are reflected in the table above. Its new issues:

| # | New issue | Disposition |
|---|---|---|
| 1 | Medium: the `SaveCoachStrategy` remount (`key=JSON.stringify(coach)`) loses an in-flight write's outcome and re-enables Save | **FIXED.** The key is removed and the component stays mounted while the coach edits. It also stays mounted while the strategy is invalid: Save is disabled and a hint is shown. It records the strategy that was **sent**; when the editor has changed since, the outcome carries "your edits since then are not saved". A click while in flight can no longer overwrite what was sent. That second bug was found by the new test, which failed until the guard was added. Tests: `coachInputs.test.tsx` "keeps a write in flight across edits…" (still busy, no second POST, the note shown, the original body) and `MatchPage.test.tsx` "saves the edited coach strategy…" (closes R4's MatchPage gap) |
| 2 | Medium (a11y): `.live-status:empty{display:none}` hid the persistent region | **FIXED.** The rule is removed. Regression test `liveRegions.test.tsx`: no stylesheet rule may hide a status region, and the idle regions are rendered. It fails when the rule is put back. Its first version read the CSS through `?raw`, which the test config's `css: false` empties, so it passed vacuously; planting the bug exposed this. It now reads the files from disk and asserts they are non-empty |
| 3 | Low–medium: stale `document.title` on pages without their own title | **FIXED.** `Shell` resets the title to "STRATAI" in a layout effect on each path change, so the page's own passive effect wins. The report sets its title from the URL at once, so it is set while loading and when refused. Test: `App.test.tsx` "does not keep the previous page title…" |
| 4 | Low: the `no_prior_concluded_event_epa` text overclaims; prototype-name lookups | **FIXED.** Both codes now read "no EPA: no qualifying earlier event with an EPA", matching `ml/ratings/provider.py:54` and `epa_states.py:14`. Lookups use `Object.hasOwn`. Tested in `display.test.tsx` "absence reasons in plain words", which includes `constructor` |
| 5 | Low: `aria-disabled` buttons have no busy style | **FIXED.** `button[aria-disabled='true']` is dimmed with a progress cursor |
| 6 | Low: "ⓘ" in the badge's accessible name | **FIXED.** It is now an `aria-hidden` span, not CSS `::after` |
| R2-9 partial | The event team comparison repeated reasons per cell | **FIXED.** Each column whose cells are all absent for one reason states it once below the table (`sharedAbsence`, `labels.ts`) |
| R2-10 partial | Tables outside `.table-scroll` | **FIXED.** The chart data tables and the EPA provenance table are wrapped |
| R2-9 "raw code in small print" | The raw code stays only in `title` and `data-reason` | **NOT CHANGED.** This is deliberate (P8-D1 D1.7) and is to be ratified |
| R2-6, R2-11 rest | Live regions in the loading text, comparison and pick list; tab auto-activation; `disabled` on the compare, rank and synergy buttons | **OPEN** (P8-R9) |
| R2-7 rest | Chart ticks are about 7 px at the 420 px minimum width | **OPEN.** The data table carries the values (P8-R9) |
| R3-6 rest | No debounce on the write-access probe | **OPEN, low.** The sequence guard prevents the wrong state |
| R3-9 rest | Coach bodies are hand-typed | **OPEN, low.** They match `docs/phase7.md`, and the body tests assert the exact JSON |
| Gaps | `invalid_coach_input` and 5xx write paths untested; smoke coverage of model routes | **OPEN.** Model routes need the environment of record (P8-R1) |

## Acceptance preparation (2026-10-19): re-review of every disposition

Each R1–R4 disposition above was re-checked against the code on 2026-10-19. The R3-5, R3-6 and R3-8 rows were
corrected, and the R4-2 row was completed.

**Found during this preparation (not by a reviewer):**

| Item | Disposition |
|---|---|
| Phase 5 writes picked up the 30 s read timeout (D1.3, first build) | **FIXED.** Only GETs time out. A malformed 2xx now says the request was accepted. Covered by 6 tests in `client.phase8.test.ts`; the key one is proven against the bug |
| The `/inputs` migration was not verified for every legacy path and link | **VERIFIED.** 3 redirect tests (including Back), plus 1 test of the Overview links through the redirects. Headless Chromium on the dev server shows all three legacy paths render their pages |
| The Overview's unknown-artifact fallback link `'/'` now opens the dashboard | **RECORDED** (D1.2), unchanged: the Phase 5 page stays byte-identical. A ruling is requested |

**Regression tests for the three save/status bugs** found in review. Each is proven: it fails when its bug is put
back and passes when restored.

| Bug | Test | Proof |
|---|---|---|
| R4-1: remounting `SaveCoachStrategy` on each edit lost an in-flight write | `MatchPage.test.tsx` "keeps a save in flight when the coach edits the strategy (regression …)" | 1 failure with `key={JSON.stringify(coach)}` restored |
| A click while in flight overwrote the record of what was sent, so the "edits not saved" note was lost (found by the test for R4-1) | `coachInputs.test.tsx` "keeps a write in flight across edits …" and the `MatchPage` test above | 2 failures with the `write.busy` guard removed |
| R4-2: `.live-status:empty{display:none}` | `liveRegions.test.tsx` "no stylesheet rule hides a status region" | 1 failure with the rule appended |

## Second pass (2026-10-19, after Sven Morais's rulings)

All four reports (R1–R4) were re-read against the rows above and against the code. The following rows change; every
other disposition stands as written.

| Finding | Was | Now |
|---|---|---|
| R2-9: keep the raw code visible "in small print" | NOT CHANGED (deliberate) | **FIXED** per the D1.7 ruling. The raw code is visible secondary text after the plain words; tested and proven, and checked in a real browser (P8-D2 §1) |
| R2-11: tab history (R4: "No test checks history or `replace`") | `replace` fixed but untested | **TESTED.** `EventPage.history.test.tsx` covers Back, Forward, shared tab links and `as_of` still pushing; proven against push-on-tab |
| R3-6: the write-access race (R4: "no debounce … No test") | PARTIAL, untested | **TESTED.** `session.race.test.tsx`, proven against the pre-Phase-8 code. **Still not debounced:** one probe per keystroke, a GET that stores nothing; documented in P8-D2 §2. It stays PARTIAL on debouncing only |
| R4: D1.2 unknown-input fallback (raised during acceptance preparation) | RECORDED, unchanged | **FIXED** per the D1.2 ruling: no link, with a clear no-page note. Tested and proven |
| New: a race in the report's print handling (seen as a test failure under load) | — | **FIXED.** The listener is attached in a layout effect, and repeated events add to the restore list. The existing print test passes in 6 of 6 full runs |
| New: intermittent failures under worker oversubscription (`ReportPage` axe timeout; one Phase 5 `GameSpecPage` failure, cause unknown) | — | **MITIGATED.** `maxWorkers: '50%'`; 6 of 6 full runs pass. Tracked as P8-R14 |

Still OPEN, unchanged (P8-R9):
- R2-6: three live regions still mount together with their content, and three buttons still use `disabled` while busy.
- R2-7: chart tick size on phones.
- R2-10: no sticky column.
- R2-11: tabs activate automatically.

## Final audit (2026-10-19)

- **All four reports re-read; no finding dropped.** The dispositions above stand. Still open: R2-6 (rest), R2-7
  (rest), R2-10 (sticky column), R2-11 (auto-activation) and R3-6 (debounce), all tracked in P8-R9 or recorded as
  not debounced.
- **Originals and derivatives.** The verbatim originals of R2 and R4 are unchanged local evidence and are excluded
  from the commit candidate, because they contain local paths. `sanitized/R2_accessibility_ux.md` and
  `sanitized/R4_fix_verification.md` are the commit copies. Each names its original's git blob and differs only in
  the replaced paths. R1, R3 and this file contain no local paths and are included as they are.
- **New in this audit:**
  - Phase 5 write-safety evidence was completed (every write tested).
  - A non-GET `network_error` now warns that the request may have been stored.
  - P8-R15 (duplicated loading and error components) was recorded.
