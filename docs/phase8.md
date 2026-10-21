# Phase 8 — Frontend / Dashboard

The strategy dashboard is built on the Phase 7 API. It extends the existing `frontend/` app (React 19, TypeScript,
Vite, React Router, Vitest), next to the Phase 5 human-input pages.

- **Spec:** `docs/P8Milestones.md` (revision 1, the agent's working freeze). The baseline and deviations D1.1–D1.9
  were ratified on 2026-10-19 by Sven Morais's rulings and direction (`.agent/phase8/decisions/P8_D2_…`).
- **Decisions:** `.agent/phase8/P8_M0_DECISIONS.md` (P8-Q1…Q13).
- **Status:** `.agent/phase8/PHASE_STATUS.md`.
- **Acceptance:** `.agent/phase8/PHASE_ACCEPTANCE.md`.

## Running it

```sh
# API: the dashboard reads the Phase 7 routes. Writes (coach inputs) need HUMAN_INPUTS_WRITE_TOKEN on the server.
python -m api                                    # http://127.0.0.1:8000

# web app
cd frontend
npm ci
npm run dev                                      # http://localhost:5173, proxies /api to STRATAI_API_URL
```

- **The dev proxy** sends `/api/*` to `STRATAI_API_URL` (default `http://127.0.0.1:8000`) and strips `/api`. This is
  same-origin by design: the API's CORS allow-list is not widened for the write token.
- **In production,** serve `npm run build`'s `dist/` from the same origin as the API, with `/api/*` routed to the
  API and the prefix stripped. `VITE_API_BASE` changes the client's base path.
- **Unknown paths:** serve `index.html` for every path the static files do not match (history fallback), so a
  shared link such as `/report/2026mrcmp_qm12` opens directly.
- **The probes** (`/health`, `/ready`) sit outside the server's `API_PREFIX`. The documented deployment (an empty
  `API_PREFIX`, with `/api` stripped by the proxy) reaches them as `/api/health` and `/api/ready`.
- **No secret is in the bundle.** The write token is typed into the page header and held in memory only.

**Local verification without the environment of record:**
- run the API with `DATABASE_URL=<.../stratai_test> EPA_SOURCE=statbotics API_PORT=8765`;
- run the app with `STRATAI_API_URL=http://127.0.0.1:8765`.

Model-backed parts then show `model_not_loaded`, and the pick list shows `not_approved`.

## Tests and checks

| Check | Command | What it covers |
|---|---|---|
| Unit and page tests | `cd frontend && npm test` | Vitest + Testing Library + jsdom: 157 tests in 27 files, 32 of them the unchanged Phase 5 tests. Fixtures are synthetic and typed from the generated API types; the tests include axe checks |
| Types | `npm run typecheck` | `tsc -b` |
| Lint | `npm run lint` | oxlint (8 pre-existing warnings in Phase 5 files; none in Phase 8 files) |
| Build | `npm run build` | type check + `vite build` |
| API types current | `python -m scripts.phase8_generate_api_types --check` | `frontend/src/api/generated.ts` equals what the live OpenAPI document renders |
| Contract | `pytest tests/test_phase8_frontend_contract.py tests/test_frontend_api_contract.py` | Every dashboard route exists. Every locked operation is called or explicitly not called. Only locked operations are called. The query parameters match OpenAPI. The types are current |
| Live smoke | `python -m scripts.phase8_live_smoke --api <API> --season <year> [--app <app URL> --chrome <headless chromium>]` | Calls every dashboard operation and records its status and code. A 422 `validation_error` fails the run. Coach writes are sent without a token and must be refused. The optional browser run loads every page in headless Chromium |

**Regenerate the API types** after any API change, including description-only changes:
`python -m scripts.phase8_generate_api_types`.

## Rules every view follows (P8-Q4, P8-Q5)

**Probabilities are shown exactly as served.**
- Strategy and playoff odds are the engine's display strings (`<5%`, `>95%`, 0.05 steps), with their validation
  status and reasons.
- The M6/M7 value (`CalibratedWinProbability`) is a percentage only when validated. An unvalidated value is marked
  "Unvalidated model output", with its reason, and never styled as a probability.
- The two models never share a field.
- Nothing is computed, rounded, compared or derived client-side.

**Labels are shown verbatim,** each with a plain explanation. The badge is a toggle that reveals the explanation inline,
and it is the badge's accessible description. `validated_playoff_success` (the event-level PX-4 label,
P7-D7) and `validated_playoff` (PX-2 match probabilities) are never merged.

**Absences are explicit.** A null value is "—" with its reason, never 0.
- The served reason is shown in plain words (`reasonText` in `frontend/src/dashboard/labels.ts`), followed by the
  raw served code as visible secondary text. For example, `withheld_no_prior_event` reads "no EPA: no qualifying
  earlier event with an EPA (withheld_no_prior_event)". No hover is needed, so the code also reaches touch and
  screen-reader users (the D1.7 ruling, 2026-10-19).
- A reason without a plain-word mapping is shown exactly as served, once.
- The raw reason is also kept in `data-reason`.
- When a whole section shares one reason, the reason is stated once and the cells show "—".

**Refusals are states.** One map (`frontend/src/dashboard/refusals.ts`) explains each API refusal. The code, the
server message and the request id stay visible. Transport failures (`network_error`, `timeout`,
`malformed_response`) get a Retry; nothing retries automatically.

**The moment (`as_of`) and the selection** (season, tab, side, configuration, pairing) live in the URL, so every
view is shareable and back/forward works.
- A tab change replaces the history entry, so Back leaves the page.
- `as_of` is kept to the second, and Apply without a change keeps the URL's exact instant.

**Coach writes** (`/strategy/coach-strategies`, `/strategy/coach-observations`) behave as follows:
- They send the session's in-memory write token. No read sends it, and a test checks every read method.
- They have no client-side timeout and are never retried.
- While a write is in flight, its button is `aria-disabled` and further clicks are ignored.
- After a network failure, the page warns that the write may have been stored, rather than inviting a duplicate.

**Accessibility (WCAG 2.1 AA intent):**
- After a navigation, focus moves to `main` and the page title follows the h1.
- Every view has axe checks in its tests.
- Tables and charts scroll inside their own box on phones.
- Printing the report opens its collapsed sections.

## Views

| Route | View | API operations | Notes |
|---|---|---|---|
| `/?season=` | Events | `GET /events` | Search and sort; empty and failure states |
| `/events/{e}` | Event dashboard | `/events/{e}/analysis`, `/teams`, `/matches`, `/qualification-forecast` (+ `GET /events` for the name) | Tabs fetch on first visit. The predicted ranking shows its model (raw EPA / M5 v2) and switch point. Playoff contenders are `captain_candidates` and `strongest_teams`. The team comparison carries the INTERIM caveat |
| `/events/{e}/teams/{t}` | Team profile | `/strength` (as_of), `/metrics`, `/events/{e}/matches` | Strength with the EPA components, defense and feeding (scouting-only), history (the event's matches filtered to the team), and charts of alliance scores and season auto points. Stored metrics are labelled a whole-event snapshot |
| `/matches/{m}` | Match strategy | `/strategy/matches/{m}/recommend` and `/compare`, `/predictions/matches/{m}/win-probability`, `/events/{e}/matches`, coach writes | The AI recommendation (with `selection_note`) and the coach strategy side by side, evaluated in one `compare` call. M6/M7 sits in its own panel. Coach strategy and observation writes are gated, never retried, and blocked while in flight |
| `/events/{e}/strategy-lab` | Hypothetical pairing | `/strategy/hypothetical/recommend` and `/compare`, `POST /predictions/win-probability`, `/events/{e}/teams` | The same workbench as a scheduled match |
| `/events/{e}/alliance-selection` | Alliance selection | `/alliance-selection/candidates`, `/pick-list`, `POST /predictions/alliance-synergy` | Candidate factors with n and status (absent values sort last). A draft-state builder for the pick list: today the real refusal (`not_approved`, P6-DM1); when served, ranked picks, reach-finals labels, alternatives and provenance, as `validated_playoff_success` |
| `/report/{m}?as_of=&side=` | Pre-match report | `GET /matches/{m}/pre-match-report` | Shareable: a stable URL, Copy link, Print. Our and the opposing alliance (role from the engine's strategy, expected contribution = EPA by phase), synergy, the forecast (M6/M7), strategy detail, and evidence per robot. The six items no engine produces are explicit absences with their meaning (P7-Q12, P8-Q6) |
| `/status` | System status | `/health`, `/ready` | As the probes report |
| `/inputs/*` | Human inputs (Phase 5) | `/human-inputs/*` | Unchanged; the old paths `/game`, `/profiles` and `/review` redirect |

The deprecated `GET /predictions/events/{e}/ranking` is deliberately not called (`NOT_CALLED` in `dashboard.ts`).
The canonical ranking is the analysis ordering (P7-Q2).

## Verification states (kept separate)

| State | Meaning |
|---|---|
| Implemented | In the code |
| Tested with fixtures | Synthetic, typed fixtures in Vitest |
| Verified against the local API | `scripts/phase8_live_smoke.py` against `stratai_test` with the reference EPA source; results in `.agent/phase8/runs/` |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | Phase 8 CONDITIONALLY ACCEPTED, not fully complete (2026-10-19, as directed by Sven Morais; `.agent/phase8/PHASE_ACCEPTANCE.md`) |

## Contract-test changes

| Date | Test | Change | Why |
|---|---|---|---|
| 2026-10-18 | `tests/test_frontend_api_contract.py` | Unchanged; it still checks the Phase 5 client (`client.ts`) both ways, including "never calls the core prediction routes" | The dashboard has its own client and registry (`dashboard.ts`) and its own test (`tests/test_phase8_frontend_contract.py`), so that guarantee about the human-input app still holds |

## Deviations from the frozen spec

The deviations D1.1–D1.9 were ratified on 2026-10-19 by Sven Morais's rulings and direction. The proposal is in
`.agent/phase8/decisions/P8_D1_IMPLEMENTATION_DEVIATIONS_2026-10-18.md`, and the rulings and final dispositions are in
`P8_D2_RULINGS_AND_DEVIATION_DISPOSITIONS_2026-10-19.md`.
- **Registry and test:** a separate dashboard registry and contract test.
- **Routes:** the human-input pages are under `/inputs`, with redirects from the old paths. An unknown input type on
  the Overview shows a no-page note and no link.
- **Timeouts:** Phase 5 reads time out after 30 s; Phase 5 writes and the upload never time out.
- **Write-access probe:** guarded against out-of-order answers. One probe per keystroke; not debounced.
- **Coach-write buttons:** `aria-disabled` while in flight, and a save survives edits.
- **Tabs:** a tab change replaces the history entry; a moment change still pushes one.
- **Reasons:** absence reasons are in plain words, with the raw code visible.
- **Labels:** each label is a badge with an explanation you can open.
- **Test infrastructure:** `axe-core`, timeouts, and `maxWorkers: '50%'`.

## Known gaps

All are in `.agent/phase8/RISK_REGISTER.md`.
- **Not seen with real models:** nothing has been checked in the environment of record (P7-Q5). Every model-backed
  view has been seen only as its refusal.
- **Report:** P8-DM2 "complete" is NOT MET and deferred. Six report items have no engine and stay explicit absences
  (P8-Q6 decided 2026-10-19: Option C now, then D; `.agent/phase8/decisions/P8_Q6_DECISION_2026-10-19.md`).
- **Coach writes:** verified on 2026-10-19 against a live local API on a disposable, empty database with synthetic
  data (P8-R7 closed). Not verified in the environment of record.
- **Accessibility** (P8-R9): closed on 2026-10-19.
  - Tabs open only on Enter or Space; arrow keys move focus.
  - Status lines are persistent.
  - Busy buttons are `aria-disabled` and guarded.
  - Scrolling tables keep a sticky first column.
  - Chart ticks are readable on phones.
- **Test reliability** (P8-R14): the frontend tests run on half the CPUs (`maxWorkers: '50%'`). With one worker per
  CPU, intermittent timeouts occurred.
- **Printing:** A4 pagination was fixed and verified on 2026-10-19 for locally servable content. The
  model-populated sections have not been printed (P8-R11, which depends on the environment of record).
