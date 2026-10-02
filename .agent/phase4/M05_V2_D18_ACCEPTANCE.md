# Phase 4 — Milestone 5 (v2, D18): ACCEPTED

**Accepted by Kanav, 2026-10-02.** This new record supersedes nothing and edits no file. `M05_ACCEPTANCE.md` (the D15 v2 run, "pending review") and `D18_RESULTS.md` stay as written.

**Phase 4 is NOT complete:**
- M07 remains FAILED under its frozen D16 criterion;
- `python -m scripts.phase4_done_means` remains NOT MET.

## Basis of acceptance

| Item | Evidence |
|---|---|
| **Gate** (D16 §1.5 under D18 §4): midpoint Spearman beats the same-protocol raw-EPA baseline and the D18 M4 baseline | **0.6112440558451762** > 0.5955 (`results/d18/m05v2_result.json`) |
| **Paired strength** over 208 events | +0.0157 (95% CI 0.004–0.027); better in 122 events; Wilcoxon p = 0.004 |
| **Reproducibility** | Twin fit identical. The production rebuild reproduces the D18 midpoint Spearman and top-8 recall bit for bit (`.agent/production/d18_model_registration.json`) |
| **Artifact integrity** | Reload through the sha256 pin: 0 differences across 108,024 ratings. Artifact sha256 `1f0fe5aa…6312` |
| **Production alignment** | The API serves only `ranking_xgb_v2` and refuses M5 v1. Served features equal the D18 frame (360 matches, 0 mismatches; `.agent/production/d18_integration_check.json`) |
| **Leakage** | D18 S1–S5 pass. Label shuffle at chance on real data (8 seeds, mean 0.070) and on the M8 fixture (0.010) |

## Scope of what is accepted — the documented boundary

**Validated:**
- M5 v2 orderings at and after each team's mid-qualification point (evaluated at the midpoint: 0.6112; at the last qualification snapshot: 0.6314).

**Not validated:**
- **Pre-event M5 v2 orderings.** They are below raw EPA (0.5565 vs 0.5955), so raw EPA is the pre-event ordering.
- **Precision of the score.** Performance is moderate and not guaranteed. `predicted_rating` is a relative score, so only the ordering is meaningful.

**Provenance note.** The registered artifact's manifest provenance says "acceptance pending review", as written at registration (2026-10-02, before this acceptance). Manifests are write-once; this record is the acceptance.
