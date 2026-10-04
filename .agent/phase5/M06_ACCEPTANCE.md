milestone: P5-M6 In-season learning loop (DM2)
status: ACCEPTED on its criteria (a)-(e), via the labelled rerun. DM2 MET since the P5-D3 adoption of P5-M2 (2026-10-04)
population: P5-D14, a seeded stratified selection (seed 20261006, fingerprint 24e23b1a...4f48), p5_m6_selection.json (commit 6d8134b)
  - E1 2026iscmp; E2 2026nccab; E3 2026cur; E4 2026vache; E5 2025mawne
  - 44 checked steps
files:
  - data/orchestrator.py: watch_event after_sync and after_watch_sync, which recompute team_metrics during --watch and trigger the live EPA refresh when configured
  - data/metrics/compute.py: quality-issue dedup (§9.10, the prerequisite)
  - data/replay.py (ReplayTBAClient)
  - scripts/phase5_m6_selection.py, scripts/phase5_m6_replay.py
  - tests/test_watch_follow_on.py, test_data_replay.py, test_phase5_m6_selection.py, test_metrics_quality.py (dedup)
records:
  - p5_m6_replay.json: FAILED, kept unchanged (commit eafba43). 14 problems, all harness defects (M06_RECORDED_RUN_FAILURE.md)
  - p5_m6_replay_rerun1.json: PASSED (sha 42f8c172..., provenance commit 5d39052). Harness corrections approved 2026-10-03
  - p5_m6_replay_rerun1_log.json: the complete response log (sha 33e3fea3...)
rerun_results: 44 / 44 steps, 32.6 min (budget 45), 0 problems
  (a) served = assembler: 352 / 352; match count +1 traced to its raw payload: 264 / 264
  (b) no-op polls: 44 / 44; control comparisons: 47 unchanged (baselines reset after 13 bulk syncs, 388 matches)
  (c) sampled re-requests: 171 / 171 identical, each under its original EPA settings
  (d) team_metrics = recompute: 678 / 678
  (e) 2026iscmp: fallback_stratai served 80 / 80 with provenance
  leakage sentinels: 10 / 10 unchanged (future match row and future scouting observation, one of each per event)
  endpoints: 8 / 8 returned 200, including E4's switch from raw_epa to ranking_xgb_v2 (2 / 2)
  diagnostic: d18_skip vs literal_state differed on 4 of 352 lookups (production uses d18_skip, P5-D11)
note: the §9.10 dedup was committed after the rerun. None of P5-M6's criteria read data_quality_issues
done_means: "DM2 by the replay with (a)-(e) passing" -> replay criteria MET; P5-M2 adopted (P5-D3, 2026-10-04) -> DM2 MET
