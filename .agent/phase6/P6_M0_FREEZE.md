# P6-M0 — Phase 6 specification freeze

**FROZEN / APPROVED by Kanav, 2026-10-04.** The commit introducing this file is the P6-M0 freeze point.

From here on, methodology and acceptance criteria change only by a new, dated decision in `P6_M0_DECISIONS.md` made **before the affected result exists**. A change made after seeing a result is never permitted. **D9 is binding:** a genuine failure stops and escalates.

**P6-M0 contains zero Phase 6 implementation.** No P6-M1 … P6-M14 code, model, engine, endpoint, frontend work or migration exists.

## Frozen documents (git blob hashes at the freeze)

| File | Blob |
|---|---|
| `docs/P6Milestones.md` (revision 2) | `4b34b5346261a60bc3a7488b658089d1a7529e0b` |
| `.agent/phase6/P6_M0_DECISIONS.md` (P6-A1 … A12 approved; P6-Q0 … Q13 decided) | `47fce8b3f64ec168c5582d2e5240125b7ac36630` |

**Sources at the freeze (unchanged by it):**

| File | Blob |
|---|---|
| `docs/ROADMAP.md` (source of P6-DM1 / P6-DM2) | `d7517b09f62056ec3155047c0efac31fb1640896` |
| `docs/PROJECT_VISION.md` | `398864b6146b9e4a82751150fba067f9d8ea42ae` |
| `prompts/MASTER_BUILD.md` | `0fc8716314f03b3e93ce17e531d83361aa1a309c` |
| `docs/P5Milestones.md` (frozen P5-M0 rev. 3; the source of the PX track via P5-D4) | `2d7bc67480005cef908bbc3e611342471b3bec49` |
| `.agent/phase5/P5_M0_DECISIONS.md` (as frozen at P5-M0) | `7d26fc230851c2a9cbd8a9792ff955bc541e889e` |

Check: `git hash-object <file>` must equal the blob above. `ROADMAP.md` and `P5Milestones.md` also equal their P5-M0 freeze hashes.

## What the freeze fixes

- **Done-means (immutable):**
  - **P6-DM1:** alliance selection on a pre-registered population of held-out 2026 events (stratified by week and event size). It must identify **> 50% (pooled)** of the strong alliances (**winner and finalist**). "Identifies" = the predicted alliance contains the captain and at least one actual pick, and is among the engine's **top 2** contenders. An event-bootstrap CI is reported, misses are reviewed by a named mentor against predefined reason categories, and the baselines are a raw-EPA draft and actual-seed ordering.
  - **P6-DM2:** verifiably zero mechanism for AI strategies to receive inflated odds: one model, one input set, both paths.
- **Playoff track:**
  - **PX-1:** regularized logistic regression (seed difference, composition sums, bracket round; no in-playoff results). It must beat M6/M7-on-playoffs **and** seed-only on held-out 2026 log-loss, with paired CIs excluding 0.
  - **PX-2:** the M7/D16 gate unchanged; calibration slice = the last 20% of 2025 playoffs.
  - **PX-3:** an exact simulator.
  - **PX-4:** P(win event) and P(reach finals) must each beat seed-only on log-loss, with CIs excluding 0.
- **Alliance selection:**
  - the objective is P(win event), with the six factors entering only through PX-1 features and no hand-set weights;
  - the draft model is deterministic best-available by the P5-M4 ordering (its accuracy is reported, not gating);
  - 3–5 alternatives.
- **Strategy:**
  - one component model (P6-M10) for both paths. Its baseline must pass the M7 gate on 2026 EPA-complete qualification matches; it is not required to beat M6/M7;
  - historical strategy effects are `not_validated`;
  - display "<5%" / ">95%";
  - "indistinguishable at model resolution" below one display step;
  - no opponent best-response.
- **Data:**
  - defense = quality only, when validated; feeding `insufficient_data`;
  - Phase 6 validation proceeds with 0 scouting rows, and nothing is fabricated or inferred;
  - the sampling protocol: per-run dated pre-run decisions, seeded and stratified, a hard 45-minute limit, and escalation above 10% M1 exclusions.
- **Unchanged:**
  - M6/M7 and every D18 model;
  - all Phase 4 and Phase 5 criteria, records and decisions (P5-D3, P5-D4, P5-D11, P5-D13);
  - the migration 0010 incident record;
  - the test-database guard;
  - PR #29.

## Prerequisite before implementation (P6-Q0)

Phase 6 implementation must not begin until the approved code baseline exists:
1. `phase5/build` @ `6e76520` is merged into `main` with Kanav's **explicit approval of that merge and push**;
2. Phase 6 is then branched from the resulting `main`.

**At the freeze, that merge has not been performed.**
