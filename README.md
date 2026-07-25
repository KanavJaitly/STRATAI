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
venv/bin/python -m pytest -q --deselect tests/test_config.py::test_settings_allows_missing_statbotics_api_key
```

The deselected test is a known pre-existing failure that triggers whenever a `.env` file
exists; see [docs/data_pipeline.md §9.2](docs/data_pipeline.md#92-known-failing-config-test).
Statbotics data is also currently unavailable against the live API —
[§9.1](docs/data_pipeline.md#91-statbotics-does-not-work-against-the-live-api) explains
why and what still works.

## Stack

Python 3.11 · FastAPI (later phases) · PostgreSQL 18 · psycopg3 · Pydantic v2 · httpx ·
pytest. Migrations are raw SQL applied in filename order — no Alembic.
