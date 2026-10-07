# P6-M1 source-evidence audit of the stored 2024–2026 rulesets (read-only)

**2026-10-07. Audit only.**
- No ruleset was approved, changed or re-submitted.
- `phase6_playoff_track` (M1, PX-1/2/4, M6 (b), M8) was not run.
- Nothing was written to any database.

**What was audited:** the rows stored on serving (ids 1–3), read read-only.

**Evidence** (`.agent/phase6/diagnostics/p6_m1_source_audit/`):
- the official PDFs (sha256 re-checked against `rulesets_research/sources.json`), with text extracted by pypdf;
- the official FIRST volunteer and selection documents;
- the FRC Events division pages, fetched 2026-10-07;
- TBA only for the designated mappings, read-only from the isolated `stratai_test` copy.

**Machine checks behind the tables:**

| Check | Result |
|---|---|
| (a) Every `§X … p.N` reference in the stored JSON lies within that section's pages | 26/26 |
| (b) Every single-quoted manual phrase in the stored JSON appears **verbatim** in the official PDF | all, including the T606 box and the TU19 quote. The only non-manual quotes are the FRC Events division names, checked in (e) |
| (c) Every Table 10-2 row, parsed from each manual, against the stored bracket | 13 slots + finals, 0 mismatches each season |
| (d) Team Update scan of every tournament section | the same list as the research package |
| (e) FIRST division team lists vs TBA rosters, for all 24 division keys | identical |
| (f) TBA slot mapping, re-run on current data | identical to the research evidence |

**Legend:**
- **Result:** PASS / FAIL / UNRESOLVED / N/A.
- **Basis:** **E** = explicit in the source; **I** = requires interpretation.
- **Confidence:** H / M / L.
- **Page references** are PDF pages, which equal the printed page numbers.

## 0. Integrity (R10 for all seasons)

| id | Season | Status | Stored sha256 | Content hashes to it now | Equals the committed `resolved/ruleset_<y>.json` | v3 / no markers |
|---|---|---|---|---|---|---|
| 1 | 2024 | `awaiting_review` | `cdba3adde21db30e571a6e7b0e9d4f7ecfce48d48fc927b944a3c6d95092cee2` | yes | yes | yes / yes |
| 2 | 2025 | `awaiting_review` | `befbbb87ca62b766dfc89173d955ed3e52d0b4e810ca352c6d4b294e153e40d5` | yes | yes | yes / yes |
| 3 | 2026 | `awaiting_review` | `24bd006cae59cf5498538ab5ac78c0cf902a789310ce0b4988d93ab3f3a77b6c` | yes | yes | yes / yes |

**The audited content is exactly the content that approval would approve:** `review --approve` requires that same full sha256.

## 1. 2024 CRESCENDO (id 1)

Source: [2024GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2024/Manual/2024GameManual.pdf), final PDF, sha256 `1b7e1dc3…` verified. Team Updates: [TeamUpdates-combined.pdf](https://firstfrc.blob.core.windows.net/frc2024/Manual/TeamUpdates/TeamUpdates-combined.pdf) (TU00–21).

| R | Result | Stored value | Source and location | Source text (verbatim or exact description) | Why it supports or not | Basis | Conf. |
|---|---|---|---|---|---|---|---|
| R1 | N/A (reviewer) | — | — | Your name and qualification | Not a source question | — | — |
| R2 | PASS | `manual.version`: "final consolidated PDF … Section 10 'Tournaments' V5, Section 11 V5, Section 12 V0 … TU00-21 (TU21, 2024-04-09)" | page footers; TU21 header | Footers: "Section 10 Tournaments V5", "Section 11 District Tournaments V5", "Section 12 FIRST Championship Tournament V0". TU21: "the final Team Update" | Matches. TU scan: TU04 (01-19, Table 10-3), TU13 (02-20, §10.2), TU16 (03-05, §10.6.3.1 wording), TU19 (03-26, §10.6.5), TU20 (04-02, §10.2). None changed a structured field after the first event (02-24) | E | H |
| R3 | PASS | all fields | (R4–R8, R11–R13) | — | Each field is verified in its own row | E | H |
| R4 | PASS | `alliance_counts` = [{25, null, 8}] | §10.6.1 p.121; §10.6.6 p.127 | "the top 8 ranked teams become the ALLIANCE Leads"; "Multi-day events with 24 teams or fewer employ a modified Playoff MATCH format" | 25+ teams use the standard 8. The ≤24 format is not representable (byes), so it is excluded (R9/R14). Not representable: the "multi-day" qualifier. No single-day ≤24 event exists in the data | E | H |
| R5 order | PASS | `serpentine` | §10.6.1 p.121 | "Round 1: In descending order (ALLIANCE 1 to ALLIANCE 8) … Round 2: … the selection order is reversed" | Exact | E | H |
| R5 picks | PASS | `picks_per_alliance` 2 | §10.6.1 p.121 | "each ALLIANCE Lead chooses 2 other teams … results in 8 ALLIANCES of 3 teams" | Exact | E | H |
| R5 captain | PASS | `captain_rule` `highest_ranked_available` | §10.6.1 p.121 | "the top 8 ranked teams become the ALLIANCE Leads"; "If an invitation from a top 8 ALLIANCE to another ALLIANCE Lead is accepted, all lower ALLIANCE Leads are promoted 1 spot. The highest-ranked, unselected team becomes the ALLIANCE 8 Lead"; T601 box (absent Lead: lower Leads promoted) | Rank-ordered promotion is what the label means: each seed's captain is the best-ranked team not already on an alliance | E (label mapping is direct) | H |
| R5 accept | PASS | `captain_may_accept_higher_alliance` true | §10.6.1 p.121 | the promotion sentence above presupposes a Lead accepting an invitation | Exact | E | H |
| R5 decline/pick | PASS | `declined_team_may_be_picked_later` false | §10.6.1 T602 p.121 | "T602 *Declining teams can't be picked. An ALLIANCE CAPTAIN may not invite a team that has declined another ALLIANCE'S invitation…" | Exact | E | H |
| R5 decline/captain | UNRESOLVED (correctly null) | `null` + `unresolved` note (D-PX1-4) | §10.6.1 p.121 | "An ALLIANCE Lead that declines an invitation … is able to invite teams to join their ALLIANCE"; "The highest-ranked, **unselected** team becomes the ALLIANCE 8 Lead" | A current Lead keeps captaincy (explicit). Whether a non-Lead decliner counts as "unselected" is **not defined**: ambiguous, not silent. Null is the faithful value. See package P1 | I | M |
| R5 backup | PASS | `backup_robots` true | §10.6.3 p.124; T604 p.125 | "the ALLIANCE CAPTAIN has the option to bring in the highest ranked team from the pool … composed of 4 teams"; "Each ALLIANCE is allotted 1 BACKUP TEAM coupon" | Exact | E | H |
| R6 | PASS | 13 slots + finals; rounds 1–5, finals 6; `wins_needed` 2 | §10.6.2 Table 10-2 p.123; p.122; §10.6.2.2 p.124 | Table rows M1 "Upper 8 1" … M13 "Lower W12 L11"; Finals 14–16 "W13 W11"; round markers 1@M1, 2@M5, 3@M9, 4@M11, 5@M13; "Playoff MATCHES consist of 6 rounds"; "The first ALLIANCE to win 2 MATCHES in the Finals" | Parsed table = stored (0 mismatches); finals = the 6th round | E | H |
| R7 | PASS | `semifinal` set n = MATCH n; `final` set 1 | TBA (designated) | 185/185 seeded 8-alliance events: every set's seeds and colours match | Exact | E (data) | H |
| R8 | PASS with source conflict | `tie_rule` (Table 10-3: TECH FOUL / AUTO / STAGE / replay; finals and overtime; Einstein replay; TU04 note) | §10.6.2.1 pp.123–124; §10.6.2.2 p.124; §12.4 p.138; TU04 (2024-01-19) | Final PDF 3rd criterion: "ALLIANCE STAGE points". TU04: "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points" | The text records both wordings. **No TU records the change**; informational only (D7). Package P2 | E (conflict) | M |
| R9 | PASS | unsupported rules recorded | P1/P2 decision records | M1–M8 dispositions; D-PX1-1–5 | Recorded | E | H |
| R10 | PASS | — | §0 | — | Hash integrity | E | H |
| R11 | PASS | nulls: `declined_team_may_become_captain` only, with note | — | — | Exactly the decided nulls; no markers | E | H |
| R12 | PASS | all citations | (a), (b) above | — | Every reference on its pages; every quote verbatim | E | H |
| R13 | PASS | variant `first_championship_division`: 3 picks, no backups, 8 events | §12.2 p.137 | "There is no provision for BACKUP TEAMS at the FIRST Championship … the process continues with a third round of selection … Round 3 … reversed again, with ALLIANCE 1 picking first … 8 ALLIANCES of 4 teams each" | Exact. Its other fields equal the default ("per the process as described in Section 10.6.1"). Event mapping: §6 | E | H |
| R14 | PASS | exclusions `2024isde2` (`backup_before_first_match`), `2024vapor` (`small_event_byes_not_represented`) | §5 | — | Intentional and evidenced; no others | E | H |
| R15 | N/A (pending) | — | — | Written by the CLI on approval | — | — | — |

## 2. 2025 REEFSCAPE (id 2)

Source: [2025GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/2025GameManual.pdf), sha256 `dc6aa9dd…` verified. Team Updates: [TeamUpdate-Combined.pdf](https://firstfrc.blob.core.windows.net/frc2025/Manual/TeamUpdates/TeamUpdate-Combined.pdf) (TU00–21).

| R | Result | Stored value | Source and location | Source text | Why | Basis | Conf. |
|---|---|---|---|---|---|---|---|
| R1 | N/A (reviewer) | — | — | — | — | — | — |
| R2 | PASS | "Section 10 'Tournaments (T)' V6, Section 11 V3, Section 13 V0 … TU00-21 (TU21, 2025-04-08)" | footers; TU21 | "Section 10 Tournaments (T) V6", "Section 11 District Tournaments V3", "Section 13 FIRST Championship Tournament (C) V0" | Matches. TU scan: TU01/TU02/TU14 (§10.6.1 pick timer), TU08/TU09 (§10.6.3.2 pool), TU14 (§10.2), TU19 (03-25, Table 10-3 2nd criterion). Only the free-text tie wording changed mid-season | E | H |
| R3 | PASS | all fields | — | — | — | E | H |
| R4 | PASS | [{25, null, 8}] | §10.6.1 p.123; §10.6.6 p.131 | as 2024 (identical wording) | as 2024 | E | H |
| R5 order | PASS (nominal) | `serpentine` | §10.6.1 p.124; T605 p.124 | "In round 1 selections are made in descending order (ALLIANCE 1 to ALLIANCE 8), whereas in round 2 selections are made in ascending order (ALLIANCE 8 to ALLIANCE 1)" | Exact. T605 (pick timer) can skip and revisit an alliance, which the schema cannot represent (M5, descriptive). Package P5 | E | H |
| R5 picks | PASS | 2 | §10.6.1 p.123 | "each ALLIANCE Lead chooses 2 other teams"; p.124 "This process results in 8 ALLIANCES of 3 teams" | Exact | E | H |
| R5 captain | UNRESOLVED (correctly null) | `captain_rule` `null` + `unresolved` (D-PX1-5) | §10.6.1 p.123; T601 box p.123; official 2025 documents | "the top 8 ranked teams become the ALLIANCE Leads"; absent Lead: "all lower ranked ALLIANCE Leads are promoted 1 spot". **2024's "If an invitation … to another ALLIANCE Lead is accepted …" sentence is absent** (verified by text search). Alliance Selection Changes (Rev. Sep 2024): "bringing in new Alliance Leads"; Emcee Training / Script: "Would you prefer to join or form your own Alliance?" | No public FIRST 2025 source states who fills a captain position vacated by a Lead who accepts. Not inferred from TBA. FIRST Q&A (2025): login-gated, not searched. Package P3 | E (absence) | H that it is unresolved |
| R5 accept | PASS | true | T605 box p.124 | "A valid team selection includes any team who has not yet accepted or declined an invitation to join another ALLIANCE and is not an ALLIANCE Lead that has had a pick timer violation"; "If the team accepts, it becomes a member of that ALLIANCE" | Leads are valid selections and may accept | E | H |
| R5 decline/pick | PASS | false | T606 p.125 | "An ALLIANCE CAPTAIN may not invite a team that has declined another ALLIANCE'S invitation…" | Exact | E | H |
| R5 decline/captain | UNRESOLVED (correctly null) | `null` + note | §10.6.1 p.125 | "An ALLIANCE Lead that declines … is able to invite teams to join their ALLIANCE" | Covers a current Lead only; silent otherwise. The Pick Process sheet (Rev. Feb 26, 2025): a decliner "may not be auto assigned" (picks, not captains). Package P1 | E (silence) | H |
| R5 backup | PASS | true | §10.6.3 p.128; T608 p.129 | same text as 2024 | Exact | E | H |
| R6 | PASS | as 2024 | Table 10-2 p.127; p.126; §10.6.2.2 p.128 | identical table; "consist of 6 rounds" | Parsed = stored | E | H |
| R7 | PASS | as 2024 | TBA | 198/198 events | Exact | E (data) | H |
| R8 | PASS | Table 10-3: MAJOR FOUL / LEAVE + AUTO CORAL / BARGE / replay; finals, overtime, Einstein; TU19 note | §10.6.2.1 p.128; TU19 (2025-03-25) | "2nd ALLIANCE LEAVE + AUTO CORAL points"; TU19: "to reflect how the FMS has been calculating AUTO points" (verbatim) | Matches the final text, and records the mid-season wording change, which TU19 says left FMS behaviour unchanged. Informational. Package P2 | E | H |
| R9 | PASS | recorded | — | — | — | E | H |
| R10 | PASS | — | §0 | — | — | E | H |
| R11 | PASS | nulls: `captain_rule`, `declined_team_may_become_captain`, each with a note (default and variant) | — | — | Exactly the decided nulls | E | H |
| R12 | PASS | citations | (a), (b) | — | — | E | H |
| R13 | PASS | variant: 3 picks, no backups, 8 events | §13.2 p.147 | identical wording to 2024 §12.2 | Exact; mapping §6 | E | H |
| R14 | PASS | `2025ncash` (`small_event_byes_not_represented`) | §5 | — | — | E | H |
| R15 | N/A (pending) | — | — | — | — | — | — |

## 3. 2026 REBUILT (id 3)

Source: [2026GameManual.pdf](https://firstfrc.blob.core.windows.net/frc2026/Manual/2026GameManual.pdf) "Version: TU22", sha256 `5c67300f…` verified. Team Updates: [REBUILT_TeamUpdate-Combined.pdf](https://firstfrc.blob.core.windows.net/frc2026/Manual/TeamUpdates/REBUILT_TeamUpdate-Combined.pdf) (TU01–22).

| R | Result | Stored value | Source and location | Source text | Why | Basis | Conf. |
|---|---|---|---|---|---|---|---|
| R1 | N/A (reviewer) | — | — | — | — | — | — |
| R2 | PASS | "PDF marked 'Version: TU22' (every page) … through TU22 (2026-04-21)" | cover and footers | "Version: TU22" on the cover and every section footer | Matches. TU scan: TU08 (02-06, §10.2), TU12 (02-20, Table 10-2 award-break names only). Both precede the first event (03-03). TU22 (04-21) is G211 only. The Israel events (06-28 to 07-08) ran after TU22 | E | H |
| R3 | PASS except the captain-rule interpretation (R5) | — | — | — | — | — | — |
| R4 | PASS | [{25, null, 8}] | §10.6.1 p.123; §10.6.6 p.131 | as 2024 | as 2024 | E | H |
| R5 order | PASS (nominal) | `serpentine` | §10.6.1 p.124 | as 2025 | as 2025 (T605 limit) | E | H |
| R5 picks | PASS | 2 | §10.6.1 pp.123–124 | as 2025 | Exact | E | H |
| R5 captain | **PASS by interpretation (H3)** | `captain_rule` `highest_ranked_available` (default and variant) | §10.6.1 p.123; T601 box p.124; **T606 box p.126** | Explicit: "the top 8 ranked teams become the ALLIANCE Leads"; absent Lead: "all lower ranked ALLIANCE Leads are promoted 1 spot". T606 box, **verbatim**: "When a team has declined, the team will show with a strikethrough on the team number in the audience display. Teams highlighted in orange (will become captain if not picked) will NOT get a strikethrough if they decline as they can still become captains." | T606 establishes that there is, at any moment, a team that **"will become captain if not picked"**. It does **not** state how that team is chosen (by rank or otherwise), and 2024's promotion sentence is absent. "Highest-ranked available" is an **interpretation**: consistent with the Leads being "the top 8 ranked teams" and with rank-ordered promotion of absent Leads, but not stated. Kanav chose it (H3); the citation quotes T606 verbatim, not paraphrased. Package P4 | **I** | M |
| R5 accept | PASS | true | T605 box p.125 | as 2025 | Exact | E | H |
| R5 decline/pick | PASS | false | T606 p.125 | as 2025 | Exact | E | H |
| R5 decline/captain | UNRESOLVED (correctly null) | `null` + note | §10.6.1 p.126; T606 box p.126 | a current Lead keeps captaincy; an orange-highlighted decliner "can still become captains" | Two cases are established (true). A non-highlighted decliner is not addressed: the strikethrough box may imply it is out, but does not say so. Null is faithful. Package P1 | E + I | M |
| R5 backup | PASS | true | §10.6.3 p.128; T608 p.129 | as 2025 | Exact | E | H |
| R6 | PASS | as 2024 | Table 10-2 p.127 (TU12 changed award names only); p.126; §10.6.2.2 p.128 | identical topology | Parsed = stored | E | H |
| R7 | PASS | as 2024 | TBA | 208/208 events | Exact | E (data) | H |
| R8 | PASS | Table 10-3: MAJOR FOUL / AUTO FUEL / TOWER / replay; finals, overtime, Einstein | §10.6.2.1 p.128; §10.6.2.2 p.128; §13.4 p.148 | "2nd ALLIANCE AUTO FUEL points", "3rd ALLIANCE TOWER points"; no 2026 TU touched Table 10-3 | Exact | E | H |
| R9 | PASS | recorded | — | — | — | E | H |
| R10 | PASS | — | §0 | — | — | E | H |
| R11 | PASS | null: `declined_team_may_become_captain` with note; `captain_rule` non-null (H3) | — | — | As decided | E | H |
| R12 | PASS | citations | (a), (b) | — | The H3 citation quotes T606 exactly | E | H |
| R13 | PASS | variant: 3 picks, no backups, 8 events | §13.2 p.147 | identical wording | Exact; mapping §6 | E | H |
| R14 | PASS | `2026tuak2`, `2026tuis4`, `2026mefal`, `2026txfor`, `2026txmca`, `2026isde2` | §5 | — | — | E | H |
| R15 | N/A (pending) | — | — | — | — | — | — |

## 4. Summary

| | 2024 | 2025 | 2026 |
|---|---|---|---|
| PASS, explicit | R2–R4, R5 (5 of 6 parts), R6, R7, R9–R14 | R2–R4, R5 (5 of 7 parts), R6–R14 | R2, R4, R5 (5 of 7 parts), R6–R14 |
| PASS by interpretation | — | — | R5 captain rule (H3) |
| PASS with source conflict (informational) | R8 (TU04 wording) | — | — |
| UNRESOLVED, correctly stored as null with a note | `declined_team_may_become_captain` | `captain_rule`, `declined_team_may_become_captain` | `declined_team_may_become_captain` |
| FAIL | **none** | **none** | **none** |
| N/A | R1 (reviewer), R15 (pending) | same | same |

## 5. Exclusion audit (R9/R14)

Data: read-only isolated copy (`exclusions.json`).
- **"Rows removed"** = PX-1 rows the event would contribute if it were not excluded (decided matches, members, EPA-complete).
- **"Roster rule"** = what the stored `alliance_counts` does to the event without the exclusion.

| Event | Reason | Evidence | Required? | Representable by the current schema? | Downstream effect of excluding |
|---|---|---|---|---|---|
| `2024isde2` | `backup_before_first_match` | Seed 7 lists 5554, 4590, 2212, 4416. 4416 (listed 4th) is on the field in both of the alliance's matches (sf3, sf6); 2212 (a round-2 pick) in neither. 2024 T604 p.125: "An ALLIANCE may not request a BACKUP TEAM until after their first Playoff MATCH" | Yes (D-PX1-3): no FIRST document explains it | No. The members cannot be established without interpreting TBA's list order | 30 teams, so the roster rule covers it. M1: −1 event. PX-1: 0 rows (all 15 EPA-incomplete). Not held out |
| `2024vapor` | `small_event_byes_not_represented` | 23 teams; §10.6.6 p.127 gives 7 ALLIANCES ("a 24-team event creates 7 ALLIANCES"; byes); TBA: 8 alliances, alliance 8 = 9990–9992 placeholders | Yes: byes are not representable | No (bye/placeholder schema needed) | Roster rule: not covered (23 < 25), so it is excluded either way; the exclusion only names the reason. PX-1: 0 rows |
| `2025ncash` | `small_event_byes_not_represented` | 22 teams; §10.6.6 p.131 gives 7; TBA: alliance 8 = 9991–9993 | Yes | No | Not covered either way. PX-1: 4 rows (train) not available either way |
| `2026tuak2` | `backup_before_first_match` | Seed 8 lists 9583, 10940, 9247, 10998. 10998 (4th) plays sf1 and sf7, 10940 (round-1 pick) does not; 10940 plays sf9. 2026 T608 p.129 forbids a backup before the first match | Yes (D-PX1-3) | No | Covered (33 teams). M1: −1 event. **PX-1: −10 held-out rows. PX-4/M8: −1 event** |
| `2026tuis4` | `backup_never_played` | Seed 4 lists 9427, 9519, 8151, 8042. 8042 (4th) is on the field in none of sf2, sf7, sf9, sf12. 2026 T609 p.129: "A BACKUP TEAM must be included in the LINEUP for the ALLIANCE'S next MATCH following their recruitment" | Yes (D-PX1-3) | No | Covered (29 teams). M1: −1. **PX-1: −6 held-out rows. PX-4/M8: −1 event** |
| `2026mefal` | `small_event_byes_not_represented` | 20 teams; §10.6.6 gives 6; TBA: alliances 7–8 = 9990–9995 | Yes | No | Not covered either way. PX-1: 5 rows not available either way |
| `2026txfor` | `small_event_byes_not_represented` | 24 teams; §10.6.6 gives 7; TBA: alliance 8 = 9990–9992 | Yes | No | Not covered either way. 13 rows not available either way |
| `2026txmca` | `small_event_byes_not_represented` | 18 teams; §10.6.6 gives 5; TBA: alliances 6–8 = 9991–9999 | Yes | No | Not covered either way. 9 rows not available either way |
| `2026isde2` | `alliance_count_contrary_to_10_6_6` | 24 teams, **8 real alliances** (no placeholders), contrary to §10.6.6's 7. Held 2026-06-30 to 07-01, after TU22; no FIRST document explains it | Yes | No: any roster row giving 8 at 24 teams would contradict §10.6.6 for `2026txfor` | Not covered either way. PX-1: 0 rows |

- **Exclusions that change a population:** only the D-PX1-3 anomalies (2026: −16 held-out PX-1 rows, −2 PX-4/M8 events; 2024: none).
- **Exclusions that do not:** the 6 small-event / §10.6.6 exclusions. Without them the same events fall to `not_covered`; the exclusions make the reason explicit.
- **None unintended:** no other event is excluded. Every seeded alliance lists 3 or 4 teams. Every 4-listed alliance outside the 24 Championship divisions is a T604/T608-consistent backup, apart from the 3 excluded anomalies.

## 6. Championship division mapping (R7/R13)

For all 24 keys, the stored `url` (FRC Events) lists exactly the same team numbers as TBA's qualification roster for the stored `event_key`, and TBA names the event "<Name> Division". The 8 per season are the only events where every alliance lists 4 teams; the variant mixes nothing else in.

| Season | arc | cur | dal | gal | hop | joh | mil | new |
|---|---|---|---|---|---|---|---|---|
| 2024 | ARCHIMEDES 75 = 75 | CURIE 74 = 74 | DALY 75 = 75 | GALILEO 75 = 75 | HOPPER 75 = 75 | JOHNSON 74 = 74 | MILSTEIN 75 = 75 | NEWTON 75 = 75 |
| 2025 | 75 = 75 | 76 = 76 | 75 = 75 | 75 = 75 | 75 = 75 | 75 = 75 | 75 = 75 | 75 = 75 |
| 2026 | 75 = 75 | 74 = 74 | 75 = 75 | 75 = 75 | 74 = 74 | 75 = 75 | 74 = 74 | 75 = 75 |

## 7. Categories

**A. AUTO-PASS:** everything not listed under B, in all three seasons. That is:
- R2, R4;
- serpentine order, picks, captain-may-accept, decline-cannot-be-picked, backups;
- 2024 captain rule;
- the Championship variant;
- R6, R7, R10, R11, R12, R13, R14;
- 2025 and 2026 R8;
- the null representation itself.

**B. HUMAN JUDGMENT REQUIRED:**
- P4: 2026 captain rule (interpretation of T606);
- P2: 2024 tie-rule wording conflict;
- P1: decliner captaincy, stored null in all seasons (confirm null);
- P3: 2025 captain rule (confirm null);
- P5: T605 representational limit (acknowledge).

**C. FAIL / MUST FIX: none.**

## 8. Human-review package

**P1. `declined_team_may_become_captain`: null in all seasons. Confirm null.**
- **Stored:** null, with a note (D-PX1-4).
- **Source:**
  - All seasons: a Lead who declines keeps captaincy.
  - 2026: an orange-highlighted decliner "can still become captains".
  - 2024: "The highest-ranked, unselected team becomes the ALLIANCE 8 Lead"; whether a decliner counts as "unselected" is not defined.
  - 2026: the strikethrough note may imply non-highlighted decliners are out, but does not say so.
- **My reading:** the source is ambiguous rather than silent in 2024 and 2026, and silent in 2025. No season establishes a single true/false.
- **Recommendation:** keep null. TBA has 0 declines in 2024–2026, so no validated number depends on it.
- **Your decision:** confirm null, or rule a value per season from your FRC knowledge. A ruling would be a new dated decision and a new ruleset version.

**P2. 2024 tie-rule 3rd criterion: a source conflict (informational only).**
- **Stored:** the final PDF wording "ALLIANCE STAGE points", plus a note of TU04's wording.
- **Source:**
  - TU04 (2024-01-19): "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points".
  - Final PDF p.124: "ALLIANCE STAGE points". STAGE also includes HARMONY in the point table.
  - No TU records the change.
- **Recommendation:** accept as stored. `tie_rule` is free text and affects no computation.
- **Your decision:** accept, or say which wording governed 2024 events.

**P3. 2025 `captain_rule`: null. Confirm it is unresolved.**
- **Stored:** null, with a note listing the sources searched (D-PX1-5).
- **Source:** Leads = top 8, and absent-Lead promotion, are explicit. Nothing states who replaces a Lead who **accepts** an invitation; 2024's sentence is absent. FIRST's 2025 volunteer documents confirm only that new Leads are "brought in".
- **Consequence:** P6-M1 (b) records 2025 as `captain_rule_not_established`. The draft model and engine refuse 2025. M6 (b) and M8 are 2026-only, and PX-1/2/4 don't use it.
- **Recommendation:** keep null. Change it only if you can cite a FIRST source, for example the login-gated 2025 Q&A.
- **Your decision:** confirm null.

**P4. 2026 `captain_rule = highest_ranked_available`: a stated interpretation (H3).**
- **Stored:** `highest_ranked_available`, citing §10.6.1 and the T606 box verbatim.
- **Literal source:** T606 says teams "highlighted in orange (will become captain if not picked)" can decline and still become captains. **It does not say the orange team is the highest-ranked available one**, and 2026 has no promotion-on-acceptance sentence.
- **Note:** your H3 instruction paraphrased T606 as "the highest-ranked available team becomes captain if not picked". The source does not say that, so the stored citation quotes it exactly instead.
- **Consequence:** this value lets the M8 / P6-DM1 draft model run for 2026. Null would block it. Decide on the evidence.
- **Recommendation:** I can't establish it from FIRST text alone. It is supported by "top 8 ranked teams become the ALLIANCE Leads", rank-ordered absent-Lead promotion, and the existence of a determined "will become captain" team. TBA agrees at 1,657 of 1,664 2026 alliances, but data is not a rule.
- **Your decision:** as the domain reviewer, accept the interpretation (keep), or reject it, which would mean a new version with null.

**P5. T605 pick timer (2025, 2026): a representational limit, no value at issue.**
- **Stored:** `order` = `serpentine`, which is literally correct for the nominal order.
- **Source:** a skipped alliance is revisited later, or auto-assigned "the next highest-ranked unselected team". The schema cannot represent this (M5, descriptive).
- **Your decision:** acknowledge.

## 9. Decisions you need to make

1. **P4:** accept or reject the 2026 captain-rule interpretation.
2. **P1:** confirm `declined_team_may_become_captain` = null for 2024, 2025 and 2026.
3. **P3:** confirm 2025 `captain_rule` = null.
4. **P2:** accept the 2024 tie-rule text as stored.
5. **P5:** acknowledge the T605 limit.

If you accept all five, nothing needs to change, and the three stored rulesets can be approved as audited, by sha256. Rejecting P4, or ruling on P1 or P3, means a new ruleset version: draft, submit, review.

**R1 (your identity and qualification) and R15 (the approval record) are yours by definition.**
