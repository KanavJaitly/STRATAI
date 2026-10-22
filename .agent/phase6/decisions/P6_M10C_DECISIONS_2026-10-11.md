# Kanav's decisions of 2026-10-11 (Phase 6)

**Recorded from Kanav Jaitly's instruction of 2026-10-11.** Transcribed by Claude Code. Nothing here is a result.

## 1. P6-M10c

**Approved for pursuit** as a new, controlled calibration candidate.
- **Link:** q = ε/2 + (1 − ε) · expit(a_g · z).
- **ε:** pooled across source groups, bounded to [0, 0.08].
- **Slopes:** the existing source groups and per-group slopes.
- **Excluded from this version:** group-specific ε and week-specific factors.

**Spec:** `P6_M10C_SPEC.md`, frozen before any fit or evaluation (`P6_M10C_FREEZE_2026-10-11.md`).

**Unchanged:**
- M10b's frozen spec (`d699afaf`), A1 (`a453eaba`), its DEV result, the production calibrator, the pins and the audit;
- the served `p6m10-v1` and its `not_validated` status;
- every historical record: nothing is overwritten, amended or relabelled.

**Not authorized:** a production M10c fit or registration, pins, a 2027 run, a serving change, or any change to the acceptance gate.

## 2. DEV-c

**Approved:** preparing and running DEV-c **once**, only after the M10c spec and the DEV-c procedure are frozen (spec §4).
- It is diagnostic evidence only. It is never described as independent acceptance evidence.
- 2025 and 2026 results are never used to claim 2027 acceptance.
- **If the predeclared rule fails,** the failure is recorded honestly and the work stops: no methodology change, no registration, no serving change.

## 3. Multiplicity

**If M10c is adopted after the specification review,** it is the **sole primary candidate** eligible for the 2027 P6-M10 acceptance test.
- M10b is preserved as historical evidence and is **not** tested on 2027.
- Two candidates are never tested on 2027 so that whichever passes can be chosen.

A DEV-c pass does not authorize registration, serving, or changing the gate.

## 4. EPA-source wiring

**Approved, implementation only and fail-closed:** PX-2b, PX-4b and M8b read the pinned 2027 EPA source.
- It reuses the existing pinned source record and integrity checks, with no alternate fallback.
- It refuses on missing or mismatched pins.
- It preserves every current frozen slice, model and calibrator check.
- No blocked evaluation is run, and no specification is altered.

**Deferred:** the optional `ranking_xgb_v2` `d18` pin in the P6-M6 (b) harness.
- The write-once measurement `p6_m6b_draft_accuracy_rerun1.json` is preserved.
- **That record does not include the ranking model's hash.** Today's registry file (`1f0fe5aa…`) equals the G3 pin, and the registry is write-once, so the run used it **by inference, not by record**.

## 5. Human inputs

**D9 decision v1: confirmed by Kanav Jaitly on 2026-10-11.**
- The confirmation is against the exact blob `147463ecf103e3995d3cb5ccdaf6a289c2495738`: `decisions/p6_d9_v1_confirmation.json`.
- **It does not validate PX-1,** and it does not accept PX-1b. PX-1b's acceptance remains FINAL-1 on 2027 plus Kanav's sha-matched confirmation.

**M8b mentor.** Kanav states that Mr. Biery is the confirmed M8b mentor and has agreed to review every miss.
- The M8b pre-run record is prepared from that statement: `decisions/P6_M8B_PRE_RUN_DRAFT.md` and `p6_m8b_pre_run_draft.json`.
- **It is a draft, not yet adoptable.** Two items of required evidence are missing and are not invented:
  1. the date of Mr. Biery's agreement;
  2. the evidence of his written agreement (`P6_M8B_SPEC.md` §1.3).
- The 2027 seed and per-stratum count also need to be confirmed against a 2027 runtime projection, which needs 2027 data.
