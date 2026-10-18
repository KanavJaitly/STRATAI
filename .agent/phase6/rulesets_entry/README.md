# P6-M1 human-entry package: 2024, 2025, 2026 rulesets (schema `p6-ruleset-v3`)

**Prepared 2026-10-06 by Claude. Status: not entered, not submitted, not approved.**
- **What it is:** a pre-filled entry form per season, built from the official-FIRST research package (`.agent/phase6/rulesets_research/`, unchanged) and Kanav's dated decisions (`.agent/phase6/decisions/P6_M1_P1_SCHEMA_V2.md`, `P6_PX1_COMPOSITION_DECISIONS.md`).
- **Not human-verified:** a person verifies every value against its cited source, decides every `HUMAN_DECISION(...)` marker and enters it under their own name.
- **Approval:** a named, qualified human FRC-domain reviewer approves after independently verifying the stored ruleset against the authoritative FIRST sources (R1–R15). The reviewer may also be the author (review control of 2026-10-07, `.agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md`).

**Current state: implementation complete; validation not run; P6-M1 human approval required.**

## Files

| File | Use |
|---|---|
| `entry_2024.json`, `entry_2025.json`, `entry_2026.json` | The form to enter, in the exact v3 field format. Each is **refused by the schema as delivered**: every `HUMAN_DECISION(...)` string is invalid until a person replaces it |
| `entry_2024.md`, `entry_2025.md`, `entry_2026.md` | One row per field: proposed value, source or citation, status (**ESTABLISHED** by FIRST / **DECIDED** / **HUMAN DECISION**), and the downstream behaviour that depends on it |
| `small_events.json` | The small-event exclusion entries, per season, for option O1 |
| `APPROVAL_RECORD_TEMPLATE.md` | The record the reviewer completes after approval, including the full approved sha256 |

## The remaining human decisions (nothing else is open)

| ID | Seasons | Marker in the form | Options | Depends on it |
|---|---|---|---|---|
| **H1 Small events** | all | `HUMAN_DECISION(SMALL_EVENTS)` in `event_exclusions` | **O1:** paste the season's entries from `small_events.json` (explicit reason per event). **O2:** delete the marker (counted as `not_covered`). Byes cannot be represented either way (M3) | P6-M1 (a) exclusion counts. The events are never modelled under either option. 2024: 1 event; 2025: 1; 2026: 4 (3 placeholder events plus `2026isde2`) |
| **H2 Round convention (D3)** | all | `HUMAN_DECISION(D3_ROUNDS): proposed n` in every `round` | Confirm the manual's labels (1–5, finals 6), or another convention applied **identically** in all three seasons | PX-1's round-interaction features (pooled 2024–2025) |
| **H3 2026 `captain_rule`** | 2026 | `HUMAN_DECISION(2026_CAPTAIN_RULE)` in the default **and** the variant | (a) `highest_ranked_available` (§10.6.1 plus the T606 "will become captain if not picked" box), or (b) `null` with an `unresolved` entry | P6-M1 (b) for 2026. Under (b), the draft model and engine refuse 2026, so **P6-M8 / P6-DM1 cannot run**. Decide on the evidence, not on that consequence |

**Reviewer confirmations, which are checks rather than decisions:**
- each division event key matches its FRC Events page;
- the manual version strings;
- the 2024 tie-rule wording caveat (TU04);
- the 2025 TU19 note.

**Already decided, not open:**
- `declined_team_may_become_captain` = `true` in all seasons (HD-1, 2026-10-08; supersedes D-PX1-4's null; `.agent/phase6/decisions/P6_M1_HUMAN_DECISIONS_2026-10-08.md`);
- 2025 `captain_rule` = `null` (D-PX1-5; HD-2 recorded, still unresolved);
- 2026 `captain_rule` = `highest_ranked_available` (H3, confirmed by HD-3); 2024 tie-rule wording (HD-4); the pick timer is out of scope (HD-5);
- **v2 forms with these decisions:** `resolved_v2/ruleset_<season>.json` (prepared; not stored, not approved);
- the Championship variant (P1; 3 picks, no backups);
- the three anomaly exclusions (D-PX1-3);
- C1/C2.

## Workflow (exact commands)

**Prerequisite (Kanav):** apply migration 0011 to serving, with explicit approval.
- Follow the steps in `P6_M1_HUMAN_INPUT_GUIDE.md` §7: back up, confirm serving ends at 0010, check out `phase6/build`, then `python database/migrate.py` with `DATABASE_URL` set to serving.
- The rulesets are stored in serving; the isolated test copy is cloned from it.
- **Nothing in this package writes to any database.**

For each season, the author (one named person) does:
1. Copy `entry_<season>.json` to a working file. Resolve every `HUMAN_DECISION` (H1–H3), using the entry sheet.
2. Verify every value against the cited page of the official PDF. Check each PDF's sha256 against `.agent/phase6/rulesets_research/sources.json`.
3. Run `python -m scripts.phase6_rulesets draft --file <working file> --by "<Author Full Name>"`. Schema errors print with field paths; a remaining marker is one of them.
4. Run `python -m scripts.phase6_rulesets submit --id <id>`.

Then the reviewer, a named, qualified human FRC-domain reviewer (who may be the author), does:
1. Run the checklist in `P6_M1_HUMAN_INPUT_GUIDE.md` §5 against the **stored** JSON (read-only), not the author's file.
2. Copy `review_checklist_template.json` and set each item `true` only when verified. Then run `python -m scripts.phase6_rulesets review --id <id> --reviewer "<Full Name>" --approve --qualification "<qualification>" --checklist <file> --sha256 <full stored sha256>`, or `--return --note "<what to fix>"`. The CLI writes the approval record JSON.
3. Record the approval with `APPROVAL_RECORD_TEMPLATE.md`, including the full approved sha256. Commit it.

## The gate that unblocks validation

`scripts/phase6_playoff_track.py` calls `require_rulesets`. That passes only when **the database the runner reads holds an `approved` ruleset for each of 2024, 2025 and 2026**:
- the table exists (migration 0011);
- each stored JSON re-validates under `p6-ruleset-v3`;
- each JSON matches its stored sha256 (`approved_ruleset`).

The runner reads only an isolated `stratai_test` copy. After all three approvals on serving:

```
python -m scripts.phase5_isolated_db --name stratai_test --replace      # fresh clone of serving, now with the approved rulesets
export DATABASE_URL=$(python -m scripts.phase5_isolated_db --name stratai_test --print-url-env)
python -m scripts.phase6_playoff_track m1                                # P6-M1 (a)/(b) record, then m2, m3, m5, m6b (m8 needs its pre-run record and a named mentor)
```

Until then, every run prints `BLOCKED: no approved P6-M1 ruleset for [...]` and writes nothing. That was verified on 2026-10-06.
