milestone: P5-M9 Team capability intake and the DM1 end-to-end dry run
status: NOT ACCEPTED. DM1 NOT MET: BLOCKED BY REQUIRED HUMAN INPUT
built:
  - ml/gameanalysis/capability.py: raw-first intake; deterministic human-authored rubric; heuristic_not_validated_against_outcomes
  - scripts/phase5_dm1_dry_run.py:
      run: P5-D13 rules; consensus labels; per-function kappa status; clock; write-once before any 2026 match data
      score: once, 2026 competition weeks 1-3 = TBA weeks 0-2, not_validated
      mentor-review: records the human review
  - the runner is wired end to end under test with synthetic fixtures (nothing recorded)
acceptance_criteria:
  a_DM1_within_5_days: NOT RUN. The clock starts when a person begins entering the 2026 spec from the manual
  b_scored_once: NOT RUN (follows a)
  c_mentor_review: NOT RUN (human)
external_human_inputs (never simulated; AI knowledge of 2026 is hindsight leakage, P5-D7):
  1. the 2026 game spec, entered from the manual by a person (starts the clock)
  2. pre-2026 catalog specs, entered from manuals, plus their manifest
  3. the codebook
  4. two independent codings of the 77 reference rows
  5. the consensus-meeting coding
  6. the action-type -> function map (pre-reveal)
  7. the human-authored feasibility rubric
  8. at least 10 sample team profiles, fixed before the run
  9. the mentor review
done_means: DM1 met -> NOT MET (blocked by human input)
