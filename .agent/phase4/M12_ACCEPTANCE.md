# Phase 4 — Milestone 12 Acceptance: ML API Endpoints

## Completed Milestone

Milestone 12 of `docs/P4Milestones.md`'s 13-milestone plan: four ML prediction
endpoints extending the Phase 3 `api/` package additively.

  - `GET /predictions/matches/{match_key}/win-probability` — win probability for a
    real, scheduled match.
  - `POST /predictions/win-probability` — win probability for two supplied
    (possibly hypothetical) alliances.
  - `GET /predictions/events/{event_key}/ranking` — predicted team ranking for an
    event.
  - `POST /predictions/alliance-synergy` — alliance synergy score for three
    supplied teams.

**Accepted in full.** Like M8/M9/M10, this milestone's own "Success looks
like"/"What to test" criteria (happy path, insufficient-features, unknown
team/event, model-not-loaded, symmetry-through-API, schema validation) are all
about the API layer's own wiring and error handling — verifiable end-to-end with
real (if separately, clearly synthetic) fit models registered into a temporary
registry, exactly as M8's audit and M10's registry tests already established.
**Not implied by this acceptance:** no model is actually pinned in the real,
deployed configuration — `Settings.ml_ranking_model_version_tag` /
`ml_win_prob_model_version_tag` both default to `None`, which is this project's
honest current state (M4-M7's real, dated backtest numbers are still blocked on
Statbotics). Until an operator points those settings at a real, accepted,
registered model, the two model-backed endpoints will correctly answer
`model_not_loaded` in production — that is this milestone working as designed,
not a gap in it.

## Files Modified/Created

- `api/routes/predictions.py` (new) — the four endpoints, request/response
  schemas, error-code helpers.
- `api/ml_loading.py` (new) — startup-time pinned-model loading.
- `api/dependencies.py` (modified, additive) — `get_ranking_model`/
  `get_win_prob_model`/`get_ranking_model_manifest`/`get_win_prob_model_manifest`.
- `api/app.py` (modified, additive) — loads the two pinned models once at
  startup, mounts the new router.
- `data/config.py` (modified, additive) — `ml_registry_dir`,
  `ml_ranking_model_version_tag`, `ml_win_prob_model_version_tag`.
- `ml/features/roster.py` (new) — `event_exists`, `get_event_season`,
  `get_match_event_and_scheduled_time`, `list_teams_at_event`: small,
  additive lookups the API layer needs that Milestone 1's assembler does not
  otherwise expose, deliberately NOT reusing `data.metrics.compute`'s private
  equivalent (Phase 3 file, "do not modify without coordination").
- `ml/features/assembler.py` (modified) — `_build_team_features` promoted to
  public `build_team_features`, mirroring the established
  `parse_tba_team_number` precedent for a genuinely-reused private helper; no
  behavior change.
- `tests/test_api_predictions.py` (new) — 18 tests.
- `tests/test_api_foundation.py` (modified) — the Phase 3 "exactly these
  endpoints" contract pin updated to include the four new paths.
- `tests/test_metrics_docs_contract.py` (modified) — two Phase 3 docs-contract
  tests scoped to explicitly exclude the new `/predictions/*` paths, which
  belong to a future `docs/ml_models.md` (Milestone 13), not
  `docs/metrics_pipeline.md` — see Issues Found below.

## Architectural Decisions

1. **`model_not_loaded` is a 404, not a 503** — found and fixed during
   implementation, not assumed correct up front. `api/errors.py`'s own
   established (Phase 3) security rule strips any route-supplied `.code`/
   `.message` at status >= 500, so a 503 would have silently rendered as the
   generic `service_unavailable`/"not ready" text instead of the milestone's
   own named code. `api.routes.metrics`'s existing `metrics_not_computed`
   precedent — "the served computed thing does not exist yet" as a 404 with a
   distinct code — is the closer, already-established fit, and is what this
   route now follows exactly.
2. **`insufficient_features` is an API-level policy, not a model-level one.**
   `RankingXGBModel`/`WinProbXGBModel` both handle an all-absent input
   gracefully (XGBoost's own native missing-value learning), by design (M5/M6).
   Serving a "confident" number computed from literally zero real evidence is
   a different, worse claim than serving one built from thin-but-real data, so
   this route adds its own explicit check (every team involved has zero
   present features at all) rather than relying on the model to refuse.
3. **`build_team_features` (Milestone 1) was promoted from private to public**
   rather than duplicated — the ranking and alliance-synergy endpoints both
   need one team's own point-in-time snapshot outside the context of one
   specific match, which is exactly what that function already computes.
   Mirrors this codebase's own established precedent
   (`data.staging.normalizer._parse_team_number` -> `parse_tba_team_number`)
   for promoting a genuinely-reused private helper rather than reinventing it.
4. **A small, deliberately separate `ml/features/roster.py`** rather than
   reusing `data.metrics.compute`'s private `_teams_at_event` — this codebase's
   standing rule ("additive only... do not modify Kanav's M3-M10 computation
   logic without coordination") would make promoting that specific private
   helper to public an out-of-scope change to a Phase 3 file. The query itself
   is an 8-line `DISTINCT` lookup with nothing to diverge from Phase 3's own
   copy — a small, low-risk duplication in the additive `ml/` package instead.
5. **`ModelManifest` (Milestone 10) has no `version_tag` field** — that value
   lives in `Settings`, which the API layer already has, so responses echo it
   directly from configuration rather than requiring a change to M10's
   already-accepted registry schema for a value it can get for free.
6. **`calibration_status` is always `"uncalibrated"`** in every response —
   honestly, not a placeholder: no real calibrator (Milestone 7) has ever been
   fit on real data or registered, for the identical Statbotics reason M4-M7
   are unaccepted. Reported explicitly rather than omitted from the schema.

## Tests Added & Executed

`tests/test_api_predictions.py` — 18 tests, real Postgres + real FastAPI
`TestClient` against the real application from `create_app()`, two real (if
synthetically fit) models registered into a temporary registry directory:

- **Happy path per endpoint** (the milestone's own named test): all four
  endpoints, response validated through the real pydantic response model
  classes (`WinProbabilityResponse.model_validate(...)`, etc.), not merely
  key-presence-checked — the milestone's own named "response schema validated
  against the canonical models" requirement.
- **Symmetry-through-API** (the milestone's own named test): the same two
  alliances posted in both orders through the real HTTP endpoint give
  probabilities that sum to exactly 1.0 (to floating-point tolerance) — proof
  Milestone 6's algebraic symmetry guarantee survives the full HTTP round trip,
  not just a direct model call.
- **model-not-loaded** (the milestone's own named test): both model-backed
  endpoints, dependency-overridden to `None`, each correctly 404 with the
  distinct `model_not_loaded` code — this is also literally what this project's
  real, currently-deployed configuration would answer today, since nothing is
  actually pinned in `Settings`.
- **insufficient-features** (the milestone's own named test): a real, genuinely
  data-free team roster (rostered only into an unplayed match, no score, no
  scouting, no EPA) correctly 422s on both the match-based and ad-hoc
  win-probability endpoints.
- **unknown team/event** (the milestone's own named test): both a nonexistent
  `event_key` and a team_number not rostered at a real event each 404 with
  their own distinct code, across every endpoint that takes them.
- Additional coverage beyond the milestone's own named list: an unknown
  `match_key` (404 `match_not_found`); a wrong-sized alliance list (422
  `validation_error`, FastAPI's own request-validation path); the alliance-
  synergy endpoint confirmed to have NO model-not-loaded case at all (it needs
  no model — both model dependencies overridden to `None` and the endpoint
  still succeeds).

`tests/test_api_foundation.py` and `tests/test_metrics_docs_contract.py` — two
pre-existing Phase 3 contract tests updated (see Issues Found), both re-passing.

## Terminal Verification Status

```
python -m pytest tests/test_api_predictions.py -v
18 passed in 16.54s

python -m pytest tests/test_api_foundation.py tests/test_metrics_api.py tests/test_metrics_docs_contract.py -q
66 + 49 passed (after the two contract-test fixes)
```

Full repository suite, isolated (no concurrent background job):

```
python -m pytest -q
1185 passed, 2 warnings in 377.33s
```

Zero regressions against the 1167-passed baseline immediately prior (1185 = 1167 + 18 new). Statbotics rechecked again this session (now returning HTTP 503, previously 500 — still down either way, independently curl-verified against the codebase's own exact endpoint).

## Issues Found During Implementation

Three real issues, all found by running the tests, not merely by inspection:

1. **The `model_not_loaded` status-code bug described in Architectural
   Decision 1** — caught by three failing tests expecting a custom error code
   at 503 and getting the generic `service_unavailable` instead. Fixed by
   switching to 404, matching `metrics_not_computed`'s existing precedent.
2. **The happy-path win-probability test initially failed with
   `insufficient_features`, not a bug in the route.** The test fixture's
   played match was the ONLY match its own six teams appeared in, so their
   `average_score` was correctly, leakage-safely absent as of that match's own
   `scheduled_time` (Milestone 1's point-in-time guarantee: a match's own
   outcome never counts toward its own teams' history). Fixed by adding an
   earlier, already-played prior match for the same six teams to the fixture,
   giving them real history to draw from — the fixture was wrong, not the code.
3. **Two pre-existing Phase 3 docs-contract tests broke**, both because they
   implicitly assumed `/teams/.../metrics` was the only non-probe endpoint that
   would ever exist: `test_documented_endpoints_are_exactly_the_live_ones`
   (asserts live paths == `docs/metrics_pipeline.md`'s documented paths) and
   `test_reliability_score_placeholder_caveat_reaches_the_served_schema`
   (asserted `"INTERIM"` appears in literally every non-probe endpoint's
   description). Both scoped to exclude the four new `/predictions/*` paths,
   for the same reason `PROBE_PATHS` already excludes `/health`/`/ready`: those
   paths belong to a different page's documented scope (a future
   `docs/ml_models.md`, Milestone 13), not an oversight in either test or in
   this milestone's own work.

## Remaining Known Risks

- No model is actually pinned in the real deployed configuration yet (see
  "Not implied by this acceptance" above) — this is the honest, correct current
  state, not a defect, and will resolve naturally once Statbotics recovers and
  M4-M7 are accepted and registered.
- `calibration_status` will need to become genuinely dynamic (reading whether
  a real M7 calibrator is registered and applied) once M7 is accepted —
  currently always `"uncalibrated"`, honestly, since none exists yet.

## Roadmap Satisfaction

- "Read pinned model versions from the registry — no training or heavy
  recompute in the request path" — `api.ml_loading` loads once at startup;
  every request path is read-only inference. ✅
- "Reuse the M12-M13 structured error envelope + distinct outcome codes" —
  every error goes through the existing `ApiError`/`error_json_response`
  machinery; four distinct codes (`model_not_loaded`, `event_not_found`/
  `match_not_found`, `team_not_found`, `insufficient_features`) plus FastAPI's
  own `validation_error` for malformed requests. ✅
- "Response schemas are Pydantic models that echo model version + calibration
  status" — `WinProbabilityResponse`/`TeamRankingResponse` both carry
  `model_type`/`model_version`/`model_version_tag`/`calibration_status`. ✅
- "Endpoints return complete, versioned predictions; degraded inputs return
  documented codes, not 500s or silent guesses" — pinned directly by test;
  zero 500s anywhere in the test suite's error-path coverage. ✅
- "No LLM calls anywhere in the path" — none exist in this module or anything
  it imports. ✅

## Production Readiness

Ready to serve real predictions the moment a real, accepted model is registered
(M10) and `Settings.ml_ranking_model_version_tag`/`ml_win_prob_model_version_tag`
are set to point at it — no code change required, only configuration.

## Readiness for Next Milestone

M12 is fully accepted. M13 (Phase 4 documentation, contract tests & sign-off)
is next, and is where `docs/ml_models.md` — the page these four endpoints
belong to — gets written; it depends on all prior milestones, several of which
(M4-M7) remain unaccepted pending Statbotics.
