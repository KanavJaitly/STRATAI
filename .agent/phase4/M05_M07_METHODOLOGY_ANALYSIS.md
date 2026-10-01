# Phase 4 — M5 / M7 Methodology Analysis (decision input)

2026-09-30. Analysis only. Nothing here changes methodology, acceptance criteria, M4, M5, M7 or EPA, and M6/M7/M11/M13 were not run.

- Evidence: `results/m05_m07_methodology_analysis.json`, produced by `results/m05_m07_methodology_analysis.py` (read-only, checkpointed per section, 20 s).
- Discipline: no new held-out 2026 metric was computed for M5. Its evaluative numbers use only the 2024/2025 training seasons; 2026 appears only as distributions. M7 uses the frozen M4 baseline's own held-out predictions, rebuilt exactly; all 6 frozen M4 metrics match bit-for-bit.

## Decisions needed before Phase 4 can continue

1. **Order.** May M6 → M7 → M11 proceed while M5 is open? Neither M6 nor M7 depends on M5. Under D9 as written, execution stays stopped at M5.
2. **M5 path.** Either:
   - (a) record M5 as failed, leaving the ranking half of the phase's done-means unmet; or
   - (b) approve one pre-registered methodology change from §2.3 and re-run M5 once under D9.
3. **Ranking decision time.** Only needed if 2(b): at what point is "final rank" predicted (§2.2)? 60% of today's evaluation snapshots are taken after qualification ends.
4. **M7 band definition.** As implemented it cannot be reliably passed by a perfectly calibrated model (§3). Choose one of §3.4's options.
5. **M7 symmetry.** Must the calibrated M7 output keep M6's exact red/blue symmetry? Neither calibrator guarantees it today.

The rest of this document is the evidence for these five.

---

## 1. M7 — the band check

### 1.1 Exact definition (as implemented)
`check_calibration_band(compute_reliability_bins(preds, labels), target=0.60, tolerance=0.02)`:

- Bins are 10 equal-width bins with index `min(int(p·10), 9)`.
- The checked bin is the one with `lower ≤ 0.60 < upper`, i.e. **[0.60, 0.70)**.
- It passes iff **0.58 ≤ observed win rate ≤ 0.62** (inclusive).
- `within_band` is None if the bin has fewer than 30 predictions.
- D6 adds: ECE < 0.05 is the acceptance threshold; "the band applies where the bin has sufficient observations".

### 1.2 Under perfect calibration, on the actual 15,027 held-out M4 predictions

| Quantity (bin [0.60, 0.70)) | Value |
|---|---|
| Predictions in bin | **605** |
| Mean predicted probability | **0.6501** |
| Expected wins if perfectly calibrated (sum of p) | **393.31** (rate 0.6501) |
| Standard error of the rate (Poisson-binomial) | **0.0194** |
| Upper bound 0.62 in standard errors | −1.56 SE |
| **P(observed rate in [0.58, 0.62]) if perfectly calibrated** | **6.47%** exact (normal approximation 5.99%) |
| Actual M4 baseline result | 337 wins, rate **0.5570** → `within_band = False` |
| Bin's contribution to observed ECE (0.1194) | 0.00375 (**3.1%** of it) |
| Bin's expected contribution if calibrated | 0.00062 |

Confirmation: 100 trials with these exact predictions, labels drawn so the predictions are perfectly calibrated, scored by the real M7/D6 functions (seed 20260930, 1.4 s):
- The band check passed **8/100** (consistent with 6.47%).
- The bin's win rate averaged 0.648 (sd 0.020).
- ECE averaged **0.0059** (max 0.0095); 100/100 trials were below 0.05.

### 1.3 Why it can't be reliably passed
- For a perfectly calibrated model, the expected win rate in a bin equals the bin's mean prediction m. For [0.60, 0.70), m lies inside that interval; for any spread-out set of predictions it is near 0.65.
- The check asks for a rate ≤ 0.62. As the bin's sample grows the rate converges to m, so whenever m > 0.62 **the chance of passing goes to 0 as data increases**: more evidence makes a perfect model fail more surely.
- It passes only when the bin's predictions happen to sit at 0.60–0.62. That is a property of the model's prediction spread, not of calibration.

Root cause, in order:
1. **Target statistic.** The rate is compared with the bin's lower edge (0.60), not with what the bin predicts (its mean, about 0.65).
2. **Tolerance vs sample size.** ±0.02 is about 1 SE at n ≈ 600. Even a correctly specified check passes a perfect model only about two-thirds of the time (§1.4).
3. **Acceptance rule.** The pass/fail has no allowance for sampling error.

The bin width itself is not the problem.

### 1.4 Options (analysis only, none chosen)

| Option | Definition | P(pass) for a perfectly calibrated model on these predictions |
|---|---|---|
| Current | [0.60, 0.70) rate within 0.60 ± 0.02 | 6.5% |
| A | same bin, rate within its **own mean prediction** ± 0.02 | 69.5% |
| B | bin **centred on 0.60**, [0.55, 0.65) (n = 587, mean 0.602), rate within 0.58–0.62 | 66.5% |
| C | A or B with tolerance max(0.02, 2·SE), i.e. ±0.039 at n ≈ 600 | about 95% by construction |
| D | ECE < 0.05 (D6) as the only gate; band reported as a diagnostic | expected ECE if calibrated 0.0059 (8× margin) |

Note: the observed M4 baseline is miscalibrated (ECE 0.1194, mostly from the outer bins [0, 0.1) and [0.9, 1.0), together 61% of ECE). It would fail any of these definitions, which is the intended outcome for an overconfident model.

---

## 2. M5 — the ranking model

### 2.1 Facts requested

**Target.** Each team appearance gets ±|score margin| of its match: + if its alliance won, − if it lost (direction from TBA's label), 0 for a tie. All three alliance partners receive the same value; the target does no attribution. Units: game points (total score including fouls).

**Features** (`TEAM_FEATURE_NAMES`; snapshot strictly before as_of):

| Feature | Unit / scale | Kind |
|---|---|---|
| epa_total / epa_auto / epa_teleop / epa_endgame | game points per team, from the team's latest prior concluded event (D13 + STRATAI availability) | EPA-derived; season game points |
| average_score, score_stddev | alliance total score (with fouls) at this event before as_of | raw game points |
| average_auto_points | alliance auto points at this event (M11, deliberately unscaled per D12) | raw game points |
| consistency_rating | 100·(1 − CV), clipped 0–100 | scale-free |
| reliability_score | 100 · matches_used / matches_scheduled | scale-free (100 in practice) |
| matches_considered, matches_used | counts | scale-free |
| defense_* / feeding_* | 0–5 scouting scale / counts | absent in all three seasons (0% present) |

**Distributions** (team appearances; p50 / p90; full tables in the JSON):

| | 2024 | 2025 | 2026 |
|---|---|---|---|
| week-1 score mean / sd (season scale) | 45.0 / 20.4 | 83.0 / 36.8 | 132.0 / 93.8 |
| target sd; mean \|target\| | 30.9; 24.6 | 48.1; 38.0 | **155.2; 116.9** |
| epa_total (present share) | 16.5 / 31.0 (55%) | 22.1 / 51.5 (95%) | 36.4 / 117.4 (97%) |
| epa_endgame | 1.5 / 3.0 | 2.1 / 7.1 | 7.2 / 28.0 |
| average_score | 49.5 / 80.3 | 90.0 / 159.0 | 150.8 / 344.7 |
| score_stddev | 15.4 / 23.0 | 26.6 / 40.1 | 70.8 / 123.8 |
| average_auto_points | 17.2 / 27.5 | 16.3 / 33.5 | 29.8 / 66.6 |

**Shift, train (2024 + 2025) vs 2026** (KS statistic; share of 2026 values above the training maximum):

| Feature | KS | Above training max |
|---|---|---|
| target | 0.254 | 1.4% |
| epa_total | 0.346 | 9.8% |
| epa_endgame | 0.492 | 26.9% |
| epa_teleop | 0.316 | 7.4% |
| average_score | 0.557 | 7.6% |
| score_stddev | 0.776 | 2.0% |
| average_auto_points | 0.449 | 5.6% |
| consistency_rating | 0.331 | 0% |
| match counts | about 0.008 | 0% |

For scale, 2024 vs 2025 alone already shows KS 0.22 (epa_total) and 0.55 (average_score).

**Why iteration 2.**
- Early stopping holds out the temporally last 20% of training rows: 2025-03-23 → 2025-04-19, 6,893 rows. That slice's target sd is 49.5, against 38.1 for the rows the model was fit on, which mix 2024 (sd 30.9) and early 2025.
- Validation RMSE bottoms at round index 2 (48.74, against 49.48 for a constant prediction) and then rises while training RMSE keeps falling. The model has learned the earlier, smaller-scale target, so further rounds hurt on the later, larger-scale one.
- Ranking quality on that 2025 validation slice (85 events with ranks) peaks at **0.50** (around 10 rounds), against **0.65 for raw EPA**. So the model trails raw EPA even within 2025, before any cross-season extrapolation.

**Two causes, compounding:**
- (i) the target gives all partners the same margin, so it cannot separate teams on an alliance; EPA's update attributes performance team by team;
- (ii) raw game-point targets and features change scale by season, which takes it from 0.50 in-distribution to 0.39 on 2026.

### 2.2 Information availability and leakage

- **Same constraints for baseline and model.** Both are scored by the same `run_ranking_backtest`, on the same fold, against the same final ranks, from the same per-(team, event) snapshot (the team's latest held-out appearance). The baseline reads only `epa_total` from that snapshot; the model reads all 17 features. The model has *more* information than the baseline, never less.
- **Snapshot timing (affects both; decision 3).** In 2024 and 2025, **60%** of those snapshots come from after the event's last qualification match. At that point in-event `average_score` has event-level Spearman **0.82 (2024) / 0.78 (2025)** with final rank, against 0.52 / 0.58 for prior-event EPA. Final qualification rank is fixed by those same matches, so in-event features at that time are close to the outcome.
  - This does not explain the failure: it favours the model.
  - It does mean any future M5 that leans on in-event features would be scored on information unavailable at a pre-event decision point.
- **Label shuffle.** Over 8 seeds, Spearman ranged −0.28 to +0.27 (mean **0.023**), against 0.39 trained on real labels. Training on noise gives chance. Leakage would also *raise* a model's score, and this failure is a shortfall, so leakage cannot explain it.

### 2.3 Would it also fail with Statbotics EPA?

**Yes, by construction.**
- Statbotics EPA uses the same method and the same per-season game-point units. STRATAI's week-1 statistics reproduce Statbotics' published unitless EPA for team 1678.
- The target does not involve EPA at all, and cause (i) is independent of the EPA source.

This cannot be measured directly: `team_event_stats` has 0 rows.

### 2.4 Candidate changes (analysis only; none chosen)

Two facts apply to every option:
- **The ranking baseline is unaffected.** Each transform below is a positive monotone map within an event, so it leaves the raw-EPA ranking baseline, which is within-event order, exactly at **0.5951**. M4's ranking baseline would not need re-freezing unless decision 3 changes the snapshot.
- **Where a change lives decides how far it reaches.** Inside M5 only, it is contained to M5. In the shared `team_vector`, it also changes M6's inputs and requires re-running M8's audit, re-registering under M10's feature-list guard, updating M11's parity tests and M12's API. (M6/M7 have no frozen numbers yet.)

| Candidate | Definition | Information needed and causal availability | Leakage risk | Distribution effect (KS, train vs 2026) | Interpretability; fit with M5's goal |
|---|---|---|---|---|---|
| **S1** Own-season scale | x / s_Y, target / s_Y; s_Y = STRATAI week-1 score sd of season Y | s_Y is known once week 1 ends; week-1 snapshots need a fallback (e.g. the S2 value), or a running scale from matches before as_of | the week-1 look-ahead (documented) unless running or prior-season | target 0.254 → **0.029**; epa_total 0.346 → 0.287 (over-corrects: 2026's sd/mean ratio is 0.71, against 0.45 / 0.44) | "points in units of this season's spread"; keeps absolute strength within a season |
| **S2** Prior-season scale | x / s_{Y−1} | fully causal from day 1; 2024 has no prior inside STRATAI data, so 2024 rows drop out or need S1 | none | epa_total **0.069**; average_score 0.116 — but only because 2026/2025 growth happened to match 2025/2024. It cannot see a new game's scale | simple; fragile across game changes |
| **E1** Event-relative | percentile (or ratio to event mean) of x among the event's teams at the decision time; target as within-event normalized margin | the event roster and each team's snapshot at the decision time — causal | must use only snapshots ≤ the decision time (decision 3) | epa_total **0.004**, average_score **0.002** (shift removed by construction) | "strength relative to this field"; matches the within-event evaluation exactly; gives up cross-event comparison |
| **R1** Within-event ranking objective | pairwise or NDCG ranker (e.g. XGBoost rank:pairwise), groups = training events, label = final qualification rank of 2024/2025 events | training-season final ranks (synced); features at a pinned decision time | the snapshot-timing concern is acute (labels and features from the same matches) — requires decision 3 | none by itself; trees still split on raw values, so pair with E1 or S1 | optimizes the evaluation directly. **Note:** M3's accepted `Model.fit(rows)` has no access to ranks, and this formulation was considered and declined on 2026-09-25. Needs an interface decision |
| **T1** Attribution-aware target | e.g. a team's alliance margin minus its partners' prior expected contributions, or a future-event EPA delta | partners' prior EPA (causal, D13) | low | target scale still varies by season; combine with S1 or E1 | addresses cause (i), which every scale fix leaves untouched; closest to what EPA already does |

Any choice needs, before results:
- a pre-registered specification (target, features, objective, decision time, hyperparameters as they are);
- one re-run under D9;
- for a shared-vector change, M8 re-run and M10 re-registration.

The M5 gate itself (D5: Spearman strictly above 0.5951) would be unchanged by any of them.
