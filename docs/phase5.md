# StratAI Phase 5 — Pre-Season & In-Season Intelligence

The reference for what Phase 5 built, what each output means, and how far each one can be trusted. It is pinned
to the code and the records by `tests/test_phase5_contract.py`.

- **Specification (frozen at P5-M0):** `docs/P5Milestones.md`.
- **Decisions:** `.agent/phase5/P5_M0_DECISIONS.md` (P5-D1 to P5-D14).
- **Evaluation records:** `.agent/phase5/results/`. Each is write-once, with its commit and frame, snapshot or
  population fingerprint.
- **Done-means report:** `python -m scripts.phase5_done_means`. It reads the records only.

Phase 5 builds on the Phase 4 contracts in `docs/ml_models.md`:
- **Models:** the frozen D18 models are consumed, never retrained.
- **Probabilities:** qualification probabilities are validated only on EPA-complete matches.
- **Playoffs:** probabilities are never validated (the playoff track is a Phase 6 prerequisite, P5-D4).

**Verification-runtime rule (CLAUDE.md, permanent):** no verification run may exceed about 45 minutes. Expensive
replays use seeded, stratified samples plus targeted edge cases.

## Status at a glance

| Milestone | Status | Notes |
|---|---|---|
| P5-M1 Alliance and seed data | **accepted** | data findings recorded |
| P5-M2 Live EPA refresh | **accepted, not adopted** | L1–L4 passed; production adoption is a human decision (P5-D3) |
| P5-M3 Strength views | **accepted** | descriptive; EPA provenance on every value |
| P5-M4 Event analysis | **accepted** | the ordering is validated; captain improvement is not claimed |
| P5-M5 Qualification forecasts | **accepted** | the 80% range **failed** its coverage band, so it is served `not_validated` |
| P5-M6 In-season loop | **accepted on (a)–(e)** (labelled rerun) | the first recorded run **failed** on harness defects and is kept |
| P5-M7 Meta tracking | **accepted** | false-alarm check passed; real flags are descriptive |
| P5-M8 Game-rule analysis | built and tested; **blocked by required human input** | rules decided (P5-D13) |
| P5-M9 Capability intake and DM1 | built and tested; **blocked by required human input** | DM1 not run |
| P5-M10 Docs, contracts, sign-off | this page, the contract tests, `scripts/phase5_done_means.py` | |

**Done-means (immutable):**
- **DM1 — NOT MET.** The dry run needs human-authored inputs that may not be simulated (§P5-M9).
- **DM2 — NOT MET.** The P5-M6 replay passed criteria (a)–(e), but P5-M6's declared dependency, *P5-M2
  adopted*, is a pending human decision (P5-D3).

## Labels served

| Label | Meaning |
|---|---|
| `validated` | met its own pre-registered criterion (e.g. the raw-EPA ordering, D18 M4 0.5955) |
| `validated_as_measured` | measured once on a pre-stated population and served with that measurement; no improvement is claimed unless its CI excludes 0 |
| `approximately_calibrated_qualification` | a qualification probability on an EPA-complete match (M12 gating) |
| `descriptive` | a statistic of the data, with no predictive claim |
| `not_validated` | never validated, or its validation failed, with a reason |
| `heuristic_not_validated_against_outcomes` | P5-M9 recommendations from a human-authored rubric |
| `curated_reference_unverified` | a historical design example from the curated reference (P5-D10); no success rate or ranking |
| `provisional` | codebook labels whose κ is below 0.6 (P5-D13) |
| `low_confidence` | a forecast at an event in Statbotics weeks 1–3 |
| `live_refresh_not_yet_validated` | any output using a live-refreshed (non-root) EPA snapshot or a live fallback, until L6 |
| `descriptive_definition_pending` | defense ratings: descriptive, while Phase 3 M14's defense-definition decision is open |

**EPA source states (P5-D2):**
- served: `current`, `stale`, `fallback_stratai` (STRATAI EPA, `fallback_reason` = statbotics_unprocessed_72h);
- refused: `pending` (`epa_source_pending`, 422) and `unavailable` (`epa_source_incomplete`, 422);
- absent: `withheld_no_prior_event` (null with a reason).

**Error codes on Phase 5 endpoints:**
- `event_not_found`, `team_not_found`;
- `epa_source_not_loaded`, `epa_source_incomplete`, `epa_source_pending`;
- `model_not_loaded`;
- `invalid_as_of` (422: a timestamp without an offset is refused).

## P5-M1 — Alliance and seed data

- **Source:** `data/alliances.py` lands TBA `/event/{key}/alliances` raw-first.
- **Readers:** `read_event_alliances` (seeds, picks, declines) and `read_event_alliance_outcomes` (results). They
  are kept apart, because outcomes are **labels only, never features**.
- **Unseeded events:** division-champion events have `seed = null`.
- **Record:** `.agent/phase5/results/p5_m1_alliance_acceptance.json`.

| Check | Result |
|---|---|
| Coverage | 100% of playoff events, all three seasons |
| Playoff participants on no alliance | 5, in 4 events (backups are unknown: TBA records none) |
| Seed–rank violations | 9, in 6 of 591 seeded events. 8 are TBA placeholder teams (`999x`); 1 is a real anomaly (2026milac) |
| Seed-order rejections | 0 |

## P5-M2 — Live EPA refresh (accepted; not adopted)

- **Status:**
  - implemented to `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md`, with A1/A2 semantics from P5-D11 (Q1,
    `.agent/phase5/M02_DECISION_REQUIRED.md`): D18's availability skip is kept;
  - production still serves the frozen D18 source until a recorded adoption decision (P5-D3).
- **Snapshot log:** `ml/ratings/live_snapshots.py`; append-only manifests rooted at the D18 snapshot;
  `snapshot_id` is the manifest's sha256.
- **Provider:** `ml/ratings/live_epa.py`. Every served value names its state, `snapshot_id`, `retrieved_at` and raw
  sha256.
- **Refresh:** `ml/ratings/live_source.py`, `scripts/live_epa_refresh.py`. The `--watch` follow-on triggers it when
  configured. A failed cycle writes no manifest, and the previous snapshot keeps serving, labelled `stale`.
- **Selecting it:** `EPA_SOURCE=p5_live_statbotics` with `LIVE_EPA_LOG_DIR`, `STATBOTICS_SNAPSHOT_DIR`,
  `STRATAI_EPA_CHAIN`, `LIVE_EPA_A1A2_POLICY=d18_skip` and `LIVE_EPA_CONCLUDED_SEASONS`. It reports
  `evaluated_configuration: false`.

| Check | Result |
|---|---|
| L1 equivalence (319,301 appearances) | **passed**: 0 mismatches; 263,726 Statbotics / 450 STRATAI fallback / 55,125 withheld, equal to D18 |
| L2 simulated cadence (6, 24, 72 h lags) | **passed**: 522 / 547 / 1,726 differences, all explained by the lag (pending refusals); 0 values served before availability. Diagnostic at 24 h: M5 v2 midpoint 0.6112, qualification ECE 0.0153 |
| L3 outage drill | **passed** |
| L4 atomicity and re-serve | **passed** (labelled rerun; the first run's sub-check defect is kept on record) |

**L5 and L6** are scheduled for 2027 (value drift via the 14-day sweep; a live shadow evaluation of logged
predictions with the D18 methodology unchanged).

## P5-M3 — Team and robot strength views

- **Endpoint:** `GET /teams/{team_number}/events/{event_key}/strength?as_of=<ISO-8601 with offset>`.
- **Built from:** `ml/views/strength.py`, composing the assembler and Phase 3's statistics. No new statistic, and
  `team_metrics` is never read (a current snapshot would leak past as_of).
- **Every numeric field** has n and an uncertainty (an SD, or `none` with a reason). Absent values are null with a
  reason.
- **Labels:**
  - defense is `descriptive_definition_pending`; feeding is `not_validated`;
  - `reliability_score` carries Phase 3's INTERIM caveat on the endpoint.

| Check (1,000 sampled 2026 appearances) | Result |
|---|---|
| Equality with the assembler's `TeamFeatures` | 0 mismatches |
| n, uncertainty, absent reasons, EPA provenance | 0 failures |

## P5-M4 — Event analysis

- **Endpoint:** `GET /events/{event_key}/analysis?as_of=`.
- **Policy (P5-D6):**
  - raw EPA until every team has played its ⌈n_i/2⌉-th qualification match;
  - M5 v2 from then on;
  - never mixed.
- **Captain candidates and strongest teams** are the ordering's top 8. No playoff probability is served.
- **Record:** `.agent/phase5/results/p5_m4_event_analysis.json`.

| Criterion | Result | Label |
|---|---|---|
| (a) Reproduction | raw EPA 0.5955, M5 v2 midpoint 0.6112: exact | — |
| (b) Ordering at the switch point (208 events) | M5 v2 0.6138 vs raw EPA 0.5955; paired +0.0183, 95% CI [0.0082, 0.0288] | raw EPA `validated`; M5 v2 after the switch `validated_as_measured` |
| (c) Captain hit rate, pre-event | 0.4207 (95% CI 0.4056–0.4357) | `validated_as_measured` |
| (c) Captain hit rate, switch point | 0.4255 vs 0.4207; paired CI [−0.0126, 0.0198]: **no improvement claimed** | `validated_as_measured` |

## P5-M5 — Qualification forecasts and expected records

- **Endpoint:** `GET /events/{event_key}/qualification-forecast?as_of=`. Qualification matches only.
- **Per match:** the frozen M7 pair's q, built at min(as_of, the match's time), gated exactly as M12.
- **Per team:**
  - expected wins = Σ q (to 1 dp);
  - the central 80% Poisson-binomial range;
  - a record label: `not_validated` if any of its matches is EPA-incomplete;
  - a range label;
  - `low_confidence` in Statbotics weeks 1–3.
- **Record:** `.agent/phase5/results/p5_m5_qualification_forecast.json`.

| Criterion | Result |
|---|---|
| (a) Reproduction (12,245 matches, 7,845 team-events) | 0.0000 / 1.1207: exact |
| (b) 80% range coverage, measured once | 0.8532, **outside [0.75, 0.85]: failed**, so the range is served `not_validated`. The criterion is not loosened |

## P5-M6 — In-season learning loop

- **Watch:** `--watch` now recomputes `team_metrics` after every poll that loads rows
  (`data.orchestrator.after_watch_sync`). CLAUDE.md constraint 5's gap (docs/metrics_pipeline.md §9.9) is closed,
  and its prerequisite, quality-issue dedup (§9.10), was closed first.
- **Population** (amended by P5-D14, the 45-minute rule):
  - a seeded (20261006), stratified selection, recorded before any check (`p5_m6_selection.json`, fingerprint
    `24e23b1a…4f48`);
  - the events: 2026iscmp (EPA fallback), 2026nccab (week 0), 2026cur (championship division), 2026vache
    (policy switch) and 2025mawne (DQ / surrogate);
  - 44 checked steps, through the production ingestion path into an isolated database.
- **Records:**
  - `p5_m6_replay.json`: **failed**, 14 problems, all harness defects (`.agent/phase5/M06_RECORDED_RUN_FAILURE.md`).
    Kept unchanged.
  - `p5_m6_replay_rerun1.json`: **passed**, with the approved harness corrections. Its full response log is
    `p5_m6_replay_rerun1_log.json`.

| Criterion (rerun, 32.6 min) | Result |
|---|---|
| (a) Served view = assembler; match count +1, traced to its raw payload | 352 / 352; 264 / 264 |
| (b) No-op re-poll; control teams unchanged without a new input | 44 / 44; 47 / 47 |
| (c) Sampled re-requests identical, under their original EPA settings | 171 / 171 |
| (d) `team_metrics` = fresh recompute | 678 / 678 |
| (e) 2026iscmp fallback teams served `fallback_stratai`, with provenance | 80 / 80 |
| Leakage sentinels (future match row; future scouting observation) | 10 / 10 unchanged |
| Endpoints, including the raw EPA → M5 v2 switch | 8 / 8; 2 / 2 |

## P5-M7 — Meta tracking

- **Components** (`ml/features/score_components.py`): auto, teleop (excluding the endgame), endgame, fouls and
  adjustments, per season, as TBA labels them.
- **Detector** (`ml/meta/weekly.py`, P5-D12, Q2 in `.agent/phase5/M07_DECISION_REQUIRED.md`):
  - the event is the unit;
  - Welch's t-test of week w's events against earlier weeks' events;
  - Holm across the 4 components per (season, week);
  - the effect size is the difference in mean share, in percentage points.
- **Records:** `p5_m7_adapter_parity.json`, `p5_m7_detector.json`.

| Criterion | Result |
|---|---|
| (a) Adapter parity | **106,390 / 106,390** rows |
| (b) False alarms (1,000 permutations, 16,000 families) | rate 0.0436 ≤ 0.05; 95% CP upper 0.0469 ≤ 0.07: **passed** |
| (c) Real 2024–2026 flags | 10 of 16 families flagged (foul share falling, teleop share rising), `descriptive`, no accuracy claim |

**Not observable (P5-D10):** archetype or mechanism meta needs at-event mechanism labels.

## P5-M8 — Game-rule analysis

- **Spec and catalog:** `data/game_spec.py`. A human-entered, versioned schema (including `action_type` and
  `element_type`), catalog sha256 integrity, and a pre-reveal filter.
- **Curated reference:** `data/design_reference.py`, sha256-verified, 77 rows, with verbatim text. Examples are
  `curated_reference_unverified`; the pre-reveal filter excludes the 10 REBUILT rows for 2026.
- **Rules** (P5-D13, Q3 in `.agent/phase5/M08_DECISION_REQUIRED.md`; `ml/gameanalysis/rules_p5d13.py`):
  - similarity: cosine of period shares, plus the Jaccard overlap of field-element types, with no threshold;
  - candidate archetypes from a human action→function map;
  - expected ranges from the most similar catalog season, rescaled per period, `not_validated`;
  - the dominant component by expected median;
  - κ: the pooled gate overall, plus per-function `provisional`;
  - served labels from the consensus coding.
- **Status:** built and tested; **blocked by required human input** (the codebook, two codings and a consensus
  coding, catalog specs, and the action map).

## P5-M9 — Capability intake and the DM1 dry run

- **Capability:** `ml/gameanalysis/capability.py`. Raw-first intake and a deterministic, human-authored rubric.
  Outputs are `heuristic_not_validated_against_outcomes`.
- **DM1 runner:** `scripts/phase5_dm1_dry_run.py`.
  - `run` records predictions before any 2026 match data is read, timed from the 2026 spec's `entry_started_at`.
  - `score` runs once against competition weeks 1–3 (TBA weeks 0–2) and is `not_validated`.
  - `mentor-review` records the human review.
- **Blocked by required human input.** None of these may be authored by an AI; AI knowledge of 2026 is hindsight
  leakage (P5-D7).
  1. The 2026 game spec, entered from the manual by a person. This starts the 5-day clock.
  2. The pre-2026 catalog specs.
  3. The codebook.
  4. Two independent codings, then the consensus coding.
  5. The action-type → function map.
  6. The feasibility rubric.
  7. At least 10 sample team profiles.
  8. The mentor review.

## P5-M10 — Documentation, contracts and sign-off

- **This page:** pinned by `tests/test_phase5_contract.py`, which checks:
  - endpoints, labels and error codes;
  - every record's provenance;
  - the numbers above against the records;
  - the pinned serving decisions against their records.
- **`scripts/phase5_done_means.py`:** reports DM1 and DM2 from the records alone.
- **Phase acceptance:** `.agent/phase5/PHASE_ACCEPTANCE.md`.
