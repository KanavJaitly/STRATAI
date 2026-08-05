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
* Milestone 9 (Kanav, 2026-08-05): ScoutRadioz research, in
  docs/data_pipeline.md section 4.1 and RUNNING_NOTES.md — no connector
  built. ScoutRadioz has no public, documented API: every data-bearing
  route, including its own CSV export, requires an authenticated per-team
  login, unlike TBA/Statbotics's open APIs. load_scouting_observation and
  aggregate_defense_feeding are already source-agnostic (confirmed with real
  multi-source rows in tests/test_repository.py and
  tests/test_aggregation.py), so nothing needed to change there; human-form
  submission remains the sole populated measurement path for Phase 3, and
  the registries' "scoutradioz" slot stays reserved and tested as
  unregistered.
* Milestone 10 onward (the metrics computation pipeline, and everything
  after) not started. See docs/P3Milestones.md for the full per-milestone
  checklist and RUNNING_NOTES.md for status/decisions.

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
Phase 3 Milestone 10 – the metrics computation pipeline.

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
