# P11A E2 research benchmark (research tooling, not production)

This directory holds the evidence for `docs/P11-E2-Benchmark-Report.md`. It is isolated research tooling:
- nothing in `api/`, `data/`, `ml/` or `workspaces/` imports it;
- it reads no database and never contacts the serving `stratai`;
- `PROTOCOL.json` was fixed before any execution.

The specification `docs/P11-RecommendationIntelligence.md` stays PROPOSED / NOT APPROVED. Nothing here approves a
threshold or passes a gate.

## Environment

- Python 3.14, using the project `.venv`.
- `requirements.txt`, with numpy, scipy and httpx.
- On this macOS build, XGBoost needs `DYLD_LIBRARY_PATH`, but these scripts do not import it.

## Reproduce

Every step is a separate command with its own budget (`--budget-minutes`, at most 45). Each writes its own outputs.

```bash
# 1. Raw-first download (Statbotics public API; about 1-2 minutes per season)
for y in 2024 2025 2026; do
  .venv/bin/python -I research/p11_e2/fetch_statbotics.py --season $y --out research/p11_e2/cache/raw --budget-minutes 15
done

# 2. Evaluation populations and exclusion logs
for y in 2024 2025 2026; do
  .venv/bin/python -I research/p11_e2/build_population.py --season $y --raw research/p11_e2/cache/raw \
      --out research/p11_e2/cache/population
done

# 3. E2 predictions at each event's selection moment (a few minutes per season)
for y in 2024 2025 2026; do
  .venv/bin/python -I research/p11_e2/run_e2.py --season $y --population research/p11_e2/cache/population \
      --out research/p11_e2/results --budget-minutes 30
done

# 4. Metrics, bootstrap CIs, the delta/pi grid, G2 residuals, independence on real data
.venv/bin/python -I research/p11_e2/analyze.py --results research/p11_e2/results --budget-minutes 40

# 5. Simulations: separate fixed-scope tasks, as actually run for the report (each under its 40-minute budget).
#    The original single task per sigma/tau exceeded its budget for 1.0 and 3.0 under CPU contention, so those were
#    split by matches-per-team cap (--caps low = caps 3,6; high = 9,none; cap9; nocap). Each split has its own stream.
P=research/p11_e2/cache/population; O=research/p11_e2/results; S=".venv/bin/python -I research/p11_e2/simulate.py"
$S --sigma-over-tau 0.5 --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 2.0 --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 1.0 --caps low --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 1.0 --caps high --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 3.0 --caps low --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 3.0 --caps cap9 --population $P --out $O --budget-minutes 40
$S --sigma-over-tau 3.0 --caps nocap --population $P --out $O --budget-minutes 40

# 6. Per-robot field audit (TBA public schema)
.venv/bin/python -I research/p11_e2/audit_fields.py --cache research/p11_e2/cache --out research/p11_e2/results

# 7. Report figures (tables) from the results
.venv/bin/python -I research/p11_e2/summarize_sims.py --results research/p11_e2/results
```

## Reproducibility notes

- **Seeds:** 20261105 for the bootstrap and the simulations. Simulation tasks derive their stream from (seed,
  10 × sigma/tau).
- **Data version.**
  - `cache/raw/<season>/manifest.json` records each page's URL, fetch time and sha256.
  - Statbotics may correct historical results later, so a re-download can differ. Compare the sha256s, or keep the
    cache.
- **Excluded from git:** `cache/` (raw data and populations, about 315 MB), per `.gitignore`. `results/` holds the
  outputs the report cites (about 71 MB, mostly `e2_records_*.json`), including the `*partial_run*` files from runs
  that stopped at their budget; they are kept for the record and not used.
- **REML form.** The E2 2026 run and the later simulation tasks use `model.reml` (exact n x n Woodbury). E2
  2024/2025 and the earlier simulation tasks used the direct form, preserved as `model.reml_direct`. They agree to
  <= 2.1e-6 relative.
