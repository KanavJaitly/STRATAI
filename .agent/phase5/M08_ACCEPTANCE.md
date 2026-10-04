milestone: P5-M8 Game-rule analysis
status: NOT ACCEPTED. Built and tested, with the rules decided (P5-D13) and implemented; "exercised by DM1" waits on human inputs
files:
  - data/game_spec.py: GameSpec v1 with human-entered action_type and element_type; catalog integrity; pre-reveal filter
  - data/design_reference.py: reference sha verified; codebook and coding; Cohen's kappa; label_status per P5-D13; reconcile_with_consensus
  - ml/gameanalysis/analysis.py, ml/gameanalysis/rules_p5d13.py: similarity, candidate archetypes, expected ranges, dominant component
  - tests/test_game_analysis.py, tests/test_rules_p5d13.py (synthetic fixtures, including the DM1 runner wiring end to end)
acceptance_criteria:
  schema, determinism and catalog-integrity tests: PASS
  reference sha256 verified at load: PASS
  codebook agreement (kappa) reported: NOT RUN (needs the human codebook and two human codings)
  output labels: descriptive / curated_reference_unverified / not_validated, as specified (tested)
external_human_inputs (never simulated):
  - catalog game specs entered from manuals
  - the codebook
  - two independent codings, then the consensus coding
  - the action-type -> function map (pre-reveal)
done_means: "built and tested; exercised by DM1" -> NOT MET (DM1 blocked by human inputs)
