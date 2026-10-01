# Phase 4 — M5 redesign and M7 gate: specifications

Status: **FROZEN — decision D16 (Kanav, 2026-09-30).** M6 approved as-is; M5 v2 approved as specified with no changes; M7 approved with the G2 clarification incorporated below (fixed bins, the unevaluable rule, no practical-difference threshold). The commit introducing this status line is the freeze point. Nothing may change below it without a new decision.

Order:
- M7 is implemented, verified against §2.5's pre-stated criteria, and run only if every check passes;
- then M5 v2 is implemented and run **once**; a gate failure stops and escalates.

Unchanged:
- the failed M5 result and its evidence (`M05_ESCALATION.md`, `results/m05_*`);
- M4's frozen numbers;
- D5's gate form and D6's ECE threshold;
- EPA methodology and the D7 split.

Notation: Y is the season, e an event, m a match. Scores are TBA's official alliance scores (`score_red`/`score_blue`, fouls included). "Retained" means a row of the M2 training frame (M2's exclusion rules applied: DQ-affected and unplayed matches are excluded).

---

## 1. M5 — redesigned ranking model (`RANKING_MODEL_VERSION` 2.0.0, a new class; v1 is kept unchanged)

### 1.1 Target: event-level attributed contribution to qualification win margin

For each training event e (seasons 2024, 2025 only):

**Matches and teams.**
- Q_e = e's retained qualification rows.
- T_e = the teams that appear in them.
- n_i = the number of rows in Q_e containing team i.

**Equations.** For each m ∈ Q_e, the margin d_m = S_red(m) − S_blue(m). The design row a_m ∈ ℝ^{|T_e|} has:
- a_{m,i} = +1 if i is on the red alliance of m;
- a_{m,i} = −1 if i is on the blue alliance;
- a_{m,i} = 0 otherwise.

**Attribution** (ridge least squares, λ = 1, fixed in advance):

  ĉ_e = argmin_c Σ_{m∈Q_e} (d_m − a_mᵀc)² + λ‖c‖²  =  (AᵀA + λI)⁻¹ Aᵀd

**Normalization (label side only).** σ_e = population SD of {S_red(m), S_blue(m) : m ∈ Q_e}.

**Target.** For team i at event e:

  y_{i,e} = ĉ_{e,i} / σ_e

y_{i,e} is defined only when n_i ≥ 3 and σ_e > 0. Otherwise the team-event contributes no training samples, and the count is reported.

Every training sample (§1.4) of team i at event e carries the same label y_{i,e}.

**Why it is an individual contribution.**
- Each team plays with different partners and against different opponents across the schedule. Least squares uses that variation to separate each team's share of its alliances' margins: the standard OPR/CCWM attribution.
- The v1 target gave all three partners the identical margin of every match. Here two partners receive different values whenever their other matches differ.
- Margin equations cannot identify a common shift (3 + 3 alliances cancel it). The ridge term fixes it at the minimum-norm solution, so ĉ_e is centred near 0: a contribution relative to that event's field.

**Why it suits final qualification rank.**
- Rank is ordered by ranking points, and most RP comes from winning qualification matches (win RP is 2 in 2024, 3 in 2025/2026).
- Winning is decided by the sign of the official margin over exactly the matches Q_e. y_{i,e} is the team's attributed share of that margin over those same matches.
- Bonus RPs are not modelled. They correlate with scoring but are a documented limitation, as in v1.

**Why it uses no future information.**
- y is a training label: an outcome of a training-season event, computed after that event, never a model input.
- Training uses only 2024 and 2025 (D7); no label is ever computed for 2026.
- Features (§1.2) are snapshots strictly before each sample's as_of.
- σ_e is label-side only. It is never used to normalize a feature or a prediction.

**Edge cases.**
- **Ties:** d_m = 0, kept as an equation (it is evidence of equal strength).
- **Penalties:** official scores are used because they decide the win. Foul points a team concedes reduce its margin and are attributed to it; foul points awarded to it are opponent behaviour and act as noise spread by least squares.
- **Zero scores** are kept as recorded (9 alliances in training).
- **DQ-affected and unplayed matches** are absent, by M2's rules (the default `include_dq_affected=False`).
- **Surrogate appearances** count as played: the robot played, even though FRC excludes the match from that team's ranking (131 training rows).
- **Short or placeholder alliances:** a missing slot contributes 0 to a_m. Every training qualification row is 3 vs 3.
- **Replays:** each retained match_key is one equation.
- **Playoff-only teams** (no qualification rows) get no label.

Training data: 15,618 team-events in 383 events. Only 1 has n_i < 3.

### 1.2 Features: causally normalized

**Season scale.** S(Y, t) = population SD of every official alliance score in completed matches of season Y (all events) with scheduled_time < t.
- It is defined only when at least 200 such alliance scores exist; otherwise it is absent.
- It is read from the canonical `matches` table.

At a snapshot of team i for target event e (season Y) at time as_of:

**In-event features** (game points), each divided by S(Y, as_of):
- average_score, score_stddev, average_auto_points.

**EPA features** (game points): epa_total, epa_auto, epa_teleop, epa_endgame, each divided by:
- S(Y, as_of) if the D13-selected source event is in season Y;
- S(Y_src, +∞) — the full source season, which is complete before season Y begins — if it is from an earlier season Y_src.

**Unchanged** (already scale-free or counts): consistency_rating, reliability_score, matches_considered, matches_used, and the defense/feeding fields.

**Missing values.** A normalized feature is NaN (absent) if its raw value is absent or its scale is absent. Nothing is imputed, as in v1.

**Two new TeamFeatures fields**, each with a presence flag: `score_scale` and `epa_scale`.
- They are filled by the assembler from canonical tables only, and are causal by construction.
- They are additive: `TEAM_FEATURE_NAMES` is not changed, so M6's inputs are unchanged.
- M5 v2 builds its own feature vector from them.

### 1.3 What a snapshot may contain (the information set at as_of)

- EPA from D13's selected prior event: concluded before as_of, and its STRATAI value available before as_of.
- The team's own completed matches at this event strictly before as_of. At a qualification snapshot these can only be earlier qualification matches.
- S(Y, as_of), from matches strictly before as_of.

Never: playoff results, RP standings, the final rank, or any match at or after as_of.

### 1.4 Training samples

- One sample per (team appearance in a training-season qualification row with a defined label).
- Features: that row's snapshot (§1.2). Label: y_{i,e}.
- Playoff rows are not used.
- XGBoost parameters, rounds and early stopping (temporal last 20% of samples by scheduled_time) are exactly v1's. Nothing is tuned.

### 1.5 Primary evaluation (2026 held-out; the gate)

**Decision point.**
- For each 2026 team-event: take team i's retained qualification rows at e in scheduled order, n_i of them.
- The decision snapshot is its k-th row, with k = ⌈n_i / 2⌉.
- So the prediction is made halfway through the team's qualification schedule, with k − 1 of its matches known.
- Every decision snapshot is before qualification ends, so no post-qualification snapshot exists in the evaluation.
- The schedule (and therefore n_i) is published before the event starts.

**Score.**
- Per event with real final qualification ranks: the Spearman correlation between predicted rating and −final rank, over teams with both (at least 2).
- Averaged over events. This is the same statistic and averaging as `run_ranking_backtest`.

**Baseline under the identical protocol.**
- `RawEpaRankingBaseline` (unchanged), scored on the same snapshots, events and teams.
- *Documented reason:* the old 0.5951 used the latest snapshot including playoffs, which also adds playoff-only backup teams. A valid comparison needs identical decision points.

**Gate (D5's form, made stricter).** M5 v2 passes iff Spearman(M5 v2) > the same-protocol baseline **and** Spearman(M5 v2) > the frozen 0.5951.

**Secondary diagnostics** (reported, not gating):
- top-8 recall;
- the same evaluation at k = 1 (pre-event) and at k = n_i (last qualification snapshot);
- label shuffle over 8 seeds;
- retrain reproducibility;
- feature gain shares.

### 1.6 Then

- Run once.
- Pass → `M05_ACCEPTANCE.md`.
- Fail → stop and escalate (D9). No second redesign.

---

## 2. M7 — calibration gate (replaces the [0.60, 0.70) → 58–62% band)

### 2.1 Model and data

- **Model and training rows:**
  - M6's `WinProbXGBModel` (unchanged), trained by `fit_calibrated_win_prob_model` on the EPA-complete 2024 + 2025 training rows (the M6 / M11 population);
  - the model is fit on the first 80% (temporal);
  - the calibrator on the last 20%, never on 2026.
- **Evaluation:** EPA-complete 2026 held-out rows, ties excluded (the M4 / M6 population).

### 2.2 Symmetric calibrator (new class; the existing calibrators are kept)

Let p = M6(R, B); M6 guarantees M6(B, R) = 1 − p.

**Fit.** Isotonic regression g (non-decreasing, clipped to [0, 1]) on the perspective-augmented calibration set:

  D = {(p_j, y_j)} ∪ {(1 − p_j, 1 − y_j)}

**Serve.**

  q(R, B) = ½ · [ g(p) + 1 − g(1 − p) ]

**Properties** (exact in real arithmetic):
- q(B, R) = ½[g(1 − p) + 1 − g(p)] = 1 − q(R, B);
- q is non-decreasing in p;
- q ∈ [0, 1].

The symmetrization guarantees symmetry for any g. The augmentation makes the fit itself use each match from both perspectives.

### 2.3 The gate (all four must pass)

**G1 — global calibration (D6, unchanged).** ECE(q, y) < 0.05.
- ECE is M3's `expected_calibration_error`, with 10 equal-width bins over [0, 1] and bin index min(⌊10q⌋, 9).

**G2 — per-bin statistical consistency.**
- **Bins, fixed before evaluation:** the 10 boundaries are 0, 0.1, 0.2, …, 1.0. Bin b, for b = 0…9, holds the predictions with min(⌊10q⌋, 9) = b, computed as `min(int(q * 10), 9)` — the same expression as G1's ECE. So bins are [b/10, (b+1)/10), except the last, which also contains q = 1. The boundaries never depend on the data.
- **Eligible bins:** a bin is eligible if n_b ≥ 30 (`DEFAULT_MIN_BIN_COUNT`). Bins with fewer than 30 predictions are reported as **untested**, never as passing.
- **Hypothesis:** for each eligible bin b, with W_b = observed wins, H₀ is W_b ~ PoissonBinomial({q_i : i ∈ b}). That is, the observed win count is consistent with the bin's own individual predicted probabilities.
- **Exact pmf:** P is computed by the exact recursion over the bin's q_i (no approximation).
- **p-value:** the exact two-sided p-value p_b = Σ_{k : P(k) ≤ P(W_b)·(1 + 10⁻⁷)} P(k). The 10⁻⁷ relative tolerance treats probabilities equal up to floating-point error as tied, the convention of R's `binom.test`. p_b is capped at 1.
- **Family correction:** Holm–Bonferroni over the m eligible bins at α = 0.05. Sort p_(1) ≤ … ≤ p_(m); reject p_(j) while p_(j) ≤ 0.05 / (m − j + 1), stopping at the first non-rejection.
- **Outcome:**
  - **unevaluable** if m < 2. This is not a pass: M7 cannot be accepted, and execution stops and escalates.
  - Otherwise **pass** iff no bin is rejected, and **fail** if any bin is rejected.
- **No practical-difference threshold.** The decision is the statistical test alone.
- **Report:** every bin's boundaries, n_b, mean q, observed wins and rate, expected wins Σq_i, the central 95% Poisson-binomial interval of the rate under H₀ (smallest k with CDF ≥ 0.025 to smallest k with CDF ≥ 0.975, divided by n_b), p_b, Holm threshold and decision; untested bins listed with their counts.

**G3 — exact symmetry.**
- For every evaluation row, max |q(R, B) + q(B, R) − 1| ≤ 1e-12, computing q(B, R) through the full model on the swapped feature row.
- Predictions are identical in forward and reversed call order.

**G4 — fit isolation.** The calibrator's fit set contains no 2026 row (the existing structural guarantee, asserted).

### 2.4 Why this definition

- Under perfect calibration, E[W_b] = Σ q_i. G2 therefore compares each bin's observed rate with *its own* mean prediction, which removes the old check's fixed-0.60 target.
- The tolerance comes from the exact sampling distribution of the bin's own predictions instead of a fixed ±0.02.
- The family-wise false-failure rate for a perfectly calibrated model is ≤ 5%.
- **Large bins are sensitive.** Bins near 0 or 1 can hold thousands of predictions (5,118 in M4's [0.9, 1.0) bin), so small real miscalibration is detectable there and G2 will reject it. That is intended: the gate certifies consistency, not approximate closeness. G1 still bounds overall size.
- On the M4 predictions, a perfectly calibrated model's expected ECE is 0.0059, so G1's threshold is attainable.

### 2.5 Verification before the real-data run (criteria fixed here, before any run)

All synthetic. Every check must pass before M7 touches 2026; any failure stops M7.

**V1 — probability calculation.**
- (a) The pmf equals brute-force enumeration over all 2ⁿ outcomes for 200 random probability vectors, n = 1…12: max |difference| ≤ 1e-12, and each pmf sums to 1 within 1e-12.
- (b) For n = 300 random probabilities, 200,000 simulated draws match the pmf: total-variation distance ≤ 0.01, and the simulated mean and variance are within 1% of Σp and Σp(1 − p).
- (c) p-values agree with SciPy's exact `binomtest` when all probabilities in a bin are equal (n ∈ {30, 100, 500}, several p), within 1e-9.

**V2 — false-failure rate under perfect calibration.**
- 1,000 synthetic datasets of 15,000 predictions each, drawn from a U-shaped Beta(0.5, 0.5), with labels drawn so the predictions are exactly calibrated.
- The G2 failure rate must be ≤ 0.05 within sampling error: its 95% Clopper–Pearson lower bound ≤ 0.05.
- No dataset may be "unevaluable".

**V3 — power to detect miscalibration.** Same design, 200 datasets per scenario. G2 must reject in ≥ 80% of datasets in each:
- (i) overconfidence: true logit = 0.8 × predicted logit;
- (ii) a uniform shift: true probability = clip(q + 0.03, 0, 1).

Rejection rates are also reported for (iii) a mild shift of +0.01, for information only.

**V4 — symmetry.**
- (a) The calibrator alone: |q(p) + q(1 − p) − 1| ≤ 1e-12 for 100,000 random p, plus the endpoints and 0.5. q is non-decreasing on a sorted grid.
- (b) End to end: M6 trained with the symmetric calibrator via `fit_calibrated_win_prob_model` on synthetic rows. For 1,000 synthetic matches, |q(R, B) + q(B, R) − 1| ≤ 1e-12 through the full model on the swapped rows, and predictions are identical in forward and reversed order.

**V5 — regression.** The existing calibration tests pass, including fit isolation and small-bin honesty, together with new unit tests for the gate's pass, fail and unevaluable outcomes.

---

## 3. Order and records

1. **M6** (unchanged) can run now on frame `54e9d54b…`. M5 v2's new TeamFeatures fields are additive and do not change M6's inputs.
2. **M7** after §2 is implemented and its §2.5 checks pass.
3. **M5 v2** after §1 is implemented; it needs a frame rebuilt with `score_scale` / `epa_scale`. The M4 ranking baseline is re-scored under §1.5 on that frame; M4's frozen 0.5951 stays the recorded M4 number.
4. **M11** when its dependencies are met.
5. **M13** only after all required milestones pass.

This decision is recorded as D16 in `PHASE_STATUS.md`.
