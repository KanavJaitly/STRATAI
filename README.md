# StratAI

An AI-assisted strategy platform for the FIRST Robotics Competition. StratAI analyses
historical and live FRC data to produce statistically grounded, unbiased strategic
recommendations.

**Current phase: Phase 2 — Data Pipeline (complete).** The ingestion pipeline pulls event,
match, team, and EPA data from external sources into PostgreSQL, validating it and keeping
it traceable to its source. Metrics, predictions, and pick lists come in later phases.

## Documentation

**[docs/data_pipeline.md](docs/data_pipeline.md)** is the reference for Phase 2:
architecture, the full schema, incremental state, data quality and lineage, a verified
local quickstart, and known issues. Start there.

**[docs/metrics_pipeline.md](docs/metrics_pipeline.md)** is the reference for Phase 3:
how a scouting observation and a match score become one served `TeamMetrics` object — the
rating scale, the aggregation methodology, the API contract, and the limits on what the
served numbers may be used to claim.

**[docs/ml_models.md](docs/ml_models.md)** is the reference for Phase 4: features, the
backtest method, the models and their held-out results, the calibration evidence, and
which predictions can and cannot be trusted. Phase 4's done-means is not met (M7 failed).

[RUNNING_NOTES.md](RUNNING_NOTES.md) tracks milestone status and the design-decision log.

## Project layout

| Path | Contents |
|---|---|
| `data/pipeline.py` | The four ingestion stages (extraction → landing → staging → serving) |
| `data/orchestrator.py` | Run bookkeeping, watermarks, and the pipeline CLI entry point |
| `data/clients/` | Source connectors (The Blue Alliance, Statbotics) |
| `data/landing/` | Raw payload ingestion — immutable, versioned, deduplicated |
| `data/staging/` | Validation, normalization, and data quality checks |
| `data/serving/` | Canonical table loaders (upsert-based) |
| `data/lineage.py` | Provenance from a canonical row back to its raw payload |
| `database/` | Connection helper, raw SQL migrations, migration runner |
| `tests/` | Unit, integration, and contract tests |

## Quick start

Full walkthrough in [docs/data_pipeline.md §7](docs/data_pipeline.md#7-local-quickstart).
The short version:

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
createdb -U postgres -h localhost stratai  # use a role that exists in your cluster
cp .env.example .env                       # then fill in DATABASE_URL and TBA_API_KEY
venv/bin/python database/migrate.py        # apply migrations
venv/bin/python database/verify_db.py      # confirm the schema
venv/bin/python -m data.orchestrator 2024casj   # sync one event end to end
```

Run the tests:

```bash
export DATABASE_URL=$(venv/bin/python -m scripts.phase5_isolated_db --name stratai_test --print-url-env)
venv/bin/python -m pytest -q
```

**The suite runs only against an isolated test database** (since 2026-10-04; `tests/db_guard.py`, installed by
`tests/conftest.py`). A session whose `DATABASE_URL` resolves to anything other than `stratai_test` or
`stratai_test_<suffix>` stops before collection, and the serving database `stratai` is always refused. There is
no bypass. Clone the isolated copy once with `python -m scripts.phase5_isolated_db --name stratai_test`, then
export its URL as above. Background: `.agent/phase5/INCIDENT_2026-10-04_0010_on_serving.md`.

All tests pass, with 3 integration tests self-skipping when no database is reachable. (If
you have an older command with `--deselect tests/test_config.py::...`, drop it — that test
was fixed on 2026-07-25; see
[docs/data_pipeline.md §9.2](docs/data_pipeline.md#92-known-failing-config-test).)
Statbotics data is currently unavailable against the live API —
[§9.1](docs/data_pipeline.md#91-statbotics-client-fixed-live-confirmation-still-pending-their-outage) explains
why and what still works.

## Stack

Python 3.11 · FastAPI (later phases) · PostgreSQL 18 · psycopg3 · Pydantic v2 · httpx ·
pytest. Migrations are raw SQL applied in filename order — no Alembic.
