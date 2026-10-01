# Phase 4 — Milestone 6 Acceptance: Win Probability Model (symmetric by construction)

Accepted 2026-09-30. EPA source: STRATAI (D15). Model unchanged since 2026-09-25. Statbotics parity is not claimed.

## Criteria (docs/P4Milestones.md M6)

| Criterion | Evidence | Result |
|---|---|---|
| swap(red, blue) ⇒ p → 1 − p, guaranteed | structural p = ½[raw(R,B) + 1 − raw(B,R)]; held-out maximum error **0.0**; unit test | PASS |
| Beats or matches baseline log-loss on held-out | **0.5143** vs frozen 0.6734 | PASS |
| Beats or matches baseline Brier on held-out | **0.1719** vs frozen 0.1785 | PASS |
| Identical alliances → identical probability | held-out order independence (forward vs reversed); unit test | PASS |
| No-strategy-leakage | `tests/test_ml_models_win_prob.py` | PASS |
| Reproducible | two runs identical | PASS |

## Numbers (held-out 2026, D7)

Frame `54e9d54b…`, the same as M4. Same population as the frozen baseline: EPA-complete rows, 15,027 scored, 34 ties excluded (precedent: `scripts/run_m11_generalization.py`).

| | Log-loss | Brier | Accuracy | ROC-AUC | ECE |
|---|---|---|---|---|---|
| M4 `EpaWinProbBaseline` | 0.6734 | 0.1785 | 0.7622 | 0.8421 | 0.1194 |
| M6 `WinProbXGBModel` | 0.5143 | 0.1719 | 0.7231 | 0.8237 | 0.0300 |

- Diagnostic, all 17,960 held-out rows (EPA may be missing; native NaN handling): log-loss 0.5600, Brier 0.1897, accuracy 0.7042, AUC 0.7978, ECE 0.0740.
- Evidence: `results/m06_result.json`. Runner: `scripts/run_phase4_stratai.py m06`.

## Observation (not a defect; recorded so the gate is not over-read)

M6 passes its defined gate (log-loss, Brier) mainly through much better calibration. The overconfident baseline still discriminates better: accuracy 0.7622 vs 0.7231, AUC 0.8421 vs 0.8237. M6 is not a uniform improvement over raw-EPA win probability.

## Regression

`tests/test_ml_models_win_prob.py`, `tests/test_ml_models_team_vector.py`: 26 passed.
