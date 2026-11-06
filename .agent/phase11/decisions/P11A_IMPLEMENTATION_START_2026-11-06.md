# P11A implementation start (2026-11-06)

**Authorization.**
- The project owner's instruction of 2026-11-06 ("I am authorizing implementation"), in the Claude Code session that
  produced `docs/P11-RecommendationIntelligence.md` and `docs/P11-E2-Benchmark-Report.md`.
- The specification itself stays **PROPOSED / NOT APPROVED** and is not edited.
- The P11A-Q1 … Q10 *proposed defaults* (spec §21.3) are used as working assumptions. They are not treated as
  approved decisions.

**What is built now** (each part pure and tested; database-backed parts written but unverified on this machine,
which has no PostgreSQL):
1. **A season scoring configuration** (`ml/alliance/scoring_config.py`).
   - A separate, reviewed artifact that references the approved P5-M8 GameSpec by sha256 and takes every point
     value from it. This is the spec B4 / P11A-Q4 fallback; extending the frozen P5 GameSpec schema would change frozen
     P5 catalog hashes.
   - Unapproved configurations are refused for scoring.
2. **The A3 estimator** (`ml/alliance/estimator.py`): the hierarchical Gaussian model, REML, joint posterior
   covariance, independent individual priors, identifiability and collapse diagnostics, and A3.2 labels.
3. **The B5 alliance value** with caps and threshold bonuses, and the C/D/E planner (`ml/alliance/planner.py`).
4. **An event snapshot** for offline use (`ml/alliance/snapshot.py`).
5. **The team profile** (`ml/alliance/profile.py`).
6. **Additive, workspace-scoped API operations.** The locked `…/recommendations` operation and the P11-Q1
   precedence are unchanged (P11A-Q2 default).

**Candidate thresholds (not approved).**
- The values: n_min = 4, w_min = 0.4, max |corr| = 0.5, min partners = 12, collapse ratio σ̂²/var(y) < 0.05. They are
  taken from the E2 report §17/§21 candidate ranges.
- Every output carries `thresholds_status: candidate_unapproved`.

**Gated (code paths exist only where noted; nothing is served as validated):**
- win probability (not built);
- synergy bonuses (none);
- individual validated contributions (estimates are `not_validated`);
- playoff-bias correction (none);
- probabilistic availability (none; `availability_not_modelled`);
- scoring with an unapproved configuration (refused);
- calibrated intervals (labelled `not_calibrated`, citing E2: 80% nominal covered 68%);
- δ/π comparisons (every comparison `unresolved`, `comparison_threshold_not_approved`).

## Observation during implementation (recorded, threshold NOT changed)

The candidate collapse rule (σ̂²/var(y) < 0.05) refused a synthetic event whose fit was correct: σ̂² = 17.8 against a
true 16, with var(y) ≈ 398 because the synthetic teams' teleop contributions were very spread out. The ratio rule
therefore also fires on high-signal, low-noise events, not only on collapsed fits. The threshold was left as it is;
the affected tests use a realistic alliance noise (SD 6). Whoever ratifies the candidate thresholds should consider
an absolute floor on σ̂² (or σ̂² against the E2 per-season residual variance) instead of, or beside, the ratio.
