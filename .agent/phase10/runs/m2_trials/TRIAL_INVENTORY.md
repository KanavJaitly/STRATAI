# P10-M2 — simulated-event trial inventory (2026-10-20/21)

All runs are `scripts/phase10_live_sync_stress.py` on event `2024casj`:
- 93 recorded matches (qualification first, then playoff) and 42 teams;
- `EPA_SOURCE=statbotics`;
- each run on its own disposable `stratai_test_p10_<pid>` database;
- source payloads read only from `stratai_test`.

Files in this directory are sanitized copies: no credentials, machine paths replaced by placeholders. The originals
were in the session scratchpad.

## Harness and code versions

| Version | Application code | Harness |
|---|---|---|
| **H1** | Before `read_snapshot` (each feature read on its own connection) | Strength check compared `matches_considered` (wrong: it counts scheduled-but-unplayed matches by design) |
| **H2** | `read_snapshot` in `build_team_features` | Strength check compares `average_score.n` and its value; no watchdog |
| **H3** | As H2 | As H2, plus the stall watchdog (`InFlight`, `Watchdog`, `stall_diagnostics`); a stall force-drops the disposable DB |

The application code did not change between H2 and H3; only the harness did.

## Every run

**Configuration** is matches per poll / readers. "OK" is the harness's own `ok`. Every OK run completed all 93
matches with **0 problems (stale or look-ahead) and 0 server errors**.

| Run | Version | Config | Instrumentation | Duration | Outcome | Evidence |
|---|---|---|---|---|---|---|
| H1-a | H1 | 20 / 3 | none | crashed | **Harness defect:** `KeyError: 'scoring'` (wrong response path) | none (session log only) |
| H1-b | H1 | 20 / 3 | none | 94 s | **Application failure:** 8 HTTP 500s (strength 2, analysis 4, report 1, briefing 1), `TeamFeatures` invariant `auto_points_matches_used (15) cannot exceed matches_used (12)`. Also 42 strength "problems" per poll before quals finished: a **harness defect** (the H1 check) | none: overwritten by the next run (values from the session log) |
| H2-a | H2 | 20 / 3 | none | 1,042 s | **Stall:** one analysis request took 1,010 s; the main loop stopped after poll 2 and the run was stopped by its time budget. 0 problems and 0 5xx in the polls that ran | `p10_trial.json` |
| H2-b | H2 | 20 / 3 | external `pg_stat_activity` sampling | 72 s | OK | `p10_trial2.json` |
| H2-c | H2 | 20 / 3 | `faulthandler.dump_traceback_later(100, exit=True)` | under 100 s | exit 0 (finished before the dump) | none (no `--out`) |
| H2-d (t1) | H2 | 6 / 6 | `faulthandler` repeat dump every 240 s | 440 s | OK (survived two dumps) | `p10_t1.json`, `stack_1.txt` |
| H2-e (t2) | H2 | 6 / 6 | `faulthandler` repeat dump | about 240 s | **Instrumentation failure:** segmentation fault at the 4:00 dump | `p10_t2.err`, `stack_2.txt` |
| H2-f (t3) | H2 | 6 / 6 | `faulthandler` repeat dump | about 240 s | **Instrumentation failure:** segmentation fault at the 4:00 dump | `p10_t3.err`, `stack_3.txt` |
| H2-g (t4) | H2 | 6 / 6 | none | 459 s | OK | `p10_t4.json` |
| H2-h (t5) | H2 | 6 / 6 | none | killed at 700 s | **Hang:** killed by the outer `timeout 700` (harness budget 600 s); no report written; its disposable DB was left and dropped by hand | none |
| H3-a..c (t6–t8) | H3 | 6 / 6 | none | 485 / 508 / 502 s | OK, OK, OK | `p10_t6.json`, `p10_t7.json`, `p10_t8.json` |
| H3-d..k (s11–s18) | H3 | 20 / 6, stall 60 s | none | about 150 s each | s11, s13–s18 OK. **s12: stall:** analysis at 99.5 s; watchdog fired after poll 3 (60 of 93 matches) | `p10_s11..s18.json` |
| H3-l (tw) | H3 | 20 / 6, stall 60 s | external `ss` TIME_WAIT sampling | 156 s | OK | `p10_tw.json` |
| H3-m (mem) | H3 | 20 / 6, stall 60 s | external `free` / backend sampling | 158 s | OK | `p10_mem.json` |

Left-over disposable databases from H2-e, H2-f and H2-h (`stratai_test_p10_14915`, `_21753`, `_6228`) were found
and dropped by name on 2026-10-20. None remains.

## Counts by workload and version

Instrumentation failures (H2-e, H2-f) have no application outcome and are not in any denominator. Harness defects
(H1-a, and the strength problems of H1-b) are not application failures.

| Workload | Version | Valid runs | OK | Stall or hang | 5xx | Stale / look-ahead |
|---|---|---|---|---|---|---|
| 20 / 3 | H1 | 1 (H1-b) | 0 | 0 | **8** (the race, since fixed) | 0 real (all 42/poll were the harness defect) |
| 20 / 3 | H2 | 3 (H2-a, b, c) | 2 | **1** (H2-a) | 0 | 0 |
| 6 / 6 (the prescribed default) | H2 | 2 uninstrumented (t4, t5) + 1 instrumented (t1) | 2 | **1** (t5) | 0 | 0 |
| 6 / 6 (the prescribed default) | H3 | 3 (t6–t8) | 3 | 0 | 0 | 0 |
| 20 / 6 | H3 | 10 (s11–s18, tw, mem) | 9 | **1** (s12) | 0 before the stall | 0 before the stall |

**Since the snapshot fix (H2 + H3):**
- 18 runs had an application outcome;
- **3 of them stalled or hung** (H2-a, t5, s12);
- **0 had a server error or a stale or look-ahead value** before a stall.

The stalls occurred in all three workloads. These counts are not pooled into one pass rate, because the workloads
and harness versions differ.

## Secondary errors after a forced drop (s12)

When the watchdog force-dropped the database, about 260 reader requests failed with
`database "stratai_test_p10_16201" does not exist`, and 4 with `AdminShutdown`
(`p10_s12_err_summary.txt`). The 37 "problems" after poll 3 are the same cause.

These follow from the drop. They are not separate application failures. The report records the stall
(`stall.call`, `stall.seconds`) as the run's failure.

## Reclassification after review R1 (2026-10-21): the three stalls were VM suspends

The kernel log has the ChromeOS VM's `maitred` "prepare to suspend" and "set time" records. Converted to UTC, the
suspend windows contain each stall:

| Suspend (UTC) | Length | Run | Reclassified as |
|---|---|---|---|
| 2026-10-20 23:47:45 → 00:04:21 | 995.6 s | H2-a (started 23:47:16) | **environment-invalid** (was: stall) |
| 00:11:35 → 00:15:58 | 263.4 s | H2-c (faulthandler, exit 0) | **environment-invalid** (was: exit 0) |
| 00:46:50 → 01:08:40 | 1,310.0 s | t5 (started about 00:41) | **environment-invalid** (was: hang) |
| 01:39:32 → 01:40:56 | 83.8 s | s12 (started 01:38:14) | **environment-invalid** (was: stall). Every view's maximum latency is within 1–3 s of the gap |

**Corrected counts since the snapshot fix (H2 + H3):**
- 15 runs had a valid application outcome. All 15 are OK: **0 stalls, 0 server errors, 0 stale or look-ahead
  values.**
- 4 runs are environment-invalid (H2-a, H2-c, t5, s12).
- 2 are instrumentation failures (t2, t3).

These H2/H3 runs predate the review's fixes (the view-level snapshot, the harness H4 checks), so they are evidence
for the H2/H3 code only.

## H4 runs (2026-10-21, after the review fixes): `runs/m2_h4/`

| Run | Config | Duration | Outcome | Reads | 5xx | Pauses |
|---|---|---|---|---|---|---|
| h4_run1 | 6 / 6 | 423 s | pass | 8,716 | 0 | 0 |
| h4_run2 | 6 / 6 | 429 s | pass | 8,730 | 0 | 0 |
| h4_run3 | 6 / 6 | 421 s | pass | 8,680 | 0 | 0 |
| h4_run4 | 6 / 6 | 418 s | pass | 8,710 | 0 | 0 |
| h4_run5 | 6 / 6 | 402 s | pass | 8,717 | 0 | 0 |

`code_sha256` is `ae14d78605…` for all five.

**H4 harness defect, found by inspecting these reports:**
1. `reader_threads_still_alive` was `None` in every report: the summary was taken before the readers were joined,
   so that one check was vacuous. Every other check was valid.
2. After the qualification matches, the report and briefing readers asked for unplayed playoff matches: a correct
   but uninformative `404 match_not_found`, in about 55 % of those calls.

**Fixed in H4.1**, and the prescribed runs were repeated with it (`runs/m2_h41/`). The H4 runs are kept but not used
for the acceptance verdict.
