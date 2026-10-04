# P5-M6 recorded verification (P5-D14) — FAILED: diagnosis and decision request (2026-10-03)

**Status: ESCALATED under D9 (stop and escalate). No rerun has been made.** The failed record is kept unchanged.

## The recorded result

- **Record:** `.agent/phase5/results/p5_m6_replay.json`, commit `eafba43`, provenance commit `e61dadc`.
- **Selection:** `p5_m6_selection.json`, fingerprint `24e23b1a…4f48`.
- **Run:** 44 / 44 steps in 30.9 min, within the 45-minute budget, not stopped. **passed = false**, 14 problems:
  - 13 × (b) "control … in-event change since step N", all at the first playoff steps of E1, E2, E4 and E5;
  - 1 × (c) "143 sampled responses re-served differently on the final database" (143 of 175).
- **Checks that passed:**
  - (a) served = assembler: 352 / 352;
  - (a) match count +1, traced to its raw payload: 264 / 264;
  - (d) `team_metrics` = recompute: 678 / 678;
  - no-op re-polls: 44 / 44;
  - leakage sentinels: 10 / 10 unchanged;
  - (e) `fallback_stratai` served 80 times, 0 wrong;
  - E4 switch checks: 2 / 2 (raw EPA, then M5 v2);
  - endpoints: 8 / 8 returned 200.
- **Diagnostic:** `policy_differences` = 4. Production uses `d18_skip` (P5-D11).

## Diagnosis (read-only, against the isolated verification database and the selection record)

**1. All 13 (b) problems are the harness's own baseline error.**
- Each flagged control team played in that event's **post-window bulk catch-up sync**, which landed just before
  the first playoff step. 13 of 13 confirmed.
- The bulk sync is a new canonical input. P5-M6 (b) is "zero changes **without** a new input", so these changes
  are correct behaviour.
- The harness compared a control team only with its last *served* state, never resetting the baseline when a
  bulk sync landed that team's matches.

**2. The (c) problem is the harness re-serving with the wrong provider configuration.**
- The end-of-run re-serve used whichever EPA provider was current: the last event's (E5, season 2025, concluded
  seasons {2024}).
- Every 2026 entry was originally served with concluded seasons {2024, 2025}. The responses' EPA provenance
  differs in `concluded_seasons` and `season_end`.
- **EPA values are identical** under the two configurations: 0 of 264 affected-team lookups differ.
- **Observed vs predicted:** the observed mismatch share is 143 / 175 = 0.817, against a predicted 2026 share of
  288 / 352 = 0.818. The 2025 entries all matched.

**3. A latent ordering flaw in the approved procedure.** It caused no reported problem, but it matters for fidelity.
- P5-D14 processes events in E1–E5 order and assumed events "do not interact".
- They do, through season-wide causal scales: when 2026iscmp (July) was served, 285 earlier 2026 matches from the
  other selected events (2026nccab 71, 2026cur 139, 2026vache 75) had not yet been replayed.
- The serving path was correct for the database it saw: (a) equality held. But that database was missing
  pre-as_of history that the final database has.

**No defect in the system under test was found.**
- Ingestion, serving, `team_metrics`, idempotence, leakage protection, the EPA fallback and the policy switch all
  behaved as specified.
- The three faults are all in the verification harness or in the approved procedure's ordering assumption.

## Decision requested (Kanav)

**Approve a labelled rerun** (`p5_m6_replay_rerun1.json`, which supersedes but keeps the failed record), with the
harness fixes below.

**Unchanged:**
- the population, selection, seed and fingerprint;
- the windows;
- criteria (a)–(e) and their pass conditions;
- the 45-minute budget.

**Fixes:**
1. **(b) baseline.** After any bulk sync, every team with a match in it has its baseline reset: a bulk sync is a
   new input.
2. **(c) provider.** Each re-serve uses the provider configuration it was served with (by season).
3. **Ordering.** All planned actions run in global chronological order. The actions are:
   - each event's pre-window bulk sync, timed just before the window;
   - its window steps;
   - its post-window bulk sync, before its playoff steps;
   - **a final bulk sync of the event's remaining playoff matches** after its last window step.
   So every selected event's earlier rows exist before any later as_of is served. This changes the processing
   order and adds at most 5 bulk syncs; the selection is untouched.
4. **Record.** The full response log is persisted write-once next to the record, so a failure can be diagnosed
   from evidence rather than reconstruction.

**Estimated runtime:** about 32 min (31 min measured, plus 5 bulk syncs at about 10 s), under a 45-minute hard
limit.

The alternative is to keep P5-M6 as FAILED. DM2 then stays unmet regardless.
