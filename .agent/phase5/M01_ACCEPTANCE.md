milestone: P5-M1 Alliance and seed data
status: ACCEPTED
record: .agent/phase5/results/p5_m1_alliance_acceptance.json (commit 3082b47)
files:
  - data/alliance_checks.py (new): frozen criteria (b), (c) as pure functions
  - scripts/phase5_m1_alliance_acceptance.py (new): one-time real-data run
  - scripts/phase5_records.py (new): write-once Phase 5 records; refuses dirty trees
  - tests/test_alliance_checks.py, tests/test_phase5_records.py (new)
  - ingestion (data/alliances.py, TBA client) predates the freeze, as authorized
results:
  ingestion_facts_hold: true (608 payloads; 606 events; 591 seeded; 15 division-champion; 4,782 alliances; 0 backups)
  a_coverage: 2024 1.0, 2025 1.0, 2026 1.0 (190 / 203 / 213 playoff events)
  b_membership_exceptions: 5 teams in 4 events (2024mosl 4330; 2024mxto 9499; 2024nytr 9624; 2024onwat 7722, 9663). Likely backups, since TBA records none
  c_seed_rank: 9 violations in 6 of 591 seeded events. 8 involve TBA placeholder teams 999x (2024vapor, 2025ncash, 2026mefal, 2026txfor, 2026txmca); 1 genuine anomaly (2026milac seed 8: captain 7768, expected 6087)
  d_rejections: 0
decisions: none new. A failing criterion is a recorded data finding, per the spec.
tests: 21 passed (alliance checks, records, alliances); full regression at the phase audits
bug_hunt: placeholder 999x teams surfaced (they must be handled by any future playoff model, PX-1). Seed order and outcome separation verified
known_risks:
  - backups unknown (TBA null)
  - placeholder 999x teams in alliances
done_means: (a)–(d) recorded with their numbers -> MET
