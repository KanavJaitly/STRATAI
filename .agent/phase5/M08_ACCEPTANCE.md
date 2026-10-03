milestone: P5-M8 Game-rule analysis
status: NOT ACCEPTED (built and tested; not exercised by DM1, which is BLOCKED_ON_HUMAN plus open decision Q3)
files:
  - data/game_spec.py (new): versioned, human-entered GameSpec (match length, scoring actions by period, RP rules, field elements, manual sections, entered_by, entry clock, llm_used fixed False); catalog manifest with sha256 integrity; pre-reveal filter
  - data/design_reference.py (new): curated reference loaded with sha256 40aef139...39e1 and 77 rows verified at load, micro-archetype verbatim, every example labelled curated_reference_unverified, pre-reveal filter (2026 drops the 10 REBUILT rows); human Codebook / Coding schemas; double-coding validation; Cohen's kappa pooled and per function; label_status with an explicit gate
  - ml/gameanalysis/analysis.py (new): value table; past-season component ranges (seasons < reveal); analysis pipeline with Q3 rule slots that refuse until decided
  - tests/test_game_analysis.py (8): schema, determinism, catalog integrity, reference sha and filter, kappa, refusals, leakage refusal (synthetic fixtures, labelled as such)
acceptance_criteria:
  schema_determinism_catalog_integrity_tests: PASS (tests above)
  reference_sha256_verified_at_load: PASS
  codebook_agreement_reported: NOT RUN. Needs the human codebook and two independent human codings
  outputs_labelled: descriptive (value table, ranges), curated_reference_unverified (examples), not_validated (forward-looking Q3 outputs)
open:
  - Q3 (.agent/phase5/M08_DECISION_REQUIRED.md): similarity, candidate archetypes, expected ranges, dominant components, the kappa gate and coding reconciliation
  - human inputs: catalog specs, the codebook, two codings
done_means: "built and tested; exercised by DM1" -> NOT MET (not exercised: DM1 blocked)
