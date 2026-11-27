# WP-NORM-EPA-v1 — frozen candidate specification (win probability)

- **Status:** RESEARCH CANDIDATE. Not served, not validated, not approved. The served model stays M6+M7
  (`win_prob_xgb_calibrated`, d18), unchanged.
- **Frozen:** 2026-11-26 (audit follow-up, workstream 1). Any change to a definition, input, cutoff, fitting rule,
  metric or decision rule below is a new candidate (WP-NORM-EPA-v2), with its own spec frozen before it is run on
  2027 data.
- **Code:** `ml/candidates/win_prob_norm_epa.py` (definition and fit), `scripts/evaluate_model_candidates.py`
  (evaluation), `tests/test_model_candidates.py` (properties), as committed with this spec.
- **Evaluation of record:** 2027, run once (section 7). Every 2026 number here is retrospective evidence only.

## 1. Why: the diagnosis of the served model's 2026 underperformance

M6 takes raw game-point features (EPA and score statistics in points). FRC scoring changes every season. Measured on
the D18 frame (`results/evaluation_2026_retrospective.json`, `diagnosis`), the median causal season scale S (population
SD of alliance scores, `ml/features/scale.py`) was:

| Season | Median S | vs the 2024–25 mean | Median abs raw EPA difference (red − blue) | Median abs normalized difference |
|---|---|---|---|---|
| 2024 | 21.6 | 0.72× | 12.4 | 0.53 |
| 2025 | 38.6 | 1.28× | 20.1 | 0.55 |
| 2026 | 98.9 | **3.29×** | 48.6 | 0.59 |

The 2026 raw differences are about 2.4 times 2025's and 3.9 times 2024's. A model fit in raw points reads them as far
more decisive than they are, so it is overconfident in 2026. Normalized, the three seasons look alike (0.53–0.59).

The audit report's "2.5–3.8×" is corrected here: 2026's scale is 2.6× 2025's, 4.6× 2024's and 3.29× their mean.

**Related finding: a near-certainty problem.** On 2026 qualification matches, the served model's log loss is 0.539
with the project's metric (`ml/backtest/metrics.log_loss`, probabilities clamped at 1e−15), but 0.524 with the audit
script's clamp at 1e−6. Brier, AUC and ECE are identical under both. The gap comes from a few predictions extremely
close to 0 or 1 that were wrong. This spec uses the project's metric throughout.

## 2. Inputs and features

For each of the six teams in a match, from the match row's `TeamFeatures` (built as of the match's scheduled time):
- `epa_total`: EPA from the team's latest strictly earlier event (D13/D18 EPA source), never the match's own event;
- `epa_scale`: the scale of that EPA's source, S(Y, as_of) for a same-season source, or the source season's full S
  for an earlier season.

Per team: z = epa_total / epa_scale. **Each team uses its own scale.** In 2025 and 2026, 36.6% and 36.4% of matches
mix EPA from two seasons. This choice was fixed on its definition before any per-team result was computed (section 8
records what was then seen).

Per match: x = Σ_red z − Σ_blue z.

**Missing data.** x is defined only for 3 v 3 matches where all six z exist. Otherwise the candidate gives no
probability, and nothing is substituted. This matches the served label's population ("EPA-complete").

## 3. Model and fitting

- p(red wins) = 1 / (1 + exp(−b·x)), with **no intercept**: p(x) + p(−x) = 1, so swapping alliances gives the
  complement. Order within an alliance does not matter (a sum).
- b is the maximum-likelihood estimate by Newton's method (`fit_coefficient`), with no regularisation. It is
  deterministic.
- **No post-hoc calibrator.** The one-parameter logistic is the probability model. Calibration is tested, not
  fitted (section 5).

## 4. Training data and cutoffs

- **Frame:** the D18 frame, `C:/Dev/StratAI-artifacts/phase4/frame_ab1adbf38b43c2f3/frame_rows.json.gz`.
- **Rows:** seasons **2024 and 2025 only** (the served models' training seasons, D7), every competition level,
  non-tie (`red_win` or `blue_win`), x defined: **19,615 rows**.
- **Frozen coefficient:** b = **1.962270** (6 d.p.; `results/evaluation_2026_retrospective.json`). A refit on the same
  rows must reproduce it. For 2027 the candidate is **not** refit on 2026: it is evaluated with this b, like the
  served model, which is also fit on 2024 and 2025.

## 5. Metrics

On the evaluation season's **qualification** matches that are non-tie with x defined (the primary population), the
script reports:
- **primary:** log loss;
- **secondary:** Brier, ROC AUC, ECE (10 equal-width bins), and the D6 calibration gate's G1 (ECE < 0.05) and G2
  (per-bin Poisson-binomial tests, Holm-corrected; `ml/calibration/gate.py`). G3 (symmetry, order independence) holds
  by construction and is tested;
- **differences:** candidate minus each baseline, with 95% CIs from 1,000 event-clustered bootstrap replicates
  (seed 20261126).

Playoff matches are reported as secondary, with no decision attached: the served label does not cover them.

## 6. Baselines to beat

1. **The served M6+M7** (d18 pins in `scripts/local_test_env.PINS`), on the same rows. This is the baseline that
   decides.
2. **The raw-EPA logistic:** the same model on raw points, fit on the same training rows.
3. **The base rate:** the training rows' red-win rate (0.5287).

## 7. The pre-registered 2027 evaluation, and conditions for production

**The run.** Once, after a 2027 data cutoff that the owners record before running it. The command:

    python -m scripts.evaluate_model_candidates --season 2027 --pre-registered-2027-run --reps 1000 --out <record>

It uses this spec's code at its committed revision, a D18-procedure frame that includes 2027, and b as frozen. No
re-run after looking, and no change of population or metric.

**The candidate passes only if all hold on 2027 qualification matches:**
1. candidate − served M6+M7 log loss has a 95% CI **entirely below 0**;
2. the D6 gate's G1 **and** G2 pass;
3. candidate − raw-EPA logistic and candidate − base rate log loss each have a 95% CI entirely below 0.

**Production also needs (a pass is necessary, not sufficient):**
- the owners' written approval (Kanav Jaitly and Sven Morais), recorded under `.agent/phase*/decisions/`;
- registration in the model registry (`ml/registry.py`) with a manifest naming this spec and the 2027 record;
- a serving decision covering pins, the served label and its scope (`ml/validation_scope.py`), and a contract relock
  if any served value changes;
- a point-in-time check of the serving path.

Nothing here changes production. Without a pass, M6+M7 stays served as it is, with the 2026-11-26 labels.

## 8. Retrospective 2026 evidence (NOT validation)

2026 was examined repeatedly before this candidate existed (D15, D18, the M7 diagnostic, P5-M4, the audit). These
numbers are reported for transparency, and they **cannot** support approval. 2026 qualification, EPA-complete,
non-tie, n = 12,245, 208 events:

| | Log loss | Brier | AUC | ECE | G1 | G2 |
|---|---|---|---|---|---|---|
| **WP-NORM-EPA-v1** | **0.4988** | **0.1651** | 0.8364 | 0.0104 | pass | **fail** (1 bin) |
| served M6+M7 | 0.5394 | 0.1719 | 0.8225 | 0.0153 | pass | fail (1 bin) |
| raw-EPA logistic | 0.6356 | 0.1713 | 0.8520 | 0.1123 | fail | fail (8 bins) |
| base rate | 0.6952 | 0.2510 | 0.5 | 0.0318 | pass | unevaluable |

Candidate minus served: log loss −0.0406 (95% CI −0.0625 to −0.0190), Brier −0.0068 (−0.0132 to −0.0004). On 2026 the
candidate would **fail** its own condition 2 (G2). On playoffs (n = 2,782) it scores log loss 0.5534 vs 0.5745 served,
but neither passes G1.

**Seen after freezing the definition, and deliberately not acted on.** The audit's exploratory version divided every
team's EPA by the first team's scale. It scored lower log loss on 2026 (0.478 with the 1e−6 clamp). For a team whose EPA
comes from 2025, that version divides 2025 points by a 2026 scale, which shrinks stale cross-season EPA toward zero.
That may be a real effect. Adopting it now would be choosing a definition by its 2026 result. A variant that treats
cross-season EPA explicitly (for example, a separate coefficient or shrinkage for prior-season sources) would be
WP-NORM-EPA-v2, frozen before 2027 data is seen.

## 9. Known limitations

- One feature. It ignores in-event form, which the served model's later features carry. A variant adding the
  normalized in-event average was better still on 2026 in the audit. That too would need its own spec.
- Early-season matches rely on prior-season EPA (section 8).
- The model is fit on all competition levels, but the decision population is qualification only.
