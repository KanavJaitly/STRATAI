# P6-M8b pre-run record: DRAFT (prepared 2026-10-11)

**Not adoptable yet.** This draft is prepared from Kanav Jaitly's statement of 2026-10-11, with its parameters in `p6_m8b_pre_run_draft.json`.
- The M8b harness reads only `P6_M8B_PRE_RUN.md` and `p6_m8b_pre_run.json`. Neither exists, so M8b refuses.
- Nothing here is invented.

**Basis:** `P6_M8B_SPEC.md` §1.3, §2 and §3; P6-Q1; P6-Q13.

## What is recorded

| Field | Value | Status |
|---|---|---|
| Mentor | Mr. Biery | **Confirmed**: his written reply of 2026-10-08, "Yes I'll do that" (`P6_M8B_MENTOR_AGREEMENT_2026-10-08.md`) |
| Population | 2027 events reproduced by the 2027 P6-M1 check (C0), minus C2 and the playoff-before-selection leakage exclusion, each counted | as `P6_M8B_SPEC.md` §2 |
| Strata | TBA week × qualification-roster-size tercile | as P6-M8 |
| Seed | 20271012 | **proposed**; Kanav to confirm |
| Per stratum | 1 | **proposed**; to be confirmed against a 2027 runtime projection |
| Reason categories | the six P6-M8 categories, copied verbatim, with their required evidence | as P6-M8 |
| Review rule | each miss reviewed by the named mentor; a miss without an accepted category counts as a miss; nothing accepted by default | as P6-M8 |
| Sentinel | the sampled event with the fewest teams; a far-future result inserted at 2027-12-31 | as `P6_M8B_SPEC.md` §5 |

## Required evidence still missing

**Mentor evidence: now recorded** (2026-10-11), in `P6_M8B_MENTOR_AGREEMENT_2026-10-08.md`.
- Mr. Biery's written reply of **2026-10-08**, verbatim: **"Yes I'll do that"**, to Kanav's request that he review every required miss.
- It fills `mentor_agreement` (`confirmed`, `date`, `evidence`).
- **Limitation:** the original request text was not recovered, so the scope rests on Kanav's attestation.

**Still needed before adoption:**
1. **Kanav's confirmation of the seed and per-stratum count.** P6-Q13 sampling decisions are made by people, in the dated pre-run record, before the run. The values 20271012 and 1 are proposals.
2. **Adoption:** the draft renamed to `P6_M8B_PRE_RUN.md` / `p6_m8b_pre_run.json` and committed, dated, before the M8b run.
3. *Recommended, not required by the harness:* a copy of Kanav's original request to Mr. Biery.

**M8b also still requires:**
- a PX-4b pass (and so a PX-2b pass and PX-1b's acceptance);
- the 2027 C0 record;
- an approved 2027 ruleset.

**Not changed:**
- The frozen `P6_M8B_SPEC.md` still reads "Mr. Biery is the proposed mentor; his agreement is not confirmed today". It is a frozen specification, and its sentence stands as written on 2026-10-08.
- The frozen P6-M8 pre-run record (`36b52c7`) is unchanged.
