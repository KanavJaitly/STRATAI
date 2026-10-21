# P6-M2 PX-1: the gate FAILED (D9: recorded, not redesigned)

2026-10-08. This file is a failure record, not an acceptance record.

**Run:** one run, exactly as specified, at `7574d50` (0.8 min).
- **Specification:** `.agent/phase6/P6_M2_PX1_SPEC.md` (blob `24b427f2…`), unchanged.
- **Composition decisions:** `.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md` (blob `119b25ff…`; D-PX1-1 to D-PX1-5, C1/C2), as approved before the run.
- **Rulesets:** the approved P6-M1 v2 rulesets, ids 4–6 (`c782fc1`).
- **Record:** `.agent/phase6/results/p6_m2_px1.json`, write-once.
- **Registry:** the frozen run registers `playoff_px1` / `playoff_seed_only` `px1-v1`.

**Rows:**
- **Fit:** 3,465 eligible 2024–2025 playoff matches.
- **Evaluation:** 2,632 held-out 2026 matches over 194 events, 0 `insufficient_data`.
- **Excluded, by reason:**
  - 2,392 EPA-incomplete;
  - 364 `four_member_alliance` (24 FIRST Championship division events; D-PX1-2);
  - 24 events not reproduced or excluded at P6-M1;
  - 10 ties or unplayed.
- **Features used:** seed difference plus 10 composition-sum differences, with interactions for rounds 2–6 (66 columns).
- **Dropped as recorded by the frozen rules:** defense and feeding (no data); `reliability_score` and the observation counts (no variation).

| Gate (P6-Q3: PX-1 log-loss strictly better than each baseline; paired event-bootstrap 95% CI of the difference entirely below 0; 2,000 resamples, seed 20261010) | PX-1 | Baseline | PX-1 − baseline (95% CI) | Result |
|---|---|---|---|---|
| vs M6/M7 (`win_prob_xgb_calibrated` `d18`, same selection-moment inputs) | 0.6419 | 0.5599 | +0.0820 [+0.0234, +0.1481] | **FAIL**: significantly worse |
| vs seed-only logistic (same 2024–2025 rows) | 0.6419 | 0.5185 | +0.1234 [+0.0634, +0.1891] | **FAIL**: significantly worse |
| **Gate** | | | | **FAILED** |

**Consequences (D9, P6-Q3: "If either fails: D9, stop and escalate"):**
- PX-1 stays `not_validated`.
- The dependent chain does **not** run: **PX-2 (P6-M3), PX-4 (P6-M5) and P6-M8 / P6-DM1 are blocked by this failure.** `phase6_playoff_track` refuses each prerequisite (`passed` false).
- P6-M6 (b) depends only on P6-M1 and still runs.

**Not changed:** the model, its features, the regularization (C = 1.0), the round-interaction design, the populations, the gate or any threshold. Any redesign needs Kanav's dated decision and a new pre-registered specification evaluated on a population not yet seen. 2026 has now been observed for PX-1, so it cannot validate a redesign.

**Observed facts, no diagnosis performed:**
- PX-1 is also worse than the seed-only model fit on the same rows, which uses only the seed difference.
- The PX-1 design has 66 columns. The frozen spec scales without centering and fits with no intercept.
