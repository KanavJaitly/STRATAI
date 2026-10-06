# PX-1 composition, Championship exclusion and unresolved selection rules: dated decisions and change plan

**Decided by Kanav, 2026-10-06. Documented here, NOT implemented.** Implementation follows only after Kanav reviews the change plan (§6).

**What this record is:** a dated decision record alongside the frozen specifications. It **does not edit** them:
- `docs/P6Milestones.md` and `.agent/phase6/P6_M0_DECISIONS.md` are hash-frozen;
- `.agent/phase6/P6_M2_PX1_SPEC.md` is frozen by its own text.

When implemented, the PX-1 and P6-M1 records will carry this file's git blob, as they carry the spec's.

**Evidence** (read-only diagnostics on the isolated copy):
- `.agent/phase6/diagnostics/P6_PX1_COMPOSITION_REPORT.md`;
- `p6_px1_composition_diagnostic.json` (`8441354`);
- `p6_px1_exclusion_counts.json` (`0df1b30`).

## 1. Decisions

| ID | Decision | Frozen text it relies on | Kind |
|---|---|---|---|
| **D-PX1-1** | **PX-1 composition is the alliance at the selection moment: the captain and the two original picks.** A standard-event backup (TBA's 4th `picks` entry, recruited during the playoffs per T604/T608) is **never** part of it. The same applies to:<br>• the M6/M7 baseline inside the PX-1 gate;<br>• PX-4's actual alliances;<br>• P6-M8's "actual pick" (P6-Q1), so a backup cannot satisfy it;<br>• the P6-M7 engine's alliances.<br>A temporal and data-semantics correction, not a metric choice | P6-M2 *Inputs* ("three teams' … at the selection moment"); P6-M2 *Leakage* (no in-playoff information); PX-1 spec §1–§2 ("captain-and-picks", "six teams") | the frozen reading; the implementation currently deviates |
| **D-PX1-2** | **FIRST Championship division rows are excluded from PX-1 and counted** by season and event. Their selection-time alliances have four members (2024 §12.2; 2025/2026 §13.2), which is outside the frozen three-team definition. PX-1 is **not** redefined as a four-team model. They remain valid P6-M1 events, represented by the schema-v2 selection variant. The rows are identified from the approved ruleset's **cited variant**, never from `events.event_type` or data patterns | PX-1 spec §1–§2; P6-Q2 "Excluded from training" | **a population addition to P6-Q2 / PX-1 spec §1, authorized by this decision** |
| **D-PX1-3** | **`2024isde2`, `2026tuak2` and `2026tuis4` stay unresolved.** At ruleset entry they are listed in `event_exclusions`, unless an authoritative FIRST document resolves them. Nothing is inferred from TBA | — | entry instruction |
| **D-PX1-4** | **M4: `declined_team_may_become_captain` may be `null`** = "not established by an authoritative source", stored with an explicit unresolved note.<br>• `false` contradicts the documented rule (a Lead who declines keeps captaincy).<br>• `true` asserts a case FIRST does not establish.<br>• TBA has 0 declines in 4,782 alliances.<br>Any path that would actually need the value refuses with an explicit unresolved state, and never substitutes true or false | — | schema/validation change (plan §6) |
| **D-PX1-5** | **2025 `captain_rule` = `null`**, the same unresolved treatment. A final targeted search of official FIRST sources (§2) found no rule for who fills a captain position vacated by a Lead who accepts another alliance's invitation. TBA behaviour is not used | — | schema/validation change (plan §6) |

## 2. The final 2025 `captain_rule` search (official FIRST sources only)

| Source | Version and identity | What it says on this question |
|---|---|---|
| 2025 Game Manual §10.6.1 | [2025GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/2025GameManual.pdf), Section 10 V6, sha256 `dc6aa9ddbeba25c679c58bae746bde14dba2af79a61a65d8c5f575ca6cdfd523` | "the top 8 ranked teams become the ALLIANCE Leads"; absent Lead, then "all lower ranked ALLIANCE Leads are promoted 1 spot"; a Lead is a valid selection (T605 box); "An ALLIANCE Lead that declines … is able to invite teams". **Nothing on who replaces a Lead who accepts** (2024's sentence, "all lower ALLIANCE Leads are promoted 1 spot. The highest-ranked, unselected team becomes the ALLIANCE 8 Lead", is absent in 2025) |
| 2025 Team Updates 00–21 | [TeamUpdate-Combined.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/TeamUpdates/TeamUpdate-Combined.pdf), sha256 `fc8c6292a5756244d1e896d01fc78bb620db9caa95913d42c02a450e379f10fb` | TU01, TU02 and TU14 edit §10.6.1 (pick timer only). **Nothing on captain succession** |
| Alliance Selection Changes (FIRST, Rev. Sep 2024; the 2025 process) | [alliance-selection-changes.pdf](https://www.firstinspires.org/sites/default/files/uploads/resource_library/frc/game-and-season-info/competition-manual/alliance-selection-changes.pdf), sha256 `fd1d6fc5b1b236aaceb682b5febb04ac407040dfdb283965c336ddb2ad85784b` | "Time is also spent shuffling teams around and **bringing in new Alliance Leads**." It acknowledges replacement Leads, but **not who** |
| 2025 FRC Emcee Training | [mc-training.pdf](https://www.firstinspires.org/hubfs/web/volunteer/frc/mc-training.pdf), sha256 `f4fbaff914b8e459fe620c6c72e926e4d6dc958a4c62ac3dcfa313fb9336c8a0` | "If a top eight team selects another top eight team, use this phrasing: 'Would you prefer to join or form your own Alliance?'" **Not who replaces it** |
| FRC Alliance Selection Script 2025 (v3-5bh) | [alliance-selection-script.docx](https://www.firstinspires.org/hubfs/web/volunteer/frc/alliance-selection-script.docx), document created 2025-03-05, sha256 `5035e86744c4ad8f7ec0998697b67426c8f539b1b429ad2b51146a360c058c4c` | "repeat this process … if there are remaining captains to introduce"; "AFTER bringing out the Alliance 8 Captain". **The successor is not specified** |
| Alliance Selection Pick Process (Rev. Feb 26, 2025) | [alliance-selection-process.pdf](https://www.firstinspires.org/hubfs/web/volunteer/frc/alliance-selection-process.pdf), sha256 `8dfa5c5e331fc599699935fe783b2a5d3a84935ac0e8af44c05481f34925b86f` | The automatic assignment of a **pick** is "the next highest-ranked unselected team who has not declined". **Picks only, not captains** |
| Official FIRST Q&A (2025 board) | `game-qa.firstinspires.org/boards/2025/FRC/QA` | **Not searchable here:** it redirects to a FIRST account login. Someone with a FIRST account could search it. A cited answer there would resolve D-PX1-5 |

**Verdict:** FIRST establishes that replacement Leads exist in 2025, but not the rule that chooses them. 2025 `captain_rule` = `null`, unresolved.
- **2024:** established (§10.6.1 promotion text).
- **2026:** supported (§10.6.1 T606 box, "will become captain if not picked"), medium. Unchanged by this search.

## 3. Exact affected populations (pre-M1 candidate population; P6-M1 reproduction exclusion not yet applicable)

| | 2024 (train) | 2025 (train) | 2026 (held-out) |
|---|---|---|---|
| Candidate rows (decided `sf1–13` / `f1`, sides mapped) | 2,817 | 3,007 | 3,165 |
| **Excluded: four-member (Championship division) alliance (D-PX1-2)** | **120** | **122** | **122** |
| Excluded: EPA-incomplete (frozen rule, over the 3 selection members per side) | 1,691 | 422 | 368 |
| Excluded: tie or unplayed (frozen) | 5 | 4 | 1 |
| **Eligible PX-1 rows after D-PX1-1 + D-PX1-2** | **1,006** | **2,463** | **2,675** |
| Eligible under the current implementation (all listed teams, Championship included) | 1,109 | 2,560 | 2,738 |
| Net change | −120 Championship, +17 rows where a backup lacked EPA | −122, +25 | −122, +59 |
| Standard-event rows whose composition changes (backup removed), eligible either way | 194 | 350 | 598 |

The Championship exclusion is 364 rows in 24 events:

| Season | Rows per event |
|---|---|
| 2024 | `arc` 15, `cur` 15, `dal` 15, `gal` 15, `hop` 15, `joh` 15, `mil` 15, `new` 15 |
| 2025 | `arc` 15, `cur` 15, `dal` 15, `gal` 15, `hop` 16, `joh` 15, `mil` 16, `new` 15 |
| 2026 | `arc` 16, `cur` 15, `dal` 15, `gal` 15, `hop` 16, `joh` 15, `mil` 15, `new` 15 |

All 364 would have been EPA-complete.

## 4. Conflicts with frozen items: STOP, needs explicit confirmation

D-PX1-2 authorizes the Championship exclusion **from PX-1 validation**. Its consequences reach three other frozen items. These are reported, not decided:

| # | Frozen item | Consequence | Why it cannot be avoided | Needs |
|---|---|---|---|---|
| **C1** | **PX-4 (P6-M5, P6-Q5): held-out 2026 event population** | The 8 2026 Championship divisions are reproduced P6-M1 events and so in PX-4's population. PX-4 needs PX-1 probabilities for their **4-member** alliances, which PX-1 does not define. Under the guard in §6 they would become `insufficient_data` / excluded, a PX-4 population change | Computing them would silently apply PX-1 outside its frozen domain (the current code would sum 4 teams) | **Your confirmation** that the Championship exclusion extends to PX-4, counted (8 events), or another ruling |
| **C2** | **P6-M8 / P6-DM1 (P6-Q1): held-out 2026 event population** | The same: the engine's field for a Championship division has 4-member alliances, outside PX-1's domain. P6-Q1 fixes the population as "held-out 2026 events stratified by week and size", with the exact sample in M8's pre-run record, which is not yet written | Same as C1 | **Your confirmation** that the M8 pre-run record excludes Championship divisions, counted |
| **C3** | **PX-2 (P6-Q4) calibration slice** | **No conflict in definition** ("the temporally last 20% of the 2025 eligible playoff matches"), but its **membership changes**. The 122 2025 Championship rows (April) would otherwise sit inside the last 20%. Slice: 512 rows under the current implementation, 493 under the decisions | — | none (informational) |

**Not affected:**
- P6-M10 to M13 (qualification matches only);
- the M6/M7 Phase 4 models (the baseline is applied, never refitted);
- the PX-1 objective, features, regularisation, thresholds and train/test split;
- the PX-2/PX-4 methodology, other than C1/C3;
- every acceptance criterion.

**Kept as in the frozen text:** P6-M1 (b) for 2025 is recorded as "captain rule not established", with counts. P6-M1's criterion is "(a) and (b) recorded with counts. Every exclusion has a reason", so this does not alter it.

## 5. Frozen texts touched by these decisions (none edited)

| Frozen text | Effect |
|---|---|
| P6-M2 *Inputs*, *Leakage*; PX-1 spec §1–§2 | D-PX1-1 is their consistent reading. The spec's premise "Backups are unknown" is superseded by fact (TBA lists backups as a 4th pick) |
| P6-Q2 "Excluded from training"; P6-M2 *Implementation* "Excluded"; PX-1 spec §1 exclusion list | D-PX1-2 adds a counted exclusion (authorized) |
| P6-Q1 "actual pick" | D-PX1-1: a backup is not an actual pick (consistent with the text) |
| P6-Q5 / P6-M5; P6-Q1 population | C1 and C2: need confirmation |
| P6-M1 (b) | 2025 captain rule recorded as not established, with counts |
| P6-Q2 "~5,900 eligible 2024–2025 playoff training matches" | Unchanged. The figure matches candidates before the frozen EPA exclusion (5,824); after it, 3,469 under these decisions |

## 6. Change plan (NOT implemented; awaiting review)

| # | File / consumer | Exact change | Semantics |
|---|---|---|---|
| 1 | `data/rulesets.py` `SelectionRules` | `captain_rule: Literal["highest_ranked_available"] \| None`; `declined_team_may_become_captain: bool \| None`; new **required** `unresolved: [{field, note, sources_checked}]`. Validator: a field is `null` **iff** it has an `unresolved` entry; only these two fields may be `null`; note and sources non-empty. Bump `SCHEMA_VERSION` to `p6-ruleset-v3`; nothing has ever been stored | D-PX1-4/5 |
| 2 | `ml/playoffs/data.py` | New `selection_members(alliance, event_rules)` = `picks[: 1 + picks_per_alliance]`. A remaining listed entry is a backup only if `backup_robots` is true and there is at most one; anything else raises `unexpected_listed_team` (counted, never interpreted). `map_matches` maps sides over the members ("captain-and-picks", spec §1; substitutes tolerated). `playoff_rows(…, event_rules)` composes red/blue from the members, and **before** the EPA check excludes a row whose side has ≠ 3 members as `four_member_alliance`, counted per event | D-PX1-1/2 |
| 3 | `ml/playoffs/px1.py::alliance_match_probability` | Refuses any alliance that is not exactly 3 teams (`ValueError`: outside PX-1's frozen domain), so PX-4, M8 and the engine cannot silently sum 4 | D-PX1-2 guard |
| 4 | `scripts/phase6_playoff_track.py` `assemble_rows` / `assemble_rows_for` | Pass `ruleset.for_event(event_key)`; features for the members; exclusion counts by reason **and by event** in the PX-1 record; the record carries this file's blob | D-PX1-1/2 |
| 5 | … `run_m2` / `_m6m7_on` | Unchanged code: the baseline receives `row.red_teams` / `row.blue_teams`, which become the members through #2 | D-PX1-1 |
| 6 | … `run_m5` (PX-4) | Actual alliances = members. Championship events: **pending C1** (excluded and counted if confirmed) | D-PX1-1; C1 |
| 7 | … `run_m8` | `actual` = members (so `identifies()` cannot match a backup); the seed-order baseline and miss facts use the members. Championship events: **pending C2** | D-PX1-1; C2 |
| 8 | … `run_m1` / `_captain_rule_violations` | `captain_rule` `null`, so the season's (b) check is recorded as `captain_rule_not_established` with counts, not as violations. A `null` decline flag counts `decline_rule_not_established` only where a recorded decline would decide a captain (0 today) | D-PX1-4/5 |
| 9 | `ml/playoffs/selection.py` | `_check_supported`: a `null` `captain_rule` raises `RulesetError("not_established")`. `_captain`: a `null` decline flag raises `not_established` **only** when a declined team would be the best-ranked eligible captain; otherwise it proceeds. With 0 declines, no historical run changes. The engine and draft surface the coded error, so a caller gets an explicit unresolved state | D-PX1-4/5 |
| 10 | `scripts/phase6_rulesets.py` template | Blank `unresolved` entry (fails validation until filled or replaced with `[]`) | D-PX1-4/5 |
| 11 | Docs | `docs/phase6.md` (P6-M1 v3 fields; PX-1 composition and exclusion); `P6_M1_HUMAN_INPUT_GUIDE.md` (rows for `unresolved`; D-PX1-3 entry instruction) | — |
| — | **Unchanged** | P6-M6 (a) record; M6 (b) (indexes picks by turn order, never a backup); P6-M10 to M13; the Phase 4 models; the research package; frozen specification files | — |

**Regression tests required:**
- `selection_members`:
  - a standard alliance with a backup gives 3 members;
  - a Championship-variant alliance gives 4;
  - two extra entries, or an extra entry where `backup_robots` is false, are refused.
- `playoff_rows`:
  - a backup never enters red/blue composition;
  - a backup lacking EPA no longer excludes the row;
  - a four-member row is excluded as `four_member_alliance` **before** the EPA check, counted per event.
- The M6/M7 baseline input (`_m6m7_on`) gets exactly 3 teams a side.
- `alliance_match_probability` refuses a 4-team alliance.
- M8: `identifies()` with actual = members cannot be satisfied by the backup alone.
- Schema:
  - `null` is accepted only for the two fields, and only with an `unresolved` note;
  - a note for a non-`null` field is refused;
  - `null` elsewhere is refused;
  - the v2 version string is refused.
- Selection:
  - with a `null` decline flag, drafts and the engine run unchanged when no declined team is decisive;
  - they raise `not_established` when one is;
  - a `null` `captain_rule` makes the draft model and engine raise `not_established`;
  - M1 (b) records `captain_rule_not_established`.
- The existing tests are updated for v3 fixtures.
- The full isolated suite must stay green.

**Not run, applied or entered:** PX-1, PX-2, PX-4, M6 (b), M8; migration 0011; any ruleset.
