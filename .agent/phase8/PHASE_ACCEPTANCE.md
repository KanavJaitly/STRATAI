# Phase 8 — Frontend / Dashboard: CONDITIONAL ACCEPTANCE record

**Status: CONDITIONALLY ACCEPTED, NOT FULLY COMPLETE.** The scope below is as directed in writing by Sven Morais on
2026-10-19, and the record was prepared by Claude Code on that date.
- **Sven's confirmation of this record:** **CONFIRMED by Sven Morais on 2026-10-19** (section 7). This is a conditional
  acceptance, not full Phase 8 completion; the MASTER_BUILD Phase Acceptance Gate remains unsatisfied on its own terms.
- **Not authorized by this record:** staging, committing, pushing, a PR, or starting Phase 9.
- **Not claimed:** full Phase 8 completion, real-model verification, a successful live coach submission, or a
  successful alliance-selection result.
- Branch `phase8/build` (base `7c678eb`). Nothing was staged or committed when this record was written. It was later
  committed and merged with authorization (section 8).

**Decision records:**
- `decisions/P8_D1_IMPLEMENTATION_DEVIATIONS_2026-10-18.md` (the proposal);
- `decisions/P8_D2_RULINGS_AND_DEVIATION_DISPOSITIONS_2026-10-19.md` (rulings and final dispositions; authoritative);
- `decisions/P8_Q6_REPORT_COMPLETENESS_BRIEF_2026-10-19.md` (the options);
- `decisions/P8_Q6_DECISION_2026-10-19.md` (the decision).

**History:** the earlier proposal is kept unchanged in `PHASE_ACCEPTANCE_PROPOSAL_2026-10-19.md`. A final independent
audit on 2026-10-19 (section 6) re-verified this record against the repository and corrected stale wording elsewhere.

---

## 1. Dispositions M0–M7

**Verification states:**
- "Local evidence" = implemented, tested with synthetic fixtures, and verified against the local API (`stratai_test`,
  reference EPA source).
- **Environment of record:** BLOCKED (P7-Q5) for every milestone.

| Milestone | Disposition | Evidence | Explicitly not established |
|---|---|---|---|
| **M0** spec and decisions | **Conditionally accepted** on local evidence (confirmed 2026-10-19). Frozen-spec baseline intact; D1.1–D1.9 ratified per Sven's direction, after the 2026-10-19 rulings and evidence | Blobs `3bef760f…` / `507f01df…` rechecked; P8-D2 §4 | — |
| **M1** foundation | **Conditionally accepted** on local evidence | Types current; contract 9 passed; client tests (`http` 9, `dashboard` 8, `client.phase8` 18 (every Phase 5 write named and tested), `useResource` 5, `useOnDemand` 3, `session.race` 1); redirects and links (`App` 10, `OverviewPage.unknownInput` 1); 32 Phase 5 tests unchanged | Environment of record |
| **M2** event dashboard | **Conditionally accepted** on local evidence | `EventsPage` 5, `EventPage` 5, `EventPage.history` 2; live event pages OK | No model-backed ranking or forecast seen (`model_not_loaded` only) |
| **M3** team profile | **Conditionally accepted** on local evidence | `TeamPage` 5; live team page OK; visible raw codes checked in a real browser | Environment of record |
| **M4** match strategy | **Conditionally accepted** on local evidence | `MatchPage` 9, `StrategyLabPage` 3, `coachInputs` 7, `liveRegions` 2; live pages OK; tokenless writes refused with 403 | **No AI strategy on real data. No successful live coach submission** |
| **M5** alliance selection | **Conditionally accepted** on local evidence | `AlliancePage` 4 (success rendering on a fixture **labelled synthetic**); live candidates and synergy return 200, the pick list 409 `not_approved` | **No successful alliance-selection result**: refusal-only (P6-DM1) |
| **M6** pre-match report | **Implementation (report UI) accepted.** **P8-DM2 is explicitly UNMET and DEFERRED** | `ReportPage` 6; live report returns 200 and the page is OK | **The report is not complete.** Six items are unsupported (section 2) |
| **M7** cross-cutting quality | **Conditionally accepted** on local checks | axe in the page tests; live smoke ALL OK; the measured `--input-border`; 6 of 6 stable full runs | **Accessibility items open (P8-R9). A4 print unverified (P8-R11)** |
| M8 docs and acceptance | This record, `docs/phase8.md`, `frontend/README.md` | Confirmed by Sven Morais, 2026-10-19 (section 7) | — |

**Overall: Phase 8 is CONDITIONALLY ACCEPTED, NOT FULLY COMPLETE.**

## 2. Done-means

| Done-means | Status | Basis |
|---|---|---|
| **P8-DM1** "every view runs off the real API endpoints" | **MET AGAINST THE LOCAL API ONLY**, not the environment of record or production | Contract tests: routes exist, every locked operation is called or listed in `NOT_CALLED`, only locked operations are called, query parameters match. The live smoke ran 24 API calls and 11 pages, ALL OK. Every model-backed part was seen **only as its declared refusal** |
| **P8-DM2** "the pre-match report is complete and shareable with an alliance partner as-is" | **NOT MET. DEFERRED** (P8-Q6: Option C now, then D) | Shareable locally (stable URL, copy link, print). **Not complete:** `strengths_and_weaknesses`, `defensive_threats`, `key_risks`, `predicted_flow`, `critical_matchups` and `key_success_factors` stay explicit "not produced by any engine" absences. Nothing is fabricated, and P7-Q12 stands. Staged order recorded; no implementation started |

## 3. Verification (2026-10-19, after the final change)

| Check | Command | Result |
|---|---|---|
| Focused tests: D1.2, D1.4, D1.6, D1.7 | `npx vitest run` on the four test files | All pass. **Each fails against the old behaviour** (verified by temporarily restoring it, then restoring the fix; files compared afterwards) |
| Frontend, full | `cd frontend && npx vitest run` | **Final audit (fresh): exit 0, 27 files, 157 passed** (32 Phase 5 + 125 Phase 8), 3 of 3 runs. Earlier: 145 passed, 6 of 6 runs after `maxWorkers: '50%'`, so 9 of 9 consecutive full runs have passed since that setting. Before it: 3 intermittent single-test failures in 18 runs (P8-R14) |
| Types | `npx tsc -b` | exit 0 |
| Lint | `npx oxlint` | exit 0: 0 errors, **8 warnings, the unchanged Phase 5 baseline** (`components/common.tsx` 2, `components/hooks.ts` 3, `state/session.tsx` 3) |
| Build | `npm run build` | exit 0: JS 418.88 kB (gzip 120.88 kB), CSS 16.07 kB, 0 source maps (final audit, fresh) |
| API types | `venv/bin/python -m scripts.phase8_generate_api_types --check` | exit 0 |
| API contract tests | `venv/bin/python -m pytest tests/test_phase8_frontend_contract.py tests/test_frontend_api_contract.py -q -p no:cacheprovider` | exit 0, 9 passed |
| Contract lock | `venv/bin/python -m scripts.phase7_contract_lock check` | exit 0: `changed: []`, `added: []` |
| Live smoke | `venv/bin/python -m scripts.phase8_live_smoke … --out .agent/phase8/runs/live_smoke.json` | **Final audit (fresh):** exit 0, ALL OK (24 API calls, 11 pages). Servers stopped and confirmed down afterwards |
| **Full backend suite** | `DATABASE_URL=<…/stratai_test> venv/bin/python -m pytest tests -q -p no:cacheprovider` | **Exit 1. The suite does not pass:** 2,489 passed, **5 failed** (the 5 known baseline failures, listed below), 5 skipped, 1 xfailed (`runs/backend_final.txt`, 2026-10-19). **Not re-run in this pass:** no backend source, contract, lock or backend test changed since that run (verified by file times and `git diff HEAD -- api ml data database`), and the contract tests were re-run |
| Frozen spec | `git hash-object docs/P8Milestones.md .agent/phase8/P8_M0_DECISIONS.md` | `3bef760f318c264bb38029dbf6a4471520564b1d`, `507f01df912051face85ab4fd917b20cf316b386`: unchanged |

**The 5 known baseline failures:**
- `test_ml_features_score_breakdown.py::test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score`
- `test_phase5_contract.py::test_p5_d3_adoption_record_matches_the_served_status_and_its_evidence`
- `test_phase6_rulesets.py::test_m1_reproduction_path_runs_on_real_events_with_injected_rulesets`
- `test_phase6_rulesets.py::test_m1_counts_ruleset_exclusions_and_records_the_variant_applied`
- `test_phase6_rulesets.py::test_m8_future_playoff_sentinel_changes_no_selection_moment_input_and_is_removed`

## 4. Audit points

- **Phase 7 contract:** the lock and tests are untouched. There is no backend source diff against `HEAD`.
- **Phase 5:**
  - The only source change is the D1.2 ruling in `OverviewPage.tsx`.
  - The Phase 5 test files are byte-identical; the new Phase 5-area tests are in new files.
  - Phase 5 writes have no client timeout.
- **Probabilities and labels:** served as is. `validated_playoff_success` and `validated_playoff` stay distinct.
- **Absences:** never shown as 0.
- **Secrets and artifacts:** see `COMMIT_CANDIDATE.md` and P8-R12. Originals that contain local paths are excluded from
  the commit candidate; sanitized derivatives are proposed instead (section 6.6).
- **Reviews:** four independent reviews (R1–R4) are recorded verbatim. Every disposition was re-checked twice
  (`reviews/REVIEW_DISPOSITION.md`). **No human code review has taken place.**

## 5. Remaining risks (`RISK_REGISTER.md`)

**Open:**
- **P8-R1:** no real-model / environment-of-record verification.
- **P8-R2:** the six report items (DM2 deferred).
- **P8-R3:** alliance selection is refusal-only.
- **P8-R4:** deployment is needed to share the report.
- **P8-R5:** slow routes.
- **P8-R6:** Phase 7 carry-overs.
- **P8-R10:** the smoke script's request bodies are a copy.
- **P8-R11:** A4 print; fixed and verified locally, with the model-populated sections still open (section 9).
- **P8-R14:** test reliability under load.
- **P8-R15:** duplicate loading and error components in the Phase 5 and dashboard areas (final audit).

**Resolved:**
- **P8-R8:** deviation ratification (P8-D2).
- **P8-R13:** the Overview fallback (D1.2 ruling).
- **P8-R12:** local paths in the evidence. Closed 2026-10-19 after the merge (section 8).
- **P8-R7:** live coach submission. Closed 2026-10-19 (section 9).
- **P8-R9:** accessibility items. Closed 2026-10-19 (section 9).

---

## 6. Final independent audit (2026-10-19)

**Scope:** a fresh audit of the repository against this record, under Sven Morais's instruction of 2026-10-19 to
prepare Phase 8 for his final confirmation. No Git write operation was run.

### 6.1 Repository state, verified with read-only commands

| Item | State |
|---|---|
| Branch and HEAD | `phase8/build` at `7c678ebcb3e3570bbd945602f20ba785c125a124`, matching the prior report. The remote is `origin` (GitHub `KanavJaitly/STRATAI`); the branch has no upstream |
| Staged | 0 |
| Working tree before the audit | 15 modified tracked files and 95 untracked, 110 in total. This matched `COMMIT_CANDIDATE.md` exactly (103 included + 7 excluded) |
| Changes since the previous report | None. No file was newer than the manifest |
| Phase 7 run logs | The four files in `.agent/phase7/runs/` are untouched (sizes and mtimes of 2026-10-18 unchanged) |
| Working tree after the audit | 0 staged, 15 modified tracked files, and 100 untracked (the earlier 95 plus 5 sanitized derivatives). `COMMIT_CANDIDATE.md` was regenerated: 115 files = 106 INCLUDE + 9 EXCLUDE, reconciled exactly with git. No INCLUDE file contains a secret, username, home path or build artifact |
| Remote | There is no `origin/phase8/build`; the branch has never been pushed |

### 6.2 The MASTER_BUILD Phase Acceptance Gate, on its own terms (`prompts/MASTER_BUILD.md`)

**NOT SATISFIED on its own terms.** Phase 8 is conditionally accepted by the human decision, as Phases 6 and 7 were.
The unmet conditions:
- **"The full phase-relevant test suite passes"** is not met. The backend suite exits 1, with the 5 known baseline
  failures, all outside Phase 8. The frontend passes.
- **"No meaningful unresolved defect remains"** is not met. P8-DM2 is unmet (deferred), and P8-R9 and P8-R14 are
  open.
- **"Production readiness … confirmed"** is not met. There is no environment of record (P8-R1) and no deployment
  (P8-R4).
- **Protocol gap:** no `MID_PHASE_AUDIT.md` was written during Phase 8. The independent reviews R1–R3 (with fixes)
  and R4 (fix verification) came late in the phase instead. This cannot honestly be backfilled; it is recorded
  here.

### 6.3 Phase-Level Audit checklist (MASTER_BUILD), applied in this audit

| Item | Result |
|---|---|
| Regressions | Frontend 157 passed (3 of 3 runs). The 32 Phase 5 tests are byte-identical and pass. The backend has 0 new failures against the baseline |
| Architectural drift / coupling | No imports in either direction between `src/dashboard` and the Phase 5 `src/pages`. One fetch core (`http.ts`) is shared deliberately |
| Duplicated logic | **Found (deliberate):** two loading hooks (Phase 5 `useLoad`, Phase 8 `useResource`) and two error notices (`ErrorNotice`, `RefusalNotice`). They were kept because Phase 5 is not refactored in Phase 8. Recorded as P8-R15 |
| Stale documentation | Corrected (6.5) |
| Hidden assumptions | Phase 5 writes were assumed covered by one test. Now every write is named and tested (6.4) |
| Missing tests | Added (6.4). No `.skip`/`.only` and no lint or TypeScript suppressions, apart from the generated file's header |
| Race conditions | The write-access race, the print race and the in-flight save are fixed and proven (P8-D2) |
| Data quality / statistical validity | No client-side computation of probabilities. Labels are served verbatim (R1, R4) |
| Performance | Bundle 418.88 kB JS (gzip 120.88 kB). Slow backend routes are tracked (P8-R5) |
| Interface stability | Contract lock unchanged; generated types current |
| Technical debt | P8-R15; the remaining accessibility items (P8-R9) |
| Security | No `dangerouslySetInnerHTML`, `eval`, console output or secrets. The token stays in memory, and only writes send it (tested) |

**Phase Acceptance Review, nine dimensions:**

| Dimension | Status |
|---|---|
| Architecture | Examined above |
| Maintainability | P8-R15 |
| Scalability | Single event-scale views; not load-tested beyond the local smoke |
| Extensibility | Endpoint registry and generated types |
| Performance | P8-R5 |
| Reliability | P8-R14; write safety improved (6.4) |
| Developer experience | `docs/phase8.md`, recovery commands |
| Security | As above |
| Production readiness | **Not confirmed** (P8-R1, P8-R4) |

### 6.4 Code and test changes made in this audit

- **Phase 5 write safety, evidence gap closed:**
  - `client.phase8.test.ts` now names every Phase 5 write (`uploadManual`, `saveSpec`, `submitSpec`, `reviewSpec`,
    `createProfile`, `editProfile`, `duplicateProfile`, `archiveProfile`, `submitArtifact`, `establishArtifact`).
  - A test asserts the list equals `ENDPOINTS`' non-GET operations, and that each write waits 10 minutes without a
    client timeout, is sent once and is not retried.
  - These tests failed (10 of 18) when the write rule was temporarily removed.
- **Ambiguous outcome:**
  - `http.ts` now adds "The request may still have been stored: check before submitting it again." to a
    `network_error` on any non-GET request. It covers the Phase 5 pages, which show the message through their
    unchanged `ErrorNotice`, and the dashboard.
  - Reads are unchanged.
  - The test failed when the sentence was removed.
  - This is a message change only. The Phase 5 tests are unchanged and pass.

### 6.5 Records corrected in this audit

Each correction is dated in place, and the history is kept:
- **`PHASE_STATUS.md`:** the spec, decision and review lines still said "not human-approved", "Q6 needs a human" and
  "PROPOSED ratification, pending", although P8-D2 and the P8-Q6 decision exist.
- **M01–M07:** the `date:` lines said "human acceptance PENDING", which contradicted their conditional status.
- **M07:** "Not done" listed 3 accessibility items; the risk register lists 5, plus A4.
- **M00:** a dated addendum points to P8-D2 and P8-Q6.
- **`docs/phase8.md`:** the spec line said ratification was pending.
- **`frontend/README.md`:** the Phase 5 page table now shows the `/inputs/*` paths.

### 6.6 Privacy

**Originals with local paths** are kept unchanged as local evidence and are **excluded** from the commit candidate:
- reviews R2 and R4 contain scratchpad paths that include the username;
- the run logs `backend_baseline`, `backend_final` and `frontend_vitest` contain repository paths under the home
  directory.

**Sanitized derivatives** are in `reviews/sanitized/` and `runs/sanitized/`. Each one:
- names its original by git blob;
- differs only in the replaced path prefixes (verified with `diff`);
- contains no username and no home path.

**Secrets:** no `.env` secret value, database password or credential pattern appears in any candidate file.

---

## 7. Confirmation of conditional acceptance (Sven Morais, 2026-10-19)

**Quoted from Sven Morais's written instruction in the session:**
> I confirm Phase 8 conditional acceptance, with the limitations and open risks recorded in
> ".agent/phase8/PHASE_ACCEPTANCE.md". This is conditional acceptance, not full Phase 8 completion. The MASTER_BUILD
> Phase Acceptance Gate remains unsatisfied on its own terms. Preserve that fact in the acceptance record.

**Rulings preserved as confirmed:**

| Item | Confirmed status |
|---|---|
| M0–M5 | Conditionally accepted on local evidence only |
| M6 | Report UI accepted; **P8-DM2 unmet and deferred** |
| M7 | Conditionally accepted on local checks; the accessibility (P8-R9) and A4-print (P8-R11) risks stay open |
| P8-DM1 | Met against the local API only, not the environment of record |
| P8-DM2 | Unmet and deferred: Option C now, then Option D |
| Overall | **Phase 8 is conditionally accepted, not fully complete** |
| MASTER_BUILD Phase Acceptance Gate | **Not satisfied on its own terms** (§6.2). The missing mid-phase audit stays recorded as missing and is not backfilled |
| Backend suite | Exit 1: 2,489 passed, 5 known baseline failures, 5 skipped, 1 xfailed. It does not pass |

**Not claimed:**
- real-model or environment-of-record verification;
- a successful live coach submission;
- a successful alliance-selection result;
- production readiness.

**Outstanding risks:** every outstanding risk stays open as documented in `RISK_REGISTER.md`.

**Frozen specification:** unchanged. The blobs `3bef760f318c264bb38029dbf6a4471520564b1d` and
`507f01df912051face85ab4fd917b20cf316b386` were verified again at confirmation.

**Git authorization in the same instruction:** staging the reviewed candidate (`COMMIT_CANDIDATE.md`, INCLUDE list
only) is authorized. **Committing, amending, pushing, creating a remote branch, opening or merging a PR, and starting
Phase 9 are NOT authorized** and need separate, explicit authorization.

---

## 8. Post-merge record (2026-10-19)

**What happened, verified with Git:**
- With Sven Morais's authorization, the 106-file candidate was committed as
  `a5bc422c28b6126b8d8586965ea3424b79e062e3` ("phase8: conditionally accept dashboard implementation"; parent
  `7c678eb`).
- It was pushed to `origin/phase8/build` and merged into `main` via PR #33 (merge commit
  `12a29540ae6c0f82bcfe6bd76b4e90cb075b0e45`). The merge tree is identical to `a5bc422`.

**Status unchanged by the merge:** everything in sections 1–7 stands.
- Phase 8 is conditionally accepted, not fully complete, and the MASTER_BUILD gate is not satisfied on its own terms.
- P8-DM2 is deferred, and its six fields stay explicit absences.
- There is no real-model or environment-of-record verification, no successful live coach submission and no
  successful alliance-selection result.
- The backend suite result is still exit 1, with the 5 known baseline failures.
- All risks other than R8, R12 and R13 stay open.

**P8-R12 closed.** Evidence checked against `origin/main`:
1. none of the five originals containing local paths is in the merged tree or in any commit since `7c678eb`;
2. all five sanitized copies are in `main` and labelled;
3. each original is intact locally: its blob hash equals the hash recorded in its sanitized copy;
4. the merged Phase 8 content contains no username, home-directory path or temporary local path.

---

## 9. Closeout work (2026-10-19, uncommitted)

Done under Sven Morais's closeout instruction. Evidence is in `runs/closeout_2026-10-19.md`; the raw files are kept
locally, outside the repository.

**What changed:**

| Item | Outcome |
|---|---|
| **R11** A4 print | **Fixed and verified** for all locally servable content: pagination fixed (16 → 10 pages), every page inspected. **The model-populated sections stay unverified (OPEN, depends on R1)** |
| **R7** live coach write | **Verified and CLOSED.** On a new, empty, migrated database with synthetic data: 201/201 with exactly 2 rows persisted and matching what was sent; 403 with no token, a wrong token, and a wrong token afterwards; serving and the test database untouched; the database dropped |
| **R9** accessibility | **Fixed, verified and CLOSED** (all five items), with tests proven against the old code and checks in real Chromium |
| **P8-DM2** `predicted_flow` | **A decision was prepared, not implemented:** `decisions/P8_D3_PREDICTED_FLOW_PROPOSED_2026-10-19.md` (PROPOSED). Serving it changes the locked entry `not_produced.predicted_flow`, which needs Sven's approval (P7-DM2, P7-Q12). **P8-DM2 stays NOT MET and deferred** |

**Checks after the changes:**
- frontend: 165 passed, 3 of 3 runs; type check, lint (8 baseline warnings) and build pass;
- contract and docs tests: 74 passed;
- generated types current; contract lock unchanged; live smoke ALL OK;
- the frozen spec hashes are unchanged.

The backend suite was not re-run, because only frontend files changed. Its result stays **exit 1** (2,489 passed, 5
known baseline failures, 5 skipped, 1 xfailed).

**Status unchanged:**
- Phase 8 is **conditionally accepted, not fully complete**, and the MASTER_BUILD gate is not satisfied on its own
  terms.
- There is no environment-of-record or real-model verification.
- Alliance selection is refusal-only.
