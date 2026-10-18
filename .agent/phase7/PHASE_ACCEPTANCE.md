# Phase 7 — API Layer: Phase Acceptance record

phase completion status: **ACCEPTED CONDITIONALLY at phase level**, by Sven Morais on 2026-10-18 (`decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md`,
approval recorded verbatim). This is NOT full milestone completion:
- P7-M8 (real examples) remains BLOCKED (environment, P7-Q5) and is deferred.
- The environment-of-record suite portion of P7-M9 is deferred.
- P7-DM1 is not met.
- P7-DM2 has a contract-lock control, but routine automatic enforcement is not yet demonstrated.
- MASTER_BUILD's Phase Acceptance Gate is not satisfied on its own terms, because P7-M8 is not accepted. The phase is
  accepted by the human decision, with that item deferred, as Phase 6 was with P6-DM1.

Everything that can be built and verified on this machine is done and verified. Environment-dependent checks and the
Phase 6 dependencies remain open (risk register).

date: 2026-10-18
branch: phase7/m0-spec (base main 4290a3d). NOTHING COMMITTED: commits wait for Sven's explicit authorization.
spec: docs/P7Milestones.md (rev 2, frozen 2026-10-17); .agent/phase7/P7_M0_DECISIONS.md (approved by Sven Morais);
post-freeze decisions P7-D1 … P7-D7 (.agent/phase7/decisions/)

## Milestones

| Milestone | Status | Record |
|---|---|---|
| P7-M0 Specification freeze | FROZEN 2026-10-17 | P7_M0_FREEZE.md |
| P7-M1 API contract foundation | ACCEPTED 2026-10-17 (erratum 2026-10-18: vacuous route walks fixed, criteria re-verified) | M01_ACCEPTANCE.md |
| P7-M2 Team metrics and strength | ACCEPTED 2026-10-17 | M02_ACCEPTANCE.md |
| P7-M3 Win probability and rankings | ACCEPTED 2026-10-17; real-model check BLOCKED (environment) | M03_ACCEPTANCE.md |
| P7-M4 Event analysis and discovery | ACCEPTED 2026-10-18 | M04_ACCEPTANCE.md |
| P7-M5 Match strategy | ACCEPTED 2026-10-18; real P6-M10 artifact checks BLOCKED (environment) | M05_ACCEPTANCE.md |
| Mid-Phase Audit | Stable after fixes (P7-D4) | MID_PHASE_AUDIT.md |
| P7-M6 Alliance selection | ACCEPTED 2026-10-18; real output DEFERRED with P6-DM1 (P7-Q1); playoff label decided by P7-D7 (addendum) | M06_ACCEPTANCE.md |
| P7-M7 Pre-match report data | ACCEPTED 2026-10-18; real-model output BLOCKED (environment) | M07_ACCEPTANCE.md |
| P7-M8 Real request/response examples | **NOT ACCEPTED: BLOCKED (environment, P7-Q5)**. Tooling, contract test and runbook built and tested | M08_ACCEPTANCE.md |
| P7-M9 Docs, contract tests, sign-off | Scope verifiable here complete; environment-of-record suite DEFERRED (BLOCKED); phase accepted conditionally by Sven Morais, 2026-10-18 | M09_ACCEPTANCE.md, `decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md` |

## Done-means (evaluated honestly)

### P7-DM1: every core feature is callable via the API with documented examples. NOT MET.
**Callable: yes, for all seven core features.**

| Feature | Routes | Real output here | Examples |
|---|---|---|---|
| Match strategy | 6 assess/recommend/compare routes + 2 coach writes | BLOCKED (environment: no P6-M10 artifact). Playoff-context odds: **refusal only** (`playoff_model_unavailable`; real output deferred with P6-DM1) | none (BLOCKED) |
| Win probability | match and ad-hoc routes; also in the forecast and the pre-match report | BLOCKED (environment: no M6/M7 artifact) | none (BLOCKED) |
| Team metrics | metrics, strength | needs the environment of record for a real example | none (BLOCKED) |
| Rankings | event analysis `ordering` (canonical); deprecated ranking route | BLOCKED (environment: EPA source, M5 v2) | none (BLOCKED) |
| Alliance selection | candidates; pick list | candidates: BLOCKED (environment). Pick list: **callable, refusal only; real output deferred with P6-DM1** (`not_approved` today) | none (BLOCKED); synthetic success comes from its test |
| Event analysis | analysis, qualification forecast, discovery reads | BLOCKED (environment) for real output | none (BLOCKED) |
| Pre-match report data | pre-match report | model parts BLOCKED (environment); without models they are explicit absences | none (BLOCKED) |

The examples criterion fails today. `tests/test_phase7_examples.py::test_every_operation_in_scope_has_its_required_examples`
is a strict xfail and will fail once examples exist and the marker remains.

### P7-DM2: no endpoint shape changes after frontend work begins. MET AS A CHECKABLE CONTROL; not yet demonstrated.
**In place:**
- `docs/api_contract_lock.json` locks all 24 core operations: schemas, operationIds, declared codes, `deprecated`.
- `tests/test_phase7_contract.py` pins it, including a planted-change test.
- Every relock (P7-D2 … P7-D5) carries a dated decision.
- `python -m scripts.phase7_contract_lock check` exits 0.

**Limits:**
- Uncommitted.
- No CI runs it (out of Phase 7 scope, as the spec says).
- The human-input routes are governed by `frontend/src/api/types.ts`, not by this lock (P7-Q4; decided below).
- The open label decision (P7-D5) may still change one locked value, and must be settled before frontend work.
- The property can only be demonstrated once Phase 8 starts.

## Human decisions
- **Phase acceptance: APPROVED (conditional, phase-level).** `decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md`, by Sven Morais on 2026-10-18, recorded
  verbatim. P7-M8 and the environment-of-record portion of P7-M9 are deferred, and P7-DM1 is not met (the Phase 6
  precedent).
- **Playoff label: DECIDED.** `decisions/P7_D7_PLAYOFF_LABEL.md`, approved by Sven Morais on 2026-10-18. The
  canonical label is `validated_playoff_success` for the pick list's event-level values, and `validated_playoff`
  stays reserved for P6 single playoff-match probabilities after PX-2. Applied and relocked; both frozen specs are
  unchanged.

## Major architectural decisions
- **One contract layer** (`api/contract.py`): the error envelope, `error_responses` declarations, the shared
  probability objects (`CalibratedWinProbability` for M6/M7, `StrategyOdds` display strings for P6), and
  `Validation` labels inherited from engines, never upgraded.
- **Shape lock** with normalized OpenAPI and dated relocks (P7-A4, P7-Q4).
- **Point in time everywhere:** no future `as_of` on any route (P7-D1, P7-D4); every match description uses
  `min(as_of or now, scheduled_time)` (P7-D6).
- **Services, not routes, compose engines** (P7-A3): `ml/views/*`, `ml/strategy/service.py`,
  `ml/playoffs/service.py`, `api/win_probability.py`, `api/strategy_shapes.py`.
- **Real gates for alliance selection** (R4, P7-D5): approved ruleset → event rules → PX gate records → inputs, with
  the PX artifacts named in the records → engine → draft state.
- **Examples** carry environment fingerprints and are captured only in the environment of record (P7-Q5).

## Human-input routes: lock decision (carried risk from the Mid-Phase Audit)
The 22 `/human-inputs/…` operations stay out of `docs/api_contract_lock.json`. P7-Q4 already decided that their
shapes are locked by `frontend/src/api/types.ts`, the Phase 5 web app that consumes them, and that they get no
captured examples. Nothing new is decided here. They remain documented in docs/phase5.md.

## Major bugs found and resolved during Phase 7
- **M1:** under FastAPI 0.141, route-walk contract tests walked nothing and passed vacuously. Fixed with a walker
  proven complete against OpenAPI (erratum).
- **M4:** a look-ahead leak: playoff matches and alliances were listed before selection (P7-D2).
- **M5:**
  - back-dated coach observations could change past evaluations (P7-D3);
  - duplicate hypothetical teams gave a 500;
  - the EPA envelope was missing.
- **Mid-Phase Audit:** lock and tests assumed an empty `API_PREFIX`; future `as_of` was refused only on POST routes
  (P7-D4).
- **M6 (P7-D5):**
  - caller-triggerable KeyError 500s;
  - a single declined team crashed the engine with an AssertionError (a Phase 6 engine fix);
  - captains listed ahead of their turn silently skewed the pick list;
  - rank freshness was checked against planned times only;
  - PX artifacts were not tied to the evaluated ones.
- **M7:**
  - private route helpers were reused (P7-A3), now shared modules;
  - one part of a look-ahead test was inert.
- **Phase-Level Audit (P7-D6):**
  - scheduled-match routes used a future scheduled time as their moment;
  - the examples tooling broke under `API_PREFIX`;
  - leftover imports, a private cross-module import, stale docs and `.env.example`.

## Phase-Level Audit (2026-10-18)
Three independent reviewers ran, read-only, with no database access.

**(a) Whole-phase checklist:** 0 high, 2 medium, 7 low.
- M1 and M2 are fixed (P7-D6). L1, L2, L3, L6 and L7 are fixed.
- L4 (the pick list builds strength views it does not use) and L5 (the EPA-complete rule restated in the forecast;
  scope mapping and match-error messages repeated in three routes) are recorded as technical debt below.
- Clean:
  - lock integrity;
  - unique operationIds;
  - 500 declared everywhere;
  - no default 422 schema;
  - `parse_as_of` on every `as_of`;
  - the EPA envelope on every EPA-backed route;
  - no raw probability served;
  - the coach-observation landing filter;
  - the constant-time fail-closed token;
  - the pick-list check order and codes;
  - no ml → api imports;
  - frozen blobs intact.

**(b) Phase Acceptance Review, nine dimensions:** 9 findings (all medium or low). Phase 7 code: F9, a misleading
comment, corrected; the redundant pre-match row build is removed. The rest are outside Phase 7's code, or are
platform hardening the user excluded from this phase (no Phase 10 work). They are recorded as risks below, with
owners.
- Architecture, maintainability, extensibility, developer experience: sound.
- Security: sound in Phase 7's code. Gaps are F1, F3, F7.
- Reliability: no unhandled 500 path in Phase 7 routes. Gaps are F1, F4.
- Performance and scalability: weak (F2, F4, F6, F8).
- Production readiness: F5.

**(c) Docs completeness:** every gap found is fixed in docs/phase7.md. That covered:
- the pick-list error codes;
- the coach-write 201 bodies and the strategy and observation schemas;
- the assess response;
- the ranking, synergy and win-probability fields and their missing-data rules;
- strength's missing-data rules;
- a dependency table;
- stale statements.

Examples remain BLOCKED.

## Final test status
- **Command:** `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest tests -q --tb=line -p no:cacheprovider`,
  on Sven's machine against the isolated stratai_test copy (not the environment of record).
- **Result:** 5 failed, 2483 passed, 5 skipped, 1 xfailed (10:24); pytest exit 1 from the 5 baseline failures only.
  The raw log was kept locally in `.agent/phase7/runs/phase_final.txt`, which is excluded from the commit; the
  counts and failure names recorded here are the evidence.
- **The 5 failures:** the same 5 baseline tests, by name. All are environment-only or pre-existing:
  - `test_ml_features_score_breakdown::test_adapter_resolves_every_real_alliance_breakdown...`: the local DB has no
    2025 data;
  - `test_phase5_contract::test_p5_d3_adoption_record...`: the pre-existing P5 CRLF hash defect;
  - two `test_phase6_rulesets::test_m1_*`: no real playoff events in the local DB;
  - `test_phase6_rulesets::test_m8_future_playoff_sentinel...`: a Windows artifact path.
- **Regressions:** 0. Skips unchanged (5).
- **Re-run after P7-D7, the label change (latest):** identical counts, 2,483 passed, 5 failed, 5 skipped,
  1 xfailed; pytest exit 1; the same 5 baseline failures; 0 regressions. Contract and docs tests: 404 passed, 1
  skipped, 1 xfailed. The lock check exits 0.
- **The 1 xfail** is the strict BLOCKED completeness check for P7-M8.
- **Baseline at phase start (2026-10-17):** 2019 passed, 5 failed (the same 5), 5 skipped.
- `python -m scripts.phase7_contract_lock check`: exit 0, 24 operations.
- **Type check / lint:** not configured (P7-A9). They are reported as not configured, never as passing.
- **The full suite in the environment of record** (required by P7-M9): BLOCKED (environment, P7-Q5).

## Production readiness (Phase 7 as a whole)
- **Ready, on the evidence here:** the contract layer, the error envelope, point-in-time rules, refusals, the lock,
  and documentation, for the locked API surface.
- **NOT ready for production use as a whole.** No real-model output has been verified (P7-Q5). The pick list is
  refusal-only (P6-DM1). The platform hardening items below are open. No commit exists.

## Risk register (owners, impact, follow-up)

| # | Risk | Owner | Impact | Follow-up |
|---|---|---|---|---|
| R1 | Environment of record unavailable (P7-Q5): no model artifacts, serving DB through 0011, or production EPA config | Sven / Kanav (human input) | P7-M8 examples, the M3/M5/M7 real-model checks and the environment-of-record suite cannot run; P7-DM1 stays unmet | Provide the environment; run the capture runbook; remove the xfail; rerun the suite |
| R2 | CLOSED 2026-10-18 by P7-D7: the playoff label is `validated_playoff_success` (applied, relocked). Residual: `scripts/phase6_playoff_track.py:542` still passes `validated_playoff` to the engine for the P6-M8 run | P6 track owner | None for the API, which sets its own label; the P6 script's internal label disagrees with P6-M7 | Optionally align the script under the P6 process; it changes no written record |
| R3 | The PX gate records carry no artifact sha256s; the PX-2 calibrator lives only in the P6 rows cache | P6 track owner | Even if the PX gates pass, the pick list refuses (`playoff_models_not_accepted`) | Have the P6 records name the evaluated artifacts (a P6 change) |
| R4 | Alliance selection deferred with P6-DM1 (rulesets awaiting review) | Kanav / named FRC reviewer (P6-M1) | The pick list is refusal-only; no validated playoff output | Approve the P6-M1 rulesets; run the PX gates |
| R5 | Recommend latency grows about 0.025 s per coach observation at the event, unbounded; the pre-match report runs two recommends | Phase 7 / Sven (decision) | Past about 300 observations, recommend exceeds the 10 s budget | Decide whether to restrict observations to the six teams (P7-M5 note) |
| R6 | No request-body size limit (F3) | Phase 10 hardening | Large bodies are buffered and parsed before any check | Middleware cap (about 1 MB JSON; MAX_MANUAL_BYTES for uploads) |
| R7 | No DB connect/statement timeouts; an EPA-load failure is retried on every request under the lock (F4) | Phase 10 hardening | A slow DB can exhaust the worker pool, `/ready` included | Back-off cache for failures; `connect_timeout` and `statement_timeout` |
| R8 | Readiness ignores model and EPA state (F5) | Phase 10 hardening | A deploy with every model unloaded reports ready | Per-dependency entries in `/ready`; optional strict start |
| R9 | Per-team DB connections, no request-level snapshot, the forecast's per-match rebuilds; no pooling (F6, pre-existing) | Phase 10 hardening | High connection counts per request; possible mixed snapshots during a refresh | Request-scoped feature memo, one transaction per request, pooling |
| R10 | Unbounded live-EPA snapshot cache (F8) | Phase 10 hardening (P5 code) | Memory growth when callers walk historical `as_of` values | Small LRU |
| R11 | Game-manual download returns 500 for a non-latin-1 or quote-containing filename (F1); the upload handler blocks the event loop (F2); a storage_integrity message reveals a server path (F7) | Phase 5 human-inputs owner | That manual can never be downloaded; one slow upload stalls all requests; minor information disclosure | Sanitise filenames and use RFC 6266 `filename*`; threadpool the upload; drop the path from the message |
| R12 | One shared write token; caller-asserted identities; no rate limits (P7-Q10, documented) | Phase 10 hardening | Weak attribution for coach writes | Per-user auth when it is in scope |
| R13 | Phase 7 technical debt: an analyze_event features-only path for the pick list (L4); one helper for the EPA-complete rule, scope mapping and match-error messages (L5); eager EPA resolve in the pick list (F9) | Phase 7 follow-up | Extra work per request; rules restated in a few places | Refactor in a later change, behind the existing tests |
| R14 | Round 3 of the M6/M7 adversarial review did not run (org spend limit) | Process | Less independent review of those milestones; rounds 1–2 and the Phase-Level Audit did run | Optionally rerun it later |
| R15 | Write-once records (e.g. the P7-M5 latency record) need a committed tree | Sven (commit authorization) | Those records are not yet written | Write them after the commit |
| R16 | Pre-existing P5 hash portability defect (CRLF; test_phase5_contract) | Phase 5 owner | One permanent failure on non-Windows checkouts | Recompute the evidence sha256 over normalized bytes (outside Phase 7) |
| R17 | P7-DM2 is not enforced automatically: nothing committed, no CI | Sven (commit); CI outside Phase 7 | A shape change could slip in if the suite is not run | Commit; run the contract suite at every change; CI later |

## Readiness for the next phase
Phase 7 is accepted conditionally (2026-10-18). Phase 8 (frontend) should NOT start until:
1. The work is committed (with explicit authorization), so the lock is the baseline frontend types are built
   against.
2. There is an explicit instruction to begin Phase 8.

The label decision is done (P7-D7). The deferred items stay open in the risk register. Phase 8 has not been started,
and no frontend types are frozen.

No Phase 8, 9 or 10 work was done.
