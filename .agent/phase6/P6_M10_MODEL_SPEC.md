# P6-M10 — strategy-conditional outcome model: frozen model specification

**Written 2026-10-05, before the model was fit and before any evaluation result existed.** The commit introducing this file freezes it. It implements frozen decisions P6-Q8 (the component model) and P6-Q9 (the baseline gate), plus P6-A4, A5, A8, A9, A12, Q10, Q11 and Q12. Nothing here changes a frozen decision; this file fixes the implementation details those decisions leave open. **D9 applies:** one evaluation run, and no change to this specification after a result.

## 1. Inputs (all measured; nothing imputed)

For each of the six teams in a match, at the match's `as_of`, from `TeamFeatures` (Phase 4 assembler, D18 / P5-M2 EPA semantics):
- `epa_auto`, `epa_teleop`, `epa_endgame`: prior-event Statbotics EPA components (points). Their sum equals `epa_total` (checked on the D18 frame: max |difference| 0.01).
- `epa_scale`: the causal scale of that team's EPA source (D16).
- `score_scale`: the causal scale S of the match's season at `as_of` (D16). All six teams share one value. A disagreement is an error, not a choice.

If any team lacks a component, `epa_scale` or `score_scale`, the model returns `insufficient_data` and no probability.

## 2. Capabilities and strategy conditioning (P6-Q8)

- **Measured capability** of team t on component c ∈ {auto, teleop, endgame}: `cap[t,c] = max(0, epa_c) / epa_scale[t]`. Capability is non-negative: a negative EPA estimate is measurement noise, not a negative contribution a robot can withhold.
- **Strategy weight** `w[t,c] ∈ {0, 1}`. It is 1 if and only if all of these hold:
  - c is among the robot's pursued components;
  - c ≠ teleop, or the robot's role is `scoring`;
  - no applicable coach observation marks (t, c) or robot t unavailable.
- Role allocation therefore only re-weights contributions **within** measured capability. It never exceeds it.
- **Alliance component mean:** `mu[A,c] = sum over the alliance's teams of w[t,c] * cap[t,c]`.
- **Defense and feeding effects** enter only from measured data. Today `scouting_observations` has 0 rows (P6-Q12), so the effect is **zero**, labelled `not_validated` / `insufficient_data` (P6-Q11), never estimated.

## 3. Outcome model

- **Normalized actual component difference** of a match: `d[c] = (a[red,c] - a[blue,c]) / S`, for c ∈ {auto, teleop, endgame, other}. The components come from the P5-M7 adapters, with `other = fouls + adjust`, so the four sum to the official score difference.
- **Predicted component difference:** `delta[c] = mu[red,c] - mu[blue,c]`; `delta[other] = 0`, since no team capability exists for fouls.
- **Model:** `d = B·delta + e`, where B = diag(beta_auto, beta_teleop, beta_endgame, 0) and e ~ N(0, Σ) (4×4).
- **P(red wins)** = Φ(m / s), with m = Σ_c beta_c·delta[c] and s = sqrt(1ᵀ Σ 1).
  - Φ is computed as ½·erfc(−x/√2), so swapping red and blue gives exactly 1 − p up to floating-point rounding.
  - There is no intercept: the model is antisymmetric by construction.
- **Ties:** a continuous score difference gives P(tie) = 0. Ties are excluded from evaluation, as in M7.

## 4. Fit (training only; never 2026)

- **Rows:** D18 frame rows, `frame_ab1adbf38b43c2f3` (content hash recorded), with:
  - season ∈ {2024, 2025};
  - comp_level = qualification;
  - EPA-complete (six teams with `epa_total`);
  - every §1 input present;
  - a valid score breakdown for both alliances (P5-M7 adapter parity holds), read from `raw_source_payloads` on the isolated `stratai_test` copy, whose totals equal the match's official scores.
- **Ties are kept for fitting.** The regression is on score differences, not labels.
- **Exclusions:** counted by reason.
- **beta_c** (c ∈ {auto, teleop, endgame}): ordinary least squares without an intercept, for each component separately: beta_c = Σ d[c]·delta[c] / Σ delta[c]².
- **Σ:** the uncentred second moment of the residual vectors, Σ = (1/n) Σ eeᵀ, with e = d − B·delta. Uncentred because the model has no intercept, so its residuals have mean 0 by construction of the difference.
- **Determinism:** no randomness in the fit.
- **Artifact:** registered write-once in the model registry as `model_type = "strategy_outcome_component"`, `version_tag = "p6m10-v1"`. The model file holds beta, Σ, the fit counts and the sha256 of this specification.

## 5. Evaluation (P6-Q9; one run)

- **Population:** held-out **2026 EPA-complete qualification** matches in the same D18 frame.
  - **Excluded, counted:** ties (as M7), and matches the model cannot score because a §1 input is absent.
  - The profile before this spec, which looked only at availability counts, found 30 EPA-complete 2026 qualification matches without a causal scale.
- **Gate: the M7/D16 constants, unchanged** (`ml.calibration.gate.evaluate_calibration_gate`):
  - G1: ECE < 0.05.
  - G2: exact Poisson-binomial per-bin test, Holm α = 0.05, 10 fixed bins, bins with ≥ 30 predictions.
  - G3: |p(R,B) + p(B,R) − 1| ≤ 1e-12, with order independence.
  - G4: fit rows only from 2024–2025, and every fit row strictly before every evaluated row.
  - The baseline passes only if all four pass.
- **Reported, not gated (P6-Q9):**
  - log-loss, Brier and ECE;
  - the **paired log-loss difference vs M6/M7** (the registered D18 pair `win_prob_xgb_calibrated` `d18`, applied to the same rows), with an event-bootstrap 95% CI (2,000 resamples, seed 20261005). P6-M10 is not required to beat M6/M7.
- **Record:** `.agent/phase6/results/p6_m10_outcome_model.json`, write-once, with the frame hash, the artifact sha256, this spec's blob and the commit.
- **Runtime:** a closed-form model on about 12k rows; well under 45 minutes.

## 6. Served status

| Case | `validation_status` |
|---|---|
| Baseline strategy for both alliances, no coach observations, qualification context | `validated` if §5 passed; otherwise `not_validated` (`p6_m10_gate_failed`) |
| Any non-baseline strategy | `not_validated` (`strategy_effect_unmeasured`), plus `insufficient_data` reasons for defense / feeding roles (P6-Q11, P6-Q12) |
| Any coach observation applied | `not_validated` (`coach_observation_effect_unmeasured`) |
| Playoff context | refused (`playoff_model_unavailable`) until PX-1/PX-2 pass (P6-A12) |

**Display (P6-A5):** below 0.05 shows "<5%", above 0.95 shows ">95%"; otherwise the Phase 4 0.05 step, symmetric about 0.5. The internal probability is never clamped.

## 7. D9

A genuine gate failure is recorded write-once, and the baseline odds are then served `not_validated`. Nothing in §1–§5 changes after a result. The strategy track's other milestones continue, carrying that status.
