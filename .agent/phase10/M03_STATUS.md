# P10-M3 — Performance measurement: status (2026-10-21)

**status:** profiling COMPLETE. Sven Morais selected P10-D1 option B on 2026-10-21 as a controlled experiment. **B was
implemented, measured and REJECTED** (criteria 1a, 1b and 2 not met), and **option A is retained**
(`decisions/P10_D1_EXPERIMENT_RESULT_2026-10-21.md`). No performance change is in the code.

| Item | Result |
|---|---|
| Tool | `scripts/phase10_connection_profile.py` (disposable DB; `psycopg.connect` and `Cursor.execute` wrapped in-process to count and time) |
| Run | `runs/m3/connection_profile_run1.json`: 2024casj fully played, 10 repeats per route, 45 s per load level at 1 / 3 / 6 readers, 160 s total, DB dropped, no VM pause in the window (kernel log) |
| Connection cost | Connect + close median 9.5 ms (p99 16.8 ms), against `SELECT 1` on an open connection at 0.1 ms |
| Per route, alone | Report 248 ms: 13 connections (146 ms), 72 statements (83 ms). Strength 64 ms: 4 connections (42 ms). Metrics 21 ms: 1 connection (15 ms). Connecting is about 60–70 % of database-heavy latency |
| Under load | 448 / 963 / 905 requests in 45 s at 1 / 3 / 6 readers (saturates at 3). About 110–116 connections per second. Report median 0.25 s alone, 0.71 s at 6 readers. Process CPU / wall 1.36 at 6 readers. At most 10 PostgreSQL sessions. No intermittent failure, no progressive degradation |
| On the stall | **These measurements do not explain any stall:** the stalls were VM suspends (review R1, verified). Connection churn is a latency cost, not a demonstrated reliability defect. Correlation is not claimed as causation |
| Hot spots fixed | None. The dominant cost is the connection lifecycle, an architectural change that needs a decision (P10-D1). The per-response snapshots of P10-M2 already reuse one connection for the strength, analysis and report builds |
| Limits | One machine and one event. In-process client. No models: analysis's compute path was measured only in the stress runs (5.1 s median per build). The throughput ceiling's split between connection work and the GIL is not separated |

## The P10-D1 option B experiment (2026-10-21)

| Item | Result |
|---|---|
| Runs | 3 option-A baselines and 3 option-B profiles (profiler P2, frozen), all valid (no pause). 5 option-B stress runs: 4 pass, 1 environment-invalid; 0 server errors and 0 stale values in all |
| Report alone, median | 0.2105 s (A) → 0.2286 s (B), +8.6 %. **Still 13 connections per call** |
| Strength alone | 4 → 2 connections per call |
| Report p99 at 6 readers | 1.016 s → 1.503 s (noisy in both arms) |
| Throughput at 6 vs 3 readers | not improved; failed in 1 of 3 B runs |
| Session leak | none, in either arm |
| Verdict | **REJECTED; A restored.** The code fingerprint equals the A baseline's |
| What it shows | The report's connection cost comes mainly from the app-level EPA provider and helpers, not the request's `Database`. A wider variant (B′) would be a new decision |
