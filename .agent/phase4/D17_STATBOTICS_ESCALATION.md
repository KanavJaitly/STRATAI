# Phase 4 — D17 (Statbotics as the EPA source): snapshot built, D8 gate INVALID, stopped

2026-10-01. **No M4–M7 run has been made on Statbotics EPA.** Existing evidence (D15, STRATAI EPA) is untouched.

## Statbotics recovery — verified independently

- **Monitor state:** `RECOVERY_PENDING`, not confirmed. One successful check at 2026-10-01T20:27Z (1678/2024casj, EPA 49.22, 17 matches); it needs a second consecutive day.
- **Endpoints checked** (raw `httpx` calls, independent of the codebase client):
  - `GET /v3/team_event/1678/2024casj` → 200. The schema is identical to the response captured from the live API on 2026-08-01 (zero field differences). EPA fields: `epa.total_points`, `epa.breakdown.{auto,teleop,endgame}_points`, `unitless`, `norm`, `stats`.
  - `GET /v3/team_events?event=<key>&limit=1000` → 200. Each record is identical to the single-team endpoint's body, so it is used for the snapshot: 608 requests instead of about 24,000.
- **Coverage:** `GET /v3/events?year=2026` lists 215 events, exactly ours. Sampled events from all three seasons return records.

## Snapshot (provenance)

`C:\Dev\StratAI-artifacts\statbotics\statbotics_snapshot_20261001T220423Z` (`manifest.json` is copied to `results/`):
- **Fetch:** 608/608 events, 24,022 records; 0 failures, 0 skipped, 0 fatal quality issues.
- **Window:** retrieved 2026-10-01T22:04:23Z → 22:19:51Z. Producing commit `575cc4f`.
- **Raw responses:** `raw/<event>.json.gz`, with a per-event sha256, retrieval time, endpoint and parameters.
- **Landing:** each record landed to `raw_source_payloads` (source=statbotics, id `{team}_{event}`, schema `statbotics-v3`, with its fetch timestamp). It was staged and loaded by the existing Phase 2 path (`sync_event(extraction=...)`). TBA was never contacted, so the TBA raw snapshot behind every earlier artifact is unchanged.
- **`team_event_stats`:** 24,022 rows, sha256 `c73775c6…`, exported as `team_event_stats.json.gz`. `build-frame --statbotics-snapshot` refuses to build if the table no longer matches this fingerprint.

## D8 readiness gate: INVALID — the blocker

`automation/data_readiness.assess_readiness` (unchanged), saved in `results/d8_readiness_statbotics.json`:

| Category | Appearances |
|---|---|
| ok | 264,405 |
| no prior event (legitimate) | 54,446 |
| **invalid expected row** | **438** |
| **missing expected row** | **12** |

Breakdowns and final rankings: all OK.

**All 450 failing appearances are exactly the whole of 2026iscmp** (the Israel DCMP, 36 teams, held July 2026). Their D13 source events are 2026isde1 (205 appearances, 16 teams) and 2026isde2 (245, 19).

**Cause: Statbotics never processed the 2026 Israeli district events.** They ran in June–July, after the Championship. Statbotics lists all five (isde1–4, iscmp) as `"status": "Upcoming"`, week 1, `matches_played = 0`, with EPA equal to the pre-event start value (`stats.mean = max = 0`). It has no rows at all for 2026iscmp (canonical data: 75 matches). Team 4744 has no 2026isde2 row, so its lookup would silently fall back to 2025 EPA.

D8 forbids treating this as legitimate absence, or imputing or substituting EPA. **Stopped.**

## Further facts relevant to the decision

1. **The frozen numbers are STRATAI-EPA numbers.** M4 (0.7622 / 0.6734 / 0.1785 / 0.8421 / 0.1194; Spearman 0.5951, top-8 0.6472), M5 v2 (0.6128) and M6/M7 were all computed with EPA from STRATAI (D15). Switching the source changes every EPA feature value, so every one of them would be a **new controlled run**, not a confirmation.
2. **The two sources agree closely but not exactly** (`results/epa_source_comparison.json`, 23,931 shared team-events):

   | Season | Pearson | Mean abs. difference | Exact to 0.01 |
   |---|---|---|---|
   | 2024 | 0.9966 | 0.59 pts | 0.7% |
   | 2025 | 0.9996 | 0.37 | 1.4% |
   | 2026 | 0.9983 | 0.30 | 7.4% |

   There is no bias (mean differences +0.01 to +0.07). This is not a parity claim.
3. **Season-end values on the Statbotics source.** Statbotics publishes no availability metadata. A team-event with no qualification matches carries Statbotics' season-end EPA: 188 such played team-events in this snapshot (e.g. Einstein). STRATAI's provider withheld these in-season (1,053 appearances); the Statbotics D13 SQL cannot. The raw record's `record.qual.count = 0` identifies them objectively, but no frozen rule uses it.
4. **M5 v2 is single-run under D16** (passed on STRATAI EPA). A Statbotics run would be a second run of that methodology with a different EPA input.
5. **M11:** a real consumer exists (D4/D12 `average_auto_points`, which feeds M5 v1 and M6), so it is not deferred. Its frozen generalization script's ranking check is hard-wired to M5 **v1** (`RankingXGBModel`), the failed model.

## Decisions needed

- **A. 2026iscmp:**
  - exclude it from the Statbotics-based held-out evaluation as a counted source-data exclusion (450 of about 108k held-out appearances; about 75 of 17,960 test matches) — an amendment to D7/D8's population;
  - or wait for Statbotics to process the June–July Israeli events (no known timeline);
  - or keep STRATAI as the source of record (D15) and use Statbotics for validation.
- **B.** If Statbotics is the source of record: confirm M4 is re-frozen on Statbotics (with new numbers, keeping the STRATAI-based numbers as the D15 record), and that M5 v2, M6 and M7 are new controlled runs.
- **C.** Season-end values: accept the known look-ahead, or adopt the objective `record.qual.count = 0` rule (unavailable until season end) before any run.
- **D. M11:** which M5 model its generalization check uses (v1 as frozen, or the model of record).
