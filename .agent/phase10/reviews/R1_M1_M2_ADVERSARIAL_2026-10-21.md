# P10 review R1 — independent adversarial review of P10-M1 and P10-M2 (2026-10-21)

**Reviewer:** an independent Claude Code subagent, told to refute.

**How it worked:**
- read-only;
- no database connection and no pytest (a full suite was running);
- in-process probes only (scratch files outside the repository);
- `phase7_contract_lock check` run with no database: `changed: [] added: []`.

The report is abridged below, every finding with its disposition. **All findings were accepted.** The fixes are
verified by tests: the test files are named per row, and the pre-fix reproductions are in
`runs/p10_r1_prefix_check.txt`.

## The headline: the three "stalls" were the VM being suspended

**Claim.** The kernel log shows `maitred: Received request to prepare to suspend` followed later by a
`set time to <epoch>` on resume, each time a stall was recorded.

**Verified independently on 2026-10-21.** The suspend and resume pairs, converted from the `set time` epochs and
the dmesg deltas:

| Suspend window (UTC) | Length | Run |
|---|---|---|
| 2026-10-20 23:47:45 → 00:04:21 | 995.6 s | H2-a (started 23:47:16): an analysis of about 1,010 s |
| 00:11:35 → 00:15:58 | 263.4 s | overlaps H2-c (faulthandler run, exit 0) |
| 00:46:50 → 01:08:40 | 1,310.0 s | t5 (started about 00:41): the "hang" killed by `timeout 700` |
| 01:39:32 → 01:40:56 | 83.8 s | s12 (started 01:38:14): the 99.5 s analysis. Strength max 84.4 s and report max 86.8 s match the gap |

**Disposition: ACCEPTED.**
- H2-a, t5 and s12 are reclassified **environment-invalid**: neither passes nor application failures
  (`runs/m2_trials/TRIAL_INVENTORY.md`).
- The connection-churn hypothesis is **not needed** to explain any stall.
- The harness now detects a pause itself (H4 heartbeat). A run with any pause is `environment_invalid`, never
  counted.
- The t2/t3 segfaults lie outside every suspend window, which is consistent with the faulthandler-instrumentation
  attribution.

## Findings

| # | Sev. | Finding (abridged) | Disposition |
|---|---|---|---|
| F1 | HIGH/MED | **The strength view was not one version.** `build_team_strength` re-read scores, season events and auto points through the plain `Database` after `build_team_features`. During a sync, `average_score.n` could disagree with the day counts and `season_by_event`, and it was served silently | **FIXED.** `@consistent_reads` (`database/connection.py`) puts the whole view on one snapshot. Deterministic test: with a commit between the feature build and the view's re-reads, the undecorated view mixes versions (n 4, day total 5) and the decorated one does not (`tests/test_phase10_snapshot.py`) |
| F2 | MED | **Other reads escaped.** Scale lookups and EPA providers were bound to the outer database; snapshots were per team, not per response; `analyze_event` and the pre-match report mixed versions across teams and across passes | **FIXED for every read through the passed database:** `analyze_event` and `pre_match_inputs` are `@consistent_reads`, and nested builds reuse the one snapshot. **Residual (P10-R4):** an EPA provider or scale lookup built by the app on `state.database` still reads on its own connection. A production `--watch` can refresh Statbotics `team_event_stats`, so an EPA value could come from a newer version than the scores. The residual is low because EPA is taken only from a strictly earlier, concluded event, never the event being synced |
| F3 | MED | **A chunked oversized manual upload returned 500, not 413.** The route's `await request.body()` raised `ClientDisconnect` | **FIXED** (`api/body_limit.py`). Test: a minimal app reproducing the route shape. The pre-fix code gives 500 `internal_error`; the fix gives 413 |
| F4 | MED/LOW | **The EPA backoff did not stop a burst:** 10 queued requests made 10 serial attempts. The reload path had no backoff | **FIXED.** The backoff is re-checked inside the lock, and a failed reload backs off while the loaded source keeps being served. Tests: a concurrent burst gives 1 attempt (the pre-fix code fails it); a failed reload is attempted once in the window |
| F5 | LOW/MED | **The bounded LRU was not thread-safe:** a `KeyError` under thread switching | **FIXED:** a lock, and the value is returned from a local. Test with `sys.setswitchinterval(1e-6)`, 6 threads × 3,000 lookups: no error. **Residual:** cycling over more than 8 snapshots re-reads every time (the bound is a deliberate trade-off) |
| F6 | MED | **The stale-data check was narrow:** after the poll only; count and mean only; 5xx in the check not counted; a non-200 strength skipped | **PARTLY FIXED (H4):** the check's own 5xx and every non-200 strength response for a team with completed matches are now problems. **The reads during a sync** are now one version by construction (F1, F2) and tested deterministically. **Residual (P10-R5):** the harness still compares count and mean only, and does not check analysis or report contents |
| F7 | MED | **Look-ahead was barely exercised:** readers never pass `as_of`, and every 2024 time is in the past | **ACCEPTED as a limitation (P10-R5).** Point-in-time correctness is covered by the earlier phases' as_of tests (P7-M7 report no-look-ahead, P5-M3 strength). The stress test checks only "no unplayed match counted" |
| F8 | MED | **The load was not representative:** most analysis and report calls were refusals; latency mixed refusals with real work; no error codes; EPA always absent; the live EPA source never exercised | **PARTLY FIXED (H4):** statuses carry error codes, and latency is also reported for 200s only. **Residual (P10-R5):** no models and no EPA rows locally (P9-R4), and the live EPA source was not exercised |
| F9 | LOW/MED | **Weak stall diagnostics:** `InFlight` keyed by the reader thread, not the worker; stacks cut to 12 frames; non-atomic stacks; main-thread hangs in the check or the idle re-poll unwatched; no wall clock or pause detection | **PARTLY FIXED (H4):** full stacks, UTC timestamps, a heartbeat with pause detection, and the pauses recorded in the stall record. **Residual:** worker-thread attribution and atomic stacks need a sampler such as py-spy, which is not installed |
| F10 | LOW | **Secondary errors after the forced drop were not separated** in the report | **ADDRESSED:** H4's `verdict` names each failure. A run with a pause is `environment_invalid`, so post-drop errors are never counted as application failures. The s12 error summary accounts for all 269 tracebacks as drop consequences |
| F11 | LOW | **The artifacts did not record their own configuration;** `ok` did not require reader activity | **FIXED (H4):** `harness_version`, `code_sha256` and `config` are in every report. The verdict requires completed reader calls, every view exercised, and reader threads stopped |
| F12 | LOW | **A 413 is served undeclared on locked operations** (for example `POST /predictions/win-probability` declares 200/404/422/500) | **DECISION REQUESTED (P10-Q9).** Declaring 413 on every locked operation would be a relock: a contract change that needs Sven's decision. The lock is unchanged; the 413 is documented in `docs/phase10.md` |
| F13 | LOW | **The statement timeout replaced any `options` in the DSN** | **FIXED:** the timeout is appended to existing options (tested) |

## Unconfirmed concerns

| Concern | Disposition |
|---|---|
| Connection doubling (a snapshot plus the outer connections) against `max_connections` | Measured in P10-M3: at most 10 PostgreSQL sessions sampled at 6 readers. Recorded with the pooling proposal (P10-D1) |
| Data edge cases (DQ, surrogates, `-1` recorded scores) in `expected_scoring` | OPEN (P10-R5). 2024casj passed with no mismatch. A recorded `-1` would show as a mismatch, not pass silently |
| A race between the watchdog's drop and the `finally` drop | Both use `IF EXISTS … WITH (FORCE)`: harmless |

## Per-criterion verdicts (the reviewer's), with the state after the fixes

See `M01_ACCEPTANCE.md` and `M02_ACCEPTANCE.md`. Those records apply the spec's criteria to the evidence after
the fixes. They do not adopt the reviewer's verdicts, which were given before the fixes.
