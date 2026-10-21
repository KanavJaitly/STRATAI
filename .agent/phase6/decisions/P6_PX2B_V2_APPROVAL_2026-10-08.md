# Approval: PX-2b specification version 2 (Kanav, 2026-10-08)

**Approved:** `.agent/phase6/P6_M3_PX2B_SPEC_V2.md`, git blob **`b4397537755acd818ed24cba6b9586ddc6e09f32`** (committed at `ae98a93`). It is the governing PX-2b specification for future work.

**Text that this approval supersedes.** That file's header still reads "PROPOSED (not adopted …)". It is not edited, because its blob is what was approved; this record is the adoption.

**Version 1** (`P6_M3_PX2B_SPEC.md`, blob `1833a2132475745708d66503ebbb018a460853cf`, `021e6ea`) is kept unchanged as historical evidence. It no longer governs PX-2b.

## Scope

**Authorized:** preparation and implementation, while no 2027 evaluation data exists. That covers the code, tests, and the one-time calibration-base fit that v2 §2.2 requires before any 2027 data exists (2024–2026 data only).

**Not authorized:**
- any real PX-2b, PX-4b or M8b evaluation;
- waiving any prerequisite;
- accepting PX-1b;
- any change to v2's slice, calibrator type, gate items, thresholds, constants or 2027 holdout;
- any tuning against 2027 outcomes.

## Kanav's implementation requirements (2026-10-08)

1. **The exact frozen slice:** the 526-row calibration slice and its provenance (`diagnostics/px2b_c1_slice_provenance.json`) are preserved exactly.
2. **The base model's rows:** the base model is fit only on eligible rows strictly earlier than the slice, excluding every event that has a slice row.
3. **Per-prediction proof:** every prediction the calibrator is fit on must be shown out-of-sample for its match and its event, not by timestamp alone.
4. **The calibrator's inputs:** the calibrator is fit only on those out-of-sample predictions and their observed outcomes.
5. **The candidate:** the calibrator is applied to `px1b-v1`, which stays the candidate. The base model is never substituted for it.
6. **Unchanged:** calibrator type, gate items, thresholds, constants, 2027 holdout and prerequisites.
7. **Tests:** disjoint populations, event-straddling exclusion, reproducible provenance, and refusal of blocked evaluations.
8. **Unchanged records:** v1, the PX-1 and PX-1b records and every historical result. The v2 hash and the implementation commit are recorded.

## Not decided by this record

**Kanav's confirmation of D9 decision v1 remains separate and outstanding.** This approval applies only to PX-2b v2.
