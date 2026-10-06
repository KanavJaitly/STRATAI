# 2025 REEFSCAPE: P6-M1 entry sheet (schema `p6-ruleset-v3`)

**Form:** `entry_2025.json`. It is prepared from the research package; nothing in it is human-verified.
- Every `HUMAN_DECISION(...)` string in it is refused by the schema, so the form cannot be stored until a person decides it.
- **Status legend:**
  - **ESTABLISHED** by FIRST: transcribed from the cited official document; the reviewer verifies it.
  - **DECIDED** (Kanav, 2026-10-06): a dated decision already recorded.
  - **HUMAN DECISION**: a person decides.

## 1. Season default (`selection`)

| Field | Proposed value | Source / citation | Status | Downstream behaviour that depends on it |
|---|---|---|---|---|
| `season`, `game_name` | 2025, REEFSCAPE | manual cover and §1 | **ESTABLISHED** by FIRST | provenance |
| `manual.title`, `manual.version` | as in the form (section versions and final Team Update) | page footers; Team Update headers (research `citations_2025.md`) | **ESTABLISHED** by FIRST | provenance; the reviewer confirms D1 (no structured field changed mid-season) |
| `alliance_counts` | one row: `min_teams` 25, `max_teams` null, `alliances` 8 | §10.6.1 (8 ALLIANCES); §10.6.6 (24 teams or fewer use a modified format) | **ESTABLISHED** by FIRST | P6-M1 (a): `alliances_for(team count)`. A roster under 25 is not covered unless excluded (§4) |
| `selection.order` | `serpentine` | §10.6.1 (rounds 1→8 then 8→1) ; T605 pick timer can reorder actual picks (M5, descriptive) | **ESTABLISHED** by FIRST | turn order: draft model, M6 (b), M8 |
| `selection.picks_per_alliance` | `2` | §10.6.1: 'each ALLIANCE Lead chooses 2 other teams' | **ESTABLISHED** by FIRST | selection-time members (PX-1, M6/M7 baseline, PX-4, M8 composition) and turn order |
| `selection.captain_rule` | `null` + `unresolved` entry (in the form) | D-PX1-5; sources searched listed in the note and in `P6_PX1_COMPOSITION_DECISIONS.md` §2 | **DECIDED** (Kanav, 2026-10-06) (D-PX1-5) | P6-M1 (b) captain check; draft model and engine. **`null` means P6-M1 (b) records `captain_rule_not_established`, and the draft model and engine raise `not_established` for every 2025 event**. M6 (b) and PX-1/2/4 do not use it |
| `selection.captain_may_accept_higher_alliance` | `true` | §10.6.1 T605 box: a valid selection includes an ALLIANCE Lead without a pick-timer violation; Alliance Selection Script: "Would you prefer to join or form your own Alliance?" | **ESTABLISHED** by FIRST | draft model (`false` would be refused as `not_supported`) |
| `selection.declined_team_may_be_picked_later` | `false` | §10.6.1 T606: 'An ALLIANCE CAPTAIN may not invite a team that has declined' | **ESTABLISHED** by FIRST | pick availability in drafts. TBA records 0 declines, so no historical effect |
| `selection.declined_team_may_become_captain` | `null` + `unresolved` entry (in the form) | D-PX1-4; the note states what §10.6.1 does and does not establish | **DECIDED** (Kanav, 2026-10-06) (D-PX1-4) | `not_established` only where a declined team would be the next captain (0 declines in 2024–2026, so no historical run changes) |
| `selection.backup_robots` | `true` | §10.6.3: BACKUP TEAMS; 1 coupon per ALLIANCE | **ESTABLISHED** by FIRST | `selection_members`: one extra listed team is a backup (never a member); any other extra listing is refused |
| `selection.unresolved` | the entries in the form | as above | **DECIDED** (Kanav, 2026-10-06) | the schema requires exactly one entry per `null` |
| `selection.citation` | as in the form | §10.6.1, §10.6.3, §13.2 p.147 | **ESTABLISHED** by FIRST | provenance |

## 2. FIRST Championship division variant (`selection_variants[0]`, name `first_championship_division`)

| Field | Proposed value | Source / citation | Status | Downstream |
|---|---|---|---|---|
| `selection.picks_per_alliance` | `3` | §13.2 p.147: 'the process continues with a third round of selection ... This process results in 8 ALLIANCES of 4 teams each' | **ESTABLISHED** by FIRST | members = 4. **PX-1 excludes these rows (`four_member_alliance`, D-PX1-2)**. M6 (b) turn order has 3 rounds |
| `selection.backup_robots` | `false` | §13.2 p.147: 'There is no provision for BACKUP TEAMS at the FIRST Championship' | **ESTABLISHED** by FIRST | an extra listed team is refused |
| `selection.order` | `serpentine` | §13.2 p.147: Round 3 'reversed again, with ALLIANCE 1 picking first' | **ESTABLISHED** by FIRST | turn order 1→8, 8→1, 1→8 |
| other selection fields, `unresolved` | **identical to the season default** | §13.2 p.147: 'ALLIANCES are selected per the process as described in section 10.6.1' | as §1 | as §1 |
| `events[]`: `2025arc` | url https://frc-events.firstinspires.org/2025/ARCHIMEDES; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025arc` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025cur` | url https://frc-events.firstinspires.org/2025/CURIE; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025cur` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025dal` | url https://frc-events.firstinspires.org/2025/DALY; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025dal` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025gal` | url https://frc-events.firstinspires.org/2025/GALILEO; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025gal` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025hop` | url https://frc-events.firstinspires.org/2025/HOPPER; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025hop` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025joh` | url https://frc-events.firstinspires.org/2025/JOHNSON; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025joh` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025mil` | url https://frc-events.firstinspires.org/2025/MILSTEIN; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025mil` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |
| `events[]`: `2025new` | url https://frc-events.firstinspires.org/2025/NEWTON; section §13.2 p.147; team_update `null` | FRC Events page verified 2026-10-06 (HTTP 200; shows the division of the FIRST Championship); TBA names `2025new` the same division | **ESTABLISHED** by FIRST; the reviewer confirms the key-to-division match | as the variant |

## 3. Unresolved and decided-null fields

- `declined_team_may_become_captain`: `null` (D-PX1-4). Default and variant.
- `captain_rule`: `null` (D-PX1-5). Default and variant

## 4. Event exclusions (`event_exclusions`)

| Event | Reason code | Status | Downstream |
|---|---|---|---|

**Small events: **HUMAN DECISION** (the `HUMAN_DECISION(SMALL_EVENTS)` marker in the form).**

§10.6.6 gives multi-day events of 24 teams or fewer floor((teams − 1) / 3) ALLIANCES, with byes. The schema cannot represent byes or TBA's placeholder alliances (M3):
- each alliance count needs its own bracket;
- seeds must be ≤ the alliance count;
- the 'multi-day' condition has no field.

So no small-count row can be transcribed faithfully. Events affected this season (`small_events.json`):

- `2025ncash` (`small_event_byes_not_represented`): 22 qualification teams: §10.6.6 gives 7 ALLIANCES with byes; TBA records 8 alliances, alliance 8 made of placeholder teams 9991-9993 with recorded 'bye' results (mismatch M3).

**Options (choose one, record it dated):**
- **O1, explicit:** paste this season's entries from `small_events.json` into `event_exclusions`. Each event is excluded and counted under its own reason.
- **O2, generic:** delete the marker. These events are then refused by the roster rule and counted as `not_represented:not_covered` (the bracket check sees fewer than 25 teams).
- **Either way:** they are excluded and counted, never modelled. Representing them would need a further schema change (bye/placeholder support), which is not approved.
- **Do not** add small-count `alliance_counts` rows: each would need a bracket, and byes cannot be expressed.

## 5. Bracket (`brackets[0]`, 8 alliances) and tie rule

| Field | Proposed value | Source | Status | Downstream |
|---|---|---|---|---|
| `slots` M1–M13: `competition_level`, `set_number`, `red` / `blue` sources | as in the form | §10.6.2 Table 10-2. TBA `semifinal` set n = MATCH n at every seeded event (research README §3) | **ESTABLISHED** by FIRST + TBA-verified | P6-M1 (a) reproduction; PX-3/PX-4 simulation; PX-1 round lookup |
| `finals`: `final` set 1, `wins_needed` 2, red W(M11), blue W(M13) | as in the form | §10.6.2 Table 10-2; §10.6.2.2 | **ESTABLISHED** by FIRST | as above |
| `slots[].round`, `finals.round` | **`HUMAN_DECISION(D3_ROUNDS)`**; proposed the manual's labels: M1–4 = 1, M5–8 = 2, M9–10 = 3, M11–12 = 4, M13 = 5, finals = 6 | Table 10-2 'Round' column; 'Playoff MATCHES consist of 6 rounds' | **HUMAN DECISION** (D3) | **PX-1 features:** round-interaction terms, pooled over 2024–2025. The convention **must be identical in all three seasons** |
| `tie_rule` | as in the form | §10.6.2.1 Table 10-3; §10.6.2.2; TU19 (2025-03-25) wording change | **ESTABLISHED** by FIRST (free text) | informational only |

