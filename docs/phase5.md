# StratAI Phase 5 — Pre-Season & In-Season Intelligence

The reference for what Phase 5 built, what each output means, and how far each one can be trusted.

- **Specification (frozen at P5-M0):** `docs/P5Milestones.md`.
- **Decisions:** `.agent/phase5/P5_M0_DECISIONS.md`.
- **Evaluation records (write-once, with commit provenance):** `.agent/phase5/results/`.

Phase 5 builds on the Phase 4 contracts in `docs/ml_models.md`:
- **Models:** the frozen D18 models are consumed, never retrained.
- **Probabilities:** qualification probabilities are validated only on EPA-complete matches.
- **Playoffs:** probabilities are never validated (the playoff track is a Phase 6 prerequisite).

## P5-M1 — Alliance and seed data

- **Source:** `data/alliances.py` lands TBA `/event/{key}/alliances` raw-first.
- **Readers:** `read_event_alliances` (seed, position, name, captain, picks, backup, declines) and `read_event_alliance_outcomes` (playoff results). They are kept apart, because outcomes are **labels only, never features**.
- **When usable:** seeds and picks are known only after alliance selection.
- **Unseeded events:** division-champion events (Einstein and the multi-division DCMP finals) have `seed = null`.
- **Quality checks:** `data/alliance_checks.py`; the recorded result is `.agent/phase5/results/p5_m1_alliance_acceptance.json`.

| Check | Result |
|---|---|
| Coverage | 100% of playoff events, all three seasons |
| Playoff participants on no alliance | 5, in 4 events (backups are unknown: TBA records none) |
| Seed–rank violations | 9, in 6 of 591 seeded events. 8 are TBA placeholder teams (`999x`); 1 is a real anomaly (2026milac) |
| Seed-order rejections | 0 |

## P5-M3 — Team and robot strength views

- **Endpoint:** `GET /teams/{team_number}/events/{event_key}/strength?as_of=<ISO-8601 with offset>` (default: now). Errors: `event_not_found`, `team_not_found`, `epa_source_not_loaded`, `epa_source_incomplete`, `invalid_as_of` (422; a timestamp without an offset is refused).
- **Built from:** `ml/views/strength.py`, composing the assembler's `build_team_features` and Phase 3's `classify_match_days`. No new statistic. `team_metrics` is not read, because it is a current snapshot and would leak past `as_of`.
- **Every numeric field** is a `Measure`: value, n, and an uncertainty (an SD, or `none` with a reason). An absent value is null with a reason.
- **EPA:** carries `epa_value_source`, `epa_source_state` (P5-D2: `current`, `stale`, `fallback_stratai`, or `withheld_no_prior_event` when absent) and its source event.
- **Auto points:** the current event, plus the season's earlier events listed one by one (never pooled).
- **Defense:** `definition_pending` (the Phase 3 M14 product decision is open). **Feeding:** `not_validated` (no feeding field is collected at scout time).

| Check (1,000 sampled 2026 appearances, D18 source) | Result |
|---|---|
| Exact equality with the assembler's `TeamFeatures` | 0 mismatches |
| n, uncertainty, absent reasons, EPA provenance | 0 failures |
| Equality with the D18 frame's own features | 0 mismatches |
| EPA source states seen | current 963, withheld 33, fallback_stratai 4 |

## P5-M2 — Live EPA refresh (built; not adopted)

- **Status:** implemented to `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md`. Production still serves the frozen D18 source (P5-D3).
- **Open decision Q1** (`.agent/phase5/M02_DECISION_REQUIRED.md`): the design's §3.5 and its L1 criterion disagree about D18's A1/A2 availability skip (1,817 of 319,301 appearances). L1 and L2 run only after it is decided.
- **Snapshot log** (`ml/ratings/live_snapshots.py`):
  - append-only manifests, rooted at the D18 snapshot;
  - each refresh writes the parent manifest plus its changed events;
  - `snapshot_id` is the manifest's sha256.
- **Provider** (`ml/ratings/live_epa.py`):
  - every served value names its `epa_source_state`, `snapshot_id`, `retrieved_at` and raw sha256;
  - a STRATAI fallback also names its `fallback_reason` and replay.
- **Refusals:**
  - `pending` → `epa_source_pending` (422);
  - `unavailable` → `epa_source_incomplete` (422);
  - an older event is never substituted.
- **Refresh** (`ml/ratings/live_source.py`, `scripts/live_epa_refresh.py`):
  - fetch, then raw file, Phase 2 landing, the S1 check, and a manifest;
  - a failed cycle writes no manifest, and the previous snapshot keeps serving, labelled `stale`.
  - **Warning:** refreshing changes `team_event_stats`, after which the D18 loader refuses that database. Never run it against the serving database before adoption.
- **Selecting it:** `EPA_SOURCE=p5_live_statbotics` with `LIVE_EPA_LOG_DIR`, `STATBOTICS_SNAPSHOT_DIR`, `STRATAI_EPA_CHAIN`, `LIVE_EPA_A1A2_POLICY` (Q1) and `LIVE_EPA_CONCLUDED_SEASONS`. It reports `evaluated_configuration: false` and `live_refresh_not_yet_validated`.

| Check | Result |
|---|---|
| L1 equivalence with D18 | not run (waits for Q1) |
| L2 simulated cadence | not run (waits for Q1) |
| L3 outage drill (injected 503s and timeouts) | **passed**: pending → fallback_stratai → current; stale while failing; no manifest from a failed refresh |
| L4 atomicity (2026iscmp, 24 h lag) | **passed** on the labelled rerun (the first run's only failure was a defect in an extra sub-check) |
| Root equals D18 (24,022 values; T_w1, T_end) | passed (test) |

**L5 and L6, scheduled for 2027:**
- **L5:** the daily sweep re-fetches events for 14 days, so value drift is measurable from the log.
- **L6:** log every qualification prediction from 2027 week 1 (`ml/ratings/prediction_log.py`). After the 2027 qualification season, apply the D18 methodology unchanged to the logged EPA-complete predictions.

## P5-M4 — Event analysis

- **Endpoint:** `GET /events/{event_key}/analysis?as_of=`.
- **Ordering policy (P5-D6, measured once):**
  - Raw EPA until every rostered team has played its ⌈n_i/2⌉-th qualification match (the event switch point).
  - M5 v2 from then on.
  - Never a mix of the two.
- **What the response contains:**
  - the ordering;
  - captain candidates (its top 8);
  - strongest teams (the same top 8, with no playoff probability);
  - each attending team's strength view (P5-M3, descriptive).
- **Record:** `.agent/phase5/results/p5_m4_event_analysis.json` (commit 4cc3792).

| Criterion | Result | Label |
|---|---|---|
| (a) Reproduction | raw EPA 0.5955, M5 v2 midpoint 0.6112: exact | — |
| (b) Ordering at the switch point (208 events) | M5 v2 0.6138 vs raw EPA 0.5955; paired +0.0183, 95% CI [0.0082, 0.0288]. M5 v2 is served after the switch | raw EPA `validated`; M5 v2 after the switch `validated_as_measured` |
| (c) Captain hit rate, pre-event | 0.4207 (95% CI 0.4056–0.4357) | `validated_as_measured` |
| (c) Captain hit rate, switch point | 0.4255 vs raw EPA 0.4207; paired CI [−0.0126, 0.0198]. **No improvement claimed** | `validated_as_measured` |
