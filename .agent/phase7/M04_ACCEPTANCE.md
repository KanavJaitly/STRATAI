# P7-M4 — Event analysis and discovery: acceptance record

status: ACCEPTED (2026-10-18)
spec: docs/P7Milestones.md P7-M4 (a)-(c) (frozen); P7-Q2, P7-Q8, R8; post-freeze P7-D2
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new: ml/views/discovery.py, api/routes/discovery.py, tests/test_phase7_event_regression.py,
  tests/fixtures/p7_m4_event_golden.json, tests/test_phase7_discovery_api.py,
  .agent/phase7/decisions/P7_D2_DISCOVERY_CORRECTIONS.md
- modified: ml/views/event_analysis.py (analyze_event, M5V2Required, EventAnalysis), ml/views/qualification_forecast.py
  (forecast_event_qualification, ForecastMatch, EventQualificationForecast), api/routes/event_analysis.py and
  api/routes/qualification_forecast.py (now thin; no route-to-route import), api/app.py (discovery router),
  tests/phase7_support.py (api_routes / api_routes_checked; refuses mounts at any depth), tests/test_phase6_contract.py,
  tests/test_phase7_contract.py, tests/test_api_foundation.py (PHASE7_PATHS), docs/phase7.md,
  docs/api_contract_lock.json (+5 operations, 13 total; P7-D2 relock), .agent/phase7/M01_ACCEPTANCE.md (erratum)

## Scope delivered
- (a) Event-analysis and qualification-forecast composition extracted into ml/views services, behaviour unchanged.
  The routes only check input, call the service, label and serialize. The services are reusable by the
  pre-match report.
- (b) Both routes locked.
- (c) Discovery reads (P7-Q8), read-only, served from canonical tables:
  - GET /events?season=
  - GET /events/{event_key}/teams (the shared roster)
  - GET /events/{event_key}/matches?as_of=, point in time:
    - the qualification schedule is always visible;
    - a playoff match is visible only once scheduled before as_of (P7-D2);
    - a result is visible only for a match scheduled before as_of;
    - a withheld result is null with its reason.

## Acceptance criteria (spec)
- The extracted services reproduce the post-P7-M3 responses exactly at a fixed as_of: PASS.
  - The golden was captured from both routes before extraction, at pre-event, after-switch, pre-event forecast and
    after-all forecast as_of values.
  - The model stubs are feature-dependent and red/blue-asymmetric, so values vary: both ordering policies,
    probabilities 0.75-0.95 including the clip, different expected wins. A guard refuses a constant golden.
  - The extracted services reproduce it key for key.
- The extracted error paths are covered: PASS. model_not_loaded on both routes (Phase 5 tests); epa_source_incomplete
  and epa_source_pending propagated from both services and mapped to declared codes (new tests).
- Discovery reads are read-only and point in time where they expose results: PASS.
  - Results appear only for matches scheduled before as_of.
  - Playoff matches and their alliances appear only once available; an untimed playoff match is never listed.
  - The schedule is visible; empty cases are 200 []; every refusal code is checked with assert_declared_error.
- Five operations locked: PASS (lock check exit 0; the P7-D2 relock is recorded with its 2 changed entries and
  decision reference).

## Terminal verification
- Final full suite: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest -q --tb=line -p no:cacheprovider`
  -> 5 failed, 2304 passed, 5 skipped (6:05); pytest exit 1 from the 5 baseline failures only. Same 5 tests as the
  baseline by name; 0 regressions; skips unchanged at 5.
- An earlier run, before the review fixes: 5 failed (the same 5), 2298 passed, 5 skipped.
- `python -m scripts.phase7_contract_lock check` -> exit 0.
- type check / lint: not configured.

## Found during this milestone
- FastAPI 0.141 wraps included routers, so two M1 tests and the new owned-endpoints test walked no routes.
  Fixed with a walker proven complete against OpenAPI, with non-vacuity checks; the M1 record carries an erratum.
  Both M1 criteria re-verified with real checks.

## Phase F (independent review): 8 findings, all resolved
1. High: playoff matches and their alliances were listed before they existed, which leaks the selection outcome
   and, through bracket structure, withheld results. Fixed (P7-D2): listed only once scheduled before as_of; never
   when untimed. Tested with a playoff fixture.
2. Medium: scheduled_time is a weak availability proxy (late events; corrected scores). Documented as a limit in
   the module, the route description and docs/phase7.md. It is the same rule as the feature assembler; a tighter
   rule needs a post-result time the canonical tables do not hold, which would need a decision.
3. Medium: winning_alliance documented as "null for a tie". Fixed: red, blue or tie (normalizer); null only when
   none recorded. Tested with a real 'tie'.
4. Low: event_type was always null (never written). Removed before any client used it (P7-D2; recorded relock).
5. Low: docs omitted the declared 422 on /teams. Fixed.
6. Low: match ordering by key string. Fixed: scheduled time, qualification before playoffs, set, match number.
   (DESCRIPTIVE is imported from ml.views.strength: the direction is correct; kept.)
7. Low: test gaps. Added service-level EPA refusal tests for both routes; the wrong-route code test now runs the
   real check against the planted code.
8. Nit: mounts inside included routers were skipped. The walker now refuses a mount at any depth.

## Remaining known risks
- The scheduled_time availability proxy (finding 2) is shared with the feature assembler; recorded for the
  Phase-Level Audit.
- The golden does not cover a real statbotics_week or the live source's flags. While writing this record, a check
  showed no test drove a real week through the route (the Phase 5 test covers only null). Added
  test_the_forecast_labels_early_season_weeks_low_confidence: weeks null/1/3/4/6, run after the final full suite,
  22/22 discovery tests pass. The live flag is covered at epa_info level (tests/test_epa_adoption.py), and the
  code that applies it was moved verbatim.

## Decision
ACCEPTED. All P7-M4 criteria passed with the evidence above; 0 regressions. Next: P7-M5 (match strategy), then the
Mid-Phase Audit.
