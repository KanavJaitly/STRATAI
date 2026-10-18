# P6-M8 pre-run record (P6-Q1, P6-Q13): 2026-10-08

**Committed before any P6-M8 run and before PX-4.** The parameters are fixed in `p6_m8_pre_run.json`; the harness reads it and refuses without it. Prepared by Claude on Kanav's instruction (2026-10-08).

**Frozen basis:**
- P6-Q1: the population, the strong alliances, "identifies", the >50% criterion, predefined reason categories and a named mentor;
- P6-Q13: seeded, stratified, ≤45 minutes, fixed before the run;
- C2: FIRST Championship divisions are excluded, with their four-member alliances outside PX-1's representation, and counted.

**Population:**
- held-out 2026 events that P6-M1 reproduces, minus C2, recorded as intended vs validated;
- strata: TBA week × qualification-roster size tercile;
- **seed 20261012, 1 event per stratum** (22 strata on the approximate population).

**Runtime:**
- the synthetic engine timing gives about 25 minutes expected and 37.5 minutes worst case for 22 events;
- 2 per stratum would exceed the 45-minute limit;
- the hard 45-minute budget aborts the run with nothing recorded.

**Leakage sentinel** (frozen P6-M8 "Leakage" row; added to the harness at the same commit as this record):
- **Event:** the sampled event with the fewest teams.
- **Insertion:** a far-future playoff result with scouting rows, inserted into the isolated copy, then always removed.
- **Pass:** every output (ordering, both drafts, all contender probabilities) must be unchanged.

**Reason categories:** six, each with its required evidence; definitions are in the JSON.

| Code | Covers |
|---|---|
| `post_selection_event` | something after the selection moment decided it |
| `unmeasured_role` | defense, feeding or another unmeasured role |
| `insufficient_preselection_data` | absent or thin selection-moment data |
| `procedural_selection_event` | T601, T605 or a decline |
| `outcome_variance` | both baselines also missed |
| `data_error` | wrong input data |

Nothing is accepted by default. A miss without an accepted category counts as a miss.

**Mentor: Mr. Biery.** Kanav named him on 2026-10-08 as the proposed reviewer of every miss. **His agreement and any review are not yet confirmed.** `m8-review` requires his review file (`p6_m8_mentor_review.json`), naming him.
