# P6-M10c DEV-c: predeclared rule NOT met (2026-10-11)

**Record:** `results/p6_m10c_dev.json`, write-once, sha256 `c26362e97a10c24271d5474af3697da0538d7b1a88b1d4eae8d8597c3db4cf40`.
- Run once at `c55ebed`, under spec `P6_M10C_SPEC.md` (blob `f24a8d1c`) and Kanav's DEV-c authorization.
- 20 seconds, on `stratai_test`.

**Decision: `rule_not_met`.** M10c stops, and M10b stands as frozen.
- Nothing is registered, pinned or served, and no methodology is changed.
- P6-M10 stays `not_validated`, and `p6m10-v1` stays served.

**Diagnostic evidence only.** DEV-c is never acceptance evidence, and neither its pass nor its failure says anything about 2027.

## Population and checks

| Item | Value |
|---|---|
| Base | v1 procedure on 2024: 4,797 rows; reproduces DEV-M10b's β and Σ exactly (0.0); sha `737b7884…`; not registered |
| C (calibration) | 2025 types 0/1/2/5, weeks 0–3: **6,086 rows**, to 2025-03-23. Groups: same 1,039 / mixed 2,931 / prior 2,116. Excluded: 56 ties, 67 input-absent. Fingerprint `02eef8f0…` |
| E (evaluation) | 2025 weeks ≥ 4 plus the Championship: **4,985 rows, 65 events**, from 2025-03-26. Groups: same 4,010 / mixed 971 / prior 4. Excluded: 32 ties. Fingerprint `bbf2fcc2…` |
| Temporal and leakage | events disjoint; matches disjoint; C before E; the base before C: **all pass** (fit isolation true) |
| Identical E rows | both models scored the same 4,985 rows |

## Diagnostics (predeclared, spec §4.6)

| Id | Status | Detail |
|---|---|---|
| D1 M10c fit | pass | ε = 0.0372; slopes same 1.433, mixed 1.082, prior 0.886; gradient 2.4e-17; Hessian eigenvalues 0.0085–1.11 |
| D2 M10b-form fit | pass | factors same 1.318, mixed 0.996, prior 0.813 |
| **D3 G2 rejections** | **fail** | M10c rejects **1** bin; the M10b form rejects **0** (and passes G2) |
| D4 ECE | pass | M10c 0.0149 ≤ M10b form 0.0166 |

**Reported, not gating.** M10c log-loss 0.4572 vs M10b form 0.4564; Brier 0.1501 vs 0.1502. The raw base's ECE is 0.0419.

## What happened

M10c's rejected bin is **0.0–0.1**: predicted 0.052, observed 0.028 (n = 654, p = 0.0032). The upset floor raised the low tail above what 2025's later weeks showed. In this population, underdogs won *less* often than the floor implies.

That is the opposite of 2026's DEV pattern, where the calibrated tails were over-confident and motivated the floor. **The tail behaviour was not stable across these two development populations.** The confounds the spec named apply: E is 80% same-group, and the transfer here is within one season.

**No change follows from this result.** The rule was predeclared, and the result is recorded as it is. Any further version would be a new, separately approved specification.
