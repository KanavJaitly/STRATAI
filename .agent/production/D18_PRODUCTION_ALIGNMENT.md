# Production alignment with the evaluated D18 system

2026-10-02. **Phase 4 status (unchanged): evaluation complete; acceptance criteria not fully met (M7 FAILED).**

This work changes no model, calibrator, D18 rule, threshold or Phase 4 record. It makes the production path serve exactly what was evaluated, and it gates what the evaluation did not support.

## What changed

| Area | Before | After |
|---|---|---|
| **Ranking model served** | M5 v1 `RankingXGBModel` (`ranking_xgb`, FAILED) | M5 v2 `RankingXGBModelV2` (`ranking_xgb_v2`) only. v1 is refused by name; `Settings.ml_ranking_model_type` is a single-value literal |
| **Win-probability model served** | raw M6 (`win_prob_xgb`) | the D18 M7 pair, M6 + symmetric isotonic calibrator (`win_prob_xgb_calibrated`), packaged unchanged by `ml/models/calibrated_win_prob.py`. The qualification calibration evidence belongs to this pair |
| **Pinning** | version tag only | type + version tag + **artifact sha256**, checked before loading; a tag without a sha256 is a configuration error |
| **Artifacts** | none registered | `scripts/register_d18_production_models.py`: same deterministic fits; refuses unless each reproduces its D18 record bit for bit (`d18_model_registration.json`) |
| **EPA source** | `stratai` (D15) or plain `statbotics`; D18 not selectable | `d18_statbotics_primary`, now the default: the evaluated source, with S1 integrity checks (`ml/ratings/d18_source.py`). Fails loudly when unconfigured |
| **Provenance in responses** | model type/version/tag | plus model sha256, training-frame hash, manifest provenance, EPA source identity, `evaluated_configuration`, and per-team `epa_value_source` / source event |
| **Win probability** | exact decimal, `uncalibrated` | qualification scope only: rounded to 0.05 within [0.05, 0.95]. Playoff or unstated ad-hoc context: `red_win_probability` = null, `unvalidated_red_win_probability` plus warning. `calibration_status` = `m7_gate_failed` |
| **Ranking / synergy** | — | `validation_status` `moderate_held_out` / `not_validated_against_outcomes` |
| **New error codes** | — | `epa_source_not_loaded`, `epa_source_incomplete` |

## Configuration (non-secret; in the process environment or `.env`)

```
EPA_SOURCE=d18_statbotics_primary
STATBOTICS_SNAPSHOT_DIR=C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z
STRATAI_EPA_CHAIN=C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json
ML_REGISTRY_DIR=C:/Dev/StratAI-artifacts/ml_registry
ML_RANKING_MODEL_VERSION_TAG=d18
ML_RANKING_MODEL_SHA256=1f0fe5aae90244e2736950928a88e733c85214b8def547b399b87c0cdd136312
ML_WIN_PROB_MODEL_VERSION_TAG=d18
ML_WIN_PROB_MODEL_SHA256=c76d329918e1667ae6f641ae6023e0649f34feb7c35064dea8b3db5cd1a8b0a2
```

The local `.env` was not edited. Verification passed these as process environment variables.

## Verification evidence

- **`d18_model_registration.json`:** both refits reproduce the D18 records exactly, and the reload round trip has 0 mismatches (108,024 ratings; 15,027 probabilities).
- **`d18_integration_check_run1.json`** (first run, kept):
  - models, EPA source, served-equals-evaluated features and provenance all PASS;
  - the gating check FAILED on a verification design flaw (it probed `2026dal` "as of now", which D18 correctly refuses).
- **`d18_integration_check_run2.json`** (kept):
  - the corrected gating check PASSED: 2026dal refused as `epa_source_incomplete`, the normal path verified on 2026onnob, the ad-hoc request unvalidated, 0 of 25 playoff matches with a validated value;
  - check 3 FAILED on one transient feature mismatch (`2026mibel_qm76`).
  - **Cause:** the full test suite was running concurrently against the same database. Its fixtures insert 2026-season rows, which shift the causal season scale.
  - **Evidence:** the same match is identical to the frame on a quiet database.
  - This is recorded as a production limitation (never run tests against a serving database).
- **`d18_integration_check.json`:** run 3, clean, with nothing concurrent (see the final report).
- **`tests/test_d18_production_source.py`:** the production loader equals the evaluation's loader (state plus 5,450 lookups, including all 450 fallback appearances).

## Not changed, deliberately

- D15 / D18 records, the D18 spec, the M07 diagnostic, M10 / M11 evidence and the M13 package are untouched.
- `scripts/run_phase4_d18.py`'s pinned functions are unchanged.
- No milestone was re-run. The registration refits only reproduce records; they re-judge nothing.
