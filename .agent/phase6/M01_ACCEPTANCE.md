milestone: P6-M1 Season rulesets for alliance selection and playoffs
status: IMPLEMENTED; NOT ACCEPTED -- BLOCKED BY REQUIRED HUMAN INPUT
implementation: data/rulesets.py (SeasonRuleset schema; draft -> submit -> approval by a DIFFERENT named reviewer; versions kept; approved_ruleset refuses unapproved seasons); database/migrations/0011_phase6_season_rulesets.sql; scripts/phase6_rulesets.py (CLI); scripts/phase6_playoff_track.py m1 (a: bracket reproduction vs real TBA structure; b: serpentine captain rule)
tests: tests/test_phase6_rulesets.py (workflow, refusal, smoke of the reproduction path with SYNTHETIC rulesets), tests/test_phase6_playoff_evaluation.py
blocked_on:
  - approved 2024, 2025, 2026 rulesets entered from the official manuals (every rule cited) and approved by a named reviewer
  - migration 0011 on the serving database (production DDL: Kanav's explicit approval)
no_fabrication: no ruleset was drafted, entered or approved by Claude; test rulesets are labelled SYNTHETIC fixtures
