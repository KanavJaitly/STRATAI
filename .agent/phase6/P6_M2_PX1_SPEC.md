# PX-1 (P6-M2) and PX-2 (P6-M3): frozen model and evaluation specification

**Written 2026-10-05, before any PX-1 data was assembled and before any result existed.** The commit introducing this file freezes it.
- **What it implements:** frozen decisions P6-Q2 (model and features), P6-Q3 (the PX-1 gate) and P6-Q4 (PX-2), plus the P6-M0 interpretation notes.
- **What it fixes:** only the implementation details those decisions leave open.
- **D9:** one run of each milestone; nothing here changes after a result.

**Blocked until P6-M1 exists.** The bracket round comes from the approved P6-M1 ruleset's slot mapping, so PX-1 cannot be assembled until approved rulesets exist for 2024, 2025 and 2026. No rule is hard-coded instead.

## 1. Rows

- **Matches:** canonical 2024–2026 playoff matches (`competition_level` ∈ {semifinal, final}) with a winner (TBA `winning_alliance`).
- **Ties:** excluded from fit and evaluation, counted.
- **Alliances:** from P5-M1 (`read_event_alliances`). A match side maps to the alliance whose captain-and-picks contain **at least two** of that side's three teams. Backups are unknown, so substitutes are tolerated.
- **Excluded, counted by reason:**
  - an unmappable or ambiguous side;
  - an event among the **15 division-champion events with null seeds** (P6-Q2);
  - a match whose (`competition_level`, `set_number`) is absent from that season's approved slot mapping;
  - an event whose bracket reproduction failed in P6-M1.
- **Selection moment** of an event: one minute after its latest qualification match's `scheduled_time`. Team features are assembled at that `as_of` (the Phase 4 assembler, D18 EPA semantics, causal scales). **No earlier or in-playoff result is ever a feature** (P6-Q2): all of an event's playoff matches share the selection-moment features of their alliances.
- **EPA-incomplete rows** (any of the six teams without `epa_total`) are excluded, counted (P6-Q2).
- **Splits:**
  - fit: 2024–2025;
  - evaluation: held-out 2026, with the same exclusion rules;
  - PX-2 calibration slice: the **temporally last 20% of the 2025 eligible playoff matches**, by `scheduled_time` (P6-Q4).

## 2. Features (P6-Q2: seed difference, alliance composition sums, bracket round; nothing else)

- **Seed difference:** `s = seed_red − seed_blue`.
- **Composition sums:** the Phase 4 M6 alliance representation, `TEAM_FEATURE_NAMES` summed per alliance (`ml.models.win_prob._alliance_vector`), entered as **red − blue differences**.
  - A composition column is used only if it is present for all six teams in **every** eligible training row.
  - A column absent everywhere is dropped and recorded as "no data". Today these are defense/feeding score and agreement, because there are 0 scouting rows.
  - A column whose difference has no variation in the training rows is dropped and recorded.
  - Nothing is imputed. An evaluation row missing a used column is excluded, counted, as `insufficient_data`.
- **Bracket round** r: the slot's round from the approved ruleset (the finals' round for finals).
  - Main effects: the difference vector d = (s, composition differences).
  - Round enters as **interactions** d·1[r = k] for every round k present in the training rows except the lowest (the reference).
  - A symmetric round term alone cannot move an antisymmetric probability (P6-M0 interpretation note).
- **Scaling:** each column is divided by its root mean square over the training rows. This is not centred, so negating a row negates its features exactly.
- **No intercept.**

## 3. Model

- **Fit:** `sklearn.linear_model.LogisticRegression(penalty="l2", C=1.0, fit_intercept=False, solver="lbfgs", max_iter=10000)` on the training rows, label red-win.
  - **No tuning:** C = 1.0 is fixed here, before any data.
  - **Deterministic:** lbfgs on fixed data.
- **Probability:** p(red) = expit(w·x) and p(blue) = expit(−w·x), so swapping the alliances gives exactly the complement up to floating-point rounding. The model is antisymmetric by construction.
- **Registry:** `playoff_px1` / `px1-v1`, write-once, with the column list, the dropped columns and the scaling factors.

## 4. PX-1 gate (P6-Q3)

- **Held-out 2026 log-loss of PX-1** (uncalibrated) must be **strictly better than both** baselines, on the same rows:
  1. **M6/M7:** the registered `win_prob_xgb_calibrated` `d18`, applied to each playoff match's selection-moment features (the same inputs as PX-1; never in-playoff data).
  2. **Seed-only:** a logistic regression on the seed difference alone (no intercept), fit on the same 2024–2025 rows.
- For each comparison, the **paired event-bootstrap 95% CI** of (PX-1 log-loss − baseline log-loss) per match must lie entirely below 0 (2,000 resamples, seed 20261010).
- If either comparison fails: D9, stop and escalate.

## 5. PX-2 (P6-Q4)

- **Calibrator:** `SymmetricIsotonicCalibrator`, fit on PX-1's raw outputs on the calibration slice (§1), with both perspectives as in M7.
- **Gate:** `evaluate_calibration_gate` with the M7/D16 constants unchanged, on held-out 2026:
  - G1: ECE < 0.05;
  - G2: 10 bins, at least 30 per bin, exact Poisson-binomial test, Holm α = 0.05;
  - G3: symmetry within 1e-12, with order independence;
  - G4: fit isolation, the slice entirely before 2026.
- **Served probabilities:** pass gives `validated_playoff`; fail gives `not_validated` (`px2_gate_failed`), with D9 applying.

## 6. Records

- `.agent/phase6/results/p6_m2_px1.json`
- `.agent/phase6/results/p6_m3_px2.json`

Both are write-once, with the row and exclusion counts, the column list, the registry sha256s, the commit and the per-run time budget (45 minutes).
