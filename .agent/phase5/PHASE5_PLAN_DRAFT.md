# Phase 5 — Implementation plan (DRAFT; superseded 2026-10-02 by the formal proposed specification in docs/P5Milestones.md, kept as history)

2026-10-02. Based on `docs/ROADMAP.md` Phase 5 (`docs/P5Milestones.md` is empty) and the Phase 4 contracts as they actually stand:
- **Status:** Phase 4 evaluation complete; acceptance criteria not fully met (M7 failed).
- **Production serving:** the D18 models and source (`docs/ml_models.md` §9).
- **Trust table:** `docs/ml_models.md` §10.

**Roadmap done-means:**
1. The pre-season module runs end-to-end within 5 days of a game reveal (dry-run against a past season).
2. Mid-season, the ratings visibly update as new matches arrive.

**Standing rules, carried over:**
- no LLM in the core;
- point-in-time features only;
- `insufficient_data` propagates;
- every new output carries a `validation_status`;
- no playoff, series or bracket probability is presented as validated.

## 0. Prerequisites (before or at the start of Phase 5)

| # | Item | Why | Owner |
|---|---|---|---|
| P0 | Accept or reject M5 v2 (D18) | Every ranking feature depends on it | Kanav |
| P1 | **Live EPA freshness.** A pre-registered spec, then an implementation, for refreshing the D18 source during a season: a snapshot per refresh, provenance per refresh, the D18 selection and timing rules unchanged, and a provider reload on refresh | The D18 source is a fixed snapshot, loaded once, and refuses a changed `team_event_stats`. The done-means "ratings visibly update" needs fresh prior-event EPA. In-event features already update from the canonical tables | Spec: Kanav decides; build: P5-M1 |
| P2 | Land TBA `/event/{key}/alliances` (Phase 2 path, raw-first) | Ground truth for captain and alliance predictions; seeds for any future playoff model | P5-M1 |
| P3 | Phase 3 M14: feeding data collection and the defense definition | Team-strength views must not imply feeding is validated | Kanav |

## 1. SUPPORTED NOW — built on validated Phase 4 contracts

### P5-A Event analysis (pre-event and in-event)

| | |
|---|---|
| **Inputs** | event_key; roster (`ml.features.roster`); as_of |
| **Outputs** | attending-team comparison (EPA components, Phase 3 metrics with presence flags); **predicted qualification ordering**; likely alliance captains (top-k of the predicted ordering); each with `validation_status` |
| **Data** | canonical tables; D18 EPA source; final rankings (landed) |
| **Phase 4 contracts** | **Pre-event:** the M4 raw-EPA ranking baseline (`RawEpaRankingBaseline`, Spearman 0.5955). At the pre-event snapshot M5 v2 is *below* raw EPA (0.5565), so pre-event ordering must use raw EPA. **In-event (from each team's mid-qualification point):** M5 v2 (0.6112 midpoint, 0.6314 last snapshot). Win probabilities only through the gated M12 contract |
| **Already implemented** | M12 ranking endpoint (M5 v2, any as_of); features; registry; provenance |
| **To build** | (1) A snapshot-aware ranking policy: raw EPA before the event, M5 v2 after the mid-qualification point, both shown in between. Rule frozen in a spec; no new model. (2) Captain-candidate derivation and its backtest (needs P2). (3) Team comparison payload. (4) An event-analysis endpoint |
| **Tests** | A contract test that the pre-event path uses the baseline. A replay backtest on held-out 2026 (no retraining): ordering Spearman by snapshot must reproduce the D18 numbers. A captain hit-rate backtest against real alliances (P2), reported with a CI. Point-in-time sentinel tests |
| **Done** | The endpoint returns ordering, comparison and captain candidates with validation status; the replay reproduces 0.5955 / 0.6112; the captain hit rate is measured and documented, whatever it is |

### P5-B Qualification match forecasts and expected qualification records

| | |
|---|---|
| **Inputs** | the event's qualification schedule; as_of |
| **Outputs** | per-match rounded qualification probabilities; per-team expected qualification wins as a range |
| **Phase 4 contracts** | the gated qualification probability (ECE 0.015; bins within ±3.2 pts); expected-wins error 1.12 vs 0.96 irreducible |
| **Already implemented** | the qualification win-probability endpoint (rounded, gated) |
| **To build** | (1) A schedule-level aggregator. Expected wins are the sum of per-match q, with a Poisson-binomial range, matching the M7 math. (2) An early-season (weeks 1–3) low-confidence label (ECE 0.046–0.068 measured). (3) An endpoint |
| **Tests** | Replay on 2026 qualifications: mean actual − expected ≈ 0 and mean \|error\| ≈ 1.12 (reproduces the diagnostic); interval coverage reported; no playoff matches accepted |
| **Done** | Expected records reproduce the D18 diagnostic numbers; coverage is documented; playoff matches are refused or labelled unvalidated |

**Ranking-point (RP) projection is out of scope:** bonus RPs were never modelled.

### P5-C Robot/team strength analysis

| | |
|---|---|
| **Inputs** | team, event, as_of |
| **Outputs** | EPA total and components (with source provenance); Phase 3 metrics (average, SD, consistency, good/average/bad day); auto-points history; defense (scouting); feeding marked unvalidated |
| **Phase 4 contracts** | features (M1) with presence flags; D18 provenance; `average_auto_points` adapters |
| **Already implemented** | almost all of it (assembler, Phase 3 `/teams/.../metrics`) |
| **To build** | an aggregation endpoint; season-to-date trend series; uncertainty (SD and n) shown with every mean |
| **Tests** | contract tests (presence flags, provenance, `insufficient_data`); point-in-time tests |
| **Done** | Every displayed statistic carries n, uncertainty and provenance; nothing absent is shown as 0 |

### P5-D Game-rule analysis (pre-season)

| | |
|---|---|
| **Inputs** | a **structured, human-entered game specification**: scoring actions and points, periods, endgame, RP rules, field elements. No LLM parses the manual in the core |
| **Outputs** | comparison to a catalog of past games (2024–2026 have real breakdown data; earlier games would be catalog-only); scoring-action value tables; candidate archetypes |
| **Phase 4 contracts** | none directly; uses the season adapters (`ml/features/score_breakdown.py`) for historical comparisons |
| **Already implemented** | nothing (adapters only) |
| **To build** | the game-spec schema; a historical catalog; similarity measures; an archetype enumeration; the roadmap's "5-day dry run" harness |
| **Tests** | schema validation; a dry run against the 2026 reveal using only pre-reveal information; archetype "dominance" predictions scored against 2026 week-1 to week-3 scoring distributions |
| **Done** | The dry run completes within 5 days of a simulated reveal, and its predictions are scored and recorded. **Dominance predictions are unvalidated until scored.** |

### P5-E Team capability intake

| | |
|---|---|
| **Inputs** | budget, manufacturing, programming and mentor resources (form) |
| **Outputs** | a realistic robot ceiling; a recommended archetype; achievable features |
| **Phase 4 contracts** | none; P5-D's archetypes |
| **Already implemented** | nothing |
| **To build** | an intake schema and storage (raw-first); a documented, rules-based mapping (no LLM); explanation output |
| **Tests** | schema and determinism tests; expert-review spot-checks (no outcome ground truth exists) |
| **Done** | Deterministic, explainable recommendations reviewed by a mentor. **Labelled heuristic, not validated against outcomes.** |

### P5-F Meta tracking (Week 0/1 onward)

| | |
|---|---|
| **Inputs** | `score_breakdown` components per week (needs component adapters per season beyond auto points) |
| **Outputs** | the weekly distribution of scoring components; change detection on component shares |
| **Phase 4 contracts** | season adapters; point-in-time discipline |
| **Already implemented** | the auto-points adapter only |
| **To build** | component adapters (2024–2026); weekly aggregates; a change-point detector with documented thresholds |
| **Tests** | adapter parity tests (as in M11); a detector backtest on 2024–2026 week sequences; false-alarm rate on shuffled weeks |
| **Done** | Component trends are reproducible from raw data, and the detector's false-alarm rate is measured. "Underperforming concepts" is limited to scoring components: no robot-design data exists |

### P5-G In-season learning loop (roadmap: ratings update as matches arrive)

| | |
|---|---|
| **Inputs** | the live sync (`--watch`); refreshed EPA (P1) |
| **Outputs** | ratings and forecasts that change as matches complete, each with an as_of and provenance |
| **Phase 4 contracts** | M5 v2 and M6/M7 are frozen artifacts. Updating means new features, **not retraining**: a retrained model is a new version needing its own evaluation |
| **Already implemented** | in-event features recompute from canonical tables on every request; `--watch` keeps the canonical tables current |
| **To build** | P1 (EPA refresh and provider reload); a refresh trigger after sync; an "as of" audit trail; `team_metrics` recompute during watch (the CLAUDE.md constraint-5 gap) |
| **Tests** | A simulated-event replay: feed a 2026 event match by match and assert ratings change only through new data, deterministically. A point-in-time sentinel. The Phase 10 stress test is later |
| **Done** | During a replayed event, ratings visibly update after each completed match, with provenance, and with no retraining |

## 2. NOT YET VALIDATED — do not build as trusted outputs

| Output | Why not | What would validate it |
|---|---|---|
| Playoff match probability | D18: higher seed underestimated by ~15 pts; ECE 0.119 | A new pre-registered model with playoff context (an antisymmetric seed-difference feature), its own frozen spec, and a stratified M7 run once |
| Bracket simulation / series odds | Compounds the playoff bias (best-of-3 at 0.60 → 0.65 vs ~0.81 observed) | The above, plus a series-level backtest |
| Playoff success prediction / "playoff contenders" as probabilities | Same | The same. Until then, list contenders by strength ordering only, without probabilities |
| Alliance synergy (M9) as predictive | Never tested against outcomes | A backtest of synergy vs alliance playoff results (needs P2) |
| Pre-event M5 v2 ordering | Below raw EPA at the pre-event snapshot | — (use raw EPA) |
| Feeding ratings | No feeding data at collection time | Phase 3 M14 |
| Live-refreshed EPA accuracy | Never evaluated: D18 is a fixed snapshot | P1's spec plus a replay check |
| Any new statistic | — | Its own evaluation before it is labelled validated |

## 3. Suggested Phase 5 milestone order

1. P5-M1: P1, P2.
2. P5-M2: P5-C (strength views).
3. P5-M3: P5-A (event analysis).
4. P5-M4: P5-B (qualification forecasts).
5. P5-M5: P5-G (in-season loop; done-means 2).
6. P5-M6: P5-F (meta tracking).
7. P5-M7: P5-D and P5-E (pre-season; done-means 1, with its dry run).
8. P5-M8: docs, contract tests and sign-off.

Each data-backed milestone closes on a replay or backtest with numbers recorded before acceptance, as in Phase 4.
