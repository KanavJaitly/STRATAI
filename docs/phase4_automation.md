# Phase 4 automation

This page covers the automation that finishes Phase 4's real-data milestones once
Statbotics recovers, at $0. Binding decisions D1–D11 are recorded in
`.agent/phase4/PHASE_STATUS.md`. This page is how they are implemented.

The system is three workflows, and **only a human starts the expensive ones**:

| Workflow | Trigger | Does | Worst case |
|---|---|---|---|
| `statbotics-monitor.yml` | daily cron + manual | Two-stage Statbotics probe, debounce, notifications, **shutdown** | 10 min/day |
| `phase4-data-build.yml` | manual only | Rebuild + gate the historical dataset, checkpoint it as a dump | 285 min/run |
| `phase4-execute.yml` | manual only | One Phase 4 attempt with Claude, one PR per milestone | 295 min/run |

Gate order, all fail-closed:

1. Monitor `RECOVERY_CONFIRMED`. This authorizes a human to look (D10), nothing more.
2. Data build: preflight → lock → sync → readiness gate `COMPLETE`.
3. Attempt: preflight (fresh probe, data `COMPLETE`, dump present, secrets, budget, resume point) → lock → restore → re-verify → Claude.

## 1. Monitor

One request a day, plus at most one retry, to the exact endpoint that populates
`team_event_stats`:

    GET https://api.statbotics.io/v3/team_event/1678/2024casj

Team 1678 at 2024casj is the record behind
`tests/fixtures/statbotics_team_event_2024casj.json`. The probe needs a pair that
is known to be real, because Statbotics answers a *nonexistent* team-event with
HTTP 500, which looks exactly like an outage.

| Stage | Passes only if | Fails on |
|---|---|---|
| A — transport | HTTP 200 with a JSON object body | DNS/connect error, timeout (15 s), any 5xx, 429, other 4xx, empty/`null`/non-JSON/non-object body |
| B — data | Body passes `normalize_statbotics_team_event_stats` and `check_entity` with no error; it is 1678/2024casj; EPA is finite; `matches_played > 0` | Schema drift, wrong record, null/NaN/Infinity EPA, zero-match placeholder, incoherent W/L/T |

Both stages run in memory, and the probe never opens a database connection.

Debounce and breaker:

- **Confirming recovery** needs two passes on consecutive UTC calendar days.
  - A same-day re-check doesn't count as a second day.
  - A skipped day restarts the count.
  - Any failure revokes recovery.
- **The circuit breaker** trips on three consecutive HTTP-200-but-unusable results
  (outages never trip it). It moves the monitor to `ESCALATED` until a human clears it.

**Shutdown.** Before each daily check, the monitor evaluates `automation/completion.py`
against `origin/main`. Phase 4 counts as complete only when all of these hold:

- every file from `M03_ACCEPTANCE.md` to `M13_ACCEPTANCE.md` exists, M11 included (D4);
- `PHASE_ACCEPTANCE.md` exists;
- issue #27 is closed;
- no `automation/phase4-m*` PR is open.

When that is true, it **disables** (never deletes) all three workflows and comments
on #27. If any of those facts can't be read, it treats Phase 4 as not complete.

## 2. Historical-data readiness (D8)

`automation/data_readiness.py` is separate from the monitor and never writes
persistent data (it uses session TEMP tables only).

The unit of requirement is a **team appearance**: one (team, event, match time)
for every scheduled match in 2024–2026. The backtest reads exactly one EPA row per
appearance, chosen by `ml/features/assembler.EPA_SOURCE_SQL` (decision D13):

- **Candidates** are the team's prior events it had finished before `as_of`: the
  event's `end_date` is before `as_of`, *and* the team's latest completed match there
  is before `as_of`.
- **Order** is latest `end_date`, then latest completed match, then `event_key`
  ascending. Postgres row order is never used.

Because the lookup only considers events that **have a `team_event_stats` row**, a
missing row silently falls back to older EPA. The gate therefore applies the same
rule independently, to the events the team actually completed matches at, and
classifies each appearance:

| Category | Meaning | Effect |
|---|---|---|
| `ok` | Expected row exists, is valid, and is the row the assembler selects | — |
| `no_prior_event` | No earlier concluded event; the assembler's documented `EPA_WITHHELD_NO_PRIOR_EVENT` path | Legitimate, counted and reported |
| `missing_expected_row` | Includes the silent-fallback case | `PARTIAL` |
| `invalid_expected_row` | Null or non-finite EPA (any component), or `matches_played` null or ≤ 0 | `INVALID` |
| `source_mismatch` | Gate and assembler disagree (impossible while their rules match; checked anyway) | `INVALID` |

Same-date ties (a division and its Einstein or DCMP finals) are resolved by the
rule and only counted, never blocking.

**M11's input.** Every completed match must have a current raw TBA payload whose
`score_breakdown` passes `ml/features/score_breakdown.auto_points`:

- **not published** — TBA has no breakdown for the match. Legitimate; counted.
- **raw payload missing** — `PARTIAL`.
- **rejected by the adapter** — `INVALID`.

It also requires a usable final ranking (via `read_final_ranks_for_season`, the
backtest's own reader) for every held-out 2026 event.

Status precedence is UNKNOWN > FAILED > INVALID > PARTIAL > COMPLETE. Only
**COMPLETE** permits M4–M7.

As of 2026-09-29 (after D13) the result is **FAILED**, only because Statbotics is unsynced:

- 19,735 required EPA source rows, 0 present;
- 0 ambiguous sources: 1,979 ties resolved by latest completed match, 0 by `event_key`;
- 53,195/53,195 completed-match score breakdowns valid (2024: 16,977; 2025: 17,846; 2026: 18,372);
- 208/208 held-out rankings present.

## 3. Data build (D3)

The ephemeral PostgreSQL service container is rebuilt by
`database.migrate.run_migrations`, `data.orchestrator.sync_season` (with
Statbotics) and `data.rankings.sync_event_rankings`. `automation/data_build.py`
adds no ingestion logic. It only chooses which events to pass to `sync_season`
and when to stop:

- **Resumable.** Only incomplete events are re-synced. A run starts by restoring the
  previous dump, and landing-layer dedup plus upserts make re-syncs idempotent.
- **Bounded.** It stops 20 minutes before its 240-minute deadline, then gates and dumps.
- **Degradation-aware.** It stops if the probe fails, or if most of a chunk is still
  incomplete right after syncing it.

The dump (`pg_dump -Fc`) is uploaded as an Actions artifact, with a sha256 and the
`team_event_stats` fingerprint recorded in state. The ceiling is 250 MB and
retention is 30 days.

State names a checkpoint only if one is usable:

- **Recorded only after upload.** A checkpoint is recorded only once its artifact
  upload has succeeded. A local dump alone isn't one, and neither is an oversized dump,
  which is never uploaded.
- **Resuming.** Before resuming, the build asks the Actions API whether the recorded
  checkpoint still exists.
- **Unusable previous checkpoint.** If it has expired, can't be downloaded, or fails
  its checksum or restore, the build starts fresh and state forgets it, so a dead
  pointer can never wedge later builds. A failed restore stops that run first, so it
  never continues on a half-restored database.
- **`data_ready` needs both** COMPLETE readiness and an uploaded checkpoint.
- **Progress** counts only rows captured in an uploaded checkpoint.

**Why a dump.** Statbotics is one request per team-event: 23,969 requests, about
1.7–3.3 h. Rebuilding inside every attempt would consume most of D2's 300-minute
budget before any Phase 4 work began, and would be paid again on each resume. The
dump is a checkpoint of the deterministic rebuild, not a separate database; it also
pins a snapshot, so backtests are reproducible. Approved by Kanav (D14).

## 4. One execution attempt (D1, D2, D9)

`phase4-execute.yml` runs three jobs, whose timeouts sum to 295 min (≤ 300).

- **preflight (5 min)** runs every gate in `automation/execution_state.preflight`
  and returns every reason for a refusal. It checks:
  - Phase 4 not already complete;
  - state `READY`;
  - monitor `RECOVERY_CONFIRMED`;
  - a fresh A+B probe;
  - `CLAUDE_CODE_OAUTH_TOKEN` present and `ANTHROPIC_API_KEY` **absent** (it would
    route usage to paid API billing);
  - data `COMPLETE` and its dump still available;
  - the monthly minute cap;
  - a resume point.

  It then acquires the lock and announces the attempt on #27.
- **execute (275 min)** does the following:
  - Checks out the resume commit with `persist-credentials: false`.
  - Restores the dump (sha256 check), then re-runs the readiness gate and requires
    `COMPLETE` with the recorded fingerprint.
  - Runs `claude -p` (CLI pinned to 2.1.285, `--permission-mode dontAsk`, an explicit
    tool list, never `--dangerously-skip-permissions`) on `prompts/PHASE4_UNATTENDED.md`,
    killed at 235 min.
  - Strips `ANTHROPIC_API_KEY` and every GitHub token from Claude's environment.
  - Sets `TBA_API_KEY` to a placeholder, so no ingestion can happen.
  - Bundles `automation/phase4-m*` branches.
- **publish (15 min)** runs on a fresh runner from pristine `main`.
  `automation/publish.py` accepts the bundle only if every branch:
  - is `automation/phase4-mNN` (03–13);
  - descends from the attempt's base;
  - changes nothing in `.github/`, `automation/`, `prompts/`, `docs/P4Milestones.md`
    or `tests/test_automation_*`.

  It is all-or-nothing, with non-force pushes (so a human edit to a branch is never
  overwritten). Then it opens one stacked PR per milestone, records the outcome,
  persists state and releases the lock, and runs even if the execute job failed.

**Outcomes.** Claude's report can only lower the verdict:

| Outcome | Effect |
|---|---|
| `progress_checkpointed` | `READY` |
| `budget_exhausted` | `READY`; resume from the last published branch |
| `claude_failed`, `infrastructure_failed` | `READY` |
| `awaiting_human_signoff` | `AWAITING_HUMAN` (M13's dated sign-off is Kanav's) |
| `escalated`, `usage_exhausted`, `harness_violation` | `ESCALATED` immediately |

Three consecutive attempts, or three builds, with no progress trip the breaker. A
real-data acceptance failure is an `escalated` stop, never an iteration (D9).

**Resume point.**

- Start from `main` if nothing unmerged is outstanding, if `main` contains the last
  published branch (merge commit, fast-forward), or if that branch's work is **on
  `main` by content**.
- The content test covers squash and rebase merges, which rewrite commits. At publish
  time each branch records a manifest: every path it changed since its merge-base with
  `main`, and that path's blob. The work is on `main` only if every manifest blob
  matches `main` and every deleted path is absent there.
- A file merely existing is never enough, and a hand-edit after the merge makes the
  test fail.
- A partially merged stack is not on `main`.
- Otherwise, start from the last published branch if it contains `main`.
- Otherwise refuse. Automation never rebases or overwrites human work.
- `clear-execution-escalation` also forgets the last published branch, but only when
  its work is on `main` by content.
- Deciding the resume point never marks anything accepted: acceptance is only the
  milestone's own artifact on `main`.

**Trusted code, never re-runs.** Every job of all three workflows first refuses a
dispatch from any ref other than `main`. Every job then checks out
`${{ github.sha }}`, the dispatched `main` commit, so only reviewed code runs.

- **Separate workspaces:** the execute job keeps the harness in `trusted/` and gives
  Claude a separate checkout of the resume commit in `work/`. `verify_dataset`,
  `run_claude` and the prompt come only from `trusted/`, and Claude's workspace has no
  push credentials.
- **No re-runs:** every job of the two heavy workflows refuses GitHub's "Re-run".
  A re-run reuses the preflight's earlier outputs, so it would skip the gates, the
  lock and the budget. Dispatch a fresh run instead. The execute and publish jobs' always-run steps are
  also gated on the guard, so a refused re-run writes no state, touches no lock and
  posts no alarm.
- **Minute accounting:** preflight takes the larger of the state ledger and the
  Actions API's billed minutes for every attempt of every heavy run this month, using
  `filter=all`. That catches re-run clicks and runs whose state record was never
  published. If the API can't be read, preflight refuses.

**State publication.** The monitor and the heavy workflows all write
`automation/phase4-state`. `automation/state_push.py` handles each write:

- It commits only that workflow's own files, then fetches, rebases onto the latest
  tip and pushes, at most 5 times, never with force.
- The workflows write disjoint files, so both sides' changes survive.
- A genuine conflict aborts, pushes nothing, and fails the step.
- A heavy workflow announces its result on #27 only after the push succeeded.
  Otherwise it posts "state NOT published", @-mentions you, and fails the run.

**Publication outcomes.** `publish.py` always writes its result. A missing result, an
exception, a violation or any failed push overrides Claude's own report, and such an
attempt never counts as progress. "Awaiting human sign-off" is accepted only if
`automation/phase4-m13` is published.

Protected paths are read NUL-separated, with git's path quoting and rename detection
off. A non-ASCII or renamed path can't slip past the check.

**Lock.** The lock is `refs/heads/automation/phase4-lock` (`automation/execution_lock.py`).

- Acquiring = creating the ref, which is atomic: the second creator gets a 422.
- A lock is stale only when the owning run is no longer queued or running according
  to the Actions API.
- Reclaiming a stale lock is a non-force fast-forward from the stale commit, which
  acts as a compare-and-swap.
- A database advisory lock can't work here: every run has its own ephemeral database.
- Workflow `concurrency: phase4-heavy` is a second, independent guard.

## 5. Operating it

    gh workflow run statbotics-monitor.yml -f mode=check                        # force a probe
    gh workflow run statbotics-monitor.yml -f mode=status                       # print state only
    gh workflow run statbotics-monitor.yml -f mode=clear-escalation             # reset monitor breaker
    gh workflow run statbotics-monitor.yml -f mode=clear-execution-escalation   # reset build/attempt stop
    gh workflow run phase4-data-build.yml                                       # after RECOVERY_CONFIRMED
    gh workflow run phase4-execute.yml                                          # after data_ready
    gh variable set PHASE4_MONITOR_PAUSED --body true                           # pause the monitor
    gh variable set PHASE4_MONTHLY_MINUTE_CAP --body 1500                       # planning cap (default 1500)
    gh workflow disable <file>                                                  # disable; history kept
    git show origin/automation/phase4-state:execution_log.jsonl                 # audit log

No command bypasses a gate. Clearing returns to `WAITING` or `READY`, and every
preflight rule still applies.

One-time setup, all at $0:

1. Verify billing at github.com/settings/billing: no payment method, or an Actions budget of $0 with "stop usage".
2. Keep Claude usage credits / extra usage **off** (D1).
3. Add repository secrets `TBA_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`).
4. Do **not** add `ANTHROPIC_API_KEY`; preflight refuses if it exists.
5. Optional: Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests".
   It is currently **off**; without it, publish pushes the branches and posts compare links instead of PRs.

## 6. Cost audit

| Service | Use | Paid? | Billing info needed? | Can it charge automatically? |
|---|---|---|---|---|
| GitHub Actions (private repo) | three workflows, ubuntu-latest (1×) | included minutes | no | only if a payment method + non-zero budget exist; otherwise blocked. **Verify.** |
| GitHub Actions artifacts | ≤ 250 MB dump, 30-day retention | included storage (500 MB on Free) | no | same as above |
| GitHub API / Issues / refs | state, lock, notifications | free | no | no |
| Statbotics API | probe + one sync | free, unauthenticated | no | no |
| TBA API | sync | free key | no | no |
| Claude Code (`CLAUDE_CODE_OAUTH_TOKEN`) | attempts | existing subscription usage | no | only if usage credits are enabled; keep off (D1). An exhausted allowance ⇒ `usage_exhausted` ⇒ stop |
| PostgreSQL | service container per job | free | no | no |
| Email | GitHub's own notification email | free | no | no |

Minute planning:

- Monitor: ≤ 310/month.
- Build: ≤ 285 each; expected 1–2 runs.
- Attempt: ≤ 295 each.

Preflight refuses a run if `used this month + worst case + 310 reserve` would pass
the cap (default 1500 of the account-wide 2,000 free minutes).

**Expected setup cost: $0. Expected recurring cost: $0/month.** The only known
billable paths are account settings this repository cannot read: a payment method
with a non-zero Actions budget, or Claude usage credits turned on. Both must be off,
and verified by Kanav.

## 7. Open items needing Kanav

1. **Review the D13 completed-match guard** in the PR. It changes accepted M1
   behaviour, beyond the literal tie-break instruction, to stop same-day
   Einstein/DCMP-finals EPA leaking into Saturday division matches (902 appearances).
2. **Setup** (§5): billing check, `TBA_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` secrets,
   and optionally allowing Actions to open PRs.
3. **Unknown subscription throughput.** Whether one 235-minute attempt fits the Claude
   plan's usage window is unknown; if not, the run stops as `usage_exhausted`.
4. **M13's dated sign-off** is yours, after real M4–M7 held-out results exist.
