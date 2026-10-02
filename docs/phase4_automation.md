# Phase 4 automation — Statbotics recovery monitor

Status: **monitor only.** It detects and reports Statbotics recovery. It cannot
start Phase 4, sync data, run a backtest, or accept a milestone. Unattended
Phase 4 execution is not built; the decisions it is waiting on are listed at the
end of this page.

## What it checks

One request a day (plus at most one retry) to the exact endpoint the pipeline
uses to populate `team_event_stats`:

    GET https://api.statbotics.io/v3/team_event/1678/2024casj

Team 1678 at 2024casj is the record behind
`tests/fixtures/statbotics_team_event_2024casj.json`. A known-real pair is
required because Statbotics answers a *nonexistent* team-event with HTTP 500,
which looks exactly like an outage. `/matches` is not checked: nothing in the
pipeline consumes it.

| Stage | Passes only if | Fails on |
|---|---|---|
| A — transport | HTTP 200 with a JSON object body | DNS/connect error, timeout (15 s), any 5xx, 429, any other 4xx, empty body, `null`, non-JSON, a non-object JSON value |
| B — data | the body passes `normalize_statbotics_team_event_stats` and `data.staging.quality.check_entity` with no error-severity issue; it is 1678/2024casj; `epa_total` is present and every EPA component is finite; `matches_played > 0` | schema drift, wrong record, null/NaN/Infinity EPA, zero-match placeholder, incoherent W/L/T vs count |

Both stages run in memory. The probe never opens a database connection, so it
cannot put a health-check artifact into `raw_source_payloads` or
`team_event_stats` (a test enforces this).

**Stage B passing is not historical-data readiness.** `team_event_stats` has
never been populated (0 rows as of 2026-09-29). M4–M7 need a full Statbotics
season sync and a coverage check, which this monitor does not perform.

## State machine

    WAITING ──pass──▶ RECOVERY_PENDING ──pass, next calendar day──▶ RECOVERY_CONFIRMED
       ▲                     │                                            │
       └──────── any failed check (event: recovery_lost) ◀─────────────────┘

    3 consecutive HTTP-200-but-unusable results (Stage B, or a non-object body) ──▶ ESCALATED

- Two passes on the same UTC date count as one day. A day with no check at all
  (GitHub occasionally drops scheduled runs) restarts the count.
- Outages (5xx, timeouts) never trip the circuit breaker: waiting is the
  designed response to an outage. HTTP 200 with unusable data is different —
  waiting does not fix schema drift — so it escalates.
- `ESCALATED` keeps logging checks but advances nothing until a human runs
  `clear-escalation`, which returns to `WAITING`, never to `CONFIRMED`.
- `RECOVERY_CONFIRMED` authorizes nothing. It is reported to a human.

## Where things live

| What | Where |
|---|---|
| Code | `automation/statbotics_health.py`, `automation/monitor_state.py`, `automation/monitor.py` |
| Schedule | `.github/workflows/statbotics-monitor.yml`, daily at 15:37 UTC |
| State + append-only audit log | `monitor_state.json`, `monitor_log.jsonl` on the `automation/phase4-state` branch (never `main`) |
| Notifications | comments on issue #27, only on transitions |

The workflow pushes state with a plain (non-force) push, so a stale concurrent
run is rejected rather than overwriting newer state; `concurrency:` also
serializes runs.

Notifications: `monitor_initialized`, `tentative_recovery`, `recovery_lost` and
`escalation_cleared` are routine comments. `recovery_confirmed` and
`circuit_breaker` also @-mention the repository owner. Both reach email through
GitHub's own notifications (you authored issue #27, so you are subscribed), with
no mail service or credential. Confirm email is enabled for "Participating" and
"Watching" at github.com/settings/notifications. A run that fails outright
(e.g. an unreadable state file) is reported by GitHub's failed-run email.

## Operating it

    gh workflow run statbotics-monitor.yml -f mode=check              # force a check now
    gh workflow run statbotics-monitor.yml -f mode=status             # print state, change nothing
    gh workflow run statbotics-monitor.yml -f mode=clear-escalation   # human reset of the breaker
    gh variable set PHASE4_MONITOR_PAUSED --body true                 # pause (runs are skipped)
    gh variable delete PHASE4_MONITOR_PAUSED                          # resume
    gh workflow disable statbotics-monitor.yml                        # disable; history is kept
    git show origin/automation/phase4-state:monitor_log.jsonl         # inspect the audit log

None of these can move the monitor to `RECOVERY_CONFIRMED` without two real
consecutive-day passes. The workflow only runs from `main` (GitHub runs
scheduled workflows on the default branch only).

## Cost

The repository is private on a personal account, so Actions minutes are
metered against the account's free monthly allowance (public repositories are
not metered).

- One job a day on `ubuntu-latest` (the 1× minute rate), installing five small
  packages and making one HTTP request (two attempts at most): roughly 1–2
  billed minutes per run, ~30–60 minutes a month. The job has a 10-minute hard timeout, so the worst case
  is ~300 minutes a month.
- No secrets, no database, no paid API, no cloud resource. Statbotics is free
  and unauthenticated; comments and state commits use the built-in
  `GITHUB_TOKEN`.
- Storage: two small text files on one branch.

Whether exceeding the free allowance could ever *bill* depends on account
settings this repository cannot see (a payment method on file and the Actions
budget). With no payment method, usage past the allowance is blocked, not
charged. Verify at github.com/settings/billing that either no payment method is
on file or the Actions budget is $0 with "stop usage" enabled.

## Not built: unattended Phase 4 execution

These need a decision before any of it is built:

1. **Claude authentication.** The only official $0 route is a
   `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro/Max/Team/Enterprise,
   valid one year), which draws on the subscription's included usage instead of
   API billing. It needs your approval, and extra usage / usage credits must
   stay off so an exhausted allowance fails rather than bills.
   `ANTHROPIC_API_KEY` is pay-as-you-go and is ruled out.
2. **Runtime.** GitHub-hosted jobs stop at 6 hours; the 24-hour ceiling would
   need a chain of checkpointed jobs. Every minute of that is metered against
   the same free allowance, and M4–M7 plus the reviews could consume a large
   share of it.
3. **Database.** The only $0 option found that works while your computer is off
   and exposes nothing: a PostgreSQL service container inside the job, rebuilt
   from TBA + Statbotics by the existing orchestrator (the current database
   holds only public TBA data; `scouting_observations` is empty). No persistent
   remote database is free without a billing-backed account.
4. **Phase 4 rules that unattended execution cannot resolve by itself:**
   - The Phase Acceptance Gate requires *every* milestone to be individually
     accepted (`prompts/MASTER_BUILD.md`). M11 is deferred, not accepted, so
     Phase 4 cannot close as the rules stand.
   - M5 names an "agreed metric" (Spearman / top-8 recall) and M7 an "agreed ECE
     threshold". Neither is recorded, and the held-out season is not recorded as
     a decision either (the M4 script's example uses 2024+2025 → 2026).
   - The phase spec says "iterate" when a model misses the baseline; for
     unattended runs the instruction is to stop and escalate instead.
   - "Complete" historical coverage needs a definition: some team-events may
     legitimately have no Statbotics record, and the M4 script already excludes
     and reports EPA-incomplete matches.
