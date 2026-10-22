# FINAL-1 (PX-1b's 2027 acceptance evaluation): implementation audit (2026-10-09)

**Scope.** Implementation and software verification only, as authorized by Kanav on 2026-10-09.
- **Not run:** no acceptance evaluation; no acceptance record; no model registered or accepted.
- **Unchanged:** PX-1 `not_validated`; PX-1b unaccepted; 2027 acceptance pending.

**Code:** `scripts/phase6_px1b_final1.py` (commit `5f05297`). Reached only through `python -m scripts.phase6_px1b gate2027`, which also requires the approved 2027 ruleset before anything runs.

## Conformance with the frozen requirements (PX-1b spec §6, blob `80201eb0…`; D9 v1 Part B)

| Frozen requirement | Implementation | Verified by |
|---|---|---|
| Candidate = the registered `px1b-v1`, unchanged | `pinned_px1b_models()`: `_model_path` sha check against pin record v2 | an altered candidate or seed-only file is refused |
| Seed-only comparator = `playoff_px1b_seed_only` `px1b-v1` | the same pinned loader | same |
| M6/M7 = `win_prob_xgb_calibrated` `d18`, on the same selection-moment features | `load_m6m7()` (pinned `expected_sha256`), scored by `_m6m7_on` on each row's selection-moment features | a hash mismatch is refused; M6/M7 is called on exactly the rows PX-1b and seed-only score |
| Rows: held-out 2027, PX-1b §1, every exclusion counted | `assemble_2027`: `assemble_rows` (P6-M1 status, A1 `playoff_before_selection_moment`, four-member, EPA-incomplete) + `drop_scale_absent`. Insufficient rows are excluded from every model and counted. A non-2027 row is refused | test |
| Candidate frozen before any 2027 outcome | `px1b-v1`'s final-fit seasons ⊆ 2024–2026. Its registry training hash = the final-fit fingerprint = the pinned population. It must be registered before the first 2027 selection moment | tests |
| The gate: strictly better than **both**, each paired event-bootstrap 95% CI entirely below 0, 2,000 resamples, seed 20261010 | `ml.playoffs.px1b.gate_2027` → `paired_log_loss_gate` → `event_bootstrap_mean_ci` (`DEFAULT_RESAMPLES` 2000, level 0.95) | tests of pass and fail cases (each comparison alone failing fails the gate); the resamples, seed, events and units are recorded |
| Run once, after the 2027 season is complete and synced, on Kanav's instruction | refused if `p6_px1b_gate_2027.json` exists; `write_once` never overwrites; Kanav's authorization file is required | tests |
| Prerequisites (D9 v1 Part B 3(a)–(d)) | 2027 playoff data; the approved 2027 ruleset; the C0 record (not escalated, made with that ruleset); the pinned 2027 EPA source (manifest and chain sha256; covers 2027) | each absent or inconsistent case is refused in a test |
| Kanav's confirmation of D9 decision v1 (his 2026-10-09 instruction) | `p6_d9_v1_confirmation.json`, matched to the record's current blob | absent, unconfirmed and wrong-blob cases are refused |
| A pass ≠ acceptance (Part B condition 4) | the record states it. Acceptance additionally requires `p6_px1b_final1_confirmation.json` (checked by the PX-2b chain's `_require_model`) | — |
| A fail → D9 | `passed: false` is recorded; PX-2b and everything after it keep refusing | existing chain tests |

**Refusal behaviour on today's real state** (read-only; nothing written; 18 result files before and after):
- **`gate2027`:** refused at the missing 2027 ruleset.
- **The prerequisite check called directly:**
  - **verified:** pins v2, the pinned models, the M6/M7 hash, the final-fit record and DEV-1;
  - **named as missing:** the D9 v1 confirmation, the FINAL-1 authorization, the 2027 ruleset, the C0 2027 record, 2027 playoff data and the pinned 2027 EPA source.
- **`epa-pin-2027`:** refused for want of its config.

## Files a person must write (formats checked by the code; none exist today)

| File (`.agent/phase6/decisions/`) | Required fields |
|---|---|
| `p6_d9_v1_confirmation.json` | `confirmed: true`, `confirmed_by`, `date`, `record: ".agent/phase6/decisions/P6_D9_PX1B_REPLACEMENT_V1.md"`, `record_blob` (that file's current git blob) |
| `p6_px1b_final1_authorization.json` | `authorized: true`, `authorized_by`, `date`, `scope: "FINAL-1"`, `season: 2027`, `season_complete_and_synced: true` |
| `p6_px1b_epa_source_2027_config.json` | `snapshot` (a D18 snapshot directory whose manifest covers 2027), `chain` (the EPA chain file) |
| `p6_px1b_final1_confirmation.json` (after a pass) | `confirmed: true`, `confirmed_by`, `date`, `record: "p6_px1b_gate_2027.json"`, `record_sha256` |

## Observations (not defects)

- **`registered_at` comes from the registry manifest.** It is not itself pinned; the model file is. It is corroborated by the final-fit record's commit (`d45432e`, 2026-10-08) and the pin records, all of which predate any 2027 data.
- **PX-2b, PX-4b and M8b still read the 2027 EPA source through `PX1B_TRACK`, which is deliberately unset.** They keep refusing. Wiring them to the pinned 2027 source would be a separate, approved change.

## Tests

| Test run | Result |
|---|---|
| `tests/test_phase6_final1.py` | 37 passed |
| Full PX harness batch (12 files) | **207 passed, 0 failed, 0 skipped** (45 s) |
