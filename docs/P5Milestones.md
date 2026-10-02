Phase 5 — Pre-Season & In-Season Intelligence: Milestone Specification

Status: **PROPOSED, 2026-10-02 — awaiting Kanav's approval. Nothing below is implemented.** The commit that records approval is the freeze point. After it, methodology and acceptance criteria change only by a recorded decision made before the affected result exists.

Source: `docs/ROADMAP.md` Phase 5. The Phase 4 contracts are as they actually stand (`docs/ml_models.md`):
- Phase 4 evaluation complete; acceptance criteria not fully met (M7 FAILED);
- M5 v2 accepted;
- production serves the D18 models and source.

**Roadmap done-means:**
1. The pre-season module runs end-to-end within 5 days of a game reveal, dry-run against a past season's reveal.
2. Mid-season, the ratings visibly update as new matches flow in.

---

## Standing rules (apply to every milestone)

- **No LLM in the core.** Models, statistics and optimization only (CLAUDE.md).
- **Point-in-time:** every feature uses only data strictly before its as_of. Alliance seeds and picks are usable only after alliance selection. Alliance *outcomes* are labels only (`data/alliances.py`).
- **Frozen models:** the D18 artifacts (M5 v2 `ranking_xgb_v2` `1f0fe5aa…`; the M7 pair `win_prob_xgb_calibrated` `c76d3299…`). Updating means new inputs, never retraining. A retrained or new model is a new version with its own frozen spec and single evaluation.
- **Every output carries a `validation_status`.** Nothing unvalidated is presented as validated.
- **`insufficient_data` propagates.** Absence is never 0.
- **Evaluation discipline:**
  - each metric is computed once, on a pre-stated population;
  - results are recorded write-once with the frame/snapshot hash and commit;
  - D9 applies: stop and escalate on a genuine failure; never change methodology after seeing a result.
- **Tests run against a non-serving database** (`docs/ml_models.md` §9, limitation 6).

## The validated / unvalidated boundary (unchanged from Phase 4)

| Validated (within its documented limits) | Not validated |
|---|---|
| Qualification-level win probabilities: rounded to 0.05 in [0.05, 0.95]; D18 qualification ECE 0.015 | Playoff probabilities |
| M5 v2 orderings at and after each team's mid-qualification point (0.6112 / 0.6314) | Bracket and series odds; playoff-success prediction |
| Raw-EPA orderings, including pre-event (M4 baseline 0.5955) | Pre-event M5 v2 orderings (0.5565 < 0.5955) |
| EPA and Phase 3 strength views with n, uncertainty and provenance | Alliance synergy (M9) as a predictor |
|  | Feeding ratings (Phase 3 M14 open) |
|  | Live-refreshed EPA (until P5-M2's L1–L4 pass, and `live_validated` after L6) |

A Phase 5 milestone may move an item to the left column only by meeting its own pre-registered acceptance criteria below.

---

## P5-M0 — Specification freeze

- **Inputs / outputs:** this document and `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md`, approved, with the open decisions resolved (the fallback option; thresholds).
- **Done-means:** an approval commit naming both documents. No Phase 5 module code is merged before it.

## P5-M1 — Alliance and seed data (ingestion landed 2026-10-02; acceptance pending)

| | |
|---|---|
| **Inputs** | TBA `/event/{key}/alliances` for every canonical 2024–2026 event |
| **Outputs** | Raw payloads (tba / `event_alliances`). `read_event_alliances` gives seed, captain, picks, backup and declines. `read_event_alliance_outcomes` gives results, as labels |
| **Data dependencies** | canonical `events`; landed final rankings |
| **Evaluation population** | every 2024–2026 event with a non-null alliance payload |
| **Frozen methodology** | Seed = N for alliances named "Alliance N", which must match list order; partial, duplicate or out-of-order seeds reject the event. Division-champion events (Einstein `*cmptx` and the multi-division DCMP finals `*micmp` / `*necmp` / `*oncmp` / `*txcmp`; 5 per season) have `seed` = null, with list position kept but not a seed. Captain = picks[0]. Seeds and picks are known only after alliance selection. **Ingestion facts (2026-10-02):** 608 payloads landed; 606 events with alliances (591 seeded, 15 division-champion); `2026isde3` and `2026isde4` have none (no canonical playoff matches); TBA's `backup` field is null for all 4,782 alliances, so backup robots are unknown |
| **Acceptance criteria** | (a) Coverage is reported per season: events with alliances / events with playoff matches. (b) Every playoff-match team appears on exactly one alliance of its event, or as that alliance's backup; per-event exceptions are listed. (c) **Seed–rank consistency:** for each alliance k, its captain is the best-ranked team not already on alliances 1..k−1 at that point, allowing declines; violations are listed. (d) No payload is rejected by the seed-order check, or each rejection is listed. A criterion that fails is a data finding to report, not a pass |
| **Leakage constraints** | Outcome fields never reach a feature: a test asserts `Alliance` has no outcome attribute and that readers stay separate |
| **Reproducibility** | Raw-first and deduplicated; re-sync is idempotent; the counts above are recomputable from `raw_source_payloads` |
| **Done-means** | Ingestion is landed for 2024–2026, and criteria (a)–(d) are recorded with their numbers |

## P5-M2 — Live EPA refresh

| | |
|---|---|
| **Inputs / outputs / everything** | Exactly `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md` once frozen |
| **Acceptance criteria** | Historical checks L1–L4 pass before any live use. L5–L6 run prospectively in 2027. Until L6 passes, live-refreshed outputs carry `live_refresh_not_yet_validated` |
| **Done-means** | The provider is implemented to the frozen design; L1–L4 are recorded as passed; the prospective L5–L6 protocol is scheduled. L1–L4 failing means stop and escalate |

## P5-M3 — Team and robot strength views

| | |
|---|---|
| **Inputs** | team, event, as_of |
| **Outputs** | EPA total and components with per-value provenance; Phase 3 metrics (average, SD, consistency, good/average/bad day, reliability) with n; season-to-date auto points; defense (scouting, signed-off definition pending); feeding labelled `not_validated` |
| **Data dependencies** | the assembler (M1); the D18 source; `team_metrics`; scouting observations |
| **Evaluation population** | none: no new statistic is introduced. Contract-level only |
| **Frozen methodology** | Values exactly as the Phase 3/4 functions compute them; no new aggregation |
| **Acceptance criteria** | Every numeric field has its n and its uncertainty (SD, or a stated "none"). Every EPA value has `epa_value_source` and its source event. An absent value is null with a reason. The values equal the assembler's `TeamFeatures` for 1,000 sampled 2026 appearances (exact) |
| **Leakage constraints** | as_of honoured; point-in-time sentinel test |
| **Reproducibility** | Deterministic given as_of, snapshot and commit |
| **Done-means** | The endpoint and contract tests pass; the 1,000-appearance equality check is recorded |

## P5-M4 — Event analysis (pre-event and in-event)

| | |
|---|---|
| **Inputs** | event_key; as_of |
| **Outputs** | Attending-team comparison (P5-M3 payloads). Predicted qualification ordering under the frozen policy below. Captain candidates (top 8 of the ordering, with declines not modelled). "Strongest teams" listed by ordering **without any playoff probability**. Every element carries its `validation_status` |
| **Data dependencies** | P5-M3; final rankings; P5-M1 alliances, for evaluation |
| **Evaluation population** | held-out 2026: the 208 events with final ranks (as D18); for captains, the 2026 events with alliances (P5-M1) |
| **Frozen methodology** | **Ordering policy:** raw EPA (`RawEpaRankingBaseline`) for every team before its ⌈n/2⌉-th qualification match; M5 v2 from that match onward; both shown in between. This follows directly from D18: pre-event M5 v2 0.5565 < raw EPA 0.5955; midpoint 0.6112 > 0.5955. Captain candidates = top 8 of the ordering at the evaluated snapshot |
| **Acceptance criteria** | (a) **Reproduction:** on the D18 frame, the policy's ordering reproduces the recorded numbers exactly (raw EPA 0.5955 pre-event; M5 v2 0.6112 at the midpoint). (b) **Captain hit rate** — mean of \|predicted ∩ actual captains\| / 8 over events, at the pre-event and midpoint snapshots, with an event-bootstrap 95% CI — is measured once and recorded next to the raw-EPA top-8 baseline. It is labelled `validated_as_measured`. An improvement over the baseline is claimed only if the CI of the paired difference excludes 0 |
| **Leakage constraints** | Pre-event snapshots use nothing from the event; captains are evaluated against alliances that are never inputs; point-in-time sentinel tests |
| **Reproducibility** | Write-once result records with the frame hash and commit |
| **Done-means** | (a) is exact; (b) is recorded with its CI; the endpoint serves only labelled outputs |

## P5-M5 — Qualification match forecasts and expected qualification records

| | |
|---|---|
| **Inputs** | an event's qualification schedule; as_of |
| **Outputs** | Per-match qualification probabilities, rounded and gated as in M12. Per-team expected qualification wins, with an 80% Poisson-binomial range from the per-match q. A `low_confidence` label for Statbotics weeks 1–3 |
| **Data dependencies** | the M7 pair (served); schedule; D18 source |
| **Evaluation population** | held-out 2026 EPA-complete qualification matches (the D18 diagnostic population: 12,245 matches, 7,845 team-events) |
| **Frozen methodology** | Expected wins = Σ q over the team's qualification matches. Range = the central 80% of the Poisson-binomial over those q (the exact recursion in `ml/calibration/gate.py`). Ranking-point projection is excluded: bonus RPs were never modelled |
| **Acceptance criteria** | (a) **Reproduction:** mean actual − expected = 0.0000 and mean \|actual − expected\| = 1.1207, matching `results/d18/m07_diagnostics.json`. (b) **Range coverage** — the share of team-events whose actual wins fall inside the 80% range — is measured once. Labelled `validated` if coverage is within [0.75, 0.85]; otherwise recorded as a failure, with the range served as `not_validated` |
| **Leakage constraints** | Only qualification matches are accepted (playoffs refused); features at each match's as_of |
| **Reproducibility** | Write-once records |
| **Done-means** | (a) is exact; (b) is recorded with its pass/fail label |

## P5-M6 — In-season learning loop

| | |
|---|---|
| **Inputs** | the live sync (`--watch`); P5-M2 refreshed snapshots |
| **Outputs** | Ratings and forecasts that change as matches complete, each with as_of, `snapshot_id` and provenance; `team_metrics` recomputed during watch (closing the CLAUDE.md constraint-5 gap) |
| **Data dependencies** | P5-M2; P5-M3/M4/M5 |
| **Evaluation population** | a match-by-match replay of five held-out 2026 events (chosen before running: the first five 2026 events by key, plus 2026iscmp), under P5-M2's simulated retrieval |
| **Frozen methodology** | No retraining. An update is caused only by a new canonical match row or a new snapshot |
| **Acceptance criteria** | (a) After every completed match, the affected teams' served features change exactly as the assembler computes, and the change is traced to the new row. (b) Zero changes without a new input. (c) The replay is bit-for-bit reproducible. (d) `team_metrics` equals a fresh recompute after every match |
| **Leakage constraints** | Point-in-time sentinel inserted mid-replay; no future row is ever visible |
| **Reproducibility** | Replay log of (as_of, snapshot_id, model sha256s, commit) |
| **Done-means** | Roadmap done-means 2, demonstrated by replay: ratings visibly update after each completed match with provenance, and (a)–(d) pass. A *live* demonstration needs the 2027 season, through P5-M2's L6 |

## P5-M7 — Meta tracking (Week 0/1 onward)

| | |
|---|---|
| **Inputs** | `score_breakdown` per completed match |
| **Outputs** | Weekly distributions of scoring components (auto, teleop, endgame, fouls) per season. A change-point flag on component shares. Labelled descriptive, not predictive |
| **Data dependencies** | season adapters (`ml/features/score_breakdown.py`), extended from auto points to all components |
| **Evaluation population** | all 2024–2026 completed matches with valid breakdowns |
| **Frozen methodology** | Component adapters per season. The detector is a two-sample test of component share, week w vs weeks < w, Holm-corrected across components at α = 0.05 |
| **Acceptance criteria** | (a) **Adapter parity:** components + fouls + adjustments = official score for 100% of valid rows (as D12 verified for auto). (b) **False-alarm rate:** 1,000 within-season week-label permutations give a family-wise flag rate ≤ 0.05 (95% Clopper–Pearson upper bound ≤ 0.07). (c) Flags on the real 2024–2026 sequences are recorded descriptively; there is no ground truth, so no accuracy claim |
| **Leakage constraints** | Week w uses only weeks ≤ w |
| **Reproducibility** | Recomputable from raw payloads |
| **Done-means** | (a) and (b) pass; (c) is recorded. "Underperforming concepts" is limited to scoring components: no robot-design data exists |

## P5-M8 — Game-rule analysis (pre-season)

| | |
|---|---|
| **Inputs** | A **structured, human-entered game specification**: scoring actions and points by period, endgame, RP rules, field elements, match length. The schema is versioned. No LLM parses the manual in the core |
| **Outputs** | A scoring-action value table; similarity to a catalog of past games; enumerated candidate archetypes, with expected scoring ranges derived from the catalog |
| **Data dependencies** | the game-spec catalog (2024–2026 have real breakdown data; earlier games are catalog-only); P5-M7 adapters |
| **Evaluation population** | dry run against the 2026 reveal: the 2026 spec entered from the manual only, with the catalog limited to games before 2026 |
| **Frozen methodology** | Similarity and archetype enumeration rules fixed before the dry run. Predictions are recorded (write-once) before any 2026 match data is read |
| **Acceptance criteria** | (a) The pipeline runs end-to-end from spec entry to outputs, with the elapsed working time recorded (the roadmap requires ≤ 5 days). (b) Predictions are scored once against 2026 weeks 1–3: the predicted vs actual dominant scoring components, and the archetype expected-range coverage. Recorded and labelled `not_validated` unless a pre-stated bar is met (to be fixed at P5-M0) |
| **Leakage constraints** | The dry run cannot read 2026 match data before its predictions are recorded |
| **Reproducibility** | Spec, catalog and outputs are versioned and hashed |
| **Done-means** | Roadmap done-means 1: the dry run completes within 5 days, with predictions recorded and scored |

## P5-M9 — Team capability intake

| | |
|---|---|
| **Inputs** | budget, manufacturing, programming and mentor resources (form; raw-first storage) |
| **Outputs** | A realistic robot ceiling, a recommended archetype and achievable features, with an explanation, all labelled `heuristic_not_validated_against_outcomes` |
| **Data dependencies** | P5-M8 archetypes |
| **Evaluation population** | none: there is no outcome ground truth |
| **Frozen methodology** | A documented, deterministic rule mapping; no LLM |
| **Acceptance criteria** | Determinism and schema tests; a mentor review of at least 10 sample profiles, recorded |
| **Leakage constraints** | n/a |
| **Reproducibility** | The same inputs and rule version give the same output |
| **Done-means** | Rules are documented, tests pass, and the review is recorded |

## P5-M10 — Documentation, contract tests and sign-off

**Requirements:**
- `docs/phase5.md` documents every module, its `validation_status` values and its numbers;
- contract tests pin them to the code and records;
- a done-means check reads the records, as Phase 4's `scripts/phase4_done_means.py` does.

**Done-means:** both roadmap done-means are recorded with real numbers, or Phase 5 stays open.

---

## Playoff track — roadmap preserved (specified later; not built in Phase 5)

**The qualification model is not a playoff model.** D18 found that the higher seed wins 77.3% of playoff matches against the 62.4% predicted. Phase 6 alliance selection must optimize playoff win probability, so this track must come first, in order:

1. **PX-1 — Playoff model.**
   - A new model with playoff context: an antisymmetric seed-difference feature, alliance composition (captain and picks from P5-M1), and bracket position.
   - Its own frozen spec, D7-style temporal split and single run.
   - A **stratified** calibration criterion, playoff-only, with M7's per-bin test.
2. **PX-2 — Bracket and series simulator.**
   - Built on PX-1 probabilities only, after PX-1 passes.
   - Validated against real 2024–2026 bracket outcomes (P5-M1 outcome labels) for series and alliance-advancement calibration.
3. **Until both pass:** no playoff, series, bracket or playoff-success probability is served as validated. M12's playoff gating stays.

Placement (late Phase 5 or start of Phase 6) is a decision for P5-M0.

## Order and dependencies

| Milestone | Depends on |
|---|---|
| P5-M0 | — |
| P5-M1 | P5-M0 |
| P5-M2 | P5-M0 |
| P5-M3 | P5-M0 |
| P5-M4 | P5-M3 (and P5-M1 for captains) |
| P5-M5 | P5-M3 |
| P5-M6 | P5-M2, P5-M3, P5-M4, P5-M5 |
| P5-M7 | P5-M0 |
| P5-M8 | P5-M7 |
| P5-M9 | P5-M8 |
| P5-M10 | all of the above |
| PX | P5-M1 |
