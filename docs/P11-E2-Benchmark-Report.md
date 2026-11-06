# P11A E2 historical alliance-score benchmark and human-approval evidence package

**Status: research evidence (2026-11-05). It approves nothing.** `docs/P11-RecommendationIntelligence.md` stays
PROPOSED / NOT APPROVED and was not changed. No threshold is approved here, and no gate is passed. Every candidate
range below is input for a human decision.

**What it is.** A benchmark of how accurately the specification's alliance-score methodology (AS-1, spec B5)
predicts real 2024–2026 FRC playoff alliance scores, using only information available at each event's
alliance-selection moment. It also includes:
- simulations for the prior, independence and identifiability tolerances;
- an audit of TBA's per-robot fields.

**Who reads it.** The owners deciding P11A-Q3 (δ, π), the A3.2/B5 tolerances and the G2 bound. Also a future
implementer.

**Where everything is.**
- Tooling: `research/p11_e2/` (isolated research scripts, not imported by any production code).
- Fixed protocol: `research/p11_e2/PROTOCOL.json`, frozen before any run.
- Outputs: `research/p11_e2/results/`.
- Raw data: `research/p11_e2/cache/` (git-ignored).

**Two parts.**
- §1–§18 are the **original evaluation** (2026-11-05). Their results are unchanged.
- §19–§22 are a **follow-up investigation** (2026-11-06), run under `research/p11_e2/FOLLOWUP_PROTOCOL.json`, which
  was fixed before any follow-up analysis.
- Two reporting corrections to the original part are marked **Corrected 2026-11-06**: the run accounting (§18) and
  the 2025 endgame field status (§15, §17).

**Value labels used throughout:**
- **observed:** a recorded match result;
- **model prediction:** a model's output on pre-selection data;
- **simulation output:** synthetic truths on real schedules;
- **inference:** this report's interpretation.

---

## 1. Executive summary

**The population.** E2 ran on 17,771 real playoff alliance appearances (8,848 red-vs-blue pairs) from 587 official
events in 2024–2026. Every prediction used only the event's qualification results (all before the selection moment)
and earlier, already-ended events.

**What the evidence shows:**
1. **AS-1, as far as it can be implemented, beats the simple baselines by a wide margin.**
   - No-foul MAE: 30.2 points over all seasons, against 44.3 (team average), 49.5 (prior-event estimate) and 58.3
     (event mean). The 95% CIs do not overlap.
   - It is **not better than unshrunk least-squares OPR**: paired MAE difference 0.01 [−0.22, 0.24] points.
     - OPR is better in 2024 and 2025, by 0.6 and 1.1 points.
     - AS-1 is better in 2026, by 1.6 points.
   - AS-1 with independent individual priors is marginally better than the current-event joint model (−0.18
     [−0.32, −0.06]).
2. **Playoff alliances outscore their qualification-based prediction.** Every model under-predicts. AS-1's bias is
   −6.1 points overall: −6.9 in 2024, −10.7 in 2025, −0.9 in 2026.
3. **AS-1's predictive intervals are too narrow for playoffs.** Nominal 80% covers 68.2% [67.3, 69.0], and nominal 95%
   covers 86.8%. Standardized residuals have SD 1.27, not 1. This is model misspecification for the playoff context
   (bias plus extra playoff variance), not an identifiability problem: the simulations at real schedule sizes are
   well calibrated.
4. **Expected-score differences rank alliances usefully, but imperfectly.** The sign of the expected red−blue
   difference matches the single-match outcome in 75.7% of non-tie matches.
   - The difference forecast's calibration slope is 0.91.
   - Turned into P(red outscores blue in this match), with match noise included (a calibration check, not a served
     win probability), it is reasonably calibrated overall (ECE 0.032, Brier 0.165).
   - It is **overconfident when the blue alliance is strongly favoured.**
5. **δ and π cannot yet be responsibly approved.**
   - The uncertainty that P(Δ) is built from comes from the same model whose intervals under-cover.
   - Classifications shift by about 11–12% of comparisons per grid step.
   - Score scales differ 6× between seasons (playoff alliance SD 26 / 50 / 148 points), so a single absolute δ cannot
     serve every season.
6. **Ignoring covariance between robot estimates has little practical effect** at real FRC schedule sizes. On real
   data, at most 1.1% of comparisons change class, and the predictive SD changes by +0.4% (median). In simulation, at
   most 3.1% of classifications change. Coverage moves by up to 4.8 points, but only in the stress case of three
   matches per team at σ/τ = 3.
7. **Prior dependence (A3.2).**
   - The prohibited plug-in and the joint current-event model are indistinguishable at real schedule sizes.
   - They separate only with few matches and high noise. At cap 3 and σ/τ = 3, joint covers 62.0% and plug-in
     57.3%.
   - **Both under-cover** there, because neither propagates uncertainty in the variance hyperparameters.
   - Independent priors with correctly stated variance stay near nominal (78–80%).
8. **Identifiability matters.** Per-robot coverage falls well below nominal for robots with:
   - three or fewer matches;
   - fewer than 12 distinct partners;
   - a maximum posterior correlation with another robot of 0.5 or more;
   - or a joint-model data weight below 0.5.

   A REML degeneracy (σ̂² → 0 on short schedules) produced very narrow, badly overconfident intervals.
9. **No TBA per-robot field qualifies as individual numerical ground truth.** All 18 are categorical. 15 are partial.
   The three 2025 `endGameRobot` fields are unverified candidates for the whole 2025 endgame component.
10. **Not validly evaluable here:**
    - AS-1's caps and shared-resource rules (no approved GameSpec);
    - the project's canonical TBA/D18 data path;
    - G2 detection of known anomalies (no DQ'd playoff alliance in the population);
    - individual-robot validation (E1b);
    - any win probability.

---

## 2. The E2 definition used, and its mapping to the specification

| Spec element (`docs/P11-RecommendationIntelligence.md`) | As implemented here |
|---|---|
| §20 E2: AS-1 vs actual formed playoff alliances' component and total scores, with features at the selection moment | Every playoff alliance appearance (the three robots recorded as playing), predicted from that event's qualification results only. Selection moment = the last qualification match's time |
| Observed truth | Recorded alliance auto, teleop, endgame, no-foul and total points |
| Metrics: MAE/RMSE, 80% interval coverage | Plus bias, median AE, percentiles, 50/90/95% coverage, event-cluster bootstrap CIs, and pairwise comparisons |
| Baselines: additive A3 sum, additive prior-event EPA, PX-1 composition sums | A3 sum = AS1_joint (no interaction terms). "Prior-event EPA" = M2: our own prior-event estimate from recorded results, because point-in-time EPA cannot be reconstructed here (§5). PX-1 composition sums: **not evaluated** (needs the project's registry artifacts and D18 EPA, unavailable here). Added: event mean (M0), team average (M1), plain OPR (M3) |
| A3.2 priors (i) individual, (iii) current-event joint | AS1_indep_prior (i, with fallback to iii) and AS1_joint (iii). (ii) (an independent population prior) is evaluated in simulation only |
| A3.2 prohibited plug-in | AS1_plugin, a diagnostic only |
| B5.2 joint covariance; B5.3 no independence by default | AS1_joint uses the full posterior covariance. AS1_joint_diag is the independence comparator |
| B5.2(c) season rules with caps (Monte Carlo) | **Not evaluated.** No approved GameSpec or B4 configuration exists, so every component is treated as linear (uncapped) |
| B6 comparison on Δ under estimation uncertainty | The red−blue expected-score difference with its full-covariance estimation SD; the δ/π grid in §10 |

---

## 3. Repository and data inventory

| Item | Exists? | Used? |
|---|---|---|
| The project PostgreSQL (canonical TBA data, D18 EPA, model registry) | Not on this machine. The build machine has no PostgreSQL, and no TBA key is configured | No |
| AS-1 / A3 implementation in the repo | **No.** P11A is a proposed spec only | Implemented here as research code (`research/p11_e2/model.py`), from spec A3.2 and B5 |
| GameSpec (`data/game_spec.py`), approved specs | Schema yes; **no approved spec for any season** | No (caps cannot be evaluated) |
| P5-M7 component adapters (`ml/features/score_components.py`) | Yes | Not directly. Statbotics' per-alliance components, with the parity auto + teleop + endgame = no-foul checked on every row |
| Backtest harness (`ml/backtest/`) | Yes | Not reused. It operates on the project's DB-assembled feature rows, which do not exist here |
| Historical dumps in the repo | None (only two scouting CSVs) | — |
| Statbotics public API v3 | Reachable; no key | **Yes.** Recorded results only (§5) |
| TBA public OpenAPI schema | Reachable | Yes, for the field audit (§15) |

**Data actually used.**
- Statbotics pages for each season are stored raw, with sha256 (`cache/raw/<season>/manifest.json`):
  - 2024: 18 pages, 190 events, 16,979 matches;
  - 2025: 19 pages, 203 events, 17,867 matches;
  - 2026: 20 pages, 215 events, 18,164 matches.
- Fetched 2026-11-05 23:35–23:40 UTC.
- 2027 was never requested. The fetcher refuses it.

---

## 4. Historical population and exclusions

**Included:** official events of types regional, district, district_cmp and champs_div. Statbotics' event lists
contain no off-season events.

| Season | Events (total → included) | Qualification alliance rows | Playoff alliance predictions | Playoff matches | Red-vs-blue pairs |
|---|---|---|---|---|---|
| 2024 | 190 → 184 | 27,922 | 5,602 | 2,807 | 2,795 |
| 2025 | 203 → 198 | 29,417 | 5,980 | 2,997 | 2,983 |
| 2026 | 215 → 205 | 29,690 | 6,189 | 3,119 | 3,070 |
| **All** | **608 → 587** | **87,029** | **17,771** | **8,923** | **8,848** |

**Exclusions** (every one logged in `cache/population/population_<season>.json`, with its key):

| Reason | 2024 | 2025 | 2026 |
|---|---|---|---|
| Event: Einstein (no qualification) | 1 | 1 | 1 |
| Event: fewer than 12 qualification matches | 4 | 4 | 9 |
| Event: no valid playoff rows | 1 | 0 | 0 |
| Qualification alliance: DQ'd team (excluded from fitting) | 158 | 185 | 338 |
| Qualification alliance: missing result | 14 | 45 | 0 |
| Qualification alliance: parity failure (auto + teleop + endgame ≠ no-foul) | 0 | 5 | 0 |
| Playoff alliance: missing result | 10 | 14 | 49 |
| Playoff alliance: timestamped before the event's last qualification match | 30 | 28 | 0 |
| Playoff alliance: a robot with no qualification row | 2 | 0 | 2 |
| Playoff alliance: DQ'd team | 0 | 0 | 0 |

**Notes on the exclusions:**
- **Pairs:** a playoff match yields a red-vs-blue pair only if both alliances are included. 75 matches lost one side.
- **Robots without a prior event:** M2 and AS1_indep_prior have no prior-event estimate for about 46% of robots
  (the share with one: 54.1% / 54.0% / 54.7%). M2 then uses the event mean/3. AS1_indep_prior uses the population
  fallback. Both are counted, not dropped.
- **Missing-data detail:** per-event listings are in the population files.

---

## 5. Temporal-leakage safeguards

1. **Selection-moment information set.** Every AS-1 and baseline fit uses only the event's qualification rows. Every
   included playoff row is timestamped after the last qualification match. The 58 that were not are excluded, never
   used as inputs.
2. **No in-playoff updating.** Earlier playoff matches of the same event are never used.
3. **Cross-event inputs** (M2's prior-event values and AS1_indep_prior's priors, and the drift variance τ_drift²)
   use only same-season events whose `end_date` is strictly before the target event's `start_date`.
4. **No cross-season information** (different games).
5. **No Statbotics model output is an input.** No EPA, no `pred` fields, no event metrics. Today's values for past
   events come from the current Statbotics model and are not point-in-time.
6. **Limits stated, not hidden:**
   - **Corrections:** recorded results are today's official values. A result corrected after the event would differ
     from what was known at selection. This is rare, and is not measurable here.
   - **Hyperparameters per event:** σ² and τ² are REML-fitted per event, from that event's qualification rows only.
     No pooled hyperparameter crosses time.
7. **The 2027 holdout** was never requested, read or used.

---

## 6. Benchmark methodology and baselines

**Per event and component** (auto, teleop, endgame, no-foul, each fitted separately):

| Model | What it is | Information |
|---|---|---|
| M0 event mean | The event's mean qualification alliance points | This event's qualifications |
| M1 team average | Mean of the three robots' qualification alliance averages | Same |
| M2 prior-event | Sum of each robot's AS1_joint posterior mean at its most recent earlier same-season event (else event mean/3) | Earlier events only |
| M3 plain OPR | Least-squares per-robot contributions (ridge 1e-6); prediction variance s²(1 + a'(A'A)⁻¹a) | This event's qualifications |
| **AS1_joint** | Spec A3.2(iii) + B5. A hierarchical Gaussian, x_r = μ + u_r, u_r ~ N(0, τ²), y = Ax + e, e ~ N(0, σ²). μ is flat and integrated. σ², τ² by REML. Prediction a'x̂; variance a'Σa + σ² (full covariance) | This event's qualifications |
| AS1_indep_prior | Spec A3.2(i). Prior N(prior-event posterior mean, its variance + τ_drift²) for robots with an earlier event. τ_drift² is from earlier pairs (≥ 30 pairs, else none). Others: population fallback (iii) | Both |
| AS1_plugin | The prohibited plug-in (μ fixed at mean(y)/3), a diagnostic only | This event's qualifications |
| AS1_joint_diag | AS1_joint's mean, with the variance from the diagonal of Σ only | Same |

**Further details:**
- **Total score** = the no-foul prediction plus the event's mean qualification foul points received. Its variance
  adds the qualification foul variance.
- **Real-data hyperparameters** (no-foul, median across events): σ = 10.4 / 19.3 / 43.5 and τ = 8.5 / 16.3 / 48.6
  points for 2024 / 2025 / 2026, so σ/τ ≈ 1.2 / 1.2 / 0.9. τ_drift was available for 135 / 142 / 144 events.
- **REML implementation.** The 2026 run used an exact n×n (Woodbury) evaluation of the same REML likelihood, after
  the direct N×N form ran past its time budget. Both forms agree to ≤ 2.1×10⁻⁶ relative on every sampled event
  (`model.reml` vs `model.reml_direct`). 2024 and 2025 used the direct form.

---

## 7. Score prediction results

**No-foul alliance points** (*model prediction* vs *observed*; event-cluster bootstrap 95% CIs, 1,000 resamples):

| Season | Model | MAE [95% CI] | RMSE | Bias (pred − actual) | Median AE |
|---|---|---|---|---|---|
| 2024 | M0 event mean | 24.5 [23.6, 25.5] | 30.0 | −22.3 | 21.6 |
| 2024 | M1 team average | 19.4 [18.7, 20.0] | 24.0 | −16.5 | 17.0 |
| 2024 | M2 prior-event | 21.8 [21.1, 22.4] | 26.3 | −19.3 | 19.8 |
| 2024 | M3 plain OPR | **12.8** [12.4, 13.2] | 16.3 | −4.5 | 10.6 |
| 2024 | AS1_joint | 13.4 [13.0, 13.8] | 16.9 | −6.9 | 11.2 |
| 2024 | AS1_indep_prior | 13.3 [12.9, 13.7] | 16.7 | −6.9 | 11.1 |
| 2025 | M0 | 43.3 [41.8, 44.7] | 52.5 | −38.9 | 39.0 |
| 2025 | M1 | 33.6 [32.7, 34.6] | 40.9 | −28.6 | 29.9 |
| 2025 | M2 | 39.1 [37.8, 40.4] | 46.8 | −35.7 | 35.9 |
| 2025 | M3 | **19.9** [19.3, 20.5] | 25.1 | −6.3 | 16.5 |
| 2025 | AS1_joint | 20.9 [20.3, 21.5] | 26.2 | −10.7 | 17.6 |
| 2025 | AS1_indep_prior | 20.8 [20.2, 21.5] | 26.0 | −10.9 | 17.6 |
| 2026 | M0 | 103.5 [99.0, 108.2] | 140.1 | −81.4 | 74.8 |
| 2026 | M1 | 77.3 [74.3, 80.5] | 103.8 | −52.4 | 57.4 |
| 2026 | M2 | 84.8 [82.0, 87.8] | 111.0 | −58.7 | 66.4 |
| 2026 | M3 | 56.0 [53.3, 58.5] | 75.5 | +7.8 | 42.0 |
| 2026 | AS1_joint | 54.4 [52.1, 56.7] | 72.3 | −0.9 | 41.1 |
| 2026 | AS1_indep_prior | **54.1** [51.8, 56.5] | 71.9 | −1.2 | 41.9 |
| All | M3 | 30.2 [28.5, 32.2] | 47.8 | −0.8 | 18.2 |
| All | AS1_joint | 30.2 [28.6, 32.1] | 46.3 | −6.1 | 18.9 |
| All | AS1_indep_prior | **30.0** [28.3, 31.8] | 46.0 | −6.3 | 18.8 |

**Paired MAE difference vs AS1_joint** (no-foul; positive = AS1_joint more accurate):

| Comparator | 2024 | 2025 | 2026 | All |
|---|---|---|---|---|
| M0 event mean | 11.08 [10.36, 11.81] | 22.34 [21.07, 23.60] | 49.10 [45.85, 52.34] | 28.11 [26.26, 29.80] |
| M1 team average | 5.96 [5.53, 6.39] | 12.67 [11.92, 13.43] | 22.95 [20.84, 25.11] | 14.14 [13.12, 15.16] |
| M2 prior-event | 8.34 [7.77, 8.90] | 18.13 [17.05, 19.13] | 30.44 [27.61, 33.26] | 19.33 [18.04, 20.58] |
| M3 plain OPR | −0.61 [−0.74, −0.49] | −1.06 [−1.30, −0.84] | 1.62 [1.03, 2.22] | 0.01 [−0.22, 0.24] |
| AS1_indep_prior | −0.14 [−0.21, −0.05] | −0.12 [−0.27, 0.03] | −0.29 [−0.64, 0.05] | −0.18 [−0.32, −0.06] |

**Components** (AS1_joint MAE, with bias in parentheses; M0 MAE for scale):

| Season | Auto | Teleop | Endgame | Total (incl. fouls) |
|---|---|---|---|---|
| 2024 | 6.3 (−3.1) vs 9.2 | 11.2 (−5.8) vs 16.6 | 2.3 (+0.5) vs 2.5 | 14.5 (−7.8) vs 25.6 |
| 2025 | 6.6 (−3.8) vs 11.8 | 17.4 (−7.3) vs 29.3 | 5.4 (−1.5) vs 7.4 | 20.9 (−10.4) vs 43.2 |
| 2026 | 14.6 (−6.4) vs 24.0 | 37.8 (+6.1) vs 59.6 | 22.4 (−6.1) vs 29.6 | 54.8 (−4.2) vs 106.2 |

**Inference.**
- **Composition-aware models (M3, AS-1) are much better than composition-blind ones.** The large negative biases of
  M0–M2 show that playoff alliances are far stronger than the event average, as expected.
- **Every model still under-predicts playoff scores.** Plausible causes:
  - performance improves over an event;
  - playoff incentives differ (no ranking points);
  - captains select on information beyond qualification results;
  - shrinkage pulls top robots toward the mean. AS-1 is more biased than unshrunk OPR in 2024–2025.
- **No playoff term is added.** A playoff adjustment would be a new term; the spec (B5.5) allows one only if it is
  pre-registered and validated on held-out playoff scores.
- **The benchmark shows no measurable accuracy gain of AS-1 over plain OPR overall.** The small differences change
  sign by season, and they are not meaningful improvements.

---

## 8. Uncertainty and interval calibration

**AS1_joint coverage of observed playoff scores, by nominal level:**

| Season | Target | 50% | 80% | 90% | 95% |
|---|---|---|---|---|---|
| 2024 | no-foul | 0.363 | 0.638 | 0.762 | 0.837 |
| 2025 | no-foul | 0.422 | 0.710 | 0.826 | 0.896 |
| 2026 | no-foul | 0.432 | 0.695 | 0.805 | 0.868 |
| All | auto | 0.405 | 0.672 | 0.785 | 0.854 |
| All | teleop | 0.405 | 0.683 | 0.790 | 0.858 |
| All | endgame | 0.421 | 0.711 | 0.819 | 0.887 |
| All | no-foul | 0.407 | **0.682** | 0.798 | 0.868 |
| All | total | 0.421 | 0.701 | 0.812 | 0.883 |

**80% coverage by model** (no-foul, all seasons): M3 0.704 [0.694, 0.712]; AS1_joint 0.682 [0.673, 0.690];
AS1_indep 0.683; AS1_joint_diag 0.684; AS1_plugin 0.682; M0–M2 0.55–0.59. Mean 80% widths: AS-1 76.7 points; M3 77.8.

**By event** (AS1_joint, events with ≥ 10 playoff predictions; n = 586):
- The median event's 80% coverage is 0.69.
- The 10th–90th percentile range is 0.53–0.83.
- 52% of events are below 0.70.

**Inference.**
- AS-1's intervals are systematically **too narrow** for playoff scores, by a standardized-residual SD of about 1.27
  (§13).
- This holds in every season and every component.
- It is not caused by ignoring covariance or by the plug-in: those variants are indistinguishable.
- The simulations (§11) show the model is well calibrated where its assumptions hold, at real schedule sizes. So the
  miscalibration is the qualification-to-playoff shift: bias plus extra variance.

---

## 9. Alliance comparisons (red vs blue in each playoff match)

The compared quantity is the **expected-score** difference. Outcomes are single matches (*observed*), so even a
perfect expected-score model would mis-rank some matches.

| Model | Sign accuracy (non-tie, n = 8,765) | Difference MAE | Correlation | Calibration slope |
|---|---|---|---|---|
| AS1_joint | 0.757 | 38.2 | 0.749 | 0.91 |
| AS1_joint_diag | 0.757 | 38.2 | 0.749 | 0.91 |
| AS1_indep_prior | **0.762** | 37.5 | 0.761 | 0.92 |
| M3 plain OPR | 0.757 | 38.8 | 0.747 | 0.83 |
| M1 team average | 0.741 | 48.3 | 0.727 | 2.52 |
| M2 prior-event | 0.515 (0.66–0.71 excluding its 25% predicted exact ties) | 49.1 | 0.537 | 0.81 |

**By season (AS1_joint):** sign accuracy 0.718 / 0.761 / 0.788. When the sign was wrong, the actual difference had a
median of 12 / 16 / 42 points (2024 / 2025 / 2026), so wrong preferences are mostly close matches.

**Calibration of the difference distribution.** This is a check on the model only. It is a single-match score
comparison, never served, and **not** a win probability. P(red outscores blue) = Φ(m/√(s²_est + 2σ²)):

| Predicted | 0–0.1 | 0.1–0.2 | 0.2–0.3 | 0.3–0.4 | 0.4–0.5 | 0.5–0.6 | 0.6–0.7 | 0.7–0.8 | 0.8–0.9 | 0.9–1.0 |
|---|---|---|---|---|---|---|---|---|---|---|
| n | 197 | 389 | 518 | 665 | 760 | 923 | 978 | 1,063 | 1,155 | 2,117 |
| Mean predicted | 0.051 | 0.151 | 0.252 | 0.352 | 0.453 | 0.550 | 0.649 | 0.751 | 0.850 | 0.968 |
| Observed | 0.162 | 0.244 | 0.322 | 0.406 | 0.467 | 0.602 | 0.697 | 0.749 | 0.844 | 0.950 |

**Overall:** ECE 0.032 and Brier 0.165 (2024: 0.187; 2025: 0.161; 2026: 0.149). The 80% predictive coverage of the
actual difference, including match noise, is 0.748 (0.691 / 0.824 / 0.726).

**Inference.**
- Expected-score differences carry real ranking information, with sign accuracy around 76%.
- When the model strongly favours blue, red still outscores blue 2–3× as often as predicted. That is consistent with
  the higher seed (red) over-performing its qualification-based estimate.

---

## 10. δ and π sensitivity analysis

**The compared quantity.**
- Δ is the AS1_joint expected-score difference, with its full-covariance **estimation** SD only; single-match noise is
  excluded, as the spec requires.
- The median estimation SD of Δ is 7.5 / 14.1 / 33.1 points by season.
- The season playoff alliance SDs are 26.0 / 50.5 / 148.4.
- The "incorrect preference" rate compares each preference with the single-match outcome, so even a perfect model has
  a floor above zero.

**Absolute δ, all seasons** (shares of 8,848 comparisons; "A" = red):

| δ | π | A pref. | B pref. | Equivalent | Unresolved | Incorrect pref. rate |
|---|---|---|---|---|---|---|
| 0 | 0.8 | 54.8% | 16.2% | 0.0% | 29.1% | 17.5% |
| 0 | 0.9 | 46.9% | 11.4% | 0.0% | 41.8% | 14.7% |
| 5 | 0.8 | 47.4% | 11.7% | 0.0% | 40.9% | 14.6% |
| 5 | 0.9 | 39.6% | 7.9% | 0.0% | 52.5% | 12.1% |
| 10 | 0.8 | 40.7% | 8.5% | 3.0% | 47.8% | 12.7% |
| 10 | 0.9 | 34.0% | 5.5% | 0.1% | 60.4% | 9.8% |
| 15 | 0.8 | 35.3% | 6.3% | 13.2% | 45.2% | 10.9% |
| 15 | 0.9 | 29.6% | 4.1% | 7.4% | 58.9% | 8.3% |
| 20 | 0.8 | 30.8% | 4.9% | 24.6% | 39.7% | 9.9% |
| 20 | 0.9 | 25.3% | 3.3% | 15.6% | 55.8% | 7.9% |
| 30 | 0.8 | 24.0% | 3.2% | 41.8% | 31.0% | 8.7% |
| 30 | 0.9 | 20.0% | 2.2% | 34.3% | 43.4% | 6.7% |

**By season (π = 0.9):**

| δ | 2024 | 2025 | 2026 |
|---|---|---|---|
| 10 | 0.3% equivalent, 78.0% unresolved | 0% equivalent, 65.4% unresolved | 0% equivalent, 39.5% unresolved |
| 20 | 47.2% equivalent | 2.1% equivalent | 0% equivalent |

The same absolute δ means completely different things in different seasons.

**δ relative to the season playoff SD** (π = 0.9):

| Season | δ = 0.1 SD | δ = 0.2 SD |
|---|---|---|
| 2024 | 57.6% unresolved | 66.4% unresolved |
| 2025 | 56.1% unresolved | 65.6% unresolved |
| 2026 | 42.9% unresolved | 52.1% unresolved |

The incorrect-preference rate is 7–16%. Relative δ behaves far more consistently across seasons than absolute δ.

**Stability and event sensitivity (AS1_joint):**
- **Grid steps:** one step in δ changes the class of 12.4% of comparisons on average (max 25.6%). One step in π
  changes 11.4% (max 16.1%).
- **Events:** the share unresolved varies widely between events. At δ = 5, π = 0.8 the event 10th–90th percentile
  range is 13%–67%.

**Inference.**
- **Equivalence** appears only when δ is well above Δ's estimation SD. That makes `practically_equivalent` rare at
  small δ, and season-dependent at large δ.
- **Raising π** lowers the incorrect-preference rate (for example 17.5% → 14.7% → 12.0% at δ = 0, for π = 0.8 → 0.9 →
  0.95), at the cost of more unresolved comparisons.
- **Why these numbers cannot be approved now.** Δ's SD comes from a model whose intervals under-cover (§8). P(Δ > δ)
  is therefore likely overstated, and π values would not mean what they say.

---

## 11. Prior dependence and coverage (simulation output)

**Setup** (fixed in `PROTOCOL.json` before running):
- **Schedules:** real qualification schedules of 24 seeded, size-stratified events, 8 per season.
- **Truths:** x ~ N(30, 10²).
- **Grid:** σ/τ ∈ {0.5, 1, 2, 3} × matches-per-team cap {3, 6, 9, none} × equal/unequal observations × three noise
  structures (independent, shared match effect ρ = 0.5, robot-specific heteroscedastic) × 3 replicates.
- **Scenario fairness:** every prior scenario sees the same data in each replicate. Real data sits at σ/τ ≈ 0.9–1.2
  and about 10–12 matches per team.

**Per-robot coverage, pooled over cells** (nominal 50 / 80 / 95):

| σ/τ | Scenario | Cov50 | Cov80 | Cov95 | Width80 | RMSE | Alliance cov80 |
|---|---|---|---|---|---|---|---|
| 0.5 | indep individual | 0.484 | 0.777 | 0.930 | 5.66 | 2.47 | 0.775 |
| 0.5 | indep population | 0.489 | 0.787 | 0.938 | 7.16 | 3.21 | 0.787 |
| 0.5 | current-event joint | 0.485 | 0.783 | 0.936 | 7.08 | 3.25 | 0.781 |
| 0.5 | plug-in (diagnostic) | 0.485 | 0.782 | 0.935 | 7.08 | 3.25 | 0.781 |
| 1.0 | indep individual | 0.491 | 0.789 | 0.940 | 8.50 | 3.49 | 0.784 |
| 1.0 | indep population | 0.492 | 0.790 | 0.942 | 11.54 | 4.82 | 0.787 |
| 1.0 | joint | 0.481 | 0.777 | 0.933 | 11.32 | 4.89 | 0.774 |
| 1.0 | plug-in | 0.481 | 0.777 | 0.933 | 11.31 | 4.89 | 0.773 |
| 2.0 | indep individual | 0.491 | 0.790 | 0.945 | 10.93 | 4.37 | 0.788 |
| 2.0 | indep population | 0.494 | 0.793 | 0.945 | 17.13 | 6.86 | 0.792 |
| 2.0 | joint | 0.464 | 0.750 | 0.907 | 16.23 | 7.10 | 0.751 |
| 2.0 | plug-in | 0.461 | 0.746 | 0.900 | 16.12 | 7.10 | 0.740 |
| 3.0 | indep individual | 0.496 | 0.797 | 0.948 | 11.82 | 4.66 | 0.794 |
| 3.0 | indep population | 0.494 | 0.798 | 0.947 | 20.28 | 8.01 | 0.789 |
| 3.0 | joint | 0.435 | 0.707 | 0.856 | 18.31 | 8.44 | 0.708 |
| 3.0 | plug-in | 0.426 | 0.691 | 0.834 | 17.90 | 8.44 | 0.676 |

**Joint vs plug-in by matches-per-team cap** (80% coverage):

| σ/τ | Cap 3 | Cap 6 | Cap 9 | No cap |
|---|---|---|---|---|
| 0.5 | 0.740 / 0.739 | 0.797 / 0.797 | 0.793 / 0.792 | 0.801 / 0.801 |
| 1.0 | 0.734 / 0.732 | 0.787 / 0.787 | 0.793 / 0.793 | 0.794 / 0.794 |
| 2.0 | 0.687 / 0.671 | 0.756 / 0.754 | 0.779 / 0.779 | 0.779 / 0.779 |
| 3.0 | 0.620 / 0.573 | 0.706 / 0.694 | 0.750 / 0.747 | 0.752 / 0.750 |

**Noise structures** (joint model, σ/τ = 1, 80% robot coverage):
- independent: 0.780 / 0.772 (equal / unequal observations);
- shared match effect: 0.781 / 0.770;
- heteroscedastic: 0.792 / 0.768.

Unequal observations cost about 1 point, and correlated noise costs about 1 point.

**Inference.**
- **Double counting.** At real schedule sizes, the plug-in's double counting changes coverage by under 0.2 points. It
  matters only with few matches and high noise.
- **The bigger short-schedule problem is shared.** Both joint and plug-in treat σ̂² and τ̂² as known (empirical Bayes)
  and under-cover. Independent priors with correctly specified variance stay near nominal at every σ/τ.
- **Caveat on the independent priors.** That calibration was given the true prior error variance. In practice it must
  be estimated (τ_drift², §6), so the result is a best case.

### 11.1 σ/τ = 3.0

σ/τ = 3.0 ran as three fixed-scope tasks (caps 3 and 6; cap 9; no cap), 1,728 simulations in total, because the
single task exceeded its budget (§18). It is the clearest degradation case:
- **Joint model, full schedules:** 80% coverage is 0.752, and 0.707 pooled over caps.
- **Degenerate REML fits:** about 8% of robots fall in the w_eff ≥ 0.9 bin, with 80% intervals about 4 points wide
  and 17% coverage.
- **Short schedules:** with three matches per team, the plug-in's double counting costs 4.7 coverage points beyond the
  joint model (0.573 vs 0.620).
- **Independent priors** with their true error variance stay at 0.797–0.798.

Real data sits at σ/τ ≈ 0.9–1.2, so σ/τ = 3 is a stress case. It shows what happens with very noisy components or very
few matches.

---

## 12. Robot-independence sensitivity

**Real data** (AS1_joint, full covariance vs diagonal):
- Alliance estimation SD: diagonal/full median ratio 1.021 (10th–90th percentile 0.985–1.054).
- Alliance predictive SD: ratio 1.004 (0.997–1.011), because σ² dominates.
- Red−blue difference estimation SD: ratio 0.993 (0.956–1.030).
- Classification changes on the δ/π grid: at most 1.1% of comparisons (for example 0.5% at δ = 0, π = 0.8; 0.8% at
  δ = 10, π = 0.8).
- Coverage: 0.682 (full) vs 0.684 (diagonal).

**Simulation** (joint model; full vs diagonal; δ = 2 points, π = 0.8):

| σ/τ | Cap | Alliance cov80 full / diag | Width ratio diag/full | Pair-difference cov80 full / diag | Class changed | Incorrect pref. full / diag |
|---|---|---|---|---|---|---|
| 0.5 | 3 | 0.731 / 0.747 | 1.030 | 0.730 / 0.733 | 3.1% | 5.6% / 5.6% |
| 0.5 | none | 0.809 / 0.817 | 1.018 | 0.802 / 0.798 | 0.4% | 0.7% / 0.7% |
| 1.0 | 3 | 0.729 / 0.740 | 1.020 | 0.720 / 0.725 | 2.5% | 10.1% / 10.3% |
| 1.0 | none | 0.787 / 0.797 | 1.018 | 0.789 / 0.786 | 0.6% | 2.7% / 2.7% |
| 2.0 | 3 | 0.689 / 0.680 | 0.990 | 0.662 / 0.681 | 1.0% | 15.5% / 15.5% |
| 2.0 | none | 0.781 / 0.787 | 1.014 | 0.777 / 0.774 | 0.7% | 6.4% / 6.4% |
| 3.0 | 3 | 0.642 / 0.611 | 0.953 | 0.574 / 0.622 | 0.7% | 19.2% / 19.8% |
| 3.0 | none | 0.748 / 0.749 | 1.004 | 0.741 / 0.742 | 0.5% | 8.4% / 8.4% |

**Inference.**
- **Alliance sums:** robot estimates at an event are mostly *negatively* correlated (partners share credit). So
  ignoring covariance slightly over-states alliance-sum uncertainty (+1–3%).
- **The stress case:** with three matches per team at σ/τ = 3, ignoring covariance moves alliance coverage by 3.1 points
  and pair-difference coverage by 4.8 points.
- **Differences:** ignoring it slightly under-states difference uncertainty.
- **Overall:** the practical effect is small at real schedule sizes, and largest with three or fewer matches per team.
- **Candidate tolerance (§17):** a simplification is acceptable only if it changes classifications by ≤ 1–2% and
  coverage by ≤ 1–2 points. Full covariance costs almost nothing to compute, so there is no need to simplify.

---

## 13. G2 anomaly-bound analysis

**Standardized playoff residuals** z = (observed − predicted)/predictive SD (AS1_joint, *observed vs model
prediction*):

| Season / target | SD of z | Mean | Share \|z\|>2 | >2.5 | >3 | >3.5 | >4 |
|---|---|---|---|---|---|---|---|
| Nominal normal | 1 | 0 | 4.55% | 1.24% | 0.27% | 0.05% | 0.01% |
| 2024 no-foul | 1.29 | +0.58 | 15.4% | 7.7% | 3.3% | 1.6% | 0.50% |
| 2025 no-foul | 1.11 | +0.50 | 9.7% | 3.9% | 1.6% | 0.55% | 0.17% |
| 2026 no-foul | 1.33 | +0.05 | 12.4% | 6.2% | 3.3% | 1.6% | 0.69% |
| All no-foul | 1.27 | +0.37 | 12.4% | 5.9% | 2.7% | 1.2% | 0.46% |
| All auto | 1.25 | +0.55 | 13.7% | 6.6% | 3.2% | 1.4% | 0.65% |
| All endgame | 1.25 | +0.15 | 10.6% | 4.8% | 2.0% | 0.82% | 0.42% |

**Groups** (no-foul, share |z| > 3):
- semifinal rounds: 2.3% (SD 1.23);
- finals: 4.9% (SD 1.47);
- regionals: 3.2%;
- districts: 2.8%;
- district championships: 1.4%;
- Championship divisions: 1.4%.

**Asymmetry.** In 2024 and 2025, most extreme residuals are *over*-performance (high side 2.8% vs low side 0.5% at
|z| > 3 in 2024). In 2026 they are mostly *under*-performance (low side 2.2%, high side 1.1%).

**Known anomalies.** The population has **no DQ'd playoff alliance**, and no other independent anomaly record exists
here. **The detection rate therefore cannot be measured.**

**Inference.**
- Raw-z bounds flag about 10× the nominal rate, because the model is mis-scaled for playoffs (§8).
- Any bound must be set either on recalibrated residuals, or empirically, as a target flag rate.
- **Attribution stays at the alliance level** (spec G2). Nothing in this analysis can identify a robot as the cause.

---

## 14. w_min, n_min and identifiability (simulation output)

**Per-robot 80% coverage and RMSE (τ = 10) by diagnostic** (joint model; σ/τ = 0.5 / 1.0 / 2.0):

| Diagnostic bin | Cov80 (0.5 / 1.0 / 2.0) | RMSE (0.5 / 1.0 / 2.0) |
|---|---|---|
| Matches n = 1 | 0.741 / 0.704 / — | 7.26 / 9.11 / — |
| n = 2–3 | 0.74 / 0.73–0.74 / — | 5.0–6.0 / 6.8–7.6 / — |
| n = 4–5 | 0.80–0.81 / 0.77–0.78 / — | 2.7–3.0 / 4.8–5.3 / — |
| n = 6–9 | 0.79–0.80 / 0.79–0.80 / — | 1.9–2.5 / 3.5–4.4 / — |
| Distinct partners < 6 | 0.740 / 0.725 / 0.688 | 6.28 / 7.89 / 9.16 |
| Partners 6–11 | 0.755 / 0.747 / 0.706 | 4.60 / 6.35 / 8.41 |
| Partners 12–17 | 0.797 / 0.791 / 0.764 | 2.31 / 4.21 / 6.76 |
| Partners ≥ 18 | 0.79–0.81 / 0.79–0.80 / 0.78–0.79 | 1.5–1.8 / 3.0–3.4 / 5.2–5.9 |
| Max \|corr\| < 0.4 | 0.78–0.81 / 0.77–0.79 / 0.71–0.79 | — |
| Max \|corr\| 0.4–0.5 | 0.792 / 0.735 / 0.676 | 4.94 / 7.10 / 10.83 |
| Max \|corr\| 0.5–0.6 | 0.751 / 0.685 / 0.522 | 5.18 / 7.50 / 13.84 |
| Max \|corr\| ≥ 0.6 | 0.605 / 0.422 / 0.169 | 5.80 / 8.95 / 9.79 |
| w_eff < 0.2 | 0.43 / 0.45 / 0.55 | — |
| w_eff 0.2–0.4 | 0.73 / 0.68 / 0.74 | — |
| w_eff 0.4–0.5 | 0.78 / 0.74 / 0.78 | — |
| w_eff ≥ 0.5 (excluding the ≥ 0.9 degenerate bin at σ/τ = 2) | 0.75–0.79 / 0.75–0.79 / 0.72–0.79 | — |

**At σ/τ = 3 (stress case)**, coverage is below nominal in every bin:
- n ≤ 3: 0.62–0.63;
- n = 4–6: 0.71–0.72;
- n ≥ 7: 0.73–0.77;
- max |corr| 0.3–0.4: 0.59; ≥ 0.4: 0.18–0.35;
- w_eff 0.4–0.7: 0.80–0.82; w_eff < 0.2: 0.59.

**Degenerate fits.**
- At σ/τ = 2, robots with w_eff ≥ 0.9 have 80% intervals only 3.8 points wide, and 15.6% coverage.
- The same robots dominate the max |corr| ≥ 0.6 bin, at 16.9% coverage.
- These are REML fits on short schedules in which σ̂² collapsed toward zero, an overconfident failure mode of plug-in
  (empirical Bayes) hyperparameters.

**Inference.** Reliability depends on partner diversity and posterior correlation as much as on n. A sample-size rule
alone is not enough.

---

## 15. Per-robot ground-truth field audit

**Source.** TBA's public API v3 schema (`cache/tba_schema/api_v3.json`, sha256 `7cc321d3…db8d2a`, fetched
2026-11-06 00:09 UTC). Data-level checks (availability, missingness, reconciliation) need TBA match payloads, which
are unavailable here, so they are all **unverified**. Details: `results/field_audit.json`.

| Season | Fields | Allowed values | Meaning | Numeric points? | Determines | Classification |
|---|---|---|---|---|---|---|
| 2024 | `autoLineRobot1–3` | No, Yes | Left the starting zone in auto | No | Only the auto-leave sub-component (`autoLeavePoints`). Note points are alliance-level | **partial** |
| 2024 | `endGameRobot1–3` | None, Parked, CenterStage, StageLeft, StageRight | End state | No | Park and on-stage points. Harmony and spotlight are alliance-level, and trap is per stage | **partial** |
| 2025 | `autoLineRobot1–3` | No, Yes | Left the starting line | No | Only auto mobility (`autoMobilityPoints`) | **partial** |
| 2025 | `endGameRobot1–3` | None, Parked, ShallowCage, DeepCage | Barge state | No | Plausibly all barge points. The project's 2025 endgame component is `endGameBargePoints` | **unverified**: the one candidate for a whole component; needs an approved 2025 GameSpec, a pre-registered conversion and a parity check on every stored row |
| 2026 | `autoTowerRobot1–3` | None, Level1–3 | Tower level in auto | No | At most the auto tower part. Auto fuel is alliance-level | **partial** |
| 2026 | `endGameTowerRobot1–3` | None, Level1–3 | Tower level at the end | No | At most the endgame tower part. Endgame fuel is alliance-level | **partial** |

**Corrected 2026-11-06: the status of the 2025 `endGameRobot1–3` fields.**
- They are **`unverified`**, and remain so until both of these are inspected:
  - the actual TBA match payloads, for availability, missingness and whether the per-robot conversion reconciles
    with `endGameBargePoints` on every stored row;
  - an approved 2025 GameSpec.
- Calling them a "candidate for the whole component" describes their *meaning* in the schema only. It is not
  evidence that they qualify, and they must not be described as qualifying, or treated as partially validated,
  before those inspections.

**Conclusion.** None of the 18 per-robot fields qualifies as individual numerical ground truth. Every one is
categorical. Individual robot estimates cannot currently receive individual-level numerical validation from these
sources. They keep `estimated_aggregate_validated` or `not_validated` status (spec A3, E1b).

---

## 16. Limitations and unresolved issues

1. **Not the project's canonical data path.**
   - The benchmark uses Statbotics' mirror of official results, not the project's TBA ingestion, adapters and D18
     EPA.
   - Component definitions are Statbotics' (parity-checked on every row), which may differ slightly from
     `ml/features/score_components.py`.
   - Re-running on the project's isolated `stratai_test` copy is needed before any result is cited as the project's
     E2.
2. **AS-1 is only partly implementable.**
   - Caps, shared resources and season interactions (B4, B5.2(c)) are not evaluated: no approved GameSpec exists.
   - Components are fitted separately, so cross-component covariance is not modelled.
3. **The point-in-time EPA baseline could not be reconstructed.** M2 uses our own prior-event estimates instead. The
   PX-1 composition baseline is not evaluated.
4. **No pre-registration.** This is not the spec's pre-registration (§20). `PROTOCOL.json` was fixed before execution,
   but the owners did not approve it in advance. Its results are evidence for designing the real pre-registration, not
   a gate result.
5. **Hyperparameters are point estimates (empirical Bayes)** in every AS-1 variant. The simulations show this
   under-covers on short schedules.
6. **Single-match outcomes** make every "incorrect preference" rate a mix of model error and match noise. Expected-score
   correctness cannot be observed directly.
7. **G2 detection** cannot be assessed: there are no known anomalies.
8. **Runs that hit their budgets** are listed in §18. No partial result is used in this report except where labelled.
9. **The simulations are best cases.** Independent-prior scenarios were given their true error variance.

---

## 17. Candidate ranges for human decision (none approved)

| Decision | Evidence sufficient to decide? | Candidate range | What is still needed |
|---|---|---|---|
| **Use expected score for alliance comparisons** (B6 initial objective) | **Partly.** Expected-score differences rank alliances with about 76% single-match sign accuracy, and beat composition-blind baselines | Supportable as a *ranking* signal. Not supportable as calibrated uncertainty | Recalibrate playoff bias and variance (pre-registered), then re-run E2 on the project's data |
| **δ** (practical-equivalence margin) | **No** | If expressed relative to the season's playoff alliance SD, 0.1–0.2 SD looks workable (≈ 2.6–5.2 / 5–10 / 15–30 points for 2024 / 2025 / 2026). Absolute δ is not transferable across seasons | Calibrated Δ uncertainty; human judgment on what score difference matters strategically |
| **π** (decision threshold) | **No** | At δ = 0–5 points, π = 0.8–0.9 decides 47–71% of comparisons, with 12–18% incorrect preferences against single-match outcomes | The same recalibration. Until then, π would overstate confidence |
| **Prior-dependence coverage tolerance** (A3.2 test) | **Partly** (simulation) | Joint coverage within 2–3 points of nominal at n ≥ 6 is achievable at σ/τ ≤ 2. At n ≤ 3, no current-event method meets it | Decide whether short-schedule estimates must be `prior_dominated` (see w_min/n_min), or whether hyperparameter uncertainty must be propagated (fully Bayesian) |
| **Robot-independence tolerance** (B5.3) | **Yes, for a candidate.** Effects are small and measured | Allow simplification only if ≤ 1–2% of classifications and ≤ 1–2 coverage points change | Confirm on the project's data. Practically, keep full covariance (negligible cost) |
| **G2 anomaly bound** | **No** | On raw z: \|z\| > 3.5–4.0 flags about 0.5–1.2% of playoff alliances. On recalibrated z (SD inflated × 1.27): about 2.75–3.15 | Recalibration; a target flag rate chosen by humans; known anomalies (none exist here) to measure detection |
| **n_min** | **Partly** (simulation) | 4–6 matches (coverage recovers from about 0.73 to about 0.78–0.80 at n ≥ 4) | Combine with the partner and correlation rules; confirm on real E1a |
| **w_min** (joint model) | **Partly** (simulation) | 0.4–0.5 (coverage below 0.75 under 0.4) | A guard against degenerate REML fits (w_eff near 1 with tiny width), which a w_min rule cannot catch |
| **Identifiability limits** | **Partly** (simulation) | Max \|posterior corr\| ≤ 0.4–0.5; distinct partners ≥ 12 | Confirm calibration of the `weakly_identified` labels on real data (needs E1b ground truth, which does not exist) |
| **Individual ground-truth fields** | **Yes** (as a negative) | None qualifies. The 2025 `endGameRobot` fields stay `unverified` until their actual TBA data and an approved 2025 GameSpec are inspected (corrected 2026-11-06) | An approved 2025 GameSpec, a pre-registered conversion, and a parity check on stored TBA payloads |

---

## 18. Reproduction, commands, seeds and run log

**Commands.** See `research/p11_e2/README.md`. Every step is a separate command with `--budget-minutes` (at most 45).
Run with the project `.venv` (Python 3.14; numpy 2.5.4, scipy 1.18.1, httpx 0.28.1) and `python -I`.

**Versions:**
- Git: `main` at `3757d2a`, with `research/` and the two docs uncommitted.
- Seeds: 20261105 (bootstrap, simulations). Simulation streams: [20261105, 10 × σ/τ, (split id)].

**Data versions:** `cache/raw/<season>/manifest.json` gives the URL, fetch time and sha256 of each page.

**Run log**, including runs that stopped at their budget:

| Task | Result | Minutes | Used? |
|---|---|---|---|
| E2 2024 | complete | 7.7 | yes |
| E2 2025 | complete | 16.4 | yes |
| E2 2026 run 1 (30-min budget, 4 parallel simulations) | **stopped at budget**, pass 1, 183/205 events, no records | 30.1 | no (`e2_records_2026.partial_run1.json`) |
| E2 2026 run 2 (40-min budget) | **stopped at budget**, pass 1, 204/205 events | 40.0 | no (`partial_run2`) |
| E2 2026 run 3 (n×n REML) | complete | 13.6 | yes |
| Analysis (all seasons) | complete | 10.2 | yes |
| Simulation σ/τ 0.5 | complete (1,728) | 28.0 | yes |
| Simulation σ/τ 1.0 (single task) | **stopped at budget** (1,144/1,728) | 40.0 | no (`partial_run1`) |
| Simulation σ/τ 1.0 caps 3, 6 | complete (864) | 23.9 | yes |
| Simulation σ/τ 1.0 caps 9, none, run 1 | **stopped at budget** (789/864) | 40.0 | no (`partial_run2`) |
| Simulation σ/τ 1.0 caps 9, none, run 2 | complete (864) | 19.5 | yes |
| Simulation σ/τ 2.0 | complete (1,728) | 25.3 | yes |
| Simulation σ/τ 3.0 (single task) | **stopped at budget** (1,046/1,728) | 40.0 | no (`partial_run1`) |
| Simulation σ/τ 3.0 caps 3, 6 | complete (864) | 26.4 | yes |
| Simulation σ/τ 3.0 caps 9, none (two-cap task) | **stopped at budget** (622/864) | 40.0 | no (`partial_run2`) |
| Simulation σ/τ 3.0 cap 9 | complete (432) | 7.9 | yes |
| Simulation σ/τ 3.0 no cap | complete (432) | 8.2 | yes |
| Field audit | complete | <1 | yes |

No task ran longer than 41 minutes. A task that reached its budget stopped and wrote partial results marked
`partial: true`. Each was then re-run with a narrower fixed scope, as separate tasks.

**Corrected 2026-11-06: exact accounting**, verified against every task's execution log.

| Category | Count | Runs |
|---|---|---|
| Stopped at their time budget (`partial: true`) | **6** | E2 2026 run 1 (183/205 events); E2 2026 run 2 (204/205); simulation σ/τ 1.0 single task (1,144/1,728); σ/τ 1.0 caps 9 + none, run 1 (789/864); σ/τ 3.0 single task (1,046/1,728); σ/τ 3.0 caps 9 + none (622/864) |
| Stopped manually (not in the table above) | **1** | The first analysis run, started while only the 2024 and 2025 records existed. It was stopped before writing any output, because the 2026 records were missing. The analysis was then run once on all three seasons |
| Completed replacement runs used in the report | **6** | E2 2026 run 3; σ/τ 1.0 caps 3 + 6; σ/τ 1.0 caps 9 + none, run 2; σ/τ 3.0 caps 3 + 6; σ/τ 3.0 cap 9; σ/τ 3.0 no cap |
| Partial outputs kept and excluded from every analysis | **6 files** | `e2_records_2026.partial_run1.json`, `e2_records_2026.partial_run2.json`, `sim_sigma_over_tau_1.0.partial_run1.json`, `sim_sigma_over_tau_1.0_caps_high.partial_run2.json`, `sim_sigma_over_tau_3.0.partial_run1.json`, `sim_sigma_over_tau_3.0_caps_high.partial_run2.json` |
| Scratch diagnostic runs (outputs outside `results/`, never used) | **3** | A one-minute simulation timing probe, stopped at its 1-minute budget by design; a test of `analyze.py` on a scratch copy of the 2024–2025 records (complete); single-event timing and REML-equivalence checks |

**The earlier summary of this work stated "five" budget-limited runs. That was wrong: there were six.** The table in
this section always listed six.

The follow-up investigation's runs are logged in §22.

---

# Follow-up investigation (2026-11-06)

**What this part is, and what it is not.**
- It is new analysis, separate from the original evaluation above, and it leaves the original results unchanged.
- **Protocol:** `research/p11_e2/FOLLOWUP_PROTOCOL.json`, fixed before any follow-up analysis.
- **Scripts:** `followup_bias.py` (F1c refits), `analyze_followup.py` (F1, F2) and `followup_short_schedule.py` (F3).
- **Outputs:** `results/followup_*`.
- **Unchanged:** no threshold, method or specification. Every correction evaluated here is a research candidate.

## 19. Why playoff alliance scores are under-predicted (F1)

### 19.1 Is the bias systematic, or driven by particular events?

**F1a: qualification vs playoff alliance means** (no-foul, event-averaged; *observed* vs *model prediction*):

| Season | Qualification mean | Playoff mean (observed) | Playoff mean (AS-1 predicted) |
|---|---|---|---|
| 2024 | 46.9 | 69.2 | 62.3 |
| 2025 | 91.8 | 130.8 | 120.2 |
| 2026 | 166.0 | 247.2 | 246.2 |

AS-1 already explains most of the qualification-to-playoff jump through alliance composition: the selected robots are
stronger. The remainder is the bias.

**F1b: event-level residual** (observed − AS-1, no-foul):

| Season | Events | Row mean | Event median | 10%-trimmed | Share of events > 0 | Without the 5% most extreme events | Event p10–p90 |
|---|---|---|---|---|---|---|---|
| 2024 | 184 | 6.9 | 6.9 | 6.9 | 94.6% | 6.4 | 1.7 to 12.3 |
| 2025 | 198 | 10.7 | 10.6 | 10.6 | 90.9% | 9.8 | 0.4 to 20.3 |
| 2026 | 205 | 0.9 | 2.0 | 1.6 | 54.6% | 1.0 | −30.1 to 28.5 |

**Groups** (`followup_tables.md` has the full list):
- **2024 and 2025:** uniform across event sizes and weeks, about +6 to +8 points in 2024 and +8 to +13 in 2025. The
  exception is Championship divisions: +3.8 in 2024 and +0.5 in 2025.
- **2026:** reverses through the season:
  - weeks 1–3: +8 to +11;
  - weeks 4–7: −3 to −12;
  - Championship divisions: −23.3;
  - events with more than 50 teams: −14.2;
  - finals: −16.9.

**Inference.**
- **2024 and 2025:** the bias is **systematic**. Nine in ten events show it, and it is not driven by a few events
  (trimming changes it by under 1 point).
- **2026:** the "+0.9" average is not "no bias". It is a positive bias early in the season cancelling a negative bias
  in late, large and Championship events.

### 19.2 Change in performance over the event (F1c)

AS-1 was refitted on the first two-thirds of each event's qualification matches.
- **"Late-qual"** is the error on the held-out last third.
- **"Playoff (early fit)"** is the error predicting playoffs from that earlier fit.

| Season | Component | Late-qual residual | Late-qual z SD | Late-qual 80% coverage | Playoff residual (early fit) | Playoff residual (full fit, original) |
|---|---|---|---|---|---|---|
| 2024 | no-foul | +3.6 | 1.03 | 0.771 | +9.2 | +6.9 |
| 2025 | no-foul | +8.2 | 1.03 | 0.762 | +15.4 | +10.7 |
| 2026 | no-foul | +11.3 | 1.05 | 0.791 | +9.8 | +0.9 |
| All | auto | +2.1 | 1.05 | 0.785 | +6.0 | +4.5 |
| All | teleop | +4.3 | 1.07 | 0.779 | +5.6 | +2.2 |
| All | endgame | +1.4 | 1.06 | 0.792 | +3.9 | +2.5 |

**Inference.**
1. **Teams improve during the event in all three seasons.** The model fitted on earlier matches under-predicts later
   qualification matches by 3.6–11.3 points. Its standardized-residual SD is still about 1.04, and its 80% coverage is
   0.76–0.79, so **within qualifications AS-1 is close to calibrated apart from this drift.**
2. **A fit centred earlier in time under-predicts playoffs more.** The early-fit playoff residual exceeds the
   full-fit one by 2.3 / 4.7 / 8.9 points, which is consistent with continued improvement.
3. **How much of the playoff bias drift explains.** A rough linear extrapolation (an *inference*, not a fitted
   model): if drift continues at its late-qualification rate, it would account for:
   - **2024:** about half the playoff bias;
   - **2025:** most of it;
   - **2026:** far more than the observed +0.9.
4. **2026 therefore has a strong playoff-specific *negative* effect** that offsets the drift.

### 19.3 Alliance composition and selection (F1d)

**Residual by the alliance's predicted-strength tercile** within its event (T1 = weakest):

| Season | Playoff T1 / T2 / T3 | Late-qual T1 / T2 / T3 (held-out) |
|---|---|---|
| 2024 | +7.6 / +7.0 / +5.6 | +3.5 / +3.8 / +3.5 |
| 2025 | +10.9 / +10.8 / +10.3 | +7.4 / +8.8 / +8.5 |
| 2026 | +9.4 / −0.3 / **−10.6** | +12.4 / +8.1 / +13.3 |

**Inference.**
- **Shrinkage is not the cause.** The held-out late-qualification residual is flat across strength terciles in every
  season. So shrinkage does not under-predict strong alliances within qualifications, and regression to the mean is
  handled.
- **2024–2025:** the playoff bias is also nearly flat across terciles. This is a general uplift, not an effect
  concentrated in the strongest, hand-picked alliances. Selection on information outside the qualification data
  cannot be ruled out, because it is not observable here, but it is not needed to explain these numbers.
- **2026:** the strongest playoff alliances are over-predicted by 10.6 points, although strong alliances were
  *under*-predicted in late qualifications (+13.3). That is a playoff-specific suppression of strong alliances in
  2026.
- **Possible explanations for 2026** (not tested, because no approved 2026 GameSpec or per-robot data exists):
  - nonlinear scoring that the linear model ignores: caps, shared resources or saturation (spec B4/B5.2(c));
  - heavier playoff defense against strong alliances.

### 19.4 Rounds, components, data and scoring assumptions (F1e, F1f)

**By round and appearance:**
- **2025:** grows with round: first appearance +8.5, third or later +12.8, finals +13.6.
- **2026:** falls with round: first appearance +5.9, third or later −3.1, finals −16.9.
- **2024:** flat, about +6.4 to +7.2.

**By component** (mean residual):

| Season | Auto | Teleop | Endgame | No-foul | Total |
|---|---|---|---|---|---|
| 2024 | +3.1 | +5.8 | −0.5 | +6.9 | +7.8 |
| 2025 | +3.8 | +7.3 | +1.5 | +10.7 | +10.4 |
| 2026 | +6.4 | **−6.1** | +6.1 | +0.9 | +4.2 |

- **Where the bias sits:** mostly auto and teleop in 2024–2025. In 2026, teleop alone is over-predicted, which fits a
  playoff-specific teleop constraint (§19.3).
- **Fouls:** add about +1 point (total vs no-foul) in 2024 and +3 in 2026. They are not a main driver.
- **Missing data:** cannot explain the bias. The exclusions (about 0.8% of qualification rows and 0.8% of playoff
  rows, §4) are far too few and are unrelated to the residual's sign. No excluded row was reintroduced.
- **The scoring-rule assumption** (linear, uncapped) is the most plausible contributor to the 2026 reversal. It cannot
  be tested without an approved GameSpec.

### 19.5 Conclusion on the bias

The +6-point average is **not one effect**:
1. **Within-event improvement** (+3.6 to +11.3 points per late third of qualifications) is present in every season.
   AS-1 cannot see it, because it treats each robot's contribution as constant over the event.
2. **A playoff-specific effect,** whose sign depends on the season:
   - positive beyond drift: about +3 in 2024 and about +2 in 2025;
   - strongly negative for strong alliances in 2026, especially in late-season, large and Championship events and in
     finals.
3. **2024–2025 are systematic.** 2026 is heterogeneous by week, event type and round, so a single constant cannot
   describe it.

## 20. Correction candidates on held-out events (F2)

**Setup.** Two pre-declared forms, both fitted on training events only and evaluated on held-out test events only:
- **C1:** pred × m, SD × k.
- **C2:** pred + c·SD, SD × k.

**Two designs:**
- **W (within season):** train on events that ended before the season's median start date; test on the later events.
- **X (cross season):** train on 2024–2025; test on 2026.

Both forms are reported for both designs. Nothing was selected after seeing the test results, and the original E2
results were not corrected.

| Design | Train / test events | Form | Fitted parameters | Test MAE (uncorrected → corrected) | MAE gain [95% CI] | Test bias | 80% coverage (uncorr. → corr.) [gain CI] | 50 / 90 / 95% coverage (corrected) |
|---|---|---|---|---|---|---|---|---|
| W 2024 | 62 / 104 | C1 | m = 1.140, k = 1.266 | 14.3 → 13.3 | +1.02 [+0.50, +1.44] | −7.0 → +3.0 | 0.631 → 0.782 [+0.13, +0.17] | 0.49 / 0.88 / 0.94 |
| W 2024 | 62 / 104 | C2 | c = 0.628, k = 1.244 | 14.3 → 12.9 | +1.41 [+1.07, +1.78] | −7.0 → +0.9 | 0.631 → 0.786 [+0.14, +0.17] | 0.49 / 0.88 / 0.94 |
| W 2025 | 95 / 102 | C1 | m = 1.116, k = 1.153 | 21.3 → 20.8 | +0.53 [−0.54, +1.55] | −10.2 → +6.4 | 0.724 → 0.813 [+0.06, +0.11] | 0.52 / 0.90 / 0.95 |
| W 2025 | 95 / 102 | C2 | c = 0.556, k = 1.136 | 21.3 → 19.5 | +1.75 [+1.12, +2.40] | −10.2 → +2.7 | 0.724 → 0.826 [+0.08, +0.12] | 0.54 / 0.91 / 0.95 |
| W 2026 | 99 / 106 | C1 | m = 1.053, k = 1.321 | 62.4 → 65.2 | **−2.83** [−3.73, −1.85] | +7.4 → +23.5 | 0.690 → 0.801 [+0.10, +0.12] | 0.52 / 0.89 / 0.93 |
| W 2026 | 99 / 106 | C2 | c = 0.223, k = 1.300 | 62.4 → 64.0 | **−1.60** [−2.24, −0.93] | +7.4 → +21.1 | 0.690 → 0.797 [+0.10, +0.12] | 0.52 / 0.89 / 0.94 |
| X | 382 / 205 | C1 | m = 1.096, k = 1.221 | 54.4 → 58.2 | **−3.86** [−4.89, −2.78] | −0.9 → +22.9 | 0.695 → 0.763 [+0.06, +0.08] | 0.49 / 0.86 / 0.91 |
| X | 382 / 205 | C2 | c = 0.541, k = 1.200 | 54.4 → 58.5 | **−4.11** [−5.24, −3.01] | −0.9 → +28.3 | 0.695 → 0.753 [+0.05, +0.07] | 0.47 / 0.86 / 0.91 |

(Positive MAE gain = the correction is more accurate. Bias = predicted − observed.)

**Does a correction improve both accuracy and calibration?**
- **Within 2024 and 2025:** yes. The z-shift form C2 improves MAE (+1.4 and +1.8 points; CIs exclude 0) and brings
  80% coverage to 0.79–0.83. The multiplicative form helps less, and its 2025 accuracy CI includes 0.
- **Within 2026 and across seasons:** **no.** Both forms make point predictions *worse* (−1.6 to −4.1 points, CIs
  exclude 0), because the bias changes sign between the training and test events (§19.1).
- **The variance inflation** (k ≈ 1.14–1.32) improved coverage in every design. It is the only component that
  transfers, but it does not reach nominal coverage across seasons (0.75–0.76).
- **Practical constraint:** even a within-season correction needs about half a season of events before it can be
  fitted.

**Inference.**
- A constant playoff mean correction is **not supportable**. It does not transfer between seasons, and it fails within
  2026.
- A playoff **variance inflation** is consistently supported in direction, but its size varies by season (1.14–1.32).
- Any adopted adjustment would still be a new term needing its own pre-registration (spec B5.5).
- Modelling within-event drift, a time-varying contribution, addresses the one cause found in every season. It is the
  better-motivated research direction, but it is not evaluated here.

## 21. Short-schedule reliability (F3, simulation output)

**Setup.**
- The same 24 real schedules; independent noise.
- σ/τ ∈ {1, 3}; matches per team capped at 3, 6 or none; 216 simulations per σ/τ.
- **Four variants on identical data:**
  - **V1:** the current REML plug-in;
  - **V2:** the true (oracle) σ² and τ²;
  - **V3:** the true σ², with τ² from REML;
  - **V4:** hyperparameters integrated over a REML-likelihood-weighted grid, with a normal approximation of the
    mixture.

**Per-robot 80% coverage** (nominal 0.80):

| σ/τ | Cap | V1 REML plug-in | V2 oracle | V3 σ² known | V4 integrated | REML collapse rate (σ̂²/σ² < 0.25) | Data-only flag (σ̂²/var(y) < 0.05) | V1 coverage in flagged fits |
|---|---|---|---|---|---|---|---|---|
| 1.0 | 3 | 0.763 | 0.798 | 0.799 | 0.769 | 6.9% | 5.6% | **0.467** |
| 1.0 | 6 | 0.780 | 0.791 | 0.783 | 0.787 | 0% | 0% | — |
| 1.0 | none | 0.794 | 0.795 | 0.793 | 0.807 | 0% | 0% | — |
| 3.0 | 3 | **0.614** | 0.788 | 0.718 | 0.698 | 1.4% | 0% | — |
| 3.0 | 6 | 0.736 | 0.808 | 0.774 | 0.722 | 0% | 0% | — |
| 3.0 | none | 0.759 | 0.786 | 0.766 | 0.752 | 0% | 0% | — |

**95% coverage:** at σ/τ = 3 with cap 3, V1 0.762 vs oracle 0.950.

**Why the intervals become overconfident:**
1. **It is hyperparameter estimation, not the model's structure.** With the true σ² and τ², coverage is nominal at
   every schedule length and noise level (0.79–0.81).
2. **Two mechanisms:**
   - **(a) Collapse.** With few rows, REML sometimes puts nearly all variance into τ² and drives σ̂² toward zero. That
     produces very narrow intervals: 6.9% of fits at σ/τ = 1, cap 3, with 47% coverage in those fits. Knowing σ²
     removes the problem.
   - **(b) Sampling error in σ̂² and τ̂²** even without collapse. Both are unbiased on average (mean ratios
     0.97–1.07), but an error in the shrinkage weight is not reflected in the interval. This dominates at high noise:
     σ/τ = 3, cap 3, coverage 0.61 with almost no collapse. Knowing σ² recovers only part of it (0.72).
3. **Grid integration (V4) is not a sufficient fix.** It helps slightly in the hardest case (0.61 → 0.70) and
   slightly hurts at cap 6 (0.736 → 0.722). This is a limitation of this particular integration and its normal
   approximation. A properly specified hierarchical Bayesian treatment of the hyperparameters is not ruled out, and
   was not evaluated.

**Do the candidate criteria catch it?**
- **Lenient set:** n ≥ 4, max |corr| ≤ 0.5, ≥ 12 partners, w_eff ≥ 0.4.
- **Strict set:** n ≥ 6, max |corr| ≤ 0.4, ≥ 12 partners, w_eff ≥ 0.5.
- Both are computed from V1, as a system would compute them.

| σ/τ | Cap | Lenient: share passing; 80% coverage pass / fail | Strict: share passing; 80% coverage pass / fail |
|---|---|---|---|
| 1.0 | 3 | 0% passing; — / 0.763 | 0% passing; — / 0.763 |
| 1.0 | 6 | 94%; 0.780 / 0.774 | 93%; 0.781 / 0.761 |
| 1.0 | none | 100%; 0.794 / — | 100%; 0.794 / — |
| 3.0 | 3 | 0%; — / 0.614 | 0%; — / 0.614 |
| 3.0 | 6 | 40%; 0.814 / 0.684 | 19%; 0.822 / 0.717 |
| 3.0 | none | 82%; 0.780 / 0.664 | 64%; 0.780 / 0.723 |

**Inference.**
- **The n_min candidates (4–6) exclude every robot on three-match schedules,** which is where collapse and the worst
  under-coverage occur.
- **At high noise,** the combined criteria separate reliable robots (passing: 0.78–0.82) from unreliable ones
  (failing: 0.66–0.72).
- **The collapse flag added nothing beyond the criteria in these simulations,** because collapse occurred only with
  three matches.
- **However, a w_min rule cannot detect collapse.** A collapsed fit gives w_eff near 1 (§14), and n ≥ 4 does not
  guarantee an event is free of collapse with other schedules or noise.
- **A data-only collapse check** (σ̂²/var(y) < 0.05 flagged about 80% of collapsed fits) is a cheap additional safeguard
  worth considering.
- **What the criteria do not fix:** they decide *which* estimates may be relied on. Passing estimates at σ/τ = 3 still
  cover only about 0.78.
- **Real-data context:** events sit at σ/τ ≈ 0.9–1.2, with about 10–12 matches per team, where V1 is close to nominal
  (0.79). Short-schedule risk applies mainly to plans made **before qualifications finish** (spec H2) and to small or
  disrupted events.

**Safeguards that would prevent misleading recommendations** (candidates for human decision; nothing here changes the
spec):
1. Keep the n_min and identifiability rules (spec A3.2, A3.7) as they stand. Robots that fail are `prior_dominated` or
   `weakly_identified`, never used in preference conclusions.
2. Add an explicit collapse guard: σ̂² near zero, or at its optimizer bound, marks the whole event fit `unreliable`.
3. Where possible, use independent σ² (and τ²) estimates from earlier events of the same season, instead of
   estimating them from a few rows. V3 shows that knowing σ² largely removes collapse.
4. Label every pre-selection plan made on a short schedule as such, and keep its comparisons `unresolved` unless the
   criteria pass.

## 22. Follow-up run log and files

| Task | Result | Seconds | Output |
|---|---|---|---|
| `followup_bias.py` 2024 | complete | 16.5 | `results/followup_f1c_2024.json` |
| `followup_bias.py` 2025 | complete | 17.4 | `results/followup_f1c_2025.json` |
| `followup_bias.py` 2026 | complete | 21.5 | `results/followup_f1c_2026.json` |
| `followup_short_schedule.py` σ/τ 1.0 | complete (216) | 32.2 | `results/followup_f3_sigma_over_tau_1.0.json` |
| `followup_short_schedule.py` σ/τ 3.0 | complete (216) | 36.5 | `results/followup_f3_sigma_over_tau_3.0.json` |
| `analyze_followup.py` | complete | 23.8 | `results/followup_analysis.json`, `results/followup_tables.md` |
| F3 timing probe (σ/τ 3.0, 1-minute budget, scratch) | complete within its budget; output outside `results/`, not used | 32.2 | scratch only |

**No follow-up run was interrupted.**

**Code change.** `research/p11_e2/model.py` now exposes `reml_objective` and `reml_tau_given_sigma`. The REML
likelihood itself is unchanged: `reml()` was re-checked against `reml_direct()` after the change (≤ 3.8×10⁻⁶ relative
on sampled events). No production code changed.

**Reproduce:**
```bash
for y in 2024 2025 2026; do .venv/bin/python -I research/p11_e2/followup_bias.py --season $y \
  --population research/p11_e2/cache/population --out research/p11_e2/results --budget-minutes 40; done
.venv/bin/python -I research/p11_e2/analyze_followup.py --results research/p11_e2/results \
  --population research/p11_e2/cache/population
for r in 1.0 3.0; do .venv/bin/python -I research/p11_e2/followup_short_schedule.py --sigma-over-tau $r \
  --population research/p11_e2/cache/population --out research/p11_e2/results --budget-minutes 40; done
```
