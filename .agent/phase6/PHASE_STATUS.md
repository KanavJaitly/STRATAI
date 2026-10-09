phase: 6
branch: phase6/build (from main aab8fe1, the P6-Q0 baseline)
status: IMPLEMENTATION COMPLETE TO THE LIMIT OF AVAILABLE INPUTS; Phase 6 NOT complete
spec: docs/P6Milestones.md (P6-M0 FROZEN at 9964001; unchanged)
done_means: {P6-DM1: NOT MET (PX-1 gate FAILED 2026-10-08 -> PX-2/PX-4/M8 blocked by D9), P6-DM2: MET (p6_m13_parity_audit_rerun1.json)}
accepted: [P6-M0 frozen, P6-M1 (rulesets approved ids 4-6; check recorded), P6-M4 (correctness + real structure), P6-M6 (a), P6-M6 (b) measured (non-gating), P6-M7 optimization correctness, P6-M9, P6-M11, P6-M12 (rerun1), P6-M13 (rerun1), P6-M14]
failed_d9: [P6-M10 gate (G2) -> baseline strategy odds not_validated; P6-M2 PX-1 gate (P6-Q3: worse than M6/M7 and seed-only; rerun1 after the 2026-10-08 audit's two defect fixes also FAILED -- cause: 2026 scale shift in the frozen raw-unit design) -> PX-2, PX-4, P6-M8 not run; no redesign without Kanav's dated decision]
failed_and_superseded: [P6-M12 run 1 (harness defect), P6-M13 run 1 (two demonstrated defects), P6-M6 (b) run 1 (pooled rates only)] -- all kept
decided: [PX-1 accepted as not_validated under the frozen spec (Kanav, 2026-10-08; decisions/P6_PX1_NOT_VALIDATED_2026-10-08.md) -> PX-2, PX-4, P6-M8 stay not run (D9); any redesign is a separate pre-registered effort, not validatable on 2026]
px1b: [spec v1 frozen (P6_M2_PX1B_SPEC.md, ca13e98); PX-1 amendment A1 (P6_M2_PX1_SPEC_A1.md); DEV-1 2024->2025 DV1+DV2 met (development, not acceptance); final candidate px1b-v1 frozen (fit 2024-2026, before 2027 data); FINAL-1 needs 2027 data, an approved 2027 ruleset, a 2027 M1 check and 2027 EPA -> not evaluable; does NOT unblock PX-2/PX-4/M8 without a versioned D9 decision (spec §8)]
blocked_by_human_input: [P6-M8 mentor (Mr. Biery) agreement and review -- outstanding, and moot unless PX-4 can run]
prerequisites:
  - migration 0011 on the serving database: APPLIED 2026-10-06 (Kanav's approval)
records: .agent/phase6/results/ (p6_m10_fit, p6_m10_outcome_model, p6_m12_strategy_validation(+_rerun1), p6_m13_parity_audit(+_rerun1), p6_m6a_profiles, p6_m1_ruleset_check, p6_m2_px1(+_rerun1), p6_px1b_dev, p6_px1b_final_fit, p6_m6b_draft_accuracy(+_rerun1))
human_inputs_never_fabricated: true
known_risks:
  - PX-1 must beat M6/M7-on-playoffs and seed-only (P6-Q3); PX-2 must pass the M7 gate that M7 itself failed on qualifications
  - strategy and defense/feeding effects are unmeasurable from history (0 scouting rows; no strategy records)
no_phase7_or_8_work: true (no HTTP routes, no UI; pinned by tests/test_phase6_contract.py)
