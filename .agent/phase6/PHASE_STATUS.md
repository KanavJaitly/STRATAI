phase: 6
status: P6-M0 FROZEN (Kanav, 2026-10-04; revision 2); zero implementation
spec: docs/P6Milestones.md (revision 2, frozen)
decisions: .agent/phase6/P6_M0_DECISIONS.md (P6-A1 … A12 APPROVED; P6-Q0 … Q13 DECIDED)
freeze_record: .agent/phase6/P6_M0_FREEZE.md (the commit introducing it is the freeze point)
current_milestone: none started; next is P6-M1, after the P6-Q0 baseline exists
milestones: [P6-M0 freeze (FROZEN), P6-M1 rulesets, P6-M2 PX-1, P6-M3 PX-2, P6-M4 PX-3, P6-M5 PX-4, P6-M6 profiles+draft, P6-M7 selection optimizer, P6-M8 DM1 validation, P6-M9 strategy repr., P6-M10 outcome model, P6-M11 strategy optimizer, P6-M12 strategy validation, P6-M13 parity audit (DM2), P6-M14 sign-off]
done_means: {P6-DM1: NOT MET (not run), P6-DM2: NOT MET (not run)}
prerequisite_before_implementation:
  - P6-Q0: merge phase5/build @ 6e76520 into main with Kanav's explicit approval (merge + push), then branch Phase 6 from that main. NOT PERFORMED.
human_inputs_required: [P6-M1 season rulesets entered from the manuals + named reviewer; P6-M8 defensible-reason review by a named mentor]
known_risks:
  - PX-1 must beat both M6/M7-on-playoffs and seed-only with paired CIs excluding 0 (P6-Q3); a failure is a D9 stop
  - PX-2 may fail (M7 failed on qualification; playoff ECE 0.119): playoff probabilities would stay not_validated
  - strategy effects are not identifiable from historical data (no strategy records; 0 scouting rows): not_validated
  - defense/feeding are insufficient_data for every historical event (P6-Q12)
results: none (no Phase 6 run has happened)
