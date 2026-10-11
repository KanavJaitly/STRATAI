# Phase 6: the human inputs and authorizations still to come (prepared 2026-10-11)

**A request sheet, not an authorization.** None of the files below exists, and nothing here creates one.
- Each is written or approved by the person named, **only** when its preconditions hold.
- Each is verified by the code named. A file that fails its check is refused.
- **No placeholder here may be copied into a real file** before the decision it records is made.

## The order (each step needs the ones before it)

| Step | Who | File or action | Exact fields (as the code checks them) | Preconditions | Checked by |
|---|---|---|---|---|---|
| R1 | a named, qualified reviewer | the **2027 ruleset**, entered from the official 2027 game manual and approved in `season_rulesets` (`scripts/phase6_rulesets.py`) | the P6-M1 ruleset schema; approval names the reviewer | the 2027 manual is released | `require_rulesets(database, (2027,))` |
| R2 | Kanav | `decisions/p6_px1b_epa_source_2027_config.json` | `snapshot`, `chain` (paths to a 2027 Statbotics snapshot and STRATAI chain) | the 2027 season is complete and synced; a snapshot covering 2027 exists | `epa-pin-2027` then writes `results/p6_px1b_epa_source_2027.json` after D18's integrity checks. **Commit it.** It feeds FINAL-1, M10b's frame, PX-2b, PX-4b and M8b |
| R3 | (command) | `python -m scripts.phase6_playoff_track m1-2027` → `results/p6_m1_ruleset_check_2027.json`; **commit it** | — | R1 and 2027 playoffs synced | FINAL-1: not escalated; ordering after the evidence commit `a52641e` |
| R4 | Kanav | `decisions/p6_px1b_final1_authorization.json` | `authorized: true`, `authorized_by`, `date`, `scope: "FINAL-1"`, `season: 2027`, `season_complete_and_synced: true` | R1–R3 | `check_authorization` (FINAL-1) |
| R5 | (command) | `python -m scripts.phase6_px1b gate2027` → `results/p6_px1b_gate_2027.json` (once) | — | R4 | FINAL-1's prerequisites |
| R6 | Kanav, **after a pass only** | `decisions/p6_px1b_final1_confirmation.json` | `confirmed: true`, `confirmed_by`, `date`, `record: "p6_px1b_gate_2027.json"`, `record_sha256` (that file's sha256) | R5 passed | `_require_model(PX1B_TRACK)` |
| R7 | (commands) | `python -m scripts.phase6_playoff_track px2b`, then `… px4b` (PX-1b track) | — | R6, and each predecessor passed | each harness's frozen gate |
| R8 | Kanav | M8b pre-run **adoption**: fix the seed and per_stratum (proposed 20271012 / 1), then commit `decisions/P6_M8B_PRE_RUN.md` + `p6_m8b_pre_run.json` from the draft | `seed`, `per_stratum`, `reason_categories`, `mentor`, `mentor_agreement` (`confirmed`, `date`, `evidence`: already recorded) | **can be done now**, before any 2027 data | `_m8_config` |
| R9 | (command) | `python -m scripts.phase6_playoff_track m8b` | — | R7 (PX-4b passed), R8 | the frozen sentinel; the 45-minute budget |
| R10 | **Mr. Biery** | `decisions/p6_m8b_mentor_review.json` | `mentor: "Mr. Biery"`; `decisions`: one per missed strong alliance, each with `event_key`, `strong`, `accepted` and `category` (one of the six codes) | R9 | then `… m8b-review` (`run_m8_review`): DM1 met iff share > 0.5 and no miss unreviewed |
| M1 | Kanav | `decisions/p6_m10b_frame_2027_authorization.json` | `authorized`, `authorized_by`, `date`, `scope: "P6-M10b-frame-2027"`, `season_complete_and_synced: true`, `seasons: [2027]`, `spec_blob: "d699afafc01d42904c7afc7c7e209f8007a6a207"`, `amendment_a1_blob: "a453eaba397d8108a8cf967c27da554021921e5f"` | R2 committed; 2027 synced | `check_frame_authorization`. Then `frame-2027` writes `results/p6_m10b_frame_2027.json`; **commit it** (`713a13c` must be its strict ancestor) |
| M2 | Kanav | `decisions/p6_m10b_authorization.json` | `authorized`, `authorized_by`, `date`, `scope: "P6-M10b"`, `season: 2027`, `season_complete_and_synced: true`, `spec_blob`, `amendment_a1_blob` (as above) | M1 committed | `check_authorization` (M10b `final`). The run writes `p6_m10b_outcome_model.json` (once) |
| M3 | Kanav, **after a pass only** | `decisions/p6_m10b_confirmation.json` | `confirmed: true`, `confirmed_by`, `date`, `record: "p6_m10b_outcome_model.json"`, `record_sha256` | M2's run passed | `m10b_serving_decision` |
| M4 | Kanav | `decisions/p6_m13_m10b_rerun_authorization.json` | `authorized`, `authorized_by`, `date`, `scope: "P6-M13-M10b"`, `spec_blob` (M10b's), `plan_blob: "62b5cfd9b0f20efc379b4d4b9c8003a1dc9c7ce2"` | M2's run passed | `rerun_prerequisites`. The rerun writes `p6_m13_parity_audit_m10b.json`. Serving switches only when M3 and M4's rerun both hold |

**Never acceptable substitutes:**
- 2026 data, DEV or diagnostic results, synthetic fixtures;
- an unpinned artifact;
- a hand-written result record.

**M10c is stopped** (DEV-c rule not met), so no M10c authorization is pending.
