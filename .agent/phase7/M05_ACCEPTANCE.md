# P7-M5 — Match strategy: acceptance record

status: ACCEPTED (2026-10-18); real P6-M10 artifact checks BLOCKED (environment)
spec: docs/P7Milestones.md P7-M5 (a)-(e), acceptance (1)-(8) (frozen); P7-Q9, P7-Q10, P7-Q11, R1-R3, R11, R13, R14,
R16, R19; post-freeze P7-D1 (as_of rule), P7-D3
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new: ml/strategy/service.py, api/routes/strategy.py, scripts/phase7_m5_recommend_latency.py,
  tests/test_phase7_strategy_api.py (51 tests), .agent/phase7/decisions/P7_D3_STRATEGY_CORRECTIONS.md
- modified: data/config.py (ml_strategy_* pins), api/ml_loading.py (load_pinned_strategy_model), api/dependencies.py
  (get_strategy_model), api/app.py (state + router), api/routes/common.py (require_writer moved here, unchanged),
  api/routes/human_inputs.py (re-exports it), ml/strategy/coach_inputs.py (load_coach_observations landed_before=,
  default unchanged), tests/test_api_foundation.py (PHASE7_PATHS), docs/phase7.md, docs/api_contract_lock.json
  (+8 operations, 21 total; P7-D3 relock)

## Scope delivered
- (a) Model pin (type, version tag, sha256; all required), loaded only through load_registered_strategy_model,
  so the served baseline reason is p6_m10_gate_failed. Unpinned, wrong sha, or a malformed artifact gives
  model_not_loaded, never a crash.
- (b) ml.strategy.service builds the MatchContext for a scheduled match (as of its scheduled time) or a
  hypothetical 3v3 (explicit match_context; as_of not in the future; six distinct teams). Both paths get the
  identical observations, observed and stored before as_of (P7-D3). Refusals are typed, in the engine's own order.
- (c) assess / recommend / compare, for scheduled matches and hypotheticals. Odds are StrategyOdds display strings
  with the engine's status and reasons. selection_note and the three-valued compare label are served. No raw
  precision. The EPA source envelope is on every response (P7-D3).
- (d) Coach strategy and observation writes: write token (fail closed); raw JSON body landed raw-first; limits
  documented (caller-asserted author and observer, no existence checks, no size limit).
- (e) Latency measured against the pre-registered 10 s budget: within budget, documented (see below).

## Acceptance criteria (spec)
- (1) HTTP parity: PASS.
  - The recommendation, its alternatives and the baseline, re-assessed and compared as a coach would, give
    identical displays, statuses and reasons, on both sides, for scheduled matches and hypotheticals, with
    observations.
  - Defects planted in the HTTP layer are caught: a middleware re-rounding, relabelling or dropping a reason on
    /assess or /compare, and a dependency override serving a different model to /recommend only.
  - The engine-level P6-M13 audit is unchanged; its fixture tests pass in the suite (tests/test_phase6_parity_audit.py).
  - Re-running it on the real artifact (writing to .agent/phase7/results/) is BLOCKED (environment).
- (2) Every probability is not_validated with its reasons: PASS (baseline p6_m10_gate_failed; a non-baseline
  strategy adds strategy_effect_unmeasured and the defense reason; coach_observation_effect_unmeasured).
- (3) A playoff context is a 200 with null odds and playoff_model_unavailable; missing inputs are a 200 with
  insufficient_data and missing_input:*: PASS.
- (4) Typed 4xx: PASS. Covered: validation_error (malformed strategy; non-distinct hypothetical teams;
  missing match_context; non-object coach body), invalid_strategy, invalid_coach_input, alliance_incomplete,
  mixed_season_scale (HTTP 409 and service level), match_not_found, match_not_scheduled, match_context_unknown,
  event_not_found, team_not_found, invalid_as_of (including future), model_not_loaded, epa_source_not_loaded.
  Any other ValueError is a 500 that leaks nothing (tested).
- (5) Write token: unset is writes_disabled; wrong or missing is write_not_authorized; correct stores raw-first.
  On invalid_coach_input the raw row exists; a 403 or a non-object body stores nothing: PASS.
- (6) No raw-precision field in any schema or body: PASS.
- (7) Latency recorded against the 10 s budget: PASS (measured, within budget, documented).
  - End to end over HTTP, 0 observations: 1.86 s.
  - Engine only, by coach observations at the event: 0 → 1.27 s, 25 → 2.16 s, 100 → 4.43 s, 300 → 8.77 s
    (median of 3).
  - Local machine and synthetic model (is_environment_of_record false).
  - Not a write-once record: scripts.phase5_records refuses an uncommitted tree, and commits wait for Sven.
    `scripts/phase7_m5_recommend_latency.py --record` writes it from a clean tree.
- (8) Real P6-M10 artifact checks: BLOCKED (environment) until P7-Q5.

## Terminal verification
- Final full suite: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest -q --tb=line -p no:cacheprovider`
  -> 5 failed, 2360 passed, 5 skipped (7:54); pytest exit 1 from the 5 baseline failures only. Same 5 tests as the
  baseline by name; 0 regressions; skips unchanged.
- An earlier run, before the review fixes: 5 failed (the same 5), 2343 passed, 5 skipped.
- After the review fixes: tests/test_phase7_strategy_api.py, test_phase6_coach_inputs.py and
  test_phase6_parity_audit.py -> 62 passed.
- `python -m scripts.phase7_contract_lock check` -> exit 0.
- type check / lint: not configured.

## Phase F (independent review): 9 findings, all resolved or recorded
1. Medium-high: duplicate or shared teams in a hypothetical gave a 500, or odds for an impossible match. Fixed: the
   request model requires six distinct teams (422). Tested for assess, recommend and compare.
2. Medium: no EPA source envelope on strategy responses. Fixed (P7-D3; relock recorded).
3. Medium: observations filtered only on caller-asserted observed_at, so a back-dated later submission changed past
   evaluations. Fixed (P7-D3): also stored before as_of. Tested both ways. The invalid count is now point in time
   too.
4. Medium: the latency claim was engine-only and ignored observations. Fixed: end-to-end measurement plus the
   observation scaling; the threshold (about 300 observations) is a recorded risk.
5. Low-medium: coach_observations_applied wording overstated. Reworded.
6. Low: test gaps. Added: HTTP 409 mixed_season_scale; ValueError is a 500; hypothetical recommend and compare;
   planted defect on /compare; observations through every path.
7. Low: the sha256 was optional and a KeyError could crash startup. Fixed: the sha256 is required; KeyError is
   caught. Tested.
8. Low: coach-write limits. Documented (no existence checks, no size limit, caller-asserted identities).
9. Low: docs status. Fixed. _compare uses the engine's own assess and compare_odds label rule (identical
   semantics), so the difference value is never formed in a response.

## Remaining known risks
- Recommend latency grows with coach observations at the event (about 0.025 s each); past about 300 it would exceed
  the budget, and nothing bounds the count. The fix (observations restricted to the six teams) needs its own
  decision.
- Coach writes: one shared secret; no rate limit or size limit; caller-asserted identities (P7-Q10, documented).
- Real-model checks and the real-artifact P6-M13 re-run: BLOCKED (environment).

## Decision
ACCEPTED. Every P7-M5 criterion that can run here passed with the evidence above. (8) and the real-artifact part of
(1) are recorded as BLOCKED (environment), not passed. 0 regressions. Next: the Mid-Phase Audit, then P7-M6.
