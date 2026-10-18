# P7-M7 — Pre-match report data: acceptance record

status: ACCEPTED (2026-10-18); real-model output BLOCKED (environment, P7-Q5): the win probability and strategy
parts run on stub/synthetic models here
spec: docs/P7Milestones.md P7-M7 (frozen); P7-Q12, P7-A3, P7-A7, R2; post-freeze P7-D4 (as_of rule)
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new:
  - ml/views/pre_match_report.py: the service;
  - api/routes/pre_match_report.py: `GET /matches/{match_key}/pre-match-report`;
  - api/win_probability.py: the one M6/M7 evaluation, moved from api/routes/predictions.py;
  - api/strategy_shapes.py: the strategy shapes and builders, moved from api/routes/strategy.py;
  - tests/test_phase7_pre_match_report_api.py (27 tests).
- modified:
  - ml/strategy/service.py: `context_for_match(as_of=)`, default unchanged;
  - api/contract.py: `m6m7_unvalidated_reason`;
  - api/routes/predictions.py and api/routes/strategy.py: these now use the shared modules, with behaviour
    unchanged;
  - ml/synergy/score.py: `SYNERGY_VALIDATION_STATUS`;
  - api/app.py: the router;
  - tests/test_api_foundation.py (PHASE7_PATHS), docs/phase7.md, docs/api_contract_lock.json (+1 operation, 24
    total).

## Scope delivered
One structured aggregate per scheduled match, at `min(as_of, scheduled_time)`:
- `teams[]`: the P5-M3 strength view, including the EPA components, with provenance;
- `synergy[]`: Phase 4 M9;
- `win_probability`: M6/M7 in `CalibratedWinProbability`, through the one shared evaluation;
- `strategy`: P6-M11/P6-M10, recommend and baseline per side, through the P7-M5 service;
- `not_produced`: the six ROADMAP items, each null with `not_produced_by_any_engine` and its semantics.

A missing model or an engine refusal drops only its own part, with a typed `absent_code` and an `absent_reason`.

## Acceptance criteria (spec)
- (1) Every field traces to a named engine output or is an explicit absence: PASS.
  - Each part names its source.
  - At the scheduled time, the parts equal the routes that serve the same engines (tested):
    - `win_probability` equals the predictions route's `win_probability`;
    - each strategy side equals `/strategy/matches/{key}/recommend` (recommended, baseline, vs_baseline_label,
      unavailable_reasons, context);
    - each team's strength (and defense with observations present) equals the strength route.
  - The absences are tested:
    - each model missing on its own, the other part still served;
    - `alliance_incomplete`, for synergy and the strategy;
    - `match_context_unknown`;
    - `mixed_season_scale`;
    - `insufficient_features` (the predictions route's 422 here is a typed absence);
    - a playoff match (`playoff_scope`; `playoff_model_unavailable`).
- (2) No look-ahead: PASS.
  - At the scheduled time: a later score on the match itself, a later match and a later EPA row change no field.
  - At an earlier `as_of`, none of these change the report:
    - a scored match between the moment and the match;
    - a prior event ending after the moment, with its own EPA;
    - scouting submitted after the moment for an event match before it;
    - a back-dated coach observation stored later;
    - a stored `team_metrics` row.
  - The same data does change a report taken at the match, so it is not inert.
  - A planted defect (moment = as_of, ignoring scheduled_time) fails 3 tests.
- (3) No field is free text generated in the core: PASS. Every string is an engine label, an identifier or a
  constant. The report modules import no LLM or HTTP client and never read the metrics snapshot (AST test).
- (4) Defense/feeding absence is explicit: PASS. When observations are too few, the value is null with
  `insufficient_data` (tested). With observations present, the values pass through unchanged (median 3.0, n=2,
  equal to the strength route).
- (5) The INTERIM caveat is present: PASS. Every team has `reliability_score_interim`, and the route description
  carries INTERIM (contract test).
- (6) Only services from P7-M2…M6, with no new model, heuristic or derivation rule: PASS.
  - The review found the first draft importing private route helpers (P7-A3). They were moved into
    `api/win_probability.py` and `api/strategy_shapes.py`, which both the routes and the report use.
  - The contract lock confirms that no previously locked schema changed.
- (7) The stored team_metrics snapshot is never read: PASS (the behavioural test in (2), plus the AST test).
- Errors (all tested):
  - `match_not_found`;
  - `match_not_scheduled`;
  - `invalid_as_of` (future; malformed);
  - `epa_source_not_loaded`;
  - `epa_source_incomplete` / `epa_source_pending`.

## Terminal verification
- The final full suite is shared with P7-M6:
  - command: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest tests -q --tb=line -p no:cacheprovider`
  - result: 5 failed, 2468 passed, 5 skipped; pytest exit 1 from the 5 baseline failures only (same names).
  - 0 regressions. The raw log stays local (`.agent/phase7/runs/m6m7_full.txt`, excluded from the commit).
- The predictions goldens (tests/test_phase7_predictions_regression.py) pass after the M6/M7 evaluation moved.
- `python -m scripts.phase7_contract_lock check` exits 0 (24 operations).

## Phase F (independent review)
- **Round 1:** no blocking defects. One moderate conformance finding: private route helpers were imported and the
  M6/M7 evaluation was duplicated (P7-A3). Fixed, as described in (6). Six test gaps, all added:
  - a stronger look-ahead check;
  - `mixed_season_scale`;
  - the EPA refusals;
  - defense present;
  - `insufficient_features`;
  - a single model missing.
- **Nits applied:** a typed `absent_code` next to `absent_reason`; accurate refusal wording; the docs on an earlier
  `as_of` and the cost.
- **A real bug the new tests exposed:** one part of the first look-ahead test was inert. Scouting counts only at
  the target event, so its prior-event scouting row proved nothing. Fixed.
- **Round 2:** the adversarial workflow did not run (all agents stopped by the spend limit). Recorded as not done.

## Remaining known risks
- **Cost:** two full recommendations per report, and each team's features are built three times. It grows with
  coach observations, like P7-M5 (unbounded; recorded at M5).
- **Inherited:** a 2v3 qualification match with full EPA gets a validated M6/M7 value. The predictions route does
  the same (documented).
- **Real-model output** (M6/M7 and P6-M10 artifacts): BLOCKED (environment) until P7-Q5.

## Decision
ACCEPTED. Every P7-M7 criterion passed with the evidence above. 0 regressions. Real-model output is BLOCKED
(environment), not claimed.
