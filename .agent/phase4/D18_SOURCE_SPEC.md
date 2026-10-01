# Phase 4 — D18: Statbotics-primary EPA source version (SP1) — specification

Status: **FROZEN — decision D18 (Kanav, 2026-10-01).** The commit introducing this file is the freeze point, made before any D18 dataset or metric exists. Nothing below may change after a D18 metric is seen.

D15 (STRATAI EPA) results remain the historical record and are never overwritten. D18 results are new, separately labelled artifacts. Model methodology (D7 split, M4/M5 v2/M6 definitions, D16 M7 gate) is unchanged. Only the EPA source, its temporal availability rules, the baseline references (§4), and M11's model of record (§5) are defined here.

## 1. Sources

**Primary: Statbotics.**
- **Snapshot:** `statbotics_snapshot_20261001T220423Z` (manifest in `results/`).
  - Endpoint: `GET https://api.statbotics.io/v3/team_events?event=<key>&limit=1000`, schema `statbotics-v3`, 608 events, retrieved 2026-10-01 22:04–22:19 UTC by commit 575cc4f.
  - Values come from canonical `team_event_stats` (epa_total, epa_auto, epa_teleop, epa_endgame ← `epa.total_points`, `epa.breakdown.{auto,teleop,endgame}_points`).
  - The table must match the snapshot fingerprint `c73775c66063a36a…`, and every row's epa_total must equal its raw record's; otherwise nothing is built.
- **Metadata from the raw snapshot records:** `record.qual.count`, `record.total.count`, `status`, `week`.

**Fallback: STRATAI**, for one event only.
- **Scope:** every team appearance whose **target event is `2026iscmp`**, and no other. Statbotics never processed the June–July 2026 Israeli events (`status: "Upcoming"`, `matches_played = 0`; no 2026iscmp rows). Expected: exactly 450 appearances.
- **Values:** STRATAI chain `chain_e77d9444c57a7b50` (the D15 artifacts), through `StrataiPointInTimeEpa`, unchanged: D13 plus STRATAI availability.

## 2. Selection (D13, unchanged)

- **Candidates:** for appearance (team i, target e, time t), the team's other events whose `end_date::timestamptz` and whose latest completed match for i are both before t (canonical facts).
- **Order:** latest end date, then latest completed match, then event_key ascending. The first candidate that is valid and available (§3) is served.

**Validity (D8's rule):**
- a Statbotics row is valid iff `epa_total` is not null and `matches_played > 0`;
- outside the fallback scope, a candidate that has no Statbotics row or an invalid one is a **hard error**. The build stops: there is no silent fallback to an older event.

## 3. Temporal availability (Statbotics values)

A candidate value is servable only if `available_at < t`. Otherwise it is skipped and counted, and the next D13 candidate is considered. This is the same treatment D15 gave STRATAI values, built from Statbotics' own metadata.

Let Y be the source event's season.

**A1 — season-end values.** If the raw record has `record.qual.count = 0` (or no qualification count), the published value is Statbotics' season-end rating for that team.
- `available_at` = T_end(Y): the latest scheduled time of a completed match in season Y (canonical).

**A2 — all other values:** `available_at` = max(the team's latest completed match at the source event, T_w1(Y)).
- T_w1(Y) = the latest scheduled time of a completed match at events whose Statbotics records are `status = "Completed"` with `week = 1`.
- Those are the matches Statbotics' season statistics are computed from. Unprocessed events (`Upcoming`) are not among them.

## 4. Gates under D18 (methodology unchanged; baselines re-referenced to the same source)

| Milestone | Run | Gate |
|---|---|---|
| **M4** | twice, on the D18 frame | its criteria unchanged; the numbers become the **D18 frozen baseline** |
| **M5 v2** | once, D16 §1 unchanged | Spearman (midpoint) > the same-protocol D18 raw-EPA baseline **and** > the D18 M4 ranking Spearman |
| **M6** | once, unchanged | held-out log-loss ≤ D18 M4 win-prob log-loss **and** Brier ≤ D18 M4 Brier, on the D18 EPA-complete rows; exact symmetry |
| **M7** | once | the D16 §2 gate G1–G4 unchanged (ECE < 0.05; exact Poisson-binomial per-bin test with Holm, α = 0.05; symmetry; isolation) |

The D15 numbers (M4 0.5951 etc.) are reported alongside for comparison and are not used as D18 gates: they measure a different EPA source.

## 5. M11 under D18

- **Model of record.** M5 v1 is FAILED and superseded (D16). So M11's ranking check evaluates the **M5 model of record, v2**, with v2's own protocol (midpoint snapshot, same-protocol raw-EPA baseline).
- **Unchanged parts.** `generalization_checks` (strict "above baseline and above chance" for win-prob log-loss and Brier, ranking Spearman, and `average_auto_points` resolving in the held-out season), the M6-vs-M4 win-prob comparison on EPA-complete held-out rows, and the D7 split.
- **Readiness.** D8's breakdown and ranking requirements apply. EPA readiness is §6's check.

## 6. Verification before any D18 metric (each must pass; the frame is built only for these)

- **S1 — snapshot integrity:** table fingerprint = manifest, and raw epa_total = table epa_total for every row.
- **S2 — fallback scope:** STRATAI fallback serves exactly the 2026iscmp appearances (reported count), and no other appearance carries `stratai_fallback`.
- **S3 — no silent fallback:** zero hard errors (§2) across all 2024–2026 appearances.
- **S4 — selection parity:** on ≥ 5,000 random non-fallback appearances where §3 skipped nothing, the served source event equals D13's `EPA_SOURCE_SQL` over `team_event_stats`.
- **S5 — leakage:**
  - no served value has `available_at ≥ t`;
  - no A1 (season-end) value is served before T_end;
  - counts are reported per rule.
- **S6 — cross-check (reported, not gating):** T_w1(Y) compared with STRATAI's `week_one_complete_time`.

**Provenance.** Each team appearance records `epa_value_source ∈ {statbotics, stratai_fallback}` (none when EPA is withheld). The dataset manifest records the source version, the snapshot, the chain and all counts.
