# StratAI ML Models (Phase 4)

This page is the reference for STRATAI's Phase 4 ML layer: features, dataset, backtest method, models, calibration, guarantees, evaluated results, and what is and is not trustworthy. `tests/test_ml_models_docs_contract.py` pins every feature name, constant, endpoint, exclusion rule and frozen number quoted here to the live code and the write-once result records.

**Status: Phase 4 evaluation complete; acceptance criteria not fully met. Phase 4's done-means is NOT MET.**
- Ranking beats the naive baseline: **MET**.
- Win probability calibrated: **NOT MET** (M7 failed).

`python -m scripts.phase4_done_means` reads the records and reports this. The evaluation is complete, so what can and cannot be trusted is known (§10).

**In short:**
- **Ranking:** performance is moderate and not guaranteed.
- **Qualification win probabilities:** reasonably calibrated within the tested population (2026, held out).
- **Playoff probabilities:** NOT currently validated. The higher-seed playoff effect is a known systematic limitation (§7).
- **Precision:** unsupported statistics must not be presented with false precision.

**D18 is the evaluated production-source configuration.** The production API serves exactly the D18 models and EPA source (§9).

---

## 1. Source version of record: D18

Every number on this page is from the **D18** controlled run. The spec is `.agent/phase4/D18_SOURCE_SPEC.md`, frozen at `ec1b0af` before any D18 data or metric existed.

**EPA source**
- Statbotics team-event EPA, from the cached, checksum-verified snapshot `statbotics_snapshot_20261001T220423Z` (608 events, 24,022 rows; endpoint `/v3/team_events?event=<key>`).
- For appearances whose target event is `2026iscmp` only, STRATAI's own EPA is used, labelled `stratai_fallback`, because Statbotics never processed the 2026 Israeli events. Exactly 450 appearances.

**Selection (D13).** Among the team's other events whose end date and whose last completed match for the team are both before `as_of`, take:
1. the latest end date;
2. then the latest completed match;
3. then event_key ascending.

A missing or invalid Statbotics row for a candidate is a hard error. There is never a silent step to an older event.

**Availability.** A value is used only when `available_at < as_of`; otherwise the next candidate is considered.
- **A1:** `record.qual.count = 0` marks a season-end value, available only after the season's last completed match.
- **A2:** otherwise, available after the team's last match there and after week-1 statistics are complete.

**Provenance.** Every team appearance records `epa_value_source` (`statbotics`, `stratai_fallback`, or none when withheld).

**Verified before any metric** (`.agent/phase4/results/d18/source_verification.json`):
- snapshot integrity;
- fallback scope 450/450;
- 0 hard errors;
- 0/6,000 selection mismatches;
- 0 leakage.

**D15 (STRATAI EPA throughout)** is the preserved historical comparison (`.agent/phase4/results/m0*_result.json`).

## 2. Features

`ml/features/assembler.py` builds `TeamFeatures` from data strictly before `as_of`. Every optional value has a presence flag, and nothing is imputed.

- `epa_total`, `epa_auto`, `epa_teleop`, `epa_endgame` — prior-event EPA (§1); absent with `epa_withheld_reason`.
- `average_score`, `score_stddev`, `consistency_rating`, `reliability_score` — the team's completed matches at this event before `as_of` (Phase 3 statistics).
- `average_auto_points` — mean auto points from the season's score breakdown (`ml/features/score_breakdown.py`; an unknown season raises `UnsupportedSeasonError`).
- `matches_considered`, `matches_used` — counts.
- `defense_score`, `defense_agreement`, `defense_observation_count`, `feeding_score`, `feeding_agreement`, `feeding_observation_count` — scouting only. Never inferred from scoring; absent when observations are insufficient.
- `score_scale`, `epa_scale` — D16's causal season scale S(Y, t): the population SD of the season's alliance scores before t. It needs at least `MIN_ALLIANCE_SCORES` = 200 scores.

**M6's input** is `TEAM_FEATURE_NAMES` (the 17 names above, excluding the scales), summed per alliance, red then blue.

**M5 v2's input** is `FEATURE_NAMES_V2`:
- `epa_total_norm`, `epa_auto_norm`, `epa_teleop_norm`, `epa_endgame_norm`, `average_score_norm`, `score_stddev_norm` and `average_auto_points_norm` are the game-point features divided by the causal scale;
- the remaining names are unchanged.

## 3. Dataset (M2)

`ml/dataset/builder.py` produces one row per completed match: label `red_win` / `blue_win` / `tie`, score margin, and the scheduled time.

**Exclusion reasons:**
- `no_scheduled_time`
- `unplayed`
- `winning_alliance_missing`
- `dq_affected`
- `dq_status_unknown`

Ties, surrogates and playoff matches are kept and tagged.

**The D18 frame** (`ab1adbf3…`) has 52,469 rows. It excluded 726 `dq_affected` and 25 `unplayed`.

## 4. Backtest method (M3)

- **Split (D7):** train 2024 + 2025, held-out 2026, strict temporal order (`ml/backtest/harness.py`).
- **Win-prob population:** EPA-complete rows (all six teams have EPA): 19,780 train / 15,061 held-out, with 34 ties excluded from scoring.
- **Ranking ground truth:** real 2026 final qualification ranks (208 events).
- **M5 v2 decision point:** each team's ⌈n/2⌉-th qualification match (`ml/backtest/ranking_midpoint.py`). No playoff or post-qualification information is used.

## 5. Results (held-out 2026, D18)

Every row is a single, write-once run with its frame hash and commit, recorded in `.agent/phase4/results/d18/`.

| Milestone | Metric | D18 | D15 (history) | Result |
|---|---|---|---|---|
| M4 baseline (frozen bar) | win-prob log-loss / Brier | **0.6707 / 0.1783** | 0.6734 / 0.1785 | PASS (reproducible) |
| M4 baseline (frozen bar) | ranking Spearman / top-8 recall | **0.5955 / 0.6472** | 0.5951 / 0.6472 | PASS |
| M5 v2 `RankingXGBModelV2` | midpoint Spearman | **0.6112** (baseline 0.5955) | 0.6128 | PASS |
| M6 `WinProbXGBModel` | log-loss / Brier | **0.5209 / 0.1749** | 0.5143 / 0.1719 | PASS |
| M7 symmetric isotonic calibration | ECE / G2 | **0.0232 / 2 of 9 bins rejected** | 0.0375 / 5 of 10 | **FAILED** |
| M11 generalization | all four checks | **PASS** | not run | PASS |

## 6. Models

**M5 v2 — `RankingXGBModelV2`**
- **Target:** a team's ridge-attributed share of its alliances' qualification margins at a training event (`RIDGE_LAMBDA` = 1.0; at least `MIN_QUAL_MATCHES` = 3), divided by the event's score SD.
- **Training:** XGBoost, seed 42, early stopping on the temporal last 20%.
- **Paired evidence over 208 events:** +0.0157 Spearman over raw EPA (bootstrap 95% CI 0.004–0.027), better in 122 events, Wilcoxon p = 0.004.
- **Label shuffle over 8 seeds:** mean 0.070, range −0.18 to +0.28 — chance.

**M6 — `WinProbXGBModel`**
- XGBoost on the two alliance vectors.
- Served as p(R, B) = ½[raw(R, B) + 1 − raw(B, R)]: exactly symmetric by construction.
- **Caveat:** it beats the baseline on log-loss and Brier through calibration, but discriminates worse (accuracy 0.7162 vs 0.7625; ROC-AUC 0.8203 vs 0.8422).

**M7 — `SymmetricIsotonicCalibrator`**
- Isotonic g fit on both perspectives of the last 20% of training (late 2025), never on 2026. Served as q = ½[g(p) + 1 − g(1 − p)].
- **Gate (D16):** all four must pass.
  - **G1:** `ECE_THRESHOLD` = 0.05.
  - **G2:** an exact Poisson-binomial test per bin on 10 fixed bins, for bins with at least `MIN_BIN_COUNT` = 30 predictions; Holm correction at `ALPHA` = 0.05.
  - **G3:** symmetry within `SYMMETRY_TOLERANCE` = 1e-12.
  - **G4:** fit isolation.

## 7. Calibration evidence

From `.agent/phase4/D18_M07_DIAGNOSTIC.md`:

| Population | n | Mean predicted (red) | Observed | ECE |
|---|---|---|---|---|
| All | 15,027 | 0.514 | 0.536 | 0.0232 (perfect-calibration floor 0.0077) |
| Qualification | 12,245 | 0.498 | 0.497 | 0.015 (all bins within ±3.2 pts) |
| Playoff | 2,782 | 0.587 | 0.706 | 0.119 |
| Playoff, higher seed's view | 2,750 | 0.624 | 0.773 | 0.149 |

- **Playoffs.** The higher seed wins far more often than the features predict, in every season (+6.8 pts in 2025). A model and calibrator that are color-symmetric by construction, and have no seed information, cannot represent this.
- **Calibration does not transfer across seasons.** In a 2024 → 2025 diagnostic fold the calibrated model also fails, and calibration worsened log-loss. In-sample calibration is not evidence.

## 8. Unbiasedness and leakage guarantees

- **Point in time.** Every feature is computed strictly before `as_of`. EPA follows §1 availability.
- **Training precedes testing.** `Fold` structurally enforces max(train time) < min(test time).
- **Symmetry.** M6 and M7 are exactly symmetric: swapping red and blue gives 1 − p (error 0.0 on held-out data).
- **No strategy-source field.** No feature encodes a recommendation source. Alliance order (red or blue) is symmetrized away, so color carries no information. This is also why the playoff higher-seed effect is invisible to the model (§7).
- **One-command audit (M8).** `python -m scripts.ml_bias_audit` checks symmetry, order invariance, strategy leakage, as-of integrity and label-shuffle collapse, for both ranking models. M5 v2: true-label correlation 0.759, shuffled 0.010.
- **Load-time guard (M10).** The registry refuses a model whose feature list differs from the current one. Round trip on the D18 models: 0 mismatches.

## 9. Production serving (M12, aligned with D18 on 2026-10-02)

The four routes:
- `GET /predictions/matches/{match_key}/win-probability`
- `POST /predictions/win-probability`
- `GET /predictions/events/{event_key}/ranking`
- `POST /predictions/alliance-synergy`

### Models served

`api/ml_loading.py` serves only the D18 models of record.

| Use | Model type | What it is |
|---|---|---|
| Ranking | `ranking_xgb_v2` | M5 v2, `RankingXGBModelV2` |
| Win probability | `win_prob_xgb_calibrated` | the D18 M7 pair: M6 plus its symmetric isotonic calibrator (`ml/models/calibrated_win_prob.py`) |

`ranking_xgb` (M5 v1, FAILED) and raw `win_prob_xgb` are refused by name. The model-type settings are single-value literals, so nothing falls back to them.

**Pins.** Each served model is pinned by type, version tag and artifact sha256:
- `ML_RANKING_MODEL_VERSION_TAG` with `ML_RANKING_MODEL_SHA256`;
- `ML_WIN_PROB_MODEL_VERSION_TAG` with `ML_WIN_PROB_MODEL_SHA256`;
- `ML_REGISTRY_DIR` for the registry location.

The sha256 is checked against the registered file before loading, and a tag without its sha256 is a configuration error. Replacing a served model therefore requires an explicit configuration change.

**Artifacts.** `scripts/register_d18_production_models.py` built the artifacts by the evaluation's own deterministic fits. It refuses to register unless they reproduce the D18 records exactly:
- M5 v2: Spearman 0.6112 bit for bit;
- the M7 pair: ECE and every G2 bin identical.

Its record is `.agent/production/d18_model_registration.json`. Every response echoes `model` (type, version, tag, `model_sha256`, `training_dataset_hash`, provenance).

### EPA source

`EPA_SOURCE` = `d18_statbotics_primary` (the default) builds the D18 source with its snapshot-integrity checks (`ml/ratings/d18_source.py`). It needs:
- `STATBOTICS_SNAPSHOT_DIR`, the verified snapshot;
- `STRATAI_EPA_CHAIN`, the fallback chain.

Unconfigured or failing a check, it serves `epa_source_not_loaded`, never a substitute source. `stratai` and `statbotics` stay selectable as non-evaluated references, and responses then report `evaluated_configuration` = false.

Every response carries `epa` (source, `evaluated_configuration`, snapshot provenance) and per-team `epa_value_source` / `epa_source_event_key` / `epa_withheld_reason`.

### Win-probability gating (M7 FAILED)

| Scope | `validation_status` | `red_win_probability` |
|---|---|---|
| Qualification match (`competition_level` = qualification), or ad-hoc with `match_context` = qualification | `approximately_calibrated_qualification` | rounded to `PROBABILITY_DISPLAY_STEP` = 0.05 and clipped to [0.05, 0.95]; never a precise decimal, never 0% or 100% |
| Playoff match, ad-hoc `match_context` = playoff, or no stated context | `not_validated` | **null** |

- In the not-validated case the model output appears only as `unvalidated_red_win_probability`, with a `warning` that it must not be presented as a probability.
- Every win-probability response carries `calibration_status` = `m7_gate_failed`.
- No series, bracket or playoff-success probability is served anywhere.
- Ranking responses carry `validation_status` = `moderate_held_out`; `predicted_rating` is a relative score, so only the ordering is meaningful.
- Synergy responses carry `not_validated_against_outcomes`.

**Error codes:**
- `model_not_loaded`
- `epa_source_not_loaded`
- `epa_source_incomplete` — the D18 source lacks a valid row for a required prior event; it never silently uses an older one
- `event_not_found`
- `match_not_found`
- `team_not_found`
- `insufficient_features`

### Verified

`scripts/verify_d18_production.py` (record `.agent/production/d18_integration_check.json`) checks the real application against the D18 frame:
- the served models and their hashes;
- the EPA source and snapshot;
- served features equal to the evaluated features match by match, including every 2026iscmp qualification match;
- provenance labels;
- playoff gating.

`tests/test_d18_production_source.py` checks that the production D18 loader equals the evaluation's loader on the real snapshot.

### Production limitations

1. **The snapshot is fixed.** A live Statbotics sync changes `team_event_stats`, so the snapshot fingerprint no longer matches and the D18 source refuses to load (`epa_source_not_loaded`). A new snapshot must be taken with `scripts/sync_statbotics_snapshot.py` and configured explicitly.
2. **It loads once.** The EPA source reads canonical facts on first use. Events completed after that are not candidates until the process restarts.
3. **The STRATAI fallback covers 2026iscmp only.** A future event whose prior event Statbotics has not processed returns `epa_source_incomplete`.
4. **Different decision points.** The ranking endpoint scores teams as of the request. The evaluated decision point was each team's mid-qualification snapshot.
5. **Some "as of now" requests are refused, by design.**
   - **The cause.** D18 refuses (`epa_source_incomplete`) when a team's latest prior event has no valid Statbotics row outside the 2026iscmp fallback scope.
   - **Where it hits.** After the 2026 season, any event whose roster includes a team whose latest event was an unprocessed 2026 Israeli event. Example: `2026dal` ranking, because its Israeli teams last played `2026iscmp`.
   - **Why the evaluation never hit it.** It always predicted at match time.
   - **Behaviour.** This is the no-silent-fallback rule working; nothing is substituted. Widening the fallback scope would be a new pre-registered source decision.
6. **Never run the test suite against a serving database.**
   - **The risk.** Its database fixtures insert and delete sentinel rows in whatever `DATABASE_URL` names, including 2026-season matches (`tests/test_live_watch.py`).
   - **What it does.** While a test runs, those rows can shift the causal season scale for served features.
   - **Observed.** It happened once during verification: run 2 of `scripts/verify_d18_production.py`, run concurrently with the suite, saw one transient feature mismatch. That match is identical on a quiet database.

## 10. What to trust

| Output | Trust | How to present it |
|---|---|---|
| Team ranking within an event (M5 v2) | Moderate: per-event Spearman median 0.61 (10th–90th percentile 0.46–0.78); only slightly better than raw EPA | An ordering with uncertainty. Do not present rank gaps of a few places as meaningful. |
| Qualification win probability (M6 + M7) | Approximately calibrated (ECE 0.015, unbiased, bins within ±3 pts) | Rounded to about 5 pts, or as bands ("~65%"). Never as "63.4%". |
| Expected qualification wins | Unbiased; about 1.1 wins mean absolute error per event (0.96 is irreducible) | As a range. |
| Playoff win probability or series odds | **Not trustworthy.** Higher seed underestimated by about 15 pts per match | Do not present as a probability, and do not feed it to bracket simulation. |
| Early-season (weeks 1–3) probabilities | Worse calibrated (ECE 0.046–0.068) | With a visible low-confidence label. |
| Defense / feeding | Scouting-only. Feeding is unvalidated (Phase 3 M14 open) | With `insufficient_data` when thin. |

## 11. Known limitations

1. M7 failed: probabilities are not certified calibrated, and the done-means is not met.
2. There is no playoff or seed information in the models, so playoff predictions are systematically biased against the higher seed.
3. The M7 calibrator is coarse (127 output values) and fit on one late-2025 slice. Calibration does not transfer across seasons.
4. M6 uses raw game-point features; scoring scale shifts between seasons (2026 is 2.5–3.8× the training seasons).
5. M5 v2's gain over raw EPA is small (+0.016). At the pre-event snapshot it is below raw EPA (0.5565 vs 0.5955).
6. 2024 rows have no prior-season EPA (no 2023 data), so 43% of training rows are not EPA-complete and are excluded from win-prob training. The 2026 Israeli events rely on the STRATAI fallback.
7. Only one held-out season (2026) has been evaluated under D7.

## 12. Reproduction

```
python -m scripts.run_phase4_d18 verify --snapshot <snapshot> --chain <chain>      # source checks (S1-S6)
python -m scripts.run_phase4_d18 build-frame --snapshot <snapshot> --chain <chain> --out <dir>
python -m scripts.run_phase4_d18 m04|m05v2|m06|m07|m11 --frame <frame>              # each refuses a second run
python .agent/phase4/results/d18/m07_diagnostics.py <frame> <snapshot> <out.json>
python -m scripts.ml_bias_audit
python -m scripts.phase4_done_means
python -m scripts.register_d18_production_models --frame <frame> --registry <dir>  # once; refuses unless it reproduces D18
python -m scripts.verify_d18_production --frame <frame>                            # production == evaluated D18
```

## 13. Extending

- **A new season** needs a score-breakdown adapter in `ml/features/score_breakdown.py`. Without one it raises `UnsupportedSeasonError`, never a silent 0.
- **A model change** — for example causally normalized M6 features, or an antisymmetric playoff seed-difference feature — needs its own frozen specification, written before its one run. It is a new version; it does not replace a recorded result.
