phase: 6
status: SPECIFICATION_DEFINED (revision 1, 2026-10-04); NOT FROZEN; zero implementation
spec: docs/P6Milestones.md
decisions: .agent/phase6/P6_M0_DECISIONS.md
current_milestone: P6-M0 (specification freeze), awaiting Kanav
milestones: [P6-M0 freeze, P6-M1 rulesets, P6-M2 PX-1, P6-M3 PX-2, P6-M4 PX-3, P6-M5 PX-4, P6-M6 profiles+draft, P6-M7 selection optimizer, P6-M8 DM1 validation, P6-M9 strategy repr., P6-M10 outcome model, P6-M11 strategy optimizer, P6-M12 strategy validation, P6-M13 parity audit (DM2), P6-M14 sign-off]
done_means: {P6-DM1: alliance selection on real past events (operational terms: P6-Q1), P6-DM2: verifiably zero AI-odds inflation}
human_decisions_required: [P6-Q0 … P6-Q13; approve or override P6-A1 … P6-A12]
human_inputs_required: [P6-M1 season rulesets entered from the manuals + named reviewer; P6-M8 defensible-reason review; P6-Q11 defense definition (Phase 3 M14)]
blockers:
  - P6-Q0: Phase 5 code is only on phase5/build @ 6e76520 (unpushed); the implementation baseline must be decided
known_risks:
  - PX-2 may fail (M7 failed on qualification; playoff ECE 0.119): playoff probabilities would stay not_validated (D9)
  - strategy effects are not identifiable from historical data (no strategy records; 0 scouting rows)
  - defense/feeding are insufficient_data for every historical event
results: none (no Phase 6 run has happened)
