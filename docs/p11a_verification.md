# P11A verification on an isolated PostgreSQL copy

**Status (2026-11-06): prepared, NOT RUN.** The build machine has no PostgreSQL. Nothing below has a result yet.

**Hard rules, from CLAUDE.md:**
- The serving database `stratai` is never modified, migrated or used for testing.
- Tests run only against `stratai_test` or `stratai_test_<suffix>`. `tests/db_guard.py` refuses anything else, at
  collection and at every connection, and has no bypass.
- No run exceeds 45 minutes.

## 1. Requirements

| Item | Requirement |
|---|---|
| Server | PostgreSQL 16 or later (the project ran 18.6), reachable from the test machine |
| Copy | A new database `stratai_test_p11a` (any `stratai_test_<suffix>` works) holding a full copy of real data |
| Data | 2024–2026 TBA ingestion: events, matches, match_teams, current raw match payloads with `score_breakdown`, event rankings, event alliances (with outcomes), team_metrics. No 2027 rows. |
| Schema | Migrations 0001–0013 recorded in `migrations_applied` |
| Rulesets | The approved P6-M1 rulesets for 2024–2026 (ids 4–6), for the replay and E5 setup |
| Python | This repository's `.venv`. On macOS without OpenMP, set `DYLD_LIBRARY_PATH` to the scikit-learn `.dylibs` folder, so xgboost loads. |
| EPA (Part B baselines and E5 only) | The production EPA configuration (`EPA_SOURCE`, `STATBOTICS_SNAPSHOT_DIR`, and so on) pointing at local files. No network call is needed. |

## 2. Make the copy (read-only on the serving database)

**Preferred: `pg_dump` / `pg_restore`.** It only reads the serving database, in one serializable snapshot, and needs
no exclusive access:

```bash
SERVING_URL=postgresql://USER@HOST:5432/stratai          # read access is enough
TEST_URL=postgresql://USER@HOST:5432/stratai_test_p11a
createdb --maintenance-db="$SERVING_URL" stratai_test_p11a
pg_dump --format=custom --no-owner --serializable-deferrable --dbname="$SERVING_URL" --file=stratai.dump
pg_restore --no-owner --dbname="$TEST_URL" stratai.dump
```

**Alternative: `python -m scripts.phase5_isolated_db --name stratai_test_p11a`.**
- It uses `CREATE DATABASE … TEMPLATE stratai`. PostgreSQL then needs **no other session connected to `stratai`**, so
  stop the API and any `--watch` sync first.
- It writes nothing to `stratai` and refuses the serving name.

## 3. Point every command at the copy, and check it, before anything else

```bash
export DATABASE_URL="$TEST_URL"      # the environment overrides .env; never rely on .env
python -m scripts.p11a_db_preflight  # read-only; must print "status": "ready"
```

**What the preflight does:**
- **Before connecting:**
  - prints host, port and database name (never the password);
  - **refuses (exit 2)** anything but `stratai_test` / `stratai_test_<suffix>`, including the serving `stratai`.
- **Then, inside one READ ONLY transaction:**
  - confirms `transaction_read_only = on`;
  - lists missing migrations;
  - counts 2024–2026 qualification matches with landed breakdowns, rankings and alliances;
  - reports any 2027 row.

**If migrations are missing**, apply them **only after** the preflight has printed the copy's name:
`python database/migrate.py`. It migrates whatever `DATABASE_URL` names and has no guard of its own, so the
explicit export above is required.

## 4. The P11A database tests (`tests/test_p11a_db.py`)

| Run | Command | Writes | Expected time |
|---|---|---|---|
| Real data, read-only | `pytest tests/test_p11a_db.py -k real_data` | none: one READ ONLY transaction; one test proves a write is refused | seconds to a few minutes |
| Authenticated API | `pytest tests/test_p11a_db.py -k api` | sentinel rows (season 9977, teams 99771–99799) in the copy only, removed afterwards | under a minute |
| Phase 11 API (prerequisite) | `pytest tests/test_phase11_live_draft_api.py` | as above | under a minute |
| Phase 11 replay (P11-DM1) | `python -m scripts.phase11_replay --per-season 2 --budget-minutes 40` | none | ≤ 40 min |

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
