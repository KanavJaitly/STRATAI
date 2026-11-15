# P11-FB1 vs P11-FB2 on replayed real selections (2026-11-15)

**What this is:** the descriptive comparison that the P11-FB2 record (§10) prescribes, run after FB2 was frozen
(`6450d8a`) and built (`57fc462`, test fix `fddc989`).

**What it is not:**
- **Not a validation.** Real teams pick for reasons no rule sees: their scouting, strategy and relationships. How
  often a rule lists the team that was actually picked describes agreement with human picks; it does not measure
  pick quality.
- **Not independent of the design.** Kanav's replay of 2024njfla informed FB2.
- **Not followed by tuning.** FB2 was not changed after these numbers; any change would be P11-FB2.1.

## How it was run

- **Script:** `scripts/phase11_replay.py`.
  - It replays each event's actual selection through the live draft record, action by action.
  - For every real pick, it notes where the picked team stood in the list advising the picking alliance just before
    the pick: `primary`, `backup_<k>` or `unlisted`. At that moment it is that alliance's turn, so each list holds 4
    teams (1 + max(3, 0)).
  - **FB2** is the served rule (`recommend`). **FB1** is its pure function on the same P5-M4 ordering
    (`fb1_lists_at`).
- **Database:** `stratai_test_p11fu`, read-only, with the local test pins (`scripts/local_test_env.PINS`: the d18 M5 v2
  model and the D18 Statbotics EPA source).
- **Samples:** the ones Phase 11 used, with seed 20261104.

| Run | Events | Result file |
|---|---|---|
| Prescribed (`--per-season 2`) | 6 | `p11fu_fb2_compare_prescribed_20261115.json` |
| Wide (`--per-season 10`) | 30 (29 replayed; 2026tuis4 is excluded by the approved 2026 ruleset) | `p11fu_fb2_compare_wide30_20261115.json` |
| `--events 2024njfla` | 1 | `p11fu_fb2_compare_njfla_20261115.json` |

The prescribed sample shares 2 events with the wide sample (2024lake, 2024txbel), so the two are not independent.

### The database, compared with the Phase 11 runs on `stratai_test_p11`

- `stratai_test_p11` (Sven's clone of the D18 handoff, through migration 0014) is not on this machine, so the two
  databases were not compared directly.
- `stratai_test_p11fu` is a clone of the local `stratai_test`, made on 2026-11-14.
- Compared through the results instead:
  - the seeded draw chose **the same events** as the 2026-11-09 runs, in both samples;
  - every event's outcome is **identical**: passed, number of actions, overrides, and skipped.
- The databases may differ in rows that neither run touches.

## Results

**FB2 mode:** FB2 used component mode (auto, teleop and endgame estimates) at all 31 events. It left out 1-8 DQ'd
alliance rows at 12 of them. The total-score and EPA-component modes are covered by the unit tests only.

### Where the actual pick stood

**Wide sample: 29 events, 472 picks.**

| | Primary | Backup | Unlisted | Listed |
|---|---|---|---|---|
| FB1 | 103 | 141 (63 / 33 / 45 at backup 1 / 2 / 3) | 228 | 51.7% |
| FB2 | 128 | 165 (69 / 62 / 34) | 179 | 62.1% |

| Season | FB1 primary / backup / unlisted (listed) | FB2 primary / backup / unlisted (listed) |
|---|---|---|
| 2024 (168 picks) | 33 / 60 / 75 (55.4%) | 39 / 55 / 74 (56.0%) |
| 2025 (160 picks) | 40 / 44 / 76 (52.5%) | 39 / 62 / 59 (63.1%) |
| 2026 (144 picks) | 30 / 37 / 77 (46.5%) | 50 / 48 / 46 (68.1%) |

**Prescribed sample: 6 events, 96 picks.**

| | Primary | Backup | Unlisted | Listed |
|---|---|---|---|---|
| FB1 | 23 | 34 | 39 | 59.4% |
| FB2 | 32 | 35 | 29 | 69.8% |

| Season | FB1 (listed) | FB2 (listed) |
|---|---|---|
| 2024 (32 picks) | 8 / 13 / 11 (65.6%) | 12 / 9 / 11 (65.6%) |
| 2025 (32 picks) | 9 / 8 / 15 (53.1%) | 9 / 11 / 12 (62.5%) |
| 2026 (32 picks) | 6 / 13 / 13 (59.4%) | 11 / 15 / 6 (81.3%) |

**What these numbers show:**
- On these samples, FB2's list contains the team actually picked more often than FB1's, overall and in 2025 and 2026.
- In 2024 the two are about level.
- The samples are small and seeded, and they are not a holdout.

### 2024njfla (the event that informed FB2)

Team 11 (MORT) was alliance 2's captain. TBA's reconstruction gives the same picks as Kanav's record: 1218, then 2577.

| Pick | Actually picked | FB1 list (position) | FB2 list (position) |
|---|---|---|---|
| MORT's 1st (seq 5) | 1218 | 1811, 223, 3142, 4361 (**unlisted**) | 8513, 223, 219, 1218 (**backup 3**) |
| MORT's 2nd (seq 24) | 2577 | 5624, 752, 8704, 2577 (**backup 3**) | 2577, 5624, 752, 8704 (**primary**) |

**Where 2577 stood:**
- At alliance 4's second pick (seq 22) and alliance 3's (seq 23), FB2 listed 2577 as backup 2 and backup 1; FB1 did
  not list it.
- At MORT's second pick, FB2 put it first and FB1 put it fourth.

**Why FB2 put 2577 first:** with 11 and 1218 on the alliance there was no component gap, so the order is the
reliability- and consistency-adjusted estimated contribution. 2577's was 7.3 points (5624: 7.0; 752: 7.3; 8704: 7.2),
so this is a near-tie. 2577's card explains its qualification rank of 34 of 34 with the fixed lower-half line.

**Across the event's 16 picks:**
- FB1: 3 primary, 8 backup, 5 unlisted;
- FB2: 7 primary, 8 backup, 1 unlisted.

### P11-DM1 under FB2

**P11-DM1 still holds:**
- prescribed: 6 of 6 events pass;
- wide: 29 of 29 (2026tuis4 skipped by the ruleset);
- 2024njfla passes.

**Across all three runs:**
- 0 problems, 0 overrides;
- no unavailable team was recommended;
- every recorded alliance matches TBA;
- every primary that was recommended could be recorded at that turn.

### Speed (P11-Q3, ≤ 2 s at p95)

| Run | Cold, first call per event (max) | Warm p95 (max over events) |
|---|---|---|
| Wide | 1.545 s (the same events under FB1 on 2026-11-09: 1.047 s) | 0.0118 s |
| Prescribed | 0.808 s | 0.0063 s |
| 2024njfla | 0.599 s | 0.0074 s |

The first call at an event computes the P5-M4 analysis and FB2's three REML fits once. Both are cached after that.
