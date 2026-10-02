# P5-M0 audit — curated robot-design / archetype dataset

2026-10-02. **Analysis only:** no archetype engine, similarity code, model or API was built.

- **Source of truth:** `data/reference/frc_robot_design_curated.csv` (sha256 `40aef139…139e1`).
- **Database:** canonical STRATAI, read-only.
- **Reproduce:** `python .agent/phase5/robot_design_audit/audit.py <statbotics_snapshot> audit_result.json`.
- **Full per-row output:** `audit_result.json`.

## 1. Structure

| Item | Finding |
|---|---|
| Rows / columns | **77** rows / 6 columns. The request stated 78. **Kanav (2026-10-02): the attached 77-row CSV is authoritative; no row is reconstructed.** The discrepancy stays documented |
| Columns | `Year`, `Team`, `Game Name`, `Robot Micro-Archetype`, `Technical Specifications`, `Key Characteristic & Competitive Advantage` |
| Completeness | every field populated; 0 exact duplicates; no repeated (year, team) |
| Seasons | 18 games, 1996–2026. Years and game names all agree. 2026–2022: 10 rows each; 2019: 5; 2018 and 2017: 4 each; then 2, 2, 2, 1, 1, 1, 1, 2, 1, 1. Absent: 1992–95, 1997–2001, 2003–07, 2009, 2020–21 |
| Teams | 25 distinct. Repeats: 254 ×12, 1323 ×7, 1678 ×6, 118 ×6, then 4414, 2910, 2056, 1114 and 148 ×4 each, then 1690, 971 and 6045 ×3 each. Every repeat is the same team in a *different* game (254 appears in 12 different games). The dataset is concentrated on a few teams across many games, not many teams within a game |
| Micro-archetypes | 76 distinct names for 77 rows; only "Virtual Four-Bar Parallel Linkage Arm" repeats (1690 2025, 4414 2023) |

## 2. Joinability to STRATAI data

- **Joinable: 30 of 30** rows from 2024–2026 (STRATAI's synced seasons). Every team is in `teams` and played 2–9 events, with final qualification ranks, Statbotics EPA (D18 snapshot) and alliance roles (P5-M1 data).
- **Not joinable locally: 47 rows** (1996–2023). STRATAI has no data before 2024.
  - TBA serves historical events and matches.
  - Statbotics EPA starts in 2002, so 1996 has no EPA anywhere.
  - Joining these rows would need a Phase 2 backfill of those seasons. That is not in Phase 5 scope.

## 3. Outcome data that exists, and what it shows about the sample

**For the 30 joinable rows:**
- per-event qualification rank;
- season-maximum EPA;
- captain/pick role and playoff results (labels);
- match records.

**The sample is extremely selected:**

| Measure | Value |
|---|---|
| Season-max EPA percentile within its season | median **99.7th**; minimum 79.6th; n = 30 |
| Ranked 1st at some event that season | 22 of 30 |
| Alliance captain at least once | 29 of 30 |

These are mostly the strongest teams in the world. The dataset has no ordinary or unsuccessful robots, so any mechanism–outcome association is confounded with team strength.

**No archetype performance statistic was computed.** With this sample none would be meaningful.

## 4. Archetype normalization

- **The names are not a category system.** The 76 distinct micro-archetype names are unique descriptions, not reusable categories.
- **A draft two-level taxonomy was tried with transparent keyword rules:**
  - function: scoring_launcher, scoring_placer, acquisition, indexing_storage, endgame_climb, drivetrain_defense;
  - family: 16 families, e.g. flywheel_turret, elevator_cascade, arm_four_bar, effector_suction.
- **Automatic keyword assignment is not reliable.** A row-by-row review found **19 of 77 rows (25%)** where the keyword label contradicts the row's own description. (The first, quick estimate was "about 15, ~20%"; corrected 2026-10-02 after the full review.)
  - Rows: 6, 10, 16, 28, 29, 31, 35, 38, 42, 44, 45, 51, 61, 63, 67, 69, 73, 75, 77.
  - Examples:
    - row 42, "Non-**turret**ed" shooter, tagged as a turret;
    - rows 16, 35 and 51, turreted *placing* mechanisms, tagged as launchers;
    - row 31, a telescoping boom, tagged as drivetrain because it mentions a swerve module;
    - row 69, a slingshot, tagged as an endgame climb because it mentions a winch;
    - rows 61 and 67, a gear pocket and a tape-measure hook, tagged as elastic launchers because they mention springs.
  - This is one reviewer's judgment, which is itself evidence for double coding.
- **Single labels lose information:**
  - 12 names explicitly combine functions with "/" (rows 5, 11, 21, 22, 36, 51, 57, 58, 60, 62, 72, 74);
  - more describe several functions in their text (e.g. row 10, launcher plus climb; row 6, sweeper plus launcher).
- **Even well labelled, the cells are tiny:** the largest (function × game) cell has 7 rows.

**Recommendation:**
- normalize with a **human-coded, multi-label codebook** (a set of functions, and a family per function), frozen before coding;
- double-code every row and report inter-rater agreement;
- always keep the original micro-archetype text verbatim.

## 5. Structured features

**Extractable as categorical/boolean attributes, with low coverage:**

| Attribute | Rows |
|---|---|
| Pneumatic actuation | 15 |
| Turret | 8 |
| Elastic/spring | 7 |
| Steel | 7 |
| Carbon fiber | 5 |
| Sensors | 5 |
| Passive/gravity | 4 |
| Vision/localization | 4 |
| Swerve | 3 |
| Tank/tracks | 3 |
| Polycarbonate | 2 |

**32 of 77 rows yield no attribute at all.**

**Not available:** drivetrain type for most rows, weight, dimensions, cycle times, cost, build resources, and any game-rule context.

**Not usable as features:**
- **23 rows contain unsourced numeric performance claims** (e.g. "85% volume", "100ms", "18 ft/s", "12 lbs", "10 balls/sec"). They stay text until each is verified against a source.
- **The "competitive advantage" text** is a narrative claim, not a measurement.

## 6. What the dataset can and cannot support

| Use | Supported? | Basis |
|---|---|---|
| Historical archetype **retrieval** ("which recorded designs used a turret / a cascade elevator / suction?") | **Yes, as an unverified reference.** Results are labelled `curated_reference_unverified` | text + codebook labels |
| **Game-mechanic similarity** | **No, by itself.** It holds no game rules, only game names. With a P5-M8 game-spec catalog it can attach *example* designs to similar games | needs the P5-M8 catalog |
| **Archetype comparison** | Qualitative only (described trade-offs) | design text |
| **Archetype performance analysis** | **No.** 30 joinable rows, all elite, no contrast group, confounded with team strength, cells of 7 or fewer | §3 |
| **Predictive modelling / expected success rates** | **No** | §3–§5 |
| Week 0/1 archetype meta | **No.** There are no per-week or per-event robot labels | — |

## 7. Data needed before any quantitative archetype claim

1. **A representative labelled sample:** all teams, or a random sample of teams, per season, not hand-picked elite teams. That means several hundred team-seasons per season, over at least 3 seasons STRATAI has outcome data for.
2. **Mechanism labels from verifiable sources** (robot reveals, technical binders, build threads, event scouting), coded with the frozen codebook, with inter-rater agreement reported.
3. **A join to measured outcomes:** per-event EPA, ranks and playoff results (all available for 2024–2026 now).
4. **A pre-registered comparison:**
   - a metric, e.g. event EPA or rank percentile;
   - a held-out season;
   - control for team strength (prior-season EPA, or within-team comparison across seasons);
   - a minimum cell size (e.g. ≥ 30 team-seasons per archetype-game cell);
   - a stated acceptance criterion.
5. **Causal claims** ("mechanism Z increases win probability") need much more than this: within-team or natural-experiment designs. They are out of scope.
6. **Week 0/1 archetype meta** needs per-team mechanism labels collected at events, e.g. a scouting field. That is a data-collection extension, not available now.

## 8. Effect on the Phase 5 specification (decision P5-D10)

**P5-M7 Meta Tracking — unchanged.**
- Quantitative meta tracking stays on score-breakdown components.
- The specification records the explicit gap: archetype-level meta needs at-event mechanism labels (§7.6).

**P5-M8 Game-Rule Analysis — changed (a reference layer added; no quantitative criterion weakened):**
- **New input:** the curated dataset, pinned by sha256, used only as a historical design-example reference.
- **Codebook taxonomy:**
  - a human, multi-label codebook, frozen before coding;
  - every row double-coded;
  - Cohen's κ reported on function labels;
  - labels used as categories only if κ ≥ 0.6, otherwise served as `provisional`.
- **Labelling:** every output drawn from it carries `curated_reference_unverified`. No success rate, no performance ranking.
- **DM1 dry-run leakage:** the 2026 rows (10, REBUILT) are excluded from the catalog and reference for the 2026-reveal dry run. In general, rows with year ≥ the simulated reveal year are excluded.

**P5-M9 Team Capability Intake — clarified:**
- Recommendations may cite curated examples, labelled as such.
- The capability→archetype feasibility mapping is a human-authored rubric: the dataset has no resource, cost or complexity data.
- The mentor-review acceptance is unchanged.

**Unchanged:** all quantitative acceptance criteria and both done-means. No Phase 4 criterion or record is affected.

## 9. Data gaps to keep documented

- 77 rows vs the stated 78.
- 47 rows are outside STRATAI's data.
- No 2020–21 rows, and only 1–2 per season before 2014.
- Elite-only selection.
- Unverified provenance and numeric claims.
- No game rules.
- No at-event mechanism labels.
- Backups unknown in alliance data (P5-M1).

## Appendix A — the 30 joined rows and their outcome data (descriptive, labels only)

"Captain at" and "Picked at" count events, including division-champion playoffs. No archetype statistic is derived from this table.

| Row | Year | Team | Events | Best qual rank | Captain at | Picked at | Season-max EPA percentile |
|---|---|---|---|---|---|---|---|
| 1 | 2026 | 4414 | 5 | 1 | 5 | 0 | 100.0 |
| 2 | 2026 | 1323 | 5 | 1 | 2 | 3 | 99.8 |
| 3 | 2026 | 254 | 5 | 1 | 2 | 3 | 99.9 |
| 4 | 2026 | 4065 | 5 | 3 | 1 | 4 | 92.2 |
| 5 | 2026 | 1678 | 5 | 1 | 4 | 1 | 99.9 |
| 6 | 2026 | 2910 | 5 | 1 | 2 | 3 | 99.7 |
| 7 | 2026 | 2056 | 6 | 1 | 3 | 3 | 99.8 |
| 8 | 2026 | 1690 | 4 | 1 | 2 | 2 | 99.7 |
| 9 | 2026 | 581 | 4 | 2 | 1 | 3 | 99.1 |
| 10 | 2026 | 118 | 9 | 1 | 6 | 3 | 97.4 |
| 11 | 2025 | 2910 | 5 | 1 | 3 | 2 | 99.9 |
| 12 | 2025 | 1690 | 5 | 1 | 4 | 1 | 99.9 |
| 13 | 2025 | 254 | 3 | 1 | 1 | 2 | 99.5 |
| 14 | 2025 | 4414 | 5 | 1 | 1 | 4 | 99.6 |
| 15 | 2025 | 1678 | 4 | 1 | 4 | 0 | 99.8 |
| 16 | 2025 | 1323 | 4 | 1 | 3 | 1 | 99.9 |
| 17 | 2025 | 2056 | 6 | 1 | 4 | 2 | 100.0 |
| 18 | 2025 | 971 | 3 | 7 | 1 | 2 | 97.5 |
| 19 | 2025 | 1114 | 4 | 4 | 2 | 2 | 98.6 |
| 20 | 2025 | 5990 | 4 | 2 | 1 | 2 | 99.2 |
| 21 | 2024 | 1690 | 5 | 1 | 5 | 0 | 99.8 |
| 22 | 2024 | 254 | 4 | 1 | 3 | 1 | 99.9 |
| 23 | 2024 | 1323 | 4 | 1 | 2 | 2 | 99.9 |
| 24 | 2024 | 2910 | 4 | 1 | 1 | 3 | 99.6 |
| 25 | 2024 | 3255 | 2 | 2 | 1 | 1 | 85.3 |
| 26 | 2024 | 118 | 8 | 1 | 4 | 4 | 97.7 |
| 27 | 2024 | 4414 | 4 | 1 | 2 | 2 | 99.5 |
| 28 | 2024 | 179 | 3 | 1 | 1 | 2 | 94.3 |
| 29 | 2024 | 6045 | 3 | 19 | 0 | 2 | 79.6 |
| 30 | 2024 | 971 | 3 | 5 | 3 | 0 | 92.1 |

## Appendix B — the 47 rows not joined (seasons before STRATAI data)

- **2023:** 1323 (row 31), 4414 (row 32), 254 (row 33), 2056 (row 34), 1678 (row 35), 2910 (row 36), 118 (row 37), 5406 (row 38), 6045 (row 39), 2767 (row 40)
- **2022:** 254 (row 41), 1619 (row 42), 1323 (row 43), 179 (row 44), 6045 (row 45), 1678 (row 46), 2056 (row 47), 3310 (row 48), 973 (row 49), 118 (row 50)
- **2019:** 1323 (row 51), 254 (row 52), 973 (row 53), 148 (row 54), 118 (row 55)
- **2018:** 254 (row 56), 148 (row 57), 1678 (row 58), 1323 (row 59)
- **2017:** 2767 (row 60), 254 (row 61), 1678 (row 62), 118 (row 63)
- **2016:** 330 (row 64), 971 (row 65)
- **2015:** 1114 (row 66), 148 (row 67)
- **2014:** 254 (row 68), 1114 (row 69)
- **2013:** 254 (row 70)
- **2012:** 254 (row 71)
- **2011:** 254 (row 72)
- **2010:** 469 (row 73)
- **2008:** 1114 (row 74), 148 (row 75)
- **2002:** 71 (row 76)
- **1996:** 71 (row 77)
