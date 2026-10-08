# R1–R15 review package: v2 rulesets (2024, 2025, 2026)

**The checklists:** `review_<season>.json`. An item is `true` **only** where a committed audit or test already establishes it. **R1, R10 and R15 are `false`.** They depend on your own actions, and the CLI refuses approval until you set them `true`.

| Season | File | Expected v2 sha256 |
|---|---|---|
| 2024 | `resolved_v2/ruleset_2024.json` | `6b3d221227090d4378ef6a6778de70ced410822412a35daa72bcf0c590902971` |
| 2025 | `resolved_v2/ruleset_2025.json` | `0ad72856f82dd1abe9d149d27a76124cbec7916d4e97a30645a772b5020f8d7e` |
| 2026 | `resolved_v2/ruleset_2026.json` | `7695b4a9f0058a0aff3007ac35939bbb075f5afa2757b4635ce3284a6d66a930` |

**Sources of the evidence:**
- **SA:** `decisions/P6_M1_SOURCE_AUDIT.md` (`330d7af`), on the v1 content. v2 changes only the fields listed in HD.
- **HD:** `decisions/P6_M1_HUMAN_DECISIONS_2026-10-08.md`, your dated decisions.
- **HA:** `decisions/P6_M1_HD_AUDIT_2026-10-08.md` (`cebbe5a`, applied in `a133fbc`).
- **T:** `tests/test_phase6_ruleset_entry.py`, which pins v2 = v1 apart from the decided fields.

| Item | Status | Evidence |
|---|---|---|
| R1 identity and qualification | **false: yours** | State your name and qualification accurately |
| R2 documents, Team Update precedence | true | SA §1–3 R2 (PDF hashes, footers, full Team Update scan) |
| R3 every value | true | SA (every v1 value); HA (the changed fields); T (no other change) |
| R4 alliance counts | true | SA R4 (25+ → 8; small events excluded) |
| R5 selection behaviour | true | SA R5 (explicit items). HD-1 (decline → may become captain; your interpretation, labelled). HD-2 / HD-3. 2025 `captain_rule` null |
| R6 bracket and rounds | true | SA R6 (Table 10-2 parsed = stored, 0 mismatches, all seasons) |
| R7 TBA mapping | true | SA R7 (fresh re-run: 185, 198, 208 events, all sets match) |
| R8 tie rule | true | SA R8; HD-4 (2024 wordings compatible; both cited) |
| R9 unsupported rules recorded | true | SA R9 / §5 |
| R10 stored content | **false: yours** | After `draft`, confirm the stored sha256 equals the table above (step 5 of the command list) |
| R11 populated or explicitly unresolved | true | T (no `HUMAN_DECISION(` markers; the only null is 2025 `captain_rule`, with its note) |
| R12 citations | true | SA (a)/(b) (every reference in range, quotes verbatim); HA §6 (new 2026 quotes verbatim); the HD quotes were checked verbatim at `245aa2e` |
| R13 Championship variants | true | SA §6 (all 24 division keys: FIRST team list = TBA roster) |
| R14 exclusions intentional | true | SA §5 (9 exclusions, each required and evidenced) |
| R15 approval recorded | **false: yours** | Set `true` when you approve. The CLI writes `P6_M1_APPROVAL_<season>_v2.json`; commit it |
