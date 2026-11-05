# Phase 11 plan: live alliance selection (manual draft tracking and a dynamic picklist)

- **Spec:** `docs/P11-P19Phases.md` §5. Global rules are in §3. Status PROPOSED; Phase 11 was started on the owner's
  instruction of 2026-11-04.
- **Decisions:** `decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md`. P11-FB1 is frozen there.
- **No milestones** (the spec defines phases only). The work units below are an internal order. The phase is done
  only when DM1–DM3 and acceptance criteria 1–9 hold.

## Work units

| Unit | What | Depends on |
|---|---|---|
| W1 | Pure draft log (`workspaces/draft_log.py`): actions, replay, validation, effective history, board state. Reuses `ml.playoffs.selection` (`DraftState`, `turn_order`, the pool and captain rules, extracted without any change of behavior) | — |
| W2 | Migration 0013: `draft_records`, `draft_actions` (append-only, client action ids, a per-record sequence, author composite FK, source and mode), the CHECK for the new permission | — |
| W3 | Service (`workspaces/live_draft.py`): start (setup from the rankings, roster and approved ruleset, or manual rules), append, undo, correct, close, reopen, read; a row lock serializes appends; activity log entries | W1, W2 |
| W4 | Recommendations (`workspaces/draft_recommendations.py`): the engine first, then P11-FB1; a warm cache per event; provenance (record sequence, models, ordering policy) | W1, W3 |
| W5 | API under `/workspace/alliance-selection/drafts…`: classified (zero-LLM), path-pinned, contract-locked | W3, W4 |
| W6 | Frontend: a live page (a board, recording controls, primary and backup lists, history, polling, stale marking), reached from the drive-team and admin dashboards; a workspace client checked against OpenAPI | W5 |
| W7 | Replay harness (`scripts/phase11_replay.py`): a seeded sample of real events, reconstructed from `data/alliances.py` and the rankings, with a 45-minute budget | W3, W4 |
| W8 | Docs (`docs/phase11.md`, `docs/team_workspaces.md`), the full regression run, and the acceptance record | all |

## Interfaces

- `draft_log.replay(actions) -> DraftView` is the single source of the state. The service, the recommendations and
  the replay harness all call it.
- The recommendations take `(DraftView, workspace team)` and call `ml.playoffs.service.pick_list` or
  `analyze_event`. They never change engine logic or gates.

## Risks

- **Environment:** this machine has no PostgreSQL. DB-backed tests (W2, W3, W5) and the real-data replay (W7) cannot
  run here. Unit tests cover W1 and W4 without a DB. The rest needs an isolated `stratai_test_<suffix>`.
- **Reconstruction:** TBA alliances give final alliances, not pick timing or who a team declined. W7 documents what
  cannot be reconstructed and records declines at a documented, conservative point.
- **Captain naming:** the P6-Q6 draft model names a captain when its seed's first turn comes, which covers
  promotion. The record uses the same convention: an explicit `captain` action checked against the captain rule, with
  projected captains shown and labelled.
- **Permission CHECK:** a deployment without 0013 refuses the new permission. `set_role_permissions` must explain
  this, not return a 500.
- **Statistical:** P11-FB1 is `not_validated` and shows no probability. The 2027 holdout is untouched.

## Verification states (§3.6)

The states are implemented, fixtures-tested, isolated-real-data, outcome-validated and human-accepted. Each unit's
state is reported in `PHASE_STATUS.md`.
