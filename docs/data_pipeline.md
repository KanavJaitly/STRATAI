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
pick lists — that is Phase 3 onward. Phase 3 has since added two **empty** tables to the
same database (`scouting_observations`, `team_metrics`, via `0008`); no pipeline described
in this document reads or writes them, and they are covered only in
[§4.1](#41-phase-3-metrics-tables-schema-only). What it guarantees is that the data those phases
consume is complete, deduplicated, validated, traceable to its source, and safe to
re-sync at any time.

Sources: [The Blue Alliance](https://www.thebluealliance.com/apidocs) (events, matches,
teams) and [Statbotics](https://www.statbotics.io/) (EPA-based team-event metrics — flowing
into the canonical tables and confirmed against a live response on 2026-08-01; see
[§9.1](#91-statbotics-epa-confirmed-live-resolved-2026-08-01)).

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
| `data/orchestrator.py` | Run bookkeeping, watermarks, `sync_event`, its `sync_season` / `watch_event` wrappers, CLI entry point |
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
     instance). See [§9.3](#93-what-lands-is-the-untouched-response-body--resolved-2026-07-25).

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

13 tables. Migrations are listed in [§8.6](#86-migrations).

The last two — `scouting_observations` and `team_metrics` — are **Phase 3 tables, created
empty by `0008` and not written by anything yet**. They are documented here because this
is the schema reference and the contract tests require every table in the database to
appear in it, not because the Phase 2 pipeline touches them. See
[§4.1](#41-phase-3-metrics-tables-schema-only).

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
- **A scheduled but not-yet-played match is a normal, fully-loaded row** with its
  `scheduled_time` and `score_red` / `score_blue` / `winning_alliance` all NULL.
  `score_red IS NULL` is the reliable test for "no result yet"; the two scores are
  always both NULL or both set, never one of each. TBA marks an unplayed match with a
  score of **-1** on both alliances, which the normalizer resolves to NULL — that
  sentinel never reaches this table, so nothing downstream needs to know about it.
  **Anything aggregating results must exclude these rows explicitly** — during a live
  event most of the schedule is unplayed.
- An unplayed match normally carries its real roster, but **not always**: if the roster has
  not been assigned yet, TBA publishes it as `["frc0","frc0","frc0"]` and the match loads
  with **no `match_teams` rows at all** (see
  [§9.7](#97-tbas-frc0-unassigned-roster-placeholder--resolved-2026-08-01)). An empty
  roster is a legitimate state, so anything joining `matches` to `match_teams` must not
  assume six rows per match.

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

### 4.1 Phase 3 metrics tables

Created by `0008_metrics_schema.sql`. **`team_metrics` is still empty; nothing writes it
yet.** `scouting_observations` is no longer empty as of Phase 3 Milestone 7: the human
scouting submission path (`data/metrics/submission.py`) is a real, tested writer, landing a
submission via `RawPayloadWriter` (source `"human_scout"`) and loading it into this table
via `CanonicalRepository.load_scouting_observation` once `data.pipeline.stage_batch`
validates and normalizes it (Milestones 5-6's `data/metrics/validator.py`/`normalizer.py`).
See §4.2 for the anti-abuse gate this path sits behind.

Phase 3 Milestone 3 (`data/metrics/statistics.py`) implements the pure statistical
functions — `average_score`, `score_stddev`, `consistency_rating`, `classify_match_days`,
`reliability_score` — over an already-extracted list of scores, and Phase 3 Milestone 4
(`data/metrics/history.py`) supplies that list for real: `get_team_match_history` reads
`matches`/`match_teams` and returns one team's own scores at one event, plus
`matches_scheduled`/`matches_used`. Phase 3 Milestone 8 (`data/metrics/aggregation.py`)
implements the defense/feeding side the same way: `aggregate_defense_feeding` takes an
already-fetched `list[ScoutingObservation]` for one team at one event and returns a
`DefenseFeedingProfile` (median score, population-stddev-based agreement, a
2-observation minimum before anything is reported). None of M3/M4/M8 writes
`team_metrics` — they are pure functions and a read path, with no writer between them and
that table yet. The metrics computation pipeline that would compose M3+M4+M8 into a
`TeamMetrics` and write `team_metrics` is a later Phase 3 milestone. Both tables were
created ahead of any of this logic so the storage shape was fixed first, for the same
reason Milestone 1 fixed the model shape before any of it was written.

Every column in both tables is a field of a model in `data/metrics/schemas.py`, under its
own name, with two marked exceptions. The `CHECK` constraints are transcriptions of that
module's pydantic `model_validator`s rather than new policy, so a row those models would
refuse to construct cannot be stored either.

#### `scouting_observations`

One scout's (or ScoutRadioz's) direct assessment of one team in one match —
`ScoutingObservation`, one row per model instance. **This is the source of truth for
defense and feeding**; there is deliberately no path anywhere from match scores to a
defense or feeding number.

- **PK** `id` (BIGSERIAL — *not* a model field; a surrogate key, since the natural key is
  the composite below, as with `match_teams` and `canonical_lineage`)
- **Unique** `(match_key, team_number, scout_identifier, source)` — one scout rates one
  team in one match once per source; a resubmission updates that row rather than adding a
  second opinion
- **FKs** → `matches(match_key)`, → `teams(team_number)`, → `events(event_key)`, all with
  **no ON DELETE action** (matching `match_teams`/`team_event_stats`)
- **FK** `raw_payload_id` → `raw_source_payloads(id)` **ON DELETE SET NULL** — *not* a
  model field; lineage back to the payload an observation arrived in. Nullable, because an
  observation submitted directly to StratAI never passes through the landing layer
- `defense_rating`, `feeding_rating` (INT `0`–`5`, either may be NULL but **not both** —
  `CHECK`), `notes`, `submitted_at`
- **`0` is a real rating** ("confirmed no defense/feeding observed"), never a
  missing-data sentinel
- `event_key` is **denormalized** from `match_key` (derivable via `matches.event_key`)
  because "every observation for this event" is the expected dominant access pattern.
  Agreement between the two is deliberately **not** enforced here — that is a
  raw-payload validation concern for a later milestone
- `scout_identifier` is **free text, not a foreign key**. There is no scouting
  user-identity system in Phase 3; nothing prevents spoofing or duplicate scout names.
  A documented MVP limitation
- The `0`–`5` bounds are hardcoded in SQL (it cannot import `MIN_RATING`/`MAX_RATING`), so
  changing the rating scale requires a migration

**Why `SET NULL` and not `CASCADE` on `raw_payload_id`:** `0007` sets two precedents — a
purely subordinate audit row cascades (`canonical_lineage.raw_payload_id`), while a
provenance pointer hanging off a row that must outlive it is set null
(`canonical_lineage.pipeline_run_id`). Observations are the second case, and are the only
irreplaceable data in the system: every other table is re-fetchable from TBA or Statbotics,
but a human's rating of a match played three weeks ago is not. Purging a raw payload —
which integration teardown does — must never take scouting data with it. Losing the
provenance pointer is recoverable; losing the observation is not.

#### `team_metrics`

The complete served metrics object for one team at one event — `TeamMetrics`, the literal
answer to Phase 3's Definition of Done.

- **PK** `(team_number, event_key)` composite — the same keying as `team_event_stats`
- **FKs** → `teams(team_number)`, → `events(event_key)`, no ON DELETE action
- **Index** on `event_key`. There is deliberately **no** `team_number` index: the PK
  already covers it on its leading column, exactly as `0005` records for `team_event_stats`
- `season`, `computed_at`
- From `ScoringProfile`: `matches_scheduled`, `matches_used` (both NOT NULL), plus nullable
  `average_score`, `score_stddev`, `consistency_rating`, `reliability_score`,
  `good_day_count`, `average_day_count`, `bad_day_count`
- From `DefenseFeedingProfile`: `defense_score`, `defense_observation_count`,
  `defense_agreement`, `defense_insufficient_data`, the same four for `feeding_*`, and
  `contributing_sources` TEXT[]

**`TeamMetrics` composes two sub-models; the table flattens them.** The nesting is
fixed-arity — exactly one `ScoringProfile` and one `DefenseFeedingProfile`, never optional,
never a list — and the two share no field names, so every column keeps its model name
unprefixed and reassembly is mechanical. JSONB would have made the column types and the
constraints below unenforceable; separate tables would have turned one upsert into two
writes for no gain. **The served object stays composed; only its storage is flat** — the
same split `StagingMatch` already makes when it flattens TBA's alliance nesting into
`score_red`/`score_blue`.

**A current-state snapshot, upserted in place** — not an append-only history, consistent
with `team_event_stats`. Recomputing during a live event overwrites the previous value.
"What did we know as of match 5" is answered by replaying the pipeline against a historical
cut of the already-versioned `raw_source_payloads`, not by storing every intermediate
snapshot.

**Naming:** the Phase 3 roadmap calls for a `last_computed_at` column; the model's field is
`computed_at`, and that is the name used. Since the row is upserted in place, the timestamp
of the computation that produced it *is* the last-computed time — the two names describe
the same column, and the model's spelling keeps every column traceable to a model field.

**How "no data" is represented**, mirroring the models exactly — the two tracks use
different mechanisms and the schema does not unify them:

- **`ScoringProfile` has no flag.** `matches_used` *is* the signal, and NULL always means
  "not computed" for a reason it determines: `0` means there is no data at all (every value
  column NULL); `1` means variance is undefined for one sample (`average_score` may be set,
  but `score_stddev`, `consistency_rating`, `reliability_score` and the day counts are
  NULL). `CHECK`s enforce both, plus `matches_used <= matches_scheduled` and the day counts
  being all-set-or-all-NULL and summing to `matches_used`
- **`DefenseFeedingProfile` has explicit flags.** `defense_score` is non-NULL **if and only
  if** `defense_insufficient_data` is false, and zero observations force the flag (same for
  feeding). This is load-bearing for *"defense/feeding scores = directly measured, NOT
  inferred"*: a confident-looking score built on no observations is not merely rejected by
  the model, it is **unstorable**
- `contributing_sources` is empty if and only if both tracks are insufficient — if either
  produced a real score, at least one source must be named as having produced it

`average_score` and `score_stddev` are bounded below by `0` but deliberately **not above**:
a future game could score higher than anything seen so far, and a hard ceiling would
eventually reject real data — the reasoning that rejected an invented EPA tolerance in
Milestone 9. The float columns are `DOUBLE PRECISION` rather than `team_event_stats`'
`NUMERIC`, because the models declare them as `float` and psycopg3 returns `NUMERIC` as
`Decimal`; nothing recomputes from `team_event_stats` yet, but this table is read back and
reassembled into a model on every access.

### 4.2 Phase 3 scouting submission table

Created by `0009_scouting_access_codes.sql`, as part of Milestone 7's human scouting
submission path (`data/metrics/submission.py`).

#### `scouting_access_codes`

A lightweight, no-full-auth anti-abuse gate — not an identity system. There is still no
scouting-user-identity system in Phase 3 (`scouting_observations.scout_identifier` remains
free text); this only deters casual or accidental cross-event submission noise.

- **PK** `event_key`, **FK** → `events(event_key)`, no ON DELETE action
- `access_code` (`TEXT`, `CHECK (length(access_code) > 0)`), `created_at`

**A row's absence, not its presence, is the default-open state:** an event with no row here
accepts submissions without a code. Phase 3 has no admin surface yet to let a coordinator
set one, so requiring a code unconditionally would make every event unsubmittable out of
the box. An event only becomes gated once a coordinator (via direct SQL, today — no
tooling exists yet) inserts a row for it; submissions to that event must then supply the
exact matching `access_code` or are rejected with `ScoutingAccessDeniedError`, before
anything is landed.

A dedicated table, not a column on `events`: `events` is a Phase 2 canonical table sourced
from TBA, and this is a Phase-3-only, scouting-specific concern — the same reasoning that
already kept `scouting_observations`/`team_metrics` as their own tables referencing
`events`/`teams` by FK rather than columns bolted onto them.

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
| `warning` | Recorded, record still loads | season outside 1992–next year; `team_number` above 100 000; alliance size ≠ 3 (when non-empty); a declared winner who was strictly outscored; alliance score above 1 000; TBA's unplayed sentinel on only *one* alliance; `scheduled_time` more than 730 days out or before 1992; implausible `rookie_year`; `epa_total` below −50; extraction failures |

"Negative alliance score" above means a score that is genuinely impossible. It does **not**
mean TBA's `-1` unplayed-match sentinel, which the normalizer resolves to NULL before the
quality layer ever sees it (see [§4](#4-schema-reference), `matches`). An unplayed match is
**valid and is not flagged at all** — it must not be, since during a live event most of the
schedule is unplayed. Resolving the sentinel upstream is what lets this rejection stay
fatal: relaxing it instead would have loaded every unplayed match as a **fabricated tie**,
because the two `-1`s compare equal.

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

Real output from this repository (abbreviated) — **captured 2026-07-24, during the
Statbotics outage**, which is why every Statbotics count is zero:

```text
INFO data.pipeline: Extracted event 2024casj: event=1, team=42, match=93, team_event=0
INFO data.pipeline: Landed new raw payloads: {'tba.event': 1, 'tba.team': 42, 'tba.match': 93, 'statbotics.team_event': 0}
INFO data.staging.quality: Recorded 42 data quality issue(s) for run 108 (0 fatal)
INFO data.pipeline: Loaded canonical records: {'teams': 42, 'events': 1, 'matches': 93, 'team_event_stats': 0}
INFO data.lineage: Recorded lineage for 136 canonical entity version(s) in run 108
run 108: landed={...} loaded={...} skipped=0 issues=42 (fatal=0) lineage=136 extraction_errors=42
```

**Those zeros are no longer what to expect.** Statbotics recovered on 2026-08-01
([§9.1](#91-statbotics-epa-confirmed-live-resolved-2026-08-01)), so a run today should
populate `team_event=42` and `team_event_stats: 42` for this event and emit no
`extraction_failure` warnings. Add `--no-statbotics` to skip those calls entirely.

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

Expected, with a working database: **all tests pass, 0 skipped.** No `--deselect` flag is
needed — earlier versions of this document told you to skip one config test, which was
fixed on 2026-07-25 ([§9.2](#92-known-failing-config-test--resolved-2026-07-25)).

Every test in the suite is now either pure-unit or an integration test guarded by the
conditional `requires_db` marker:

```python
requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)
```

So the skip count tells you about your environment, not about the suite: **0 skipped**
means the database is reachable and the integration tests really ran, and a non-zero count
means `DATABASE_URL` does not point at a live PostgreSQL. Nothing is skipped
unconditionally any more — until 2026-08-01 three tests used a bare `@pytest.mark.skip`
that never ran even with a working database, while this section wrongly described them as
self-skipping. One of those three carried a teardown that would have deleted the entire
landing layer; see [§9.6](#96-destructive-integration-teardown--resolved-2026-08-01).

---

## 8. Operating the pipeline

### 8.1 CLI

```bash
venv/bin/python -m data.orchestrator --help
```

```text
usage: orchestrator.py [-h] [--season YEAR] [--no-statbotics]
                       [--delay SECONDS] [--watch EVENT_KEY]
                       [--interval SECONDS] [--max-interval SECONDS]
                       [--statbotics-interval SECONDS] [--settle-polls N]
                       [--max-failures N] [--max-duration DURATION]
                       [event_key]

positional arguments:
  event_key             TBA event key, e.g. 2025casj

options:
  --season YEAR         Sync every official event of a season in chronological
                        order, e.g. --season 2024. Offseason and preseason
                        events are excluded.
  --no-statbotics       Skip Statbotics EPA metrics (TBA data only).
  --delay SECONDS       Pause between events in a season sync (default 0.5).
                        Ignored for a single event.
  --watch EVENT_KEY     Keep one event fresh during live play: re-sync it on
                        an interval until the event is over, e.g. --watch
                        2025casj. Stops on its own once the finals are
                        complete; Ctrl-C stops it cleanly at any time.

watch options (used with --watch):
  --interval SECONDS    Seconds between polls (default 120).
  --max-interval SECONDS
                        Ceiling the interval backs off to while nothing is
                        changing (default 600).
  --statbotics-interval SECONDS
                        Seconds between Statbotics refreshes, which cost one
                        request per team (default 1800).
  --settle-polls N      Extra polls after the event first looks complete, to
                        catch post-finals score corrections (default 2).
  --max-failures N      Consecutive failed polls before giving up (default
                        20).
  --max-duration DURATION
                        Optional runaway guard, e.g. 8h or 90m. Off by
                        default: the finals and calendar stop conditions
                        already end the watch.
```

Give exactly one of `event_key`, `--season`, or `--watch`.

### 8.2 Syncing a whole season

```bash
venv/bin/python -m data.orchestrator --season 2024
```

`sync_season` is a thin wrapper over `sync_event`. Each event remains an
independent sync with its own `pipeline_runs` row and its own watermarks, so a
season sync is exactly 190 single-event syncs with three added policies:

* **Scope.** Only *official* events are synced — TBA `event_type` 0–5
  (regional, district, district championship and its divisions, championship
  divisions, championship finals). Offseason (99) and preseason (100) are
  excluded: they run modified rules with ad-hoc rosters, so their results are
  not comparable and would distort any season-level metric. For 2024 that is
  190 of 324 events. The filter reads `event_type` off the **raw response
  body**, because it is not a field on `EventSummary`.
* **Order.** Chronological by `start_date`, so every event loads after the ones
  it depends on — championship divisions before the championship finals whose
  roster is drawn from them.
* **Failure isolation.** One failing event does not end the season. `sync_event`
  has already written its `failed` run row by the time it re-raises, so the
  wrapper collects the error and continues; failures are listed in the summary.

**Statbotics is probed once, then circuit-broken.** Extraction requests
Statbotics once per team per event, which is ~8,100 calls across a 2024 season.
When the service is down each of those burns the client's full retry ladder
(measured at ~1.7s, worse with read timeouts), turning a ~12-minute season sync
into a multi-hour one that produces no rows and floods `data_quality_issues`
with thousands of identical extraction failures. So a season sync makes one real
`team_event/{team}/{event}` call first; if it fails, Statbotics is skipped for
the whole run and the reason is reported:

```text
statbotics SKIPPED for the whole season: probe for team 1574 at 2024isde1
failed: ReadTimeout: The read operation timed out
```

This is production behaviour, not a test convenience: a dead *supplementary*
source should be skipped, not retried thousands of times. Nothing but
`team_event_stats` depends on it.

### 8.3 Spot-checking stored data against TBA

`scripts/spot_check.py` is a read-only report for comparing what the pipeline
stored against thebluealliance.com by eye. It prints no verdict on purpose — an
automated comparison would re-implement the pipeline's own normalization and
agree with it by construction.

```bash
venv/bin/python -m scripts.spot_check --preset            # curated 2024 results
venv/bin/python -m scripts.spot_check --season-summary 2024
venv/bin/python -m scripts.spot_check --event 2024casj
venv/bin/python -m scripts.spot_check --match 2024cmptx_f1m1 --verbose
venv/bin/python -m scripts.spot_check --team 1114 --season 2024
```

Each match line is laid out the way TBA's match table reads:

```text
  qm1        red  30 -  27 blue   RED     red: 841, 8546, 253    blue: 6884, 5104, 6918
```

`--verbose` adds the `raw_source_payloads.id` behind each row via
`canonical_lineage`, so a suspicious value can be traced to the exact stored
response body that produced it.

### 8.4 Inspecting a run

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

### 8.5 Re-syncing and back-filling

Re-running `sync_event` for an event is always safe and cheap. To **force** a full
reprocess of an event without discarding raw history, reset its watermarks — the raw rows
stay, and every current payload is re-promoted through staging:

```sql
DELETE FROM source_watermarks WHERE scope_key = '2024casj';
```

### 8.6 Migrations

| File | What it does |
|---|---|
| `0001_initial.sql` | `raw_source_payloads` + first canonical tables (`teams` keyed on `team_key`) |
| `0002_add_indexes.sql` | Lookup indexes on the canonical tables |
| `0003_pipeline_observability.sql` | `pipeline_runs`, `source_watermarks`, `data_quality_issues` |
| `0004_raw_payload_dedup_index.sql` | Dedup key now includes `payload_checksum`, enabling payload versioning |
| `0005_canonical.sql` | Re-keys the canonical layer to `team_number`; composite PK on `team_event_stats` |
| `0006_pipeline_run_scope.sql` | `pipeline_runs.scope_key`, `pipeline_runs.stage_counts` |
| `0007_data_quality_lineage.sql` | `data_quality_issues.raw_payload_id`/`field` + cascades; creates `canonical_lineage` |
| `0008_metrics_schema.sql` | Phase 3 M2: creates `scouting_observations` and `team_metrics` (schema only, nothing writes them yet) |
| `0009_scouting_access_codes.sql` | Phase 3 M7: creates `scouting_access_codes`, the lightweight per-event anti-abuse gate for human scouting submissions |

Migrations are plain SQL applied in filename order and recorded in `migrations_applied`.
**There is no Alembic and none should be added.** To add one, create
`database/migrations/0010_<name>.sql` and run `database/migrate.py`.

### 8.7 Watching a live event

```bash
venv/bin/python -m data.orchestrator --watch 2025casj
```

Start this once when an event opens and it keeps that event's data fresh for the
rest of the event with no further triggering — the automated half of *"real-time
updates must sync during an event as matches are played"*. It stops on its own
when the event ends.

`watch_event` is a thin wrapper over `sync_event`, exactly as `sync_season` is.
**Every poll is an ordinary single-event sync** with its own `pipeline_runs` row,
its own watermarks, and its own advisory lock. No sync logic is duplicated. What
the wrapper adds is four policies:

**Cadence (`--interval`, default 120s).** One poll is three TBA requests
(`/event`, `/event/{k}/matches`, `/event/{k}/teams`), so this is ~90 requests an
hour. Qualification cycles run 7–8 minutes, making it 3–4 polls per match.

An unchanged poll is **already a near no-op by construction** ([§5](#5-incremental-state)):
the landing layer discards identical payloads, so nothing sits above the
watermark and the staging and serving stages do no work at all. Only the three
HTTP fetches cost anything. After **3 consecutive** polls that land nothing the
interval grows by 1.5× up to `--max-interval` (600s), snapping back to the base
the moment anything lands. The threshold is 3 rather than 1 deliberately: a
7-minute match cycle produces 2–3 idle polls during perfectly normal play, and
backing off immediately would slow detection exactly when the event is live.
Overnight it still walks up to the ceiling, cutting a 12-hour idle stretch from
~1,080 requests to ~216.

**Statbotics on its own clock (`--statbotics-interval`, default 1800s).**
Statbotics is one request *per team*, so a 40-team regional costs ~40 requests
per poll — 1,200/hour at the TBA cadence, which is not a well-mannered thing to
do to a free community API. It therefore refreshes every 30 minutes (~80
requests/hour) and every poll in between is TBA-only. It is also **probed once
and circuit-broken** for the whole watch if it is down, using the same helper and
the same reasoning as a season sync ([§8.2](#82-syncing-a-whole-season)): 40
failing lookups per poll, each burning the client's full retry ladder, would turn
a two-minute cadence into minutes of nothing but timeouts. `--no-statbotics`
disables it outright.

**Failure isolation (`--max-failures`, default 20).** TBA being briefly
unreachable mid-event is normal at a venue. A failed poll is logged, counted, and
retried after a backed-off wait — `sync_event` has already written its `failed`
run row and its quality evidence by the time it re-raises, so nothing is lost by
carrying on. Only that many *consecutive* failures end the watch, and only that
exit returns a non-zero status, so a mistyped event key 404s out instead of
looping forever. One success resets the count.

**Knowing when to stop.** Two independent signals, both read from data the poll
just loaded, so neither costs an API request:

* **Finals complete** *(primary)* — a `final` match exists and none is unplayed.
  Checked against the whole 2024 season: **190/190** official events have a
  played final and **none** has an unplayed one, so the signal is neither
  premature (it waits out a double-elimination `f1m2`/`f1m3`) nor unreachable (an
  unneeded `f1m3` is not published in advance).
* **Calendar** *(fallback)* — `end_date` plus a **1-day** grace has passed, for an
  event that never produces finals at all (cancelled or abandoned). The grace
  cannot be zero: `end_date` is a *local* date, so 7pm Saturday in Houston is
  already Sunday 00:00 UTC and a zero-grace check would stop the watch during
  Einstein finals.

> **The obvious third option — "every scheduled match has a result" — is wrong,
> and the season data proves it.** Two of those 190 finished events
> (`2024gagwi`, `2024mdsev`) permanently hold unplayed matches, because the
> `-1`/`frc0` sentinel rows load with NULL scores and TBA never reissues a
> finished event's schedule. A watch keyed on that condition would never stop for
> them. It also false-positives mid-event, in the gap between the last
> qualification match and the playoff bracket being published.

After completion is first seen the watch polls `--settle-polls` more times
(default 2) before exiting, to catch the score corrections TBA posts in the
minutes after finals. `--max-duration` (e.g. `8h`) is an optional runaway guard,
**off by default** — the two conditions above already terminate a real event, and
a legitimate watch spans several days.

**Stopping it by hand.** Ctrl-C (or `SIGTERM`) finishes the poll in flight and
then exits cleanly; a second one aborts immediately. There is no half-written
state to worry about either way — `sync_event` is transactional and advances
watermarks at exactly one point after serving succeeds, so *between* polls is
always a consistent state.

Each poll reports what it did:

```text
poll 14: landed={'tba.match': 3} loaded={'matches': 3} | matches 41/78 played (+2 new) | next in 120s
poll 15: nothing new | matches 41/78 played | next in 120s
poll 16 FAILED (1/20 consecutive): ConnectTimeout: ...
Event 2025casj looks complete (finals complete - 78/78 matches, 3/3 finals played); 2 settle poll(s) before stopping
```

EPA (`team_event_stats`) is only as fresh as the last Statbotics refresh, and is
skipped entirely if Statbotics was down when the watch started; running a plain
single-event sync after the event picks up whatever the watch missed.

---

## 9. Known issues and limitations

### 9.1 Statbotics EPA confirmed live (RESOLVED 2026-08-01)

**Resolved.** EPA data now reaches the canonical tables. Statbotics's API recovered from
the outage that had returned HTTP 500 on every `/v3/*` endpoint, and a real sync loaded
**75 `team_event_stats` rows for `2024new`**, every lookup 200 OK. Spot-checked against the
live API, team 254's stored row matches field for field: `epa_total` 55.07, `epa_auto`
15.99, `epa_teleop` 32.48, `epa_endgame` 6.6, 14-1-0, 15 played.

**The 2026-07-25 fix was correct and needed no revision.** The client had been pointed at
`api.statbotics.org`, a host that does not resolve at all, so every lookup failed with a DNS
error and `team_event_stats` was never populated. Two things were wrong; both were fixed:

| | Before | Now |
|---|---|---|
| Base URL | `https://api.statbotics.org/v3` (no such host) | `https://api.statbotics.io/v3` |
| Paths | `/team_event/{team}/{event}`, `/matches?event=` | unchanged — these were already right |
| Response shape | flat `epa_total`, `epa_auto`, `wins`, … | nested `epa.total_points`, `epa.breakdown.auto_points`, `record.total.wins`, … flattened by `StatboticsTeamEventMetrics` |

Because no live response could be captured during the outage, that nested shape was
inferred from Statbotics's published response serializer. **The capture on 2026-08-01
confirmed the inference exactly: all 61 leaf paths matched, with no key added, removed,
renamed or re-nested and no type changed.** No production code changed as a result.
`tests/fixtures/statbotics_team_event_2024casj.json` is now a verbatim live capture,
labelled `CAPTURED FROM LIVE API`, and
`tests/test_statbotics_client.py::test_model_matches_recorded_statbotics_response` validates
the client model against it.

The nesting is absorbed in the response models (`data/clients/schemas.py`), so the client,
the staging normalizer, and `team_event_stats` all work in flat fields — one place knows the
source's structure.

#### Statbotics returns HTTP 500, not 404, for a team-event that does not exist

This is a trap worth knowing, and it made the outage look broader than it was. Asking for a
team at an event it never attended does not 404 — it returns **HTTP 500 with a `{}` body**,
indistinguishable at a glance from the infrastructure outage:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' https://api.statbotics.io/v3/team_event/254/2024casj
500     # team 254 never attended 2024casj — still 500s today, with their API perfectly healthy
```

**So a health check must use a pairing you know is valid**, or a healthy API will look
broken forever. Two verified-good pairings:

```bash
# Is Statbotics up? 254 did attend 2024new (Newton Division).
curl -s -o /dev/null -w '%{http_code}\n' https://api.statbotics.io/v3/team_event/254/2024new   # -> 200

# The pairing recorded in the test fixture: 1678 did attend 2024casj.
curl -s -o /dev/null -w '%{http_code}\n' https://api.statbotics.io/v3/team_event/1678/2024casj # -> 200
```

Confirm a team's real event list before trusting any such pairing —
`curl 'https://api.statbotics.io/v3/team_events?team=254&year=2024'` lists them. Note that
1678/**2024new** is *not* valid (1678 was in Archimedes, not Newton) even though
1678/2024casj and 254/2024new both are. An endpoint-level check that avoids the problem
entirely is `curl https://api.statbotics.io/v3/event/2024casj`, which needs no team.

Earlier revisions of this document told readers to run
`curl https://api.statbotics.io/v3/team_event/254/2024casj` to decide whether the outage was
over. That command can never return 200, and is corrected above.

#### What `epa_total` holds: EPA at the end of the event

The 2026-07-28 audit found Statbotics's archived bulk CSVs (`avgupta456/statbotics-csvs`,
`v2/team_events.csv`) track EPA as a **time series per event** — `epa_start`,
`epa_pre_playoffs`, `epa_end`, `epa_mean`, `epa_max` — and flagged that
`StagingTeamEventStats.epa_total` did not say which of them it held. The live API settles it:
`epa.stats` exposes only `start`, `pre_elim`, `mean` and `max` — there is **no `end` key** —
and top-level `epa.total_points` differs from all four for **42 of 42** teams at 2024casj.

`epa.total_points` is therefore the end-of-event value, which is the correct semantic for a
*team-event* metric. The existing mapping was already right; nothing changed.

The pipeline's graceful degradation held throughout the outage: 42 failed Statbotics lookups
never prevented the 136 TBA records from loading.

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
- **TBA's `frc0` roster placeholder** is resolved to an empty roster — see
  [§9.7](#97-tbas-frc0-unassigned-roster-placeholder--resolved-2026-08-01).
- **A fully one-sided unassigned roster is not flagged (open, unobserved).** One alliance
  all-`frc0` and the other a real three-team roster would load with one empty alliance and
  no finding at all, since an empty alliance is already legitimate (see §9.7). TBA has
  never been observed publishing that shape — every real case has both alliances
  unassigned — so no rule was invented for it. Worth revisiting only if it is actually
  seen.
- **A watch covers one event at a time.** `watch_event` polls a single event key; running
  two events concurrently means two processes. That is the real use case (a team is at one
  event), and per-event advisory locking means the two would not interfere anyway.
- **`StatboticsClient.fetch_event_match_stats` is implemented but wired into no flow.**
  (This entry previously read "only single-event sync exists", which was already stale when
  `sync_season` landed on 2026-07-25 and is doubly so now that `--watch` exists;
  `TBAClient.fetch_event_list` has driven season enumeration since then.)

### 9.6 Destructive integration teardown — RESOLVED 2026-08-01

`tests/test_raw_writer_statbotics.py::test_statbotics_and_tba_coexist_against_real_database`
used this as both its setup and its teardown, against the real configured `DATABASE_URL`:

```sql
DELETE FROM raw_source_payloads WHERE source IN ('tba', 'statbotics');
```

`source` is not a namespace. Every real landing row carries one of those two values — they
are the only ones any connector can emit, since `source_name` is a `ClassVar` fixed to
`"tba"` or `"statbotics"` — so the predicate matched **the entire table** (20,863 rows when
this was found), and `0007`'s two `ON DELETE CASCADE` foreign keys extended that to all
20,861 `canonical_lineage` rows and every `data_quality_issues` row. `Database.cursor()`
commits on context exit, so it would have been committed and irreversible. The canonical
tables have no FK to landing and would have survived — as 100K+ rows with no provenance,
against watermarks pointing at payload ids that no longer existed.

It had never fired only because of a stale unconditional `@pytest.mark.skip` whose stated
reason ("Requires local PostgreSQL database and valid `DATABASE_URL`") had long since
stopped being true — and because [§7.8](#78-run-the-tests) described that skip as
*conditional*, a reader trusting these docs and tidying the marker would have triggered it.

Fixed by scoping the delete, not by leaving it skipped:

| Change | Why |
|---|---|
| Sentinel `frc9999` → `frc9999zzztest` | `frc9999` is a validly-formatted TBA team key and could collide with real data; the new value follows the `9999zzztest` convention used elsewhere |
| One `_cleanup()` helper, `try/finally`, predicate `AND source_object_id = %s` | The delete can no longer match a row it did not itself write; it is the only `DELETE` in the module |
| `@pytest.mark.skip` → `@requires_db` (all three affected tests) | A skip marker is not a safety mechanism — it hides the statement behind a reason that eventually stops being true |
| New `test_integration_cleanup_deletes_only_its_own_sentinel` | Asserts both cascade targets are unchanged across a real `_cleanup()`, so a future rewrite that re-widens the delete fails in the suite, not in production data |

**The rule this generalizes to:** integration teardown must be scoped by the *identity*
columns of the rows the test wrote (`source_object_id`, `event_key`, `match_key`), never by
a categorical column like `source` that every real row also matches. Cleaning up by
`source` alone is safe only for a value production can never produce — `tests/test_raw_writer.py`
uses `test_source` and `race_test` for exactly that reason. This is the delete-side
counterpart of the assertion-side rule in [§9.5](#95-other-limitations) about scoping
audit-table assertions by object id.

### 9.7 TBA's `frc0` unassigned-roster placeholder — RESOLVED 2026-08-01

TBA has **two** unplayed-match sentinels, not one. The `-1` score sentinel — fixed earlier
the same day, and described in [§4](#4-schema-reference) (`matches`) and
[§6.2](#62-severity-is-policy) — is this one's sibling. They share a symptom and a
principle but nothing else: `-1` was rejected by the quality layer, `frc0` a whole layer
earlier by structural validation, so the `-1` fix did not touch it.

When a match's roster has not been assigned yet, TBA publishes it as
`["frc0","frc0","frc0"]` on **both** alliances. There is no FRC team 0 — team numbers start
at 1 — so it is a placeholder meaning "roster not assigned". The structural validator read
it as a team identity, and against a real team both of its roster rules were correct to
fire:

| Rule | What it saw |
|---|---|
| A team cannot appear twice on one alliance | `frc0` three times, on each alliance |
| A team cannot be on both alliances | `frc0` on red and blue |

So the payload was rejected before normalization, never reached the canonical tables, and —
because TBA is not going to reissue a completed event's schedule — could never become valid.
The contiguous-prefix watermark therefore held one id below it **permanently**: `2024mdsev`
sat at 19024 against a newest payload id of 19041, re-reading, re-rejecting and re-logging
17 payloads on every single run. A fourth symptom compounded it: roster backfill also read
`frc0` as a team, fetched `/api/v3/team/frc0`, got a 404, and recorded a fresh
`extraction_failure` warning each run.

**Fix: the placeholder is recognized as a sentinel and resolved into an empty roster**, at
the point the raw payload is interpreted — the same principle as `-1`, applied to a
different field. An absent score becomes `NULL`; an absent roster becomes *no*
`match_teams` rows. Not a roster of team 0: team 0 has no `teams` row, so keeping it would
only trade a validation rejection for a `missing_reference` one, and it would assert
downstream that some robot played. An empty alliance was already a legitimate canonical
state — the quality layer deliberately does not flag one, since playoff brackets are
published before alliances are selected.

`TBA_UNASSIGNED_TEAM_KEY` / `is_unassigned_team_key()` live in `data/staging/validator.py`
beside `TBA_UNPLAYED_ALLIANCE_SCORE`, and four call sites consult them deliberately:

| Site | Behaviour |
|---|---|
| `validator.validate_tba_match_payload` | placeholder excluded from the duplicate/overlap **identity sets only** |
| `normalizer._alliance_roster` | placeholder dropped, so the roster is `[]` |
| `pipeline._roster_team_keys` | placeholder never backfilled, so no 404 and no warning |
| `quality._roster_numbers` | placeholder never enters the referential lookup |

It is **not** filtered inside `tba_alliance_team_keys`, which is documented to return the
roster field unconverted. Hiding the sentinel in the shared accessor would make it
invisible to any future check that needs to see it, exactly as `-1` stays visible to
`_check_unplayed_sentinel`.

**The duplicate and overlap rules are unchanged for real teams**, which is the point of the
narrow exclusion: `["frc1114","frc1114","frc0"]` is still rejected, and `frc1114` on both
alliances is still rejected. A partially-assigned roster is not special-cased either —
`["frc1114","frc0","frc0"]` normalizes to a one-team alliance, which the existing
plausibility rule already flags as a warning.

Verified on the real event: `2024mdsev` went from 88 to **90** canonical matches, `qm73` and
`qm74` load with NULL scores, NULL winner and no roster rows, the watermark advanced
19024 → **19041**, `skipped=0 issues=0 extraction_errors=0`, and a second run is all zeros.

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

Create `database/migrations/0010_<name>.sql`, keeping it additive where possible, and run
`database/migrate.py`. Then update [§8.6](#86-migrations) and the schema reference in
[§4](#4-schema-reference) — `tests/test_docs_contract.py` fails if a table exists in the
database but is not documented here, or vice versa.
