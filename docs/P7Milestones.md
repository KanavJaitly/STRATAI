# Phase 7 — API Layer: milestones

Status: **REVISION 2 — APPROVED (Sven Morais, 2026-10-17).** P7-A1, A3 … A9 approved and P7-Q1 … Q13 decided in
`.agent/phase7/P7_M0_DECISIONS.md`. **FROZEN** at the git blob hashes recorded in `.agent/phase7/P7_M0_FREEZE.md`
(2026-10-17). No Phase 7 implementation existed when the freeze was recorded.

Sources:
- `docs/ROADMAP.md` (Phase 7 text and done-means).
- `prompts/MASTER_BUILD.md`: the execution, escalation and acceptance protocol.
- `.agent/phase6/decisions/P6_PHASE_ACCEPTANCE_2026-10-17.md`: Phase 6 accepted with P6-DM1 deferred.
- The repository as of `4290a3d` (main after PR #31). Independent reviews of the drafts against the code were
  folded in before the freeze.

## Phase 7 done-means (from `docs/ROADMAP.md`, immutable)

- **P7-DM1:** every core feature is callable via the API with documented examples. The core features are match
  strategy, win probability, team metrics, rankings, alliance selection, event analysis and pre-match report data.
- **P7-DM2:** no endpoint shape changes after frontend work begins. Phase 7 makes this checkable: the locked
  shapes are pinned by a contract test, so a change fails the contract suite that runs at every milestone
  acceptance instead of relying on memory (P7-A4). No CI job runs pytest today; adding one is not Phase 7 scope.

For a feature that cannot produce real output today (alliance selection; playoff-context strategy odds), P7-Q1
decides how P7-DM1 is judged: P7-M9 reports it as **"callable, refusal only; real output deferred with P6-DM1"**,
never as plainly met.

## Standing rules (apply to every milestone)

- **Phase 3–6 rules are unchanged.** That means: no LLM in the core; point-in-time features; nothing unvalidated
  is presented as validated; human inputs are never fabricated; D9; the 45-minute verification limit; tests only
  on isolated `stratai_test*` copies.
- **Status on every new output.** Every new Phase 7 result carries the P7-Q3 `validation` block
  (`validation.status`, `validation.reasons`, optional `validation.evidence`). Existing routes keep their current
  `validation_status` fields unchanged. The Phase 3 metrics route gains an additive `validation` block (P7-Q13).
- **Status vocabulary is inherited, never upgraded.** A Phase 7 status only repeats a label an engine or record
  already assigns. Phase 7 never emits `validated` for anything its source does not already label `validated`.
- **Point in time.** Anything that describes a match or a moment uses data available at
  `min(as_of, scheduled_time)`. A stored current-state snapshot (`team_metrics`) is never used to describe a past
  moment.
- **Routes are thin.** A route parses, calls one service function, and maps the result or a typed exception to
  the response. Composition logic lives in `ml/` or `data/` service functions that other endpoints and scripts can
  reuse (P7-A3).
- **No engine behaviour changes.** Phase 7 serializes what Phase 3–6 engines compute. It does not change a
  probability, label, threshold, model or methodology. Display rules live with their engines (`ml/`), not in
  routes. Phase 7 never adds, adjusts, rounds or caches a probability (P6-A5, P6-DM2, `ml/strategy/engine.py`
  contract). Any exception needs a new dated decision and a parity audit.
- **Validated and unvalidated values never share a key.** The M12 safeguard stays: a validated probability and an
  unvalidated one are distinct fields, and the validated field is `null` whenever the value is not validated.
- **No raw precision leaks.** For P6-M10 and the playoff/selection track, only the engine display rule's output
  is serialized (`ml.strategy.display`, P6-A5: "<5%" / ">95%" / 0.05 steps). These engine values are **never**
  serialized: `p_ours`, `p_red`, `p_blue`, `mean_difference`, `sigma`, `component_means` (and
  `Assessment.explanation()`'s `expected_component_means_normalized`, from which `p` can be recomputed with the
  published `beta` and `sigma`), compare/`vs_baseline` `difference`, and `p_win_event`, `p_reach_finals` and
  `margin_over_next` as raw floats. Probabilities appear only in displayed form. A difference appears only as the
  display rule's label (`ml.strategy.display.compare_odds(...)["label"]`). Roles and assignments from
  `explanation()` are allowed.
- **One error envelope; engine codes pass through where they exist.** Every non-2xx response uses
  `api/errors.py`'s envelope. `RulesetError` (raised by `data.rulesets` and by `ml.playoffs.selection`) carries a
  `.code`, and the API `code` equals it (the `api/routes/metrics.py` convention), always with status 409. These are
  states of the stored rules or event data, consistent with `api/routes/human_inputs.py`'s 409 for `invalid_state`
  and `storage_integrity`. `StrategyError` and
  `CoachInputError` have no code, so the API assigns new ones: `invalid_strategy` (422) and `invalid_coach_input`
  (422). `CoachInputError.problems` is joined into the message (the `api/routes/human_inputs.py` precedent;
  `ApiError` has no details field). A malformed request body is pydantic's 422 `validation_error`. Every new code
  has a status below 500, because codes are stripped at ≥500 (`api/errors.py`). A plain `ValueError` is never
  mapped wholesale to 4xx: services pre-validate inputs and raise typed errors, and anything else stays a 500.
- **Pre-validation mirrors the engine's order.** A request the engine would answer with a 200 (for example a
  playoff context, answered with `playoff_model_unavailable`) is never turned into a 4xx by an earlier API check.
- **Absence is explicit.** Unavailable, unknown and zero are distinct in every shape: `null` with a reason or
  status, never `0` or an omitted key.
- **INTERIM caveat travels.** Every route that serves `reliability_score` carries the INTERIM caveat in its
  description (`tests/test_metrics_docs_contract.py`).
- **Shapes are additive after the lock.** After a family's shapes are locked (P7-M1 mechanism), a change is
  either a backward-compatible addition with an updated snapshot or a new, dated decision row (P7-DM2).

## Milestones

### P7-M0 — Specification freeze

| | |
|---|---|
| **Objective** | Freeze this specification and its decisions before any Phase 7 implementation |
| **Scope** | This document; `.agent/phase7/P7_M0_DECISIONS.md`; a freeze record `.agent/phase7/P7_M0_FREEZE.md` with git blob hashes. **Status: FROZEN (2026-10-17)** |
| **Depends on** | Phase 6 acceptance (2026-10-17, recorded at Sven Morais's request; its record asks Kanav to confirm) |
| **Acceptance** | A freeze record naming the frozen files and their blobs, with every P7-Q decided, and zero Phase 7 implementation when it is recorded. P7-Q11 is decided as a procedure (measure, then budget) whose measurement happens in P7-M5 |
| **Human input** | **Yes:** Sven Morais (approved 2026-10-17) |
| **Prerequisite for** | Every Phase 7 milestone |

### P7-M1 — API contract foundation

| | |
|---|---|
| **Objective** | The shared mechanics every Phase 7 endpoint uses, so the endpoint families do not each invent their own |
| **Scope** | (a) The shared response building blocks decided in P7-Q3. (b) Request and response examples declared on routes so they appear in OpenAPI. (c) A shape-lock contract test that snapshots the OpenAPI component schemas and path operations of locked routes and fails on any unreviewed change (P7-A4, P7-Q4). (d) `docs/phase7.md` plus `tests/test_phase7_contract.py`, following the Phase 5/6 pattern. (e) Contract-test coupling, each change dated and recorded: supersede `tests/test_phase6_contract.py::test_no_phase6_http_routes_exist` (P7-A5) with an allow-list. Phase 6-capability paths may exist only in `api/routes/strategy.py` (`/strategy/…`), `api/routes/alliance_selection.py` (`/events/{event_key}/alliance-selection/…`) and `api/routes/pre_match_report.py` (`/matches/{match_key}/pre-match-report`), and any other module's path matching the old regex still fails. Discovery reads live in `api/routes/discovery.py` (`/events`, `/events/{event_key}/teams`, `/events/{event_key}/matches`); give `tests/test_metrics_docs_contract.py` a Phase 7 path set (its documented-endpoints and INTERIM-caveat checks); extend the `tests/test_api_foundation.py` path pin deliberately per family. (f) Declared OpenAPI error responses (codes and statuses) for every route. (g) Per P7-Q6: paths stay unversioned and `/docs` / `/openapi.json` stay on |
| **Non-goals** | New endpoint families; changing an existing response shape (that belongs to each family's milestone) |
| **Acceptance** | The shape-lock test passes on the current routes and fails on a planted shape change (shown in a test). Every existing route declares its error responses. Each contract-test change is recorded with a date and reason |
| **Human input** | No (beyond P7-M0) |
| **Prerequisite for** | P7-M2 … P7-M8 |

### P7-M2 — Team metrics and strength

| | |
|---|---|
| **Objective** | Lock the team-level shapes: stored Phase 3 metrics and the point-in-time P5-M3 strength view |
| **Scope** | `GET /teams/{team_number}/events/{event_key}/metrics` and `GET /teams/{team_number}/events/{event_key}/strength`: examples, declared errors and shape lock. The metrics route gains an additive `validation` block before it is locked (P7-Q13). It is a response subclass of `TeamMetrics`, so `TeamMetrics` itself and the docs example validated against it stay unchanged. Its vocabulary is inherited: defense `descriptive_definition_pending`, feeding `not_validated` (or `insufficient_data`), as in `ml/views/strength.py`; never `validated` (Phase 3 M14 is still open). The INTERIM reliability caveat (`data/metrics/schemas.py`) is carried as a `validation.reasons` entry, not as a status. No team-history endpoint (P7-Q8) |
| **Engines** | `data.metrics.read.look_up_team_metrics` (current-state, no `as_of`); `ml.views.strength.build_team_strength` (point in time) |
| **Acceptance: metrics** | Success; every 404/422 code (`team_not_found`, `event_not_found`, `team_did_not_attend`, `metrics_not_computed`, validation); a thin-data team (200 with its `*_insufficient_data` flags). Its documentation states it is a current-state snapshot, not point in time |
| **Acceptance: strength** | Success; `invalid_as_of`; `epa_source_*`; point-in-time `as_of`. Defense keeps `descriptive_definition_pending`, and feeding keeps `not_validated` / `insufficient_data` |
| **Human input** | No |

### P7-M3 — Win probability and rankings

| | |
|---|---|
| **Objective** | One canonical win-probability family and one canonical rankings family, with consistent `as_of` and labels |
| **Scope** | (a) The four `/predictions/*` routes and `GET /events/{event_key}/qualification-forecast`'s per-match probability, using the P7-Q3 building blocks. (b) Optional `as_of` on `POST /predictions/win-probability` and `POST /predictions/alliance-synergy` (P7-Q7). (c) Move the M6/M7 display rule (`display_probability`, today in `api/routes/predictions.py`) into `ml/`, behaviour unchanged, keeping a re-export in `api.routes.predictions` because `scripts/verify_d18_production.py`, `scripts/verify_p5_live_adoption.py`, `scripts/phase5_m2_live_epa_checks.py`, `tests/test_phase6_strategy_model.py` and `tests/test_api_predictions.py` import it there. Changes to existing `/predictions/*` and qualification-forecast fields are **additive only**: every field those two verification scripts read (`red_win_probability`, `unvalidated_red_win_probability`, `validation_status`, `teams[].epa_value_source`, `epa.validation_flags`, …) keeps its name, type and meaning. (d) Keep the M6/M7 gating exactly: the validated value only for EPA-complete qualification matches; otherwise `null`, with the rounded model output only in the unvalidated field and its reason (`playoff_scope`, `unspecified_context`, `epa_incomplete`); `calibration_status = m7_gate_failed`; 0.05 rounding and the [0.05, 0.95] clip. (e) P7-Q2: `GET /events/{event_key}/analysis` ordering is the canonical rankings surface. `GET /predictions/events/{event_key}/ranking` stays with unchanged behaviour and label, marked `deprecated` in OpenAPI and documented as non-canonical with its reason. It gets no `as_of`. Its consumers (`scripts/verify_d18_production.py`, `scripts/verify_p5_live_adoption.py`, its tests and `docs/ml_models.md`) keep working |
| **Engines** | M5 v2 (`ranking_xgb_v2`), M6/M7 (`win_prob_xgb_calibrated`), `ml.synergy.score.alliance_synergy` |
| **Acceptance** | A regression test with a frozen clock or fixed `as_of` shows that every served value (validated and unvalidated, at display resolution) is identical to the pre-Phase 7 routes for the same inputs. `model_not_loaded` and `epa_source_*` refusals are tested. No new label claims more validation than the Phase 4/5 records support. Checks against the real D18 models are **BLOCKED (environment)** until P7-Q5's environment exists; fixture-model tests do not stand in for them |
| **Human input** | No |

### P7-M4 — Event analysis and discovery

| | |
|---|---|
| **Objective** | Make event-level analysis a reusable service, and add the discovery reads the core features need |
| **Scope** | (a) Extract the composition now inside `api/routes/event_analysis.py` and `api/routes/qualification_forecast.py` into service functions, behaviour unchanged. (b) Lock `GET /events/{event_key}/analysis` and `GET /events/{event_key}/qualification-forecast`. (c) Discovery reads (P7-Q8): the events list, an event's teams and an event's matches, read-only from the canonical tables, point in time where they expose results. No team-history endpoint |
| **Engines** | `ml.views.event_analysis`, `ml.views.qualification_forecast`, `ml.features.roster` |
| **Acceptance** | The extracted services reproduce the post-P7-M3 responses exactly (regression test at a fixed `as_of`). Discovery reads are read-only, and point in time where they expose results |
| **Human input** | No |

### P7-M5 — Match strategy

| | |
|---|---|
| **Objective** | Expose the P6-M11 strategy engine over HTTP for the AI and coach paths, preserving P6-DM2 parity |
| **Scope** | (a) Settings pins (type, version tag, sha256) and a startup loader for the P6-M10 artifact that uses `ml.strategy.outcome.load_registered_strategy_model`, so the served baseline status is `p6_m10_gate_failed`; `model_not_loaded` when unpinned. (b) A service that builds a `MatchContext` from a match key, or from a hypothetical 3v3 alliance plus event, `as_of` and an explicit `match_context` (`qualification` or `playoff`; omitted means 422, P7-Q9). It pre-validates inputs (3v3, one season scale, a well-formed strategy) in the engine's own order and raises typed errors. Typed errors: a scheduled match without three teams per alliance gets the **new** code `alliance_incomplete` (409); a hypothetical alliance that is not 3v3 is rejected by the request model (422 `validation_error`); six teams on different season scales get the **new** code `mixed_season_scale` (409), raised only where the engine itself would raise, after its playoff and missing-input checks. Both the AI and coach paths build the context with the identical `load_coach_observations(database, event_key, as_of)` output, so any observation adds the same `coach_observation_effect_unmeasured` reason to both. (c) Endpoints for assess (a given strategy), recommend (the AI strategy) and compare (AI vs coach), each for a match key and a hypothetical alliance (P7-Q9). The recommend shape carries `selection_note` (P6-Q10, which exists on `Recommendation` only). The compare shape carries the engine's label, one of exactly three values: `ml.strategy.display`'s `INDISTINGUISHABLE`, `DIFFERS` and the "not comparable: a probability is unavailable" text. (d) Coach strategy and observation submission (POST) through `ml.strategy.coach_inputs`, which stores raw-first in the existing `raw_source_payloads` table (no migration), protected by the existing `require_writer` write token (P7-Q10). The POST bodies take the raw JSON object (as the human-input routes do), so validation happens inside `ml.strategy.coach_inputs` after the raw-first landing. Documented limits: `author` / `observer` are caller-asserted strings, not authenticated identities; a submission is landed before validation, so a rejected (4xx) submission stays in `raw_source_payloads`; plus the P7-Q10 token limits. (e) Recommend latency (P7-Q11): the budget is pre-registered here, before any measurement, as **10 seconds per recommend request** (one interactive request from a Phase 8 view). It is measured on the environment of record, or, until that exists, measured locally and labelled as local. Within budget: documented. Over budget: an asynchronous job endpoint |
| **Engines** | `ml.strategy.engine.StrategyEngine`, `ml.strategy.outcome`, `ml.strategy.coach_inputs`, `ml.strategy.display`, `ml.strategy.representation` |
| **Acceptance** | (1) **HTTP parity:** for identical strategies the AI and coach endpoints return identical displayed odds, statuses and reasons. Defects planted in the HTTP layer through dependency overrides are caught: a route that rounds, clips or relabels one path differently, and a route that swaps the model for one path. The engine-level P6-M13 audit is unchanged and not re-implemented over HTTP. Its fixture-engine tests (`tests/test_phase6_parity_audit.py`) pass in the suite. A re-run on the real P6-M10 artifact writes a new Phase 7 record under `.agent/phase7/results/` (never into `.agent/phase6/results/`, whose records are write-once) and is **BLOCKED (environment)** until P7-Q5. (2) Every probability carries `not_validated` and its reasons (`p6_m10_gate_failed`, `strategy_effect_unmeasured`, …). (3) A playoff context returns 200 with null odds and reason `playoff_model_unavailable`, the engine's own result. Missing inputs return 200 with `insufficient_data` and `missing_input:*` reasons. Both are tested. (4) Malformed request bodies (422 `validation_error`), `invalid_strategy` (422), `invalid_coach_input` (422), `alliance_incomplete` (409) and `mixed_season_scale` (409) are each tested. Any other `ValueError` is a 500. (5) Write-token behaviour is tested: unset → `writes_disabled`, wrong → `write_not_authorized`, correct → stored raw-first. On `invalid_coach_input` (422) the raw row exists, which is asserted. A 403 or a non-object body is not stored. (6) No value from the no-raw-precision list appears in any response (asserted on the OpenAPI schemas and on response bodies). (7) The recommend latency measurement and its environment are recorded against the 10-second budget. (8) Checks against the real P6-M10 artifact are **BLOCKED (environment)** until P7-Q5's environment exists |
| **Human input** | No for the build. Real coach entries are never fabricated as evidence |

### P7-M6 — Alliance selection

| | |
|---|---|
| **Objective** | Lock the alliance-selection shapes now, serving what can honestly run today and the engine's own refusal for what cannot (P7-Q1) |
| **Scope** | (a) Candidate profiles (`ml.playoffs.selection.candidate_profile`, P6-M6 factors). These need no ruleset: `TeamFeatures` at the selection moment plus an optional caller-supplied three-team configuration. `as_of` defaults to the event's selection moment, computed by the same rule as `EventPlayoffs.selection_as_of()`: `ml.playoffs.px1.selection_moment(latest scheduled qualification time)`. That also works before any playoff rows exist, when `read_event_playoffs` builds no `EventPlayoffs`. An event with no scheduled qualification match returns the **new** code `selection_time_unavailable` (409) instead of a 500. Without a configuration, `synergy` and `role_compatibility` are `insufficient_data` ("alliance incomplete"), as the engine returns them. It carries the INTERIM caveat because it serves `reliability_score`. (b) A pick-list / recommendation endpoint whose locked shape covers the P6-M7 output under the no-raw-precision rule (probabilities as P6-A5 display strings). The frozen P6-M7 reasoning ("change in P(win event) and in P(reach finals) versus the next-best candidate", `docs/P6Milestones.md`) is served as the display rule's label for each comparison, `compare_odds(p_candidate, p_next)["label"]`, with `null` and a reason for the last candidate. It runs only when every check passes, in this order: (1) `data.rulesets.approved_ruleset` for the season; (2) `.for_event(event)`; (3) the PX gates, read from the `passed` fields of the write-once records `p6_m2_px1.json` (PX-1, P6-Q3), `p6_m3_px2.json` (PX-2, P6-Q4) and `p6_m5_px4.json` (PX-4, P6-Q5), where a missing record means not passed (the `_require` rule in `scripts/phase6_playoff_track.py`); (4) the engine. `probability_status` is `"validated_playoff"` only when the PX-4 record's `passed` is true, exactly as `scripts/phase6_playoff_track.py` sets it, and never comes from the caller. The first failing check sets the refusal: a `RulesetError` code from steps 1, 2 or 4 (`not_approved`, `storage_integrity`, `wrong_season`, `event_excluded`, `not_covered`, and from `ml.playoffs.selection`: `not_established`, `not_supported`, `infeasible`, `invalid_state`, `event_rules_required`), or at step 3 the **new** code `playoff_models_not_accepted` (409). Today step 1 fails with `not_approved`. (c) The existing `POST /predictions/alliance-synergy` stays where P7-Q2 puts it |
| **Engines** | `ml.playoffs.selection` (`SelectionEngine`, `candidate_profile`), `data.rulesets.approved_ruleset` |
| **Acceptance** | No awaiting-review ruleset and no qualification model is ever used as a playoff model (P6-M1, P6-A12, the 2026-10-17 acceptance record). Every refusal code is tested. The success path is tested against a synthetic approved ruleset and a stub match-probability function in an isolated DB, and labelled as synthetic |
| **Human input** | No for the build. Real output needs P6-M1 (human) and passing PX-1, PX-2 and PX-4 |

### P7-M7 — Pre-match report data

| | |
|---|---|
| **Objective** | One structured aggregate per match that a Phase 8 report or Phase 9 LLM formatter can render without calling the engines again |
| **Scope** | `GET` for one scheduled match key (hypothetical matches are served by the P7-M5 strategy endpoints, not by the report). It assembles existing **point-in-time** outputs only, at `min(as_of, scheduled_time)`: teams and roles from the strategy engine (P6-M10), per-team strength (`build_team_strength`), synergy, M6/M7 win probability in its own fields (P7-A7), and EPA component contributions. It **never** reads the stored `team_metrics` snapshot, which includes later matches. Every ROADMAP Phase 8 report item no engine produces today (strengths/weaknesses labels, defensive threats, key risks, predicted flow, critical matchups, key success factors) is present as `null` with `reason: not_produced_by_any_engine` and documented semantics (P7-Q12) |
| **Engines** | Services from P7-M2 … P7-M6 only. No new model, heuristic or derivation rule (a later derivation needs its own dated decision, P7-Q12) |
| **Acceptance** | Every field traces to a named engine output or is an explicit absence. No look-ahead: a test with a past match shows that later matches change no field. No field is free text generated in the core (no LLM). Defense/feeding absence is explicit. INTERIM caveat present |
| **Human input** | No (P7-Q12 decides any derivation rules) |

### P7-M8 — Real request/response examples

| | |
|---|---|
| **Objective** | Satisfy P7-DM1's "documented examples" with real, reproducible captures |
| **Scope** | A capture script that calls every endpoint in the examples scope (P7-Q4) in-process against a named environment (pinned models, EPA source, database copy) at a fixed `as_of`. It writes the request, response and environment fingerprint to `docs/api_examples/` (P7-Q4). Each endpoint gets either (i) at least one real success and one representative refusal, or (ii) for an endpoint that can only refuse today (P7-Q1), its real refusal, explicitly labelled **refusal-only**, plus the synthetic success from its tests, labelled synthetic |
| **Environment** | P7-Q5's environment of record: the registry folders `ranking_xgb_v2/d18`, `win_prob_xgb_calibrated/d18` and `strategy_outcome_component/p6m10-v1` (sha256-verified against the recorded values), a serving-database dump with migrations through 0011, and the production EPA source configuration. Not on Sven's machine today. Until it exists, P7-M8 is **BLOCKED (environment)** and only the capture tooling and its tests are built |
| **Acceptance** | A contract test checks that every endpoint in scope has its required examples and that every captured response validates against the endpoint's locked schema. Each example records its environment and is reproducible from it |
| **Human input** | Yes: providing the environment of record (P7-Q5) |

### P7-M9 — Documentation, contract tests and sign-off

| | |
|---|---|
| **Objective** | Phase 7 documented, locked and accepted |
| **Scope** | `docs/phase7.md` complete (every endpoint: method, path, parameters, body, response fields and semantics, success and error codes, missing-data behaviour, examples, dependencies); the shape lock covers every core endpoint; Phase-Level Audit; Phase Acceptance Review; `.agent/phase7/PHASE_ACCEPTANCE.md` |
| **Acceptance** | P7-DM1 (with refusal-only features reported as such) and P7-DM2 evaluated honestly. The full suite on an isolated copy in the environment of record, with any environment-only failures named. Phase acceptance by Sven Morais or Kanav |
| **Human input** | Phase acceptance (Sven Morais or Kanav) |

## Order and dependencies

```
P7-M0 (freeze) → P7-M1 (foundation) → P7-M2 metrics/strength → P7-M3 win prob/rankings → P7-M4 event analysis
  → P7-M5 match strategy → [Mid-Phase Audit] → P7-M6 alliance selection → P7-M7 pre-match report
  → P7-M8 examples → P7-M9 sign-off
```

P7-M2 … P7-M6 depend only on P7-M1. They run in this order because P7-M4's regression baseline is the post-P7-M3
shape, and P7-M7 consumes P7-M2 … P7-M6.

## Explicit non-goals of Phase 7

- Any UI (Phase 8), any LLM wiring (Phase 9), cross-season re-validation (Phase 10).
- Running or redesigning any Phase 4–6 model, PX-1 … PX-4, or P6-M10.
- Approving P6-M1 rulesets, or any other human input.
- Changing the Phase 5 human-input routes the existing `frontend/` depends on (22 operations). They are outside
  the snapshot and the examples scope (P7-Q4).
- Any schema or DDL change to the serving database. Production DDL needs Kanav's explicit approval (P6 standing
  rule). The only data writes Phase 7 adds are the raw-first coach-input service functions (P7-Q10), which write
  to the existing `raw_source_payloads` table. Verification never writes to the serving database.
- Editing `docs/ROADMAP.md`, `docs/P5Milestones.md`, `docs/P6Milestones.md` or
  `.agent/phase6/P6_M0_DECISIONS.md` (blob-pinned by `tests/test_phase6_contract.py`).
