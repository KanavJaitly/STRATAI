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
* Real-time updates must sync **during an event** as matches are played.

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

Current Phase:
Phase 3 – Metrics and analytics (underway)

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

* Milestone 14 onward (the human validation harness and documentation) not
  started. See docs/P3Milestones.md for the full per-milestone checklist and
  RUNNING_NOTES.md for status/decisions.

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
Phase 3 Milestone 14 – human validation and acceptance harness
(scripts/metrics_spot_check.py). The deliverable is a dated human sign-off in
RUNNING_NOTES.md, not an automated test.

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
