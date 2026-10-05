phase: 6
branch: phase6/build (from main aab8fe1, the P6-Q0 baseline)
status: IMPLEMENTATION COMPLETE TO THE LIMIT OF AVAILABLE INPUTS; Phase 6 NOT complete
spec: docs/P6Milestones.md (P6-M0 FROZEN at 9964001; unchanged)
done_means: {P6-DM1: NOT MET (blocked by required human input: P6-M1 rulesets), P6-DM2: MET (p6_m13_parity_audit_rerun1.json)}
accepted: [P6-M0 frozen, P6-M4 implementation correctness, P6-M6 (a), P6-M7 optimization correctness, P6-M9, P6-M11, P6-M12 (rerun1), P6-M13 (rerun1), P6-M14]
failed_d9: [P6-M10 gate (G2) -> baseline strategy odds not_validated; no redesign without Kanav's dated decision]
failed_and_superseded: [P6-M12 run 1 (harness defect), P6-M13 run 1 (two demonstrated defects)] -- both kept
blocked_by_human_input: [P6-M1 rulesets 2024-2026 (entered from the manuals; different named reviewer) -> P6-M2, M3, M5, M6 (b), M8 not run; P6-M8 pre-run record and named mentor review]
prerequisites:
  - migration 0011 on the serving database (production DDL: Kanav's explicit approval)
records: .agent/phase6/results/ (p6_m10_fit, p6_m10_outcome_model, p6_m12_strategy_validation(+_rerun1), p6_m13_parity_audit(+_rerun1), p6_m6a_profiles)
human_inputs_never_fabricated: true
known_risks:
  - PX-1 must beat M6/M7-on-playoffs and seed-only (P6-Q3); PX-2 must pass the M7 gate that M7 itself failed on qualifications
  - strategy and defense/feeding effects are unmeasurable from history (0 scouting rows; no strategy records)
no_phase7_or_8_work: true (no HTTP routes, no UI; pinned by tests/test_phase6_contract.py)
