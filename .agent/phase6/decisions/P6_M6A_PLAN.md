# P6-M6 (a) plan: profile equality (dated pre-run record, P6-Q13 protocol)

**2026-10-05, before the run.** The commit introducing this file fixes the plan.

- **Population:** held-out 2026 events that are seeded (no null seed, so no division-champion event), have P5-M1 alliances and have a qualification schedule.
- **Sample:**
  - 30 events, drawn with `random.Random(20261011).sample` from those events sorted by `event_key`;
  - in each event, every team on an alliance (captain and picks).
- **Selection moment:** one minute after the event's latest qualification match. This is a fact of the schedule; it needs no P6-M1 ruleset.
- **Features:** the Phase 4 assembler, with D18 EPA semantics (`load_d18_provider`) and causal scales, on the isolated `stratai_test` copy (read-only).
- **Check (frozen criterion (a): exact equality with each source function):**
  - **Directly mirrored values:** for every sampled team, `ml.playoffs.selection.candidate_profile` must report exactly the source `TeamFeatures` values, with their n:
    - scoring EPA (`epa_total`);
    - average score (`average_score`, n = `matches_used`);
    - reliability (`reliability_score`);
    - consistency (`consistency_rating`);
    - defense (`defense_score`, n = `defense_observation_count`);
    - feeding (`feeding_score`, n = `feeding_observation_count`).
  - **Synergy and role compatibility,** with the team's real alliance as the configuration: they must equal `ml.synergy.score.alliance_synergy` (Phase 4 M9, as built) exactly.
  - **Defense and feeding** must be `insufficient_data` whenever no observation exists. Today that is every team, since there are 0 scouting rows (P6-Q12), and nothing may be imputed.
- **Runtime:** projected under 10 minutes; hard budget 45 minutes.
- **Record:** `.agent/phase6/results/p6_m6a_profiles.json`, write-once.
- **Out of scope:** the draft-model criterion (b) needs the approved P6-M1 rulesets and is blocked.
