# PX historical validation study, HV-1: frozen specification, version 1 (2026-10-09)

**Frozen by the commit that introduces this file, before any HV-1 metric is computed.** A change is a new version, written before the run it governs.

**What this study is.** Historical, diagnostic evidence on whether PX-1b shows repeatable value across 2024–2026.
- It was requested by Kanav on 2026-10-09, before any M10 work.
- **It is not an acceptance test.** It changes no frozen specification, gate, threshold or result.
- It cannot accept PX-1b: only FINAL-1 on an untouched 2027 holdout can (PX-1b spec §6; D9 v1).

## 0. What was already known when this was written (disclosure)

The study is not blind, and its folds are not equally independent:

| Fold | Already observed before HV-1 | Independence |
|---|---|---|
| **F1** (fit 2024 → test 2025) | **The same population and models as PX-1b DEV-1** (`p6_px1b_dev.json`): PX-1b 0.5268, PX-1 raw 0.5306, seed-only 0.5666 | **A reproduction, not new evidence** |
| **F2** (fit 2024–2025 → test 2026) | The PX-1 raw design fit on 2024–2025 was evaluated on 2026 (`p6_m2_px1_rerun1.json`: 0.6419, on 2,632 rows without the `scale_absent` rule), with M6/M7 and seed-only. PX-1b's normalization was **chosen after** the 2026 diagnostics showed the scale shift. PX-1b has never been scored on 2026 | **Post-hoc** for PX-1b: 2026 motivated its design |
| **F0** (2024, within season) | No PX outcome metric has been computed on a within-2024 split. The 2024 rows are in every PX training set | Least contaminated, but smallest |

**Conflict with the PX-1b spec, recorded explicitly.** PX-1b spec §6 says "PX-1b is never evaluated on 2026".
- HV-1 scores a **fold-specific PX-1b refit on 2024–2025** on 2026, at Kanav's explicit 2026-10-09 instruction, as a **diagnostic only**.
- The PX-1b spec is not edited. Its second clause, that no PX-1b acceptance claim may rest on 2026, holds in full for this study.
- The registered `px1b-v1` (fit 2024–2026) is **never** evaluated on any 2024–2026 outcome here.

## 1. Data (no new extraction)

**Rows:** the PX rerun1 rows cache, `C:/Dev/StratAI-artifacts/phase6/px_rows_px1-v2.pkl.gz`.
- sha256 `d7809c5fd7d245f51676b1bcef6abff153528cd581b2af1a161a1f7ffc0627cf`.
- Built under PX-1 §1 plus amendment A1, with selection-moment features (D18 EPA, causal scales).
- Minus `scale_absent` (PX-1b §1.3), which gives the PX-1b §1 rows: 2024: 991; 2025: 2,435; 2026: 2,626 (21 excluded).
- Population fingerprint `52a4d7f0ac464886b0ea020b401b71f7f1d668c49a783bab4eb2ecf7b3f12c30` (= `px1b-v1`'s training set).
- The run refuses if either hash differs.

**The same rows for every model** in a fold. `scale_absent` applies to all models, so the eligible population and the labels (`red_win` from TBA `winning_alliance`; ties already excluded) are identical across models.

**Selection moments:** each event's latest qualification `scheduled_time` + 1 minute, read read-only from the isolated `stratai_test` copy. The serving database is never touched.

## 2. Folds: walk-forward, event-disjoint, time-ordered

| Fold | Train | Test | Exclusions |
|---|---|---|---|
| **F0** (2024) | 2024 rows with `scheduled_time` < T. T = the selection moment of the event at index ⌊n/2⌋ of the 2024 events, sorted by (selection moment, `event_key`) | rows of 2024 events whose selection moment ≥ T | rows at or after T from events selected before T: counted, used nowhere |
| **F1** (2025) | every 2024 row | every 2025 row | none |
| **F2** (2026) | every 2024 and 2025 row | every 2026 row | none |

**Structural assertions for every fold** (the run refuses if any fails, and they are recorded):
- every training row's `scheduled_time` < every test event's selection moment;
- training events ∩ test events = ∅.

Every feature (EPA, history, scales) is already a selection-moment value with `as_of` before its own match (D18; PX-1b spec §3). The column selection and RMS scaling are fit on the fold's training rows only.

**2024 has no season-level fold:** no 2023 PX rows or 2023 EPA exist in the database. F0 is the only 2024 evaluation possible without new extraction. No extraction is launched.

## 3. Models (each refit per fold on that fold's training rows only; nothing registered)

| Model | Definition | Valid in |
|---|---|---|
| **PX-1b** | PX-1b spec §2–§4 (D16 normalization, column rules, round interactions, RMS, no intercept, C = 1.0, lbfgs) | F0, F1, F2 |
| **PX-1 raw** | PX-1 spec §2–§3 (the original design) | F0, F1, F2 |
| **Seed-only** | PX-1 spec §4: the seed difference alone, no intercept | F0, F1, F2 |
| **M6/M7** | frozen `win_prob_xgb_calibrated` `d18`, **not refit**, loaded with its pinned sha256 `c76d3299…`, applied to the selection-moment features as in the PX-1 gate | **F2 only.** It was fit on the 2024–2025 rows of every competition level (15,824 model + 3,956 calibration rows), so in F0 and F1 it is **in-sample** and reported as "not valid" |

The fold models' coefficients and columns are recorded. No model is registered.

## 4. Metrics (per model per fold)

**Per model:**
- rows, events;
- log-loss (`ml.backtest.metrics.log_loss`), Brier, ROC-AUC;
- ECE with 10 equal-width bins, and 10 reliability bins;
- **calibration slope and intercept:** an unpenalized logistic regression of the outcome on logit(p), with p clipped to [1e-12, 1 − 1e-12]. A slope below 1 means overconfident;
- mean |logit| on the training rows (in-sample) and the test rows, and their ratio (not defined for M6/M7);
- the share of predictions below 0.1 or above 0.9.

**Paired comparisons,** on identical test rows: PX-1b − comparator, as the per-match log-loss difference and the per-match Brier difference.
- **Method:** the event-bootstrap 95% CI (2,000 resamples, seed 20261010, percentile; `ml.backtest.bootstrap`).
- **Diagnostic reading of the frozen P6-Q3 rule:** "CI entirely below 0".

**Per event:** each model's log-loss and n per test event, and the share of events where PX-1b's log-loss is lower than each comparator's.

**Pooled F1 + F2** (season-level folds): paired log-loss vs seed-only and vs PX-1 raw over the union of test rows, with the event bootstrap over the union of events.

**A metric that cannot be computed** (for example AUC with a single class) is recorded as null, with the reason.

## 5. Reading the results (fixed now, before any result)

For each fold and valid comparator:
- **statistically supported** = the paired log-loss CI lies entirely below 0;
- **point estimate only** = the mean is < 0 but the CI includes 0;
- **not better** = the mean is ≥ 0.

| Question | How it is answered |
|---|---|
| Q1: beats the baselines on each valid held-out season? | the per-fold readings |
| Q2: consistent across seasons and events? | the sign of the point estimate in F0, F1 and F2 for each comparator, plus the per-event shares |
| Q3: better probability quality and calibration? | ECE, calibration slope and the Brier CIs, PX-1b vs PX-1 raw and vs seed-only (and M6/M7 in F2) |
| Q4: statistically supported improvement, or point estimates only? | from Q1 |
| Q5: promising enough for FINAL-1? | "**promising**" iff, in F2, PX-1b is statistically supported vs **both** FINAL-1 comparators (M6/M7 and seed-only), **and** in F1 it is statistically supported vs seed-only. Otherwise "**not demonstrated**". Either way this is advisory: FINAL-1 on 2027 remains the only acceptance |

## 5a. Record and limits

- **Record:** `.agent/phase6/results/p6_px_hv1.json`, write-once. It carries the commit, this spec's blob, the cache sha256, the population fingerprint, the M6/M7 sha, the seed, the fold assertions and every metric.
- **Runtime:** one run within the 45-minute budget (a few minutes expected). The run is pure computation on the cache, apart from one read-only query.
- **Not changed after a result.**
