# Phase 8 — Frontend / Dashboard: phase audit, acceptance review and PROPOSED conditional acceptance

> **Superseded 2026-10-19** by `PHASE_ACCEPTANCE.md` (the conditional-acceptance record, as directed by Sven Morais). Kept unchanged below as the proposal of record.

**Status: PROPOSED, awaiting Sven Morais's approval.**
- This record claims no approval. No commit, push or PR has been made, and Phase 9 has not been started.
- Branch `phase8/build` is based on main `7c678eb`. Every change is uncommitted, and nothing is staged.
- Prepared 2026-10-19 under Sven Morais's instruction to prepare Phase 8 for conditional acceptance.

**Verification states are kept separate throughout:**
- implemented;
- tested with fixtures (synthetic);
- verified against the local API (`stratai_test`, reference EPA source);
- verified in the environment of record: **BLOCKED** (P7-Q5) for every milestone;
- accepted by a human: **PENDING** for every milestone.

---

## 1. Done-means: each criterion mapped to its evidence

The roadmap wording is immutable (`docs/ROADMAP.md`, Phase 8): "Done means: every view runs off the real API
endpoints, and the pre-match report is complete and shareable with an alliance partner as-is."

### P8-DM1 — "every view runs off the real API endpoints": **MET AGAINST THE LOCAL API ONLY**

This is **not** a production or environment-of-record verification.

| Element of the criterion | Evidence | Verification state |
|---|---|---|
| Every view's data comes from API endpoints, not client data | No shipped code contains sample data; fixtures are imported only by tests (R1 checked this). Every value is read from a `dashboardApi` call | Implemented; fixture-tested |
| …the **real** endpoints, i.e. the locked Phase 7 contract | `tests/test_phase8_frontend_contract.py` checks four things against OpenAPI and the lock: every dashboard route exists; every locked operation is called or listed in `NOT_CALLED`; only locked operations are called; the query parameters match in both directions. 6 passed (`runs/contract_tests.txt`). Lock check: `changed: []`, `added: []` (`runs/contract_lock.txt`) | Implemented; contract-tested |
| …running against a real server | `scripts/phase8_live_smoke.py`: 24 API calls (23 operations, plus a pre-switch-point analysis probe) and all 11 pages in headless Chromium, against the running API on `stratai_test`. Exit 0, ALL OK (`runs/live_smoke.json`, `runs/live_smoke.txt`, 2026-10-19) | **Verified against the local API** |
| …with real models and serving data | Every model-backed part was seen **only as its declared refusal**: `model_not_loaded` for analysis, forecast, win probability and strategy, and `not_approved` for the pick list. No pinned models and no serving data are available here | **BLOCKED (P7-Q5)**: not verified |

### P8-DM2 — "the pre-match report is complete and shareable with an alliance partner as-is": **NOT MET**

| Element of the criterion | Evidence | State |
|---|---|---|
| Our alliance: role | Served from the engine's recommended strategy, or its labelled baseline. Live, it is absent (`model_not_loaded`) | Implemented and fixture-tested; live refusal only |
| Our alliance: expected scoring contribution | Served EPA by phase, with n | Implemented; verified locally |
| Our alliance: **strengths/weaknesses per robot** | `not_produced.strengths_and_weaknesses`: no engine produces it | **MISSING** |
| Opposing alliance: roles and contributions | As for our alliance | As above |
| Opposing alliance: **defensive threats** | `not_produced.defensive_threats` | **MISSING** |
| Opposing alliance: **key risks** | `not_produced.key_risks` | **MISSING** |
| Match forecast: **predicted flow** | `not_produced.predicted_flow` | **MISSING** |
| Match forecast: **critical matchups** | `not_produced.critical_matchups` | **MISSING** |
| Match forecast: **key success factors** | `not_produced.key_success_factors` | **MISSING** |
| Match forecast: win probability | M6/M7 `CalibratedWinProbability`, with its validation status. Live, `model_not_loaded` | Implemented and fixture-tested; live refusal only |
| **Complete** | Six of the roadmap's items are absent. They are labelled "not produced by any engine", each with its semantics. **A labelled absence is not a completed field** | **NOT MET**, pending P8-Q6 (`decisions/P8_Q6_REPORT_COMPLETENESS_BRIEF_2026-10-19.md`) |
| **Shareable as-is** | A stable URL (`/report/{match}?as_of=&side=`) that reproduces the report; Copy link; Print (collapsed sections open for printing; tested). Outside the team's machine it needs a deployment (P8-R4). A4 output is not verified (P8-R11) | Met locally |

---

## 2. Milestone-by-milestone acceptance status (PROPOSED)

The proposal is to accept M1–M7 **on their recorded local evidence**. "Proposed: accept" below means: if Sven
approves, the milestone is accepted with the stated limits. Each record has the details.

| Milestone | Frozen acceptance criteria | Evidence | Limits | Proposed |
|---|---|---|---|---|
| **M0** spec and decisions | Every roadmap item maps to a milestone; conflicts are recorded; human items are listed | `M00_ACCEPTANCE.md`; the freeze blobs are unchanged | Agent working freeze | **Ratify** with D1.1–D1.9 |
| **M1** foundation | The type-drift test and the endpoint contract test pass. Client behaviour is tested (abort, timeout, stale, envelope, network, malformed). The human-input pages and their 32 tests are unchanged | Types check exit 0. Contract tests: 9 passed. Client tests: `http.test.ts` 9, `dashboard.test.ts` 8, `client.phase8.test.ts` 6, `useResource` 5, `useOnDemand` 3. The 32 Phase 5 tests are byte-identical and pass | Shell and routes changed (D1.2); the Phase 5 client uses the shared core (D1.3) | **Accept** (local evidence) |
| **M2** event dashboard | Each section is fed by its route; `model_not_loaded` / `epa_source_*` show as unavailable with the reason; the ordering shows its model and switch point | `EventsPage` 5 and `EventPage` 5 tests. Live: 5 event pages OK; raw-EPA analysis before the switch point returns 200 | M5 v2 ordering and forecast never seen with a model (P7-Q5) | **Accept** (local evidence) |
| **M3** team profile | Absent values show their reasons; charts plot only served values, with axes, units and a text summary | `TeamPage` 5 tests. Live: team page OK; strength and metrics return 200 | — | **Accept** (local evidence) |
| **M4** match strategy | Both paths shown identically; `selection_note` shown; null odds with reasons; writes gated; `model_not_loaded` shown as unavailable | `MatchPage` 9, `StrategyLabPage` 3, `coachInputs` 7, `liveRegions` 2 tests. Live: match and lab pages OK, with strategy routes refused (`model_not_loaded`) and tokenless writes refused with 403 | **No AI strategy seen on real data. No successful live coach write** (P8-R7) | **Accept** (local evidence, with these limits) |
| **M5** alliance selection | The refusal-only state is clear and truthful; the success rendering is tested with a synthetic fixture; `validated_playoff_success` shown as served | `AlliancePage` 4 tests (the success fixture is **labelled synthetic**). Live: candidates and synergy return 200; the pick list returns 409 `not_approved` | The pick list is refusal-only (P6-DM1) | **Accept** (local evidence) |
| **M6** pre-match report | Every field traces to the response; every absent part shows its `absent_code`; nothing derived client-side; DM2 evaluated honestly | `ReportPage` 6 tests. Live: the report returns 200 and the page is OK | **DM2 NOT MET** (six items, P8-Q6) | **Accept the implementation**; DM2 stays unmet |
| **M7** cross-cutting quality | axe reports no violations in the tested views; the live smoke records each operation; every gap is recorded | axe runs in the page tests; the smoke shows ALL OK; R2's contrast computation plus the measured `--input-border` (3.48–5.03:1) | **Accessibility items left open (P8-R9). A4 print unverified (P8-R11)** | **Accept** (local evidence, with these limits) |
| **M8** docs and acceptance | `docs/phase8.md`, the frontend README, the audit, this proposal; DMs evaluated honestly; full suites run with baseline failures named; acceptance PENDING | This file; `docs/phase8.md`; `frontend/README.md`; section 4 below | — | Pending this approval |

---

## 3. Phase-level audit

| Check | Result |
|---|---|
| Frozen spec integrity | `git hash-object`: `docs/P8Milestones.md` is `3bef760f318c264bb38029dbf6a4471520564b1d` and `P8_M0_DECISIONS.md` is `507f01df912051face85ab4fd917b20cf316b386`. Both are unchanged since the freeze. Deviations are in `decisions/P8_D1_…` (revision 2), as a proposal |
| Phase 7 contract and tests | The lock is unchanged. No backend endpoint, model or API code changed; no backend-side file changed after the full suite ran. `tests/test_frontend_api_contract.py` is unchanged and passes |
| Phase 5 app | Page components and their 32 tests are byte-identical. Redirects are tested and checked in a real browser (D1.2). Phase 5 writes still have no client timeout (D1.3, fixed 2026-10-19) |
| Probabilities and labels | Strategy odds are display strings; M6/M7 is a percentage only when validated; the two models never share a field. `validated_playoff_success` and `validated_playoff` are never merged (tested) |
| Nulls | "—" with the reason (plain words, raw code kept in `title`/`data-reason`, stated once where shared). Never 0 |
| Fabrication | No sample data in shipped code; the synthetic fixtures are test-only and labelled |
| Secrets | A scan of all 102 changed or new files (2026-10-19, after the last edit) found no `.env` secret: `DATABASE_URL` and `TBA_API_KEY` matched 0 files, the database password matched 0 files, and `ENV` matched only as the word "development". No credential patterns were found. The bundle has no source maps. The write token is held in memory and sent only on the two coach writes (every read method is tested) |
| Write protection | The Phase 5 token is required. Writes are UI-gated, never time out or retry, cannot be submitted twice, and survive edits while in flight (tested) |
| Diff hygiene | `.oxlintrc.json` was reformatted back so its diff is only the 4-line override. The lockfile adds only `axe-core`. The run logs contain local absolute paths (P8-R12) |
| Unrelated work | The four Phase 7 run logs in `.agent/phase7/runs/` are untouched. Nothing was deleted, reset or staged |

---

## 4. Final verification (2026-10-19)

| Check | Command | Result |
|---|---|---|
| Frontend tests | `cd frontend && npx vitest run` | **exit 0: 24 files, 139 tests passed** (32 Phase 5 + 107 Phase 8). Baseline: 6 files, 32 tests (`runs/frontend_vitest.txt`) |
| Types | `npx tsc -b` | exit 0 (`runs/frontend_tsc.txt`) |
| Lint | `npx oxlint` | exit 0: **0 errors, 8 warnings, all in Phase 5 files** (`components/common.tsx` 2, `components/hooks.ts` 3, `state/session.tsx` 3), equal to the baseline (`runs/frontend_oxlint.txt`) |
| Build | `npm run build` | exit 0: JS 418.42 kB (gzip 120.72 kB), CSS 15.99 kB, 0 source maps (`runs/frontend_build.txt`) |
| API types current | `venv/bin/python -m scripts.phase8_generate_api_types --check` | exit 0 (`runs/types_check.txt`) |
| Contract tests | `venv/bin/python -m pytest tests/test_phase8_frontend_contract.py tests/test_frontend_api_contract.py -q -p no:cacheprovider` | exit 0, 9 passed (`runs/contract_tests.txt`) |
| Contract lock | `venv/bin/python -m scripts.phase7_contract_lock check` | exit 0: `changed: []`, `added: []` (`runs/contract_lock.txt`) |
| Live smoke | `venv/bin/python -m scripts.phase8_live_smoke --api http://127.0.0.1:8765 --season 2026 --app http://127.0.0.1:5173 --chrome <headless shell> --out .agent/phase8/runs/live_smoke.json` | exit 0, ALL OK: 24 API calls and 11 pages. The local API and dev server were stopped afterwards |
| **Full backend suite** | `DATABASE_URL=<…/stratai_test> venv/bin/python -m pytest tests -q -p no:cacheprovider` | **exit 1: 2,489 passed, 5 failed, 5 skipped, 1 xfailed** in 14 min 28 s (`runs/backend_final.txt`). **The suite does not pass.** The 5 failures are the same 5 known baseline tests, by name, as in `runs/backend_baseline.txt` (2,483 passed). The +6 are the new Phase 8 contract tests. 0 regressions. Not re-run after the frontend-only changes of 2026-10-19 (no backend-side file changed since; the contract tests were re-run) |

**The 5 known baseline failures:**
- `test_ml_features_score_breakdown.py::test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score`
- `test_phase5_contract.py::test_p5_d3_adoption_record_matches_the_served_status_and_its_evidence`
- `test_phase6_rulesets.py::test_m1_reproduction_path_runs_on_real_events_with_injected_rulesets`
- `test_phase6_rulesets.py::test_m1_counts_ruleset_exclusions_and_records_the_variant_applied`
- `test_phase6_rulesets.py::test_m8_future_playoff_sentinel_changes_no_selection_moment_input_and_is_removed`

---

## 5. Independent reviews

Four subagent reviews were actually performed, each with fresh context and read-only instructions. They are recorded
verbatim in `reviews/R1`–`R4`, and every finding's disposition (re-checked on 2026-10-19) is in
`reviews/REVIEW_DISPOSITION.md`.
- **R1, correctness:** 4 low findings, fixed.
- **R2, accessibility and UX:** 3 high, 8 medium and 7 low findings, mostly fixed; the remainder are in P8-R9.
- **R3, security, state and tests:** 9 findings plus test gaps. R3-6 is partial; the rest are fixed.
- **R4, fix verification:** found 6 new issues, including two mediums caused by my own fixes. All 6 are fixed, and
  the save/status bugs have regression tests proven against the planted bugs.

**No human review has taken place.**

---

## 6. Remaining risks (`RISK_REGISTER.md`)

- **P8-R1:** no real-model or environment-of-record verification.
- **P8-R2:** the six report items (P8-DM2 not met).
- **P8-R3:** alliance selection is refusal-only.
- **P8-R4:** sharing needs a deployment.
- **P8-R5:** slow routes.
- **P8-R6:** carried over from Phase 7.
- **P8-R7:** no successful live coach submission.
- **P8-R8:** the deviations are unratified.
- **P8-R9:** remaining accessibility items:
  - tabs activate automatically;
  - there is no sticky column;
  - three live regions still mount together with their content;
  - three buttons use `disabled` while busy;
  - chart ticks are about 7 px on phones.
- **P8-R10:** the smoke script's request bodies are a copy of the dashboard's.
- **P8-R11:** A4 printing is unverified.
- **P8-R12:** the run logs contain local paths.
- **P8-R13:** the Phase 5 Overview fallback link.

---

## 7. Proposed decision

> **PROPOSED for Sven Morais:** accept Phase 8 **conditionally**:
> 1. **Ratify** the P8-M0 working freeze and the deviations D1.1–D1.9, as amended or reverted by your rulings
>    (`decisions/P8_D1_…`, revision 2).
> 2. **Accept M1–M7** on their recorded local evidence, with the limits in section 2.
> 3. **Record P8-DM1 as met against the local API only.** It is not verified in production or the environment of
>    record; that remains deferred to P7-Q5.
> 4. **Record P8-DM2 as NOT MET** until P8-Q6 is decided and the six report items are actually served (or explicitly
>    waived in a dated record). The labelled absences are not to be represented as complete.
> 5. **Keep** P8-R1, R2, R7, R9 and R11 (with the rest of the register) as tracked follow-ups.
>
> **Approval: PENDING.** No commit, push or PR is authorized by this record, and Phase 9 is not started.
