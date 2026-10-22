# P6-M8b / P6-DM1 readiness (2026-10-11): sampling and prerequisites

**A read-only audit.** Nothing ran, and no review decision exists. **P6-DM1 is NOT met.**

## 1. Is the sample mandated, or a proposal?

| Source | What it fixes | Seed? | Count? |
|---|---|---|---|
| P6-Q1 (`P6_M0_DECISIONS.md`) | a seeded population stratified by week and event size, within the 45-minute budget; "the exact sample is fixed in [the] dated pre-run record" | no | no |
| P6-Q13 | every sampling decision is made before its run, in a dated decision record; seeded and stratified; a hard 45 minutes; a projected or actual overrun means redesign | no | no |
| `P6_M8B_SPEC.md` §2 | strata: TBA week × qualification-roster-size tercile; "seed and count fixed in the pre-run record before the run"; the sample must be projected to finish within 45 minutes | no | no |
| §1.3 | the pre-run record is "written by people and committed before the run" | — | — |

**So the seed 20271012 and 1 per stratum are proposals, not frozen values.** P6-Q13 and §1.3 make them a human decision. Only Kanav can fix them, and they cannot be fixed after any 2027 result.

**Does the timing matter for the seed?** No 2027 data exists. Fixing the seed now cannot be informed by results, and any value fixed before the run is equally valid.

## 2. Can one case per stratum support the intended DM1 conclusion?

**The frozen criterion** (P6-Q1; `P6_M8B_SPEC.md` §3, §6):
- the **point estimate** of the pooled share of strong alliances (winner and finalist; two per event) identified, or missed with a mentor-accepted reason category, must be **> 0.5**;
- **no miss may be unreviewed**;
- the event-bootstrap 95% CI is **reported, not gated**.

**There is no minimum sample size and no CI requirement.**

**Coverage under 1 per stratum:**
- **2026 precedent:** P6-M8's 2026 strata numbered about 22, so 1 per stratum is about 22 events, or 44 strong alliances.
- **Budget:** the 2026 runtime projection found 1 per stratum takes about 25 minutes (37.5 worst case), and 2 per stratum about 49 minutes, **over** the budget.
- **Precision:** with about 44 alliances the CI is wide (roughly ±0.15). A point estimate near 0.5 decides the outcome by a few alliances. The frozen gate accepts that; the reported CI makes it visible.
- **What it can and cannot claim:** 1 per stratum supports the frozen point-estimate test. It does **not** support a claim that the rate is above 50% with confidence. That claim is not part of the frozen criterion, and no one may make it from this sample.

**More coverage is not available under the frozen budget,** unless 2027's population is smaller or faster than 2026's. That is knowable only at run time, from the 2027 projection. If 1 per stratum projects over 45 minutes, the run must be redesigned before proceeding (P6-Q13). Nothing may be changed after a result.

**Recommendation:** fix **seed 20271012** and **per_stratum = 1** now, before any 2027 data, by Kanav's dated approval. The 2027 runtime projection stays a run-time gate (the harness aborts over budget, recording nothing).

## 3. M8b prerequisites: checklist

| # | Requirement (`P6_M8B_SPEC.md`) | Status |
|---|---|---|
| 1 | PX-1b accepted: a FINAL-1 pass on 2027 plus Kanav's sha-matched confirmation | **blocked**: needs 2027 data, an approved 2027 ruleset, the 2027 EPA source and authorizations |
| 2 | `results/p6_px4b.json` with `passed: true` (so PX-2b passed) | **blocked** behind 1 |
| 3a | Pre-run record: population, strata, sentinel, reason categories, review rule | **prepared** (draft): every field grounded in the frozen spec; the six categories unaltered (tested) |
| 3b | Pre-run record: named mentor and `mentor_agreement` | **satisfied** (2026-10-11): Mr. Biery, reply of 2026-10-08, "Yes I'll do that" (`P6_M8B_MENTOR_AGREEMENT_2026-10-08.md`). Limitation: the request text was not recovered; the scope rests on Kanav's attestation |
| 3c | Pre-run record: seed and per-stratum count fixed by people | **awaiting Kanav** (§2 above) |
| 3d | Pre-run record adopted (`P6_M8B_PRE_RUN.md` + `p6_m8b_pre_run.json`), committed, dated, before the run | **not yet**: follows 3c |
| 4 | `results/p6_m1_ruleset_check_2027.json` (C0) and an approved 2027 ruleset | **blocked**: the 2027 game manual is not available, and no 2027 ruleset exists (`stratai_test`: approved 2024–2026 only) |
| 5 | Population, case IDs and population fingerprint | **can only exist at run time**: the harness samples the 2027 population deterministically from the pre-run seed and records the sampled events |
| 6 | Mentor review file `decisions/p6_m8b_mentor_review.json`: written by the mentor, naming him; one decision per missed strong alliance | **not yet possible**: no run, so no misses. **Zero cases reviewed** |
| 7 | P6-DM1 (M8b) met: share > 0.5 and no miss unreviewed | **not evaluable**: blocked by 1, 2, 4 and 6 |

**Counting an M8b record toward P6-DM1** in `scripts/phase6_done_means.py` is a separate, reviewed change, made only after the M8b record exists (§6).
