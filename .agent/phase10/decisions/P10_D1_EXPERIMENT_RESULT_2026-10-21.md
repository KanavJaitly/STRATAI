# P10-D1 — option B experiment: result (2026-10-21)

**Verdict: REJECTED. Option A is retained.**

Option B (one connection per request, no new dependency) was implemented and measured as Sven Morais authorised
on 2026-10-21 (`P10_HUMAN_DECISIONS_2026-10-21.md`). It failed acceptance criteria 1a, 1b and 2 of the proposal
(`P10_D1_CONNECTION_POOLING_PROPOSAL_2026-10-21.md` §5). The criteria were not changed.

The prior implementation is restored. The harness's code fingerprint over the relevant files now equals the
option-A baseline's (`66ed585bfd6c…`). The B code is preserved in pushed commit `555162c`, for the record.

## What B was

`database.connection.RequestDatabase`, provided by `api.dependencies.get_database`:
- one connection per request, opened on first use and closed at the end of the request;
- each top-level call still its own transaction;
- a nested or concurrent call given a fresh connection;
- a broken connection replaced;
- `read_snapshot` using the idle request connection.

Its 10 tests passed: transactions, nesting, thread isolation, close and leaks, reconnect, timeouts, snapshot use and
restore, and through the app (one connection per request; concurrent requests never share).

## The experiment

Conditions were equivalent: same machine, same day, the same profiler version P2 frozen for all six runs,
2024casj fully played on a disposable database, `EPA_SOURCE=statbotics`. The commands:

```
EPA_SOURCE=statbotics venv/bin/python -m scripts.phase10_connection_profile --event 2024casj --repeats 10 --load-seconds 45 --readers 1,3,6 --out .agent/phase10/runs/d1_experiment/{before_A,after_B}_run{1,2,3}.json   # each exit 0
EPA_SOURCE=statbotics venv/bin/python -m scripts.phase10_live_sync_stress --event 2024casj --matches-per-poll 6 --readers 6 --out .agent/phase10/runs/d1_experiment/after_B_stress{1..5}.json        # exit 0,0,1,0,0
```

**Validity:**
- All 6 profile runs had no heartbeat pause.
- A VM suspend (21:38:32–21:54:03 UTC, kernel log) ended before the first run (21:57).
- Stress run 3 had a 13.8 s heartbeat pause at 22:35:43 UTC. It was not a kernel suspend, and it is unexplained;
  it came about two minutes before a requested restart of the local API server. That run is environment-invalid
  and not counted, and showed no failure of its own.

**Results** (median over 3 runs; per-run values in `runs/d1_experiment/EXPERIMENT_SUMMARY.json`):

| Measure | A (before) | B (after) |
|---|---|---|
| Report alone, median | 0.2105 s (0.258, 0.197, 0.211) | 0.2286 s (0.229, 0.237, 0.219) |
| Report alone, connections per call | 13 | **13** |
| Strength alone, connections per call | 4 | **2** |
| Strength alone, median | 0.062 s | 0.044 s (one run 0.193) |
| Metrics alone, median | 0.016 s | 0.021 s |
| Report at 6 readers, p99 (median of runs) | 1.016 s (2.01, 0.73, 1.02) | 1.503 s (1.50, 1.12, 1.98) |
| Requests in 45 s at 1 / 3 / 6 readers | 345–456 / 916–1,137 / 1,002–1,158 | 389–495 / 930–1,072 / 949–1,122 |
| Connections per second at 6 readers | 121–138 | 95–111 |
| PostgreSQL sessions after every load level | 0 | 0 |
| Server errors at 6 readers | 0 | 0 |

## Against the criteria

| Criterion (§5) | Result |
|---|---|
| 1a. Report median alone falls by at least 30 % | **NOT MET:** +8.6 % (slower) |
| 1b. Report p99 at 6 readers falls by at least 30 % | **NOT MET:** +47.9 %. The p99 is noisy in both arms (A: 0.73–2.01 s); no improvement is shown |
| 2. Throughput at 6 readers at least that at 3, in every run | **NOT MET:** 2 of 3 B runs (983 < 1,034 in run 3). It held in 3 of 3 A runs, so B did not improve it |
| 3. No new failure | **Met for correctness:** stress 4 pass + 1 environment-invalid, with 0 server errors and 0 stale values in all 5; option-B and snapshot tests passed. The full suite was not run on B, because criteria 1–2 had already failed it |
| 4. No session leak | **Met:** 0 in both arms |

## Why B did not help the report

The report still opened **13 connections** per call under B. Almost all of them are made through objects built on
the app's shared `Database`, not the request's:
- the EPA provider (`state.database`), one read per team;
- the scale lookup and other helpers created inside it.

Request-scoped reuse only covers reads made through the request's `Database`, which is why strength fell from 4 to
2 and the report did not change. The measured connect cost (about 10 ms) is therefore not removable by option B
as specified.

## Restoration

| Change | State |
|---|---|
| `api/dependencies.py` `get_database` | Restored to its prior text: the shared `Database` |
| `database/connection.py` `RequestDatabase` and its `read_snapshot` branch | Removed |
| `tests/test_phase10_request_connection.py` | Removed (the test of the removed code). It is in commit `555162c` |

Nothing else changed:
- the P10-M1 hardening, the P10-M2 snapshot fix and the P10-Q9 413 declaration are untouched;
- the code fingerprint equals the before-A baseline's.

**Verification after the restore:**
- focused tests: 315 passed;
- the full backend suite: see `PHASE_STATUS.md`;
- frontend: vitest 173 passed, tsc 0, lint 8 baseline warnings, build 0;
- lock check 0; types check 0.

## If the latency is still to be pursued: a new decision, not a retry of B

A variant **B′** would route the EPA provider's and the helpers' reads through the request's connection. That
means building them per request, or passing the request `Database` to them. It is a different change, touching
`api/ml_loading.py` and the EPA source lifecycle. It would need Sven's decision and the same experiment and
criteria. Option C (a pool) remains deferred to deployment.
