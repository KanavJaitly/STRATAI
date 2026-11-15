# Phase 11 — Live alliance selection: acceptance record

**Verdict:** ACCEPTED WITH LIMITATIONS.
**Decided by:** Kanav Jaitly and Sven Morais.
**Date:** 2026-11-15, the date this record is merged.

**Write-once.** This record is not edited after it is merged. A later change is a new dated record that names this
one.

**Scope: Phase 11 only.**
- **Accepted:**
  - manual draft tracking: each team's append-only live draft record, with recording, overrides, undo and correction;
  - the dynamic picklist: the P6-M7 engine when it serves, else the P11-FB2 fallback;
  - the team profiles on the live page.
- **Not accepted or approved here:**
  - P11A;
  - `docs/P11-P19Phases.md`;
  - FB2 as validated (it stays `not_validated`, and so does FB1);
  - applying migrations to any deployment.

**The FB2 records' countersignature lines.** Sven Morais's countersignature lines in
`decisions/P11_FB2_DECISION_2026-11-14.md` (line 7) and `decisions/P11_FU_CONTRACT_2026-11-14.md` (line 6) were
still blank when PR #46 was merged. Kanav instructed on 2026-11-15 to proceed as if they were signed. They were not
filled in by the agent. This record carries the joint acceptance by both owners.

| Verification state | Result |
|---|---|
| Implemented | Built 2026-11-04 on main (`3757d2a`): `workspaces/draft_log.py`, `live_draft.py`, `draft_recommendations.py`; migrations 0013 and 0014; ten locked `/workspace/alliance-selection/drafts…` operations; the page `/alliance-selection/live`. Follow-up (PR #46): `workspaces/draft_fb2.py`, `ml/alliance/estimator.py` (an unchanged P11A copy), `frontend/src/workspace/TeamProfileDrawer.tsx` |
| Decisions | `decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md` (P11-Q1–Q4, P11-FB1); `decisions/P11_FB2_DECISION_2026-11-14.md` (frozen before the build); `decisions/P11_FU_CONTRACT_2026-11-14.md` |
| Defects found and fixed | 2026-11-09 (PR #44): workspace deletion (migration 0014), the replay's backup-robot comparison, and the live page's header. 2026-11-15 (PR #46): three tablet display issues and a test-file syntax error (`fddc989`) |

## Evidence

| Evidence | Where | Result |
|---|---|---|
| 2026-11-09 verification on an isolated `stratai_test_p11` (a clone of the D18 handoff, through 0014) | `PHASE_STATUS.md`; PR #44, merged 2026-11-09 | DB-backed API tests pass; all 9 criteria PASS |
| Prescribed replay (`--per-season 2`, seed 20261104) | `results/p11_replay_20261109_235757.json` | 6 of 6 events match TBA |
| Wide replay (`--per-season 10`) | `results/p11_replay_wide_30events_20261109.json` | 29 of 29 match TBA; 2026tuis4 skipped (excluded by the approved 2026 ruleset) |
| Follow-up: team profiles and P11-FB2 | PR #46, squash-merged 2026-11-15 (`a218765`) | Backend full suite 3,404 passed; its 2 failures were only the missing `anthropic` SDK (`tests/test_phase9_llm.py` 93 of 93 with it installed). Frontend 249 passed. Contract lock and zero-LLM audit clean |
| FB1 vs FB2 comparison (descriptive) | `results/P11_FB2_COMPARISON_2026-11-15.md` | P11-DM1 holds under FB2: 6/6, 29/29, 2024njfla |

## Manual tests

### Manual test 1 (2026-11-14; Kanav; FB1 served)

**Setup:**
- 2024njfla replayed as team 11 (MORT), on `stratai_test` migrated through 0014.
- An administrator recorded, and a Drive team / strategy member watched in a second window.

**All checks passed:**
- the real draft recorded without overrides;
- the pool updates immediately;
- the recommendations refresh and cite the record number;
- `not_validated` is shown, with no probability;
- the backup counts are 3, then about 12;
- an illegal action is refused, and recorded with an override;
- a decline;
- undo (the entry is kept, marked superseded);
- correction (later actions flagged, recommendations withheld, then corrected back);
- the second window shows stale, then current;
- the Drive team member cannot record;
- there is no recommendation once the alliance is full;
- the final board matches TBA.

### Manual test 2 (2026-11-15; Kanav and Sven; P11-FB2 and the team profiles)

**Setup:** a re-check on `stratai_test_p11fu`.

**Checks:**
- profiles open from pool tiles, from the recommendations and from the Alliances table;
- "View full profile" and the back button return to the draft unchanged;
- FB2 cards show their reasons.

**The agent's real-Chrome check (2026-11-15)** at 820 × 1180 with touch: 24 of 24 checks, run twice, including:
- the drawer from every surface;
- the touch-sized info button;
- focus, Tab staying inside and Escape;
- the selection-moment as-of;
- the selected tile and pending action kept;
- full profile and back, restoring the selected tile and the exact scroll position, by the link and by the browser's
  back button;
- no axe issues in the open drawer, colour contrast included.

## Against the criteria

| # | Criterion | Automated | Manual |
|---|---|---|---|
| 1 | Validation and overrides | PASS (fixtures; DB `test_recording_follows_the_rules_and_an_override_is_kept`) | PASS (test 1: illegal action refused, then recorded with an override) |
| 2 | Immediate pool update | PASS (fixtures; replay checks after every action) | PASS (test 1) |
| 3 | Recalculation tracks the record sequence | PASS (fixtures, page tests; every replayed recommendation cites the current `record_seq`) | PASS (test 1: refresh cites the record number; the second window stale, then current) |
| 4 | Undo and correction equivalence | PASS (fixtures; DB test) | PASS (test 1: undo superseded; correction flags later actions and withholds recommendations, then corrected back) |
| 5 | Permissions by role | PASS (DB `test_permissions_are_enforced_on_every_route_as_each_role`, delegation test) | PASS (test 1: the Drive team member cannot record) |
| 6 | Team isolation | PASS (DB `test_another_team_cannot_read_or_change_the_record`) | DB test only |
| 7 | Contracts | PASS: the lock check is clean. The follow-up changed one locked leaf (`source` gains `fallback_p11_fb2`) and added optional fields, under `decisions/P11_FU_CONTRACT_2026-11-14.md`, relocked | Not applicable |
| 8 | Gates respected (P11-Q1) | PASS: the engine refuses (P6 gates unmet); the fallback is served `not_validated` with no probability (FB1, then FB2) | PASS (test 1: `not_validated`, no probability; test 2: FB2 cards with reasons) |
| 9 | Tablet usability | PASS (page tests, axe) | PASS (tests 1 and 2; the agent's real-Chrome check, 24 of 24 at 820 × 1180) |

## The observations that led to FB2

From Kanav's replay of 2024njfla as team 11 under FB1:
- **At MORT's first pick:** FB1's primary was 1811, which later captained alliance 8. MORT picked 1218. FB1 did not
  list it; FB2 lists it as backup 3.
- **At MORT's second pick:** FB1's primary was 5624, a team no alliance picked. MORT picked 2577, which was FB1's
  backup 3 and is FB2's primary. This is a near-tie: 7.3 points of estimated contribution against 7.0–7.3 for the
  next three.
- **Cause:** at a week-1 event EPA is withheld for every team, so FB1 ranked on schedule-dependent alliance averages.
  No data defect was found: 2577's 0-point qm30 is real, and 5624's DQ'd-partner match changes its average by less
  than 0.1.

## The FB2 comparison (descriptive, not validation)

The measure is whether the picked team was in the picking alliance's four-team list just before the pick. The detail
is in `results/P11_FB2_COMPARISON_2026-11-15.md`.

| Sample | Picks | FB1 listed | FB2 listed | As primary (FB1 / FB2) |
|---|---|---|---|---|
| Wide | 472 | 51.7% | 62.1% | 103 / 128 |
| Prescribed | 96 | 59.4% | 69.8% | 23 / 32 |

**How to read it:**
- 2024 is about level; 2025 and 2026 favour FB2.
- The two samples share 2 events.
- 2024njfla informed the design.
- FB2 was frozen before measuring and was not tuned afterwards.
- It describes agreement with human picks, not pick quality.

## Limitations accepted

- **Neither fallback is validated.** FB2 and FB1 are `not_validated`, and FB2's projected score is `not_validated`.
- **Declines and backup robots are not in the real-data replay.** TBA records no declines and no 2024–2026 backups.
  They are covered by fixtures and DB tests, and were tested by hand (manual test 1).
- **FB2's fallbacks to the total score or to EPA components** are covered by unit tests only: all 31 events in the
  comparison used the component fit.
- **FB2's weights are judgment calls, not fitted:** 0.5 for fit and 0.25 for consistency (with K = 24).
- **Defense and the decline flag are informational only.**
- **Environment:** verification ran on local machines only. No deployed database has migrations 0012 onward.
- **Database:** the comparison ran on `stratai_test_p11fu`, not `stratai_test_p11`. Its samples and per-event outcomes
  are identical to the 2026-11-09 runs.

## Follow-ups (not blocking)

- **P11A expected-score planning,** once a person enters a season scoring configuration (P5-D7).
- **Defense weighting,** once MORT has its own scouting data. That would be a new rule version with its own record.
