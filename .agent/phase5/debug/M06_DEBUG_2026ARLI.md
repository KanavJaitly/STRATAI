# P5-M6 debug replay — 2026arli (unrecorded; debug mode writes no acceptance record)

- **Command:** `python -m scripts.phase5_m6_replay ... --debug-event 2026arli` (one event, one run).
- **Code:** commit 5b1e296, plus the uncommitted `data/orchestrator.py` watch hook, `data/replay.py` and
  `scripts/phase5_m6_replay.py`, committed at this checkpoint unchanged.
- **Isolated database:** `stratai_p5_replay_debug`, a template copy of `stratai`, left in place for inspection.
  The serving database was read only (recorded payloads and STRATAI values) and then closed.

## Outcome

- **Process:** exited with code 0. It ran 2026-10-02 23:09:31 → 2026-10-03 about 00:02 (about 52 min).
- **Match phase:** 23:09:50 → 23:51:25 (41.6 min).
  - 65 of 65 matches replayed (50 qualification, 15 playoff), one match per step.
  - Effective rate: about 38 s per match (about 1.6 matches per minute).
- **Final check, criterion (c):** about 10 min re-serving about 750 logged strength responses at about 0.7 s
  each.
- **Output lost to my own print:** the summary was printed truncated, at 6,000 characters, then piped through
  `tail -60`. The counts and the head of the problem list are gone; the surviving 62 lines are in
  `m6_debug_2026arli_raw_output.txt`. Evidence below is recovered from the database state (read-only).

## Recovered, verified evidence (read-only queries on the replay database)

| Check | Result |
|---|---|
| Final canonical 2026arli `matches` (65 rows) and `match_teams` equal the serving database | **identical** |
| Production ingestion runs (`sync_event`, pipeline `p5_m6_replay`) | 131 succeeded, 0 failed (1 initial schedule sync, 65 match syncs, 65 no-op re-polls) |
| No-op re-polls loading zero records ((b), part 1) | **65 / 65** |
| Watch follow-on `team_metrics` recomputes (`metrics_compute`) | 65 succeeded, one per loaded step |
| Stored `team_metrics` vs a fresh recompute at the final state (teams 16, 2341) | **equal in every field except `computed_at`** |

## Reported problems: all harness defects, none in the system under test

1. **(d) "team_metrics differs from a recompute"**, reported for every team at every step.
   - **Cause:** the harness compares `model_dump()` including `computed_at`, the recompute timestamp, which is
     necessarily different.
   - **Verified:** at the final state, `computed_at` is the only differing field.
   - **Fix (harness only):** compare excluding `computed_at`.
2. **(b) "control … in-event change"** at step 2 for teams 16 and 2341.
   - **Cause:** both were controls at step 0 (qm1), played qm2 at step 1, and were controls again at step 2. The
     harness updates a control's baseline only on steps where the team is a control, so step 2 was compared with
     step 0. The change it saw is the team's own qm2 result: correct behaviour.
   - **Fix (harness only):** refresh the baseline on every step at which the team is served. Later steps will
     have reported the same artefact; their lines were truncated.
3. **Output truncation:** the summary print. Fix: write the full result to a debug file.

**Not determinable from the truncated output:** whether any (a) affected-team, sentinel, re-serve (c),
policy-agreement or end-of-event endpoint problem was also reported. The surviving lines contain only (d) and
(b) entries, but the head of the list is lost. **A clean debug rerun after the harness fixes is needed to
establish (a), (b), (c), the sentinel and the policy agreement for this event.** Criterion (e) does not apply to
2026arli: no fallback teams.

## No correctness or determinism issue found in the system

- Ingestion reproduces the serving database's canonical rows exactly.
- Re-polls are no-ops.
- `team_metrics` is recomputed on every loading step and equals a fresh computation, apart from its timestamp.
- The STRATAI chain correctly refuses to load against the replay database. Its raw payloads were re-landed with
  new ids, so `StaleEpaArtifacts` fires. That is why the harness loads STRATAI from the serving database: correct
  behaviour.

---

# Rerun after the harness fixes — 2026-10-03 (commit baf8144; debug, unrecorded)

- **Changes:** the three harness defects are fixed, and sampling plus a time budget follow CLAUDE.md's 45-minute
  rule.
- **Full result:** `m6_debug_2026arli_20261003T222611Z.json`. Stdout: `m6_debug_2026arli_run2_stdout.txt`.

| Check | Scope | Result |
|---|---|---|
| Runtime | budget 45 min | **30.1 min**, 65 / 65 steps, not stopped by the budget |
| Production ingestion (`sync_event`) plus the watch follow-on | every match (65) | 65 syncs, no failures |
| (a) Per-match equality: served strength view = assembler `TeamFeatures` | 6 affected teams plus 2 seeded controls per step | **520 / 520 equal** |
| (a) An affected team's match count rises by exactly 1, traced to the new row's raw payload | all 390 affected-team views | **390 / 390** |
| (b) No-op re-poll lands nothing, and the re-request is identical | every step | **65 / 65** |
| (b) Control teams: no in-event change since their latest served state | 127 comparisons | **0 changes** |
| (d) `team_metrics` = a fresh recompute (excluding `computed_at`) | step teams; every team at the last step | **537 / 537** |
| Planted future-row (leakage) sentinel: a scored match 1 h after as_of, at step 32 | 1 | **no served change** |
| (c) Final re-request equality on the final database | seeded sample of 150 plus the sentinel step's (155 of 520 logged) | **155 / 155 identical** |
| Candidate EPA-rule agreement (Q1: `d18_skip` vs `literal_state`) at the EPA lookup | 520 | **520 / 520 identical** |
| End-of-event analysis and qualification-forecast endpoints | once | 200 (no problem logged) |

- **Problems:** 0.
- **Replay-log context:**
  - snapshot `c7bcc3cc…ef69`;
  - simulated lag 24 h;
  - model sha256s `1f0fe5aa…6312` and `c76d3299…b0a2`;
  - STRATAI fingerprints recorded in the result file.
- **Not covered by this event:** criterion (e) (2026iscmp fallback teams) does not apply to 2026arli.
