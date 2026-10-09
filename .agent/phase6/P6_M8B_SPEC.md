# P6-M8b (versioned P6-DM1 run on PX-1b): frozen specification, version 1 (2026-10-08)

**Frozen by the commit that introduces this file, before any M8b input or outcome exists.** A change is a new version, written before the run it governs.

**Authority:**
- D9 decision v1, proposal C3;
- approved by Kanav on 2026-10-08 (`decisions/P6_D9_PX1B_APPROVALS_C0_C4_2026-10-08.md`).

**What it replaces, and what it leaves alone:**
- It versions the P6-M8 run for PX-1b, on 2027 events.
- The frozen P6-M8 (2026 events, `P6_M8_PRE_RUN.md`, `p6_m8_pre_run.json`) is unchanged and stays blocked.
- **The P6-Q1 definition of P6-DM1 is preserved unchanged (§3).**

## 1. Prerequisites (all required; the harness refuses otherwise)

1. PX-1b is accepted (`P6_M3_PX2B_SPEC.md` §1.1).
2. `results/p6_px4b.json` exists with `passed: true`; PX-2b has therefore passed too.
3. **The M8b pre-run record**, dated, written by people and committed **before** the run:
   - `decisions/P6_M8B_PRE_RUN.md` and `decisions/p6_m8b_pre_run.json`;
   - fields: `seed`, `per_stratum`, `reason_categories`, `mentor`, and `mentor_agreement`;
   - `mentor_agreement` is `{"confirmed": true, "date": …, "evidence": …}`: the named mentor's written agreement to review every miss.
   - No part of it may be presumed or fabricated. Mr. Biery is the proposed mentor; his agreement is **not** confirmed today.
4. `results/p6_m1_ruleset_check_2027.json` (C0) exists, and an approved 2027 ruleset exists.

## 2. Population and sample (P6-Q1, P6-Q13; the year changed to 2027)

**Population:** 2027 events whose bracket P6-M1 (C0) reproduces.

**Exclusions, each counted:**
- **C2:** four-member alliances (FIRST Championship divisions), or an unexplained listing;
- **Leakage:** `playoff_before_selection_moment`.

**Sample:**
- **Strata:** TBA week × qualification-roster-size tercile, computed on the eligible population.
- **Selection:** seeded; `per_stratum` events per stratum; seed and count fixed in the pre-run record before the run.
- **Runtime:** the sample must be projected to finish within the 45-minute budget. The run aborts with nothing recorded if it exceeds the budget.

## 3. P6-DM1 definition (P6-Q1, unchanged)

- **Strong playoff alliances:** the event winner and the finalist (from the C0 2027 record).
- **"Identifies":** a predicted alliance that:
  1. contains the actual captain;
  2. contains at least one actual pick (selection-time members; a backup is never an actual pick);
  3. is among the engine's **top 2 predicted contenders** by P(win event).
- **"Most":** > 50% pooled over strong alliances, with an event-bootstrap 95% CI (2,000 resamples, seed 20261010).
- **Defensible reasons:**
  - predefined reason categories, fixed in the pre-run record before any result;
  - each miss is reviewed by the named mentor;
  - a miss without an accepted category counts as a miss;
  - nothing is accepted by default.
- **Baselines:** a raw-EPA draft and actual-seed ordering, reported.

## 4. Engine (the frozen P6-M8 engine, with only the playoff model replaced)

- **Unchanged:**
  - selection engine, draft model and P(win event) contenders, as in P6-M8;
  - ordering by the validated P5-M4 policy (`ranking_xgb_v2` `d18` or raw EPA, as `policy_model` selects);
  - the event's approved 2027 rules.
- **Match probabilities:** PX-2b-calibrated PX-1b.
- **Inputs:** all at each event's selection moment.

## 5. Leakage sentinel (the frozen P6-M8 "Leakage" row)

- **Event:** the sampled event with the fewest qualification teams (ties: event key).
- **Insertion:** a far-future playoff result, with scouting rows, inserted into the isolated copy at **2027-12-31T00:00:00+00:00** (after every 2027 selection moment), then always deleted.
- **Pass:** every engine output (ordering, both drafts, all contender probabilities) must be unchanged.

## 6. Records, decision and limits

- **Step 1:** `results/p6_m8b_dm1_run.json`, write-once.
- **Step 2:** after the mentor's review, `decisions/p6_m8b_mentor_review.json`, written by the mentor and naming him. Then `results/p6_m8b_dm1.json`, write-once.
  - P6-DM1 (M8b) is met iff the pooled share is > 0.5 **and** no miss is unreviewed.
- **Done-means:** `scripts/phase6_done_means.py` reads the frozen P6-M8 record only. Counting an M8b record toward P6-DM1 is a separate, reviewed change, made only once the M8b record exists and every prerequisite above has been met.
- **Not changed after a result.**
