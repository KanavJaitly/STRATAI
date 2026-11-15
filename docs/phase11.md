# Phase 11: live alliance selection

**Status (2026-11-15): ACCEPTED WITH LIMITATIONS** by Kanav Jaitly and Sven Morais.
- Record: `.agent/phase11/P11_ACCEPTANCE.md`.
- Scope: manual draft tracking, the dynamic picklist (the P6-M7 engine, else P11-FB2) and the live-page team profiles.
- Not accepted here: P11A, `docs/P11-P19Phases.md`, FB2 as validated (it is `not_validated`), or migrations on any
  deployment.

Earlier status, kept: **Status (2026-11-04): implemented; NOT accepted.**
- Fixture-tested, and verified against the local API contract.
- Not verified on an isolated real-data copy, and not accepted by a human.
- Spec: `docs/P11-P19Phases.md` §5. Decisions: `.agent/phase11/decisions/`. State: `.agent/phase11/PHASE_STATUS.md`.

## What it does

During alliance selection, a team keeps a **private draft record** for the event and records each real action as
it happens:
- a captain named (this covers a captain promoted when a higher seed picked theirs);
- a pick (an invitation accepted);
- a decline;
- a backup robot.

After every action, StratAI recalculates the available pool and the team's primary and backup picks. Nobody types
the draft state in. A team that is picked, a captain, a team that declined (where the decline rule applies) and a
backup never appear as available, and so never appear as a recommendation.

## The record (`workspaces/draft_log.py`)

**An append-only log.**
- Each entry has a stable UUID (the client creates it, so a retried write is idempotent), a per-record sequence, an
  author, a server time and the client's time, a `source` (`manual` or `imported`) and a `mode` (`online` now;
  `local` is reserved for Phase 12).
- The state is always the log's replay, never a stored snapshot. So the state at any point is the replay of that
  prefix (P11-DM2), and Phase 12 can synchronize logs.

**Entries:**

| Entry | Meaning |
|---|---|
| `configure` | The setup: rules, final ranks, pool, what is missing, and provenance. The latest one governs, and every draft action is re-checked against it |
| `captain` / `pick` / `decline` / `backup` | The draft actions, in real order |
| `undo` | Removes the most recent action in effect. The entry it names must be that action, so an undo from a stale screen is refused |
| `correct` | Replaces an earlier action in effect with what really happened, or with nothing |
| `close` / `reopen` | A closed record refuses changes until it is reopened |

**One draft model.**
- The state is P6's `DraftState` and the order is `turn_order` (serpentine).
- The pool and captain rules are `pickable_teams` and `highest_ranked_captain`, extracted unchanged from
  `ml/playoffs/selection.py`. They are the same rules the P6-M6 draft model and the P7-M6 state check use.
- A captain is named at its seed's first turn, as the draft model names it. The board shows the captains the rules
  would name for the other seeds, labelled *projected*.

**Checks.**
- An action the rules make impossible is refused with the rule's code, for example `wrong_turn`,
  `team_on_alliance`, `team_declined`, `wrong_captain`, `captain_not_named` or `draft_complete` (the full list is
  `api/routes/live_draft.py` `RULE_CODES`).
- An administrator can record it anyway with an `override_reason`. It is then marked `overridden` in the history.
- An override never makes an impossible state; a team cannot be on two alliances, for example.
- After a correction or a new setup, an action that no longer fits is flagged `invalid`, or `not_applied` if it
  cannot apply at all. It is never dropped silently. While any action is flagged, recommendations are withheld
  (`record_needs_review`).
- A check that cannot be made is noted as unchecked, never failed and never guessed. Examples: no final ranks, so the
  captain cannot be checked; a captain rule the ruleset leaves unresolved.

## Setup (`workspaces/live_draft.build_setup`)

The setup takes:
- **Final qualification ranks**, under the same final-ranks rule as the pick list (`ranks_are_final`): fetched after
  the last qualification match and its result, and covering the roster. Otherwise `rankings_not_final` or
  `rankings_unavailable`.
- **The qualification roster** (the selection pool).
- **The event's rules**, from its season's approved P6-M1 ruleset (`approved_event_rules`). When none covers the
  event (`rules_required`), an administrator enters the alliance count, the picks per alliance and the decline,
  captain and backup rules as the event announces them. They are stored as `manual_entry`, attributed, and never
  guessed.

**Refresh ranks and rules** appends a new `configure` entry, for example once final ranks land.

## Recommendations (`workspaces/draft_recommendations.py`; decision P11-Q1)

The two sources are tried in a fixed order and never mixed.

1. **The P6-M7 engine, unchanged.**
   - It runs for the alliance the team is on, or is projected to captain, at the record's state.
   - Its ranking is served with its own status (`validated_playoff_success`, with its scope).
   - Today it refuses at every event (`playoff_models_not_accepted`), because the PX gates are unmet.
2. **The fallback rule P11-FB2** (since 2026-11-14), frozen in
   `.agent/phase11/decisions/P11_FB2_DECISION_2026-11-14.md` before any code or measurement. It ranks the available
   teams by what each adds to the alliance being built; see "P11-FB2" below.
3. **P11-FB1** (2026-11-04 to 2026-11-14; no longer served), frozen in the decision record before implementation.
   It stays in the code as a pure function (`fallback_lists`), for the tests and the FB1/FB2 comparison.
   - It ranks the available teams by the P5-M4 team-strength ordering at the selection moment.
   - **Primary** is the first team. **Backups** are the next `max(3, m)`, where `m` is the other alliances' picks
     before your next turn. If at most `m` teams are picked and nobody declines, at least one listed team is left
     when your turn comes.
   - Excluded, as the rules require and not by any prediction: your own team and alliance, and teams projected to
     captain an alliance that acts before your next turn.
   - It is served `not_validated`. It shows no probability, and it carries the engine's refusal.

### P11-FB2: the alliance-aware fallback (`workspaces/draft_fb2.py`)

Decided by Kanav on 2026-11-14 (Sven's countersignature pending); `not_validated`, no probability. Kanav's 2024njfla
replay informed the design, so that event is not independent evidence about it.

- **Per-robot strengths at the event**, strictly before the selection moment:
  - from the P11A A3 estimator, copied unchanged (`ml/alliance/estimator.py`, `p11a-a3-v1`, sha256 `47b6cc…`), with
    the current-event population prior only;
  - fitted on the qualification alliance rows, with auto, teleop and endgame from the P5-M7 adapter (fouls excluded);
  - DQ'd alliances are left out.
  - **Fallbacks, frozen:** without enough breakdowns (or an unsupported season, or a degenerate fit), one total-score
    component (fouls included). Without that either, FB2 is withheld (`fb2_projection_unavailable`); FB1 is never
    served instead. Before the P5-M4 switch point, EPA components.
  - P11A's scoring configurations, `data/season_scoring/` and E5 are not used. P11A stays disabled.
- **Gap filling:**
  - `B_c` is the median per-robot `s_c` among the event's top 24 by total.
  - Your alliance's `gap_c = max(0, B_c − members' mean s_c)`.
  - A candidate fills `min(max(eff_c, 0), gap_c)`.
- **Reliability and consistency:** `ρ = reliability/100 × (1 − 0.25 × (1 − consistency/100))`, from Phase 3 at the
  selection moment. When either is absent, its factor is 1, and the card says so.
- **Rank score** `R = members' total + Σ_c s_c·ρ + 0.5 × fit`. Ties go to the projected score, then qualification rank,
  then team number.
- **Projected alliance score** (shown, never adjusted): the members plus the candidate (the best three of four), with
  no later pick assumed. It is labelled `not_validated` and has no interval.
- **Informational only:**
  - defense ("Defense: no scouting" when there is too little);
  - the decline flag ("May decline (projected captain of alliance N).").
- **Unchanged from FB1:** the exclusions, the backups `max(3, m)` and the movement text.
- **Every card** carries fixed-template reasons (record §5), including qualification rank and, for a team ranked in
  the lower half, why it is still listed. `candidate_projections` gives every available team's card, so the profile
  drawer shows any team's projection with your alliance.
- **Speed on 2024njfla** (`stratai_test_p11fu`): cold 442 ms (ordering 365 ms, estimates 76 ms); warm p95 4.7 ms over
  27 states.

**What every response carries:**
- the record sequence it reflects;
- the movement explanation, as fixed templates ("Team T was picked by alliance 3.", "Team S is now first.");
- its provenance (rule, ordering policy and as-of, model sha256; for FB2 also the estimator version, mode, benchmark,
  members, gaps and the selection moment);
- its timings.

**Withheld, with the exact reason:**
- `not_configured`, `record_needs_review`, `team_not_selecting` or `no_remaining_turn`;
- the ordering's own refusal (`model_not_loaded`, `epa_source_not_loaded`, `epa_source_incomplete`);
- `no_candidates`.

**Speed (P11-Q3, ≤ 2 s at p95).** The ordering and profiles at the selection moment are computed once per event and
cached for 10 minutes, so an action only re-filters the pool. The first, cold computation for an event is reported
separately. The page asks for recommendations as soon as a record opens.

**Offline (§3.5).** Phase 11 has no local mode. Phase 12 adds it, on this log.

## API (team-private, under `/workspace`)

| Operation | Permission | Notes |
|---|---|---|
| `GET /workspace/alliance-selection/drafts` | `alliance_selection` | The team's records, optionally for one event |
| `POST /workspace/alliance-selection/drafts` | + `alliance_selection_record` | Start, for an event the team attends (`team_not_at_event`); one per team per event (`draft_exists`) |
| `GET /workspace/alliance-selection/drafts/{record_id}` | `alliance_selection` | The board, effective draft, flags, history |
| `POST /workspace/alliance-selection/drafts/{record_id}/actions` | + `alliance_selection_record` | A captain, pick, decline or backup; `override_reason` optional |
| `POST /workspace/alliance-selection/drafts/{record_id}/undo` | + `alliance_selection_record` | `target_action_id`: the action you see as last |
| `POST /workspace/alliance-selection/drafts/{record_id}/corrections` | + `alliance_selection_record` | `replacement: null` for "did not happen" |
| `POST /workspace/alliance-selection/drafts/{record_id}/close` | + `alliance_selection_record` | |
| `POST /workspace/alliance-selection/drafts/{record_id}/reopen` | + `alliance_selection_record` | |
| `POST /workspace/alliance-selection/drafts/{record_id}/setup` | + `alliance_selection_record` | Refresh the setup from the event's data |
| `GET /workspace/alliance-selection/drafts/{record_id}/recommendations` | `alliance_selection` | The P11-Q1 recommendation |

**Rules every route follows:**
- The workspace comes from the session, so another team's record is `draft_not_found`.
- Every write needs `X-StratAI-CSRF: 1` and a verified workspace.
- The permission is checked before anything else about the request.
- Appends lock the record row, so concurrent recorders are serialized and the second is re-checked.
- Every change is written to the activity log (`draft_started`, `draft_action_recorded`, `draft_action_overridden`,
  `draft_action_undone`, `draft_action_corrected`, `draft_reconfigured`, `draft_closed`, `draft_reopened`).

**Contracts.** All ten operations are locked (`docs/api_contract_lock.json`; no earlier entry changed) and
classified in the zero-LLM audit (the recommendations as an output). They are deliberately outside the P7-Q4 example
scope, because they are team-private (`api/examples.py` `TEAM_PRIVATE_PREFIX`).

## Permissions (P11-Q2, P11-Q4)

- **`alliance_selection_record`** is new and configurable. Administrators always hold it. It is off by default for
  strategy and scouter; an administrator can grant it in the Permissions tab, for example to the one drive-team
  member at the table.
- The board and the picklist use the existing **`alliance_selection`** permission.
- Migration 0013 adds the permission to the CHECK constraint. On a database without 0013, changing it is refused
  with `permission_needs_migration`, and the draft routes answer `live_draft_unavailable`; neither is a 500.

## Storage: migration 0013

- `draft_records`: one per workspace per event, with a client UUID.
- `draft_actions`: the log.
  - Composite keys tie each action to its own team's record and each author to its own team's membership.
  - A trigger refuses every UPDATE.
  - The application never deletes an action. Actions go only with their workspace, by cascade.
  - Migration 0014 (2026-11-09) checks the two author keys at commit. As 0013 shipped, they were checked immediately,
    so deleting any workspace with a recorded action failed with a foreign-key violation. The first DB-backed test
    run found it.

Applying 0013 and 0014 to a deployed database is a separate, authorized step (§3.6).

## The web app

- **Page:** `/alliance-selection/live?event=…`, linked from the drive-team dashboard and the Admin Dashboard.
- **Board:** a turn banner, the alliances (with projected captains labelled) and the unavailable teams with their
  reasons.
- **Recording (for those allowed):** large team tiles. Tap a team, then "Alliance N picks T" or "T declines". A
  one-tap "Confirm alliance N captain: C" names the captain, so no team number is typed. A refusal offers "Record
  with override" with a reason.
- **Your picks:** the source, the validation status and the movement. They are marked **Stale** when they reflect an
  older record version or a refresh failed, and they are never shown as current.
- **History:** undo last, correct any action, and every superseded entry kept.
- **Updates:** the page polls every 2 s while visible.

### Team profiles on the live draft page (follow-up, 2026-11-14)

Every team number on the page opens that team's profile in a slide-over drawer: the primary and backups, the
unranked list, the pool tiles, the alliances table (including projected captains), the unavailable chips and the
history entries.
- **Nothing on the page unmounts.** The selected tile, a pending action or override form, the scroll position, the
  record, the recommendations and the 2 s polling all carry on. The drawer repeats the board's record version and the
  picks' freshness (current or stale), so they stay visible while it is open.
- **Pool tiles** keep their select button and get a separate profile button beside it, 44 × 64 px, so a tap on the
  tile still selects.
- **The drawer** is a modal dialog (`role="dialog"`, `aria-modal`): focus moves to its Close button, Tab stays inside
  it, and Escape, Close or a tap outside it closes it and returns focus to the number that opened it. It is axe-clean
  in the tests.
- **What it shows**, all from locked read operations the team page already uses (no new operation):
  - qualification rank (from the record's setup) and where the team stands on the board;
  - the won–lost–tied record, the alliance score in each match (chart and table), from `GET /events/{event}/matches`;
  - EPA total/auto/teleop/endgame with its source or the reason it is withheld; average score, SD, Phase 3
    consistency and reliability, each with n or its absent reason; defense and feeding, or "not enough scouting";
    all from `GET /teams/{team}/events/{event}/strength`;
  - the average alliance score at each of the team's events this season (the same strength operation at each
    earlier event);
  - why the team is or is not in your picks, and its projected score with your alliance (Part B; under P11-FB1 there
    is none, and the drawer says so).
- **As of the selection moment.** Every read passes `as_of` = the record's selection moment (one minute after the last
  scheduled qualification match), which the recommendations response now reports in `provenance.selection_moment`.
  Before that moment, or when it is unknown, the reads are as of now and the drawer says so.
- **"View full profile"** goes to `/events/{event}/teams/{team}?from=live-draft&event={event}&as_of={moment}`. The
  team page then shows "← Back to live alliance selection" top left; nothing else in its header changes. The selected
  tile and scroll position travel in router state, never browser storage: the live page stamps its own history entry
  before leaving, so the back link and the browser's back button restore the same board.
- **Contract:** `HistoryOut` gains optional `team_number` and `seed` (additive; decision
  `.agent/phase11/decisions/P11_FU_CONTRACT_2026-11-14.md`, relocked).

## Verification (P11-DM1 … DM3)

| Check | Where | State (2026-11-04) |
|---|---|---|
| Replay, every rule, undo/correct equivalence, overrides, edge cases | `tests/test_phase11_draft_log.py` | fixtures, passing |
| Recommendations never list an unavailable team; fallback labelling; withheld reasons; warm timing | `tests/test_phase11_recommendations.py` | fixtures, passing |
| Code/migration/permission agreements | `tests/test_phase11_live_draft_units.py` | passing |
| Every route as each role and another team, CSRF, concurrency, append-only, idempotency | `tests/test_phase11_live_draft_api.py` | written; **not run**: no PostgreSQL on the build machine |
| Real past events replayed action by action (seeded sample, ≤ 45 min) | `python -m scripts.phase11_replay` | harness fixture-tested; **not run** on real data |
| The page: recording, override, stale, withheld, start with manual rules, permission, axe | `frontend/src/workspace/LiveDraftPage.test.tsx` | passing |
| P11-FB2 rules: estimates, modes, benchmark, gaps, ρ, ties, decline flag, defense, templates; the estimator copy | `tests/test_phase11_fb2.py` | fixtures + one read-only real-event loader test, passing (2026-11-15) |
| Team profiles: drawer from every surface, focus trap, Escape, polling, as-of, full profile and back, axe | `frontend/src/workspace/LiveDraftPage.test.tsx` | passing (2026-11-15) |
| FB1 vs FB2 on replayed real selections (descriptive), P11-DM1 under FB2 | `.agent/phase11/results/P11_FB2_COMPARISON_2026-11-15.md` | run on `stratai_test_p11fu`; DM1 holds (6/6, 29/29, 2024njfla) |
| Tablet (820 × 1180, touch, Chrome): drawer, info buttons, back with selection and scroll restored, axe with contrast | Playwright script, outside the repo | 24 of 24 checks, twice (2026-11-15) |

### FB1 vs FB2 (descriptive, 2026-11-15)

**Not a validation.** These numbers describe how often each rule listed the team actually picked, not pick quality.
Kanav's 2024njfla replay informed FB2.

On replays of real selections, with the Phase 11 samples (seed 20261104) on `stratai_test_p11fu`, FB2's four-team
list held the actual pick more often than FB1's:
- **Wide sample (472 picks):** 62.1% against 51.7%. As primary: 128 against 103.
- **Prescribed sample (96 picks):** 69.8% against 59.4%.

2024 is about level, and 2025 and 2026 favour FB2. At 2024njfla, MORT's picks were 1218 (FB1 unlisted, FB2 backup 3)
and 2577 (FB1 backup 3, FB2 primary). FB2 was not tuned afterwards. Details:
`.agent/phase11/results/P11_FB2_COMPARISON_2026-11-15.md`.

