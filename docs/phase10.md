# Phase 10 — Polish, Backtesting and Hardening

- **Spec:** `docs/P10Milestones.md` (revision 1, agent working freeze pending Sven Morais's ratification), with
  `.agent/phase10/P10_M0_DECISIONS.md`.
- **Status, evidence and risks:** `.agent/phase10/`.

This page describes what is built. It is completed at P10-M7.

## Platform hardening (P10-M1)

| Item | Behaviour | Where |
|---|---|---|
| Request-body limit (Phase 7 R6) | Every route refuses a body over its limit with **413 `payload_too_large`** in the error envelope, whether the length is declared or streamed. The limit is `MAX_REQUEST_BODY_BYTES` (default 1 MiB) for every route except the game-manual upload, which allows the manual's own cap plus 64 KiB. **It is declared in OpenAPI on every operation that takes a body** (20: 11 locked, relocked additively under P10-Q9, approved 2026-10-21; plus 9 unlocked). A body sent to a GET route is refused the same way, but GET routes do not declare it, because no client sends one. The code is pinned to `payload_too_large` in `api.errors`, whatever Python's phrase for 413 | `api/body_limit.py` |
| Database timeouts (Phase 7 R7) | Every connection: `DB_CONNECT_TIMEOUT_SECONDS` (default 10). API statements: `API_DB_STATEMENT_TIMEOUT_MS` (default 60000; 0 means none), appended to any `options` in the URL. Batch jobs build their own `Database` without a statement timeout | `database/connection.py`, `api/app.py` |
| EPA-source backoff (Phase 7 R7) | A failed load or reload is retried at most once per `EPA_SOURCE_RETRY_SECONDS` (default 30), including by a burst of queued requests. A failed reload keeps serving the loaded source | `api/dependencies.py` |
| Live-EPA cache (Phase 7 R10) | At most 8 snapshots' records, LRU, thread-safe | `ml/ratings/live_epa.py` |
| Manual download name (Phase 7 R11 F1) | `Content-Disposition` carries an ASCII fallback plus the exact name as RFC 5987 `filename*` | `api/routes/human_inputs.py` |
| Manual upload (F2) | The hashing, file write and database work run in the threadpool | `api/routes/human_inputs.py` |
| Storage-integrity message (F7) | Names no server path; the path is logged | `data/human_inputs.py` |
| Evidence hashes (Phase 7 R16) | The P5-D3 evidence check normalises line endings, so it holds on any checkout and still catches a content change | `tests/test_phase5_contract.py` |

## Consistent reads (P10-M2)

`database.connection.read_snapshot(database)` gives one connection inside one REPEATABLE READ, READ ONLY
transaction. Every read through it sees one database version, and a `commit()` or `rollback()` by code inside it is
ignored. `@consistent_reads` applies it to a function's `database` argument; nested uses reuse the outer snapshot.

It is used by:
- `build_team_features`;
- `build_team_strength`;
- `analyze_event`;
- `pre_match_inputs` (the report and the briefing).

So a live sync committing mid-response can no longer produce a mixed-version answer. The P10-M2 simulated event
found that bug as 500s.

A plain `Database` is wrapped. Other `Database` subclasses (the read-only session of batch jobs, test doubles) pass
through unchanged.

**Not covered:** reads made through an EPA provider or scale lookup built on the app's own `Database` (P10-R4).

## The simulated live event (P10-M2)

`python -m scripts.phase10_live_sync_stress --event 2024casj [--matches-per-poll 6] [--readers 6] [--budget-minutes 20] [--stall-seconds 120] [--out FILE]`

The run:
- creates a disposable database `stratai_test_p10_<pid>`, migrates it, and drops it at the end;
- replays one event's recorded public TBA payloads, read only from `stratai_test`, poll by poll through the
  production `sync_event` and `after_watch_sync`;
- runs reader threads against the served views at the same time.

After every poll, every team's served metrics and strength are compared with an independent recomputation from the
payloads.

**Report (harness H4):**
- `harness_version`, `code_sha256` and `config`;
- per-view statuses with error codes;
- latency, overall and for 200s only;
- each poll, with its problems;
- heartbeat `pauses`;
- `outcome`: `pass`, `fail` or **`environment_invalid`**.

A run with any heartbeat gap (the VM or process was not running) is `environment_invalid` and is never counted as a
pass or as an application failure. A stall over `--stall-seconds` records every thread's stack and the database's
sessions and locks, then force-drops the database so the run ends.

## One connection per request (P10-D1 option B): tried and rejected

Sven Morais selected option B on 2026-10-21 as a controlled experiment. It was implemented, tested (10 tests, all
passing) and measured against option A under equivalent conditions.

**It failed its acceptance criteria:**
- report latency did not fall: it was 8.6 % slower alone, and its p99 at 6 readers was higher;
- throughput did not improve.

The report still opened 13 connections per call, because most of its reads go through the app-level EPA provider
and helpers, which request-scoped reuse does not reach. **Option A is retained.**

Details: `.agent/phase10/decisions/P10_D1_EXPERIMENT_RESULT_2026-10-21.md`.

## Connection profile (P10-M3)

`python -m scripts.phase10_connection_profile --event 2024casj [--repeats 10] [--load-seconds 45] [--readers 1,3,6] [--out FILE]`

It runs on a disposable database with the event fully played, and measures:
- connection cost;
- each route's connections, statements and time split (connecting, executing, the rest);
- latency percentiles, connections per second and CPU over wall time under 1, 3 and 6 readers.

The results and the pooling proposal are in `.agent/phase10/runs/m3/` and
`.agent/phase10/decisions/P10_D1_CONNECTION_POOLING_PROPOSAL_2026-10-21.md`.

## Tests

| File | What |
|---|---|
| `tests/test_phase10_hardening.py` | Body limit (declared, streamed, the chunked route that reads its own body), timeouts, EPA backoff (sequential, burst, reload), the LRU (bounded, concurrent), the download header, the storage message, the upload off the event loop, the evidence hash |
| `tests/test_phase10_snapshot.py` | On a disposable database: the race reproduced deterministically, failing without the snapshot; one version with it; one version for the strength view; isolation; writers never blocked; read only; no leaks on errors; nesting and pass-through; concurrent readers with a stream of commits |
| `tests/test_phase10_stress_harness.py` | The harness's verdict, pause detection, the independent recomputation and the report fingerprint |
