# P6-M1 research package: 2024, 2025 and 2026 rulesets (DRAFT)

**Status: research draft. Not verified, not entered, not submitted, not approved.**
- **Prepared by:** Claude, 2026-10-05, under Kanav's P6-M1 workflow of that date. Claude researches and transcribes; a person verifies every value against the cited source and enters it under their own name; a different named person approves (`data/rulesets.py`).
- **Status of the values:** nothing here is human-verified. Nothing was stored in any database.
- **Sources:** official FIRST documents only (`sources.json`), plus the canonical TBA data, read-only from the isolated `stratai_test` copy (`tba_evidence.json`, produced by `scripts/phase6_m1_tba_evidence.py`, about 1 s to run).
- **Excluded sources:** no Reddit, blogs or third-party guides were used.

| File | What it is |
|---|---|
| `ruleset_<season>_research_draft.json` | The proposed ruleset, using the **exact P6-M1 field names and formats** (the `scripts.phase6_rulesets template` skeleton). `"UNRESOLVED"` marks a value the documents do not establish or the schema cannot hold faithfully. **Each file fails schema validation on purpose** while anything is UNRESOLVED (checked: 2024 and 2026 fail on 3 selection fields plus 6 brackets; 2025 also fails on `captain_rule`) |
| `citations_<season>.md` | One row per field: the proposed value; source document and version; FIRST URL; section or rule number with page; evidence; Game Manual or Team Update; uncertainty |
| `sources.json` | Document URLs, sha256s and page counts. The PDFs are not stored in the repository; re-download them and compare the sha256 |
| `tba_evidence.json` | The TBA evidence for D2 (mapping), D5 (fourth teams), the selection booleans and small events |

## 1. The documents and the versions that applied

| Season | Game Manual | Team Updates | Events with playoffs (canonical data) |
|---|---|---|---|
| 2024 CRESCENDO | [2024GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2024/Manual/2024GameManual.pdf): final consolidated PDF. No single version number: Section 10 V5, Section 11 V5, Section 12 V0 | [TeamUpdates-combined.pdf](https://firstfrc.blob.core.windows.net/frc2024/Manual/TeamUpdates/TeamUpdates-combined.pdf): TU00–TU21; TU21 (2024-04-09) is the final update | 190, from 2024-02-24 to 2024-04-20 |
| 2025 REEFSCAPE | [2025GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/2025GameManual.pdf): final consolidated PDF. Section 10 V6, Section 11 V3, Section 13 V0 | [TeamUpdate-Combined.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/TeamUpdates/TeamUpdate-Combined.pdf): TU00–TU21; TU21 (2025-04-08) is the last update | 203, from 2025-02-23 to 2025-04-19 |
| 2026 REBUILT | [2026GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2026/Manual/2026GameManual.pdf): marked "Version: TU22" | [REBUILT_TeamUpdate-Combined.pdf](https://firstfrc.blob.core.windows.net/frc2026/Manual/TeamUpdates/REBUILT_TeamUpdate-Combined.pdf): TU01–TU22; TU22 (2026-04-21) is the final update | 213, from 2026-03-03 to 2026-07-08 |

**The current PDF is not assumed to be the historical version.**
- Each PDF is FIRST's consolidated current manual. The version in force at an event was the manual as amended by the Team Updates published before that event.
- The rule sections were therefore checked against **every** Team Update (§2).
- **Result:** no Team Update changed a structured schema field after a season's first official event. For those fields, the final PDF gives the same values as every version in force at an event.
- **The exception is free text:** the 2025 tie-rule wording changed mid-season (TU19).

**Not obtained or reviewed** (all official FIRST material, listed here for completeness):
- the Playoff Communication Document and the Championship Playoff Communication Document, referenced by 2024 TU06/TU18/TU21, 2025 TU11 and 2026 TU11;
- the FIRST Q&A system;
- the bracket figures, which are images: Figure 10-2, Figures 11-1/11-2 and Figure 12-1/13-1. The 8-alliance bracket was taken from Table 10-2, the text form of Figure 10-2, and TBA confirms it at every event.

## 2. D1: Team Updates that touched a schema-relevant section

| Season | Team Update (date) | Section | Change | Schema field affected | Before the first official event? |
|---|---|---|---|---|---|
| 2024 | TU00 (2024-01-06) | §10.2; §10.6.2 Table 10-2 | Adds ARENA FAULT item (radio disconnect over 8 s); Table 10-2 timings and breaks only | none (bracket topology unchanged) | yes |
| 2024 | TU04 (2024-01-19) | §10.6.2.1 Table 10-3 | Sets the 3rd tiebreaker to "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points" | `tie_rule` (text) | yes |
| 2024 | TU06 (2024-01-26) | — | Playoff Alliance Communication document published | none | yes |
| 2024 | TU13 (2024-02-20) | §10.2 | ARENA FAULT wording | none | yes |
| 2024 | TU16 (2024-03-05) | §10.6.3.1 T606 | Backup coupon deadline wording | none (`backup_robots` unchanged) | no (procedural) |
| 2024 | TU18 (2024-03-19) | Playoff Communication Document V1 | Reminder that matches from previous rounds may not be replayed (per §10.6.2) | none | no (procedural) |
| 2024 | TU19 (2024-03-26) | §10.6.5 | Pit crews | none | no |
| 2024 | TU20 (2024-04-02) | §10.2 | Typical replay causes: playoff ties per Table 10-3, or any Finals MATCH | none (consistent with `tie_rule`) | no (clarification) |
| 2024 | TU21 (2024-04-09) | — | Championship Playoff Communication Document posted (not reviewed) | none known | — |
| 2025 | TU01 (2025-01-07), TU02 (2025-01-10) | §10.6.1 T605; §10.6.3.2 | Pick-timer procedure; backup pool polled by the lead queuer | none (see mismatch M5) | yes |
| 2025 | TU08 (2025-01-31), TU09 (2025-02-04) | §10.6.3.2 T611 | Backup pool wording | none | yes |
| 2025 | TU11 (2025-02-11) | — | Playoff Communication Documents updated (not reviewed) | none known | yes |
| 2025 | TU14 (2025-02-21) | §10.2; §10.6.1 | Replay examples ("score or penalty"); T605 revisit after a declined invitation | none | yes |
| 2025 | **TU19 (2025-03-25)** | §10.6.2.1 Table 10-3 | 2nd tiebreaker changes to "ALLIANCE LEAVE + AUTO CORAL points", "to reflect how the FMS has been calculating AUTO points" | `tie_rule` (text only) | **no**: 133 of 203 events had ended |
| 2025 | TU20 (2025-04-01) | §11.3 | District Championship division assignment | none | no |
| 2026 | TU08 (2026-02-06) | §10.2 | Game Data is not an ARENA FAULT | none | yes |
| 2026 | TU11 (2026-02-17) | — | Playoff Communication Documents updated (not reviewed) | none known | yes |
| 2026 | TU12 (2026-02-20) | §10.6.2 Table 10-2 | Award-break names only | none | yes |
| 2026 | TU22 (2026-04-21) | §7.2 G211 | Card scrutiny in lower-bracket and finals matches | none | no |

No Team Update in any season touched §10.6.1's structure, captains, declines, picks per alliance, §10.6.6, §11.4, §12.2/13.2 or the bracket topology.

**D1 conclusions:**
- **Events or ranges affected:** only 2025's `tie_rule` wording. 133 events ended before 2025-03-25, and 70 started on or after it. TU19 says the FMS calculation itself did not change.
- **Is one ruleset per season faithful?** Yes for every structured field in all three seasons. The 2025 `tie_rule` is free text and informational (D7), so the proposed text records the TU19 change and its date.
- **Events excluded on D1 grounds:** none.
- **Schema change for D1:** no effective-date or per-event ruleset is needed.
- **Caveat:** the three 2026 Israel events (2026-06-28 to 2026-07-08) ran after TU22. The final manual applies to them, and no later FIRST document was found.

## 3. D2: the TBA mapping (verified, not assumed)

For every seeded 8-alliance event, `scripts/phase6_m1_tba_evidence.py` checked each TBA set against the manual's Table 10-2:
1. It mapped each TBA set's red and blue teams to alliance seeds.
2. It derived each expected side from the **actual** winners and losers of the earlier sets.
3. It compared the expected sides with the actual ones.

| TBA key | Manual (Table 10-2) | Red / Blue sources | Round | Agreement (seeds and colours) |
|---|---|---|---|---|
| `semifinal` set 1 | MATCH 1 | seed 1 / seed 8 | 1 | 185/185 (2024), 198/198 (2025), 208/208 (2026) |
| `semifinal` set 2 | MATCH 2 | seed 4 / seed 5 | 1 | all |
| `semifinal` set 3 | MATCH 3 | seed 2 / seed 7 | 1 | all |
| `semifinal` set 4 | MATCH 4 | seed 3 / seed 6 | 1 | all |
| `semifinal` set 5 | MATCH 5 | L1 / L2 | 2 | all |
| `semifinal` set 6 | MATCH 6 | L3 / L4 | 2 | all |
| `semifinal` set 7 | MATCH 7 | W1 / W2 | 2 | all |
| `semifinal` set 8 | MATCH 8 | W3 / W4 | 2 | all |
| `semifinal` set 9 | MATCH 9 | L7 / W6 | 3 | all |
| `semifinal` set 10 | MATCH 10 | L8 / W5 | 3 | all |
| `semifinal` set 11 | MATCH 11 | W7 / W8 | 4 | all |
| `semifinal` set 12 | MATCH 12 | W10 / W9 | 4 | all |
| `semifinal` set 13 | MATCH 13 | L11 / W12 | 5 | all |
| `final` set 1 | Finals 14, 15, 16* and Overtime | W11 / W13, best of 3 (wins_needed 2) | Finals | all |

- **Agreement:** zero mismatches and zero colour swaps. No playoff match uses any other level or set.
- **Finals match numbers:** in TBA they are the finals game numbers, 1–4. Four occurs at 3, 2 and 1 events per season, consistent with Overtime MATCHES.
- **Semifinal match numbers:** always 1, apart from one 2025 replay (`match_number` 2).
- **Championship divisions:** the 8 FIRST Championship divisions per season use the same bracket, and agree.
- **No TBA data was altered.**

## 4. D5: what the fourth listed team is (exact finding)

**Two different things.** TBA's `backup` field is null for every 2024–2026 alliance. TBA records a backup by **appending it to `picks`**, and does not record which team it replaced.

| Season | Seeded events listing any 4th team | FIRST Championship divisions: **every** alliance lists 4 | Other events: **some** alliances list 4 | 4th team first plays after its alliance's first playoff match | 4th team is the highest-ranked team not on an alliance |
|---|---|---|---|---|---|
| 2024 | 104 | 8 (`2024arc cur dal gal hop joh mil new`) | 96 | 148 of 149 | 117 of 149 |
| 2025 | 100 | 8 (`2025arc` … `new`) | 92 | 108 of 108 | 87 of 108 |
| 2026 | 126 | 8 (`2026arc` … `new`) | 118 | 187 of 189 | 119 of 189 |

**At the FIRST Championship divisions, the 4th team is a round-3 pick.**
- 2024 §12.2 p.137; 2025 and 2026 §13.2 p.147: "the process continues with a third round of selection ... Round 3 ... ALLIANCE 1 picking first and ALLIANCE 8 picking last. This process results in 8 ALLIANCES of 4 teams each."
- Also: "There is no provision for BACKUP TEAMS at the FIRST Championship."
- So at those events `picks_per_alliance` is 3 and `backup_robots` is false.

**Everywhere else, the 4th team is a BACKUP TEAM** (§10.6.3; 2024 p.124, 2025 and 2026 p.128). The alliance captain "has the option to bring in the highest ranked team from the pool of available teams ... The resulting ALLIANCE is then composed of 4 teams". The rest of the evidence agrees:
- **Timing:** a backup may not be requested before the alliance's first playoff match (2024 T604; 2025 and 2026 T608), and the 4th team first plays after that match in 443 of 446 cases.
- **Rank:** the rank check falls short ("is not" in `tba_evidence.json`) only as an upper bound. TBA does not record BACKUP POOL declines or absences (§10.6.3.2), so a lower-ranked backup is not evidence of a rule breach.
- **Three alliances do not fit, and no FIRST document explains them:**
  - `2024isde2` seed 7: the 4th listed team, 4416, played the alliance's first match, and the 3rd listed, 2212, did not.
  - `2026tuak2` seed 8: the 4th listed team, 10998, played the first match.
  - `2026tuis4` seed 4: the 4th listed team, 8042, never played.

**Schema verdict: STOP.** The current schema cannot represent this faithfully (mismatch **M1**).
- `selection.picks_per_alliance` and `selection.backup_robots` are single values per season. Every season needs 2/true at its standard events and 3/false at its 8 Championship divisions.
- Choosing one value would be the approximation you ruled out, so both are `UNRESOLVED` in the drafts.
- **Event type cannot identify those events:** `events.event_type` is NULL for every event in the canonical data.

**Proposals (NOT implemented; each needs your explicit, dated decision):**

| Option | What | Schema or DDL impact | Effect |
|---|---|---|---|
| **P1** | Add a cited selection variant to the ruleset, e.g. `selection_variants: [{event_keys: [...], picks_per_alliance: 3, backup_robots: false, citation}]`. The event keys are entered by a person from FIRST's division list, never inferred. Consumers (`turn_order`, the P6-M1 (b) checks, P6-M6 (b), P6-M8) use the variant for those events | New `SCHEMA_VERSION` (`p6-ruleset-v2`), validators and tests. **No DDL change:** `ruleset_json` is JSONB, and 0011's one-approved-per-season index still holds, because one ruleset still covers the season | The Championship divisions are modelled faithfully |
| **P2** | Keep the schema. Transcribe 2/true, and treat the Championship divisions as `not_supported`: excluded and counted, never approximated (the guide's D5 option (c)) | None to the schema. It still needs a human-entered exclusion list, because `event_type` is NULL | 8 of 185, 8 of 198 and 8 of 208 seeded events are excluded (4.3%, 4.0%, 3.8%), below P6-Q13's 10% escalation threshold |

**A related item for the frozen PX-1 spec (reported, not changed).** At non-Championship events, a backup sits in `picks[3]`. PX-1's composition sums run over the listed picks, so backups enter its inputs at 96, 92 and 118 events. Whether that is intended is a PX-1 question (mismatch **M2**).

## 5. Rules the schema cannot represent (D6)

| ID | Rule (source) | Why the schema cannot hold it | Events affected in the data |
|---|---|---|---|
| **M1** | Championship divisions: 3 picks and no backups (§12.2 / §13.2) | One `picks_per_alliance` and one `backup_robots` per season | 8 per season (§4) |
| **M2** | Backups are recorded by TBA as a 4th `picks` entry (§10.6.3; a TBA representation) | No field separates a pick from a backup | 96, 92 and 118 events |
| **M3** | Small events (§10.6.6): "Multi-day events with 24 teams or fewer" use floor((teams − 1) / 3) alliances; "any matchup against a non-existent ALLIANCE" is a bye | (a) The "multi-day" condition has no field. (b) TBA records these events as **8 alliances**, the missing ones filled with placeholder teams 9990–9999, and the "bye" matches carry results. The schema's brackets need seeds ≤ alliances and have no bye or placeholder concept. (c) A 7-alliance count against TBA's 8 alliances makes `event_bracket` refuse the event | `2024vapor` (23 teams, 7 real alliances), `2025ncash` (22, 7), `2026mefal` (20, 6), `2026txfor` (24, 7), `2026txmca` (18, 5). TBA's real-alliance count equals the manual's formula at all five. **`2026isde2`** (24 teams) ran 8 real alliances, contrary to §10.6.6; no FIRST document explains this |
| **M4** | Declines and captaincy: a decliner who is already a Lead keeps captaincy (all seasons). In 2026, a decliner "highlighted in orange (will become captain if not picked)" can still become captain. Other decliners are not addressed | One boolean cannot express a rule conditional on status at the moment of declining. The documents are also silent for other decliners. TBA records **no** declines (0 in all three seasons), so data cannot settle it | not measurable |
| **M5** | Pick timer, T605 (2025, 2026): a skipped alliance is revisited later, or "receives the next highest-ranked unselected team" | `order` is `serpentine` only | unknown (TBA records the result, not the sequence) |
| **M6** | Finals: a tied Finals MATCH stays a tie; up to 3 Overtime MATCHES; a tied Overtime MATCH is decided by Table 10-3. Einstein Finals ties are replayed | Only `wins_needed` and free-text `tie_rule`. Faithful only if consumers count a tied finals match as no win | finals with a 4th match: 3, 2 and 1 events |
| **M7** | District Championship multi-division playoffs (§11.4 Table 11-7, Figures 11-1/11-2) and Einstein (§12.4 / §13.4, Figure 12-1/13-1): unseeded division-champion alliances | Brackets are keyed by alliance count, so a 4-alliance District Championship bracket would collide with the 4-alliance small-event format, and the alliances have no seeds | `micmp`, `necmp`, `oncmp`, `txcmp` and `cmptx` per season, already excluded by P6-Q2 (division champions) |
| **M8** | Backup mechanics (§10.6.3): one coupon per alliance, highest-ranked from the BACKUP POOL, not before the first playoff match; at District Championship playoffs, from the alliance's own division's pool | `backup_robots` is a boolean, recorded but not modelled (as designed) | informational |

**Not representable, but excluded anyway:**
- the absent-team rule (T601: absent team ineligible, lower Leads promoted);
- DQ = 0 points in a playoff match (§10.6).

## 6. Decisions D1–D7

| Decision | Research conclusion |
|---|---|
| **D1** Mid-season changes | No structured field changed mid-season. 2025 TU19 changed `tie_rule` wording only (informational). One ruleset per season is faithful; no exclusions; no effective-date schema needed (§2) |
| **D2** Match numbering | `semifinal` set n = manual MATCH n (1–13); `final` set 1 = Finals. Verified at every seeded event of each season (§3) |
| **D3** Round numbering | The manual's own labels are identical in all three seasons: rounds 1 (M1–4), 2 (M5–8), 3 (M9–10), 4 (M11–12), 5 (M13), and Finals as the sixth round ("Playoff MATCHES consist of 6 rounds"). The drafts use 1–5 and finals 6. **The convention is still yours to confirm** |
| **D4** Smaller alliance counts | The drafts transcribe §10.6.6's counts (25+ → 8, 22–24 → 7, …, 7–9 → 2). Their brackets are `UNRESOLVED` because of M3. **Yours:** keep the small counts (brackets need a bye representation or a decision), or keep only 25+ → 8 and accept the 5 placeholder events (plus `2026isde2`) as excluded and counted. Either way these events cannot be reproduced under the current schema |
| **D5** Fourth teams | §4: a round-3 pick at Championship divisions and a backup elsewhere. **STOP:** schema mismatch M1. P1 or P2 needs your decision |
| **D6** Unsupported rules | M1–M8 (§5) |
| **D7** Tie rule | Transcribed with citations per season. 2024: the final PDF says "ALLIANCE STAGE points", but TU04 (pre-season) says "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points", and no Team Update records the difference. 2025: TU19 mid-season wording change. 2026: unchanged |

## 7. Every UNRESOLVED or uncertain value

| Season | Field | Why |
|---|---|---|
| all | `selection.picks_per_alliance` | M1 (D5): 2 at standard events, 3 at Championship divisions |
| all | `selection.backup_robots` | M1 (D5): true at standard events, false at the Championship |
| all | `selection.declined_team_may_become_captain` | M4: the manuals cover only a decliner who is already a Lead (and, in 2026, one highlighted to become captain); TBA records no declines |
| 2025 | `selection.captain_rule` | The 2025 manual, unlike 2024's, does not state who replaces a Lead who accepts an invitation. TBA agrees with `highest_ranked_available` at 1,583 of 1,584 alliances, but data is not a rule |
| all | `brackets` for 7 down to 2 alliances | M3: byes and placeholder alliances |
| all | rosters of fewer than 7 teams | No rule in the manual; the schema needs at least 2 alliances; no such event in the data |
| 2026 | `selection.captain_rule` (medium) | Supported by the T606 orange-highlight note, not by an explicit promotion rule |
| 2024 | `tie_rule` 3rd criterion (medium) | Final PDF wording differs from TU04's, with no Team Update recording the change |
| 2025 | `tie_rule` 2nd criterion (medium) | Pre-TU19 wording is not in the documents obtained |
| all | `manual.version` (medium) | The PDFs are FIRST's final consolidated versions. D1 shows no structured value differs from the versions in force at events |
| all | `rounds` (medium) | D3 is your convention decision |
| — | TBA anomalies | `2024isde2` seed 7, `2026tuak2` seed 8, `2026tuis4` seed 4 (backup timing); `2026isde2` (8 real alliances at 24 teams). No FIRST document explains them |

## 8. Migration 0011

**Keep it deferred.** It was not applied to serving.
- No ruleset can be approved: every season has UNRESOLVED fields.
- If you choose P1, the ruleset schema version changes before anything is entered. This needs no DDL change, because `ruleset_json` is JSONB and P1 keeps one approved ruleset per season.
- Applying 0011 to serving remains your production step.

## 9. How a person uses this package

1. **Decide.** Settle D3, D4 and D5 (P1 or P2), and M4/M5 where they matter. Write each decision down, dated.
2. **Verify.** For each season, open the cited PDF (check its sha256 against `sources.json`) and confirm every row of `citations_<season>.md` against the cited page. Correct anything that is wrong.
3. **Enter.** Enter the verified ruleset under your own name with `python -m scripts.phase6_rulesets draft --file … --by "<you>"`. A draft file containing `UNRESOLVED` is refused by the schema.
4. **Review.** A different named person reviews it (`P6_M1_HUMAN_INPUT_GUIDE.md` §5, R1–R10), against the documents, not against this draft.

**Do not run** PX-1, PX-2, PX-4, M6 (b) or M8 until a season has an approved ruleset.
