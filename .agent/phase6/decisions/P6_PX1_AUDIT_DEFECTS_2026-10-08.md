# PX-1 root-cause audit and confirmed defects (2026-10-08)

**Scope.** This is a read-only audit of the frozen PX-1 specification and the code, records and cached rows of the frozen run (`7574d50`). It started from Kanav's request for a root-cause investigation.

**Preserved, unchanged:**
- `P6_M2_PX1_SPEC.md`;
- `results/p6_m2_px1.json` (run 1);
- `P6_M2_PX1_FAILURE.md`;
- `decisions/P6_PX1_NOT_VALIDATED_2026-10-08.md`;
- the `px1-v1` registry entries and `px_rows.pkl.gz`.

**Diagnostics:** read-only. They used the cached run-1 rows, the registered `px1-v1` models and `stratai_test` (read-only session). Nothing was refit on 2026 except the spec's own seed-only baseline in (a) below, and that only to measure defect 1's effect.

## Root cause of the gate failure

**Finding (confirmed by measurement):** a covariate-scale shift that is inherent to the frozen design. It is not an implementation bug.

**The design.** The composition features are raw red − blue sums in season-specific point units. This is the M6 `_alliance_vector` representation, which PX-1 reproduces exactly. Spec §2 scales each column by its RMS over the 2024–2025 training rows.

**The shift.** 2026 scoring is several times larger. RMS of the red − blue difference:

| Column | 2024 | 2025 | 2026 | Training scale |
|---|---|---|---|---|
| `epa_total` | 17.0 | 31.5 | 96.5 | 28.1 |
| `average_score` | 19.8 | 36.6 | 138.5 | 32.6 |
| `epa_endgame` | 2.9 | 5.5 | 22.2 | 4.9 |
| seed difference (unit-free) | 3.4 | 3.3 | 3.2 | — |

So 2026 inputs are about 3–4.5 training-RMS units where the model expects about 1.

**Effect.** PX-1's logits inflate and it becomes overconfident, but its ranking of matches is the best of the three:

| 2026 held-out | Log-loss | ROC-AUC | Mean \|logit\| | Share of p < 0.1 or > 0.9 |
|---|---|---|---|---|
| PX-1 | 0.642 | **0.826** | **4.90** | **0.655** |
| Seed-only (as built) | 0.519 | 0.776 | 0.91 | 0.074 |
| M6/M7 | 0.560 | 0.735 | — | — |

In 2025, in-sample, PX-1's mean |logit| is 1.61. The failure therefore comes from calibration under a scale shift, not from a lack of signal. It grows by round: round 6 log-loss is 0.940, against 0.504 seed-only.

**The same mechanism appears on development data only.** The frozen design fit on 2024 and evaluated on 2025, where the scale ratio is about 1.9×:
- mean |logit| rises from 1.10 to 1.77;
- 30% of predictions fall below 0.1 or above 0.9, against 1% for seed-only.

Because the root cause is in the frozen specification (§2: raw-unit composition, train-only RMS scaling), it cannot be corrected under that specification. See "Next defensible experiment" below.

## Confirmed defects (each fixed, with a regression test that failed before the fix)

**1. The seed-only baseline does not match spec §4.**
- **Spec:** "a logistic regression on the seed difference alone (no intercept)".
- **As built:** `PlayoffLogisticModel.fit(seed_only=True)` called `fit_design(rows, composition=False)`, which still added seed × round interactions. That gave 6 columns: `seed_difference` plus `*round2`…`*round6`.
- **Missed by the existing test** (`test_seed_only_baseline_uses_the_seed_alone`): it checked only that there were no composition columns.
- **Fix:** `fit_design(..., round_interactions=False)` for the seed-only model (`ml/playoffs/px1.py`).
- **Regression test:** `tests/test_phase6_px1.py::test_seed_only_baseline_is_the_seed_difference_alone`.
- **Effect on the verdict, measured:** none. The spec's 1-column baseline scores 0.5233 on 2026, against 0.5185 as built. PX-1 vs the spec baseline is +0.1186, CI [+0.0567, +0.1862]: still FAIL. The defect made the baseline slightly stronger, not weaker.

**2. Playoff results leak into the features for two training events.**
- **Data:** for `2024micmp2` (15 playoff matches, scheduled 2024-04-05 09:30–12:15) and `2025alhu`, playoff matches are scheduled **before** the event's last qualification match. For `2024micmp2`, qualifications run until 2024-04-05 17:49.
- **Why that leaks:** the frozen selection moment is the last qualification match + 1 minute. The assembler's point-in-time history (`ml/features/assembler.py`, `scheduled_time < as_of`, all competition levels) therefore contains those playoff matches' scores. The outcomes being predicted entered `average_score`, `score_stddev`, `consistency_rating` and `matches_used` for 24 training rows, which violates P6-Q2 ("no in-playoff result is ever a feature").
- **Scope:** no 2026 row is affected. Every 2024–2026 event was checked on `stratai_test`, and only these two events have a playoff match at or before the last qualification match.
- **Fix:** `EventPlayoffs.playoffs_precede_selection()`. `playoff_rows` yields no rows for such an event, counted per match as `playoff_before_selection_moment` (`ml/playoffs/data.py`).
  - The frozen selection-moment definition is **not** changed.
  - An event whose data cannot satisfy P6-Q2 at that moment is excluded, as the spec already does for events that fail bracket reproduction.
  - **For Kanav's review:** this is a new, counted exclusion reason. The alternative would redefine the selection moment, which is a spec change, so it was not taken.
- **Regression tests** (`tests/test_phase6_px1_composition.py`):
  - `test_an_event_whose_playoffs_precede_its_selection_moment_is_excluded_and_counted`;
  - `test_a_playoff_without_a_scheduled_time_cannot_leak_and_is_kept`.
- **Fixture change:** the existing fixtures put the last qualification match at the same instant as the playoffs. They now place it 2 h earlier. No other assertion changed.
- **Expected effect on the verdict:** none. Only 24 of 3,465 training rows are affected, and none of the evaluation rows.

## Checked and found consistent (no defect)

| Check | Evidence |
|---|---|
| Implementation vs spec §1–§3 (rows, members, exclusions, features, RMS scaling, no intercept, C = 1.0, lbfgs) | `ml/playoffs/px1.py`, `ml/playoffs/data.py` read against the spec; the composition is identical to `ml.models.win_prob._alliance_vector` |
| Labels and teams aligned | `red_win = winner == "red"`; red features are `members[map(red side)]`; 6,097 unique match keys; 0 rows with a team on both sides; every side has 3 teams; the better seed wins 69% / 74% / 78% |
| Probabilities valid and antisymmetric | max \|p(r) + p(swap r) − 1\| = 2.2e-16; `log_loss` clamps |
| Features available at the prediction time | EPA is always from another, earlier event (D18; 0 same-event EPA); history is `scheduled_time < as_of`; the only violation is defect 2 |
| Train/eval separation | fit on 2024–2025 rows only; evaluation on 2026 only; scaling on training rows only |
| Baselines on identical rows | both comparisons use the same 2,632 rows, 194 events and labels; recomputing from the cache gives 0.6419 / 0.5185 |
| Gate procedure | `paired_log_loss_gate`: per-match difference, event bootstrap of the pooled mean, 2,000 resamples, seed 20261010, percentile 95% CI, pass iff ci_high < 0 |

**Hypotheses considered, not established:**
- **Overfitting from 66 columns.** Some exists (2025 in-sample 0.465, vs 0.519 when fit on 2024 only), but it is small next to the scale effect.
- **Round-interaction instability.** Round-6 terms are among the largest, and the round-6 loss is the worst, but this is downstream of the scale shift.

## Verification plan (fixed before running)

- **Run:** one rerun of the frozen protocol with both fixes: `python -m scripts.phase6_playoff_track m2`. It writes `results/p6_m2_px1_rerun1.json` (write-once, superseding run 1, which is kept) and registers `px1-v2`.
- **Unchanged:** the spec, populations (plus the counted exclusion above), features, C, gate, resamples and seed.
- **Runtime:** expected about 1 min; the harness enforces 45 min.
- **Downstream:** PX-2 and PX-4 still read run 1's record and `px1-v1`. A pass would not unlock them automatically, and any change to that pointer is a separate, reviewed step.

## Next defensible experiment (proposal only; not implemented or evaluated)

**PX-1b:** the same structure, with each composition column divided by the causal season scale S(Y, t). That is D16's `score_scale` / `epa_scale`, which `build_team_features` already supplies point-in-time, so the inputs become unit-free across seasons.

It requires a **new, separately versioned specification frozen before any fit**, with:
- development data 2024–2025 (for example a 2024→2025 check, as above);
- a leakage policy that includes defect 2's guard;
- the gate stated in advance;
- **an untouched holdout for the acceptance claim.** 2026 has been observed and cannot validate PX-1b; the first candidate is the 2027 season.

No new acceptance gate is defined here.
