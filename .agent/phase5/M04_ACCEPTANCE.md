milestone: P5-M4 Event analysis (pre-event and in-event)
status: ACCEPTED
record: .agent/phase5/results/p5_m4_event_analysis.json (commit 4cc3792; sha256 in docs/phase5.md)
files:
  - ml/views/event_analysis.py (new): event-level policy (switch point, one model per ordering), ordering, captain hit, per-event Spearman, paired event bootstrap; serving_switch from the canonical schedule; SERVE_M5V2_AFTER_SWITCH pinned to the record (tested)
  - api/routes/event_analysis.py (new): GET /events/{event_key}/analysis; registered in api/app.py; path pinned in tests/test_api_foundation.py
  - scripts/phase5_m4_event_analysis.py (new): one-time (a)-(c) evaluation
  - tests/test_event_analysis.py (10), tests/test_event_analysis_api.py (7)
results:
  population: D18 frame ab1adbf3...4e25, held-out 2026, 208 events, 8,160 team-events; frozen M5 v2 from the registry (sha256 1f0fe5aa...6312), never refit; D18 EPA provider
  a_reproduction: EXACT. Raw EPA 0.5955333742533729 and M5 v2 midpoint 0.6112440558451762, equal to results/d18/m05v2_result.json
  b_served_policy (switch point, measured once):
    - M5 v2 0.6138 vs raw EPA 0.5955 (208 events)
    - paired mean +0.0183, event-bootstrap 95% CI [0.0082, 0.0288]
    - so M5 v2 is served after the switch (SERVE_M5V2_AFTER_SWITCH = True)
    - all 208 switch snapshots are at the next qualification match
  c_captain_hit_rate (validated_as_measured; 208 events, all with 8 seeded captains):
    - pre-event: 0.4207 (CI 0.4056-0.4357); the policy is raw EPA, so it equals the baseline
    - switch: policy (M5 v2) 0.4255 vs raw EPA 0.4207; paired CI [-0.0126, 0.0198] includes 0, so no improvement claimed
decisions (operationalizations, recorded before the run in the script docstring and constants):
  - switch snapshot as_of = the event's next canonical qualification match after the last team's ⌈n_i/2⌉-th retained row (the first decision the switched ordering serves)
  - CI method: Phase 4's own precedent (D18 M7 diagnostic): event-cluster bootstrap, 1,000 resamples, percentile 95%; seed 20261004 pre-declared
  - captain hit denominator 8 as specified; every event had 8 seeded captains
  - serving counts n_i from the canonical schedule (the evaluation used retained rows); documented in serving_switch
tests: 57 passed (event analysis, API foundation); isolated database (stratai_test)
bug_hunt:
  - raw-EPA ties (-inf for no EPA) break by team number; no-EPA teams are served with a null score, never a fabricated one
  - the 2nd (switch) match itself is not "before" as_of; checked
known_risks:
  - the endpoint builds each team's features twice (ordering and strength view); a performance cost only
done_means: (a) exact; (b) and (c) recorded; the endpoint serves only labelled outputs -> MET
