# StratAI

## Phase 2: Data Pipeline

This project is building the data ingestion layer for StratAI, an AI-assisted strategy platform for FRC.

### Phase 2 goals

- Integrate The Blue Alliance API
- Integrate Statbotics API
- Store raw source payloads in PostgreSQL
- Prepare data for later normalization and analytics

### Project layout

- `data/` - data pipeline code
- `data/clients/` - source connector implementations
- `data/landing/` - raw payload ingestion layer
- `data/staging/` - normalized staging models
- `data/serving/` - canonical analytics persistence
- `database/` - database connection and migrations
- `tests/` - unit and integration tests

### Local setup

1. Copy `.env.example` to `.env`
2. Fill in `DATABASE_URL` and `TBA_API_KEY`. `STATBOTICS_API_KEY` is optional for public API access.

Example `.env` for a local Postgres database named `stratai`:

```text
DATABASE_URL=postgresql://postgres:password@localhost:5432/stratai
TBA_API_KEY=your_the_blue_alliance_api_key
# STATBOTICS_API_KEY is optional
# STATBOTICS_API_KEY=your_statbotics_api_key
ENV=development
```

3. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

4. Create the local database if needed:

```bash
psql -U postgres -c "CREATE DATABASE stratai;"
```

5. Initialize the database:

```bash
.venv\Scripts\python.exe database\init_db.py
```

6. Verify the database schema:

```bash
.venv\Scripts\python.exe database\verify_db.py
```

7. Run tests:

```bash
.venv\Scripts\python.exe -m pytest
```
