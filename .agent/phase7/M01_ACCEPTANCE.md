# P7-M1 — API contract foundation: acceptance record

status: ACCEPTED (2026-10-17)
spec: docs/P7Milestones.md P7-M1 (frozen 2026-10-17)
base: main 4290a3d, branch phase7/m0-spec, uncommitted (commits wait for Sven's authorization)

## Files
- new: api/contract.py, api/examples.py, scripts/phase7_contract_lock.py, docs/api_contract_lock.json, docs/phase7.md,
  tests/test_api_contract.py, tests/test_phase7_contract.py, tests/phase7_support.py
- modified: api/app.py, api/routes/{predictions,metrics,strength,event_analysis,qualification_forecast,health,human_inputs}.py,
  tests/test_phase6_contract.py, tests/test_metrics_docs_contract.py, tests/test_api_foundation.py, docs/ml_models.md

## Scope delivered (P7-M1 a-g)
- (a) api.contract: Validation; CalibratedWinProbability (M12 split; values only on the M6/M7 0.05 grid in [0.05, 0.95];
  reason in {playoff_scope, unspecified_context, epa_incomplete}; calibration_status m7_gate_failed); StrategyOdds
  (P6-A5 display strings only, a null display needs a reason); ServedModelInfo moved from predictions (same schema
  and component name; still importable from api.routes.predictions); M6/M7 label constants defined once and
  re-exported by predictions.
- (b) api.examples: docs/api_examples/*.json attached to OpenAPI. Files are parsed at app build (a malformed file
  stops startup); a failed attachment is never cached. None exist yet (P7-M8).
- (c) shape lock: scripts/phase7_contract_lock.py with check/lock/relock/unlock, and docs/api_contract_lock.json.
  Locked so far: GET /health, GET /ready, the error envelope schemas, and the building blocks. It locks operationId,
  parameters, bodies, statuses (including empty bodies), error codes, deprecated and schema constraints; it ignores
  documentation keywords only (property names kept) and compares required/enum/anyOf as sets. Changes to locked
  entries need a decision naming a decision document and a date; every revision lists its changed entries.
- (d) docs/phase7.md; tests/test_phase7_contract.py (freeze blobs, lock, error contract, INTERIM rule, P7-Q6, docs,
  Phase 7 owned-endpoint pin).
- (e) contract-test coupling, each dated in docs/phase7.md "Contract-test changes":
  - test_phase6_contract no-routes test replaced by a per-module path-family allow-list (no mounts).
  - test_metrics_docs_contract excludes paths from phase7.md's owned list, which is pinned (live, Phase 7 modules,
    not pre-Phase 7).
  - test_api_foundation pin split into PRE_PHASE7_PATHS (unchanged) and PHASE7_PATHS (empty after M1).
- (f) every route declares its error statuses and codes through the one envelope. 500 is declared everywhere; 422
  validation_error is declared exactly where validation can fail; the human-input codes were derived from data.human_inputs
  transitively; POST /human-inputs/game-manuals now declares its existing 200 (re-upload).
- (g) unversioned paths; /docs and /openapi.json on (tested).

## Behaviour
- No served response body or status changed: only OpenAPI declarations, a moved model class (same schema), and
  constants now defined in api.contract (same values). Confirmed by the independent review and the unchanged
  API tests (tests/test_api_predictions.py and the human-input API tests pass).

## Acceptance criteria (spec)
- shape-lock test passes on the current routes: PASS (test_the_live_application_matches_the_contract_lock; `lock check` exit 0)
- shape-lock fails on a planted shape change, shown in a test: PASS (test_the_lock_detects_a_planted_shape_change;
  plus unit tests for removed fields, empty bodies, CLI refusals)
- every existing route declares its error responses: PASS (test_every_operation_declares_500_and_only_envelope_errors,
  test_validation_error_is_declared_exactly_where_it_can_happen, test_every_declared_error_code_is_raised_by_the_routes_own_code)
- each contract-test change recorded with date and reason: PASS (docs/phase7.md "Contract-test changes": 4 rows)

## Terminal verification
- full suite, final run: `DATABASE_URL=<serving URL with /stratai_test> venv/bin/python -m pytest -q --tb=line -p no:cacheprovider`
  - result: 5 failed, 2230 passed, 5 skipped (5:43). pytest exits 1 (failures present); the background job's
    reported exit 0 was `tail`'s, not pytest's.
  - failures vs baseline (2026-10-17, 2019 passed / 5 failed / 5 skipped): the same 5 tests by name. 0 new failures,
    0 newly passing, skips unchanged at 5.
    - test_ml_features_score_breakdown::test_adapter_resolves_every_real_alliance_breakdown... (environment: no 2025 data)
    - test_phase5_contract::test_p5_d3_adoption_record_matches... (pre-existing P5 CRLF-hash portability defect)
    - test_phase6_rulesets::test_m1_reproduction_path... / test_m1_counts_ruleset_exclusions... (environment: no real playoff events)
    - test_phase6_rulesets::test_m8_future_playoff_sentinel... (environment: Windows artifact path)
  - +211 tests vs baseline: test_api_contract, test_phase7_contract, and the new allow-list test.
- M1 gate tests run directly (no pipe): tests/test_phase7_contract.py, test_api_contract.py, test_phase6_contract.py,
  test_metrics_docs_contract.py, test_api_foundation.py, test_ml_models_docs_contract.py, test_frontend_api_contract.py
  -> 320 passed, 1 skipped (p6_m10 registry artifact absent on this machine), pytest exit 0.
- `python -m scripts.phase7_contract_lock check` -> exit 0.
- type check: not configured (P7-A9). lint: not configured (P7-A9).

## Phase E/F: architecture review and bug hunt (independent review)
12 findings, all resolved and covered by tests:
1. A failed example attachment was cached -> attach on a copy; nothing cached on failure; files parsed at build.
2. The lock dropped properties named title/description/summary/example(s) -> only schema keywords are dropped.
3. Empty response bodies were invisible -> empty-object leaves; filling one in is an addition.
4. The allow-list ignored path families and mounts -> per-module path regex; mounts refused.
5. The Phase 7 owned-path exclusion could be gamed -> pinned (live, Phase 7 module, not pre-Phase 7, complete).
6. The declared-code check was global -> per-route scope (own module + imported modules); behavioural helper
   tests/phase7_support.assert_declared_error for the families.
7. CalibratedWinProbability accepted off-grid values -> grid, reason and rounding invariants.
8. 422 validation_error declared where impossible -> declared exactly where validation can fail.
9. CLI gaps -> unlock, decision format, changed-entry lists, refusal on missing/mistyped ops, lock cannot absorb
   unrelated changes, sorted unordered lists, operationId locked.
10. Route codes at >= 500 -> refused by error_responses.
11. Duplicated label constants -> defined once in api.contract.
12. Undeclared 200 on game-manual upload -> declared.
Also found during implementation: docs/ml_models.md did not document epa_source_pending (fixed, test-held).

## Remaining known risks
- Real-model checks are not part of M1. The model-backed routes are locked from P7-M2/M3 on; real-model
  verification is BLOCKED (environment) until P7-Q5.
- The lock compares lists whole except required/enum/anyOf/oneOf/allOf/type (sorted). Other list changes are reported
  as changes (conservative).

## Roadmap satisfaction / production readiness
- P7-M1 scope (a)-(g) delivered. Contracts and checks are in place for M2-M8 to extend.
- Production readiness: no served behaviour change; additive tooling and documentation.

## Erratum (2026-10-18, found during P7-M4)
Two tests this record cites as passing evidence walked `app.routes` for `APIRoute`. The installed FastAPI (0.141.1;
requirements.txt allows <1.0) wraps each included router as one `_IncludedRouter` entry, so both loops found no
route and **passed without checking anything**:
- `tests/test_phase6_contract.py::test_phase6_capability_routes_live_only_in_the_phase7_modules` (the P7-A5 allow-list);
- `tests/test_phase7_contract.py::test_every_declared_error_code_is_raised_by_the_routes_own_code`.

Correction: a shared walker (`tests/phase7_support.api_routes_checked`) flattens the wrappers and asserts the
walk covers exactly the OpenAPI operations, so it can never be empty again. Both tests use it. Each gained a
non-vacuity check: a planted stray strategy route is caught, and more than 50 declared codes must be checked. Re-run
2026-10-18: both pass with real checks, so the criteria stand. They are now verified, not assumed. The independent
review's manual trace of every route's codes had reached the same conclusion. No other test in the repository walks
`app.routes` this way (`test_ml_models_docs_contract` reads the predictions router directly and is not vacuous).

## Decision
ACCEPTED. Every P7-M1 acceptance criterion passed with evidence above. 0 regressions against the baseline. Next:
P7-M2 (team metrics and strength).
