milestone: P6-M6 Selection-time candidate profiles and draft model
status: (a) ACCEPTED; (b) NOT RUN -- blocked by P6-M1 (decline rules)
evidence_a: .agent/phase6/results/p6_m6a_profiles.json (plan .agent/phase6/decisions/P6_M6A_PLAN.md; 768 teams, 30 seeded 2026 events, 0 mismatches; defense/feeding insufficient_data; 0.2 min)
implementation: ml/playoffs/selection.py (CandidateProfile: value, n, status for every factor; deterministic best-available draft on the validated P5-M4 ordering; pick_prediction_accuracy); scripts/phase6_playoff_track.py m6b (measured, not gating)
