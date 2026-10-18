# P7-M3 — Win probability and rankings: acceptance record

status: ACCEPTED (2026-10-17)
spec: docs/P7Milestones.md P7-M3 (a)-(e) (frozen); P7-Q2, P7-Q3, P7-Q7, R7; post-freeze P7-D1
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new: ml/calibration/display.py (the M6/M7 display rule, moved; behaviour identical),
  .agent/phase7/decisions/P7_D1_NO_FUTURE_AS_OF.md, tests/test_phase7_predictions_regression.py,
  tests/fixtures/p7_m3_predictions_golden.json, tests/test_phase7_predictions_api.py
- modified: api/contract.py (calibrated_win_probability; constants from ml.calibration.display),
  api/routes/predictions.py (re-exports display_probability; win_probability field; as_of on both POST routes;
  ranking route deprecated), api/routes/qualification_forecast.py (per-match win_probability),
  api/routes/common.py (parse_as_of and CODE_INVALID_AS_OF moved here, with allow_future),
  api/routes/strength.py / event_analysis.py (import from common; strength still re-exports),
  tests/test_qualification_forecast_api.py (stub identity()), docs/ml_models.md §9, docs/phase7.md,
  docs/api_contract_lock.json (+4 operations, 8 total)

## Scope delivered
- (a) The shared M6/M7 probability object, additive on every win-probability response and every forecast match.
  It holds the same value and decision as the legacy fields, and validation.reasons always carries m7_gate_failed.
- (b) Optional as_of on POST /predictions/win-probability and POST /predictions/alliance-synergy. It may not be in
  the future (P7-D1; refused beyond a 5-minute skew).
- (c) The display rule moved to ml/calibration/display.py, still importable from api.routes.predictions (scripts
  and tests unchanged).
- (d) Gating unchanged: validated only for EPA-complete qualification; playoff_scope / unspecified_context /
  epa_incomplete otherwise; m7_gate_failed; 0.05 rounding; [0.05, 0.95] clip.
- (e) The event-analysis ordering is the canonical rankings surface. GET /predictions/events/{event_key}/ranking is
  deprecated in OpenAPI (deprecated: true, with the P7-Q2 reason), its behaviour and label are unchanged, and it
  has no as_of. Its consumers (the verify scripts) keep working.

## Acceptance criteria (spec)
- Every served value is identical to the pre-Phase 7 routes for the same inputs, with a frozen clock: PASS.
  - Golden captured from the unmodified routes (9 success responses covering every gating branch, ranking,
    synergy and forecast); after M3 every old key keeps its value (additive only).
  - The golden's synthetic models output a constant 0.5, so it was strengthened:
    - the moved display rule equals a frozen copy of the original on 100,001 grid points;
    - a feature-dependent, red/blue-asymmetric model stub shows the routes serve exactly
      display_probability(f(features)), including both clips (0.05 and 0.95) and the complement on swap;
    - an explicit as_of equal to now gives the same response as omitting it.
- model_not_loaded and epa_source_* refusals tested: PASS (on each route, through assert_declared_error).
- No new label claims more validation than the Phase 4/5 records: PASS (the object repeats the legacy decision;
  m7_gate_failed is a qualifier, never an upgrade).
- Four operations locked: PASS (lock check exit 0).
- Real D18 model checks: BLOCKED (environment) -- registry not on this machine (P7-Q5). Fixture models do not
  stand in for them.

## Terminal verification
- Final full suite: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest -q --tb=line -p no:cacheprovider`
  -> 5 failed, 2284 passed, 5 skipped (5:57); pytest exit 1 from the 5 baseline failures only. Same 5 tests as the
  baseline by name; 0 regressions; skips unchanged.
- An earlier run (after implementation, before the review fixes): 5 failed (the same 5), 2279 passed, 5 skipped.
- `python -m scripts.phase7_contract_lock check` -> exit 0.
- type check / lint: not configured.

## Phase F (independent review): 6 findings
1. Medium: a future as_of could make an in-progress event count as prior and mislabel a value as validated.
   Fixed: P7-D1, refused beyond the skew. Tested.
2. Low-medium: the golden was near-vacuous for probabilities (constant 0.5). Fixed: the three strengthening tests
   above.
3. Low: ml.calibration.display pulls in sklearn through the package __init__. Considered and not changed: the ml
   package root (ml/__init__.py) already imports the backtest harness and feature pipeline eagerly by Phase 4
   design, and the API loads it at startup anyway, so moving the module would gain nothing.
4. Low: route-to-route import of parse_as_of. Fixed: moved to api.routes.common (still re-exported by strength).
5. Low: an unencoded '+' offset fails. Documented (%2B or Z), and the error message now says so.
6. Low: stale docs status. Fixed at acceptance.

## Remaining known risks
- A future as_of on the Phase 5 strength and event-analysis views may have the same exposure; recorded for the
  Phase-Level Audit and not changed (Phase 5 behaviour is out of P7-M3 scope).
- Real-model verification: BLOCKED (environment) until P7-Q5.

## Decision
ACCEPTED. All P7-M3 criteria that can run here passed with the evidence above. The real-model check is recorded
as BLOCKED (environment), not passed. 0 regressions. Next: P7-M4 (event analysis and discovery).
