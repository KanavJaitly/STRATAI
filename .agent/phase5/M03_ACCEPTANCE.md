milestone: P5-M3 Team and robot strength views
status: ACCEPTED
record: .agent/phase5/results/p5_m3_strength_acceptance.json (commit e8ade96)
files:
  - ml/ratings/epa_states.py (new): P5-D2 source-state vocabulary; served_state derivation
  - ml/features/assembler.py: TeamFeatures.epa_source_state (validated against value source and presence);
    public wrappers point_in_time_scores / point_in_time_auto_points (no logic change)
  - ml/dataset/builder.py: arrow schema carries epa_source_state
  - ml/views/strength.py (new): TeamStrengthView composed from build_team_features + classify_match_days
  - api/routes/common.py (new, moved from predictions.py), api/routes/strength.py (new), api/app.py
  - scripts/verify_d18_production.py: equality excludes epa_source_state (postdates the D18 frame)
  - scripts/phase5_m3_strength_acceptance.py (new)
  - tests/test_views_strength.py, tests/test_epa_states.py (new)
results:
  population: 1,000 of 108,024 distinct 2026 appearances in the D18 frame (seed 20261003); frame ab1adbf3…4e25
  epa_source: d18_statbotics_primary; snapshot integrity ok (608 raw files, 24,022 records)
  exact_equality_with_assembler: 0 mismatches
  contracts (n, uncertainty, absent reasons, EPA provenance): 0 failures
  additional_equality_with_d18_frame: 0 mismatches (epa_source_state excluded; the frame predates it)
  epa_source_states: current 963, withheld_no_prior_event 33, fallback_stratai 4
decisions:
  - "season-to-date auto points" served per event (Phase 4's per-event values), never pooled: pooling would be a new statistic
  - defense/feeding uncertainty is kind "none" (median has no SD in Phase 3); agreement is shown as its own measure
  - defense validation_status = definition_pending (Phase 3 M14 decision open); feeding = not_validated
  - team_metrics is not read: it is a current-state snapshot and would leak past as_of
tests: strength 10 passed; states + assembler + builder 49 passed; API regression 96 passed
bug_hunt: point-in-time sentinel (a later score of 999 and a later scouting rating are never visible); naive as_of refused (422)
known_risks:
  - acceptance script emits a pydantic 2.11 deprecation warning (instance model_fields); cosmetic, result unaffected
done_means: contract tests pass; equality check recorded (0 mismatches) -> MET
