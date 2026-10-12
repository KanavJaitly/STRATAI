# P6-M8b pre-run record (P6-Q1, P6-Q13; `P6_M8B_SPEC.md` §1.3): 2026-10-11

**Adopted and committed before any M8b run, and before any 2027 data exists.** The parameters are in `p6_m8b_pre_run.json`; the M8b harness reads it and refuses without it.

**Prepared by Claude Code on Kanav Jaitly's instructions of 2026-10-11.** It is promoted from the draft `P6_M8B_PRE_RUN_DRAFT.md`, which is kept as history.

**The sampling plan is approved by Kanav Jaitly (2026-10-11):** "freeze the M8b sampling plan with seed `20271012` and one event per stratum, subject to the frozen specification and the safeguards."
- **It approves the plan only.** It does not authorize the M8b evaluation before the 2027 ruleset, the pinned 2027 EPA source and the upstream PX-1b and PX-4b prerequisites are satisfied.

## The frozen sample

| | |
|---|---|
| **Spec** | `P6_M8B_SPEC.md`, blob `63d37a95` (unchanged) |
| **Population** | 2027 events whose bracket the 2027 P6-M1 check (C0) reproduces, minus the C2 four-member exclusion and the playoff-before-selection leakage exclusion, each counted |
| **Strata** | TBA week × qualification-roster-size tercile (cuts at the sorted ⅓ and ⅔ positions), as `_m8_sample` implements |
| **Seed** | **20271012** |
| **Per stratum** | **1** |
| **Selection** | per stratum, `random.Random(seed + 100·week + tercile).sample(members, 1)`; all members if the stratum has 1 |
| **Recorded at run time** (write-once `results/p6_m8b_dm1_run.json`) | the sampled event keys, the population fingerprint, the eligible-event count, the runtime projection |

## The pass criterion (unchanged: P6-Q1; `P6_M8B_SPEC.md` §3, §6)

**P6-DM1 (M8b) is met only if both hold:**
1. the **point estimate** of the pooled share of strong alliances (winner and finalist) identified, or missed with a mentor-accepted reason category, is **> 0.5**;
2. **no miss is unreviewed.**

**The event-bootstrap 95% CI is reported only** (2,000 resamples, seed 20261010).
- It is not a pass/fail gate.
- A wide interval is never presented as proof that performance exceeds 50%.
- With 1 event per stratum (about 22 events, 44 strong alliances, on the 2026 projection), the interval is expected to be wide.

## The runtime rule (permanent 45-minute limit)

**Before anything runs,** the harness projects the actual sampled 2027 events' runtime with the recorded timing model.
- **Timing:** 27 s at 30 teams, 112 s at 45, 247 s at 60; piecewise linear, extrapolated linearly from the nearest segment.
- **Worst case:** × 1.5, the P6-M8 worst/expected ratio (37.5 / 25 minutes).

**If the projected worst case exceeds 45 minutes,** M8b stops with nothing run or recorded, and a compliant redesign is proposed. The seed, strata, count and criteria are never reduced or changed silently. The in-run 45-minute abort also remains.

## Reason categories and review (unchanged from the P6-M8 record)

Six categories, with their definitions and required evidence in the JSON, verbatim:
- `post_selection_event`
- `unmeasured_role`
- `insufficient_preselection_data`
- `procedural_selection_event`
- `outcome_variance`
- `data_error`

**Each miss is reviewed by the named mentor,** who accepts or rejects exactly one category with its evidence. A miss without an accepted category counts as a miss. Nothing is accepted by default.

## The mentor

**Mr. Biery.** His written agreement is dated 2026-10-08, verbatim "Yes I'll do that", in reply to Kanav's request that he review every required miss (`P6_M8B_MENTOR_AGREEMENT_2026-10-08.md`).
- **Limitation:** the request text was not recovered; the scope rests on Kanav's attestation.
- **No review exists yet.** His review file (`p6_m8b_mentor_review.json`) is written by him, after the run.

## Still required before the run (none is authorized by this record)

1. An approved 2027 ruleset, and the 2027 C0 record.
2. The pinned 2027 EPA source.
3. PX-1b's acceptance: FINAL-1 on 2027 plus Kanav's sha-matched confirmation.
4. The PX-2b and PX-4b passes.
