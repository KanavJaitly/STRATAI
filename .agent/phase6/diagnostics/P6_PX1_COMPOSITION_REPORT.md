# PX-1 composition, M4 and the open P6-M1 items: read-only diagnostic and decision report

**2026-10-05. Diagnostic only.**
- Nothing in PX-1 (code, features, weights, objective, population, gate) changed. No frozen spec, M10 or research file changed.
- No ruleset was entered, and migration 0011 was not applied.
- PX-1, PX-2, PX-4, M6 (b) and M8 were not run.
- **Data:** `p6_px1_composition_diagnostic.json`, from `scripts/phase6_px1_composition_diagnostic.py` at `8441354`, on the isolated copy, read-only, 0.6 min.
- **Counts are the pre-M1 candidate population.** No approved ruleset exists, so the P6-M1 reproduction exclusion is not applied.

## 1. What the frozen texts say "composition" is

| Source (frozen) | Text |
|---|---|
| `docs/P6Milestones.md`, P6-M2 *Inputs* | "Alliance composition (**three teams'** point-in-time `TeamFeatures` **at the selection moment**)" |
| P6-M2 *Leakage* | "Team features at the selection moment. No earlier or **in-playoff** result at the event is a feature (P6-Q2). **No feature from the match itself** or any later match. Seeds only after selection" |
| `P6_M0_DECISIONS.md` P6-Q2, and interpretation note | "alliance composition sums" = "the existing Phase 4 alliance representation, i.e. **M6's input**: `TEAM_FEATURE_NAMES` summed per alliance". M6 sums the three teams of a match side (`docs/ml_models.md` §2) |
| `P6_M2_PX1_SPEC.md` §1 | "A match side maps to the alliance whose captain-and-picks contain at least two of that side's **three** teams. **Backups are unknown**, so substitutes are tolerated"; "EPA-incomplete rows (any of the **six teams** without `epa_total`)" |
| `P6_M2_PX1_SPEC.md` §2 | "A composition column is used only if it is present for all **six teams** in every eligible training row" |
| P6-M2 *Validation* / spec §4 | The M6/M7 baseline is applied "to each playoff match's selection-moment features (the same inputs as PX-1)" |
| P5-M1 acceptance, P6 inventory | "0 backups", "backups unknown (TBA null)" |

**Intended meaning:**
- An alliance's composition is **its three teams as they stand at the selection moment**: the captain and two picks.
- The spec was written on the premise that backups do not appear in the data.
- It never contemplated 4-team alliances.

## 2. What a fourth listed team is (TBA `picks[3]`; seeded events)

| | 2024 | 2025 | 2026 |
|---|---|---|---|
| Seeded events / with any 4th listed team | 185 / 104 | 198 / 100 | 208 / 126 |
| Championship divisions (every alliance lists 4): **round-3 picks**, members at selection (§12.2 / §13.2) | 8 events, 64 alliances | 8, 64 | 8, 64 |
| Standard events: **backups** consistent with T604/T608 (first play after the alliance's first match), recruited during the playoffs, **not** members at selection | 95 events, 148 alliances | 92, 108 | 116, 187 |
| **Anomalous** (unresolved; no FIRST explanation) | `2024isde2` seed 7 (in first match) | — | `2026tuak2` seed 8 (in first match), `2026tuis4` seed 4 (never played) |
| Any other 4th or 5th listed team | none (every seeded alliance lists 3 or 4) | none | none |

**Related, but not fourth teams:** the five small-event **placeholder alliances** (teams 9990–9999). Those teams have no features, so every row involving one is EPA-incomplete and excluded under every interpretation.

## 3. Effect on PX-1 observations

**Candidates** are decided `sf1–13` / `f1` matches at seeded events with both sides mapped. "Eligible" means EPA-complete for the teams in the composition.

| | 2024 (train) | 2025 (train) | 2026 (held-out) |
|---|---|---|---|
| Candidate rows | 2,817 | 3,007 | 3,165 |
| Eligible under the **current implementation** (every listed team) | 1,109 | 2,560 | 2,738 |
| Eligible under **A** (captain + two picks) and under **B** (selection-time members) | 1,126 | 2,585 | 2,797 |
| Rows whose composition differs, current vs A | 675 | 550 | 866 |
| … of which eligible under both (a changed feature value) | 314 | 472 | 720 |
| … whose eligibility flips (a 4th team lacks EPA, so the row is excluded only under the current implementation) | 17 | 25 | 59 |
| Rows that differ, current vs B (backup rows) | 555 | 428 | 744 |
| Rows that differ, A vs B (Championship rows) | 120 | 122 | 122 |
| Side appearances with a 4th listed team: backup / round-3 / anomalous | 587 / 240 / 2 | 438 / 244 / 0 | 798 / 244 / 7 |
| Rows where the on-field trio differs from A (information only) | 265 | 189 | 321 |

**Totals:**
- **Changed feature values:** 786 of 3,669 training rows (21%) and 720 of 2,738 held-out rows (26%) eligible under the current implementation.
- **Rows that drop out of the current population:** 42 training and 59 held-out rows.

**Population note:** the frozen P6-Q2 says "~5,900 eligible 2024–2025 playoff training matches". That matches the 5,824 candidates *before* the frozen EPA-incomplete exclusion. After that exclusion, about 3,700 remain (2024's EPA coverage is low). Reported as a fact; nothing is proposed.

## 4. Which gates consume this composition

| Consumer | How | Affected |
|---|---|---|
| **P6-M2 PX-1 gate (P6-Q3)** | PX-1's composition-difference features | yes |
| … the M6/M7 baseline inside that gate (`_m6m7_on`) | M6/M7 receives the same listed teams, so it gets **4-team sums** at Championship and backup rows, outside its 3-team training representation | yes |
| … the seed-only baseline | no composition, but it shares the row population (EPA exclusion) | population only |
| **P6-M3 PX-2** | calibrator fit on PX-1 outputs (last 20% of 2025) and evaluated on 2026 | yes, through PX-1 |
| **P6-M5 PX-4 (P6-Q5)** | `field_outcome` over the **actual** alliances' listed teams | yes. The seed-only baseline does not use composition |
| **P6-M8 / P6-DM1 (P6-Q1)** | engine probabilities over predicted alliances; `identifies()` uses the actual listed teams, so a **backup can satisfy "at least one actual pick"**; the seed-order baseline uses the listed teams | yes |
| **P6-M7 engine (service)** | predicted alliances never contain backups (the draft model has none), so the current implementation **trains on backups that serving never sees** (train/serve skew) | yes |
| P6-M6 (a) (already recorded) | the synergy check runs only on alliances listing exactly 3 | descriptive; no gate |
| P6-M1, P6-M6 (b), P6-M10 to M13 | captain, picks by turn order, or qualification matches | no |

## 5. Interpretations against the frozen specification

| Interpretation | Standard events | Championship divisions | Consistent with the frozen spec? |
|---|---|---|---|
| **Current implementation:** every listed team | includes backups | 4 teams | **No.** A backup is recruited during the playoffs, after the alliance's first match (T604/T608). Including it applies in-playoff information to every one of the alliance's matches, including those before the recruitment. That violates "at the selection moment" and "no in-playoff result", and breaks "three teams" / "six teams". It also creates the train/serve skew |
| **A:** captain + two ordinary picks | = the selection-time alliance | drops the round-3 pick | **Standard events: yes**, on every frozen phrase. **Championship: no.** The round-3 pick is a member at the selection moment, and nothing frozen says which three of four to use, so dropping one is an unstated rule (an approximation) |
| **B:** all members at the selection moment | = A | 4 teams | **Standard events: yes (= A). Championship: no.** It contradicts "three teams'" and "six teams", and M6's 3-team representation, which the M6/M7 baseline also receives |
| **C1:** the three on-field teams per match | the lineup | the lineup | **No.** The lineup is "from the match itself" (P6-M2 *Leakage*) and is not known at the selection moment, where PX-4, M8 and the engine need it |
| **C2:** exclude Championship-division rows from PX-1, plus A elsewhere | A | excluded | **Not in the frozen spec.** P6-Q2 lists the excluded populations (EPA-incomplete, the 15 division-champion events); this would add one. A population change needs your decision |

**Verdict:**
1. **Standard events: no mismatch.** The frozen spec has one consistent reading, A = B: captain plus two picks, backups excluded. The current implementation **deviates from it** by including backups. That is an implementation defect against the frozen spec, not a spec ambiguity, but per your instruction nothing is changed.
2. **FIRST Championship divisions: a genuine specification/data-model mismatch.**
   - The frozen texts define composition for three-team alliances at the selection moment.
   - FIRST's 4-ROBOT ALLIANCES have four members at that moment, and none of the frozen texts says how to represent them.
   - Every candidate (A, B, C1, C2, or a new 4-team definition) requires a new explicit decision.
   - **Stopped here.** Rows affected: 120 / 122 (training) and 122 (held-out) candidates.
3. **The three anomalies.** Under A their composition would follow TBA's list order, which may not reflect selection order, since a listed "pick" never played. These are 2 training and 7 held-out side appearances. **Unresolved:** exclude-and-count candidates, not to be interpreted.

## 6. M4: captaincy after a decline

**Validated numbers: none depend on it.**
- TBA records **0 declines** in all 4,782 alliances at 606 events, 2024–2026.
- The P6-M1 (b) captain check, M6 (b) (decline state from TBA) and M8 (drafts start with no declines) therefore never read the value.
- PX-1, PX-2 and PX-4 do not use it.

**But the current schema cannot leave it unresolved:**
- The field is a required boolean, so an approved ruleset must contain true or false.
- That value governs the P6-M7 engine whenever declines are supplied (`_captain`).
- What FIRST establishes:
  - a Lead who declines keeps captaincy (all seasons);
  - in 2026, a decliner highlighted to "become captain if not picked" can still become captain (2026 §10.6.1 T606 box);
  - other decliners: not established. The 2026 strikethrough note arguably implies they are out.
- So `false` contradicts established text, and `true` asserts the unestablished case.

**Conclusion:** a schema change, or a dated decision accepting a value, **is required before M1 approval** if the no-guess rule holds. It does not affect validation. A minimal option, not implemented: allow `null` ("not established"), with the engine refusing a draft state where a declined team's captaincy would be decided by it.

## 7. Decision table: what blocks what

| Item | What is needed | Blocks M1 | Blocks PX-1 |
|---|---|---|---|
| **PX-1 composition at standard events** (backups included today) | Your decision to align the implementation with the frozen reading (A), or another ruling | no | **yes** |
| **PX-1 composition at Championship divisions** | A new explicit decision (§5): mismatch | no | **yes** |
| **M4** captaincy after a decline | A schema change (e.g. null = not established) or a dated decision | **yes** (approval) | no |
| **2025 `captain_rule`** | An official FIRST source (Q&A or Playoff Communication Document) or your decision. The 2025 manual does not state who replaces a Lead who accepts | **yes** (approval) | no |
| **Anomalous events** `2024isde2`, `2026tuak2`, `2026tuis4` | An exclude-and-count decision at entry (`event_exclusions`) | **yes** (entry decision for 2024 and 2026) | **yes** (their rows' composition is unresolved) |
| **Five small-event placeholder/bye events** (plus `2026isde2`) | An exclusion decision at entry (C), or a bye schema extension if you want them represented | **yes** (entry decision) | no (placeholder rows are EPA-incomplete under every interpretation, and the events are excluded by M1) |
| **M7** District Championship / Einstein | none: frozen P6-Q2 exclusion of the 15 division-champion events, counted | no | no |
| **M3** | = the small-event row | see above | no |
| **Championship selection variants** | Entry of the 8 division keys per season, each cited from FIRST (schema v2 ready) | entry work only, no open decision | via the composition mismatch above |
