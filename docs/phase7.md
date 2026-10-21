# Phase 7 — API Layer

Phase 7 exposes every core feature over HTTP with stable, documented contracts. The core features are match strategy,
win probability, team metrics, rankings, alliance selection, event analysis and pre-match report data.

- **Specification:** `docs/P7Milestones.md`, frozen at P7-M0 (2026-10-17).
- **Decisions:** `.agent/phase7/P7_M0_DECISIONS.md`: P7-A1, A3 … A9 approved; P7-Q1 … Q13 decided by Sven Morais;
  pre-freeze reconciliation R1 … R19.
- **Freeze record:** `.agent/phase7/P7_M0_FREEZE.md`.
- **Status:** `.agent/phase7/PHASE_STATUS.md`. Milestone acceptance records: `.agent/phase7/MXX_ACCEPTANCE.md`.

Phase 7 serializes what the Phase 3–6 engines compute. It changes no probability, label, threshold, model or
methodology, and it never presents an unvalidated output as validated.

## Milestones

| Milestone | Scope | Status |
|---|---|---|
| P7-M0 | Specification freeze | Frozen 2026-10-17 |
| P7-M1 | API contract foundation | Accepted 2026-10-17 (`.agent/phase7/M01_ACCEPTANCE.md`) |
| P7-M2 | Team metrics and strength | Accepted 2026-10-17 (`.agent/phase7/M02_ACCEPTANCE.md`) |
| P7-M3 | Win probability and rankings | Accepted 2026-10-17 (`.agent/phase7/M03_ACCEPTANCE.md`); real-model check blocked (environment) |
| P7-M4 | Event analysis and discovery | Accepted 2026-10-18 (`.agent/phase7/M04_ACCEPTANCE.md`) |
| P7-M5 | Match strategy | Accepted 2026-10-18 (`.agent/phase7/M05_ACCEPTANCE.md`); real-artifact checks blocked (environment) |
| P7-M6 | Alliance selection | Accepted 2026-10-18 (`.agent/phase7/M06_ACCEPTANCE.md`); real output deferred with P6-DM1; playoff label decided (P7-D7) |
| P7-M7 | Pre-match report data | Accepted 2026-10-18 (`.agent/phase7/M07_ACCEPTANCE.md`); real-model output blocked (environment) |
| P7-M8 | Real request/response examples | Tooling and contract test built; real capture BLOCKED (environment, P7-Q5) (`.agent/phase7/M08_ACCEPTANCE.md`) |
| P7-M9 | Documentation, contract tests and sign-off | Verifiable scope complete; environment-of-record suite deferred. **Phase 7 accepted conditionally at phase level by Sven Morais, 2026-10-18** (P7-M8 and that suite deferred; P7-DM1 not met) (`.agent/phase7/decisions/P7_PHASE_ACCEPTANCE_2026-10-18.md`, `.agent/phase7/PHASE_ACCEPTANCE.md`) |

## Conventions every endpoint follows

### One error envelope

Every non-2xx response is `{"error": {"code", "message", "status", "request_id", "details?"}}` (`api/errors.py`).
`details` appears only on request-validation failures. A response at 500 or above never carries a route-specific
code or message, because the envelope is built from constants so nothing internal can leak.

**Every route declares its errors** in the OpenAPI document (`api.contract.error_responses`). For each status it
lists the exact codes it can carry, written as `code` literals in the response description.

- Every route declares 500 (`internal_error`). No route-specific code is ever declared at 500 or above, because
  none could be served.
- 422 `validation_error` is declared wherever request validation can fail: a body, a required query parameter, or
  a non-string parameter. A path string cannot fail, since the router never matches an empty segment, and neither
  can an optional string query, so routes with only those omit it. **Exception:** a route whose only 422 would
  otherwise be FastAPI's default (for example `GET /events/{event_key}/teams`, or a human-input read with a path
  string) declares `validation_error`. Otherwise FastAPI would document its own non-envelope 422.

The declarations are checked in both directions:

- `tests/test_phase7_contract.py` checks that every declared code appears in the route's own module or a module
  it imports. A code copied onto the wrong route fails.
- Each endpoint family's behavioural tests drive its error paths and check every returned code was declared
  (`tests/phase7_support.assert_declared_error`).

**Codes pass through from engines where they exist.** A `RulesetError` code is served unchanged, with status 409.
Codes the API itself introduces are listed with their endpoint family as each one is built.

### Validation status

Every new Phase 7 result carries a `validation` block (`api.contract.Validation`):

| Field | Meaning |
|---|---|
| `status` | The label the producing engine or write-once record assigns, e.g. `not_validated`. Phase 7 never assigns a stronger one |
| `reasons` | Every qualifier, most important first: e.g. `p6_m10_gate_failed`, `strategy_effect_unmeasured`, the INTERIM reliability caveat |
| `evidence` | The record or document behind the status, or null |

Existing routes keep their `validation_status` fields unchanged.

### Probabilities

Two win-probability engines exist. Each response names its model, and their numbers never share a field (P7-A7).

**M6/M7 (`win_prob_xgb_calibrated`): `api.contract.CalibratedWinProbability`.** This keeps the Phase 4 M12
safeguard. A validated value and an unvalidated value are different keys, and exactly one is set:

| Field | When set |
|---|---|
| `validated_value` | Only for an EPA-complete qualification match, M7's evaluated population. `validation.status` is then `approximately_calibrated_qualification` |
| `unvalidated_value` | Otherwise. `unvalidated_reason` is `playoff_scope`, `unspecified_context` or `epa_incomplete`, and the value must not be presented as a probability |
| `calibration_status` | Always `m7_gate_failed` |

Values are rounded to 0.05 and clipped to [0.05, 0.95].

**P6-M10 strategy odds and playoff-track probabilities: `api.contract.StrategyOdds`.** These are display strings
only: "<5%", ">95%", or a 0.05-step percentage (P6-A5). `display` is null when the engine returns no probability,
and then `validation.reasons` carries the engine's reason.

**No raw precision is ever serialized** for these engines. That covers `p_ours`, `p_red`, `p_blue`,
`mean_difference`, `sigma`, `component_means` / `expected_component_means_normalized`, `difference`,
`p_win_event`, `p_reach_finals` and `margin_over_next`. A difference appears only as the display rule's label
(`INDISTINGUISHABLE` / `DIFFERS` / "not comparable: a probability is unavailable").

### Point in time and absence

- Anything describing a match or a moment uses data available at `min(as_of, scheduled_time)`. The stored
  `team_metrics` snapshot is current-state and never describes a past moment.
- Unavailable, unknown and zero are distinct: `null` with a reason or status, never `0` or an omitted key.

### Paths and documentation

- Paths are unversioned (P7-Q6). The contract lock, not a version prefix, is the stability guarantee.
- `/docs` and `/openapi.json` are served.
- Type checking and linting are not configured in this repository. Phase 7 acceptance records report them as
  "not configured", never as passing.

## Decisions after the freeze

`P7_M0_DECISIONS.md` is blob-pinned by the freeze, so later decisions are separate dated files in
`.agent/phase7/decisions/`, following the Phase 6 precedent:

| ID | Date | Decision |
|---|---|---|
| P7-D1 | 2026-10-17 | No future `as_of` on the P7-M3 POST routes (`decisions/P7_D1_NO_FUTURE_AS_OF.md`) |
| P7-D2 | 2026-10-18 | Discovery corrections: playoff matches only once available; `event_type` removed; documentation fixes (`decisions/P7_D2_DISCOVERY_CORRECTIONS.md`) |
| P7-D3 | 2026-10-18 | Strategy corrections: the EPA source envelope on strategy responses; coach observations count only once stored before `as_of` (`decisions/P7_D3_STRATEGY_CORRECTIONS.md`) |
| P7-D4 | 2026-10-18 | Mid-Phase Audit: no route accepts a future `as_of`; `state_province` on `GET /events`; non-nullable strategy model identity (`decisions/P7_D4_MID_PHASE_AUDIT.md`) |
| P7-D7 | 2026-10-18 | Approved by Sven Morais: the canonical playoff label for the pick list's event-level values is `validated_playoff_success` (P6-M5/M7 vocabulary); `validated_playoff` stays reserved for P6 single playoff-match probabilities after PX-2. Relocked (`decisions/P7_D7_PLAYOFF_LABEL.md`) |
| P7-D6 | 2026-10-18 | Phase-Level Audit: scheduled-match strategy and win-probability routes use `min(now, scheduled_time)`; the examples tooling handles `API_PREFIX` (`decisions/P7_D6_PHASE_AUDIT.md`) |
| P7-D5 | 2026-10-18 | Alliance selection corrections: the playoff label states its scope (its naming was decided by P7-D7); PX artifacts tied to the gate records; real qualification-finished and final-rank checks; qualification-roster pool; reach-finals comparison and provenance; draft-state checks (`decisions/P7_D5_SELECTION_CORRECTIONS.md`) |

## Notes for API clients (Phase 8)

**`as_of`.** On every route `as_of` is optional and defaults to now. It is ISO-8601 with an offset: URL-encode `+`
as `%2B`, or use `Z`. It may **not** be in the future: more than 5 minutes ahead is `invalid_as_of` (P7-D1,
P7-D4). Only data available before it is used.

**Check order.** Routes check, in order:
1. request validation (422);
2. their dependencies: the model, then the EPA source (404 `model_not_loaded`, `epa_source_not_loaded`);
3. `as_of` (422 `invalid_as_of`);
4. the resource (404 `event_not_found`, `match_not_found`, `team_not_found`).

So on a machine with no models pinned, an unknown event can answer `model_not_loaded` on a model-backed route and
`event_not_found` on another. Event analysis needs its model only after the switch point, so it checks the model
last.

**The same condition, different codes (by design; handle both):**

| Condition | Win probability (`/predictions/…`) | Match strategy (`/strategy/…`) |
|---|---|---|
| Match has no scheduled time | 422 `insufficient_features` | 422 `match_not_scheduled` |
| Match has no competition level | 200, unvalidated value, `unspecified_context` | 422 `match_context_unknown` (the strategy model cannot choose qualification or playoff) |
| Hypothetical with no stated context | 200, unvalidated value, `unspecified_context` | 422 `validation_error` (`match_context` is required, P7-Q9) |

**Two validation vocabularies.**
- Routes from Phases 3–5 keep top-level `validation_status`, often with `evidence` and `not_validated_reason`.
- Phase 7 results use the `validation` block: `{status, reasons, evidence}`. These are the metrics block, discovery,
  strategy odds, and every `win_probability` object.
- Map `validation_status` to `validation.status`; the reasons and evidence keep their meaning.
- In discovery, `reasons: [canonical_tba_record]` names the source of a canonical record rather than a
  qualifier.

**Not locked.** The 22 `/human-inputs/…` operations (the Phase 5 web app's) are outside the lock (P7-Q4). Whether
to lock them before Phase 8 is decided at P7-M9.

## The contract lock (P7-DM2)

`docs/api_contract_lock.json` holds the normalized contract of every locked operation, every schema those
operations reach, and the `api.contract` building blocks (`scripts/phase7_contract_lock.py`).

- **Locked:** `operationId` (a generated client names its functions after it), parameters, request bodies,
  response statuses and schemas (including an empty one), declared error codes, `deprecated`, and every schema's
  types, properties, required lists, enums, constraints and defaults.
- **Not locked:** titles, descriptions, summaries and examples. Only schema keywords of those names are dropped; a
  property called `summary` is locked like any other.
- **Order is not meaning:** `required`, `enum` and `anyOf` lists are compared as sets.

`tests/test_phase7_contract.py` fails whenever the live application differs from the lock. Every change appends a
dated revision to the file, listing every changed entry. The commands
(`python -m scripts.phase7_contract_lock …`):

| Command | Use |
|---|---|
| `check` | Compare the live application with the lock |
| `lock --reason … OPERATION …` | Add operations. Refused if anything already locked differs |
| `relock --reason …` | Record an additive change (for example a new optional field). A change to an already-locked entry is refused unless `--decision` names an existing decision document and the decision's date |
| `unlock --reason … --decision … OPERATION …` | Remove operations; always needs a decision |

A new code on an already-declared error status counts as a change, because clients must handle every code.

| Locked operations | Locked by |
|---|---|
| `GET /health`, `GET /ready` | P7-M1 |
| `GET /teams/{team_number}/events/{event_key}/metrics`, `GET /teams/{team_number}/events/{event_key}/strength` | P7-M2 |
| `GET /predictions/matches/{match_key}/win-probability`, `POST /predictions/win-probability`, `GET /predictions/events/{event_key}/ranking` (deprecated), `POST /predictions/alliance-synergy` | P7-M3 |
| `GET /events/{event_key}/analysis`, `GET /events/{event_key}/qualification-forecast`, `GET /events`, `GET /events/{event_key}/teams`, `GET /events/{event_key}/matches` | P7-M4 |
| `POST /strategy/matches/{match_key}/assess`, `POST /strategy/matches/{match_key}/recommend`, `POST /strategy/matches/{match_key}/compare`, `POST /strategy/hypothetical/assess`, `POST /strategy/hypothetical/recommend`, `POST /strategy/hypothetical/compare`, `POST /strategy/coach-strategies`, `POST /strategy/coach-observations` | P7-M5 |
| `GET /events/{event_key}/alliance-selection/candidates`, `POST /events/{event_key}/alliance-selection/pick-list` | P7-M6 |
| `GET /matches/{match_key}/pre-match-report` | P7-M7 |
| `GET /matches/{match_key}/briefing` | P9-M4 (P9-Q8), added 2026-10-20 with no change to any entry above; documented in `docs/phase9.md` |

Recorded relocks (changes to locked entries, each with its decision): P7-D2 (`event_type` removed), P7-D3 (`epa` on the strategy responses), P7-D4 (`state_province`; non-nullable strategy model identity), P7-D5 (the pick-list status constant, comparisons, provenance and declared codes), P7-D7 (the canonical playoff label `validated_playoff_success`). The full history is the lock file's `revisions`.

## Locked endpoint contracts

The full request and response schemas are in `/openapi.json`, and their locked form is in
`docs/api_contract_lock.json`. This section gives each endpoint's semantics, which the schemas cannot. Examples
are covered under "Examples (P7-Q4)". Real captures are BLOCKED (environment, P7-Q5), so none exist yet.

**Dependencies at a glance.** Which served components each operation needs; a missing one is the refusal listed
in its errors:

| Operation | Database | EPA source | Model |
|---|---|---|---|
| Team metrics | yes (stored `team_metrics`) | no | no |
| Team strength, alliance synergy, discovery reads | yes | strength and synergy only | no |
| Win probability (both routes) | yes | yes | M6/M7 (`ML_WIN_PROB_MODEL_*`) |
| Ranking (deprecated) | yes | yes | M5 v2 (`ML_RANKING_MODEL_*`) |
| Event analysis | yes | yes | M5 v2 after the switch point |
| Qualification forecast | yes | yes | M6/M7 |
| Match strategy (6 routes) | yes | yes | P6-M10 (`ML_STRATEGY_MODEL_*`) |
| Coach writes | yes | no | no (write token) |
| Alliance-selection candidates | yes | yes | no |
| Pick list | yes | yes | approved P6-M1 ruleset, PX gate records, PX-1/PX-2 (`ML_PX1_*`, `ML_PX2_*`), M5 v2 after the switch |
| Pre-match report | yes | yes | M6/M7 and P6-M10, each optional (an absent part) |

### Team metrics (P7-M2) — `GET /teams/{team_number}/events/{event_key}/metrics`

**Purpose.** One team's stored Phase 3 metrics at one event (`data.metrics.read.look_up_team_metrics`). It reads and
never recomputes.

**Not point in time.** This is the current-state snapshot: it includes every match computed so far. For a past
moment, use the strength endpoint's `as_of`.

**Parameters.** `team_number` is an integer > 0; `event_key` is a TBA event key.

**200 body.** `TeamMetrics`, unchanged:

- `scoring`: Phase 3 statistics. `reliability_score` is the INTERIM attendance ratio.
- `defense_feeding`: scouting aggregates, with their `*_insufficient_data` flags.

It also carries an additive `validation` block (P7-Q13). Each part reuses an existing label and is never
upgraded:

| Part | Status | Reasons |
|---|---|---|
| `scoring` | `descriptive` | `"reliability_score_interim: an attendance ratio (100 * matches_used / matches_scheduled), not a robot-failure measure"` |
| `defense` | `descriptive_definition_pending` (Phase 3 M14 is open) | `"insufficient_data: fewer than 2 scouting observations"` when its flag is set; otherwise none |
| `feeding` | `not_validated` (no feeding data at collection time) | the same insufficient-data reason when its flag is set |

Reasons are exact strings (`ml.views.strength.RELIABILITY_INTERIM`, `INSUFFICIENT_OBSERVATIONS`). Match on their
prefix (`reliability_score_interim`, `insufficient_data`), not on the full text.

`defense_agreement` measures match-to-match variance confounded with scout calibration, not inter-scout agreement:
no (match, team) pair has been rated by two scouts (`docs/metrics_pipeline.md` §9.1). This is a documented caveat,
not a `validation` reason. P7-Q13 derives the block only from the stored flags.

**Missing data.**
- A thin-data team is a 200 with its flags, and nulls for undefined statistics, never `0`.
- A missing object is a 404 with one of four codes:
  - `team_not_found`
  - `event_not_found`
  - `team_did_not_attend`
  - `metrics_not_computed` (the only one worth retrying)

**Errors.** 404 with the codes above; 422 `validation_error` (for example team `0`); 500 `internal_error`.

### Team strength (P7-M2) — `GET /teams/{team_number}/events/{event_key}/strength`

**Purpose.** The P5-M3 view of one team at one event at one moment (`ml.views.strength.build_team_strength`):

- EPA with provenance;
- Phase 3 statistics recomputed point in time;
- auto points;
- defense and feeding.

Every number has its `n` and an uncertainty, or an explicit reason it has none.

**Missing data.** A null value always has its `absent_reason`; nothing is imputed:
- no prior event with EPA: the EPA measures are null, with `withheld_reason` / `absent_reason`
  `withheld_no_prior_event`;
- no completed match before `as_of`: the scoring measures are null with `no_completed_matches_before_as_of`; with
  fewer than the minimum matches, the SD is absent with its own reason;
- no score breakdown: auto points are null with `no_matches_with_a_score_breakdown_before_as_of`;
- fewer than 2 scouting observations: defense and feeding are null with `insufficient_data` (always the case for
  feeding today).

The `TeamMetrics` fields served by the metrics route above are defined in `docs/metrics_pipeline.md`.

**Parameters.**
- `team_number`: an integer ≥ 1.
- `event_key`.
- `as_of` (query, optional): ISO-8601 with a timezone offset. Defaults to now.

**Point in time.** Only data available before `as_of` is used. A later match never changes an earlier view
(tested).

**200 body.** `{strength: TeamStrengthView, epa: EpaSourceInfo}`. The labels are inherited:

| Part | Label |
|---|---|
| EPA, scoring, auto points | `descriptive` |
| Defense | `descriptive_definition_pending` |
| Feeding | `not_validated` |

**Errors.**

| Status | Codes |
|---|---|
| 404 | `epa_source_not_loaded`, `event_not_found`, `team_not_found` |
| 422 | `invalid_as_of`, `epa_source_incomplete`, `epa_source_pending`, `validation_error` |
| 500 | `internal_error` |

### Win probability (P7-M3)

There are two routes, both served by the M6/M7 pair (`win_prob_xgb_calibrated`), whose overall M7 calibration gate
failed:

- `GET /predictions/matches/{match_key}/win-probability`: a real match, with features as of `min(now, scheduled_time)`
  (P7-D6): a past match at its scheduled time, unchanged; an upcoming match from what is known now. `as_of` in the
  response is that moment.
- `POST /predictions/win-probability`: two supplied 3-team alliances at an event.
  - Body: `{event_key, red_team_numbers[3], blue_team_numbers[3], match_context?: "qualification" | "playoff"}`.
  - Query: optional `as_of` (ISO-8601 with an offset; default now; P7-Q7). Features use only data before it.
    - It must not be in the future (P7-D1): beyond a 5-minute clock skew it is refused with `invalid_as_of`, and
      within it, it is treated as now. A future `as_of` would treat an event still in progress as a completed
      prior event.
    - URL-encode a `+` offset as `%2B`, or use `Z`.

**200 body.** The Phase 4 fields are unchanged:
- `match_key` (null for the POST route), `event_key`, `red_team_numbers`, `blue_team_numbers`, `as_of`;
- `probability_scope` (`qualification`, `playoff` or `unspecified`), `competition_level`;
- `validation_status`, `not_validated_reason`;
- `red_win_probability` (the validated value), `unvalidated_red_win_probability`;
- `probability_rounding`, `calibration_status`, `evidence`, `warning`;
- `model_type`, `model_version`, `model_version_tag`, `model`;
- `epa`, and `teams` (per-team EPA provenance: `epa_value_source`, `epa_source_state`, `epa_source_event_key`,
  `epa_withheld_reason`).

Added (P7-Q3): `win_probability`, the same value as a `CalibratedWinProbability`.

**Missing data.** A team without prior EPA keeps the value but makes it unvalidated (`epa_incomplete`). If every
team has no features at all, the result is 422 `insufficient_features`; nothing is predicted from no evidence.

**Gating** (unchanged from Phase 4):

| Case | Validated value | Unvalidated value and reason | Status |
|---|---|---|---|
| EPA-complete qualification match | the rounded value | null | `approximately_calibrated_qualification` |
| Playoff | null | the rounded value, `playoff_scope` | `not_validated` |
| Ad hoc with no stated context | null | the rounded value, `unspecified_context` | `not_validated` |
| Any team without prior EPA | null | the rounded value, `epa_incomplete` | `not_validated` |

Every value is rounded to 0.05 and clipped to [0.05, 0.95]. `validation.reasons` always includes `m7_gate_failed`.
Served values are pinned against their pre-Phase 7 form (`tests/test_phase7_predictions_regression.py`).

**Errors.**

| Status | Codes |
|---|---|
| 404 | `model_not_loaded`, `epa_source_not_loaded`, `match_not_found` (match route), `event_not_found` and `team_not_found` (POST route) |
| 422 | `insufficient_features` (every team has no features at all, or a match has no scheduled time), `epa_source_incomplete`, `epa_source_pending`; on the POST route also `invalid_as_of` and `validation_error` (e.g. not 3 teams per alliance) |
| 500 | `internal_error` |

### Rankings (P7-M3, P7-Q2)

- **Canonical:** `GET /events/{event_key}/analysis` `ordering`, which follows the validated P5-D6 policy: raw EPA
  before the switch point, M5 v2 after. Its contract is locked with event analysis (P7-M4).
- **Deprecated:** `GET /predictions/events/{event_key}/ranking`.
  - It is M5 v2 always, as of the request, labelled `moderate_held_out`. Before an event, M5 v2 ranks worse than
    raw EPA (Spearman 0.5565 vs 0.5955).
  - It is marked `deprecated` in OpenAPI and stays unchanged for its consumers (`scripts/verify_d18_production.py`,
    `scripts/verify_p5_live_adoption.py`). It gets no new features (no `as_of`).
  - 200 body: `event_key`, `as_of`, `validation_status` (`moderate_held_out`), `evidence`, `model_type`,
    `model_version`, `model_version_tag`, `model`, `epa`, and `rankings[]` sorted strongest first. Each entry is
    `{rank, team_number, predicted_rating, epa_value_source, epa_source_event_key, epa_withheld_reason}`.
    `predicted_rating` is a relative score, so only the order is meaningful.
  - Missing data: every rostered team is ranked. A team without prior EPA is still rated from its other features,
    with `epa_withheld_reason` set.
  - Errors: 404 `model_not_loaded`, `epa_source_not_loaded`, `event_not_found`; 422 `epa_source_incomplete`,
    `epa_source_pending`; 500.

### Alliance synergy (P7-M3) — `POST /predictions/alliance-synergy`

**Request.** Body `{event_key, team_numbers[3]}`, plus an optional `as_of` query parameter (P7-Q7). The same rules
apply as on the win-probability POST: not in the future (P7-D1), and a `+` offset is URL-encoded.

**Response.** The `ml.synergy.score.alliance_synergy` result. It is labelled `not_validated_against_outcomes` and
needs no model. The fields:
- `event_key`, `team_numbers`, `as_of`, `validation_status`;
- `overall_score`: the weighted combination of the available terms, null when none is available;
- `role_fit_term`, with `role_fit_axes_used`;
- `scoring_distribution_term`, with `scoring_distribution_axes_used`;
- `defense_feeding_coverage_term`, with `defense_feeding_coverage_present_count` (0 to 6 scouting values present);
- `confidence` (0 to 1): the mean of the three components' completeness (axes used, and scouting values present out of 6);
- `epa`, and `teams` (EPA provenance).

**Missing data.** A term whose inputs are absent is null and is left out of `overall_score`; nothing is imputed.
With no scouting data (the usual case today), the coverage term is null, the present count is 0, and `confidence`
falls accordingly.

**Errors.** 404 `epa_source_not_loaded`, `event_not_found`, `team_not_found`; 422 `invalid_as_of`,
`epa_source_incomplete`, `epa_source_pending`, `validation_error`; 500.

### Event analysis (P7-M4) — `GET /events/{event_key}/analysis`

**Purpose.** The P5-M4 analysis of one event at `as_of` (query, optional, ISO-8601 with an offset, default now). It
is the **canonical rankings surface** (P7-Q2). The service is `ml.views.event_analysis.analyze_event`, extracted
unchanged by P7-M4 and reused by the alliance-selection pick list (its ordering and features).

**200 body.**

| Part | Content | Status |
|---|---|---|
| `ordering` | The frozen policy: raw EPA before the event switch point, M5 v2 after it; one model per ordering. A team with no prior EPA ranks last with a null score, never a fabricated one | `validated` (raw EPA, mean Spearman 0.5955) or `validated_as_measured` (M5 v2, +0.0183, CI [0.0082, 0.0288]) |
| `captain_candidates` | The ordering's top 8 | `validated_as_measured`; no improvement over raw EPA is claimed |
| `strongest_teams` | The same top 8 | No playoff or alliance-success probability is served |
| `team_comparison` | Every attending team's strength view | `descriptive`, with the INTERIM reliability caveat |
| `epa`, `ranking_model_sha256` | EPA source provenance; the M5 v2 artifact, or null under raw EPA | — |

Final rankings and alliances are never inputs.

**Errors.**

| Status | Codes |
|---|---|
| 404 | `model_not_loaded` (the switch has passed and M5 v2 is not pinned), `epa_source_not_loaded`, `event_not_found` |
| 422 | `invalid_as_of`, `epa_source_incomplete`, `epa_source_pending` |
| 500 | `internal_error` |

### Qualification forecast (P7-M4) — `GET /events/{event_key}/qualification-forecast`

**Purpose.** P5-M5 forecasts for every qualification match, and each team's expected qualification record, at
`as_of`. The service is `ml.views.qualification_forecast.forecast_event_qualification`, extracted unchanged by P7-M4.
Each match's features are built at `min(as_of, scheduled time)`, so a played match keeps its pre-match forecast.

**200 body.**
- `matches[]`: the M6/M7 gating as above. A match is validated only when it is EPA-complete; otherwise it gets
  `epa_incomplete`. Each match carries the same `win_probability` object (P7-M3).
- `teams[]`:
  - expected wins = Σ q, rounded to 0.1;
  - a central 80% Poisson-binomial range, always `not_validated` (measured coverage 0.8532, outside
    [0.75, 0.85]);
  - a record label, `not_validated` when the team's schedule includes an EPA-incomplete match.
- `statbotics_week`, and `low_confidence` for weeks 1–3.
- Qualification only. There is no ranking-point projection.

**Errors.**

| Status | Codes |
|---|---|
| 404 | `model_not_loaded`, `epa_source_not_loaded`, `event_not_found` |
| 422 | `invalid_as_of`, `epa_source_incomplete`, `epa_source_pending` |
| 500 | `internal_error` |

The P7-M4 extraction is pinned by `tests/test_phase7_event_regression.py`. That test holds a golden of both routes
captured before the extraction, with feature-dependent model stubs, and the extracted services reproduce it exactly.

### Qualification forecast probabilities (P7-M3)

Each `matches[]` entry of `GET /events/{event_key}/qualification-forecast` also carries `win_probability`, the same
object as above, for the same value. The forecast's own contract is locked with event analysis (P7-M4).

## Examples (P7-Q4)

Captured examples live in `docs/api_examples/`, one JSON file each (`api/examples.py` documents the format). Each is
labelled `real`, `refusal_only` or `synthetic`, and records the environment it was captured in. The OpenAPI
document shows them under their operations. The P7-M8 capture script writes them. Real captures need the P7-Q5
environment of record.

**Scope (P7-Q4).** Every locked operation except the probes: 22 operations (`api.examples.examples_scope`). The
human-input operations are not locked, and have no examples.

**What each operation needs** (`api.examples.missing_examples`):
- a `real` success and a `real` refusal;
- for the refusal-only pick list (P7-Q1): a `refusal_only` refusal plus a `synthetic` success, the latter written
  by its own test.

**Contract test (`tests/test_phase7_examples.py`).** Every committed example must:
- use a status its operation declares;
- validate against the route's response model (the schema the lock pins), or for a refusal, be the error envelope
  with a declared code;
- if `real`, come from the environment of record.

The completeness check is a strict xfail while P7-M8 is BLOCKED (environment). It fails as soon as the examples
exist and the marker is still there.

**Capture runbook (in the P7-Q5 environment of record only):**
1. Pin the three models with their recorded sha256s: `ML_RANKING_MODEL_VERSION_TAG` / `_SHA256`, and the same for
   `ML_WIN_PROB_MODEL_…` and `ML_STRATEGY_MODEL_…`. Configure the production EPA source, and point `DATABASE_URL` at
   the serving-dump copy (migrations through 0011).
2. Choose real keys for one past event mid-way through it, and fill every `<<KEY>>` of
   `scripts/phase7_examples_plan.template.json`:

       python -m scripts.phase7_capture_examples --plan scripts/phase7_examples_plan.template.json \
           --environment-name <name> --as-of <ISO time with offset> --set EVENT=... --set QUAL_MATCH=... ...

   The script refuses unless the environment is complete. It writes nothing unless every capture has its planned
   status and matches its contract. Each file records the environment's fingerprint: models, EPA source, database
   migration and sizes, git commit, as_of. The two coach-write successes store a row in that database copy; the
   write token is sent, never recorded.
3. Write the pick list's synthetic success:

       STRATAI_SYNTHETIC_EXAMPLES_DIR=docs/api_examples pytest \
           "tests/test_phase7_alliance_selection_api.py::test_the_synthetic_success_path_serves_the_full_shape_without_raw_precision"

4. Remove the xfail marker from `test_every_operation_in_scope_has_its_required_examples`, and run the suite.

`--allow-incomplete-environment` gives a dry run outside the environment of record. It never writes into
`docs/api_examples/`, and its examples record `environment_of_record: false`, so they can never pass the contract
test.

## Endpoints owned by Phase 7

Endpoints Phase 7 adds are listed here as `METHOD /path` with their contracts as each milestone builds them.

- `tests/test_metrics_docs_contract.py` reads this section, which excludes these paths from the Phase 3 page's
  checks.
- `tests/test_phase7_contract.py` pins it: every entry is live, is served by a Phase 7 route module
  (`api.routes.strategy`, `alliance_selection`, `pre_match_report`, `discovery`), and is not a route that existed
  before Phase 7. Every Phase 7 route is listed.

### Match strategy (P7-M5, P7-Q9, P7-Q10, P7-Q11)

`api/routes/strategy.py`, served by the P6-M11 engine (`ml.strategy.engine`) over the P6-M10 model, with contexts
built by `ml.strategy.service`.

**Endpoints.**
- Scheduled match, evaluated at `min(now, scheduled_time)` (P7-D6): a past match at its scheduled time; an upcoming
  match now, never at its future time. `context.as_of` is that moment:
  - `POST /strategy/matches/{match_key}/assess`: body `{side, strategy, opponent_strategy?}`.
  - `POST /strategy/matches/{match_key}/recommend`: body `{side, opponent_strategy?}`.
  - `POST /strategy/matches/{match_key}/compare`: body `{side, first, second, opponent_strategy?}`.
- Hypothetical alliance: the same three, with the body adding
  `{event_key, red_team_numbers[3], blue_team_numbers[3], match_context}`:
  - `POST /strategy/hypothetical/assess`
  - `POST /strategy/hypothetical/recommend`
  - `POST /strategy/hypothetical/compare`

  `match_context` (`qualification` | `playoff`) is required; omitting it is a 422. The optional `as_of` (default
  now) must not be in the future (P7-D1).
- Coach writes, which need the write token (header `X-StratAI-Write-Token`; not declared as an OpenAPI parameter,
  because the body is landed raw before any validation):
  - `POST /strategy/coach-strategies`: body `{event_key, match_key?, author, strategy}`. The success is **201** with
    `{event_key, match_key, strategy, strategy_sha256, origin: "human_entered", author, created_at}`.
  - `POST /strategy/coach-observations`: body `{event_key, team_number, kind, component?, observed_at, observer}`.
    - `kind` is `component_unavailable` (which requires `component`: `auto`, `teleop` or `endgame`) or
      `robot_unavailable` (no `component`).
    - `observed_at` is ISO-8601 with an offset.
    - The success is **201** with `{observation}`, the validated observation.
  - Both bodies are a free JSON object in OpenAPI, because they are stored raw before validation. Their schema is
    the `Strategy` and `CoachObservation` models (`ml/strategy/representation.py`). An invalid object is 422
    `invalid_coach_input`, and stays recorded.

**The strategy object** (`Strategy`, vocabulary `p6-strategy-v1`): `{vocabulary?, robots: [3 × RobotPlan]}`.
- Each `RobotPlan` is `{team_number, role, components, defense_target?, feed_target?}`.
- `role` is `scoring` (the default), `defense` (needs `defense_target`, an opponent) or `feeding` (needs
  `feed_target`, an ally).
- `components` is a subset of `auto`, `teleop` and `endgame` (default: all three). Teleop needs the `scoring` role.
- The three robots are distinct. `side` is `red` or `blue`: the alliance the strategy is for.

**One model, one path (P6-DM2).** Every probability comes from the P6-M10 model through `StrategyEngine.assess`.
The AI path (`recommend`) and the coach paths (`assess`, `compare`) differ only in where the strategy came from,
which no evaluation input carries. Both see the identical context, including the same coach observations. This is
tested over HTTP: the recommendation, its alternatives and the baseline, re-assessed as a coach would submit them,
get identical odds. Defects planted in the HTTP layer (one route re-rounding, relabelling or dropping a reason; one
route served a different model) are caught.

**Odds.** `odds` is `StrategyOdds`: the P6-A5 display string (`<5%`, `>95%` or a 0.05-step percentage), plus the
engine's `validation.status` and `reasons`. Every probability is `not_validated`:

| Case | Reasons |
|---|---|
| The baseline | `p6_m10_gate_failed` |
| Any other strategy | `strategy_effect_unmeasured`, plus `defense_effect_insufficient_data`, `feeding_effect_insufficient_data` and `coach_observation_effect_unmeasured` as they apply |
| A playoff context | 200 with `display: null` and `playoff_model_unavailable` |
| Missing inputs | 200 with `display: null`, status `insufficient_data` and `missing_input:<team>:<field>` |

No raw probability, mean difference, sigma, component mean or difference is ever served (R2, R13). Strategies are
returned as given, and roles and assignments are in the strategy itself.

**Response bodies.**
- **Assess:** `assessment` is `{strategy, opponent_strategy, odds}`: the given strategy's odds against the
  opponent's (the baseline unless supplied).
- **Recommend:**
  - `recommended`, `alternatives` (at most 5) and `baseline`, each as `{strategy, opponent_strategy, odds}`;
  - `vs_baseline_label`;
  - `candidates_evaluated` (21,952 for one side);
  - `selection_note`: the maximum of many model estimates is not an unbiased probability (P6-Q10);
  - `unavailable_reasons` when no probability exists.
- **Compare:** `first` and `second` as `{strategy, odds}`, plus `label`, which is one of:
  - "indistinguishable at model resolution";
  - "differs by at least one display step under the model (not a claim that either strategy is better)";
  - "not comparable: a probability is unavailable".
- **Every response** carries `context`:
  - `match_key`, `event_key`, `as_of`, `match_context`, `competition_level`;
  - the teams;
  - `coach_observations_applied` and `coach_observations_invalid_ignored`.

  It also carries `model`: type, version, version tag, artifact sha256, and the spec sha256.

**Model pin.** `ML_STRATEGY_MODEL_VERSION_TAG` and `ML_STRATEGY_MODEL_SHA256` (both required) are loaded only
through `load_registered_strategy_model`, so the served baseline reason is `p6_m10_gate_failed`. Any of these gives
`model_not_loaded`, never a startup crash:
- the version tag is unset;
- the sha256 is unset or wrong;
- the artifact is unreadable or malformed.

**EPA source and coach observations (P7-D3).**
- Every strategy response carries `epa` (`EpaSourceInfo`), as every EPA-backed route does: the source, whether it
  is the evaluated configuration, the P5-D3 adoption, and `live_refresh_not_yet_validated`.
- A coach observation enters a context only once it was both observed (`observed_at`, caller-asserted) and
  stored (`raw_source_payloads.ingested_at`) before `as_of`.
- Hypothetical alliances need six distinct teams (a 422 otherwise).

**Errors.**

| Route | 404 | 409 | 422 |
|---|---|---|---|
| Scheduled match | `model_not_loaded`, `epa_source_not_loaded`, `match_not_found` | `alliance_incomplete`, `mixed_season_scale` | `match_not_scheduled`*, `match_context_unknown`*, `invalid_strategy`, `epa_source_incomplete`, `epa_source_pending`, `validation_error` |
| Hypothetical | `model_not_loaded`, `epa_source_not_loaded`, `event_not_found`, `team_not_found` | `mixed_season_scale` | `invalid_as_of`, `invalid_strategy`, `epa_source_incomplete`, `epa_source_pending`, `validation_error` |
| Coach writes | — | — | `invalid_coach_input`, `validation_error` (403: `writes_disabled`, `write_not_authorized`) |

Every route also declares 500.

- `match_not_scheduled` and `match_context_unknown` (*) are new codes, listed per R1. `match_context_unknown` is
  for a match with no competition level: serving such a match as a "playoff" would mislabel it.
- `mixed_season_scale` is raised only where the engine itself refuses, after its playoff and missing-input checks.
- A malformed strategy body is the request model's 422 `validation_error`.

**Coach writes (P7-Q10).**
- `X-StratAI-Write-Token`: fail closed when unset; constant-time comparison; one shared secret with no per-user
  identity, rotation or rate limiting; same-origin only (not in CORS `allow_headers`).
- The raw JSON body is landed in `raw_source_payloads` before validation, so a rejected submission
  (`invalid_coach_input`) stays recorded. A 403 or a non-object body is not stored.
- `author` and `observer` are caller-asserted strings.

**Latency (P7-Q11, R19).** The budget was pre-registered as 10 s per recommend request, before any measurement. On
Sven's machine, with a synthetic model:
- end to end over HTTP (the database context, EPA provider, observation load and search), with no coach
  observations: 1.86 s;
- the engine alone (`scripts/phase7_m5_recommend_latency.py`) grows linearly with the coach observations at the
  event, because every one enters the context and is checked for every candidate:

| Observations | Median | Max |
|---|---|---|
| 0 | 1.27 s | 1.35 s |
| 25 | 2.16 s | 2.21 s |
| 100 | 4.43 s | 4.58 s |
| 300 | 8.77 s | 8.78 s |

These are within budget, so the latency is documented and there is no asynchronous endpoint. **Known risk:** past
about 300 observations at one event, a recommend request would exceed the budget. Nothing bounds the count, and
any write-token holder can add observations. The fix, restricting a context's observations to its six teams,
changes the engine's labelling rule and needs its own decision (P7-D3). A measurement on the model of record
belongs in the environment of record (P7-Q5).

**Coach write limits (documented, not enforced):**
- There is no body-size limit.
- `event_key` and `match_key` are stored as given, not checked against the canonical tables.
- An observation may name any team, and any `observed_at`. It is used only once both observed and stored before
  the moment being evaluated (P7-D3), so a back-dated submission never changes an earlier evaluation.
- Malformed JSON is a 422 before the token check, and nothing is stored either way.

### Alliance selection (P7-M6, P7-Q1)

`api/routes/alliance_selection.py`, served by `ml.playoffs.service` over the P6-M6/M7 engine
(`ml.playoffs.selection`).

**What this means today.** The 2024–2026 rulesets await review and the PX-1/PX-2/PX-4 gates have not run, so the
pick list returns its real refusal (`not_approved`). **Real alliance-selection output is deferred with P6-DM1**
(P7-Q1). P7-DM1 reports alliance selection as "callable, refusal only". Candidate profiles work today.

- `GET /events/{event_key}/alliance-selection/candidates` serves the P6-M6 factor profile of every team on the
  event's qualification roster (teams in a scheduled qualification match; a playoff-only row is not a candidate).
  - **Factors:** `scoring_epa`, `average_score`, `reliability`, `consistency`, `defense`, `feeding`, `synergy`,
    `role_compatibility`. Each is `{value, n, validation}`, straight from its source, with the engine's own status.
    An absent value is null with its reason; defense and feeding are never imputed. `reliability` carries the
    `reliability_score_interim` reason (an attendance ratio, not a robot-failure measure).
  - **Query:**
    - `as_of` is optional and may not be in the future. It defaults to the event's selection moment (one minute
      after its latest scheduled qualification match), or now while that is still ahead; `as_of_source` says which.
    - `configuration` is optional: three distinct qualification-roster team numbers. Its members get `synergy` and
      `role_compatibility` (`not_validated_against_outcomes`); every other team reports them `insufficient_data`
      (`alliance incomplete`).
  - **Errors:** 404 `epa_source_not_loaded`, `event_not_found`, `team_not_found`; 409 `selection_time_unavailable`
    (no scheduled qualification match; new code); 422 `invalid_as_of`, `epa_source_incomplete`, `epa_source_pending`,
    `validation_error`; 500.
- `POST /events/{event_key}/alliance-selection/pick-list` ranks every available pick for one seed's turn by P(the
  alliance wins the event) (P6-A2). P(reach finals) is reported alongside.
  - **Body:** `{seed, alliances[] (by seed, captain first; [] if not formed), declined[], turns_taken}`.
  - **Before the steps:** an unknown event is 404 `event_not_found`. A malformed body is 422 `validation_error`.
    Every route also declares 500 `internal_error`.
  - **Runs only when every check passes, in this order (R4, P7-D5).** The first failure sets the refusal:

    | Step | Check | Refusal (all 409 unless noted) |
    |---|---|---|
    | 1 | An approved P6-M1 ruleset for the season (no ruleset table means none was approved) | `not_approved`, `storage_integrity` (sha256 mismatch, or a stored ruleset that fails its schema) |
    | 2 | The event's rules | `wrong_season`, `event_excluded` |
    | 3 | The PX gates: the `passed` field (the JSON `true` only) of the write-once records `p6_m2_px1.json`, `p6_m3_px2.json`, `p6_m5_px4.json`; a missing or malformed record means not passed | `playoff_models_not_accepted` (new code) |
    | 4 | Inputs at the selection moment: every scheduled qualification match scored and the moment passed; final ranks fetched no earlier than the last qualification match's scheduled time and its last result payload, covering the qualification roster; the PX-1 model and PX-2 calibrator pinned, **and named by sha256 in the gate records**; the EPA source; the P5-M4 ordering (M5 v2 after the switch), with features for every ranked team | `selection_time_unavailable`, `rankings_unavailable`, 404 `model_not_loaded`, `playoff_models_not_accepted`, 404 `epa_source_not_loaded`, 422 `epa_source_incomplete`, 422 `epa_source_pending`, `playoff_inputs_insufficient` |
    | 5 | The engine, then the draft state | `not_covered` (no alliance-count rule or bracket for the roster), `not_established`, `not_supported`, `infeasible`, `invalid_state` (the wrong number of alliances; an unknown team; a declined team on an alliance where the rules forbid it, or `not_established` when the declined-captain rule is null; `turns_taken` beyond the draft; an alliance size that does not match its turns; a captain listed before its seed's turn, or one the captain rule would not give; not this seed's turn; a team twice across alliances is 422 `validation_error` from the body), and `playoff_inputs_insufficient` (PX-1 lacks an input or an alliance is outside its 3-team domain; the engine never imputes; new code) |

  - **200 body:**
    - `ranked[]`: each pick's predicted `configuration`, and `win_event` and `reach_finals` as display strings
      (P6-A5). It also carries `vs_next_label` and `vs_next_reach_finals_label` (the display rule's comparisons with
      the next candidate; null with `vs_next_reason` for the last), and the pick's `profile`;
    - `alternatives[]`: up to 5 distinct feasible configurations, never padded (P6-A7), with `alternatives_note`;
    - `evaluated_fields`, `notes`, `epa`, and:
      - `models`: the PX artifact sha256s and `ranking_model_sha256` (null when the ordering is raw EPA);
      - `provenance`: `ruleset_sha256`, `ruleset_variant` and `ordering_policy`.
    - `probability_status` is `validated_playoff_success` (P7-D7: the P6-M5 / P6-M7 label for event-level values;
      `validated_playoff` is reserved for P6 single playoff-match probabilities after PX-2). It is set only because
      the PX-4 record passed, and never comes from a caller.
      - Every displayed value states its scope in `validation.reasons`: `px4_scope` and `predicted_field_not_validated`.
      - Its `validation.evidence` is the PX-4 record.
    - No raw probability, difference or margin is served (R2).
  - **Pins:** `ML_PX1_VERSION_TAG`, `ML_PX1_SHA256`, `ML_PX2_CALIBRATOR_PATH` and `ML_PX2_CALIBRATOR_SHA256`, all
    required. Every file is sha256-checked before it loads, and the PX-1 file must be a `playoff_px1` model.
  - **Carried risk (P7-D5).** `scripts/phase6_playoff_track.py` writes no artifact hash into the PX records today.
    Even if those gates later pass, the pick list keeps refusing until a record binds the hashes.
  - **Pool policy.** The selection pool is the qualification roster. P6-M8's `run_m8` used every team with
    features; for historical events with full rosters the two coincide.

The success path is tested only against a **synthetic** approved ruleset, synthetic ranks, stub playoff models and
**synthetic** PX gate records in a temporary directory. That proves the wiring, the checks and the shape, and is not
evidence about any real event.

### Pre-match report data (P7-M7, P7-Q12) — `GET /matches/{match_key}/pre-match-report`

`api/routes/pre_match_report.py`, served by `ml/views/pre_match_report.py`. One structured aggregate per scheduled
match, which a Phase 8 report or a Phase 9 formatter can render without calling the engines again. Hypothetical
matches are served by the strategy routes, not by the report.

- **The moment.** Every part is taken at one moment, `min(as_of, scheduled_time)`. `as_of` is optional (default
  now) and may not be in the future (P7-D4). `as_of_source` says which applied: `scheduled_time` (the default for a
  past match), `requested` (an earlier `as_of`) or `now` (a match still ahead). Only point-in-time sources are read;
  the stored `team_metrics` snapshot is never read, so later matches change no field (tested).
- **Parts, each an existing engine output:**

  | Field | Source | Label |
  |---|---|---|
  | `teams[]` | `build_team_strength` (P5-M3), the same view as the strength route (`/teams/{team_number}/events/{event_key}/strength`, P7-M2) at the moment; `strength.epa` carries the EPA components (auto / teleop / endgame) with provenance | `descriptive`, with `reliability_score_interim` |
  | `synergy[]` | `alliance_synergy` (Phase 4 M9), one per alliance; null with `alliance_incomplete` unless the alliance has three teams | `not_validated_against_outcomes` |
  | `win_probability` | The M6/M7 model, gated exactly as the match win-probability route (`/predictions/matches/{match_key}/win-probability`, P7-M3); one evaluation (`api.win_probability.evaluate_m6m7`) serves both. At the scheduled time (as_of omitted or later) the object is identical to that route's `win_probability` (tested); with an earlier `as_of` it is taken at that moment, while that route always uses the scheduled time | `CalibratedWinProbability` |
  | `strategy` | `StrategyEngine.recommend` with the P6-M10 model for each side, through `context_for_match` at the moment; at the scheduled time each side equals the scheduled-match recommend route (`/strategy/matches/{match_key}/recommend`) (tested; shapes from `api.strategy_shapes`); alternatives are not included. The roles are those of the recommended and baseline strategies | `not_validated`, as the strategy routes serve it (P7-A7: never in the same field as the M6/M7 value) |
  | `not_produced` | None: `strengths_and_weaknesses`, `defensive_threats`, `key_risks`, `predicted_flow`, `critical_matchups`, `key_success_factors` are each `{value: null, reason: not_produced_by_any_engine, semantics}` | — |

- **A missing part is an explicit absence, never a substitute.** Each absent part has `absent_code` (a fixed
  vocabulary, to match on) and `absent_reason` (the same in words).
  - `win_probability.value` is null with `absent_code` when the M6/M7 model is not loaded (`model_not_loaded`)
    or no team has any feature (`insufficient_features`).
  - `strategy` has no `sides` and an `absent_reason` when the P6-M10 model is not loaded, the match has no level
    (`match_context_unknown`), an alliance is not three teams (`alliance_incomplete`) or the season scales differ
    (`mixed_season_scale`).
  - A playoff match is served as the engines serve it: M6/M7 unvalidated (`playoff_scope`) and strategy odds null
    (`playoff_model_unavailable`).
  - Defense and feeding are null with `insufficient_data` when the scouting observations are too few.
- **Errors:** 404 `match_not_found`, `epa_source_not_loaded`; 422 `match_not_scheduled`, `invalid_as_of`,
  `epa_source_incomplete`, `epa_source_pending`; 500.
- **No generated text.** Every string is an engine label, an identifier or a documented constant; the report
  modules import no LLM or HTTP client (tested). Derivation rules for the unproduced items need a dated decision
  (P7-Q12).
- **Cost.** The report runs two full strategy recommendations (one per side) and builds each team's features
  three times (the match row, the strength view, the strategy context). It costs somewhat more than twice a P7-M5
  recommendation, and grows with the event's coach observations in the same way (M05_ACCEPTANCE.md).
- **Inherited, unchanged:** a qualification match with a 2v3 roster and full EPA gets a validated M6/M7 value,
  because M7's population rule needs only two non-empty alliances (the predictions route behaves the same).

### Discovery reads (P7-M4, P7-Q8)

`api/routes/discovery.py`, served by `ml/views/discovery.py`. These are read-only views of the canonical tables,
and each response carries `validation: {status: descriptive, reasons: [canonical_tba_record]}`.

- `GET /events` lists the events of a season.
  - `season` (query, required, ≥ 1992) is required so the list stays bounded.
  - 200: `{season, validation, events[]}`, ordered by start date then key. Each event has `event_key`, `season`,
    `name`, `start_date`, `end_date`, `city`, `state_province` (P7-D4) and `country`. A season with no events gives an empty
    list. (`event_type` was removed by P7-D2: nothing writes it.)
  - Errors: 422 `validation_error`; 500.
- `GET /events/{event_key}/teams` is the event's roster: every team rostered into at least one match.
  - It is `ml.features.roster.list_teams_at_event`, the roster every analysis uses.
  - It includes teams that appear only in playoff matches (backup robots). The alliance-selection pool is narrower: the
    qualification roster (P7-D5). A playoff-only team from this list is `team_not_found` as a candidate
    configuration member and `invalid_state` in a pick-list draft state.
  - 200: `{event_key, validation, teams[]}`. Each team has `team_number`, `name`, `city`, `state_province`,
    `country` and `rookie_year`; a team missing from `teams` keeps its number with null details.
  - Errors: 404 `event_not_found`; 422 `validation_error` (declared because FastAPI would otherwise document its
    own 422; a path segment cannot actually fail); 500.
- `GET /events/{event_key}/matches` returns the matches **available at `as_of`** (P7-D2):
  - the qualification schedule always, since it is published before the event;
  - a playoff match only once it was scheduled before `as_of`, since its alliances are the selection outcome.
  - `as_of` (query, optional, ISO-8601 with an offset, default now).
  - 200: `{event_key, as_of, validation, matches[]}`.
    - Ordered by scheduled time, then qualification before playoffs, then set and match number; untimed
      qualification matches come last.
    - Each match has `match_key`, `competition_level`, `set_number`, `match_number`, `scheduled_time`,
      `red_team_numbers` and `blue_team_numbers`.
  - Each match also has `result: {score_red, score_blue, winning_alliance}`.
    - `winning_alliance` is `red`, `blue` or `tie`, and null only when the record has none.
    - The result is shown only for a match scheduled before `as_of` that was played. Otherwise `result` is null and
      `result_withheld_reason` is one of `not_scheduled_before_as_of`, `no_scheduled_time` or `not_played`.
  - This is the feature assembler's own availability rule (`scheduled_time < as_of`), with its limits:
    - `scheduled_time` is the planned time, so a late match's result can show between its scheduled and real time;
    - a result is the score as stored now, which may include later corrections.
  - Errors: 404 `event_not_found`; 422 `invalid_as_of`; 500.

## Contract-test changes

Each deliberate change to an earlier phase's contract test, with its date and reason:

| Date | Test | Change | Reason |
|---|---|---|---|
| 2026-10-17 | `tests/test_phase6_contract.py::test_no_phase6_http_routes_exist` | Replaced by `test_phase6_capability_routes_live_only_in_the_phase7_modules`: a strategy, alliance-selection, pick-list or playoff path may exist only in `api.routes.strategy` (`/strategy/…`), `api.routes.alliance_selection` (`/events/{event_key}/alliance-selection…`) or `api.routes.pre_match_report` (`/matches/{match_key}/pre-match-report`), each only within its own path family, and no sub-application may be mounted | P7-A5 / R8: the P6-A1 boundary (engines in Phase 6, HTTP in Phase 7) is kept, with Phase 7 now the owner of those routes |
| 2026-10-17 | `tests/test_api_foundation.py::test_exactly_the_intended_endpoints_are_exposed` | The pinned list became `PRE_PHASE7_PATHS` (unchanged) plus `PHASE7_PATHS`, which each family milestone extends | One list of the earlier phases' routes, also used to stop Phase 7 from claiming one of them |
| 2026-10-17 | `tests/test_metrics_api.py::test_the_response_carries_every_definition_of_done_field` | The pinned top-level key set gains `validation` | P7-Q13: the additive validation block on the metrics route (P7-M2) |
| 2026-10-17 | `tests/test_qualification_forecast_api.py` (`STUB` served model) | The stub gains `identity()`, mirroring `api.ml_loading.ServedModel` | P7-M3: the forecast now names the served model in its probability object |
| 2026-10-17 | `docs/ml_models.md` §9 | Records the additive P7-M3 changes (`as_of`, `win_probability`, the ranking deprecation, the display rule's new home) and documents `invalid_as_of` | Declared codes must be documented (`tests/test_ml_models_docs_contract.py`) |
| 2026-10-17 | `docs/ml_models.md` (error codes) | Documents `epa_source_pending`, which the prediction routes have returned since the P5-D3 live source | Declaring every route's codes (P7-M1 (f)) exposed the gap; `tests/test_ml_models_docs_contract.py` now holds it |
| 2026-10-17 | `tests/test_metrics_docs_contract.py` (documented endpoints; INTERIM caveat) | Paths listed in this page's "Endpoints owned by Phase 7" section are excluded, as Phase 5's are | P7-M1 (e): Phase 7 endpoints are documented here, and their INTERIM caveat is checked by `tests/test_phase7_contract.py` |
| 2026-10-18 | `tests/test_api_foundation.py` `PHASE7_PATHS` | Adds `/events`, `/events/{event_key}/teams` and `/events/{event_key}/matches` | P7-M4: the discovery reads (P7-Q8) |
| 2026-10-18 | `tests/test_phase6_contract.py`, `tests/test_phase7_contract.py` (route walks) | Walk routes with `tests/phase7_support.api_routes_checked`, proven complete against OpenAPI; non-vacuity checks added | FastAPI 0.141 wraps included routers, so the previous walks found no routes and passed vacuously (erratum in `M01_ACCEPTANCE.md`) |
| 2026-10-18 | `tests/test_api_foundation.py` `PHASE7_PATHS` | Adds the eight `/strategy/…` paths | P7-M5: match strategy and the coach writes (P7-Q9, P7-Q10) |
