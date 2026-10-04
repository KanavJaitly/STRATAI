# StratAI

## Project Overview

StratAI is an AI-powered strategy platform for FIRST Robotics Competition (FRC).

The purpose of this project is to analyze historical and live FRC competition data to provide statistically accurate and unbiased strategic recommendations throughout the robotics season.

The application should continuously improve as new match data becomes available.

---

## Primary Objectives

The system should eventually be able to:

* Generate alliance pick lists.
* Generate match strategies.
* Predict match win probabilities.
* Calculate defense ratings.
* Calculate feeding ratings.
* Calculate robot consistency.
* Analyze game metas as the season progresses.
* Generate pre-match scouting reports.
* Analyze historical team performance.
* Continuously update as new competition data becomes available.

---

## Tech Stack

Backend

* Python
* FastAPI

Frontend

* React
* TypeScript

Database

* PostgreSQL

Caching

* Redis

Machine Learning

* scikit-learn
* XGBoost
* OR-Tools
* Pandas
* NumPy

External APIs

* The Blue Alliance
* Statbotics
* ScoutRadioz (if available)

Version Control

* Git
* GitHub

---

## Folder Structure

/api
Backend API

/data
API integrations and data ingestion

/ml
Machine learning models, metrics, predictions, optimization

/frontend
React frontend

/database
Schemas and migrations

/docs
Documentation

/tests
Unit and integration tests

---

## Coding Standards

* Write clean, modular code.
* Prefer readability over cleverness.
* Use Python type hints.
* Write docstrings for public functions.
* Avoid duplicated logic.
* Use descriptive variable names.
* Keep functions reasonably small.
* Write tests for backend features whenever practical.
* Never hardcode secrets or API keys.
* **Verification runtime limit (Kanav, 2026-10-03; permanent).** No test, simulation, replay,
  verification harness or other non-production validation run may be designed or allowed to run longer
  than about 45 minutes.
  * If a run is expected to exceed that, redesign it before running it; never let it run for hours.
  * For expensive replay or simulation testing, use a seeded random or stratified representative sample of
    matches/events plus targeted edge cases, not the whole historical dataset.
  * Testing establishes that the system works correctly; it is not an exhaustive execution of history.
  * Harnesses should carry their own time budget and stop, reporting partial results, when they hit it.
* **Test-database guard (Kanav, 2026-10-04; permanent).** Database-backed tests run only against an isolated
  `stratai_test` / `stratai_test_<suffix>` copy.
  * `tests/db_guard.py`, installed by `tests/conftest.py`, refuses every other database, the serving `stratai`
    above all, before collection and at every connection.
  * Never add a bypass or weaken it. See `.agent/phase5/INCIDENT_2026-10-04_0010_on_serving.md`.

---

## Database Rules

* Store raw API responses before processing.
* Never overwrite historical match data.
* Separate raw data from calculated metrics.
* Avoid duplicate records.
* Design schemas to be scalable across multiple FRC seasons.

---

## Machine Learning Principles

The goal is not simply to build an AI model.

The goal is to build a trustworthy decision-support system.

Predictions should:

* Be data-driven.
* Avoid human bias.
* Include realistic confidence estimates.
* Never exaggerate certainty.
* Prefer explainable models when possible.

---

## Critical Constraints

These are the project's non-negotiable rules. Several modules, migrations, and
tests cite "CLAUDE.md's critical constraints" by name — this is that section.
RUNNING_NOTES.md carries the same list; keep the two in sync.

* Defense/feeding scores = **directly measured**, NOT inferred from point output.
* Win probabilities = **unbiased** — AI strategy cannot get inflated odds.
* Core engine = **no LLM API calls** — ML / stats / optimization only.
* LLM allowed only for: natural-language report generation and explanations.
* Real-time updates must sync **during an event** as matches are played. Since Phase 5 (P5-M6,
  2026-10-03), `--watch` keeps the canonical tables current *and* recomputes `team_metrics` after
  every poll that loads new rows (`data.orchestrator.after_watch_sync`), so the served metrics move
  during a watch. The quality-issue growth that blocked this (docs/metrics_pipeline.md §9.10) is
  deduplicated, and §9.9 is closed. Verified by replay
  (`.agent/phase5/results/p5_m6_replay_rerun1.json`).

The first constraint is enforced in four places, deliberately: the
`DefenseFeedingProfile` invariants in data/metrics/schemas.py, the
`*_sufficiency_check` CHECK constraints in
database/migrations/0008_metrics_schema.sql, the fact that
`aggregate_defense_feeding` is only ever handed scouting observations, and the
regression guard in tests/test_defense_feeding_constraint.py. Defense and
feeding derive from scouting_observations and nothing else; a team with no
observations gets no rating, never one synthesized from its scoring.

---

## Current Development Phase

**Phase 5 (2026-10-04): implementation checkpoint accepted by Kanav. Phase 5 is NOT complete.**
- **Status:** P5-D3 adopted (live EPA in production); DM2 met; DM1 not met.
- **Why it is incomplete:** DM1 awaits genuine human M8/M9 inputs, entered through the `frontend/` web app.
- **Records:** `.agent/phase5/PHASE_STATUS.md`, `PHASE_ACCEPTANCE.md`, `docs/phase5.md`.
- **Phase 6 is next.** It starts only on Kanav's explicit build instruction. The Phase 4 text below is historical.

Current Phase:
Phase 4 – ML Models (underway). Phase 3 is not fully closed — Milestone 14
(human validation) remains open (see the Phase 3 section below) — but Phase 4
work began ahead of it on explicit direction, since M14's remaining blockers
(a feeding-data collection gap and a pending product decision on the defense
metric's definition) are unrelated to and not fixable by any Phase 4 work.

Phase 3 progress:

* Milestone 1 (Kanav): canonical metric models in data/metrics/schemas.py —
  ScoringProfile, DefenseFeedingProfile, ScoutingObservation, TeamMetrics.
* Milestone 2 (Sven, 2026-08-02): database schema for metrics and scouting
  observations — 0008_metrics_schema.sql creates scouting_observations and
  team_metrics. Schema only at the time; team_metrics is still empty, but
  scouting_observations now has a real writer (Milestone 7). See
  docs/data_pipeline.md section 4.1.
* Milestone 3 (Kanav, 2026-08-04): pure statistical functions in
  data/metrics/statistics.py — average_score, score_stddev,
  consistency_rating, classify_match_days, reliability_score.
* Milestone 4 (Kanav, 2026-08-04): match history retrieval in
  data/metrics/history.py — get_team_match_history reads matches/match_teams
  and returns one team's own score history at one event.
* Milestone 5 (Kanav, 2026-08-04): scouting observation validation in
  data/metrics/validator.py — validate_human_scout_observation_payload,
  reusing data.staging.validator's ValidationIssue/PayloadValidationError.
* Milestone 6 (Kanav, 2026-08-04): scouting observation normalization in
  data/metrics/normalizer.py — normalize_human_scout_observation builds a
  validated raw submission into a canonical ScoutingObservation.
* Milestone 7 (Kanav, 2026-08-04): human scouting submission path in
  data/metrics/submission.py — submit_human_scout_observation gates (a
  lightweight per-event access code, 0009_scouting_access_codes.sql), lands
  via RawPayloadWriter, and stages+loads via data.pipeline's existing
  read_pending/stage_batch into a real scouting_observations row. No HTTP
  route yet — this is the service function Milestone 12's API layer will
  call once it exists.
* Milestone 8 (Kanav, 2026-08-04): defense/feeding aggregation logic in
  data/metrics/aggregation.py — aggregate_defense_feeding takes one team's
  ScoutingObservation rows at one event and returns a DefenseFeedingProfile:
  median score (not mean), population-stddev-based agreement, and a
  documented 2-observation minimum before anything is reported as sufficient.
* Milestone 9 (Kanav, 2026-08-05): ScoutRadioz CSV import, in
  data/clients/scoutradioz.py (ScoutRadiozCsvImporter, a SourceConnector
  reading a CSV export) and data/metrics/scoutradioz.py
  (ScoutRadiozFieldMapping, import_scoutradioz_csv). ScoutRadioz has no
  public API — every data-bearing route, including its own CSV export,
  requires an authenticated per-team login — so a team exports its own
  match-scouting CSV and StratAI imports it directly, reusing the human-scout
  submission path's land/stage/load machinery end to end. Column mapping
  (which raw column is defense/feeding quality, on what native scale) is
  caller-supplied configuration, not code, so no FRC game's field names are
  hardcoded. See docs/data_pipeline.md section 4.1 and RUNNING_NOTES.md for
  the full architecture and design decisions.
* Milestone 10 (Kanav, 2026-08-05): the metrics computation pipeline, in
  data/metrics/compute.py — compute_team_metrics(database, team_number,
  event_key) composes Milestones 3+4+8 into the TeamMetrics object Phase 3's
  Definition of Done names; compute_event_team_metrics(event_key, ...)
  computes and upserts it for every team rostered at an event and records
  its own pipeline_runs row (pipeline_name="metrics_compute"), wired as a
  follow-on stage right after a single-event sync in
  data.orchestrator.main. Always fully recomputes on trigger, no incremental
  watermark (documented why in data/metrics/compute.py's own module
  docstring and docs/data_pipeline.md section 4.1). Lineage traces a
  team_metrics row to every contributing match and scouting observation.
  team_metrics is no longer empty.
* Milestone 11 (Sven, 2026-08-05): metrics data quality checks, in
  data/metrics/quality.py — check_team_metrics judges a computed TeamMetrics
  on confidence and internal consistency, the axis neither the structural
  validator nor data/staging/quality.py's plausibility checks cover. It
  extends Phase 2's quality layer rather than adding a second one: the same
  QualityIssue, the same severity constants, the same DataQualityRecorder,
  the same data_quality_issues table, no migration.
  compute_event_team_metrics runs it between computing a metric and loading
  it. Because pydantic and 0008's CHECK constraints already make an
  impossible metric unconstructible, "implausible" here means jointly
  suspicious (fields individually valid that cannot both be true of one
  team's match set), and every rule is a warning that still loads — a metric
  from two matches is untrustworthy, not corrupt, and rejecting it would
  leave the team with nothing. The checks live in data.metrics, not
  data.staging, because they must import data/metrics/schemas.py and
  data.staging must not depend on data.metrics; the thresholds live in
  data/staging/quality.py with every other plausibility bound. See
  docs/data_pipeline.md section 6.4.
* Milestone 12 (Sven, 2026-08-06): the API foundation, in the new api/ package
  — api/app.py's create_app(settings=None) builds the FastAPI application on a
  bare Settings(), the same construction data/orchestrator.py's CLI uses, so
  there is no parallel config and no second env-loading mechanism. Four new
  fields on that existing Settings (api_host, api_port, api_prefix,
  cors_origins) rather than an api-specific config object. Infrastructure only,
  by the milestone's own instruction: no metrics or data endpoints, which are
  Milestone 13, pinned by a test asserting the OpenAPI paths are exactly
  /health and /ready.

  Liveness and readiness are split because a readiness probe that checks
  nothing is a liveness probe with a misleading name: /health does no I/O and
  stays usable while PostgreSQL is down, /ready does one SELECT 1 through the
  existing Database.connection() and returns 503 in the error envelope when it
  fails. That check does not address database/connection.py's lack of
  connection pooling, which remains an open backlog item.

  api/errors.py gives every error path one envelope —
  {"error": {code, message, status, request_id, details?}} — so nothing falls
  back to FastAPI's {"detail": ...}. For any status >= 500 the response body is
  built from module constants and the request id, and the exception is never
  read into it; the real detail goes to the log, correlated by request id.
  Starlette debug mode is hardcoded off and deliberately not wired to
  settings.env. The primary catch-all lives in api/middleware.py, inside
  CORSMiddleware, because Starlette's ServerErrorMiddleware re-raises after
  calling its handler and the 500 it produces carries no CORS headers.

  The request-logging middleware matches the existing convention exactly:
  logging.getLogger(__name__) with %-style lazy args, and basicConfig called
  only in api/__main__.py (python -m api), never in a library module. It logs
  method, path, status, duration and request id, and deliberately not bodies,
  headers, or query strings — Milestone 7's submission path is gated by a
  per-event access code that must not be written to disk on every request.

* Milestone 13 (Sven, 2026-08-06): the team metrics endpoint —
  GET /teams/{team_number}/events/{event_key}/metrics in api/routes/metrics.py,
  returning the canonical TeamMetrics. Phase 3's Definition of Done is now
  callable. Mounted under Settings.api_prefix, the first use of the field
  Milestone 12 added for it; the health probes stay deliberately outside it.

  Read-only, and it never recomputes: data/metrics/read.py's
  look_up_team_metrics reads team_metrics directly — one primary-key query on
  the happy path — and is a sibling of Milestone 4's history.py, not a wrapper
  over Milestone 10's compute_team_metrics. A test asserts a read adds no
  pipeline_runs row, which is an external witness that nothing recomputed.
  Reassembly constructs real ScoringProfile/DefenseFeedingProfile objects
  rather than model_construct, so Milestone 1's validators run on the way out
  and a row contradicting its own invariants fails loudly instead of being
  served as a model that lies about itself.

  Five outcomes. Metrics found is a 200. The four ways to have none are all
  404 with distinct machine-readable codes — team_not_found, event_not_found,
  team_did_not_attend, metrics_not_computed — because what separates the last
  two is actionability, not existence: compute_event_team_metrics writes rows
  only for teams match_teams rosters at the event and
  _delete_orphaned_team_metrics deletes the row for a team dropped from that
  roster, so "not computed" resolves by waiting while "did not attend" never
  resolves at all. HTTP status has no vocabulary for that difference and a
  stable code does. This required one additive change to Milestone 12's
  foundation: ApiError in api/errors.py, an HTTPException carrying its own
  code, read via getattr so every existing exception renders byte-identically,
  and honoured only below 500 so that milestone's guarantee that a >= 500 body
  is assembled purely from module constants stays intact.

  A thin-data team returns 200 with the complete object — its insufficient_data
  flags and None confidence fields intact — never an error. Returning "not
  computed" as a 200 with an empty body was considered and rejected for that
  exact reason: a thin-data team genuinely is a 200 with a mostly-empty body,
  so absent must stay a 404 or the two become indistinguishable.

  No writes and no authentication, both out of scope here and neither needed by
  a read endpoint. Auth and rate limiting are a real prerequisite for exposing
  Milestone 7's submission path over HTTP, and a separate later concern.

* Milestone 14 (Sven, 2026-08-06 harness; 2026-08-08 defense sign-off): the
  human validation and acceptance harness, scripts/metrics_spot_check.py.
  Read-only, reads through Milestone 13's look_up_team_metrics so it never
  recomputes, and prints no verdict — defense and feeding have no external
  truth source, so the only authority is a human who watched the matches.
  **Still open.** The defense half is signed off on real 2026mrcmp data (331
  observations, 58 teams over the 2-observation minimum); the feeding half
  cannot be validated at all until a feeding-quality field exists at
  collection time.

* Milestone 15 (Sven, 2026-08-08): documentation and Phase 3 contract tests —
  docs/metrics_pipeline.md and tests/test_metrics_docs_contract.py (48 tests,
  8 against the live schema). Phase 3 is now documented to Phase 2's standard
  and enforced by tests rather than trust: every column, key, cascade rule,
  endpoint, error code, rating description, and threshold the page quotes is
  pinned to the live schema or the live constant, in both directions, so a
  column or route added without documenting it fails. The page is the
  *semantic* reference for scouting_observations and team_metrics;
  docs/data_pipeline.md section 4.1 keeps the DDL, and a test intersects both
  pages' column sets with the live schema so they cannot drift apart.

  Documentation only, deliberately. The extension guide documents the real
  ScoutRadiozFieldMapping Python-dataclass mechanism rather than a YAML
  mapping file, because no YAML exists in this repo and building a loader is a
  feature, not documentation — deferred to Phase 4. reliability_score's
  candidate TBA field names (dq_team_keys/surrogate_team_keys) are documented
  as UNVERIFIED, with a test enforcing the marker, since they have never been
  checked against TBA's live docs.

See docs/P3Milestones.md for the full per-milestone checklist and
RUNNING_NOTES.md for status/decisions.

Phase 4 – ML Models (underway)

Phase 4 follows the authoritative 13-milestone plan in docs/P4Milestones.md
(restored 2026-09-21 from an earlier, independently-produced worktree after a
6-milestone plan drafted from scratch inside this session was found to
conflict with it and was discarded, code included — see RUNNING_NOTES.md for
the full record).

Phase 4 progress:

* Milestone 1 (2026-09-21): the leakage-safe feature assembly layer —
  ml/features/assembler.py's build_match_feature_row(database, match_key,
  as_of) -> MatchFeatureRow. Recomputes scoring statistics and defense/
  feeding aggregates fresh, at read time, from matches/match_teams/
  scouting_observations rows filtered to strictly before as_of, reusing
  Phase 3's own pure functions (data.metrics.statistics, data.metrics.
  aggregation) unmodified rather than reading the stored team_metrics
  snapshot — team_metrics is a current-state snapshot, not a historical
  series, so reading it directly for a past match would leak that match's
  own event forward. EPA (Statbotics team_event_stats) is never taken from
  the target match's own event, at any as_of, since that table has no
  historical series either and cannot be proven to reflect only prior
  matches within its own event; only a strictly earlier, already-concluded
  event's EPA is offered, documented as a real, open gap for a future
  EPA-history table to close. Every optional feature carries an explicit
  presence flag alongside its value. No new dependencies (pandas/numpy/
  scikit-learn/xgboost/OR-Tools are added starting Milestone 5, when a
  milestone that actually trains something needs them).
* Milestone 2 (2026-09-24): the labeled match-outcome dataset builder —
  ml/dataset/builder.py's build_training_frame(database, season_keys) ->
  TrainingFrameResult, attaching a real red_win/blue_win/tie label plus score
  margin to Milestone 1's MatchFeatureRow, and persist_training_frame writing
  the result as a versioned parquet artifact with a manifest. Five documented
  inclusion/exclusion rules (no_scheduled_time, unplayed, a defensive
  winning_alliance_missing check, dq_affected, dq_status_unknown); comp
  level, ties, and surrogate appearances are kept and tagged, never dropped.
  Confirmed directly against TBA's own live OpenAPI spec that dq_team_keys/
  surrogate_team_keys are real fields (resolving the "UNVERIFIED" status
  these exact names have carried since Phase 3 M15) and that TBA has no
  separate no-show concept (folded into DQ) and no replay concept at all
  (match_key is already TBA's one canonical record). Neither field reached
  this codebase's canonical schema, so the builder reads the untouched raw
  TBA payload directly out of raw_source_payloads.payload_json, additively —
  no migration, nothing touched in Kanav's M3-M10 computation logic. A DQ'd
  match (or one with no raw payload to check) is excluded from the labeled
  set by default, reversibly, via include_dq_affected=True. First Phase 4
  dependency added: pyarrow only, no pandas (deferred to Milestone 5 as
  planned). A related, out-of-scope gap surfaced and documented rather than
  fixed: Milestone 1's own scoring history does not currently distinguish a
  surrogate appearance from a normal one.
* Milestone 3 (2026-09-25, first milestone under Phase Execution Mode —
  prompts/MASTER_BUILD.md, adopted 2026-09-24): the temporal backtesting
  harness and Model protocol — ml/backtest/harness.py's Model
  (fit/predict_win_prob/predict_rating/save/load), Fold (structurally
  enforces max(train.scheduled_time) < min(test.scheduled_time) for every
  fold constructed, not merely tested after the fact), hold_out_season_split,
  walk_forward_splits (ISO-week bucketed), and run_win_prob_backtest/
  run_ranking_backtest, plus ml/backtest/metrics.py's seven pure metric
  functions (accuracy, log-loss, Brier, ROC-AUC, ECE, Spearman, top-k
  recall), all dependency-free per the plan's own "pandas/numpy add starting
  Milestone 5" note. No reachable database needed at all: every function
  operates on Milestone 1/2's already-assembled TrainingRow/TeamFeatures
  objects, not the database directly, so all 56 new tests are pure and
  actually execute (no requires_db skips). Found during Challenge, before
  implementation: no table or client model anywhere in this codebase has
  ever landed a team's real final event ranking, more fundamental than the
  no-database gap since it means the ranking half of these metrics has no
  real ground truth even with a live database — resolved by taking
  final_ranks as an explicit external argument rather than fabricating a
  source, flagged as load-bearing starting Milestone 5. Full acceptance
  record: .agent/phase4/M03_ACCEPTANCE.md.
* Milestone 4 (code complete 2026-09-25, NOT accepted): locked naive
  baselines — ml/models/baselines.py's RawEpaRankingBaseline and
  EpaWinProbBaseline (genuine Newton-Raphson-fit logistic, no invented
  "standard Statbotics formula"), 24 tests, all synthetic and labeled as
  such. The real, dated backtest numbers this milestone's own acceptance
  requires are blocked on a Statbotics outage (HTTP 500/503 on every
  substantive endpoint throughout this session) — see PHASE_STATUS.md.
* Milestones 5-7 (code complete 2026-09-25, NOT accepted, built ahead of
  M4's freeze as dependency-independent progress): ml/models/ranking_xgb.py
  (XGBoost rating model — the training-target formulation, a real
  architectural ambiguity M3's own locked Model protocol left open, was
  confirmed with Kanav before implementation), ml/models/win_prob.py
  (symmetric-by-construction XGBoost win-prob model — p(R,B) =
  (raw(R,B) + (1-raw(B,R)))/2, a structural guarantee for any underlying
  predictor, not merely observed), and ml/calibration/calibrator.py
  (isotonic/Platt calibration, scikit-learn added, calibration-fit
  isolation enforced structurally). 77 combined new tests. Each of these
  three milestones' own real beats-M4-baseline / real-calibration-band
  acceptance criteria need the same real EPA data M4 is blocked on.
* Milestone 8 (2026-09-25, ACCEPTED, built out of numeric order — needs no
  real data): scripts/ml_bias_audit.py, one command running symmetry,
  order-invariance, no-strategy-leakage, as-of-feature-integrity, and
  label-shuffle leakage checks against the real M5/M6 models. Proven to
  have teeth via two deliberately-broken fixture models, each shown to
  fail the specific check it violates. Full acceptance record:
  .agent/phase4/M08_ACCEPTANCE.md.
* Milestone 9 (2026-09-25, ACCEPTED): ml/synergy/score.py's
  alliance_synergy() — since no "role" field exists anywhere in this
  codebase's schema, role fit and scoring-distribution complementarity are
  computed as unit-free share vectors (a team's value on one axis / the
  alliance's total on that axis), scored via 1 − mean pairwise cosine
  similarity. This design was confirmed with Kanav before implementation
  (a genuine strategy/domain question, not just an engineering one) rather
  than guessed at. Full acceptance record: .agent/phase4/M09_ACCEPTANCE.md.
* Milestone 10 (2026-09-25, ACCEPTED): ml/registry.py's register_model/
  load_registered_model/list_registered_versions and ModelManifest.
  Write-once storage per (model_type, version_tag); the registry's own
  feature-list guard is independent of (defense in depth alongside) each
  model class's own internal check. Verified end to end against the real
  RankingXGBModel, including a simulated feature-list drift correctly
  refused at load time. Full acceptance record:
  .agent/phase4/M10_ACCEPTANCE.md.
* Milestone 11 — investigated 2026-09-25, DEFERRED (Kanav-confirmed): the
  entire data/ and ml/ packages were grepped for score_breakdown, the
  field this milestone's own brief names as the thing to adapt across
  seasons. It is never parsed or consumed anywhere in this codebase, so
  there is no existing feature or consumer for "season-aware feature
  adapters" to adapt yet — building the guard now would be speculative
  structure with no consumer, the same anti-pattern this phase already
  rejected once (Milestone 1's discarded schema-only draft). Revisit if/
  when a future feature actually reads score_breakdown.
* Milestone 12 (2026-09-25, ACCEPTED): four ML prediction endpoints
  extending the Phase 3 api/ package additively (api/routes/predictions.py)
  — match-based and ad-hoc win probability, event team ranking, alliance
  synergy — loading pinned model versions from Milestone 10's registry at
  startup (api/ml_loading.py), never in the request path. Both pinned
  version-tag settings default to None, this project's honest current
  production state, so the two model-backed endpoints correctly answer
  model_not_loaded until a real M4-M7 model is accepted and registered.
  Found and fixed a real bug during testing: model_not_loaded was first
  coded as a 503, which api/errors.py's own established security rule
  silently strips a custom error code from at that status — fixed to a
  404, matching api.routes.metrics's own existing metrics_not_computed
  precedent. Full acceptance record: .agent/phase4/M12_ACCEPTANCE.md.

See docs/P4Milestones.md for the full 13-milestone plan and RUNNING_NOTES.md
for status/decisions.

Phase 2 – Data Pipeline (complete, Milestones 1-10)

Phase 2 delivered:

* The Blue Alliance and Statbotics API clients with retry handling.
* Landing layer storing raw payloads, versioned and deduplicated.
* Staging layer with validation, normalization, and data quality checks.
* Serving layer loading the canonical tables via idempotent upserts.
* Pipeline orchestration with durable incremental state (watermarks).
* Data quality issue tracking and canonical-to-raw lineage.
* Single-event, whole-season, and automated live-event sync drivers.
* Documentation and a contract test suite.

See docs/data_pipeline.md for the architecture, schema, and quickstart, and
RUNNING_NOTES.md for milestone status and the design decision log.

Both Phase 2 done-criteria are satisfied: the stored data was manually
spot-checked against real TBA results (2026-07-25), and live-event polling runs
without manual triggering (2026-08-01, `python -m data.orchestrator --watch`).

No open blockers. The Statbotics base-URL issue previously recorded here was
fixed on 2026-07-25 and confirmed against a live response on 2026-08-01;
team_event_stats now populates. See docs/data_pipeline.md section 9.1.

Next Milestone:
Two independent threads are open, and neither blocks the other.

Phase 4 Milestones 4-7 — locked naive baselines, the rating model, the
win-prob model, and calibration. The original PostgreSQL blocker is fully
resolved (18.6 installed, migrated, full seasons 2024/2025/2026 synced
TBA-side plus event rankings for all 608 events). All four milestones'
code is built, unit-tested against synthetic fixtures, and unblocked on
everything except one remaining dependency: Statbotics has returned HTTP
500/503 on every substantive endpoint all session (independently
curl-verified against this codebase's own exact endpoints), so the real,
dated numbers these milestones' own acceptance criteria require — M4's
frozen baseline, M5/M6's beats-baseline backtest, M7's real calibration
band — stay blocked until it recovers. Rechecked at sensible intervals,
not hammered. Milestones 8-10 and 12 do not depend on real data at all and
are ACCEPTED (see their own .agent/phase4/M0X_ACCEPTANCE.md files above);
Milestone 11 was investigated and DEFERRED (nothing in this codebase reads
the field it would guard). See .agent/phase4/PHASE_PLAN.md and
PHASE_STATUS.md.

Closing Phase 3 Milestone 14, the only Phase 3 milestone still open. Its
harness is built and its defense half is signed off; what remains is not code.
Two things block it, and neither is fixable in the pipeline:

1. Feeding cannot be validated until a feeding-quality field is captured at
   scout time. No raw source has one. Importing the DCMP summary's
   pre-aggregated Feeding Score would bypass the aggregation engine and
   validate nothing.
2. The defense metric definition is an open product decision — serve quality
   only, add a defended-frequency term, or serve quality × volume. It drives
   Alliance Selection and Match Strategy, so it needs a call with Kanav.

Standing constraint on what any of this may claim: zero (match, team) pairs
have been rated by two scouts, so defense_agreement measures match-to-match
variance confounded with scout calibration, not inter-scout agreement. See
docs/metrics_pipeline.md section 9.1.

---

## Long-Term Features

Future versions should support:

* Real-time event updates
* Alliance optimization
* Strategy generation
* Robot archetype prediction
* Meta detection
* Design recommendation assistance
* Live dashboard
* Coach strategy comparison
* Automated scouting reports

---

## Instructions for Claude Code

Before making major architectural changes:

1. Explain the proposed solution.
2. Wait for approval before implementing large changes.

When implementing features:

* Read the existing codebase first.
* Follow the current project structure.
* Reuse existing code whenever possible.
* Do not delete existing functionality unless requested.
* Keep code maintainable and scalable.
* Explain important implementation decisions.

If requirements are unclear, ask questions rather than making assumptions.

The project should prioritize correctness, maintainability, and statistical accuracy over implementing features as quickly as possible.
