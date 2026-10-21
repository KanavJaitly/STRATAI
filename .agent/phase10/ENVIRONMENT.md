# Phase 10 — environment and test data (2026-10-20)

- **Branch:** `phase8/build` at `45859dc`, uncommitted (the Phase 8 closeout plus the Phase 9 work).
- **Runtime:** Python 3.11.2, Node 24.17.0, PostgreSQL 18.4. 8 CPUs, 6 GB RAM, about 6 GB free disk.
- **Installed (venv):** xgboost, scikit-learn, scipy, pyarrow, httpx, anthropic.
- **Absent:** pandas, OR-Tools, `psycopg_pool`, redis.

## Settings

`.env` holds only `DATABASE_URL`, `ENV` and `TBA_API_KEY`. None of these is set:
- a Statbotics key;
- a snapshot directory;
- a model registry;
- model pins.

So every model-backed route answers `model_not_loaded`.

## `stratai_test` contents (read-only survey, 2026-10-20)

| Season | Events | Matches (qual / semifinal / final) | Scouting | team_event_stats | team_metrics |
|---|---|---|---|---|---|
| 2022 | 0 | 0 | 0 | 0 | 0 |
| 2023 | 0 | 0 | 0 | 0 | 0 |
| 2024 | 190 | 14,129 / 2,423 / 429 | 0 | 75 (2024new only) | 42 (2024casj only) |
| 2025 | 0 | 0 | 0 | 0 | 0 |
| 2026 | 1 (2026mrcmp) | 132 / 13 / 2 | 331 (defense 331, feeding 0) | 66 | 66 |

**Raw payloads:**
- TBA: 17,221 match, 192 event and 3,530 team payloads.
- Statbotics: 141.
- Scoutradioz: 346.
- **No `event_ranking` and no `event_alliances` payloads**, so there are no final ranks and no alliance outcomes.

**2022 and 2023 exist nowhere.** The code supports only the 2024–2026 seasons:
- EPA constants;
- score-breakdown adapters;
- the snapshot manifest;
- the P6 rulesets.

## Artifacts

- **Models:** none on this machine. The D18 artifacts are on the Windows environment of record
  (`.agent/production/D18_PRODUCTION_ALIGNMENT.md`).
- **Phase 4 D18 results (2026-10-01):**
  - M4, M5, M6 and M11 passed;
  - **M7 calibration FAILED.** G2 failed 2 of 9 bins, and playoff ECE was 0.119.
