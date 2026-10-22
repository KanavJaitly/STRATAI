# P6-M10b: preparation closed out (2026-10-11)

**Status.** The production calibrator, the pins and the read-only integrity audit are complete, and Kanav accepted the audit on 2026-10-11.
- **P6-M10 stays `not_validated`.** `p6m10-v1` stays served.
- **The M10b serving guard refuses v2.** v2 is served only when every frozen prerequisite below is satisfied.
- **No 2027 acceptance run is authorized.** No serving switch is authorized.

This record changes no evidence. Every record named here is write-once and unchanged.

## 1. What is complete

| Step | Record / artifact | Identity | Commit |
|---|---|---|---|
| Spec frozen | `P6_M10B_SPEC.md` | blob `d699afafc01d42904c7afc7c7e209f8007a6a207` | `22e4d7b` |
| Amendment A1 frozen ("official events") | `P6_M10B_SPEC_AMENDMENT_A1.md` | blob `a453eaba397d8108a8cf967c27da554021921e5f` | `54a7ee5` |
| DEV-M10b (diagnostic only) | `results/p6_m10b_dev.json` | sha256 `94d6b88562da0b1fd859fb1125bd2012220d915e9c2f74f6ed81314170205c59` | `34b41b0` |
| Production calibrator | `results/p6_m10b_calibrator.json`; registry `strategy_outcome_calibrator/p6m10b-v1` | record `ab18394145d79951…`; artifact `26661227863f988c9f9251e939f59c2e4507e890b5eed8fe9a979d14bc6f6f41` | `cc6fa93` |
| Pins | `results/p6_m10b_pins.json` | sha256 `a5b1b753df5e88a4398e8885f9f2c16ba4b4dc39c9fc187d13ab2328bf42f6f5`; base `aded2c82…` + calibrator `26661227…` | `713a13c` |
| Read-only integrity audit | this record, §2 | 23 checks, all pass | (no commit: read-only) |

**The DEV result, stated as it is.** DEV improved relative to raw: G2 rejections fell from 3 to 2, and ECE from 0.0179 to 0.0151. But both the raw and the calibrated DEV predictions **failed** the overall G2 gate, and the calibrated extreme bins are overconfident. DEV is consistency evidence only, never acceptance.

## 2. The read-only integrity audit (2026-10-10; accepted 2026-10-11)

All checks were read-only. Nothing was refit, re-registered, overwritten or deleted. The audit took 11.8 s; the focused tests at `713a13c` took 89 s (258 passed).

| Area | Result |
|---|---|
| **Registry files.** The base file hashes to `aded2c82…` and the calibrator file to `26661227…`, each equal to every record that names it. Both load by their pinned sha256. The calibrator's contents equal its record. | pass |
| **Calibrator manifest (check 1c).** The first evaluation failed: the audit script wrongly required a `version_tag` field, which the registry's `ModelManifest` does not have (the tag is the directory name). Re-checked against the actual schema, it passes: the manifest validates, its model type, directory `p6m10b-v1`, `training_dataset_hash` (= the fit-set fingerprint) and feature list match, and its `created_at` equals the record's `registered_at`. | pass (corrected) |
| **Write-once records.** The calibrator record was added in `cc6fa93` and the pins in `713a13c`; neither has been touched since. The spec and A1 blobs match. Fingerprint `cf205ad6…`, 12,215 rows, groups 5,439 / 4,132 / 2,644, exclusions 30 + 33; the pins name the calibrator record's sha256 and commit. The EPA-source provenance recomputed from the frame manifest equals both records. | pass |
| **Population and DEV isolation.** The calibration set, recomputed without fitting, reproduces fingerprint, rows, groups, exclusions and latest row, and equals v1's evaluated population. The §3 conditions hold at the recorded factors, and every derivative matches the recorded one bit for bit. No DEV artifact is in the registry (22 files scanned). | pass |
| **Serving.** The guard refuses v2 with 3 reasons. The selection returns `p6m10-v1` (`aded2c82…`), `not_validated` / `p6_m10_gate_failed`. No HTTP route serves a strategy model; `load_served_strategy_model` is the one selection point. | pass |
| **Prior evidence.** The v1 fit, outcome, failure and spec, the DEV record, both P6-M13 records and both spec drafts each have exactly one commit and are unchanged. | pass |
| **No 2027 data.** All five counts are 0, read on `stratai_test` only; the serving database was not queried. | pass |

**Observation, not a defect.** The calibrator manifest's optional `provenance` field is empty (`{}`), while v1's base manifest has one. Identity rests on the pinned `model.json` sha256, and the full provenance is in the write-once calibrator record. **The registered artifact is left unchanged.**

## 3. Test-ordering history (documented, not rewritten)

| Commit | Time (−04:00) | What it did |
|---|---|---|
| `6d6af63` | 18:12:20 | Hardened `calibrate` / `pins`. Tests before this commit: 312 + 31 passed. |
| `cc6fa93` | 18:13:00 | Added the calibrator record. **Committed while 1 test failed:** the commit was not gated on the test exit code. |
| `1f5ba72` | 18:14:48 | Updated the stale test. 292 passed before the commit. |
| `713a13c` | 18:15:43 | Added the pins record. Full suite: 719 passed. |

**The failing test:** `tests/test_phase6_m10b.py::test_the_real_pins_and_final_runs_are_blocked_today`, with `AssertionError: assert not True` from `(Path(".agent/phase6/results") / runner.CALIBRATOR_RECORD).exists()`.
- **Why it was stale.** It was written before the authorized fit and asserted that no calibrator record existed. The authorized fit made that false.
- **No side effect.** It failed on its first line, before its `run_pins(None)` call. `run_pins` returns a record and writes nothing; `main` writes records.
- **What the later passing tests establish.** The real `final` still refuses. The committed calibrator record names the registered artifact (`26661227…`). The calibrate/pins refusal suite passes.

## 4. Exact frozen conditions for resuming P6-M10

Living checklist: `.agent/phase6/P6_M10B_2027_CHECKLIST.md`.

Nothing below may change thresholds, population rules or methodology in response to the DEV results. A genuine specification problem stops the work and goes to a separate dated decision.

1. **The 2027 season is complete and synced** into the isolated `stratai_test` copy.
2. **A pinned 2027 EPA source.**
   - **Who:** Kanav's config `decisions/p6_px1b_epa_source_2027_config.json`, then `python -m scripts.phase6_px1b epa-pin-2027`.
   - **Produces:** `results/p6_px1b_epa_source_2027.json`, after D18's integrity checks. This step is shared with FINAL-1.
3. **The 2027 D18 frame** (`python -m scripts.phase6_m10b frame-2027`).
   - **Needs:** Kanav's `decisions/p6_m10b_frame_2027_authorization.json` (`seasons: [2027]`, spec and A1 blobs, `season_complete_and_synced`).
   - **Produces:** the write-once `results/p6_m10b_frame_2027.json`, which must be **committed**.
4. **Ordering evidence:** `713a13c` (the pins) must be a strict ancestor of the commit that adds the frame record.
5. **Pins re-verified at run time.**
   - **Models:** base `aded2c82…`; calibrator `26661227…`; M6/M7 `d18` via `load_m6m7`.
   - **Blobs:** spec `d699afaf`; A1 `a453eaba`.
   - **Sources:** the EPA record; the frame's content hash. The frame must have been built from the currently pinned EPA source.
6. **DEV proceeded:** met (`p6_m10b_dev.json`, all three statuses `pass`).
7. **Kanav's run authorization** `decisions/p6_m10b_authorization.json`:
   - `authorized`, `authorized_by`, `date`;
   - `scope: "P6-M10b"`, `season: 2027`;
   - `season_complete_and_synced: true`;
   - `spec_blob`, `amendment_a1_blob`.
8. **One run:** `python -m scripts.phase6_m10b final`, refused if `p6_m10b_outcome_model.json` exists.
   - **A1:** every evaluated event's type is read from its raw TBA payload, fail-closed. Types other than 0–5 are excluded and counted.
   - **Gate:** pass only if G1–G4 all pass, with the frozen constants.
9. **After a pass only**, before v2 can be served:
   - Kanav's sha-matched `decisions/p6_m10b_confirmation.json`.
   - Approval of the rerun plan (blob `62b5cfd9`) through `decisions/p6_m13_m10b_rerun_authorization.json`.
   - A passing parity rerun `results/p6_m13_parity_audit_m10b.json` on the same identity.
10. **On a fail:** D9. v2 is recorded `not_validated`; a further version needs an untouched population (2028).
