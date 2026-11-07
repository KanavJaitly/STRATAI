# P11A verification on an isolated PostgreSQL copy

**Status (2026-11-07): prepared, NOT RUN.** A local PostgreSQL 18.6 now exists on the build machine; no copy has
been restored yet, so nothing below has a result.

**Hard rules, from CLAUDE.md:**
- The serving database `stratai` is never modified, migrated or used for testing.
- Tests run only against `stratai_test` or `stratai_test_<suffix>`. `tests/db_guard.py` refuses anything else, at
  collection and at every connection, and has no bypass.
- No run exceeds 45 minutes.

## 1. Requirements

| Item | Requirement |
|---|---|
| Server | PostgreSQL 16 or later (the project ran 18.6), reachable from the test machine |
| Copy | A local database `stratai_test_<suffix>` (for example `stratai_test_p11a_20261107`) holding a full copy of real data; the bare `stratai_test` is refused by the runner and the preflight |
| Data | 2024–2026 TBA ingestion: events, matches, match_teams, current raw match payloads with `score_breakdown`, event rankings, event alliances (with outcomes), team_metrics. No 2027 rows. |
| Schema | Migrations 0001–0013 recorded in `migrations_applied` |
| Rulesets | The approved P6-M1 rulesets for 2024–2026 (ids 4–6), for the replay and E5 setup |
| Python | This repository's `.venv`. On macOS without OpenMP, set `DYLD_LIBRARY_PATH` to the scikit-learn `.dylibs` folder, so xgboost loads. |
| EPA (Part B baselines and E5 only) | The production EPA configuration (`EPA_SOURCE`, `STATBOTICS_SNAPSHOT_DIR`, and so on) pointing at local files. No network call is needed. |

## 2. Make the copy (corrected 2026-11-07)

The source is the full `stratai_test` on the machine that holds it. The Render public dump is **not** a substitute:
it lacks the approved rulesets, the GameSpecs and the scouting data. Everything below happens on two machines, and
nothing is ever created or restored on the source's server.

**On the source machine (read-only).** The owner runs:

```bash
pg_dump --format=custom --no-owner --no-privileges --serializable-deferrable \
        --dbname="postgresql://<user>@localhost:5432/stratai_test" --file=stratai_test_<date>.dump
shasum -a 256 stratai_test_<date>.dump        # Windows: certutil -hashfile stratai_test_<date>.dump SHA256
```

`pg_dump` only reads. Record the checksum, and keep the original where it is.

**On this Mac.** Keep the file **outside the repository** (for example `~/StratAI-local/backups/`, mode 600), because
it holds accounts and scouting data.
1. Check the checksum: `shasum -a 256 <file>` must equal the recorded value.
2. Inspect the contents, without any database: `pg_restore --list <file>`. Confirm:
   - `TABLE DATA public migrations_applied` is present;
   - there are no entries that need a superuser (`EXTENSION` other than plpgsql, `POLICY`, `EVENT TRIGGER`,
     `PUBLICATION`, `SUBSCRIPTION`).
3. The local test role and database exist. They are created by the local `postgres` superuser, with
   `OWNER stratai_tester`, `ENCODING 'UTF8'` and `TEMPLATE template0`.
4. Restore into the local test database only:

   ```bash
   pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
              --dbname="postgresql://stratai_tester@localhost:5432/stratai_test_<suffix>" <file>
   ```

5. Delete the local dump file only after the restored copy has passed the preflight and the tests, and the original
   is confirmed intact on the source machine.

`python -m scripts.phase5_isolated_db` (`CREATE DATABASE … TEMPLATE`) works only when the source is on the same server.
It is not part of this procedure.

## 3. Point every command at the copy, and check it, before anything else

```bash
export DATABASE_URL="postgresql://stratai_tester@localhost:5432/stratai_test_<suffix>"   # password from ~/.pgpass
export TBA_API_KEY=unused
python -m scripts.p11a_db_preflight     # read-only; before migrating it lists 0013 as pending
python database/migrate.py              # report only: the target and the pending files
python database/migrate.py --apply --confirm-database stratai_test_<suffix>
python -m scripts.p11a_db_preflight     # must print "status": "ready"
```

**The preflight and the migration runner share one guard** (`database/target_guard.py`).
- **Before connecting, both refuse:**
  - Render and every other remote host;
  - the serving `stratai`;
  - the bare `stratai_test`;
  - any name that is not `stratai_test_<suffix>`.
- **After connecting:** the server must confirm the database name and a socket or loopback address.
- **The runner also refuses:**
  - a missing or incomplete `migrations_applied` history on a populated database;
  - a destructive pending migration (drop, truncate, delete) on a populated database.
- **The runner applies only with `--apply --confirm-database <exact name>`.**
- There is no production override.

The preflight reads inside one READ ONLY transaction and reports missing or incomplete history instead of failing. Take
a `pg_dump -Fc` backup of the copy before `--apply`.

## 4. The P11A database tests (`tests/test_p11a_db.py`)

| Run | Command | Writes | Expected time |
|---|---|---|---|
| Real data | `pytest tests/test_p11a_db.py -k real_data` | Its real-data reads use one READ ONLY transaction (one test proves a write is refused), **but the file's module-wide fixtures write**: see below | seconds to a few minutes |
| Authenticated API | `pytest tests/test_p11a_db.py -k api` | sentinel rows (season 9977, teams 99771–99799) in the copy only, removed afterwards | under a minute |
| Phase 11 API (prerequisite) | `pytest tests/test_phase11_live_draft_api.py` | as above | under a minute |
| Phase 11 replay (P11-DM1) | `python -m scripts.phase11_replay --per-season 2 --budget-minutes 40` | none | ≤ 40 min |

**What `-k real_data` writes (corrected 2026-11-07).** `tests/test_p11a_db.py` imports the automatic fixtures of
tests/test_phase11_live_draft_api.py, so they run for **every** test in the file, including the real-data ones:
- **Once per module:**
  - inserts sentinel events `9977zzzdraft` and `9977zzzother`, teams 99771–99786 and 99799, and eight qualification
    matches with their `match_teams`;
  - deletes them at the end.
- **Before and after each test:**
  - deletes the workspaces of teams 99771, 99772 and 99799, and users with `@workspaces.test.invalid` emails that have
    no membership;
  - deletes **every** row of `auth_attempts`.

All of this happens in the isolated copy only, and nothing outside those rows changes.

**What they check:**
- **Snapshot export:** `build_event_snapshot` on a real 2024–2026 event (`P11A_DB_EVENT`, or the event with the most
  played qualification matches). It validates and records its build time.
- **Snapshot integrity:** a save/load round trip; an altered file is refused.
- **Historical cutoff:** no row at or after `as_of`, a mid-qualification snapshot has fewer rows than the full one,
  and every prior's event ended before this event started.
- **Data fetched or computed after the snapshot time:** a landed ranking fetched after `as_of` is left out and
  recorded, and so is any scouting summary computed after `as_of`. A delayed match whose result was posted after
  `as_of` is excluded too; the cutoff logic is unit-tested in `tests/test_p11a_snapshot_builder.py`.
- **Real-event plan generation:**
  - with no registered configuration (the real state), the plan is withheld;
  - with a **synthetic, test-only** configuration in a temporary registry, the estimator and planner run on real
    rows in under 2 s, and the output satisfies the response contract. That is not a real plan: its scoring rules
    are made up.
- **Authenticated operations:** 401 without a session, 403 without `alliance_selection`, and a current plan and
  profile through HTTP from a snapshot folder.
- **Workspace isolation:** another team's workspace gets `404 draft_not_found` for the plan and the profile.

**Report results as measured.** If PostgreSQL is unavailable, these tests skip. A skip is not a pass.

## 5. Then E5 (`research/p11a_e5/`)

E5 must not run before it is registered. See `research/p11a_e5/README.md`.
