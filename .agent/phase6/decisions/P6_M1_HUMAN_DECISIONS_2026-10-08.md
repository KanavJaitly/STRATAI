# P6-M1 human FRC-domain decisions: 2026-10-08

**Decided by Kanav**, the project's qualified FRC-domain reviewer: FRC strategy team member for four years; head of strategy; current-season strategy lead.
- **Recorded by Claude** on his instruction, 2026-10-08.
- **What they resolve:** the human-review items P1–P5 of `P6_M1_SOURCE_AUDIT.md` (`330d7af`).
- **The boundary kept throughout:** these are **his domain interpretations**. Where an official FIRST source states something, it is cited. Where it does not, the record says so. No official citation is fabricated, and no interpretation is attributed to a manual.

**Not changed:**
- PX-1/PX-2/PX-4/M8 specifications, features, metrics, thresholds, splits and acceptance criteria;
- P6-M0, D-PX1-1/2/3/5, C1/C2, P6-M10, the Phase 4 models;
- all exclusions, brackets, picks, backups and variant events.

**Supersedes:**
- D-PX1-4 (null) for `declined_team_may_become_captain` only. The `not_established` behaviour for any field that stays null is unchanged.
- The H3 rationale for the 2026 captain rule (the value is unchanged).

## Decisions

| ID | Audit item | Decision (Kanav's words, condensed) | Official support | What is interpretation | Representation |
|---|---|---|---|---|---|
| **HD-1** | P1 | A lower-ranked team that declines an invitation **can still become an alliance captain** later, but **cannot be selected** by another alliance after declining | **All seasons:** "An ALLIANCE Lead that declines an invitation from another ALLIANCE is able to invite teams to join their ALLIANCE" (2024 §10.6.1 p.121; 2025 p.125; 2026 p.126). **Picking:** T602 (2024 p.121) / T606 (2025 p.125, 2026 p.125): "An ALLIANCE CAPTAIN may not invite a team that has declined". **2024:** "The highest-ranked, unselected team becomes the ALLIANCE 8 Lead" (p.121). **2026 T606 box:** "Teams highlighted in orange (will become captain if not picked) will NOT get a strikethrough if they decline as they can still become captains" (p.126) | Extending captaincy to **every** lower-ranked decliner (not only a current Lead or a highlighted team). No season's manual states this in full. **2026 note:** the strikethrough box could be read as putting non-highlighted decliners out; it does not say so, and the decision reads it as display only. No season contradicts the rule | `declined_team_may_become_captain` = **true** in 2024, 2025 and 2026 (default and Championship variant). `declined_team_may_be_picked_later` stays **false**. The two stay distinct, and the citation names HD-1 as the basis |
| **HD-2** | P3 | A lower-ranked team cannot ask a higher-ranked team to join its alliance. Once a team has made a selection as captain, it is an ALLIANCE CAPTAIN and can no longer be selected by another alliance | **First part, stated in all three manuals:** each ALLIANCE CAPTAIN "invites a team ranked below them in the standings" (2025 §10.6.1 p.124; same in 2024 and 2026) | **Second part:** not stated in the manual (the T605 box's "valid team selection" wording does not address it); his interpretation. **Neither part establishes which team fills a captain position vacated by a Lead who accepts an invitation** in 2025 | 2025 `captain_rule` **stays `null`**. Its `unresolved` note now records HD-2 and why the field remains unresolved. Both parts already hold in the draft model, so nothing new is needed. It offers only teams not already on an alliance, so a captain is never selectable. Each captain is the highest-ranked team still available at its first turn, so no higher-ranked team is ever available to it |
| **HD-3** | P4 | When the eighth-ranked original captain is selected, the ninth-ranked team becomes eligible to serve as captain: the next-highest-ranked eligible team becomes captain as earlier candidates are selected | 2026 §10.6.1: "the top 8 ranked teams become the ALLIANCE Leads" (p.123); absent Lead: "all lower ranked ALLIANCE Leads are promoted 1 spot" (p.124); T606 box (p.126) | **The rank rule** (next-highest-ranked) is his interpretation. T606 establishes that a "will become captain" team exists, not how it is chosen. It is consistent with T606 and the schema | 2026 `captain_rule` = `highest_ranked_available` (**unchanged** from v1). The citation now names HD-3 as the basis and states that T606 does not itself give the rank rule. With HD-1, "eligible" includes decliners |
| **HD-4** | P2 | Not a substantive discrepancy. PARK, ONSTAGE and NOTE in TRAP are all STAGE (endgame) scoring elements, so TU04's wording and the final manual's "ALLIANCE STAGE points" are compatible in intent | TU04 (2024-01-19): "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points"; final 2024 manual Table 10-3 (p.124): "ALLIANCE STAGE points" | The compatibility judgment | 2024 `tie_rule` keeps both citations and appends HD-4 as his interpretation. Free text; it affects no computation, feature or criterion |
| **HD-5** | P5 | Do **not** simulate the pick timer (T605) or timeout behaviour. Out of scope; continue modelling the documented selection order and team availability | 2025/2026 T605 (p.124) | — | No change. `order` stays `serpentine`; the draft model is unchanged. A documented limitation (M5, descriptive): a T605 skip or revisit is not modelled, and P6-M6 (b) reconstructs draft states in nominal order |

## The resulting rulesets (v2; prepared, NOT stored, NOT approved)

`.agent/phase6/rulesets_entry/resolved_v2/ruleset_<season>.json` are built from the stored v1 content (`resolved/`, identical to serving ids 1–3) by applying **only** HD-1 to HD-4. Each validates under `p6-ruleset-v3`.

| Season | `captain_rule` | `declined_team_may_become_captain` | Still unresolved | v2 sha256 |
|---|---|---|---|---|
| 2024 | `highest_ranked_available` (explicit) | true (HD-1) | none | `6b3d221227090d4378ef6a6778de70ced410822412a35daa72bcf0c590902971` |
| 2025 | **null** (D-PX1-5; HD-2 recorded) | true (HD-1) | **`captain_rule`** | `0ad72856f82dd1abe9d149d27a76124cbec7916d4e97a30645a772b5020f8d7e` |
| 2026 | `highest_ranked_available` (HD-3) | true (HD-1) | none | `3caf088c2b1fd4d1146d00dade9bd42355e7398f82e3c8c6c84e5652c063aae1` |

**The v1 → v2 diff is limited to:**
- `declined_team_may_become_captain`;
- the removed `unresolved` entry for it;
- citation additions naming HD-1 and HD-3;
- the 2025 `captain_rule` note;
- the 2024 `tie_rule` text.

Every new official quotation was checked verbatim against the cited page of the official PDF.

**Effect on validation: none on any recorded or projected number.**
- TBA records 0 declines in 2024–2026, so HD-1 changes no historical draft.
- HD-3 keeps the 2026 value.
- 2025's null keeps P6-M1 (b) recording `captain_rule_not_established` for 2025, and the draft model and engine refusing 2025 events. M6 (b) and M8 are 2026-only, and PX-1/2/4 do not use it.

## Next steps (not done)

The v1 rows on serving (ids 1–3, `awaiting_review`) hold the superseded content. As the qualified reviewer:
1. **Return each v1 row**, so it can never be approved:

   ```
   python -m scripts.phase6_rulesets review --id <1|2|3> --reviewer "Kanav" --return --note "superseded by v2 (HD-1..HD-4, 2026-10-08)"
   ```
2. **Store and submit v2** (author as you choose):

   ```
   python -m scripts.phase6_rulesets draft --file .agent/phase6/rulesets_entry/resolved_v2/ruleset_<season>.json --by "<author>"
   python -m scripts.phase6_rulesets submit --id <new id>
   ```
3. **Review the stored v2 rows** (R1–R15, the audit plus this record) and approve each with its full v2 sha256 above:

   ```
   python -m scripts.phase6_rulesets review --id <new id> --reviewer "<name>" --approve --qualification "<qualification>" --checklist <file> --sha256 <v2 sha256>
   ```

   Commit the generated approval records.
4. **Rebuild the isolated copy and verify the runner gate** (`P6_M1_ENTRY_STATUS.md`, last section). Only then run `phase6_playoff_track m1`, then m2, m3, m5, m6b (and m8, with its pre-run record and a named mentor).
