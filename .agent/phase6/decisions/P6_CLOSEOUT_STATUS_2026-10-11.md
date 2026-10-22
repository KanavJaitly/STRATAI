# Phase 6 closeout status (2026-10-11)

**Verdict: Phase 6 is NOT complete.**
- **P6-DM2 is met.**
- **P6-DM1 is not met.** Its route (PX-1b → PX-2b → PX-4b → M8b) needs 2027 data, an approved 2027 ruleset, Kanav's authorizations, the M8b sampling decision, and Mr. Biery's review.

Every task that could legitimately be completed without those has been done. Each item states whether it is **preparation** (software, records, pins) or **validated acceptance** (a frozen gate passed on its frozen population). **Passing software tests is not acceptance.**

## 1. Milestones

| Milestone | Frozen done-means / gate | Status | Preparation vs acceptance |
|---|---|---|---|
| P6-M0 spec | frozen | **frozen** (`9964001`) | — |
| P6-M1 rulesets | approved rulesets reproduce real events | **accepted 2024–2026** (ids 4–6; 582 events, 0 failures). **2027: none**; the 2027 manual is not available | 2027 is prep only (C0 harness) |
| P6-M2 PX-1 | P6-Q3: beats M6/M7 and seed-only (CIs exclude 0) | **FAILED** twice (D9); `not_validated` (Kanav, 2026-10-08) | — |
| PX-1b (replacement) | FINAL-1 on 2027 plus Kanav's sha-matched confirmation | **unaccepted candidate**. D9 v1 **confirmed** (Kanav, 2026-10-11). FINAL-1 implemented, fail-closed, not run | preparation complete; acceptance needs 2027 |
| P6-M3 PX-2 / P6-M5 PX-4 / P6-M8 (2026) | — | **blocked by D9** permanently | — |
| PX-2b / PX-4b | M7/D16 gate; P6-Q5 | implemented; the calibration base and pins are frozen; the **2027 EPA source is wired** (fail-closed). Not run | prep only |
| P6-M8b / **P6-DM1** | P6-Q1: share > 0.5, no miss unreviewed | **not evaluable**. Pre-run record: draft. **Mentor evidence recorded.** Seed and count await Kanav. **0 runs, 0 misses, 0 reviews** | prep only |
| P6-M4, M6 (a), M7, M9, M11 | correctness, or measured | **accepted** (implementation correctness; M6 (a) on real data) | accepted as specified |
| P6-M6 (b) | measured, non-gating | **measured** (rerun1). Its record does **not** include the ranking model's hash (inferred `1f0fe5aa`); the pin is deferred | measurement recorded |
| P6-M10 v1 | P6-Q9 gate | **FAILED** (G2), served `not_validated` | — |
| M10b | the frozen gate on 2027 (§5–§6) | **prepared**: spec and A1 frozen; DEV (diagnostic) proceeded, but both gates failed G2; production calibrator `26661227…` and pins (`713a13c`) recorded before 2027; integrity audit passed; frame producer ready. **The sole 2027 candidate. Unvalidated** | preparation only. **No acceptance evidence** |
| M10c | DEV-c rule (§4.6) | **STOPPED**: DEV-c rule not met (`p6_m10c_dev.json`; D3 fail). Not registered, pinned or served | — |
| P6-M12 | replay | **accepted** (rerun1) | accepted |
| P6-M13 / **P6-DM2** | parity audit | **met** (rerun1) for v1. The M10b v2 rerun runner and plan (`62b5cfd9`) are ready, not run (needs a passed 2027 M10b) | v1 accepted; the v2 rerun is prep |
| P6-M14 sign-off | docs, contracts, done-means | **docs and contracts current**; `phase6_done_means`: DM1 NOT MET, DM2 MET. **Sign-off not possible while DM1 is unmet** | — |

## 2. Audits this cycle (read-only)

**PX-1b EPA wiring (`91ee9ca`): pass.**
- `_epa_source(PX1B_TRACK)` takes the source only from `p6_px1b_epa_source_2027.json`.
  - It must be **present** and **committed** (`adding_commit`).
  - It must be the **2027 pin record** (`milestone`, `seasons` ⊇ {2027}).
  - It must pass FINAL-1's own `verified_epa_source`: the manifest and chain **sha256** match, and the manifest covers 2027.
- **All three consumers use it,** and FINAL-1 passes its verified paths explicitly:
  - PX-2b, via `_track_rows`;
  - PX-4b, via `run_m5`;
  - M8b, via `run_m8`.
- **No fallback is reachable.** The shared assemblers' `snapshot or SNAPSHOT` defaults are reached only by frozen PX-1 callers that pass nothing. On the PX-1b path the paths are always verified, non-null `Path`s. A test pins this.
- **Today the record does not exist,** so the track refuses.

**Mentor evidence.** Recorded in `P6_M8B_MENTOR_AGREEMENT_2026-10-08.md`:
- Mr. Biery's written reply of 2026-10-08, verbatim: "Yes I'll do that".
- It fills §1.3's fields.
- **Limitation:** the original request is not in the repository, so the scope rests on Kanav's attestation.

**M8b sampling.** The seed and count are **not** frozen values; they are a human decision (`P6_M8B_READINESS_2026-10-11.md`).

**Human-input status.**

| Input | Status |
|---|---|
| D9 v1 | **confirmed** (2026-10-11) |
| 2027 ruleset | **none**: `stratai_test` has 2024–2026 approved only; the 2027 manual is unavailable |
| 2027 data | **none** (0 matches, events, payloads or stats) |
| M8b mentor | **confirmed with evidence** |
| M8b seed and count | **awaiting Kanav** |

## 3. Expensive runs (every one within the 45-minute limit)

| Run | Minutes |
|---|---|
| M13 rerun1 | 5.8 |
| M13 run 1 | 5.3 |
| M12 run 1 / rerun1 | 5.2 / 4.9 |
| PX-1 / rerun1 | 0.8 / 0.7 |
| M6 (b) / rerun1 | 0.6 / 0.6 |
| PX-1b final fit; chain pins; PX-2b calbase | 0.6 each |
| v1 evaluation | 0.6 |
| PX-1b DEV | 0.5 |
| DEV-c | 0.3 |
| M6 (a); HV-1; M10b DEV; M10b calibrator | 0.2 each |
| M10b pins; M1 check; pins v2; registration evidence | under 0.1 |
| v1 fit | 10 s |

Nothing exceeded its budget (`over_budget` false on every record).

## 3a. Tests this cycle

| Tests | Result | Time |
|---|---|---|
| Full Phase 6 suite plus API, docs, frontend and Phase 5 contracts (on `stratai_test` only) | **814 passed** | 10 min 51 s |
| New focused tests: `test_phase6_m8b_prerun.py` (6) and the EPA path audit tests (2) | included above | — |

**Software tests establish implementation correctness only, never acceptance.**

## 4. What is needed next (in order; `P6_2027_AUTHORIZATION_REQUESTS.md`)

**Now:**
- Kanav's decision on the M8b seed and per_stratum (proposed 20271012 / 1), then adoption of the pre-run record (R8).
- Optionally, a copy of the original request to Mr. Biery.

**After the 2027 manual is released:**
- R1: the 2027 ruleset, approved by a named reviewer.

**After the 2027 season:**
- R2 and R3 (EPA pin, C0), R4 → R5 (FINAL-1), R6 (confirmation), R7 (PX-2b, PX-4b), R9 → R10 (M8b and Mr. Biery's review): **P6-DM1**.
- In parallel, for P6-M10: M1 → M2 (frame, run), then M3 and M4 (confirmation, parity rerun), before any serving change.

## Addendum (2026-10-11, later the same day): the M8b pre-run record is adopted

Kanav Jaitly approved the sampling plan: seed 20271012, one event per stratum.

**Adopted** as `P6_M8B_PRE_RUN.md` + `p6_m8b_pre_run.json`, committed before any M8b run and any 2027 data:
- **Pass criterion:** the point estimate > 0.5, with no miss unreviewed. The CI is reported only.
- **Runtime gate:** the M8b harness now projects the actual 2027 sample's runtime before anything runs. If the worst case exceeds 45 minutes it stops for a compliant redesign, never a silent change. The frozen P6-M8 path is unchanged.
- **Run record:** the sampled event keys, the population fingerprint, the eligible count and the projection are added to M8b's write-once run record.

**What the adoption does not do:**
- It authorizes **no** run.
- **P6-DM1 is still not met:** 0 runs, 0 misses, 0 reviews. It needs the 2027 ruleset and C0, the pinned 2027 EPA source, PX-1b's acceptance, and the PX-2b and PX-4b passes.
