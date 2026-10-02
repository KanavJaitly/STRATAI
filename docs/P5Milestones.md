Phase 5 — Pre-Season & In-Season Intelligence: Milestone Specification

Status: **PROPOSED (revision 3, 2026-10-02) — EPA decisions resolved, consistency review applied, robot-design dataset audit incorporated (P5-D10); awaiting Kanav's freeze approval.** The P5-M0 approval commit is the freeze point. After it, methodology and acceptance criteria change only by a recorded decision made **before the affected result exists**. Decisions: `.agent/phase5/P5_M0_DECISIONS.md`.

Source: `docs/ROADMAP.md` Phase 5. The Phase 4 contracts are as they stand (`docs/ml_models.md`):
- Phase 4 evaluation complete; acceptance criteria not fully met (M7 FAILED; done-means NOT MET);
- M5 v2 accepted;
- production serves the D18 models and source.

---

## Phase 5 done-means (immutable)

Phase 5 is complete only when **both** hold. Neither may be redefined, weakened or removed.

### DM1 — pre-season / game-analysis pipeline

The pre-season pipeline runs **end-to-end within 5 days of a game reveal**, demonstrated by a dry run against a historical game reveal.
- **End-to-end** means one run of the intended pipeline, all of it built before the simulated reveal:
  1. game-spec entry;
  2. game analysis;
  3. historical game/mechanism comparison;
  4. archetype analysis (strengths/weaknesses, and expected success only where evidence supports it);
  5. team-specific design recommendations.
- It produces its documented outputs. Components merely executing separately does not count.
- **The 5-day clock** starts when spec entry begins (the simulated reveal) and stops when the documented outputs are complete.

### DM2 — in-season learning loop

Ratings **visibly update as new matches flow in**, without manual retraining. New match data causes the appropriate ratings, features and forecasts to update through the designed pipeline.

**How it is demonstrated.**
- Real mid-season 2026 events are replayed match by match.
- Each result enters through the **production ingestion path** (raw landing → staging → canonical load) into an isolated, non-serving database.
- The **production serving path** then shows the affected ratings and forecasts updating after each match, with provenance and no retraining (P5-M6 criteria a–e).
- Components exercised separately, or test-only shortcuts, do not count.

**A live confirmation is not required by the original requirement.** A confirmation at the first live official events (2027 Week 0/1) is a recommended operational follow-up. It is **not** a Phase 5 done-means gate (P5-D8, revised).

---

## Standing rules (apply to every milestone)

- **No LLM in the core.** Models, statistics and optimization only (CLAUDE.md).
- **Point-in-time:** every feature uses only data strictly before its as_of. Alliance seeds and picks are usable only after alliance selection. Alliance *outcomes* are labels only (`data/alliances.py`).
- **Frozen models:** the D18 artifacts (M5 v2 `ranking_xgb_v2` `1f0fe5aa…`; the M7 pair `win_prob_xgb_calibrated` `c76d3299…`). Updating means new inputs, never retraining. A retrained or new model is a new version with its own frozen spec and single evaluation.
- **EPA provenance:** every output that uses EPA states, per team, `epa_value_source` (`statbotics` / `stratai_fallback` = "STRATAI EPA") and `epa_source_state` (`LIVE_EPA_REFRESH_DESIGN.md` §5). STRATAI never silently replaces Statbotics. An unprocessed Statbotics record is never treated as a valid Statbotics value.
- **Every output carries a `validation_status`**, and any reason it is not validated. Nothing unvalidated is presented as validated.
- **`insufficient_data` propagates.** Absence is never 0.
- **Evaluation discipline:**
  - each metric is computed once, on a pre-stated population;
  - results are recorded write-once with the frame/snapshot hash and commit;
  - D9 applies: stop and escalate on a genuine failure;
  - acceptance criteria are never weakened after a result exists.
- **Tests run against a non-serving database** (`docs/ml_models.md` §9, limitation 6).

## The validated / unvalidated boundary

| Validated (within its documented limits) | Not validated |
|---|---|
| Qualification win probabilities on **EPA-complete** matches: rounded to 0.05 in [0.05, 0.95]; D18 qualification ECE 0.015 | Playoff probabilities |
| M5 v2 orderings at and after each team's mid-qualification point (0.6112 / 0.6314) | Bracket and series odds; playoff-success prediction |
| Raw-EPA orderings, including pre-event (M4 baseline 0.5955) | Pre-event M5 v2 orderings (0.5565 < 0.5955) |
| EPA and Phase 3 strength views with n, uncertainty and provenance (descriptive statistics) | Qualification probabilities on EPA-incomplete matches (never evaluated) |
|  | Alliance synergy (M9) as a predictor |
|  | Feeding ratings (Phase 3 M14 open) |
|  | Live-refreshed EPA: `live_refresh_not_yet_validated` until P5-M2 L6 |
|  | Any archetype/mechanism success rate, performance ranking or effect: the curated design dataset is unverified, elite-only metadata (`.agent/phase5/robot_design_audit/AUDIT.md`) |

- **Moving an item left:** a milestone may move an item to the left column only by meeting its own pre-registered criteria.
- **Live-refreshed inputs:** an output built from live-refreshed inputs keeps its base status and adds `live_refresh_not_yet_validated`.

---

## P5-M0 — Specification freeze

**Inputs:**
- this document;
- `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md`;
- `.agent/phase5/P5_M0_DECISIONS.md`;
- the robot-design dataset audit (`.agent/phase5/robot_design_audit/AUDIT.md`).

**Done-means:**
- an approval commit naming them;
- **zero Phase 5 implementation** in the checkpoint.

## P5-M1 — Alliance and seed data

Ingestion was landed before the freeze, on explicit instruction; acceptance runs after it.

| | |
|---|---|
| **Inputs** | TBA `/event/{key}/alliances` for every canonical 2024–2026 event |
| **Outputs** | Raw payloads (tba / `event_alliances`). `read_event_alliances` gives seed, position, name, captain, picks, backup and declines. `read_event_alliance_outcomes` gives results, as labels |
| **Data dependencies** | canonical `events`, `matches`, `match_teams`; landed final rankings |
| **Evaluation population** | every 2024–2026 event with a non-null alliance payload (606) |
| **Frozen methodology** | Seed = N for "Alliance N" names, which must match list order; partial, duplicate or out-of-order seeds reject the event. Division-champion events (Einstein `*cmptx`; DCMP finals `*micmp` / `*necmp` / `*oncmp` / `*txcmp`; 5 per season) have `seed` = null. Captain = picks[0]. Seeds and picks are known only after alliance selection. **Ingestion facts:** 608 payloads; 606 events with alliances (591 seeded, 15 division-champion); 2026isde3/4 have none (no playoff matches); `backup` is null for all 4,782 alliances (backups unknown) |
| **Acceptance criteria** | (a) Coverage per season: events with alliances / events with playoff matches. (b) Every team appearing in an event's playoff matches is in that event's alliance picks; exceptions are listed (possible backups, since backups are unknown). (c) **Seed–rank consistency**, seeded events only: alliance k's captain is the best-ranked team not on alliances 1..k−1, allowing declines and picks of better-ranked teams; violations are listed. (d) Seed-order rejections are listed (0 at ingestion). A failing criterion is a data finding to report, never a pass |
| **Leakage constraints** | `Alliance` has no outcome attribute (tested); the two readers stay separate |
| **Reproducibility** | Raw-first, deduplicated, idempotent; counts recomputable from `raw_source_payloads` |
| **Done-means** | (a)–(d) recorded with their numbers |

## P5-M2 — Live EPA refresh

| | |
|---|---|
| **Specification** | Exactly `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md` (sources, states, Option A fallback at 72 h, versioning, as_of, provenance, validation) |
| **Acceptance criteria** | L1–L4 pass before adoption, and adoption is a recorded decision (P5-D3). L5–L6 run prospectively in 2027. `live_validated` only after L6 |
| **Done-means** | Implemented to the frozen design; L1–L4 recorded as passed; L5–L6 scheduled. A failure in L1–L4 stops and escalates |

## P5-M3 — Team and robot strength views

| | |
|---|---|
| **Inputs** | team, event, as_of |
| **Outputs** | EPA total and components with `epa_value_source` / `epa_source_state` / source event. Phase 3 metrics (average, SD, consistency, good/average/bad day, reliability) with n. Season-to-date auto points. Defense (scouting; definition decision pending). Feeding labelled `not_validated` |
| **Data dependencies** | assembler (M1); the active EPA provider; `team_metrics`; scouting observations |
| **Evaluation population** | 1,000 appearances sampled once (seed 20261003) from the D18 frame's 2026 rows |
| **Frozen methodology** | Values exactly as the Phase 3/4 functions compute them; no new aggregation or statistic |
| **Acceptance criteria** | Every numeric field has n and its uncertainty (SD, or an explicit "none"). Every EPA value has its provenance. Absent values are null with a reason. Exact equality with the assembler's `TeamFeatures` on the 1,000 sampled appearances |
| **Leakage constraints** | as_of honoured; point-in-time sentinel test |
| **Reproducibility** | Deterministic given as_of, snapshot and commit |
| **Done-means** | Contract tests pass; the equality check is recorded |

## P5-M4 — Event analysis (pre-event and in-event)

| | |
|---|---|
| **Inputs** | event_key; as_of |
| **Outputs** | Attending-team comparison (P5-M3). A predicted qualification ordering under the frozen policy. Captain candidates. "Strongest teams" by ordering **without any playoff probability** (playoff contention stays unvalidated until the playoff track). Every element carries its `validation_status` |
| **Data dependencies** | P5-M3; final rankings and P5-M1 alliances (evaluation only, never inputs) |
| **Evaluation population** | held-out 2026: the 208 events with final ranks (D18); captains: those events with seeded alliances |
| **Frozen methodology** | **Event-level ordering policy.** Raw EPA (`RawEpaRankingBaseline`) until *every* rostered team has played its ⌈n_i/2⌉-th qualification match (the event switch point). M5 v2 from then on. One model per ordering, because the two models' scores are on different scales and cannot be mixed. Captain candidates = top 8 of the ordering |
| **Acceptance criteria** | (a) **Reproduction (exact):** under D18's per-team protocol, raw EPA = 0.5955 and M5 v2 at the midpoint = 0.6112 (`results/d18/m05v2_result.json`). (b) **The served policy is measured once** at the event switch point: Spearman vs final rank for M5 v2 and for raw EPA at the same snapshot, with an event-bootstrap CI of the paired difference. M5 v2 is served after the switch point only if the paired mean difference is > 0; otherwise the policy serves raw EPA throughout, recorded as such. (c) **Captain hit rate** (\|predicted ∩ actual captains\| / 8, averaged over events), at the pre-event and switch-point snapshots, with a CI, next to the raw-EPA baseline. It is labelled `validated_as_measured`; improvement is claimed only if the paired-difference CI excludes 0 |
| **Leakage constraints** | Pre-event snapshots use nothing from the event; rankings and alliances are labels only; point-in-time sentinels |
| **Reproducibility** | Write-once records with the frame hash and commit |
| **Done-means** | (a) exact; (b) and (c) recorded; the endpoint serves only labelled outputs |

## P5-M5 — Qualification match forecasts and expected qualification records

| | |
|---|---|
| **Inputs** | an event's qualification schedule; as_of |
| **Outputs** | Per-match qualification probabilities gated exactly as M12 (validated only for EPA-complete matches). Per-team expected qualification wins with an 80% Poisson-binomial range. `low_confidence` for Statbotics weeks 1–3 |
| **Data dependencies** | the M7 pair; schedule; the active EPA provider |
| **Evaluation population** | held-out 2026 EPA-complete qualification matches: the D18 diagnostic population, 12,245 matches and 7,845 team-events |
| **Frozen methodology** | Expected wins = Σ q over the team's qualification matches. Range = the central 80% of the Poisson-binomial of those q (exact recursion, `ml/calibration/gate.py`). A team-event whose schedule includes an EPA-incomplete match gets its expected record labelled `not_validated`. No ranking-point projection (bonus RPs were never modelled) |
| **Acceptance criteria** | (a) **Reproduction:** mean actual − expected = 0.0000 and mean \|actual − expected\| = 1.1207 (`results/d18/m07_diagnostics.json`, 4 dp). (b) **80% range coverage** measured once: `validated` if within [0.75, 0.85]; otherwise recorded as a failure, with the range served `not_validated` |
| **Leakage constraints** | Qualification only (playoffs refused); features at each match's as_of |
| **Reproducibility** | Write-once records |
| **Done-means** | (a) exact; (b) recorded with its label |

The 80% range inherits M7's limitation: probabilities are not certified calibrated, and (b) tests the range directly.

## P5-M6 — In-season learning loop

| | |
|---|---|
| **Inputs** | live ingestion (`--watch`); P5-M2 snapshots |
| **Outputs** | Ratings and forecasts that change as matches complete, with as_of, `snapshot_id` and provenance. `team_metrics` recomputed during watch (closing the CLAUDE.md constraint-5 gap) |
| **Data dependencies** | P5-M2 (adopted), P5-M3, P5-M4, P5-M5 |
| **Evaluation population** | a replay of six held-out 2026 events, fixed now: the first five 2026 events by event_key that have qualification matches, plus 2026iscmp. Raw match payloads are re-landed chronologically through the production ingestion path into an isolated database. EPA comes from P5-M2's simulated retrieval |
| **Frozen methodology** | No retraining. An update is caused only by a new canonical row or a new snapshot |
| **Acceptance criteria** | (a) After every completed match, the affected teams' served features change exactly as the assembler computes, traced to the new row. (b) Zero changes without a new input. (c) Bit-for-bit reproducible. (d) `team_metrics` equals a fresh recompute after every match. (e) The 2026iscmp replay serves its fallback teams as `fallback_stratai` with provenance |
| **Leakage constraints** | A point-in-time sentinel is inserted mid-replay; no future row is ever visible |
| **Reproducibility** | Replay log (as_of, snapshot_id, STRATAI replay fingerprint, model sha256s, commit) |
| **Done-means** | **DM2**, by the replay above with (a)–(e) passing. A live confirmation at the first 2027 events is recommended, but not a gate |

## P5-M7 — Meta tracking (Week 0/1 onward)

| | |
|---|---|
| **Inputs** | `score_breakdown` per completed match; TBA event week (raw event payload) |
| **Outputs** | Weekly distributions of scoring components (auto, teleop, endgame, fouls) per season. Change-point flags on component shares, with effect sizes. All labelled descriptive |
| **Data dependencies** | season adapters (`ml/features/score_breakdown.py`), extended from auto points to all components |
| **Evaluation population** | all 2024–2026 completed matches with valid breakdowns |
| **Frozen methodology** | Per-season component adapters. The detector is a two-sample test of a component's share, week w vs weeks < w, Holm-corrected across components at α = 0.05, reported with its effect size |
| **Acceptance criteria** | (a) **Adapter parity:** components + fouls + adjustments = official score for 100% of valid rows. (b) **False alarms:** 1,000 within-season week-label permutations give a family-wise flag rate ≤ 0.05, with the 95% Clopper–Pearson upper bound ≤ 0.07. (c) Real 2024–2026 flags recorded descriptively; no accuracy claim |
| **Leakage constraints** | Week w uses only weeks ≤ w |
| **Reproducibility** | Recomputable from raw payloads |
| **Done-means** | (a) and (b) pass; (c) recorded. **Documented gap (P5-D10):** archetype or mechanism meta is not observable from match data, and the curated design dataset has no per-week or per-event labels. Archetype-level Week 0/1 meta needs at-event mechanism labels (e.g. a scouting field), a future data-collection extension outside Phase 5 |

## P5-M8 — Game-rule analysis

| | |
|---|---|
| **Inputs** | A **structured, human-entered game specification** (versioned schema): scoring actions and points by period, endgame, RP rules, field elements, match length. Entered from the game manual only. No LLM parses the manual in the core. **The curated design reference** `data/reference/frc_robot_design_curated.csv` (77 rows, sha256 `40aef139…139e1`), used only as historical design examples (P5-D10) |
| **Outputs** | A scoring-action value table. Similarity to a catalog of past games. Candidate archetypes, with **historical design examples** retrieved from the curated reference by codebook labels, every example labelled `curated_reference_unverified` (no success rate, no performance ranking). Expected scoring ranges derived from catalog seasons with breakdown data (2024–2026) |
| **Data dependencies** | the game-spec catalog; P5-M7 adapters |
| **Evaluation population** | used by DM1's dry run (P5-M9) |
| **Frozen methodology** | Similarity and archetype rules are fixed before the dry run. **Reference taxonomy:** a human, multi-label codebook (a set of functions, and a family per function), frozen before coding; every curated row double-coded independently; micro-archetype text always kept verbatim. Keyword auto-labelling is not used: the audit found 19 of 77 rows (25%) misassigned |
| **Acceptance criteria** | Schema, determinism and catalog-integrity tests. The reference file's sha256 is verified at load. **Codebook agreement:** Cohen's κ on function labels is reported; labels are used as categories only if κ ≥ 0.6, otherwise served as `provisional`. Outputs are `descriptive`, `curated_reference_unverified`, or `not_validated` for any forward-looking claim |
| **Leakage constraints** | In the dry run the catalog **and the curated reference** contain only games and rows from **before** the simulated reveal year. For the 2026 dry run, the 10 REBUILT rows are excluded |
| **Reproducibility** | Spec, catalog and outputs are versioned and hashed |
| **Done-means** | Built and tested; exercised by DM1 |

## P5-M9 — Team capability intake and the DM1 end-to-end dry run

| | |
|---|---|
| **Inputs** | budget, manufacturing, programming and mentor resources (form; raw-first storage); P5-M8 outputs |
| **Outputs** | A realistic robot ceiling, a recommended archetype and achievable features, with an explanation, labelled `heuristic_not_validated_against_outcomes`. It may cite curated historical examples (labelled `curated_reference_unverified`). **The DM1 dry-run record** |
| **Data dependencies** | P5-M8 |
| **Evaluation population** | **The 2026 reveal.** The 2026 game spec is entered from the manual only; the catalog is limited to pre-2026 games; at least 10 sample team profiles, fixed before the dry run |
| **Frozen methodology** | A deterministic, **human-authored capability→archetype feasibility rubric**: the curated dataset has no resource, cost or complexity data, so the rubric is not derived from it. No LLM. Rules fixed before the dry run |
| **Acceptance criteria** | (a) **DM1:** one run from spec entry to every documented output (P5-M8 analysis, comparison and archetypes, plus P5-M9 recommendations for the sample profiles). Elapsed time recorded; it must be ≤ 5 days. (b) Predictions are recorded write-once before any 2026 match data is read, then scored once against 2026 weeks 1–3: predicted vs actual dominant scoring components, and the coverage of expected scoring ranges. Labelled `not_validated` regardless of score, because one game cannot validate a predictive claim. (c) A mentor review of the sample recommendations is recorded |
| **Leakage constraints** | Human input is limited to manual facts. No human judgment step uses knowledge of how 2026 played out. Spec entry is audited against the manual |
| **Reproducibility** | Everything versioned and hashed; the dry run is re-executable |
| **Done-means** | **DM1 met:** (a) within 5 days, with (b) and (c) recorded |

## P5-M10 — Documentation, contract tests and sign-off

**Requirements:**
- `docs/phase5.md` documents every output and its `validation_status`;
- contract tests pin it to code and records;
- `scripts/phase5_done_means.py` reads the records and reports DM1 and DM2.

**Done-means:** DM1 and DM2 recorded with real evidence, or Phase 5 stays open.

---

## Playoff track — roadmap preserved (not built in Phase 5)

**The qualification model is not a playoff model.** D18: the higher seed wins 77.3% of playoff matches against 62.4% predicted. The required sequence:

1. **PX-1 — a playoff-specific model:** an antisymmetric seed-difference feature, alliance composition (P5-M1), bracket position, with its own frozen spec and single run.
2. **PX-2 — playoff-only validation and calibration:** a stratified, playoff-only per-bin test, as in M7.
3. **PX-3 — a bracket and series simulator** on PX-1 probabilities.
4. **PX-4 — validation of the simulator** against real 2024–2026 brackets (P5-M1 outcome labels).
5. **Only then** are playoff, bracket, series or playoff-success probabilities served as validated. M12's playoff gating stays until then.

**Placement (P5-D4):** the track is a **prerequisite of Phase 6 alliance selection**, after Phase 5. It is not part of Phase 5's done-means.

## Order and dependencies

| Milestone | Depends on |
|---|---|
| P5-M0 | — |
| P5-M1 acceptance | P5-M0 |
| P5-M2 | P5-M0 |
| P5-M3 | P5-M0 |
| P5-M4 | P5-M3 (P5-M1 for captain evaluation) |
| P5-M5 | P5-M3 |
| P5-M6 | P5-M2 adopted, P5-M3, P5-M4, P5-M5 |
| P5-M7 | P5-M0 |
| P5-M8 | P5-M7 |
| P5-M9 | P5-M8 |
| P5-M10 | all of the above |
| PX-1 … PX-4 | P5-M1 (in Phase 6) |
