# P8-D2 — Sven Morais's rulings and the final dispositions of D1.1–D1.9 (2026-10-19)

**This record is authoritative for the rulings and dispositions below.**
- It adds to `P8_D1_IMPLEMENTATION_DEVIATIONS_2026-10-18.md` and does not replace it. D1 (revisions 1–2, with its own
  revision history) stays as the proposal record. Revision 1's text was revised in place on 2026-10-19 (revision 2);
  that file's revision history lists every change.
- The frozen specification is **unchanged**:
  - `docs/P8Milestones.md` = `3bef760f318c264bb38029dbf6a4471520564b1d`;
  - `P8_M0_DECISIONS.md` = `507f01df912051face85ab4fd917b20cf316b386`;
  - both rechecked on 2026-10-19 after every change below.

## 1. The rulings (Sven Morais, 2026-10-19, in writing in the session)

**D1.7 ruling, quoted:**
> Keep the plain-language absence explanation as the primary text. Add the raw reason code as readable secondary
> text, visible without hover. Ensure it remains accessible on touch devices and to assistive technology. Add or
> update a regression test proving that the raw code is visibly rendered and that the plain-language explanation
> remains present.

**Applied:**
- `Absent` (`frontend/src/dashboard/display.tsx`) renders, in this order:
  - "—";
  - a screen-reader "not available";
  - the plain words (`.absent-text`);
  - the raw code as `<code class="reason-code">(code)</code>`.
- The raw code is visible text, with no hover, `title` or `visually-hidden`, so touch users see it and screen readers
  read it.
- A reason without a plain-word mapping is already shown verbatim, so it is not repeated.
- Where a whole section shares one reason, it is stated once, and that single statement carries the code.
- **Tests** (`display.test.tsx`):
  - "shows the plain explanation first and the raw served code as visible text (D1.7 ruling, no hover needed)". It
    fails against the build without the code element (verified).
  - "does not repeat a reason that has no plain-word mapping".
- **Real browser:** headless Chromium on the team page at 390 px shows `(no_prior_concluded_event_epa)` and
  `(insufficient_data: fewer than 2 scouting observations)` after their plain words.

**D1.2 ruling, quoted:**
> Change the Overview page's fallback for an unknown input type so it does not navigate to / and unexpectedly open
> the dashboard. Use a safe Phase 5 destination or a clear unsupported-input state, consistent with existing Phase 5
> behavior. Preserve the existing /game, /profiles, and /review redirects, Overview links, and Back-button behavior.
> Add a regression test for the unknown-input case.

**Applied:**
- In `frontend/src/pages/OverviewPage.tsx`, an input type with no label lists its served name with "no input page
  for this item in this app" and **no link**. This is the only change to the Phase 5 page; known inputs keep their
  links.
- **Tests:**
  - `src/pages/OverviewPage.unknownInput.test.tsx`, a new file, so the Phase 5 Overview tests are unchanged. It
    fails against the original page (verified).
  - The redirect, Back-button and Overview-link tests in `App.test.tsx` still pass.
  - The 32 Phase 5 tests are unchanged and pass.

**P8-Q6 ruling:** recorded separately in `P8_Q6_DECISION_2026-10-19.md`.

## 2. Evidence gaps closed

- **D1.4: the race test.** `src/state/session.race.test.tsx`, a new file:
  - it types "ab";
  - it answers the "ab" probe first (accepted) and then the stale "a" probe (rejected);
  - the session still shows "accepted".

  It **fails against the pre-Phase-8 session code** (verified). The same test documents the real behaviour:
  - **one GET `/human-inputs/write-access` per token change, not debounced** (the probes are `['', 'a', 'ab']`);
  - each is a GET, which stores nothing;
  - the token goes only in a header to the same-origin API;
  - only the newest answer is applied.

  So the burst is safe. **No debouncing is claimed.**
- **D1.6: the history test.** `src/dashboard/pages/EventPage.history.test.tsx`, a new file:
  - tab clicks keep the tab in the URL, and Back leaves the page rather than stepping through tabs;
  - Forward restores the tab;
  - a shared `?tab=` link opens that tab;
  - applying a moment (`as_of`) still pushes an entry, and Back undoes it.

  It **fails when tab changes push history** (verified).

## 3. Found and fixed during this pass

- **A race in the report's print handling.** The `beforeprint` listener was attached in a passive effect, so there
  was a moment when the report was on screen but printing would not open its sections. Under load the print test
  failed once. It is now a layout effect, attached during the commit, and repeated `beforeprint` events add to the
  restore list.
- **Test reliability.** With the default of one jsdom worker per CPU, the full frontend run oversubscribed the 8-CPU
  machine. Whole files ran 10–20× slower, and the following failures were seen:

  | Test | Failures |
  |---|---|
  | `ReportPage` axe test (15 s timeout) | 1 |
  | the print race above | 1 |
  | Phase 5 `GameSpecPage` upload test | 1, in 15 runs |

  The cause of the `GameSpecPage` failure was not established, and it did not reproduce. `vite.config.ts` now sets
  `maxWorkers: '50%'`. After that, **6 of 6 full runs passed** (145 tests each, about 22–24 s, against 33–74 s
  before). No test assertion was changed or weakened.

## 4. Final dispositions of D1.1–D1.9 (rechecked against code, tests and compatibility on 2026-10-19)

| # | Deviation | Code (verified) | Tests (all pass) | Compatibility | Disposition |
|---|---|---|---|---|---|
| D1.1 | Separate dashboard client, registry and contract test | `api/dashboard.ts` (23 operations, `NOT_CALLED`, a runtime query guard); Phase 5 `ENDPOINTS` unchanged | `tests/test_phase8_frontend_contract.py` 6; `test_frontend_api_contract.py` 3 (unchanged); `dashboard.test.ts` 8 | No API change; lock unchanged | **Ratified** |
| D1.2 | Human inputs under `/inputs`, legacy redirects; unknown-input fallback per ruling | `App.tsx` `<Navigate replace>` ×3; the `OverviewPage` fallback has no link | `App.test.tsx` (redirect ×4, Back, Overview links); `OverviewPage.unknownInput.test.tsx`; 32 Phase 5 tests | Old bookmarks and links work; `/` is the dashboard; the unknown-input row is now an explicit no-page state | **Ratified, with the ruling applied** |
| D1.3 | Phase 5 client on the shared fetch core | `client.ts`: reads time out at 30 s; non-GET calls and the upload never time out; typed errors | `client.phase8.test.ts` 6 (the write-timeout test is proven against the bug); `http.test.ts` 9; 32 Phase 5 tests | A hung read now ends in a typed timeout. No new duplicate-write risk. Nothing retries | **Ratified** |
| D1.4 | Sequence guard on the write-access probe | `session.tsx` `accessCheck` | `session.race.test.tsx` (proven) | One probe per keystroke, not debounced, and safe (section 2) | **Ratified, not debounced** |
| D1.5 | Coach writes: `aria-disabled`, no timeout, unknown-outcome and accepted-outcome warnings, the save survives edits | `coachInputs.tsx`, `MatchPage.tsx` | `MatchPage` 9, `coachInputs` 7, `liveRegions` 2, `dashboard.test.ts` (all three save/status regressions proven) | No double submit; nothing changes on the server | **Ratified** |
| D1.6 | Tab changes replace the history entry | `useTab.ts` `{ replace: true }` | `EventPage.history.test.tsx` 2 (proven); `EventPage.test.tsx` | Back leaves the page; tab links are still shareable; `as_of` still pushes | **Ratified** |
| D1.7 | Plain-word reasons, now with the raw code visible | `display.tsx` `Absent`; `labels.ts` `reasonText` (`Object.hasOwn`) | `display.test.tsx` 17, including the two D1.7 tests (proven) | Nothing hidden; the raw code is visible and in `data-reason` | **Ratified, with the ruling applied** |
| D1.8 | Verbatim label badges with a reachable explanation | `display.tsx` `ValidationBadge` | `display.test.tsx` (verbatim labels, distinct PX labels, explanation toggle); `AlliancePage` (never relabelled) | `validated_playoff_success` and `validated_playoff` stay distinct | **Ratified** |
| D1.9 | Test infrastructure | `axe-core` (dev only; the only lockfile addition); `testTimeout: 15_000`; `maxWorkers: '50%'` (new, section 3); async `mockApi`; one oxlint override for `src/test/**`; a per-file `@types/node` reference in `liveRegions.test.tsx` | Full run 145 passed, 6 of 6; lint 8 warnings (Phase 5 baseline) | Test and lint only; no runtime dependency | **Ratified, with `maxWorkers` added** |

**M0 disposition:** the frozen-spec baseline is intact, and D1.1–D1.9 are ratified as above, by Sven's direction of
2026-10-19 that ratification follows once this evidence was complete.

## Addendum: final audit (2026-10-19)

**D1.3 evidence was strengthened, and one message was added. No disposition changes.**
- `client.phase8.test.ts` now names and tests every Phase 5 write, and checks the list against `ENDPOINTS`. Each write
  has no client timeout, is sent once and is never retried. These tests are proven: 10 of 18 fail without the rule.
- A `network_error` on any non-GET request now says the request may still have been stored, and to check before
  submitting it again. This is shown on the Phase 5 pages and in the dashboard; reads are unchanged.

This stays within D1.3's ratified scope ("typed errors"; no unsafe retry or duplicate-submission behaviour), and no
frozen text changed.
