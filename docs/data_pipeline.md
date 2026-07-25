# StratAI Data Pipeline (Phase 2)

This document describes the Phase 2 ingestion pipeline **as it actually exists**, not as
originally planned — the plan drifted in several places (observability tables arrived in
`0003` rather than with the initial schema, the canonical layer was re-keyed to
`team_number` in `0005`, and lineage was added in `0007`). Everything below was verified
against the migration files, the code, and a live run.

- [1. Scope](#1-scope)
- [2. Architecture](#2-architecture)
- [3. Data flow, end to end](#3-data-flow-end-to-end)
- [4. Schema reference](#4-schema-reference)
- [5. Incremental state](#5-incremental-state)
- [6. Data quality and lineage](#6-data-quality-and-lineage)
- [7. Local quickstart](#7-local-quickstart)
- [8. Operating the pipeline](#8-operating-the-pipeline)
- [9. Known issues and limitations](#9-known-issues-and-limitations)
- [10. Extending the pipeline](#10-extending-the-pipeline)

---

## 1. Scope

Phase 2 ingests FRC competition data from external sources into a PostgreSQL database
shaped for later metrics and ML work. It does **not** compute metrics, predictions, or
pick lists — that is Phase 3 onward. What it guarantees is that the data those phases
consume is complete, deduplicated, validated, traceable to its source, and safe to
re-sync at any time.

Sources: [The Blue Alliance](https://www.thebluealliance.com/apidocs) (events, matches,
teams) and [Statbotics](https://www.statbotics.io/) (EPA-based team-event metrics — the
client is correct as of 2026-07-25, but no EPA data has yet reached the canonical tables
because Statbotics's API is returning 500s; see
[§9.1](#91-statbotics-client-fixed-live-confirmation-still-pending-their-outage)).

---

## 2. Architecture

### 2.1 The four layers

```
  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │  EXTRACTION  │──▶│   LANDING    │──▶│   STAGING    │──▶│   SERVING    │
  │ source APIs  │   │ raw payloads │   │ validate +   │   │  canonical   │
  │              │   │ (immutable)  │   │  normalize   │   │   tables     │
  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
   TBA / Statbotics  raw_source_        Staging* models     teams, events,
   HTTP + retries    payloads (JSONB)   + quality checks    matches,
                     versioned, deduped rejects bad data    match_teams,
                                                            team_event_stats
```

Each layer has one job, and the boundaries are deliberate:

**Extraction** (`data/clients/`) talks HTTP and nothing else. Each connector validates
responses into Pydantic models and returns them *alongside the untouched response body*
(`SourceResponse`), so the layers below get typed access without anything being discarded.
Each knows its own API's shape; no connector knows about the database.

**Landing** (`data/landing/raw_writer.py`) stores raw payloads before any
interpretation, so the original data always survives a change in how we interpret it.
It deduplicates on a payload checksum: an identical payload is never stored twice, and a
changed payload lands as a new version with the previous one demoted out of
`is_current`. This is what makes incremental processing possible (see [§5](#5-incremental-state)).

**Staging** (`data/staging/`) turns source-shaped payloads into source-agnostic canonical
models, rejecting anything malformed (`validator.py`) or implausible
(`quality.py`) before it can reach the serving layer. TBA's `"frc1114"` becomes the int
`1114` here; TBA's `"qm"` becomes `"qualification"`.

**Serving** (`data/serving/repository.py`) upserts staging entities into the canonical
tables. Every write is `INSERT ... ON CONFLICT DO UPDATE` on the table's natural key, so
loading is idempotent by construction.

### 2.2 Module map

| Module | Responsibility |
|---|---|
| `data/config.py` | `Settings` — env/`.env` resolution, timeouts, retries |
| `data/clients/source_connector.py` | `SourceConnector` ABC (`source_name`, `close()`) and `SourceResponse` (raw + parsed) |
| `data/clients/http_retry.py` | Shared retry/backoff for transient HTTP failures |
| `data/clients/schemas.py` | Source-shaped response models (`EventSummary`, `Match`, `TeamInfo`, `Statbotics*`) |
| `data/clients/tba.py` | `TBAClient` — `fetch_event`, `fetch_event_list`, `fetch_event_matches`, `fetch_event_teams`, `fetch_team_info` |
| `data/clients/statbotics.py` | `StatboticsClient` — `fetch_event_match_stats`, `fetch_team_event_metrics` |
| `data/landing/raw_writer.py` | `RawPayloadWriter`, `RawPayloadRecord`, `compute_payload_checksum` |
| `data/staging/schemas.py` | Canonical staging models (`StagingTeam/Event/Match/TeamEventStats`) |
| `data/staging/validator.py` | Structural validation; `ValidationIssue`, `PayloadValidationError` |
| `data/staging/normalizer.py` | Source payload → staging model, per-source registries |
| `data/staging/quality.py` | Plausibility + referential checks, `DataQualityRecorder` |
| `data/serving/repository.py` | `CanonicalRepository` — upsert loaders, FK-safe ordering |
| `data/lineage.py` | `LineageStore` — canonical row ↔ raw payload provenance |
| `data/pipeline.py` | The four stages as independent functions |
| `data/orchestrator.py` | Run bookkeeping, watermarks, `sync_event`, CLI entry point |
| `database/connection.py` | `Database` — context-managed psycopg3 connections/cursors |
| `database/migrate.py` | Applies `migrations/*.sql` in sorted order |
| `database/verify_db.py` | Asserts every expected table exists |

### 2.3 The one-directional dependency rule

`data/orchestrator.py` imports `data/pipeline.py`, never the reverse. The stages in
`pipeline.py` know nothing about `pipeline_runs`, `source_watermarks`, or where issues
and lineage get written — the orchestrator owns all durable run state. This is why every
stage can be tested in isolation with no run state in existence, and it is worth
preserving when adding stages.

---

## 3. Data flow, end to end

What one `sync_event("2024casj")` actually does, in order:

1. **Extract** — `pipeline.extract_event`
   - `GET /event/2024casj` → 1 event payload
   - `GET /event/2024casj/matches` → 93 match payloads
   - `GET /event/2024casj/teams` → 42 team payloads
   - *Roster backfill*: any team appearing on a match roster but missing from the team
     list is fetched individually via `GET /team/frc{n}`. TBA's team list and match
     schedule are separate endpoints with no guarantee they agree, and a rostered team
     with no `teams` row would fail the entire load on a foreign key.
   - For each attending team, `GET /v3/team_event/{team}/{event}` from Statbotics. A
     failure here is **non-fatal** — recorded as a warning, and the TBA data still loads.
   - Each connector returns `SourceResponse(raw, parsed)`. The pipeline lands `raw` —
     the source's untouched response body, every field included — and uses `parsed`
     only for control flow (reading a team number to look up its metrics, for
     instance). See [§9.3](#93-what-lands-is-the-untouched-response-body).

2. **Land** — `pipeline.land` → `RawPayloadWriter.write_many`
   Each payload is checksummed and inserted into `raw_source_payloads`. Unchanged
   payloads insert nothing. Changed payloads insert a new row and demote the previous
   version's `is_current`.

3. **Build the quality context** — `quality.build_quality_context`
   Collects which team numbers and event keys will exist after this load (everything
   extracted now, plus anything already canonical from an earlier run), so referential
   checks can distinguish "missing" from "already present".

4. **Stage** — `pipeline.read_pending` + `pipeline.stage_batch`, per (source, object type)
   - `read_pending` selects `is_current` rows for these objects with
     `id > watermark` — i.e. only what has not already been promoted.
   - `stage_batch` validates, normalizes, and quality-screens each one. Rejections
     (structural or fatal-quality) are skipped and recorded; accepted entities get a
     `LineageEntry` pairing them with their raw payload id.

5. **Record issues** — `DataQualityRecorder.record`, **before** the load, so a run that
   subsequently fails still leaves its quality evidence behind.

6. **Load** — `pipeline.load` → `CanonicalRepository.load_all`
   Teams and events first, then matches (which reconcile `match_teams`) and
   `team_event_stats`. All upserts.

7. **Record lineage** — `LineageStore.record`, **after** the load, because a lineage row
   asserts that a canonical row exists.

8. **Advance watermarks** — the single advance point, reached only if every step above
   succeeded.

9. **Close the run** — `pipeline_runs` row marked `succeeded` with a per-stage
   `stage_counts` breakdown. On any exception: marked `failed` with the error, watermarks
   untouched, and the exception re-raised.

---

## 4. Schema reference

11 tables. Migrations are listed in [§8.4](#84-migrations).

#### `raw_source_payloads`

The landing layer. Immutable, append-only, versioned history of every payload ever
fetched.

- **PK** `id` (BIGSERIAL) — also the basis of all watermarks
- **Unique** `(source, source_object_type, source_object_id, payload_checksum)` — the
  dedup key (`0004`; it replaced a `(source, type, id)` unique index that would have
  allowed only one version per object)
- **Partial index** `(source, source_object_type, source_object_id) WHERE is_current`
- `payload_json` JSONB, `payload_checksum` (SHA-256 of the canonicalized payload),
  `is_current`, `fetch_timestamp`, `ingested_at`
- **Reserved, not populated:** `season`, `event_key`, `match_key`, `schema_version`

#### `teams`

- **PK** `team_number` (INT) — re-keyed from `team_key` TEXT in `0005`, because the
  staging layer deliberately strips source-specific key prefixes
- `name` (TBA's *nickname*, not the legal name), `city`, `state_province`, `country`,
  `rookie_year`, `last_updated`

#### `events`

- **PK** `event_key`
- `season` NOT NULL, `name`, `event_code`, `start_date`, `end_date`, `city`,
  `state_prov`, `country`, `last_updated`
- Note the column is `state_prov` here but `state_province` in `teams` and in the staging
  models; `CanonicalRepository` maps between them
- **Reserved, not populated:** `event_type`

#### `matches`

- **PK** `match_key`
- **FK** `event_key` → `events(event_key)`
- `season`, `competition_level` (canonical vocabulary: `qualification`, `eighthfinal`,
  `quarterfinal`, `semifinal`, `final`), `set_number`, `match_number`, `scheduled_time`,
  `score_red`, `score_blue`, `winning_alliance` (`red`/`blue`/`tie`/NULL)

#### `match_teams`

Roster junction — which teams played which match, on which alliance and station.

- **PK** `id`; **Unique** `(match_key, team_number)`
- **FKs** → `matches(match_key)`, → `teams(team_number)`
- **CHECK** `alliance_color IN ('red','blue')`
- A junction rather than array columns, so roster membership has real referential
  integrity. Reloading a match reconciles this table to the current roster, pruning
  teams no longer on it.

#### `team_event_stats`

One team's performance at one event, from Statbotics.

- **PK** `(team_number, event_key)` composite (`0005` replaced `0001`'s surrogate `id`)
- **FKs** → `teams(team_number)`, → `events(event_key)`
- `season`, `epa_total`, `epa_auto`, `epa_teleop`, `epa_endgame`, `wins`, `losses`,
  `ties`, `matches_played`
- `matches_played` is **derived** (`wins + losses + ties`) — Statbotics reports the
  breakdown but no game count — and is left NULL if any component is missing

#### `pipeline_runs`

One row per pipeline run.

- **PK** `id`; **CHECK** `status IN ('running','succeeded','failed')`
- `pipeline_name`, `source`, `scope_key` (the event key; `0006`), `started_at`,
  `finished_at`, `records_processed`, `error_message`, `stage_counts` JSONB (`0006`)
- A row stuck at `running` means the process died mid-run

#### `source_watermarks`

Durable incremental state. See [§5](#5-incremental-state).

- **PK** `id`; **Unique** `(source, object_type, scope_key)`
- `watermark_value` TEXT (holds an integer raw-payload id; TEXT so a future source could
  watermark on a timestamp or opaque cursor), `last_synced_at`, `last_updated`

#### `data_quality_issues`

Every detected quality problem, one row per detection.

- **PK** `id`; **CHECK** `severity IN ('warning','error','critical')`
- **FKs** `pipeline_run_id` → `pipeline_runs(id)` **ON DELETE CASCADE**,
  `raw_payload_id` → `raw_source_payloads(id)` **ON DELETE CASCADE** (`0007`)
- `source`, `object_type`, `object_id`, `field`, `issue_type`, `description`,
  `detected_at`
- **Reserved, not populated:** `resolved`, `resolved_at` (no resolution workflow yet)

#### `canonical_lineage`

Audit trail from a canonical row back to the raw payload it was built from (`0007`).

- **PK** `id`; **Unique** `(entity_type, entity_key, raw_payload_id)` — makes recording
  idempotent
- **FKs** `raw_payload_id` → `raw_source_payloads(id)` **ON DELETE CASCADE**,
  `pipeline_run_id` → `pipeline_runs(id)` **ON DELETE SET NULL** (provenance stays true
  even if the run record is purged)
- `entity_type` uses the same vocabulary as `raw_source_payloads.source_object_type`:
  `event`, `team`, `match`, `team_event`
- `entity_key` is the canonical natural key as text: `team_number`, `event_key`,
  `match_key`, or `"{team_number}_{event_key}"`
- `match_teams` has no entity type of its own — its rows are traced through their parent
  match

#### `migrations_applied`

Created by `database/migrate.py` (not by a migration file). **PK** `migration_file`,
plus `applied_at`.

---

## 5. Incremental state

**A watermark is the highest `raw_source_payloads.id` already promoted into the canonical
tables**, stored per `(source, object_type, event)`.

This works because the landing layer already deduplicates. Re-syncing an unchanged event
lands zero new rows, so `read_pending`'s `id > watermark` returns nothing and the staging
and serving stages are genuine **no-ops** — not deduplicated writes, but no work at all.
When something does change, only the changed object lands a new (higher) id and only that
object is reprocessed.

Three properties worth understanding before changing any of this:

**Watermarks advance at exactly one point** — after the serving stage succeeds. A failure
anywhere leaves every watermark where it was, so the next run reprocesses that ground.
That is safe because every canonical write is an upsert: repeating a partially-completed
run converges instead of duplicating.

**Advance is contiguous-prefix, not maximum.** If payload ids 21, 22, 23 are pending and
22 is rejected, the watermark advances to **21**, not 23 — even though 23 was loaded.
A rejected payload is therefore retried on every subsequent run rather than being
skipped permanently, and it disappears from the pending set automatically if the source
later corrects it (the correction lands as the new `is_current` row). The cost is that a
permanently-bad payload is re-read and re-reported every run; that is deliberate, and it
is what keeps `data_quality_issues` able to answer "how long has this been broken".

**Watermarks never move backwards.** `WatermarkStore.advance` uses `GREATEST`, so a
replayed or out-of-order run cannot rewind progress.

Watermarks are scoped per event, including for teams: a team attending two events is
tracked independently under each, so one event's run can never advance another's. The
cost is one idempotent re-upsert of that team per event.

---

## 6. Data quality and lineage

### 6.1 Two layers of rejection, one mechanism

`data/staging/validator.py` rejects **malformed** payloads (missing required fields, wrong
types, a team on both alliances). `data/staging/quality.py` judges payloads that are
well-formed but **not believable** or that reference things which will not exist.

Both flow through the same path in `pipeline.stage_batch`: skipped, recorded in
`data_quality_issues`, watermark held short of them, retried next run. There is
deliberately only one rejection mechanism.

### 6.2 Severity is policy

| Severity | Effect | Checks |
|---|---|---|
| `error` / `critical` | **Record rejected — never reaches the canonical tables** | structural validation failure; negative alliance score; negative wins/losses/ties; `matches_played` contradicting `wins+losses+ties`; event ending before it starts; `team_number <= 0`; roster or stats referencing a team/event that will not exist |
| `warning` | Recorded, record still loads | season outside 1992–next year; `team_number` above 100 000; alliance size ≠ 3 (when non-empty); a declared winner who was strictly outscored; alliance score above 1 000; `scheduled_time` more than 730 days out or before 1992; implausible `rookie_year`; `epa_total` below −50; extraction failures |

Everything judgemental is a warning **on purpose**. FRC scoring rules change every
season, so a plausibility ceiling that looks generous today will eventually be exceeded
by a real match — and silently dropping that match would corrupt an event's record while
the run still reported success. A rule that discards real data is worse than no rule.

Two checks that were considered and deliberately **not** implemented:
`epa_total` vs. `epa_auto + epa_teleop + epa_endgame` (Statbotics does not document those
as summing exactly, so any tolerance would be invented statistics), and flagging a
declared winner of a *tied* match (playoff tiebreakers legitimately do this).

### 6.3 Tracing a canonical row to its source

```python
from data.config import Settings
from data.lineage import LineageStore
from database.connection import Database, DatabaseConfig

store = LineageStore(Database(DatabaseConfig(Settings().database_url)))

raw_id, payload = store.trace_to_payload("match", "2024casj_qm1")
# -> (1378, {'key': '2024casj_qm1', 'alliances': {'red': {'teams': ['frc841', ...]}}, ...})

store.trace("match", "2024casj_qm1")   # every payload version, oldest first
store.latest("team", "841")            # LineageRecord(entity_type='team', entity_key='841',
                                       #   raw_payload_id=1367, source='tba', pipeline_run_id=108)
```

---

## 7. Local quickstart

Verified on Linux with Python 3.11 and PostgreSQL 18. Every command below was run in this
repository.

### 7.1 Prerequisites

- Python 3.11+
- A running PostgreSQL server you can create a database in
- A TBA API key ([free, from your TBA account](https://www.thebluealliance.com/account))

### 7.2 Set up the environment

```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

All commands below use `venv/bin/python` explicitly, so no shell activation is needed.
(On Windows the equivalent is `venv\Scripts\python.exe`.)

### 7.3 Create the database

```bash
createdb -U postgres -h localhost stratai
```

Pass `-U` explicitly with a role that exists in your cluster. A bare `createdb stratai`
connects as your OS user over the local socket, which fails with
`FATAL: role "<your-username>" does not exist` unless a matching Postgres role happens to
exist. `createdb` will prompt for the password; export `PGPASSWORD` first to avoid the
prompt. The equivalent via psql is
`psql -U postgres -h localhost -c "CREATE DATABASE stratai;"`.

### 7.4 Configure `.env`

```bash
cp .env.example .env
```

Then edit `.env`:

```text
DATABASE_URL=postgresql://user:password@localhost:5432/stratai
TBA_API_KEY=your_the_blue_alliance_api_key
# STATBOTICS_API_KEY is optional — the public API needs no auth
ENV=development
```

`DATABASE_URL` must be a valid PostgreSQL DSN (it is parsed as one) and `TBA_API_KEY` is
required — `Settings()` fails fast if either is missing.

### 7.5 Apply migrations

```bash
venv/bin/python database/migrate.py
```

Idempotent: already-applied migrations are recorded in `migrations_applied` and skipped.
`database/init_db.py` is an equivalent alias that calls the same function.

### 7.6 Verify the schema

```bash
venv/bin/python database/verify_db.py
# Database verification passed. All expected tables exist.
```

### 7.7 Run the pipeline for one event

```bash
venv/bin/python -m data.orchestrator 2024casj
```

Real output from this repository (abbreviated):

```text
INFO data.pipeline: Extracted event 2024casj: event=1, team=42, match=93, team_event=0
INFO data.pipeline: Landed new raw payloads: {'tba.event': 1, 'tba.team': 42, 'tba.match': 93, 'statbotics.team_event': 0}
INFO data.staging.quality: Recorded 42 data quality issue(s) for run 108 (0 fatal)
INFO data.pipeline: Loaded canonical records: {'teams': 42, 'events': 1, 'matches': 93, 'team_event_stats': 0}
INFO data.lineage: Recorded lineage for 136 canonical entity version(s) in run 108
run 108: landed={...} loaded={...} skipped=0 issues=42 (fatal=0) lineage=136 extraction_errors=42
```

**Expect the Statbotics warnings.** `team_event=0`, `team_event_stats: 0`, and one
`extraction_failure` warning per team are the current normal state — see
[§9.1](#91-statbotics-client-fixed-live-confirmation-still-pending-their-outage). The TBA half of the pipeline is
fully working. Add `--no-statbotics` to skip those calls entirely and silence the noise.

Run it again and it should report all zeros — that is the idempotence guarantee from
[§5](#5-incremental-state) working:

```bash
venv/bin/python -m data.orchestrator 2024casj
# landed={'tba.event': 0, 'tba.team': 0, 'tba.match': 0, ...} loaded={'teams': 0, 'events': 0, ...}
```

### 7.8 Run the tests

```bash
venv/bin/python -m pytest -q
```

Expected: **all tests pass, 3 skipped.** No `--deselect` flag is needed — earlier versions
of this document told you to skip one config test, which was fixed on 2026-07-25
([§9.2](#92-known-failing-config-test)).

The 3 skips are integration tests that self-skip when no database is reachable via
`DATABASE_URL`; with a working database they run.

---

## 8. Operating the pipeline

### 8.1 CLI

```bash
venv/bin/python -m data.orchestrator --help
```

```text
usage: orchestrator.py [-h] [--no-statbotics] event_key

positional arguments:
  event_key        TBA event key, e.g. 2025casj

options:
  --no-statbotics  Skip Statbotics EPA metrics (TBA data only).
```

### 8.2 Inspecting a run

```sql
-- most recent runs
SELECT id, pipeline_name, scope_key, status, records_processed, error_message
FROM pipeline_runs ORDER BY id DESC LIMIT 10;

-- per-stage breakdown for one run
SELECT stage_counts FROM pipeline_runs WHERE id = 108;

-- incremental position per source
SELECT source, object_type, scope_key, watermark_value, last_synced_at
FROM source_watermarks ORDER BY source, object_type;

-- unresolved quality issues, worst first
SELECT severity, issue_type, object_type, object_id, field, description
FROM data_quality_issues
WHERE NOT resolved
ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1 ELSE 2 END, id;

-- where did this canonical row come from?
SELECT l.raw_payload_id, l.source, l.pipeline_run_id, r.fetch_timestamp
FROM canonical_lineage l JOIN raw_source_payloads r ON r.id = l.raw_payload_id
WHERE l.entity_type = 'match' AND l.entity_key = '2024casj_qm1'
ORDER BY l.raw_payload_id;
```

`DataQualityRecorder.open_issues(object_type=..., object_id=..., severity=...)` is the
Python equivalent of the third query.

### 8.3 Re-syncing and back-filling

Re-running `sync_event` for an event is always safe and cheap. To **force** a full
reprocess of an event without discarding raw history, reset its watermarks — the raw rows
stay, and every current payload is re-promoted through staging:

```sql
DELETE FROM source_watermarks WHERE scope_key = '2024casj';
```

### 8.4 Migrations

| File | What it does |
|---|---|
| `0001_initial.sql` | `raw_source_payloads` + first canonical tables (`teams` keyed on `team_key`) |
| `0002_add_indexes.sql` | Lookup indexes on the canonical tables |
| `0003_pipeline_observability.sql` | `pipeline_runs`, `source_watermarks`, `data_quality_issues` |
| `0004_raw_payload_dedup_index.sql` | Dedup key now includes `payload_checksum`, enabling payload versioning |
| `0005_canonical.sql` | Re-keys the canonical layer to `team_number`; composite PK on `team_event_stats` |
| `0006_pipeline_run_scope.sql` | `pipeline_runs.scope_key`, `pipeline_runs.stage_counts` |
| `0007_data_quality_lineage.sql` | `data_quality_issues.raw_payload_id`/`field` + cascades; creates `canonical_lineage` |

Migrations are plain SQL applied in filename order and recorded in `migrations_applied`.
**There is no Alembic and none should be added.** To add one, create
`database/migrations/0008_<name>.sql` and run `database/migrate.py`.

---

## 9. Known issues and limitations

### 9.1 Statbotics client fixed; live confirmation still pending their outage

**Fixed on 2026-07-25.** The client was pointed at `api.statbotics.org`, a host that
**does not resolve at all**, so every lookup failed with a DNS error and
`team_event_stats` was never populated. Two things were wrong and both are corrected:

| | Before | Now |
|---|---|---|
| Base URL | `https://api.statbotics.org/v3` (no such host) | `https://api.statbotics.io/v3` |
| Paths | `/team_event/{team}/{event}`, `/matches?event=` | unchanged — these were already right |
| Response shape | flat `epa_total`, `epa_auto`, `wins`, … | nested `epa.total_points`, `epa.breakdown.auto_points`, `record.total.wins`, … flattened by `StatboticsTeamEventMetrics` |

The nesting is absorbed in the response models (`data/clients/schemas.py`), so the client,
the staging normalizer, and `team_event_stats` all still work in flat fields — one place
knows the source's structure.

**What is still unverified.** Statbotics's API was returning HTTP 500 for every
`/v3/*` endpoint throughout the fix — from their own infrastructure (`Google Frontend`,
`x-cloud-trace-context`), with their root path flapping between 200 and 500. So the
corrected shape is derived from Statbotics's published response serializer, **not captured
from a live response**, and `team_event_stats` is **still empty after a real run**:

```text
run 248: ... loaded={'teams': 0, 'events': 0, 'matches': 0, 'team_event_stats': 0} extraction_errors=42
WARNING data.pipeline: Statbotics metrics unavailable for team 987 at 2024casj:
  Server error '500 Internal Server Error' for url 'https://api.statbotics.io/v3/team_event/987/2024casj'
```

That the failure changed from `[Errno -2] Name or service not known` to an HTTP 500 from
`api.statbotics.io` is itself the evidence the client now reaches the real service.

**To confirm once their API recovers:** run
`venv/bin/python -m data.orchestrator 2024casj` and check that `team_event_stats` gains a
row per attending team. If the live shape differs from what was inferred,
`tests/test_statbotics_client.py::test_model_matches_recorded_statbotics_response` is the
test that should fail — re-record
`tests/fixtures/statbotics_team_event_2024casj.json` from the real response (its
`_fixture_provenance` block explains how).

What *is* proven: the real nested shape flows end to end. The integration tests in
`tests/test_pipeline.py` and `tests/test_data_quality.py` feed nested Statbotics payloads
through landing, staging, and serving against a real database and assert the resulting
`team_event_stats` rows, including `matches_played`.

The pipeline's graceful degradation held throughout: 42 failed Statbotics lookups never
prevented the 136 TBA records from loading.

### 9.2 Known failing config test — RESOLVED 2026-07-25

`tests/test_config.py::test_settings_allows_missing_statbotics_api_key` used to fail in any
full-suite run, and was worked around with `--deselect` from Milestone 7 through 10. **It
now passes; no deselect flag is needed anywhere.** Recorded here because old commands and
CI snippets carrying that `--deselect` will still be circulating.

The cause was test isolation, not configuration. `Settings()` calls `load_dotenv`, which
mutates `os.environ` for the whole process and never undoes it, so the project's real
`.env` values leak into every later `Settings()` in the same session — and in a full-suite
run that leak happens during *collection*, because several modules evaluate
`pytest.mark.skipif(not _database_available(), ...)` at import time. The test cleared only
`STATBOTICS_API_KEY`, so the leaked `DATABASE_URL` shadowed its temporary `.env`.
`load_dotenv`'s refusal to override a real environment variable is correct behaviour and
was never the bug; its two sibling tests passed only because they happened to clear all
four variables by hand.

Fixed with an autouse fixture in `tests/test_config.py` that clears every Settings-backed
variable before each test, driven by `Settings.model_fields` so a newly added setting
cannot silently reintroduce the leak. Production config behaviour is unchanged —
deliberately: making `.env` override real environment variables would let a stale file in a
deployed image point a real run at the wrong database.

### 9.3 What lands is the untouched response body — RESOLVED 2026-07-25

Until 2026-07-25 the clients validated responses into Pydantic models and discarded the
original body, so what landed was `model_dump(mode="json", by_alias=True)` — a projection
that dropped every field no model declared, making those fields invisible to the canonical
tables *and* to the dedup checksum, so a change confined to one was never detected as a new
version.

Connectors now return `SourceResponse(raw, parsed)`:

- **`raw`** — exactly what the API sent. This is what the landing layer stores and
  checksums, so nothing is lost and any change is detected.
- **`parsed`** — the validated model, for typed control flow. Source-specific shapes are
  normalized here (Statbotics's nested `epa`/`record` objects are flattened by the model's
  own validator), but this is a *view* of `raw`, never a replacement for it.

Capturing a new field no longer requires widening a model first. Real fields recovered for
`2024casj` that had been discarded: match `score_breakdown` (the per-match scoring detail
Phase 3's defense and feeding ratings need), `videos`, `actual_time`, `predicted_time`,
event `event_type` and `week`, team legal `name` and geo fields.

**Storage:** raw bodies are ~8.9× the projection as JSON text (303 KiB vs 34 KiB per
event), but JSONB compresses on disk — measured 140 kB vs 46 kB for one event, ~3×. A full
season is single-digit MB either way.

**One-time re-land:** the checksum *algorithm* is unchanged; only its input became the raw
body. The first run after this change therefore lands one new version of every
already-stored object (136 for `2024casj`, so `raw_source_payloads` went 136 → 272) and
re-upserts the canonical rows once. Both payload versions are retained, since the landing
layer never rewrites history. Subsequent runs are no-ops again — verified: the second run
reported `landed={...: 0}` and `loaded={...: 0}`.

**The roster trap this exposed.** TBA's real alliance roster field is `team_keys`. The old
projection renamed it to `MatchAllianceResult`'s alias `teams`, and staging read only that
name — so reading a raw body with the old code produced an *empty* roster beside a real
score, silently, because the quality layer deliberately does not flag an empty alliance (an
unplayed playoff match has none). Every `match_teams` row would have been pruned while the
run reported success. `tba_alliance_team_keys` now reads `team_keys` with a `teams`
fallback, so both the raw bodies and the projections already in the landing layer work.
`tests/test_raw_body_preservation.py` guards this against a real captured payload.

### 9.4 Permanently skipped schema test — RESOLVED 2026-07-25 (deleted)

`tests/test_verify_database.py` used an unconditional `@pytest.mark.skip`, so it never ran
even with a working database, and its expected-table list predated `canonical_lineage`.
**It has been deleted**, because everything it was meant to assert is now covered more
thoroughly and in both directions:

| What it checked | Where that lives now |
|---|---|
| migrations apply | `test_docs_contract.py`'s `database` fixture; `test_migrations.py` |
| its 10 expected tables are a *subset* of `pg_tables` | `test_documented_tables_and_actual_tables_are_the_same_set` — bidirectional equality over all 11 tables, so an undocumented new table also fails |
| its own hardcoded table list | `test_verify_db_expected_tables_match_the_documented_set`, which calls `verify_database()` for real |

`database/verify_db.py` itself is unchanged and still the canonical expected-table list.

### 9.5 Other limitations

- **Statbotics costs one request per team per event** — the API exposes team-event metrics
  only per `(team, event)`. Fine for one event; needs revisiting for a season backfill.
- **Extraction is always a full fetch.** Neither source exposes a "changed since"
  endpoint this pipeline uses, so incrementality is achieved downstream (landing dedup +
  watermarks), not by fetching less.
- **Five reserved columns are never populated** — see [§4](#4-schema-reference). They are
  intentionally retained.
- **Sentinel test fixtures must keep their event key and payload year consistent**: the
  staging layer derives a match's season from its *event key*, so a `9997…` key with
  `"year": 2025` produces season-9997 matches that trip plausibility warnings.
- **Tests asserting on `data_quality_issues` or `canonical_lineage` must scope by object
  id, not just object type.** Both are shared append-only audit tables, and a real
  pipeline run (which [§7.7](#77-run-the-pipeline-for-one-event) tells you to do) leaves
  genuine rows behind — a run of `2024casj` alone adds one `extraction_failure` warning
  per attending team, per run. Counting by `object_type` picks those up and the assertion
  fails for reasons unrelated to the test.
- **Only single-event sync exists.** There is no whole-season or multi-event driver yet;
  `TBAClient.fetch_event_list` and `StatboticsClient.fetch_event_match_stats` are
  implemented but not yet wired into any flow.

---

## 10. Extending the pipeline

### Adding a source

1. Add a connector in `data/clients/` subclassing `SourceConnector` (provide
   `source_name` and `close()`; each connector defines its own `fetch_*` methods — the
   base class deliberately does not dictate them).
2. Add response models to `data/clients/schemas.py`.
3. Write `normalize_<source>_<entity>` in `data/staging/normalizer.py` and register it in
   the relevant registry. The canonical `Staging*` models should not need to change.
4. Add a validator in `data/staging/validator.py` if the source needs structural checks
   beyond what its Pydantic model enforces.
5. Extend `pipeline.extract_event` to produce an `ExtractionBatch` for the new source.
   Landing, staging dispatch, watermarks, quality recording, and lineage all key off
   `(source, object_type)` and need no changes.

### Adding a quality check

Add it to the relevant `_check_*` function in `data/staging/quality.py`. Choose severity
by the rule in [§6.2](#62-severity-is-policy): reject only if the record is meaningless
or unloadable, otherwise warn. Fatal checks automatically inherit the existing
rejection/retry machinery.

### Adding a migration

Create `database/migrations/0008_<name>.sql`, keeping it additive where possible, and run
`database/migrate.py`. Then update [§8.4](#84-migrations) and the schema reference in
[§4](#4-schema-reference) — `tests/test_docs_contract.py` fails if a table exists in the
database but is not documented here, or vice versa.
