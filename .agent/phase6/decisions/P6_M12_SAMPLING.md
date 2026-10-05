# P6-M12 sampling and run plan (dated pre-run record, P6-Q13 protocol)

**2026-10-05, written before the P6-M12 run.** The commit introducing this file fixes the plan. No P6-M12 result exists yet.

## Population and sample

- **Population:** exactly the P6-M10 evaluated population. That is held-out 2026 EPA-complete qualification matches in the D18 frame `frame_ab1adbf38b43c2f3`, excluding ties and matches with an absent model input (12,215 matches; `p6_m10_outcome_model.json`).
  - Playoff matches are excluded. P6-M3 has not run, so the playoff context is unavailable (P6-A12).
- **Strata:** the TBA event week, from the event's current raw payload (the P5-M7 source).
- **Sample:**
  - **15 matches per week stratum present in the population** (all of a stratum if it has fewer).
  - Within each stratum, matches are sorted by `match_key` and drawn with `random.Random(20261008 + week).sample`.
  - Strata are processed in ascending week order. The sample order is that concatenation.
- **Sentinel subset:** the first 20 matches of the sample order.

## What is checked (frozen milestone criteria a–c; d optional)

**(a) Reproduction.** For each sampled match, the engine is replayed at match time from the isolated database: the Phase 4 assembler, D18 historical EPA semantics and causal scales. Then:
- the assembled features must equal the frame's (excluding `epa_source_state`, as in P5-M3);
- the engine's baseline probability must equal, bit for bit, the P6-M10 model's probability on the frame row.

**(b) Point-in-time sentinels.** These run on a dedicated isolated clone, `stratai_test_p6m12`, cloned from the serving database by `scripts.phase5_isolated_db` and retained. For each sentinel match, three rows are inserted, all after `as_of`:
- a future match at the same event, involving its six teams, with extreme scores;
- a future scouting observation;
- a future coach observation.

The engine is then re-run. Every output must be unchanged: baseline odds, the recommended strategy and its odds, the alternatives, and the coach observations loaded. The sentinel rows are removed afterwards.

**(c) Honest odds.**
- p_red + p_blue = 1 within 1e-12.
- The engine's odds equal the model's output, so nothing is floored or clamped.
- Raw probabilities below 0.05 or above 0.95 are kept, and shown as "<5%" / ">95%".
- Counts are reported.

**(d) Mentor review:** optional and not gating. It is recorded as not performed unless a genuine named review is supplied. None will be fabricated.

## What this cannot validate (stated in the record)

- Strategy effects: no historical record of which strategy an alliance played, and 0 scouting rows.
- Defense and feeding effects.
- The calibration of the baseline odds: the P6-M10 gate failed.

## Runtime

- **Projected:** about 15 minutes (assembler + exhaustive recommender, about 4 s per match, plus the sentinel re-runs).
- **Hard budget:** 45 minutes. On overrun the harness stops and records partial results as not passed.
- **Record:** `.agent/phase6/results/p6_m12_strategy_validation.json`, write-once.
