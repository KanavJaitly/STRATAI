milestone: P5-M7 Meta tracking (Week 0/1 onward)
status: NOT ACCEPTED (BLOCKED_ON_HUMAN: open decision Q2; (a) passed, (b)/(c) wait for Q2)
records: .agent/phase5/results/p5_m7_adapter_parity.json (commit e4a8df0)
files:
  - ml/features/score_components.py (new): auto/teleop/endgame/fouls/adjust per season. Extends the frozen ml/features/score_breakdown.py without modifying it (auto comes from its auto_points)
  - ml/meta/weekly.py (new): rows, weekly distributions, Holm, share tables (Q2's two candidate tests), detector, event-level week permutation, Clopper-Pearson
  - scripts/phase5_m7_meta.py (new): (a) parity plus the weekly distributions
  - tests/test_meta_weekly.py (9)
results:
  a_adapter_parity: PASSED. 106,390 of 106,390 valid alliance rows (2024 33,954; 2025 35,692; 2026 36,744); 0 failures
    - every completed match has a breakdown
    - rows without a TBA week (championship and off-season): 2024 2,266; 2025 2,282; 2026 2,270
  weekly_distributions: recorded (descriptive)
  b_false_alarms: NOT RUN (Q2)
  c_real_flags: NOT RUN (Q2)
decisions:
  - Q2 OPEN (.agent/phase5/M07_DECISION_REQUIRED.md): the detector's test statistic and unit are unspecified and outcome-relevant
  - endgame follows TBA's own labels per season (verified, not a decision of method)
documented_gap (P5-D10): archetype or mechanism meta is not observable from match data; the curated design set has no per-week labels. It needs at-event mechanism labels, a future data-collection extension
done_means: "(a) and (b) pass; (c) recorded" -> NOT MET ((a) passed; (b)/(c) wait for Q2)
