# P6-M10b 2027 acceptance: readiness checklist

**A living document, not a frozen spec and not a decision record.** It tracks the frozen prerequisites of `P6_M10B_SPEC.md` (blob `d699afaf`) §5–§7 and amendment A1 (blob `a453eaba`). Each box is ticked only when the named artifact exists and the named check passes.

**Last updated 2026-10-11.** Items 1–4 are done. Every later item is open. `final` refuses today.

| # | Prerequisite | Artifact (who produces it) | How the code verifies it (`scripts/phase6_m10b.py`) | Status |
|---|---|---|---|---|
| 1 | Frozen spec and A1 | `P6_M10B_SPEC.md`, `P6_M10B_SPEC_AMENDMENT_A1.md` | `_spec`, `_amendment`: exact blobs | ☑ (`22e4d7b`, `54a7ee5`) |
| 2 | DEV-M10b proceeded | `results/p6_m10b_dev.json` | `dev_proceeded`: this spec, all three statuses `pass` | ☑ (`34b41b0`; both DEV gates still failed G2) |
| 3 | Production calibrator | `results/p6_m10b_calibrator.json`; registry `p6m10b-v1` | population = v1's 12,215 rows; registry sha | ☑ (`cc6fa93`, `26661227…`) |
| 4 | Pins before any 2027 data | `results/p6_m10b_pins.json` | registry files, v1 sha, EPA source, calibrator record sha and commit | ☑ (`713a13c`; integrity audit pass, 2026-10-10) |
| 5 | **2027 season complete and synced** | the 2027 season in the isolated copy (TBA) | `data_2027` > 0 (frame step); completeness is attested in items 7 and 9 | ☐ open (2027 season) |
| 6 | **Pinned 2027 EPA source** | Kanav's `decisions/p6_px1b_epa_source_2027_config.json`, then `python -m scripts.phase6_px1b epa-pin-2027`, which writes `results/p6_px1b_epa_source_2027.json`. Shared with FINAL-1 | `verified_epa_source`: manifest and chain sha256; covers 2027 | ☐ open (needs a 2027 snapshot) |
| 7 | **Frame authorization** | `decisions/p6_m10b_frame_2027_authorization.json` (**Kanav**) | `check_frame_authorization` (fields below) | ☐ open |
| 8 | **2027 D18 frame, committed** | `python -m scripts.phase6_m10b frame-2027`, which writes `results/p6_m10b_frame_2027.json`; then **commit** it | content hash; seasons `[2027]`; built from item 6's record; `713a13c` must be a strict ancestor of the commit that adds it | ☐ open |
| 9 | **Run authorization** | `decisions/p6_m10b_authorization.json` (**Kanav**) | `check_authorization` (fields below) | ☐ open |
| 10 | Run once | `python -m scripts.phase6_m10b final`, which writes `results/p6_m10b_outcome_model.json` | all of the above; A1 event types fail-closed; the unchanged gate | ☐ not run |
| 11 | **Confirmation (after a pass)** | `decisions/p6_m10b_confirmation.json` (**Kanav**): `confirmed`, `confirmed_by`, `date`, `record`, `record_sha256` | `m10b_serving_decision` | ☐ open |
| 12 | **Parity rerun (after a pass)** | approval of the rerun plan via `decisions/p6_m13_m10b_rerun_authorization.json` (**Kanav**; scope `P6-M13-M10b`, spec and plan blobs; plan `62b5cfd9`), then `python -m scripts.phase6_m13_parity_audit_m10b` | `rerun_prerequisites`; P6-DM2 on v2; identity equal to the outcome record | ☐ open |

**Authorization fields** (each also requires `authorized: true`, `authorized_by` and `date`):

| File | `scope` | Other fields |
|---|---|---|
| Frame (item 7) | `P6-M10b-frame-2027` | `season_complete_and_synced: true`, `seasons: [2027]`, `spec_blob`, `amendment_a1_blob` |
| Run (item 9) | `P6-M10b` | `season: 2027`, `season_complete_and_synced: true`, `spec_blob`, `amendment_a1_blob` |

**Why the frame holds 2027 only:**
- §5 evaluates 2027 rows alone.
- A 2027-only frame never re-derives the frozen 2024–2026 rows under a different snapshot.

The frame authorization must state `seasons: [2027]`. A different choice is a code change before item 8.

**Never acceptable substitutes:**
- 2026 data, DEV results, synthetic fixtures;
- an unpinned artifact;
- a hand-written outcome or parity record.

**No threshold, population rule or methodology changes** in response to DEV. A genuine specification problem stops the work and goes to a separate dated decision.
