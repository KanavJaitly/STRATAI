# StratAI Phase 5 — Pre-Season & In-Season Intelligence

The reference for what Phase 5 built, what each output means, and how far each one can be trusted.

- **Specification (frozen at P5-M0):** `docs/P5Milestones.md`.
- **Decisions:** `.agent/phase5/P5_M0_DECISIONS.md`.
- **Evaluation records (write-once, with commit provenance):** `.agent/phase5/results/`.

Phase 5 builds on the Phase 4 contracts in `docs/ml_models.md`:
- **Models:** the frozen D18 models are consumed, never retrained.
- **Probabilities:** qualification probabilities are validated only on EPA-complete matches.
- **Playoffs:** probabilities are never validated (the playoff track is a Phase 6 prerequisite).

## P5-M1 — Alliance and seed data

- **Source:** `data/alliances.py` lands TBA `/event/{key}/alliances` raw-first.
- **Readers:** `read_event_alliances` (seed, position, name, captain, picks, backup, declines) and `read_event_alliance_outcomes` (playoff results). They are kept apart, because outcomes are **labels only, never features**.
- **When usable:** seeds and picks are known only after alliance selection.
- **Unseeded events:** division-champion events (Einstein and the multi-division DCMP finals) have `seed = null`.
- **Quality checks:** `data/alliance_checks.py`; the recorded result is `.agent/phase5/results/p5_m1_alliance_acceptance.json`.

| Check | Result |
|---|---|
| Coverage | 100% of playoff events, all three seasons |
| Playoff participants on no alliance | 5, in 4 events (backups are unknown: TBA records none) |
| Seed–rank violations | 9, in 6 of 591 seeded events. 8 are TBA placeholder teams (`999x`); 1 is a real anomaly (2026milac) |
| Seed-order rejections | 0 |

## P5-M3 — Team and robot strength views

- **Endpoint:** `GET /teams/{team_number}/events/{event_key}/strength?as_of=<ISO-8601 with offset>` (default: now). Errors: `event_not_found`, `team_not_found`, `epa_source_not_loaded`, `epa_source_incomplete`, `invalid_as_of` (422; a timestamp without an offset is refused).
- **Built from:** `ml/views/strength.py`, composing the assembler's `build_team_features` and Phase 3's `classify_match_days`. No new statistic. `team_metrics` is not read, because it is a current snapshot and would leak past `as_of`.
- **Every numeric field** is a `Measure`: value, n, and an uncertainty (an SD, or `none` with a reason). An absent value is null with a reason.
- **EPA:** carries `epa_value_source`, `epa_source_state` (P5-D2: `current`, `stale`, `fallback_stratai`, or `withheld_no_prior_event` when absent) and its source event.
- **Auto points:** the current event, plus the season's earlier events listed one by one (never pooled).
- **Defense:** `definition_pending` (the Phase 3 M14 product decision is open). **Feeding:** `not_validated` (no feeding field is collected at scout time).

| Check (1,000 sampled 2026 appearances, D18 source) | Result |
|---|---|
| Exact equality with the assembler's `TeamFeatures` | 0 mismatches |
| n, uncertainty, absent reasons, EPA provenance | 0 failures |
| Equality with the D18 frame's own features | 0 mismatches |
| EPA source states seen | current 963, withheld 33, fallback_stratai 4 |
