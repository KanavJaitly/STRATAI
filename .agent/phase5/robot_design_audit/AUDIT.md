# P5-M0 audit — curated robot-design / archetype dataset

2026-10-02. **Analysis only:** no archetype engine, similarity code, model or API was built.

- **Source of truth:** `data/reference/frc_robot_design_curated.csv` (sha256 `40aef139…139e1`).
- **Database:** canonical STRATAI, read-only.
- **Reproduce:** `python .agent/phase5/robot_design_audit/audit.py <statbotics_snapshot> audit_result.json`.
- **Full per-row output:** `audit_result.json`.

## 1. Structure

| Item | Finding |
|---|---|
| Rows / columns | **77** rows (the request stated 78; one is missing or the count was off) / 6 columns |
| Columns | `Year`, `Team`, `Game Name`, `Robot Micro-Archetype`, `Technical Specifications`, `Key Characteristic & Competitive Advantage` |
| Completeness | every field populated; 0 exact duplicates; no repeated (year, team) |
| Seasons | 18 games, 1996–2026. Years and game names all agree. 2026–2022: 10 rows each; 2019: 5; 2018 and 2017: 4 each; then 2, 2, 2, 1, 1, 1, 1, 2, 1, 1. Absent: 1992–95, 1997–2001, 2003–07, 2009, 2020–21 |
| Teams | 25 distinct. Repeats: 254 ×12, 1323 ×7, 1678 ×6, 118 ×6, then 4414, 2910, 2056, 1114 and 148 ×4 each, and more |
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
- **Automatic keyword assignment is not reliable.** About 15 of 77 rows (~20%) are clearly misassigned. Examples:
  - "Non-**turret**ed" shooter tagged as a turret;
  - turreted placing mechanisms tagged as launchers;
  - a boom tagged as drivetrain because it mentions a swerve module.
- **Single labels lose information:** about 13 rows describe several functions ("X / Y").
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
