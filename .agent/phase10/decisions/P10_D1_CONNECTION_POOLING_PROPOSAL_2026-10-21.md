# P10-D1 — connection reuse or pooling for the API: PROPOSAL (2026-10-21)

**Status: PROPOSAL. It needs Sven Morais's decision.** Nothing here is implemented. It would add a dependency
and change the connection lifecycle: an architectural change (CLAUDE.md; P10 spec standing rule 5; P10-Q8).

## 1. What the evidence says, and does not

**The stalls.** The intermittent P10-M2 stalls (H2-a, t5, s12) were the VM being suspended, not the application:
- the kernel's suspend and resume records match all three to within seconds (`reviews/R1_M1_M2_ADVERSARIAL_2026-10-21.md`);
- in s12, every view's maximum latency equals the 83.8 s suspend;
- no lock was ungranted.

So **there is no evidence that connection-per-query causes a stall,** and this proposal does not claim a
reliability fix.

The competing explanations were tested:

| Explanation | Status |
|---|---|
| VM suspend | **Confirmed** by the kernel log (all three) |
| Database lock wait | Ruled out (s12: no ungranted lock) |
| TIME_WAIT or port exhaustion | Ruled out (about 1 socket in TIME_WAIT under load) |
| Name resolution | Ruled out (`localhost`: maximum 16 ms over 6,000 lookups) |
| Memory pressure | Ruled out (no swap; about 4.3 GB available) |
| Connection churn | Not needed to explain any stall; a **performance** cost (below) |

**The cost.** Connection-per-query is a measured latency cost. Source:
`runs/m3/connection_profile_run1.json` (disposable DB, 2024casj fully played, in-process TestClient, 8 CPUs):

| Measure | Value |
|---|---|
| New connection + close | median 9.5 ms (p99 16.8 ms) |
| `SELECT 1` on an open connection | median 0.1 ms |
| Pre-match report, alone | 248 ms median. **13 connections, 146 ms of it in connecting;** 72 statements, 83 ms |
| Strength view, alone | 64 ms. 4 connections, 42 ms connecting; 11 statements, 16 ms |
| Team metrics, alone | 21 ms. 1 connection, 15 ms connecting |
| Throughput, 1 / 3 / 6 readers | 448 / 963 / 905 requests in 45 s. Saturates at 3 readers |
| Connections per second, 3 readers | 116 |
| Report latency, 6 readers | median 0.71 s, p99 1.12 s (alone: 0.25 s) |
| Process CPU / wall, 6 readers | 1.36 (GIL-serialised Python plus connection work) |

In the database-heavy views, connecting is **about 60–70 % of a request's latency.** Under load, throughput stops
rising after 3 readers.

**Limits of the measurement:**
- one machine and one event;
- an in-process client, not uvicorn over a network;
- no models (so analysis answers its refusal and its compute path is not measured);
- the correlation of latency with connection count is measured; the throughput ceiling's cause is not separated
  between connection work and the GIL.

## 2. What exists already

| Mechanism | State |
|---|---|
| psycopg 3 | Installed. Connection pools are a separate package, `psycopg_pool`, which is **not installed** |
| Per-call connections | `Database.connection()` opens one per call |
| One connection per response | `read_snapshot` / `consistent_reads` (P10-M2) already give one connection to a whole response for the three heaviest builders: strength, analysis, report. They are a partial reuse mechanism with no new dependency |
| Long read-only jobs | `ReadOnlySessionDatabase` keeps one connection |
| Server pooling | No PgBouncer or server-side pooler in the repository or the documented environment |

## 3. Options

| | A. Keep the current design | B. Extend per-response reuse (no new dependency) | C. A process-wide pool (`psycopg_pool`) |
|---|---|---|---|
| What | Leave as is; P10-M2 needs no change | Give every request one connection for its life: a request-scoped `Database` from a FastAPI dependency, opened lazily and closed at the end. The existing `SnapshotDatabase` shape is reused for reads | `ConnectionPool(min_size, max_size, timeout)` created at startup, closed at shutdown; `Database.connection()` checks out and returns |
| Benefit | None | Removes about 12 of the report's 13 connects (an estimated ~130 ms of 248 ms) and most churn | Removes nearly all connect cost, and bounds concurrent connections (`max_size`) |
| Cost and risk | The latency stays | A request holds one connection for its whole duration (as snapshots already do). Write routes need a read-write variant. Per-request state must be reset. Touches `api/dependencies.py` and every route's `Database` | **A new dependency.** Pool sizing and timeouts. Session state can leak between checkouts (`statement_timeout`, `search_path`, an aborted transaction). Startup and shutdown hooks. Reconnect after a database restart. Tests must close pools. Async/threadpool interaction |
| Migration complexity | — | Medium | Medium–high |
| Frozen-spec or contract effect | None | None (no response changes) | None (no response changes) |

**Recommendation:**
1. **Decide A or B now; defer C.** P10-M2 does not depend on this. The stall was environmental.
2. B removes most measured churn without a dependency, and builds on the reuse already introduced.
3. C is the stronger bound for production concurrency. Decide it with the deployment (P8-R4), when the real server
   (workers, threads) is known.

## 4. Tests any chosen change must have

| Area | Required test |
|---|---|
| Transactions | A write route commits or rolls back exactly as now. A failed request leaves no open transaction. Reads inside a snapshot stay one version (existing `tests/test_phase10_snapshot.py`) |
| Concurrency | N concurrent requests never share a connection at the same time (B, C). C: pool exhaustion gives a bounded wait, then a clear 5xx with the envelope, not a hang |
| Shutdown | The app's lifespan closes every connection or pool. A test asserts no session remains (`pg_stat_activity`) |
| Reconnect | After a forced backend termination (`pg_terminate_backend`), the next request succeeds (C: the pool's check; B: a fresh connection) |
| Timeouts | `connect_timeout` and `statement_timeout` still apply to every checkout. `statement_timeout` cannot leak between requests |
| Leaks | 10,000 requests leave the session count flat (sampled) |
| Session state | `search_path`, `options` and any `SET` made by a request do not reach the next one |

## 5. The controlled experiment and the acceptance criteria

The same `scripts/phase10_connection_profile.py` (1 / 3 / 6 readers × 45 s, 2024casj, disposable DB) is run
**three times before and three times after**, on the same machine, with no VM pause (the heartbeat is checked).
Then `scripts/phase10_live_sync_stress.py` (H4, 6 / 6) is run **five times.**

**Accept if, and only if:**
1. Pre-match report median latency alone falls by **at least 30%**, and at 6 readers its p99 falls by at least 30%.
2. Throughput at 6 readers is **at least that at 3 readers** (the ceiling moves).
3. **No new failure:**
   - every H4 run is `pass` or `environment_invalid`, with 0 server errors and 0 stale values;
   - the full backend suite shows no failure beyond the known baseline;
   - `tests/test_phase10_snapshot.py` passes.
4. **No session leak:** the sampled PostgreSQL session count returns to its idle value after each run.

Otherwise: reject, and keep A.
