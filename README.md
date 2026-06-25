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
2. Fill in `DATABASE_URL`, `TBA_API_KEY`, and `STATBOTICS_API_KEY`
3. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

4. Run tests:

```bash
python -m pytest
```
