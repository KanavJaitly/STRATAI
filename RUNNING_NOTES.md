# StratAI — Running Notes

> ⚠️ **UPDATE THIS FIRST** when anything changes: stack decisions, milestone status, blockers, or key design choices. Commit it alongside the work it describes.

---

## 🔄 Project Status Tracker

| Field | Current Value |
|---|---|
| **Active Phase** | Phase 2 — Data Pipeline ✅ **COMPLETE** (Milestones 1–10) |
| **Active Milestone** | Phase 3 — Metrics & analytics (not started) |
| **Last Completed** | Milestone 10 — Docs & validation harness (commit `892aff4`, branch `milestone-10`) |
| **Last Updated** | 2026-07-25 |
| **Current Blocker** | Statbotics client fixed (`e6a08cf`); EPA data still not flowing — their API is returning 500s. Not ours to fix; re-verify when it recovers |
| **Next Session Goal** | Re-verify Statbotics against a live response when their API recovers, then scope Phase 3 |

---

## 🏗️ Tech Stack Decisions (confirmed, not placeholders)

| Layer | Decision | Notes |
|---|---|---|
| **Backend Language** | Python 3.11 | venv-based; `requirements.txt` (no pyproject) |
| **Database** | PostgreSQL 18 | local cluster, port 5432 |
| **DB Driver** | psycopg3 (sync) | context-managed `connection()`/`cursor()`, autocommit-on-exit |
| **Migrations** | Raw SQL in `database/migrations/*.sql` | applied in sorted order by `database/migrate.py`, tracked in `migrations_applied`. **No Alembic.** |
| **Validation** | Pydantic v2 | staging + source schemas |
| **HTTP client** | httpx | TBA / Statbotics clients |
| **Testing** | pytest | 225 passed / 4 skipped as of the Statbotics fix |

---

## 📦 Phase 2 Milestone Tracker

| Milestone | Status | Notes |
|---|---|---|
| 1. Scaffold & config | ✅ Done | |
| 2. DB connection & initial schema | ✅ Done | `0001_initial.sql` created the canonical tables + `match_teams`. **Correction (verified 2026-07-24):** it did *not* create `pipeline_runs` / `source_watermarks` / `data_quality_issues` — those came later in `0003_pipeline_observability.sql`, despite the plan crediting them to M2. |
| 3. Source connector + TBA client | ✅ Done | |
| 4. Landing raw ingestion writer | ✅ Done | |
| 5. Statbotics connector + landing | ✅ Done | `StatboticsTeamEventMetrics` lands EPA / W-L-T |
| 6. Staging normalizer & validation | ✅ Done | `StagingTeam/Event/Match`; strips `frc` prefix → `team_number` int |
| 7. Canonical schema + repository load | ✅ Done | see decisions below (merged PR #1) |
| 8. Pipeline orchestration & incremental state | ✅ Done | `data/pipeline.py` stages + `data/orchestrator.py` driver; watermark = highest promoted `raw_source_payloads.id`; `0006` adds `scope_key`/`stage_counts` |
| 9. Data quality checks & audit tracing | ✅ Done | `data/staging/quality.py` checks + `data/lineage.py` provenance; `0007` adds `raw_payload_id`/`field` to `data_quality_issues` and creates `canonical_lineage` |
| 10. Docs & validation harness | ✅ Done | `docs/data_pipeline.md` + `tests/test_docs_contract.py` (47 contract tests); README/CLAUDE.md corrected |

**Status Key:** ⬜ Not Started &nbsp; 🟡 In Progress &nbsp; 🔵 In Review &nbsp; ✅ Done

---

## 📐 Key Design Decisions Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-23 | **Re-keyed canonical layer to `team_number`** (`0005_canonical.sql`) | `0001` had keyed teams on `team_key` TEXT (`"frc1114"`), but M6 staging strips the prefix to `team_number` INT. Tables were empty, so drop-and-recreate lost no data. Confirmed with Kanav. `events`/`matches` left untouched (already compatibly keyed). |
| 2026-07-23 | **Kept `match_teams` junction** (not `int[]` arrays) | True FK integrity on roster membership — arrays can't enforce it. Junction already existed in `0001`. |
| 2026-07-23 | **`team_event_stats` sourced from Statbotics (M5)** | Added `StagingTeamEventStats` + `normalize_statbotics_team_event_stats` so the M7 loader is exercised end-to-end, not just against hand-built rows. `epa_endgame` nullable (Statbotics may not provide it). |
| 2026-07-24 | **Watermark = highest promoted `raw_source_payloads.id`**, per `(source, object_type, event)` | Landing already dedups identical payloads, so an unchanged object lands no new row and nothing sits above the watermark — a re-sync's staging/serving stages are true no-ops, not deduplicated work. No new schema needed; `0003`'s UNIQUE `(source, object_type, scope_key)` was already the right key. Confirmed with Kanav. |
| 2026-07-24 | **`0006_pipeline_run_scope.sql`: nullable `scope_key` + `stage_counts` JSONB on `pipeline_runs`** | `0003` gave `pipeline_runs` no scope column, so runs against different events were indistinguishable and unreconcilable against watermarks. Purely additive, rollback is `DROP COLUMN`. Confirmed with Kanav. |
| 2026-07-24 | **Watermarks advance at exactly one point** — after serving succeeds | Guarantees no failure leaves a corrupt watermark. Safe to repeat a partially-completed run because every canonical write is an upsert. A failed run is recorded as `failed` and the exception re-raised, never swallowed. |
| 2026-07-24 | **Contiguous-prefix watermark advance on validation failure** | An invalid payload is skipped + recorded, and the watermark stops short of it, so it is retried on later runs instead of permanently skipped — one bad record never blocks an event's good records. Tradeoff: a permanently-malformed record is re-read every run (idempotent, cheap). Confirmed with Kanav. |
| 2026-07-24 | **Roster backfill in extraction** | TBA's event team list and match schedule are separate endpoints with no guarantee they agree; a rostered team with no `teams` row fails the whole load on the `match_teams` FK. Missing teams are fetched individually before landing. Confirmed with Kanav. |
| 2026-07-24 | **Additive client methods** (no M3/M5 signature changes) | `TBAClient.fetch_event` (single event, vs. downloading a whole season) and `fetch_event_teams` (one request, vs. ~40 `fetch_team_info` calls). Plus `city`/`state_prov`/`country` on `EventSummary` — see tech debt below. |
| 2026-07-24 | **Watermarks scoped per event, including for teams** | A team attending two events is tracked independently under each, so one event's run can never advance another's progress. Cost is one idempotent re-upsert of that team per event. |
| 2026-07-24 | **Lineage as a separate `canonical_lineage` table**, not a `source_payload_id` column on the canonical tables | Keeps the `0001`/`0005` schema and the M7 repository completely untouched, and makes lineage an append-only *history* (every payload version an entity was built from, plus the run that promoted each) instead of a last-writer pointer that can't represent multi-source entities. Confirmed with Kanav. |
| 2026-07-24 | **Severity is the reject/allow policy** — `error`/`critical` reject, `warning` records and loads | Errors are records that are meaningless or unloadable (negative score, W/L/T contradicting its own total, end date before start, reference that won't exist). Everything judgemental is a warning: a plausibility rule that discards real data is worse than no rule, since FRC scoring changes every season and today's generous ceiling will eventually be exceeded by a real match. Confirmed with Kanav. |
| 2026-07-24 | **One rejection mechanism, not two** | A fatal quality issue takes the identical path in `stage_batch` that an M8 validation failure takes: skipped, watermark held short of it, retried next run. M9 changes to M8 are additive only (default-empty `StagedBatch.issues`/`.lineage`, optional `context` param, optional `sync_event` collaborators). Confirmed with Kanav. |
| 2026-07-24 | **`ON DELETE CASCADE` on `data_quality_issues`** (incl. redefining `0003`'s run FK) | Once issues and lineage reference runs and raw payloads, deleting either — which integration teardown does — fails on a foreign-key violation. Expressing the cleanup in the schema beat editing M8's test teardown, and it's semantically right: an issue is a subordinate record of the run and payload it describes. Lineage's run FK is `SET NULL` instead, since provenance stays true even if the run record is gone. Confirmed with Kanav. |
| 2026-07-24 | **Issues written before the load, lineage after** | A failed run's quality evidence is exactly when it's wanted, so issues must not depend on the load succeeding; a lineage row asserts a canonical row exists, so it must. |
| 2026-07-24 | **One `data_quality_issues` row per detection**, not per distinct problem | A payload that stays invalid is re-detected every run (the watermark deliberately holds short of it). Collapsing detections would lose the answer to "how long has this been broken", which is what the `resolved`/`resolved_at` columns exist to support. |
| 2026-07-24 | **Rejected: checking `epa_total` against `epa_auto + epa_teleop + epa_endgame`** | Statbotics doesn't document those as summing exactly, so any tolerance would be invented statistics generating false alarms about real data. |
| 2026-07-24 | **`docs/data_pipeline.md` is the Phase 2 reference; README stays short and points to it** | The old README's `.venv\Scripts\python.exe` quickstart could not work in this repo (Linux, `venv/`), so every documented command failed as written. Confirmed with Kanav. |
| 2026-07-24 | **Docs↔schema drift is enforced by test, in both directions** | `tests/test_docs_contract.py` fails if a table exists but is undocumented, or documented but absent — plus columns, PKs, FKs, cascades, unique indexes, check constraints, migration numbering, config defaults, and the object-type/severity/issue-type/plausibility vocabularies. Docs that can silently rot are worse than no docs. |
| 2026-07-24 | **Five reserved columns documented as "not populated", not dropped** | `raw_source_payloads.season/.event_key/.match_key/.schema_version` and `events.event_type` (plus `data_quality_issues.resolved/resolved_at`) are retained deliberately; the docs mark them so nobody builds on them. Confirmed with Kanav. |
| 2026-07-24 | **`createdb -U postgres -h localhost stratai`**, not bare `createdb` | A bare `createdb` connects as the OS user and fails with `role "<user>" does not exist`. Found by running the documented command instead of assuming it. |
| 2026-07-24 | **Audit-table assertions must scope by `object_id`** | Two M9 tests counted `data_quality_issues` by `object_type` alone and broke once real `2024casj` rows existed. Fixed in the `_issues()` test helper (approved test-only change). `data_quality_issues` and `canonical_lineage` are shared append-only tables; any test asserting on them must namespace itself. |
| 2026-07-25 | **Statbotics base URL corrected to `api.statbotics.io`** | `api.statbotics.org` never resolved, so EPA data had never once loaded. The paths (`/team_event/{team}/{event}`, `/matches?event=`) were already correct. |
| 2026-07-25 | **Nested→flat mapping lives in the client response models** | Statbotics nests EPA under `epa`/`epa.breakdown` and the record under `record.total`. Flattening via `model_validator` in `data/clients/schemas.py` means exactly one place knows the source's structure — the normalizer, `StagingTeamEventStats`, and `team_event_stats` are untouched. Flat payloads still validate, so no existing fixture broke. Confirmed with Kanav. |
| 2026-07-25 | **`matches_played` prefers `record.total.count`**, falling back to `wins+losses+ties` | Statbotics *does* report a played-match count; the old "no count exists" premise came from never having seen a real response. Also makes the M9 `matches_played` quality rule meaningful instead of tautological, since the two values now come from different places. Confirmed with Kanav. |
| 2026-07-25 | **Mocks must encode the real wire shape** | Every Statbotics test passed against an invented flat shape — that is precisely how the wrong contract survived unnoticed for five milestones. Client tests, the recorded fixture, and the M8/M9 end-to-end fakes all now use the nested shape. A mock encoding a wrong shape is worse than no test. |

---

## 🐛 Known Issues / Tech Debt

- [ ] **🟡 Statbotics: client fixed, EPA data still unobserved** (bug found in M10, fixed 2026-07-25 in `e6a08cf`): the host is corrected to `api.statbotics.io` (`.org` never resolved) and the nested response shape is absorbed in the client models. **Still open because the thing that matters — EPA rows in `team_event_stats` — has never once been observed.** Statbotics's API was returning HTTP 500 on every `/v3/*` endpoint from their own infrastructure, so the shape is derived from their published response serializer rather than captured, and a real `2024casj` run still loads `team_event_stats = 0`. The failure mode did change from a DNS error to an HTTP 500 from the real host, which is the evidence the client now reaches them. **To close out:** `curl https://api.statbotics.io/v3/team_event/254/2024casj`; when it returns 200, run `venv/bin/python -m data.orchestrator 2024casj`, confirm one `team_event_stats` row per attending team, and re-record `tests/fixtures/statbotics_team_event_2024casj.json` from the real response — `test_model_matches_recorded_statbotics_response` fails if the live shape differs. See `docs/data_pipeline.md` §9.1.
- [ ] **Sentinel event keys must agree with their payload year** (surfaced by M9): the staging layer derives a match's season from its *event key*, so a `9997…` key with `"year": 2025` yields season-9997 matches and trips plausibility warnings. M9's integration fixtures use `2025zzzqual` for this reason; M7/M8's `9998`/`9999` fixtures intentionally accept the resulting warnings.
- [ ] **Clients discard the raw response body** (surfaced by M8): they return validated Pydantic models, so the landing layer stores `model_dump(mode="json", by_alias=True)` — faithful for modelled fields, but a field no model declares is invisible to both the canonical row and the landing checksum, so a change confined to it is never detected as a new version. Widening a model fixes it per field (this is why `EventSummary` gained its location fields in M8); exposing raw response bodies from the clients would fix it generally. Documented in `data/pipeline.py`'s module docstring.
- [ ] **Statbotics extraction is N requests per event** (one per team) — the API exposes team-event metrics only per `(team, event)`. Fine for one event; will want revisiting for a full-season backfill.
- [ ] **Pre-existing config test bug** (not from M7): `tests/test_config.py::test_settings_allows_missing_statbotics_api_key` fails when a `.env` exists at project root (created by `cp .env.example .env`). Cause: `config.py` `load_dotenv(override=False)` + leaked `DATABASE_URL` in `os.environ` shadows the test's temp `.env`. Passes in a fresh clone. Fix touches M1 config/test code — deferred, needs Kanav's call (options: `override=True`, or have the test clear the env var).

---

## 🔑 Critical Constraints (Do Not Forget)

- Defense/feeding scores = **directly measured**, NOT inferred from point output
- Win probabilities = **unbiased** — AI strategy cannot get inflated odds
- Core engine = **no LLM API calls** — ML / stats / optimization only
- LLM allowed only for: natural-language report generation and explanations
- Real-time updates must sync **during an event** as matches are played

---

## 📝 Session Log

| Date | Worked On | What Was Built / Decided | Next Step |
|---|---|---|---|
| 2026-07-23 | Milestone 7 (Sven's first solo milestone) | Local env from scratch (Postgres 18, venv, deps); baseline 102 tests green; M7 built — `0005_canonical.sql` re-key, `CanonicalRepository` upsert loaders, `StagingTeamEventStats`; 113 pass; committed `4086f59`, PR #1 merged to `main` | Milestone 8 |
| 2026-07-24 | Milestone 8 | Confirmed `pipeline_runs`/`source_watermarks` came from `0003`, not M2. Built `data/pipeline.py` (4 stages) + `data/orchestrator.py` (`PipelineRunRecorder`, `WatermarkStore`, `sync_event`, CLI); `0006` applied; additive `TBAClient.fetch_event`/`fetch_event_teams`. 18 new tests, all M8 integration tests run for real against local Postgres (no skips); suite 135 pass / 4 skip / 1 deselected. Committed `0fdf200` on `milestone-8`, PR #3 merged to `main` | Milestone 9 — data quality checks & audit tracing |
| 2026-07-24 | Milestone 9 | Confirmed `data_quality_issues` existed from `0003` but lacked a raw-payload reference and `field`, and that no canonical table carried lineage. Built `data/staging/quality.py` (plausibility + referential checks, severity as reject/allow policy) and `data/lineage.py` (`canonical_lineage` provenance history, `trace_to_payload`); `0007` applied; wired into `stage_batch` reusing M8's single rejection path. 37 new tests, all M9 integration tests run for real; suite 172 pass / 4 skip / 1 deselected, M8's 18 untouched. Committed `b96b579` on `milestone-9`, PR #4 merged to `main` | Milestone 10 — docs & validation harness |
| 2026-07-24 | Milestone 10 (Phase 2 complete) | Verified true schema against migrations + live DB; wrote `docs/data_pipeline.md` (architecture, schema, watermarks, quality/lineage, verified quickstart, known issues, extension guides); added 47 contract tests incl. first real coverage of `TBAClient.fetch_event`/`fetch_event_teams`; rewrote README, updated CLAUDE.md. Ran the CLI against real `2024casj` (136 records loaded, re-run all zeros). Flagged the Statbotics base-URL bug and the permanently-skipped M2 schema test. Suite 219 pass / 4 skip / 1 deselected. Committed `892aff4` on `milestone-10`, PR #5 merged to `main` | Fix Statbotics base URL, then scope Phase 3 |
| 2026-07-25 | Statbotics client fix (not a milestone) | Diagnosed two bugs: unresolvable host (`.org` → `.io`) and a wholly wrong response shape (nested `epa`/`record`, not flat). Fixed the URL, absorbed the nesting via `model_validator` in the client models, switched `matches_played` to the sourced count, re-mocked all Statbotics tests to the real shape, added a source-derived response fixture with a model test, and updated the M8/M9 integration fakes to nested payloads. Suite 225 pass / 4 skip / 1 deselected. Live verification **pending their outage** — `team_event_stats` still 0. Committed `e6a08cf` on `fix-statbotics` | Re-verify against a live Statbotics response, then Phase 3 |
