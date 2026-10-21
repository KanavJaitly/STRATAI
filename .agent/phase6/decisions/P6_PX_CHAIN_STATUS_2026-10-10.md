# PX chain: completion state and dependency audit (2026-10-10)

**Read-only audit.** Every verification that is legitimately unblocked under the frozen specifications has been done. What remains needs human input or 2027 data. **Phase 6 is not complete** (`phase6_done_means`: P6-DM1 NOT MET, P6-DM2 MET).

**Evidence for this record:**

| Check | Result |
|---|---|
| Consolidated integrity check, read-only | 25/25 PASS, 3 s |
| Write-once | a second `registration-evidence` run was refused (`RecordError`); the record's sha256 is unchanged |
| Full Phase 6 regression sweep, `tests/test_phase6*.py` (20 files) | **332 passed, 0 failed, 0 skipped**, 236 s |
| Commits `277f938` and `ba84694` | both in HEAD's history; the evidence record has a single commit |

## Four kinds of evidence, kept distinct

- **Software correctness:** tests, mostly synthetic, plus real-artifact checks where present.
- **Provenance integrity:** pins, fingerprints, write-once records and git evidence.
  - Local git commit times are self-asserted. They are **not** independent proof of wall-clock time, and git history is tamper-evident, **not** tamper-proof (`P6_PX1B_REGISTRATION_EVIDENCE_AUDIT_2026-10-10.md`).
- **Historical diagnostic evidence:** HV-1 only. Not acceptance.
- **Predictive acceptance:** none has been demonstrated for any PX model.

## By component

| Component | Implementation | Pinned artifacts and provenance | Integrity tests | Actual evaluation run? | Blocked by (frozen) | Valid checks still possible with existing data |
|---|---|---|---|---|---|---|
| **PX-1** | complete (spec `24b427f2`) | `px1-v1`/`px1-v2` registered (not pinned: frozen chain) | PX-1 tests in the sweep | **yes:** run 1 and rerun1 both FAILED P6-Q3 → `not_validated` (Kanav, 2026-10-08) | D9 stops its PX-2/PX-4/M8 chain permanently | none; a redesign is a separate pre-registered effort, and that is PX-1b |
| **PX-1b** | complete (spec `80201eb0`): DEV-1, final fit | `px1b-v1` + seed-only pinned (pins v2); training population `52a4d7f0`; registration evidence (commit `a52641e`) | pins, G3, FINAL-1 and registration tests | **DEV-1 (development) and HV-1 (diagnostic) only.** No acceptance evaluation | FINAL-1's prerequisites (below) | none: 2024–2026 are exhausted for it (DEV-1, HV-1); 2026 is not an untouched holdout |
| **FINAL-1** (PX-1b 2027 acceptance) | complete (`5f05297`, `277f938`), fail-closed | candidate, seed-only and M6/M7 `d18` sha-checked; registration evidence verified from git; EPA-source pin format ready | 51 FINAL-1 tests | **no** | Kanav's D9 v1 confirmation; Kanav's FINAL-1 authorization; the approved 2027 ruleset; the committed C0 2027 record; 2027 playoff data; the pinned 2027 EPA source | none until 2027 data exists |
| **PX-2b** (v2, spec `b4397537`) | complete (`a31a46c`, `503ba38`) | calibration base `px2b-v2` pinned (fit set `81257bf0`); 526-row slice content pinned (`1faa617b`); its calibrator's sha256 recorded when it runs | px2b_v2 and G3 tests | **no.** Only the calibration base has been fit | PX-1b acceptance (a FINAL-1 pass + Kanav's sha-matched confirmation); the C0 2027 record; the 2027 ruleset; a configured 2027 EPA source for its track | none (its gate needs 2027) |
| **PX-4b** (spec `1d7f2640`) | complete on the PX-1b track (C4) | models via pins; calibrator via the PX-2b record's hash | C4 and G3 tests | **no** | a PX-2b pass; a 2027 EPA source for its track | none |
| **M8b** (spec `63d37a95`) | complete on the PX-1b track (C4) | models, calibrator and `ranking_xgb_v2` `d18` all hash-checked | C4 and G3 tests | **no** | a PX-4b pass; the M8b pre-run record with a named mentor's **confirmed** agreement (Mr. Biery proposed, not confirmed); the mentor's review; 2027 data | none |
| **M10** (P6-M10) | built and registered | sha-pinned (`p6_m10_fit`) | M10 tests in the sweep | **yes: FAILED its M7/D16 gate (G2)** → odds served `not_validated` (D9). A forensic diagnosis exists (`P6_M10_DIAGNOSIS.md`, diagnostic only) | D9: **no redesign without Kanav's dated decision**; none is recorded | none without that decision |

**Also not run:** the frozen PX-1 chain (PX-2, PX-4, P6-M8 on 2026) is permanently stopped by D9 and is not run.

## Remaining work

**Can be done without new human input or 2027 data: none of substance.**
- Every unblocked verification has been performed: integrity re-verification, write-once confirmation, and the Phase 6 regression sweep.
- **Two optional engineering items, each needing approval:**
  - wiring PX-2b, PX-4b and M8b to the pinned 2027 EPA source (`p6_px1b_epa_source_2027.json`). Today `PX1B_TRACK.epa_snapshot` is deliberately unset;
  - pinning `ranking_xgb_v2` `d18` in the frozen P6-M6(b) harness. It is outside the acceptance chain, and its measurement is already recorded.

**External prerequisites (human input):**
1. Kanav's confirmation of D9 decision v1.
2. The 2027 P6-M1 ruleset, entered from the 2027 manual and approved by a qualified reviewer.
3. Kanav's FINAL-1 authorization, once the season is complete and synced.
4. The 2027 EPA source config.
5. After a FINAL-1 pass, Kanav's sha-matched confirmation.
6. The M8b pre-run record, with a named mentor's confirmed agreement, and later that mentor's review.
7. Kanav's dated decision on M10.

**External prerequisites (2027 data):** 2027 playoff results; a D18 EPA snapshot covering 2027; then the C0 2027 run, committed.

**Optional, needs authorization to push:** an external timestamp witness for the evidence commit (a push or RFC 3161).
