# Phase 10 — risk and dependency register

**Status values:**
- OPEN;
- MITIGATED (with its residual);
- CLOSED (with evidence);
- CARRIED (named target: final remediation, or the environment of record);
- DECISION (needs Sven Morais).

| # | Risk / dependency | Impact | Disposition |
|---|---|---|---|
| P10-R1 | **The local VM suspends** (ChromeOS `maitred`). Three 2026-10-20/21 runs were suspended mid-run and looked like stalls or a hang | Long runs are invalidated; a suspended run can be misread as an application failure | MITIGATED: the H4 heartbeat marks any paused run `environment_invalid` (never counted). **Residual:** keep the host awake for long verification runs |
| P10-R2 | **Live-sync race (found by P10-M2):** feature reads straddling a sync commit gave `TeamFeatures` invariant failures (500s) | 5xx during a live event | CLOSED: `read_snapshot` / `consistent_reads`; deterministic regression tests (`tests/test_phase10_snapshot.py`) |
| P10-R3 | **Connection-per-query latency:** about 10 ms per connection, 60–70 % of database-heavy request latency; throughput saturates at 3 readers (`runs/m3/connection_profile_run1.json`) | Slow views under load (P8-R5) | OPEN, accepted as is: P10-D1 option B was tried and REJECTED on 2026-10-21 (no latency gain; `decisions/P10_D1_EXPERIMENT_RESULT_2026-10-21.md`), so option A is retained. A wider variant (B′, the EPA provider and helpers on the request connection) or a pool (C, with deployment) would each be a new decision. Not a reliability defect |
| P10-R4 | **Reads outside the response snapshot:** EPA providers and scale lookups built on the app's own `Database` | An EPA value from a newer version than the scores (low: EPA is only from a concluded earlier event) | OPEN, LOW. Would close with request-scoped reuse (P10-D1 option B) |
| P10-R5 | **What the simulated event does not exercise:** point-in-time `as_of`; analysis and report contents; model-backed outputs (no models, P9-R4); the live EPA source (P5-D3) and its cache; data edge cases (DQ, surrogates, `-1` sentinels) | Survival is shown for the local configuration only | CARRIED to the environment of record (with P9-R4): rerun H4 there with registered models, the D18 EPA config and a live-EPA event |
| P10-R6 | **Stall-diagnostics limits:** no worker-thread attribution and no atomic stacks without a native sampler | A future genuine stall would be harder to diagnose | OPEN, LOW (py-spy is not installed; installing it is a dependency decision) |
| P10-R7 | **Live-EPA record cache:** bounded at 8 snapshots; cycling over more than 8 re-reads each time | Extra file reads in an unusual access pattern | OPEN, LOW (a deliberate trade-off against unbounded growth, Phase 7 R10) |
| P10-Q9 | **A 413 on locked operations is not declared in OpenAPI** (the body limit, Phase 7 R6) | Clients see an undocumented status; the lock check cannot see it | CLOSED: approved by Sven Morais on 2026-10-21. Declared on the 20 operations that take a body (11 locked, relocked additively: 0 changed and 22 added leaves; 9 unlocked). Code pinned to `payload_too_large`. Lock check 0, types check 0, contract tests pass |

## Carried into Phase 10, with their disposition now

| Item | Disposition |
|---|---|
| Phase 7 R6: no body limit | CLOSED (P10-M1). The chunked-upload case was fixed after review R1; the 413 is declared (P10-Q9, 2026-10-21) |
| Phase 7 R7: no DB timeouts; the EPA load retried on every request | CLOSED (P10-M1). The burst and reload backoff were fixed after review R1 |
| Phase 7 R8: readiness ignores model and EPA state | DECISION: `/ready` is locked; a relock needs Sven (P10-Q8) |
| Phase 7 R9: no pooling, no request snapshot | Request snapshot: CLOSED for the three heaviest builders (P10-M2). Connection reuse: option B tried and rejected (P10-D1 result); A retained; open as P10-R3 |
| Phase 7 R10: unbounded live-EPA cache | CLOSED: bounded and thread-safe after review R1 (P10-R7 residual) |
| Phase 7 R11: human-input defects F1, F2, F7 | CLOSED (P10-M1) |
| Phase 7 R12: one shared write token, no rate limits | DECISION (P10-Q8): a design decision |
| Phase 7 R16 (baseline failure: CRLF evidence hash) | CLOSED: `test_p5_d3_adoption_record…` passes on this checkout |
| Baseline failure `test_m8_future_playoff_sentinel…` | Not a portability defect: it needs the D18 Statbotics snapshot (`C:/Dev/StratAI-artifacts/…`) and 2026 playoff alliance data from the environment of record. CARRIED; unchanged |
| P8-R4 deployment | DECISION / infrastructure: CARRIED to final remediation |
| P8-R5 slow routes, P9-R7 briefing latency | Measured in P10-M3 (P10-R3) |
| Phase 10 M4–M6 prerequisites (P10-Q2, Q3, Q4) | BLOCKED: see `P10_M0_DECISIONS.md` |
