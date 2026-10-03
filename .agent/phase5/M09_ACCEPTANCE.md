milestone: P5-M9 Team capability intake and the DM1 end-to-end dry run
status: NOT ACCEPTED (BLOCKED_ON_HUMAN + open decision Q3). DM1 NOT MET
files:
  - ml/gameanalysis/capability.py (new): CapabilityIntake landed raw-first (source capability_intake); a human-authored Rubric schema; a deterministic recommend() giving the realistic ceiling, the recommended archetype, achievable features and an explanation of every requirement met or unmet, labelled heuristic_not_validated_against_outcomes
  - scripts/phase5_dm1_dry_run.py (new):
      run: validates and hashes every input; enforces the reveal-year catalog/reference filters; reads 2024-2025 breakdowns only; records the elapsed time from the spec's entry_started_at; writes predictions write-once before any 2026 match data
      score: once, against 2026 weeks 1-3, labelled not_validated regardless
      mentor-review: records a named, dated review
  - tests/test_game_analysis.py: rubric determinism and explanation; raw-first intake
acceptance_criteria:
  a_DM1_run_within_5_days: NOT RUN. Needs Q3 rules, a human-entered 2026 spec (the clock starts at entry), human catalog specs, codebook and codings, a human-authored rubric, and at least 10 sample profiles fixed before the run
  b_predictions_scored_once: NOT RUN (follows a)
  c_mentor_review: NOT RUN (human)
note: none of the human inputs was simulated or authored by an AI. AI knowledge of the 2026 game would be hindsight leakage (P5-D7)
done_means: DM1 met -> NOT MET
