# P6-M13 audit plan (dated pre-run record, P6-Q13 protocol)

**2026-10-05, written before the audit run.** The commit introducing this file fixes the plan, and the run happens after it.

- **Engine:** the real `ml.strategy.engine.StrategyEngine` on the registered P6-M10 artifact `strategy_outcome_component` / `p6m10-v1`. The sha256 is pinned from `p6_m10_fit.json`, and the artifact carries its recorded status (`not_validated`, `p6_m10_gate_failed`).
- **Contexts:** real held-out 2026 data, from the D18 frame `frame_ab1adbf38b43c2f3`.
  - **Ordinary:** 10 EPA-complete qualification matches with every model input present, drawn with `random.Random(20261007).sample` from those rows sorted by `match_key`.
  - **Full-search (M2):** the first 2 ordinary contexts.
  - **Missing input (M6):** the first, by `match_key`, of the 2026 EPA-complete qualification matches lacking a causal scale. The P6-M10 evaluation counted 30 such matches.
  - **Low odds (M7):** the first, by `match_key`, of the 2026 EPA-complete qualification matches whose baseline P(red) or P(blue) is below 0.05, with that side.
- **Checks:** S1–S3 and M1–M7, as `ml/strategy/parity_audit.py` defines them. The audit passes only if all 10 pass on the real engine.
- **Planted defects:** all 7 in `PLANTED_DEFECTS`, each run on the first 3 ordinary contexts plus the same missing-input and low-odds contexts. Each must fail at least its targeted check.
- **Runtime:** projected about 20 minutes. The hard budget is 45 minutes; on overrun the harness stops and records partial results as not passed.
- **Record:** `.agent/phase6/results/p6_m13_parity_audit.json`, write-once.
