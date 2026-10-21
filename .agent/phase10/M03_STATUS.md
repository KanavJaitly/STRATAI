# P10-M3 — Performance measurement: status (2026-10-21)

**status:** measurements RECORDED; no code change made; the pooling and reuse proposal AWAITS Sven Morais's decision
(P10-D1).

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
