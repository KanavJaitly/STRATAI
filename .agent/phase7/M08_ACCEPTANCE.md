# P7-M8 — Real request/response examples: acceptance record

status: BLOCKED (environment, P7-Q5). The capture tooling, its contract test and the runbook are built and tested;
no real example exists. NOT accepted: the spec's acceptance needs real captures from the environment of record.
spec: docs/P7Milestones.md P7-M8 (frozen); P7-Q1, P7-Q4, P7-Q5, P7-A9
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new:
  - scripts/phase7_capture_examples.py: the capture script;
  - scripts/phase7_examples_plan.template.json: 43 planned captures covering all 22 in-scope operations, with
    `<<KEY>>` placeholders;
  - tests/test_phase7_examples.py: 13 tests, one of them the strict xfail below.
- modified:
  - api/examples.py: examples_scope, PROBES, REFUSAL_ONLY, iter_api_routes, validate_example, missing_examples;
  - api/contract.py: DECLARED_CODE_PATTERN, moved from scripts/phase7_contract_lock.py, which still exports
    CODE_PATTERN;
  - tests/phase7_support.py: api_routes now delegates to api.examples.iter_api_routes, with the same behaviour;
  - tests/test_phase7_alliance_selection_api.py: the synthetic success test writes the pick list's synthetic
    example when `STRATAI_SYNTHETIC_EXAMPLES_DIR` is set;
  - docs/phase7.md: the "Examples (P7-Q4)" scope, rules and capture runbook.

## Scope delivered (tooling only)
- **The capture script** runs every planned request in-process at a fixed `as_of`.
  - It refuses outside the environment of record, which needs the three pinned models, an EPA source and
    migrations through 0011.
  - It writes nothing unless every response has its planned status and matches its locked contract.
  - Each file records the environment fingerprint: the models' identities and sha256s, the EPA source and its
    provenance, the database name, latest migration and row counts, the git commit with a dirty flag, `as_of`, and
    the capture time.
  - Write-token headers are sent, never recorded.
  - A dry run (`--allow-incomplete-environment`) can never write into docs/api_examples, and its examples can never
    pass the contract test.
- **Synthetic success:** the refusal-only pick list's synthetic success is written by its own test, labelled
  synthetic (P7-Q1).

## Acceptance criteria (spec)
- "A contract test checks that every endpoint in scope has its required examples": the test is BUILT.
  `test_every_operation_in_scope_has_its_required_examples` is a strict xfail with the reason "BLOCKED (environment,
  P7-Q5)". With zero examples it xfails today, and it turns into a failure once the examples exist while the marker
  remains. The completeness rules have their own passing test.
- "... and that every captured response validates against the endpoint's locked schema": BUILT and has teeth. It
  checks:
  - a declared status;
  - the response model (2xx) or the envelope with a declared code (errors);
  - for a `real` example, that it comes from the environment of record.

  6 planted-bad examples are rejected. Today it runs over the 0 committed examples, and over a dry-run capture.
- "Each example records its environment and is reproducible from it": the fingerprint is BUILT and tested by a dry
  run against the isolated test DB. Reproduction needs the environment of record: BLOCKED.
- Real captures for the 22 operations: BLOCKED (environment). Sven's machine has no ml_registry/, no ML pins, an
  older DB (migrations to 0009, no 2025 data) and no production EPA configuration.

## Terminal verification
- tests/test_phase7_examples.py: 12 passed, 1 xfailed (strict, the BLOCKED completeness check).
- Contract and docs suites (test_phase7_contract, test_phase7_examples, test_api_contract, test_api_foundation,
  test_metrics_docs_contract, test_phase6_contract): 323 passed, 1 skipped, 1 xfailed.
- `python -m scripts.phase7_contract_lock check` exits 0.
- The full suite is recorded in PHASE_ACCEPTANCE.md (the Phase-Level Audit run).

## What unblocks it (human input, P7-Q5)
Provide the environment of record:
- the registry folders `ranking_xgb_v2/d18`, `win_prob_xgb_calibrated/d18` and `strategy_outcome_component/p6m10-v1`;
- a serving-database dump with migrations through 0011;
- the production EPA source configuration.

Then follow the runbook in docs/phase7.md "Examples (P7-Q4)", and remove the xfail marker.

## Decision
NOT ACCEPTED: BLOCKED (environment). The tooling is complete and tested; no real example is claimed.
