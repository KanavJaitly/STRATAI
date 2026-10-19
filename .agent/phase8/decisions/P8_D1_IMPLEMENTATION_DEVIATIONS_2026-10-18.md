# P8-D1 — Implementation deviations from the P8-M0 working freeze: PROPOSED RATIFICATION

> **2026-10-19:** Sven Morais's rulings on D1.2 and D1.7, the closed evidence gaps (D1.4, D1.6) and the final
> dispositions of D1.1–D1.9 are recorded in `P8_D2_RULINGS_AND_DEVIATION_DISPOSITIONS_2026-10-19.md`, which is
> authoritative for them. This file is kept unchanged below as the proposal record.

- **Dates:** drafted 2026-10-18; revision 2 on 2026-10-19 (see "Revision history").
- **Status: PROPOSED.** This is for review by Sven Morais. It is **not approved**, and nothing here claims approval
  on his behalf.
- **Author:** Claude Code, under the Phase 8 execution mandate.

## Integrity of the frozen specification

The frozen files are **unchanged**. This record only describes deviations; it does not edit the spec.

| Frozen file | Blob recorded in `P8_M0_FREEZE.md` | `git hash-object` on 2026-10-19 |
|---|---|---|
| `docs/P8Milestones.md` (revision 1) | `3bef760f318c264bb38029dbf6a4471520564b1d` | `3bef760f318c264bb38029dbf6a4471520564b1d` ✔ |
| `.agent/phase8/P8_M0_DECISIONS.md` | `507f01df912051face85ab4fd917b20cf316b386` | `507f01df912051face85ab4fd917b20cf316b386` ✔ |

**What ratification would mean:** the build is accepted as conforming to the freeze, with these nine recorded
departures. Rejecting an item means reverting it; the "Revert" line under each item says how.

---

## D1.1 — A separate dashboard client, registry and contract test

- **Frozen text:** P8-M1 (d) says "the typed client extended to the Phase 7 operations, in the one `ENDPOINTS`
  registry". The standing rules say "`tests/test_frontend_api_contract.py` checks every one".
- **Built:**
  - `frontend/src/api/dashboard.ts` holds:
    - `DASHBOARD_ENDPOINTS`: 23 operations;
    - `NOT_CALLED`: the deprecated ranking route, with its reason;
    - `DASHBOARD_QUERY_PARAMS`: enforced at run time by `call()`.
  - A new backend test, `tests/test_phase8_frontend_contract.py`, has 6 tests.
  - The Phase 5 `ENDPOINTS` and `tests/test_frontend_api_contract.py` are unchanged.
- **Rationale:** `test_frontend_api_contract.py` asserts that the human-input app "never calls the core prediction
  routes". Adding the dashboard routes to that registry would have meant weakening an existing contract test, which
  the mandate forbids.
- **Compatibility:**
  - There is no API change. The Phase 7 lock check gives `changed: []`, `added: []`.
  - The existing test is untouched and still passes.
- **Tests:**
  - `test_every_route_the_dashboard_calls_exists`
  - `test_every_locked_operation_is_called_or_explicitly_not_called`
  - `test_the_dashboard_calls_only_locked_operations`
  - `test_the_generated_types_are_current`
  - `test_the_generated_types_carry_the_locked_validation_literals`
  - `test_every_query_parameter_the_dashboard_sends_is_declared`
  - `dashboard.test.ts`: "refuses a query parameter the operation does not declare"
  - Phase 5: `tests/test_frontend_api_contract.py`, 3 passed, unchanged
- **Revert:** fold `DASHBOARD_ENDPOINTS` into `ENDPOINTS`. This would require changing the Phase 5 contract test, so
  **not recommended**.

## D1.2 — The human-input pages move under `/inputs`, with legacy redirects

- **Frozen text:** the P8-M1 acceptance says "the existing human-input pages … are unchanged".
- **Built:**
  - The page components and their 32 tests are byte-identical to `HEAD` (`git diff HEAD -- frontend/src/pages` is
    empty).
  - The shell now routes them at:
    - `/inputs` (overview)
    - `/inputs/game`
    - `/inputs/profiles`
    - `/inputs/review`
  - Each old path (`/game`, `/profiles`, `/review`) redirects with `<Navigate replace>`.
  - `/` is now the dashboard.
- **Rationale:** two areas share one shell (P8-Q1), and the dashboard is the primary area.
- **Compatibility, verified on 2026-10-19:**
  - **Legacy paths.** Each one redirects to its `/inputs` page. Back returns to the previous page; it does not
    bounce back into the redirect. This is tested (`App.test.tsx`, 3 cases) and checked in a real browser: headless
    Chromium on the dev server shows `/game`, `/profiles` and `/review` render the Game manual, Team profiles and
    Human review pages, with the right nav item current and no "Page not found".
  - **Existing in-app links.** The Phase 5 `OverviewPage` still links to `/game`, `/review` and `/profiles`. It was
    deliberately left unchanged, and the links work through the redirects. Tested: "keeps the Phase 5 overview links
    to the old paths working through the redirects".
  - **No query strings or hashes are lost.** The Phase 5 pages read no query parameters or hash (none use
    `useSearchParams` or `useLocation`).
  - **Documentation.** `frontend/README.md` and `docs/phase8.md` describe the new paths. `docs/phase5.md` names no
    UI paths.
  - **Known side effect.** `OverviewPage`'s fallback link for an *unknown* artifact is `page: '/'`, which now opens
    the dashboard rather than the inputs overview. Only artifacts outside its label table reach this fallback (none
    are served today). It is left unchanged so the Phase 5 page stays byte-identical. A one-line change to
    `'/inputs'` would fix it if wanted.
- **Tests:**
  - `App.test.tsx`: "redirects the old human-input paths to /inputs"
  - `App.test.tsx`: "redirects %s to its page under /inputs, replacing the history entry", for `/game`,
    `/profiles` and `/review`
  - `App.test.tsx`: "keeps the Phase 5 overview links to the old paths working through the redirects"
  - the 32 Phase 5 tests
- **Revert:** mount the dashboard elsewhere (e.g. `/dashboard`) and restore the Phase 5 routes at the root.

## D1.3 — The Phase 5 client uses the shared fetch core

- **Frozen text:** none directly. P8-Q10 says "a timeout gives a typed error"; the Phase 5 client is otherwise
  unchanged.
- **Built:** `client.ts` sends through `http.ts` (`requestJson`). As a result:
  1. **Phase 5 reads (GET) time out after 30 s**, with `ApiRequestError('timeout', status 0)`. Before, a hung API
     left "Loading…" on screen forever (review R3-5).
  2. **Phase 5 writes, and the manual upload, have no client timeout. This is unchanged from before Phase 8.**
     *Revision 2:* the first build gave every non-upload call the 30 s timeout, so a write the server had stored
     could time out on the client. Phase 5's `useAction` then re-enables the button, which invites a duplicate of
     a non-idempotent write (`createProfile`, `duplicateProfile`, `submitArtifact`). This was found in the 2026-10-19
     check and fixed: `call()` disables the timeout for every non-GET.
  3. **A failed connection** is now `ApiRequestError('network_error', status 0)`, not a raw `TypeError`. It is shown
     by the existing Phase 5 `ErrorNotice` as code, status and message.
  4. **A 2xx whose body is not JSON** is now `ApiRequestError('malformed_response')` with the 2xx status. Its
     message says the request was **accepted**, so nobody resubmits it. Before, it silently resolved to `null`.
  5. `getWriteToken()` was added for the dashboard's coach writes.
- **Safety, verified:**
  - Nothing retries automatically: one `fetch` per call (tested).
  - Phase 5's `useAction` has no retry path; this was confirmed by reading `src/components/hooks.ts`.
  - The token header goes only on non-GET calls plus the `write-access` probe, unchanged.
  - Envelope errors keep their code, status and request id.
- **Compatibility:** the 32 Phase 5 tests pass unchanged. User-visible changes:
  - a hung read now ends in a timeout error after 30 s, instead of loading forever;
  - transport failures and malformed responses get typed messages.
- **Tests:** in `src/api/client.phase8.test.ts` (new; the Phase 5 test files are untouched):
  - "times a read out after 30 s with a typed error, sent once"
  - "lets a write wait for the server however long it takes (no client timeout to invite a duplicate)". Proven
    against the bug: the test fails when the fix is removed.
  - "lets the manual upload wait too"
  - "reports a failed connection on a write as a typed network_error, once, with no retry"
  - "says a malformed success on a write was accepted, so nobody resubmits it"
  - "keeps the envelope error of a refused write as served"

  Plus `http.test.ts` (9 tests).
- **Revert:** restore Phase 5's own fetch body in `call()`. That would reintroduce the infinite read hang.

## D1.4 — A sequence guard on the session's write-access probe

- **Built:** in `state/session.tsx`, `refreshAccess` ignores an answer to an older probe. Before, a late answer for a
  partial token could show "token accepted" for the wrong token (R3-6).
- **Rationale and compatibility:** UI only; the server still decides every write. There is no debounce, so one probe
  is still sent per keystroke.
- **Tests:** none specific. The Phase 5 tests pass, and the race is fixed by reading (R4 rated it PARTIAL: fixed, but
  not debounced and untested).
- **Revert:** remove the guard.

## D1.5 — Coach writes: `aria-disabled` while in flight, no client timeout, an unknown-outcome warning

- **Frozen text:** P8-Q8 says writes are "disabled while in flight".
- **Built:**
  - While a write is in flight, the button is `aria-disabled` and keeps focus. A synchronous guard ignores clicks.
  - Writes have **no client timeout**.
  - After `network_error` or `timeout`, a warning says the write may have been stored. After `malformed_response`
    (a 2xx with an unreadable reply), it says the write was accepted and stored. Both say to check before
    resubmitting.
  - `SaveCoachStrategy` **stays mounted** while the coach edits. Each outcome describes the strategy that was sent,
    and if the editor has changed since, it says "your edits since then are not saved".
- **Rationale:**
  - R2-6: `disabled` dropped focus.
  - R3-3: a timed-out write invited a duplicate.
  - R4-1: remounting on each edit lost an in-flight write.
- **Compatibility:** a double submit remains impossible. Nothing changes on the server.
- **Tests:**
  - `MatchPage.test.tsx`:
    - "gates coach writes … a double click stores once"
    - "saves the edited coach strategy (not the AI one), with the token"
    - "keeps a save in flight when the coach edits the strategy (regression …)". Proven: it fails if the remount key
      is put back.
  - `coachInputs.test.tsx`:
    - "warns that a write may have been stored …"
    - "says an accepted write with an unreadable reply was stored, and does not post again"
    - "keeps a write in flight across edits …". Proven: it fails if the busy guard in `save` is removed.
    - the RecordObservation tests
  - `dashboard.test.ts`: "lets a coach write wait past the read timeout"
  - `liveRegions.test.tsx` (status regions persist). Proven: it fails if `.live-status:empty{display:none}` is put
    back. Its first version read CSS through a `?raw` import, which `css: false` empties, so it would have passed
    regardless. It now reads the files from disk and asserts they are non-empty.
- **Revert:** use `disabled` instead (this loses focus).

## D1.6 — Tab changes replace the history entry

- **Frozen text:** P8-Q9 says "back/forward works" for the selection.
- **Built:** a tab change uses `replace`. All other selections push history entry: `as_of`, side, configuration,
  pairing and season. The tab stays in the URL, so a link to it is still shareable.
- **Rationale:** R2-11. Each arrow-key press pushed a history entry, so Back stepped through the tabs.
- **Compatibility:** Back now leaves the page rather than stepping back through tabs.
- **Tests:** `EventPage.test.tsx` "switches tabs through the URL …" (the URL carries the tab). There is no test that
  asserts `replace` itself (R4 noted this).
- **Revert:** drop `{ replace: true }` in `useTab.ts`.

## D1.7 — Absence reasons in plain words; a shared reason is stated once

- **Frozen text:** the standing rules say "Nullable values render as absence, with the served reason".
- **Built:**
  - `reasonText` (`labels.ts`) maps each known reason code to plain text. Every mapped code was checked to exist in
    `ml/`, `api/` or `data/`, and the EPA wording was corrected after R4 to match `ml/ratings/provider.py`.
  - An unknown reason is shown **exactly as served**. Lookups use `Object.hasOwn`.
  - The raw reason stays on the element, as `title` and `data-reason`.
  - Where every value in a section or column is absent for one reason, the reason is stated once and each cell shows
    "—". This applies to EPA parts, report roles and EPA, and columns of the team comparison.
- **Rationale:** R2-9. Raw codes repeated in every cell were unreadable.
- **Compatibility:**
  - Nothing is hidden: the reason is always visible once, and the raw code stays in the DOM.
  - The raw code is **not** shown visibly in small print, as R2 suggested; it appears only in the tooltip. This is
    the point to rule on.
- **Tests:**
  - `display.test.tsx`: "renders a missing measurement as a dash with its reason, never 0"
  - `display.test.tsx`: "absence reasons in plain words" (known, unknown and prototype names, `data-reason`)
  - `ReportPage.test.tsx`: roles absent, stated once
  - `TeamPage.test.tsx`
- **Revert:** render the raw reason, as before.

## D1.8 — Each label is a toggle badge with a reachable explanation

- **Frozen text:** P8-Q4 says labels are "shown verbatim, with a plain explanation".
- **Built:**
  - The badge text is the raw `validation.status`, verbatim.
  - The badge is a button with `aria-expanded`, revealing the explanation inline.
  - The explanation is also its `aria-describedby`.
  - The "ⓘ" is `aria-hidden`.
  - Inside a `<summary>` the badge is a non-interactive span.
  - Badges are kept out of headings.
- **Rationale:** R1-2 (verbatim labels) and R2-2 (title-only explanations were unreachable by keyboard, touch and
  screen readers).
- **Compatibility:** `validated_playoff_success` and `validated_playoff` stay distinct.
- **Tests:** `display.test.tsx`:
  - "keeps validated_playoff_success and validated_playoff distinct (P7-D7)"
  - "shows an unknown label verbatim …"
  - "label explanations reveal the plain explanation inline …"

  Plus `AlliancePage.test.tsx` ("never relabelled").
- **Revert:** a plain span with a `title`.

## D1.9 — Test infrastructure

- **Built:**
  - `axe-core` 4.14.0 is a dev dependency only (allowed by P8-Q3). The only new package in the lockfile is
    `node_modules/axe-core`.
  - `vite.config.ts` sets `testTimeout: 15_000`: an axe run over a whole page exceeded 5 s when all the test files
    ran in parallel.
  - The `mockApi` test helper now awaits async handlers. This is backwards compatible, and the Phase 5 tests pass.
  - `.oxlintrc.json` adds one override, turning off `only-export-components` for `src/test/**` only. Lint stays at
    the Phase 5 baseline: 8 warnings, 0 errors.
  - `liveRegions.test.tsx` uses `/// <reference types="node" />`, with the existing `@types/node`, to read CSS from
    disk.
- **Compatibility:** test and lint only. No runtime dependency was added.
- **Revert:** remove each item; the axe checks would then go.

---

## Revision history

- **2026-10-18, revision 1:** D1.1–D1.9 drafted.
- **2026-10-19, revision 2:**
  - D1.3: Phase 5 writes no longer time out (a duplicate-submission hazard found while verifying this record), and a
    malformed 2xx is reported as accepted.
  - D1.2: redirect and link verification added.
  - D1.5: the R4 regressions and proven regression tests added.
  - Tests listed for each item.

## Decision requested

Sven Morais: ratify D1.1–D1.9 as a set, or name the items to revert or amend. Two points need a ruling in
particular:
- **D1.7:** whether the raw reason code should also be visible in small print.
- **D1.2:** whether to change the Phase 5 Overview's unknown-artifact fallback link to `/inputs`. That would end the
  byte-identical status of the Phase 5 pages.
