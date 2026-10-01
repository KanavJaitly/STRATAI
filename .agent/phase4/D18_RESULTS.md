# Phase 4 — D18 controlled run (Statbotics-primary EPA): M04, M05 v2, M06 passed; M07 FAILED; stopped

2026-10-01. Specification `.agent/phase4/D18_SOURCE_SPEC.md`, frozen at ec1b0af before any D18 data or metric existed. Implementation committed at 69139f8. Pre-run verification and frame committed at 77d5423, before the first metric.

Every milestone ran exactly once, through `scripts/run_phase4_d18.py`:
- write-once records in `results/d18/`;
- each run's guard confirmed the methodology files are unchanged since ec1b0af and the implementation is unchanged since 69139f8.

The D15 (STRATAI EPA) results are untouched and remain the historical record. Statbotics parity is not claimed. Phase 4 is not complete.

## Source (spec §1–3) and verification (§6) — `results/d18/source_verification.json`

All 319,301 appearances in 2024–2026:

| Outcome | Appearances |
|---|---|
| Statbotics, A2 (week-1 rule) | 262,764 |
| Statbotics, A1 (season-end value, served only after T_end) | 962 |
| **STRATAI fallback (`stratai_fallback`), all with target 2026iscmp** | **450** |
| Withheld: every D13 candidate unavailable (§3) | 679 (2024: 674; 2026: 5) |
| Withheld: no prior event (legitimate, as under D13) | 54,446 |

**Temporal exclusions** (lookups skipped by availability):
- A1 skipped 1,064 times: 331 qual-count-0 team-events, 188 of them played;
- A2 skipped 757 times;
- 679 appearances lost EPA entirely as a result.

| Check | Result |
|---|---|
| **S1 — snapshot integrity** | 608 raw files sha-verified; 24,022 raw records = 24,022 table rows (fingerprint `c73775c6…`); raw `epa.total_points` equals table `epa_total` for every row. **PASS** |
| **S2 — fallback scope** | 450 appearances target 2026iscmp; all 450 are served by the fallback; 0 fallback values elsewhere. **PASS** |
| **S3 — silent fallback** | 0 hard errors (no missing or invalid D13 candidate outside 2026iscmp). **PASS** |
| **S4 — selection parity** | 6,000 sampled (seed 20261001) from 317,034 no-skip appearances, compared with D13's `EPA_SOURCE_SQL`: 0 mismatches. **PASS** |
| **S5 — leakage** | 0 served values with available_at ≥ as_of; 0 A1 values served before T_end. **PASS** |
| **S6 — cross-check** | T_w1 and T_end equal STRATAI's recorded week-one and season-final instants in all three seasons. Reported only |

**Frame** `ab1adbf38b43c2f3…`:
- 52,469 rows (excluded: 726 dq_affected, 25 unplayed — the same rule as D15);
- the cache reproduces the content hash;
- frame appearances: Statbotics 260,183; `stratai_fallback` 450 (all at 2026iscmp); withheld 54,181; fallback outside scope 0.

## Results (held-out 2026, D7 split)

D18 gates reference the D18 M4 baseline (spec §4). D15 numbers are shown for comparison only.

| | D15 (STRATAI EPA) | **D18 (Statbotics primary)** | D18 gate | D18 status |
|---|---|---|---|---|
| **M04** win-prob baseline (15,027 EPA-complete rows) | LL 0.6734, Brier 0.1785, acc 0.7622, AUC 0.8421, ECE 0.1194 | **LL 0.6707, Brier 0.1783, acc 0.7625, AUC 0.8422, ECE 0.1186** | reproducible | **PASS** — the D18 frozen baseline |
| **M04** ranking baseline (208 events) | Spearman 0.5951, top-8 0.6472 | **Spearman 0.5955, top-8 0.6472** | reproducible | **PASS** |
| **M05 v2** (midpoint snapshot, 8,160 team-events) | 0.6128 (top-8 0.6550) | **0.6112 (top-8 0.6587)** | > 0.5955 same-protocol **and** > 0.5955 D18 M4 | **GATE PASSED** (acceptance pending review) |
| **M06** (15,027 rows) | LL 0.5143, Brier 0.1719 | **LL 0.5209, Brier 0.1749** (acc 0.7162, AUC 0.8203, ECE 0.0408) | ≤ 0.6707 and ≤ 0.1783; symmetry 0.0 | **PASS** |
| **M07** (D16 gate, 15,027 rows) | G1 0.0375 ✓, G2 5/10 bins rejected ✗ | **G1 ECE 0.0232 ✓; G2 2/9 eligible bins rejected ✗; G3 ✓ (0.0); G4 ✓** | all of G1–G4 | **FAILED** |

**Notes on the passing milestones:**
- **M05 v2 (D18):**
  - reproducible; label-shuffle mean 0.070 (8 seeds); best iteration 7;
  - secondary: the first-snapshot Spearman is 0.5565, below the baseline, as under D15;
  - the last-snapshot Spearman is 0.6314.
- **M06 (D18):** reproducible and order-independent. The same caveat as D15 applies: discrimination is below the baseline (acc 0.7162 vs 0.7625; AUC 0.8203 vs 0.8422), and the gate is won through calibration.

### M07 failure (genuine; no defect found, no rerun)

| Bin | n | Mean predicted | Observed | p | Holm threshold | Result |
|---|---|---|---|---|---|---|
| [0.1, 0.2) | 2,164 | 0.1633 | 0.1964 | 4.5e-5 | 0.0063 | **rejected** |
| [0.3, 0.4) | 2,133 | 0.3610 | 0.4276 | 2.3e-10 | 0.0056 | **rejected** |
| [0.6, 0.7) | 2,408 | 0.6418 | 0.6603 | 0.058 | 0.0100 | not rejected |

- The other 6 eligible bins are not rejected. Bin [0.4, 0.5) has only 14 rows and is not tested.
- Calibrator fit: the 2025 calibration slice, 3,937 rows.

**Diagnostic (read-only; not a gate input; no change made).**
- Observed red wins: 8,039, against 7,724.7 expected. The excess sits in the under-0.7 bins.
- Red's share of decided matches is about 49.5% in qualification in every season, but rises in playoffs, where red is the higher seed:

  | Season | Red share of decided playoff matches |
  |---|---|
  | 2024 | 62.7% |
  | 2025 | 68.0% |
  | 2026 | 70.7% |

- A model that is symmetric by construction (CLAUDE.md: unbiased win probabilities), with no seed feature and a calibrator fit on 2025, cannot represent that 2026 playoff shift.
- Whether and how to address this is a methodology decision. **Not made here.**

## M11 — resolved, not run

- **Model of record.** D18 §5, frozen before any result, evaluates M11's generalization test against the M5 model of record, **v2**, with v2's own protocol. M5 v1 is FAILED and superseded. `generalization_checks`, the D7 split and the win-prob comparison are unchanged.
- **Already in place.** M11's other criteria — season adapters, `UnsupportedSeasonError`, cross-season parity tests — exist (`ml/features/score_breakdown.py`, `tests/test_ml_features_auto_points.py`).
- **Status.** Its dependencies (M5 v2, M6) passed under D18. It has **not been run**, because D9 / the instruction says to stop on a genuine failure.
- **To run (single):** `python -m scripts.run_phase4_d18 m11 --frame <frame>`.

## M13 — not started

M13's done-means requires a calibrated win probability. M07 failed under D16, so M13 cannot be signed off.

## Decisions needed (Kanav)

1. **M07** — what is the M7 path after a second genuine G2 failure (D15: 5/10 bins rejected; D18: 2/9)? D9 forbids changing the calibrator, the bins or the test to manufacture a pass.
2. **M05 v2 (D18)** — review its gate pass for acceptance.
3. **M11** — authorize its single frozen run now, or hold it until M7 is resolved.
