# Incident 2026-10-04: migration 0010 applied to the serving database without prior approval

**Resolution: KEPT (Kanav, 2026-10-04).**
- 0010 is treated as the intended deployment migration for the human-input frontend and backend.
- No rollback or drop DDL was run, and no further production DDL may be run without explicit approval.
- A permanent test-database safety guard was added (see Prevention).
- This is an operational incident, not a Phase 5 acceptance failure. No verification result, acceptance criterion
  or record was altered because of it.

## What happened

| | |
|---|---|
| When | 2026-10-04 19:30:56.73Z (`migrations_applied.applied_at` = 15:30:56.730732 America/New_York) |
| Database | the serving database, `stratai` |
| Migration | `database/migrations/0010_phase5_human_inputs.sql` (committed in ec66b6d) |
| How | a contract-test batch was run without exporting the isolated `DATABASE_URL`: `tests/test_phase5_contract.py`, `tests/test_ml_models_docs_contract.py`, `tests/test_metrics_docs_contract.py`, `tests/test_frontend_api_contract.py` |
| Mechanism | `Settings()` resolved `DATABASE_URL` from `.env`, which names the serving database. `tests/test_metrics_docs_contract.py`'s `database` fixture (Phase 3, unchanged) calls `database.migrate.run_migrations` on that URL, which applied the one migration not yet recorded there (0010) |
| Whose error | Claude's, as operator: every Phase 5 test run is required to export the isolated `stratai_test` URL, and this one did not |

## Affected objects (all created by 0010; verified read-only afterwards)

- **Tables:** `game_manuals`, `game_spec_versions`, `capability_profiles`, `human_review_artifacts`, with their CHECK,
  UNIQUE and foreign-key constraints.
- **Indexes:**
  - `game_manuals_pkey`, `game_manuals_season_content_unique`;
  - `game_spec_versions_pkey`, `game_spec_versions_unique`, `game_spec_versions_one_approved_per_season`;
  - `capability_profiles_pkey`, `capability_profiles_unique`;
  - `human_review_artifacts_pkey`, `human_review_artifacts_unique`.
- **Sequences:** `game_manuals_id_seq`, `game_spec_versions_id_seq`, `capability_profiles_id_seq`,
  `human_review_artifacts_id_seq`.
- **Migration record:** one row in `migrations_applied`, `0010_phase5_human_inputs.sql`, making 10 rows in all.

0010 is additive (`CREATE TABLE IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`) and alters no existing table.

## Verification that serving data was untouched

These checks were read-only, after the incident. The last one used `database.readonly.ReadOnlySessionDatabase`.
- **The four new tables have 0 rows each, and their four sequences have `last_value` NULL.** Not even a failed insert
  was attempted, so **no human-input route write was performed** against the serving database.
- **`raw_source_payloads` has 0 `capability_intake` rows** (the human-input raw landing).
- **The latest serving-data timestamps all predate the incident:**
  - `raw_source_payloads` 2026-10-01 22:21;
  - `pipeline_runs` 2026-10-01 18:19;
  - `team_metrics` 2026-09-24 16:33;
  - `data_quality_issues` 2026-09-24 16:33;
  - `matches.last_updated` 2026-09-24 17:03.
- **The batch's tests only read the schema after migrating.** None inserts, updates or deletes.

## Relation to the P5-D3 adoption (unchanged)

The adoption and its evidence are untouched and are referenced here, not modified:
- **Decision record:** `.agent/phase5/results/p5_m2_adoption.json`, written once at ec66b6d and committed in 6b75843.
- **Production check:** `.agent/production/p5_live_adoption_check_rerun1.json`, provenance commit 6b75843, PASSED.
  - It ran from 19:11:48Z for 18.8 min, read-only on the serving database.
  - It finished before the incident and was committed in b0e71e8 at 19:30:53Z, three seconds before it.
- 0010's tables play no part in EPA serving, predictions or any Phase 5 acceptance check.

## Prevention (approved by Kanav, implemented)

`tests/db_guard.py`, installed by `tests/conftest.py` in `pytest_configure`, which runs before collection. That puts
it ahead of any test module's import-time connection, any `run_migrations` fixture, and any write.
- **Session check.** The database every test resolves (`DATABASE_URL` from the environment, else `.env`) must be
  `stratai_test` or `stratai_test_<suffix>`.
  - Anything else stops the session with a usage error explaining that tests must target an isolated `stratai_*`
    database.
  - `stratai` itself is named as "the SERVING database".
- **Connection guard.** `psycopg.connect` and `psycopg.Connection.connect` refuse every non-isolated database before
  a socket opens. Each refusal is recorded and fails the session, so it can never pass as a skip.
- **No bypass.** There is no environment variable or flag to turn the guard off.
- **Regression tests:** `tests/test_db_guard.py`. They include a subprocess session pointed at `stratai` (on an
  unroutable host), which is refused before any test runs.

## Related finding, exposed by the guard on its first full run (2026-10-04)

`tests/test_migrations.py::test_run_migrations_rolls_back_the_whole_batch_on_a_later_failure` (Phase 2) reached the
serving database in every full-suite run where `.env`'s database was reachable, even with the isolated URL exported.

**How it reached the serving database.**
- The test deleted `DATABASE_URL` from the environment, so `Settings()` reloaded `.env`, which names `stratai`.
- It then ran `run_migrations` against a temporary migrations directory holding:
  - `CREATE TABLE test_rollback_should_not_persist`;
  - a statement that fails.
- In its cleanup it ran `DROP TABLE IF EXISTS test_rollback_should_not_persist` and
  `DELETE FROM migrations_applied WHERE migration_file = '9999_test_rollback_valid.sql'`.

**Effect: no persistent change.**
- The batch is one transaction and rolls back by design; that is what the test asserts.
- The cleanup statements had nothing to act on.
- The serving `migrations_applied` table has 10 rows (0001-0010), none of them the test marker.
- `test_rollback_should_not_persist` does not exist.

It is unrelated to 0010: the test only ever applied its temporary directory, and today's first full-suite run started
at 19:31:23Z, after 0010 was applied at 19:30:56Z.

**Fix.** The test now uses the isolated URL that the guard accepted at session start
(`tests/db_guard.session_database_url`). Its intent is unchanged: a real rollback against real PostgreSQL. It runs on
`stratai_test`.

**Correction to `PHASE_ACCEPTANCE.md` (2026-10-03).** "Every test and replay ran on isolated copies" did not hold for
this one test's connection. No verification result depends on it.
