# P10-M2 — Live-sync stress harness and simulated event: acceptance record

**status:** the spec's acceptance criteria are MET on local evidence (2026-10-21), with the limitations below.
**P10-DM3 is met for the local configuration only.** It is not verified in the production configuration (models,
D18 / live EPA source): that is CARRIED to the environment of record.

| Verification state | Result |
|---|---|
| Implemented | `scripts/phase10_live_sync_stress.py` (harness H4.1). `database/connection.py` `read_snapshot` / `consistent_reads`, applied to `build_team_features`, `build_team_strength`, `analyze_event` and `pre_match_inputs` |
| Defect found and fixed | **A live-sync race:** a sync committing between a team's feature reads gave a `TeamFeatures` invariant failure, 8 HTTP 500s in run H1-b. Fixed by one snapshot per response |
| Tests | `tests/test_phase10_snapshot.py`, on a disposable database (12 pass). The race is reproduced deterministically (it fails without the snapshot), and the view-level mixing likewise. Also: isolation, writers never blocked, read-only, no leaks on errors, nesting, and concurrent readers against 25 streaming commits. `tests/test_phase10_stress_harness.py` (17 pass): the verdict, pause detection, the independent recomputation, and a non-vacuous join check |
| Reviewed | Review R1: all findings accepted; fixes or recorded residuals in the review record |
| Trial inventory | `runs/m2_trials/TRIAL_INVENTORY.md`: every run, with version, configuration, outcome and evidence, including the reclassification of 4 runs as VM-suspended (environment-invalid) |

## The acceptance runs

The prescribed workload, harness H4.1, final code (`code_sha256` `c5686c343d…`), files in `runs/m2_h41/`.
Settings: 2024casj (93 matches, 42 teams), 6 matches per poll, 6 readers, budget 1,200 s, stall threshold 120 s,
`EPA_SOURCE=statbotics`.

| Run | Outcome | Duration | Reads | 5xx | Stale / look-ahead | Pauses | Readers alive after join | Idle re-poll loaded | DB dropped |
|---|---|---|---|---|---|---|---|---|---|
| h41_run1 | pass | 403 s | 5,487 | 0 | 0 | 0 | 0 | 0 | yes |
| h41_run2 | pass | 428 s | 5,432 | 0 | 0 | 0 | 0 | 0 | yes |
| h41_run3 | pass | 429 s | 5,454 | 0 | 0 | 0 | 0 | 0 | yes |
| h41_run4 | pass | 400 s | 5,446 | 0 | 0 | 0 | 0 | 0 | yes |
| h41_run5 | pass | 403 s | 5,400 | 0 | 0 | 0 | 0 | 0 | yes |

**5 of 5 runs, and no run of this harness version was excluded.** The H4 runs (`runs/m2_h4/`, 5 of 5 pass) are
kept but not counted: their reader-join check was vacuous.

**Latency under load, 200s only, medians across runs:**

| View | Median | p95 | Max |
|---|---|---|---|
| Pre-match report | 0.85–0.92 s | 1.05–1.29 s | 2.42 s |
| Strength | 0.22–0.24 s | — | 1.10 s |
| Analysis (114–116 real builds per run) | 5.1–5.2 s | — | 8.8 s |

## Against the spec's criteria

| Criterion | Verdict |
|---|---|
| No 5xx and no crash | **MET:** 0 in 5 of 5 |
| No stale data: after each poll that loads results, the served team metrics and strength reflect exactly the matches loaded so far, against an independent recomputation | **MET:** 16 polls × 42 teams × 5 runs, 0 mismatches. **And by construction during a sync:** one snapshot per response, tested deterministically |
| No look-ahead | **MET in the sense checked** (no unplayed match counted). **LIMITATION:** point-in-time `as_of` is not exercised by the stress test (P10-R5; covered by the earlier phases' as_of tests) |
| Latency recorded under load | **MET** |
| Within the time budget | **MET:** at most 429 s of 1,200 s; every run under the 45-minute limit |
| Disposable DB dropped | **MET:** 5 of 5, and none left (checked). Earlier runs killed by a segfault or timeout had left 3, which were dropped by hand |

## What this does not establish (P10-R5)

- **Not exercised:**
  - model-backed outputs (no models: analysis after the switch point and the strategy parts are refusals);
  - the D18 or live EPA source (EPA absent);
  - point-in-time `as_of`;
  - the contents of analysis and report beyond their status;
  - concurrency through a real network server (in-process TestClient);
  - other events and data edge cases.
- **Not covered by the snapshot:** reads through the app's own EPA provider and scale lookup (P10-R4).
- **Environment:** a VM suspend invalidates a run. The H4 heartbeat detects it (P10-R1); none occurred in the
  acceptance runs.
