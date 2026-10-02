# Phase 4 — M13 sign-off package (for Kanav's review)

Prepared 2026-10-02 on branch `phase4-stratai/m05v2`. Nothing has been pushed or merged, and PR #29 is untouched.

This package does **not** record a sign-off. M13's sign-off is a dated human entry in RUNNING_NOTES.md, and its done-means gate is NOT MET:

    python -m scripts.phase4_done_means      # exit 1: ranking MET, calibration NOT MET

**What "complete" means here.** The required Phase 4 evaluation has been run, and what STRATAI can and cannot be trusted to do is known. Not every gate passed. Under the authoritative plan (`docs/P4Milestones.md`: "…recorded with real held-out numbers, **or the phase stays open**"), **Phase 4 is not complete**.

## 1. Milestone results

All runs were on D18 frame `ab1adbf3…` unless stated. Every real-data run happened once, with a write-once record.

| Milestone | Result | Evidence |
|---|---|---|
| M01 feature assembly | ACCEPTED (2026-09-21) | RUNNING_NOTES |
| M02 dataset builder | ACCEPTED (2026-09-24) | RUNNING_NOTES |
| M03 backtest harness | ACCEPTED (2026-09-25) | `M03_ACCEPTANCE.md` |
| **M04** baselines | **PASS**, re-frozen for D18: win-prob log-loss 0.6707 / Brier 0.1783 / accuracy 0.7625 / AUC 0.8422 / ECE 0.1186; ranking Spearman 0.5955 / top-8 0.6472; reproducible | `results/d18/m04_result.json` |
| **M05 v2** ranking | **GATE PASSED, acceptance pending your review**: 0.6112 > 0.5955; paired +0.0157 (95% CI 0.004–0.027), better in 122/208 events, Wilcoxon p = 0.004; reproducible; shuffle at chance | `results/d18/m05v2_result.json` |
| **M06** win prob | **PASS**: log-loss 0.5209 ≤ 0.6707, Brier 0.1749 ≤ 0.1783; symmetry 0.0; order-independent; reproducible | `results/d18/m06_result.json` |
| **M07** calibration (original D16 gate, D18 run) | **FAILED**: G1 ECE 0.0232 ✓; G2 2/9 bins rejected ✗; G3 ✓; G4 ✓ | `results/d18/m07_result.json`, `D18_M07_DIAGNOSTIC.md` |
| M07 replacement | **None created.** The criterion was judged appropriate (decision A, `D18_M07_DIAGNOSTIC.md` §5) | — |
| M08 bias / leakage audit | ACCEPTED 2026-09-25 (synthetic). On 2026-10-02, against the model of record v2: the first run FAILED (fixture defect: no `score_scale`, so v2 learned nothing). After the fixture fix (thresholds unchanged; v1 output byte-identical) both v1 and v2 PASS | `M08_ACCEPTANCE.md`; commit 411dc60 |
| M09 alliance synergy | ACCEPTED 2026-09-25 (synthetic). **Not validated against outcomes** — no ground truth exists | `M09_ACCEPTANCE.md` |
| M10 registry | ACCEPTED 2026-09-25. On 2026-10-02, the real D18 models round trip with 0 mismatches (108,024 ratings, 15,061 probabilities) and a drifted feature list is refused | `results/d18/m10_registry_check.json` |
| **M11** generalization | **PASS** (single frozen run, D18 §5, M5 v2): log-loss 0.5209 < 0.6707 / 0.693; Brier 0.1749 < 0.1783 / 0.25; Spearman 0.6112 > 0.5955 / 0; `average_auto_points` resolves in 2026. The adapter, unsupported-season and parity tests pass | `results/d18/m11_result.json` |
| M12 API | ACCEPTED 2026-09-25. **Two gaps:** the ranking loader serves v1 and refuses v2; no D18-source option exists in Settings | `M12_ACCEPTANCE.md`; this package §4 |
| **M13** docs and sign-off | Docs, contract tests and done-means gate built. **Sign-off: open** (gate NOT MET) | `docs/ml_models.md`, `tests/test_ml_models_docs_contract.py`, `scripts/phase4_done_means.py` |

**D15 history (STRATAI EPA throughout), preserved:**
- M4: 0.6734 / 0.1785 / 0.5951.
- M5 v1: FAILED, 0.3903.
- M5 v2: 0.6128.
- M6: 0.5143 / 0.1719.
- M7: FAILED, 5/10 bins rejected.

## 2. Provenance, leakage and reproducibility

**Source (D18).** Statbotics snapshot `statbotics_snapshot_20261001T220423Z`:
- 608 events, 24,022 rows, fingerprint `c73775c6…`;
- every raw file sha-verified, and raw EPA equals table EPA on every row.

| Source | Appearances |
|---|---|
| Statbotics | 263,726 |
| STRATAI fallback (2026iscmp only) | 450 |
| Withheld by availability | 679 |
| Withheld, no prior event | 54,446 |

**Leakage checks:**
- 0 served values with `available_at ≥ as_of`;
- 0 season-end values before season end;
- D13 parity 6,000/6,000;
- `Fold` enforces train before test structurally;
- label shuffle collapses (M5 v2 real data over 8 seeds: mean 0.070, mixed signs; M8 synthetic: 0.010);
- the M2 label uses the final score only.

**Reproducibility:**
- M4, M5 v2 and M6 each reproduce exactly (twin fits);
- the M7 diagnostic refit reproduces the recorded run bit-for-bit;
- M11's values equal the M04 / M05 v2 / M06 records;
- the registry round trip is exact.

**Freeze discipline:**
- D18 spec frozen at `ec1b0af` before any data;
- implementation at `69139f8`, and verification plus frame at `77d5423`, both before any metric;
- every run checks that the methodology files are unchanged since `ec1b0af` and the frame code since `69139f8`.

**One documented amendment (`4ef55a7`, before M11):**
- M11's readiness step needed a non-read-only connection;
- the runner pin became per-function;
- every frame-producing and already-run function is byte-identical.

## 3. Calibration evidence and its practical meaning

See `D18_M07_DIAGNOSTIC.md`.
- **Qualification:** near-calibrated. ECE 0.015, mean predicted 0.498 vs observed 0.497, all bins within ±3.2 points.
- **Playoffs:** not calibrated. ECE 0.119, and the higher seed wins 77.3% vs 62.4% predicted, in every season.
- **Across seasons:** calibration does not transfer.
- **Precision:** the calibrator is coarse (127 values).

## 4. Known limitations and Phase 5 prerequisites

1. **Playoff probabilities and series simulation are biased** against the higher seed by about 15 points per match. Do not use them for "predicted playoff success" until a model with playoff context passes its own frozen calibration test.
2. **M7 failed**, so probabilities are not certified calibrated. Qualification probabilities are approximately calibrated and should be shown coarsely.
3. **M12's ranking endpoint loads M5 v1**, the failed model. It refuses v2. It must be extended before Phase 5 serves rankings.
4. **The served feature path can't select the evaluated source.** `Settings.epa_source` offers `stratai` (D15) or plain `statbotics` (no fallback). The D18 composite provider that produced every D18 number is not selectable, so served features would not be from the evaluated source version.
5. **M5 v2's gain over raw EPA is small** (+0.016), and below raw EPA before an event has started.
6. **Evaluation coverage:** one held-out season; 2024 lacks prior-season EPA; the 2026 Israeli events use the STRATAI fallback.
7. **Defense and feeding:** feeding is unvalidated (Phase 3 M14 open) and the defense definition is pending.
8. **Live updates:** `team_metrics` does not recompute during `--watch` (CLAUDE.md constraint 5).

## 5. Is STRATAI reliable enough to proceed to Phase 5?

**Conditionally, for qualification-level uses only.**

Reliable enough:
- within-event team ordering, presented with uncertainty;
- approximate qualification win probabilities, coarsely displayed;
- expected qualification wins as ranges.

**Not reliable** for anything built on playoff probabilities, such as bracket simulation or "predicted playoff success". That is exactly what Phase 5/6 alliance selection aims at, so it must be fixed or excluded first.

Items 3 and 4 above are engineering prerequisites. Item 1 is a methodology decision.

## 6. What is NOT proven

- That probabilities are calibrated (M7 failed). Playoff calibration is disproven.
- That any result generalizes beyond 2026 as a held-out season (one season only).
- That M09 synergy scores predict alliance success (never tested against outcomes).
- That feeding ratings measure anything (no feeding data at collection time).
- Statbotics parity of STRATAI EPA (close: Pearson ≥ 0.9966; not claimed).
- That the model's rankings help a human beat raw EPA in practice (+0.016 Spearman is small).

## 7. Commands to run and review

```
git log --oneline 3f34b6b..HEAD                     # every commit of this work
python -m scripts.phase4_done_means                  # NOT MET (exit 1)
python -m pytest -q                                  # full suite
python -m pytest -q tests/test_ml_models_docs_contract.py tests/test_phase4_done_means.py
python -m scripts.ml_bias_audit                      # M8, v1 and v2
python -m scripts.run_phase4_d18 m07 --frame C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3   # refuses: single run
```

Read in this order:
1. `.agent/phase4/D18_SOURCE_SPEC.md`
2. `D18_RESULTS.md`
3. `D18_M07_DIAGNOSTIC.md`
4. `docs/ml_models.md`

## 8. Decisions for Kanav

1. Accept or reject M5 v2 (D18).
2. Accept that M7 is FAILED as recorded, leaving Phase 4 open. Or approve a pre-registered model change with its own frozen spec and one run, for example:
   - causally normalized M6 features;
   - an antisymmetric playoff seed-difference feature;
   - a stratified (qualification / playoff) M7 criterion.
3. Whether Phase 5 may start on qualification-level uses while M7 stays open, with items 3 and 4 fixed first.
4. PR #28 / #29: see the final report. The recommendation is not to merge yet.
