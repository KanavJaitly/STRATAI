# PX-1b: frozen specification, version 1 (written 2026-10-08, before any PX-1b fit or evaluation)

**Frozen by the commit that introduces this file.** Every PX-1b record cites this file's git blob, and nothing here changes after a PX-1b result. A change is a new version (`P6_M2_PX1B_SPEC_V2.md`), written before the run it governs.

**Status of PX-1, unchanged:** `not_validated` under its own frozen spec, from run 1 and rerun1. PX-1b is a separate model; nothing here relabels a PX-1 run.

**What this specification has, at the time of writing:**
- **Seen:** the PX-1 records, the root-cause audit (`decisions/P6_PX1_AUDIT_DEFECTS_2026-10-08.md`), and a label-free audit of the causal scales on the PX-1 rerun1 rows (§3.4).
- **Not seen:** any PX-1b prediction or outcome.

## 0. Hypothesis

PX-1's composition features are sums in season-specific point units, scaled by their 2024–2025 RMS. When a season's scoring scale changes (2026 is about 3–4.5× 2024–2025), they put the logits out of distribution: PX-1 ranks matches well but is overconfident.

**H-PX1b:** dividing each point-unit team feature by the causal season scale of its own units, before summing, makes the composition features comparable across seasons. It should therefore reduce out-of-distribution logits.

**This is a hypothesis.** The scale audit (§3.4) shows that normalization removes most, **not all**, of the cross-season shift.
- Normalized `average_score` and `epa_endgame` still grow about 1.6–1.7× from 2024 to 2026.
- The unit-free `consistency_rating` grows about 2×.
- Better calibration is not assumed; §5 and §6 test it.

## 1. Rows

**Unchanged from PX-1 §1:** competitions, winners, ties, selection-time members (D-PX1-1), the four-member exclusion (D-PX1-2), the selection moment, selection-moment features (Phase 4 assembler, D18 EPA), the EPA-incomplete exclusion, and the P6-M1 reproduction and approved rulesets.

**Exclusions, each counted by reason, applied identically to every model in a comparison** (all models see the same rows):
1. **`playoff_before_selection_moment`:** an event with any playoff match whose `scheduled_time` is strictly before its selection moment yields no rows. Each of its playoff matches counts once. This rule is also PX-1 amendment A1, but PX-1b states it itself.
2. **The PX-1 §1 per-row reasons, in PX-1's order:** `side_unmappable`, `slot_unknown`, `tie_or_unplayed`, `four_member_alliance`, `epa_incomplete`. The per-event exclusions are also unchanged: `event_not_reproduced_or_excluded`, and `event_<code>` for an unexplained listing.
3. **`scale_absent` (new, after `epa_incomplete`):** a row where any of the six teams lacks a **valid** `score_scale` or a **valid** `epa_scale`.
   - **Valid** means present (`*_present` true), not None, finite, and > 0.
   - An invalid present value (0, negative, NaN, inf) is treated as absent.
   - Nothing is imputed, and no other scale is substituted.

**Label:** `red_win = (TBA winning_alliance == "red")`, as in PX-1.

## 2. Features (the only change from PX-1)

### 2.1 Per-team normalized vector
Each team's vector is `ml.models.ranking_xgb_v2.team_vector_v2` (decision D16 §1.2), in `TEAM_FEATURE_NAMES` order:

| Team field | PX-1b value |
|---|---|
| `epa_total`, `epa_auto`, `epa_teleop`, `epa_endgame` | value / `epa_scale` |
| `average_score`, `score_stddev`, `average_auto_points` | value / `score_scale` |
| `consistency_rating`, `reliability_score`, `matches_considered`, `matches_used`, defense/feeding fields and observation counts | unchanged (already unit-free) |

### 2.2 The denominators
- **`score_scale`** = S(Y, as_of): the population standard deviation of every official alliance score (`score_red`, `score_blue`) in completed matches of the event's season Y, at all events, with `scheduled_time < as_of`. It is defined only when at least 200 such scores exist (`ml/features/scale.py`, D16).
  - **Used for:** in-event, point-unit history of the current season (`average_score`, `score_stddev`, `average_auto_points`).
  - **Why:** those values are in season Y's points.
- **`epa_scale`:** the scale of the season whose game the EPA value measures (`ScaleLookup.feature_scales`).
  - If the EPA source event's season equals Y, it is S(Y, as_of), the same as `score_scale`.
  - If the source season Y′ < Y, it is S(Y′, whole season). A team's first event of a season carries its previous season's EPA, which is in Y′ points.
  - A later-season source gives `None`, so the row is `scale_absent`.
  - **Used for:** the EPA fields, because those are in the source season's points.
- **Why this choice:** it is the existing, accepted Phase 4 normalization (D16). It is reused, not re-derived; no alternative denominator was compared.

### 2.3 Composition, design and scaling
- **Composition:** red alliance sum − blue alliance sum of the 2.1 vectors, over the three selection-time members.
- **The rest of PX-1 §2, unchanged:**
  - the seed difference;
  - column selection (absent everywhere → dropped, "no data"; absent in some training rows → dropped; no variation → dropped);
  - round interactions for every training round except the lowest;
  - each column divided by its RMS over the training rows (not centred);
  - no intercept.

## 3. Causality: the scales use no information after the prediction time

**3.1 `score_scale`.** `_Timeline.scale(before)` uses `bisect_left` over the season's `scheduled_time`-sorted scores.
- It sums exactly the matches with `scheduled_time < before`, using exact integer prefix sums.
- `before = as_of` is the selection moment.
- The event's own playoff matches are after `as_of`, because rule 1 removes any event where they are not. They therefore never enter its scale.
- No outcome of a predicted match is in S.

**3.2 `epa_scale`.**
- **Same-season source:** it is 3.1.
- **Earlier-season source:** the whole season Y′ < Y, which ended before season Y began.
- **Later-season source:** never used.
- The EPA value itself is D18's: always from a strictly earlier, concluded event, with no same-event EPA in the PX-1 rows (audit).

**3.3 Accepted approximation (inherited from D16, disclosed).** S treats `scheduled_time < as_of` as "known at `as_of`".
- **The risk:** a match at **another** event that is scheduled before `as_of` but played later could enter S.
- **Why it is accepted:** S is a season-wide SD over hundreds to thousands of scores, and such a match is never the predicted match or one of its event's playoff matches.
- **Determinism:** S is a pure function of the stored data.

**3.4 Label-free audit on the rerun1 rows (2026-10-08).** It reads features and scales only, never outcomes.
- **Presence:** both scales are present for all six teams in 991/991 rows of 2024, 2,435/2,450 of 2025 and 2,626/2,632 of 2026. No present scale is ≤ 0 or non-finite.
- **Within an event,** all six teams share one `score_scale`.
- **EPA source season** (team snapshots): 2025 has 9,123 same-season and 5,577 earlier-season; 2026 has 9,532 and 6,260.
- **RMS of the red − blue difference, raw → normalized:**

  | Column | 2024 | 2025 | 2026 |
  |---|---|---|---|
  | `epa_total` | 17.0 → 0.75 | 31.6 → 0.87 | 96.6 → 1.01 |
  | `average_score` | 19.6 → 0.87 | 36.6 → 0.94 | 138.3 → 1.37 |
  | `epa_endgame` | 2.9 → 0.13 | 5.5 → 0.15 | 22.2 → 0.22 |
  | `consistency_rating` (unchanged) | 16.1 | 19.3 | 31.6 |

## 4. Model

- **Fit:** `LogisticRegression(penalty="l2", C=1.0, fit_intercept=False, solver="lbfgs", max_iter=10000)`, with label `red_win`.
- **Probability:** p(red) = expit(w·x); antisymmetric by construction.
- **No tuning:** nothing is tuned. C stays 1.0.
- **Seed-only comparator:** spec PX-1 §4, the seed difference alone (one column, no round terms, no intercept), fit on the same rows.

## 5. Development protocol DEV-1 (2024–2025 only; one run; not acceptance)

- **Rows:** §1 rows of 2024 (fit) and 2025 (evaluate). 2026 is not assembled.
- **Models,** all fit on the same 2024 rows and evaluated on the same 2025 rows:
  - (a) PX-1b;
  - (b) the seed-only comparator;
  - (c) **PX-1 raw design** (PX-1 §2, unnormalized), the hypothesis control.
- **Not a development comparator:** M6/M7 `d18` was fit on the 2024–2025 Phase 4 frame, so it is in-sample on 2025.
- **Reported for each model:**
  - log-loss, Brier, ROC-AUC;
  - ECE (10 equal-width bins);
  - mean |logit| on 2024 (in-sample) and 2025, and their ratio;
  - the share of p < 0.1 or > 0.9.
- **Paired comparisons:** the event-bootstrap 95% CI of the per-match log-loss difference, 2,000 resamples, seed 20261010, percentile. This is `paired_log_loss_gate`'s procedure.
- **Proceed criteria (both required; a development decision, not acceptance):**
  - **DV1:** PX-1b − seed-only log-loss: the CI lies entirely below 0.
  - **DV2:** PX-1b − PX-1 raw log-loss: the point estimate is ≤ 0 (the CI is reported).
- **Outcomes:**
  - If both hold, PX-1b proceeds to FINAL-1 (§6).
  - Otherwise PX-1b does not proceed. The record stands, and any redesign needs a new spec version.
- **Record:** `.agent/phase6/results/p6_px1b_dev.json`, write-once. It carries the commit, this spec's blob and sha256, the dataset fingerprint (§7), the seed, the row and exclusion counts, the columns, the coefficients, and the runtime.

## 6. Final candidate and acceptance gate FINAL-1 (independent 2027 holdout)

**2026 is not a PX-1b holdout.** It was evaluated for PX-1 and inspected (label-free) above. PX-1b is **never evaluated on 2026**, and no PX-1b acceptance claim may rest on 2026.

**Final fit (only after DV1 and DV2 hold):**
- **Rows:** §1 rows of 2024–2026; 2026 is training data only.
- **Models:** PX-1b and the seed-only comparator, both fit on those same rows.
- **Registry:** write-once, as `playoff_px1b` / `playoff_px1b_seed_only`, tag `px1b-v1`.
- **Refusal:** the run refuses if any 2027 playoff match exists in the database, so the candidate is frozen before 2027 outcomes exist.
- **Record:** `p6_px1b_final_fit.json`.

**Acceptance gate (the P6-Q3 form, unchanged):** on held-out 2027 §1 rows, PX-1b's log-loss must be strictly better than **both** of:
1. M6/M7 `win_prob_xgb_calibrated` `d18`, applied to the same selection-moment features;
2. the seed-only comparator.

For **each** comparison, the paired event-bootstrap 95% CI of (PX-1b − baseline) must lie entirely below 0 (2,000 resamples, seed 20261010).

**Gate mechanics:**
- **Run:** once, after the 2027 season's events are complete and synced, on Kanav's instruction. The record is `p6_px1b_gate_2027.json`, write-once.
- **If it fails:** D9 applies.

**Prerequisites before FINAL-1 can run (none exists today; the gate cannot yet be evaluated):**
1. 2027 playoff data;
2. an approved 2027 P6-M1 ruleset (human-entered; a qualified reviewer);
3. the P6-M1 reproduction check for 2027 events;
4. a D18 EPA source covering 2027.

## 7. Reproducibility

- **Dataset fingerprint:** the sha256 of the canonical JSON of every row a run uses (fit and evaluation), sorted by `match_key`. Each row contributes its match key, season, round, seeds, label, members, and every team's raw used values and both scales.
- **Determinism:** lbfgs on fixed data is deterministic, and the bootstrap is seeded.
- **Runtime:** every run carries the 45-minute budget and stops if it is exceeded.

## 8. Phase 6 dependencies (D9): an open question, not decided here

**The question.** Under the frozen P6-M0 decisions, PX-2 requires a passing **PX-1** record (`p6_m2_px1.json`), and PX-4 and P6-M8 follow from it. Nothing in the frozen decisions says whether a versioned replacement model (PX-1b) can satisfy that prerequisite. PX-2's own definition is also tied to PX-1: its calibration slice is the last 20% of 2025, and its gate is on 2026.

**Until Kanav makes a dated, versioned decision:**
- PX-1b's results, including a FINAL-1 pass, **do not unblock PX-2, PX-4 or P6-M8**;
- `scripts/phase6_playoff_track.py` and the D9 checks are not changed.

**A candidate decision, for review only:** if PX-1b passes FINAL-1, write versioned PX-2, PX-4 and P6-M8 specifications against PX-1b, with:
- the calibration slice from 2026;
- the gates on 2027;
- the M8 population from 2027 events.

**M10's separate failure is untouched by PX-1b.**
