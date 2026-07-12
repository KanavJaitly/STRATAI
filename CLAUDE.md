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
Phase 2 – Data Pipeline

Current Tasks:

* Integrate The Blue Alliance API.
* Integrate Statbotics API.
* Store raw data in PostgreSQL.
* Design reusable API clients.
* Prepare data for later metric calculations.

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
