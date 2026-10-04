milestone: P5-M7 Meta tracking (Week 0/1 onward)
status: ACCEPTED (descriptive outputs only)
decision: P5-D12 (Q2): event-level Welch; Holm across the 4 components per (season, week); effect size = difference in mean share (pp); denominator totalPoints
records:
  - p5_m7_adapter_parity.json (commit e4a8df0)
  - p5_m7_detector.json (sha 248ff3c7..., commit 5d39052, 0.8 min)
results:
  a_adapter_parity: PASSED, 106,390 / 106,390 rows
  b_false_alarms: PASSED
    - 1,000 within-season week-label permutations (seed 20261008); 16,000 families
    - family-wise flag rate 0.0436 (<= 0.05); 95% Clopper-Pearson upper bound 0.0469 (<= 0.07)
  c_real_flags: 10 of 16 real (season, week) families flagged, recorded descriptively
    - the pattern: foul share falling and teleop share rising through each season
    - no accuracy claim
units: events with a TBA week (2024 181, 2025 194, 2026 204)
documented_gap (P5-D10): archetype or mechanism meta is not observable from match data
done_means: "(a) and (b) pass; (c) recorded" -> MET
