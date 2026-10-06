# P6-M1 — human entry and review of the 2024, 2025 and 2026 rulesets

Revised 2026-10-05.
- **What this is:** preparation only. No ruleset has been entered, submitted or approved. A person enters every value from the official documents, and a different named reviewer verifies it.
- **Workflow change (Kanav, 2026-10-05):** Claude researched the official FIRST Game Manuals and Team Updates and prepared a cited research draft for each season: `.agent/phase6/rulesets_research/` (start with its `README.md`).
  - The draft is **input to a person's verification, not a substitute**. Nothing in it is human-verified, and it was not stored anywhere.
  - Each draft fails schema validation while any value is `UNRESOLVED`.
  - It answers D1–D7 with evidence. **It reports schema mismatches that need your decision before entry:** D5 (M1) and small events (M3).
  - §2 below is superseded by the package's document list (official URLs and sha256s).
- **What it is based on:** the actual implementation, `data/rulesets.py` (schema and workflow), `scripts/phase6_rulesets.py` (CLI) and `database/migrations/0011_phase6_season_rulesets.sql`. Data facts quoted below come from the isolated copy of the canonical TBA data (read-only). They are observations, not rules.

## 1. Readiness verdict

**The workflow is functional.**
- The schema validation, the draft → submit → review → approve lifecycle, refusal of self-approval and sha256 verification on read are implemented. They are tested on the isolated copy (`tests/test_phase6_rulesets.py`).
- The CLI `template` command works.

**Six usability problems are documented below.** U1 is fixed (commit `c8b7b7a`, 2026-10-05): every template value is now a blank placeholder that fails validation, with regression tests. U2–U6 are documented, not fixed.

| ID | Problem | Effect | Proposed remedy (needs your approval; not a methodology change) |
|---|---|---|---|
| **U1 (FIXED, `c8b7b7a`)** | Before the fix, `template` **pre-filled rule values**: `captain_may_accept_higher_alliance: true`, `declined_team_may_be_picked_later: false`, `declined_team_may_become_captain: true`, `backup_robots: true`. `order` and `captain_rule` are also pre-filled, but each is the schema's only allowed value. | A value left untouched passes validation, so an un-transcribed (software-supplied) rule could enter a ruleset | Make the template emit `null` for every rule value, so validation fails until a person enters each one |
| U2 | No CLI command shows a stored ruleset; `list` shows only id, season, version, status, author, reviewer and sha prefix | The reviewer must see exactly what was stored, not only the author's file | Add a read-only `show --id` command that prints the stored JSON and its sha256. Until then, the reviewer reads `season_rulesets.ruleset_json` directly, read-only |
| U3 | Self-approval is refused by comparing names as stripped strings, case-sensitively. It is not an identity check (the Phase 5 convention: names are recorded, not authenticated) | "Kanav" and "kanav" would count as different people | Procedural: use each person's full name, written identically every time. A real identity check would be a separate decision |
| U4 | `alliance_counts` ranges are not checked for overlap, gaps, or `max_teams ≥ min_teams`. `alliances_for` takes the **first** matching rule | An entry error could silently pick the wrong rule. A gap yields `not_covered`, and the event is excluded and counted | The reviewer checks it manually (reviewer checklist R4) |
| U5 | `round` is only required to be ≥ 1. There is no check of ordering or consistency, and the finals round is not required to exceed the slot rounds | PX-1 uses rounds as categorical interactions **pooled across 2024–2025**, so inconsistent numbering across seasons would silently change the model's inputs | Your decision D3 below, plus reviewer check R6 |
| U6 | No structured field records Team Updates or effective dates. The only places are `manual.version` and each free-text `citation` | Team Update precedence can be recorded only in text | Decision D1 below. Record Team Updates inside `manual.version` and each affected `citation` |

## 2. Official documents to provide (none is in the repository)

There is no game manual in the repository, the artifact store, or `game_manuals` (0 rows on serving).

| Season | Game | Provide |
|---|---|---|
| 2024 | CRESCENDO | the official FRC Game Manual, in the version in force at the season's official events, **and every Team Update** that amended alliance selection, playoffs, the bracket, tiebreakers or backup robots |
| 2025 | REEFSCAPE | the same |
| 2026 | REBUILT | the same |

Also have TBA available for at least one real event per season, to verify the level and set-number mapping (D2).

**Optional:** upload each manual through the Phase 5 web app's Game manual page. That keeps the PDF write-once with its sha256 as provenance, and serving already has migration 0010.

## 3. Field checklist (identical for each season)

The section numbers are **not** given here. Read them from the manual you provide; "the section defining …" says what to look for.

**Every object forbids extra fields** (`extra=forbid`), so a misspelled field name is rejected.

| Field | Meaning | Required | Cite | Manual or Team Update | Human judgment? | Software validation |
|---|---|---|---|---|---|---|
| `schema_version` | schema id | optional (defaults `p6-ruleset-v1`) | — | — | no | must equal `p6-ruleset-v1` |
| `season` | the season year | required | — | manual cover | no | integer ≥ 1992 |
| `game_name` | the game's name | required | — | manual cover | no | non-empty |
| `manual.title` | exact manual title | required | — | manual | no | non-empty |
| `manual.version` | the manual version used, **plus any Team Updates applied** (U6) | required | — | manual + Team Updates | **yes (D1)** | non-empty |
| `alliance_counts[]` | rules mapping roster size → number of playoff alliances | required (≥ 1 rule) | the section defining the number of alliances | manual (or a Team Update if amended) | **yes (D4)** | ≥ 1 item; each item below |
| `alliance_counts[].min_teams` | smallest roster this rule covers | required | same | same | D4 | integer ≥ 1 (overlap and gaps not checked: U4) |
| `alliance_counts[].max_teams` | largest roster, or `null` for no upper bound | required (may be `null`) | same | same | D4 | `null` or integer ≥ 1 |
| `alliance_counts[].alliances` | alliances for that range | required | same | same | no | integer ≥ 2; **a bracket must exist for every value used** |
| `alliance_counts[].citation` | where this rule is stated | required | the section | — | no | non-empty |
| `selection.order` | draft order | required | the alliance-selection section | manual / Team Update | **yes (D5)** if the manual's order is not serpentine | must be `serpentine` (nothing else is representable) |
| `selection.picks_per_alliance` | picks after the captain | required | the alliance-selection section | manual / Team Update | **yes (D5)**: one value per season | integer ≥ 1 |
| `selection.captain_rule` | how captains are determined | required | the alliance-selection section | manual | **yes (D5)** if it differs | must be `highest_ranked_available` |
| `selection.captain_may_accept_higher_alliance` | may a would-be captain join a higher alliance? | required | the alliance-selection section | manual / Team Update | no (transcribe) | boolean. **`false` is accepted by the schema but refused by the draft model** (P6-M6/M8 `not_supported`) |
| `selection.declined_team_may_be_picked_later` | after declining, can a team be picked later? | required | the decline rule | manual / Team Update | no | boolean |
| `selection.declined_team_may_become_captain` | after declining, can a team still become captain? | required | the decline rule | manual / Team Update | no | boolean |
| `selection.backup_robots` | does the format use backup robots? | required | the backup-robot section | manual / Team Update | **yes (D5)** | boolean. Recorded, not modelled |
| `selection.citation` | the section(s) for all selection fields | required | — | — | no | non-empty, **one citation for all selection fields** |
| `selection_variants[]` | **schema v2 (P1, 2026-10-05):** a complete alternative `selection` for explicitly listed events only, e.g. FIRST Championship divisions (3 picks, no backups) | required key; `[]` when every event uses the default | the section establishing the alternative structure (e.g. 2024 §12.2; 2025/2026 §13.2) | manual / Team Update | **D5 (decided: P1)** | unique `name`; a complete `selection`; ≥ 1 event; must differ from the default (citation aside) |
| `selection_variants[].events[]` | each event the variant governs, with its provenance: `event_key`, `rule`, `document`, `version`, `team_update` (a named update, or an explicit `null`), `section`, `url` | required, every field | the FIRST source establishing that the event is governed by the variant (e.g. FIRST's Championship division list) | FIRST only | no (transcribe) | `event_key` of this season; in at most one variant; `url` an https FIRST URL (`firstinspires.org` or `firstfrc.blob.core.windows.net`). **Never inferred from `events.event_type` (NULL) or from data** |
| `event_exclusions[]` | events the ruleset cannot represent faithfully: unexplained recorded behaviour (e.g. the three backup anomalies) or a FIRST rule the schema cannot express (e.g. §10.6.6 small-event byes) | required key; `[]` when none | the research finding | research + TBA | **yes**: every exclusion is a dated decision | `event_key` of this season, at most once; `reason` a lower_snake_case code; non-empty `finding`. `for_event` refuses an excluded event; P6-M1 counts it under its reason |
| `selection.unresolved[]` (schema v3) | why `captain_rule` or `declined_team_may_become_captain` is `null`: the rule is **not established** by an authoritative FIRST source (D-PX1-4/5, 2026-10-06) | required key; `[]` when both are established | the sources searched | FIRST only | **yes**: a `null` is a recorded finding, never a default | each `null` needs exactly one entry (`field`, `note`, `sources_checked`), and an entry needs a `null`. Only these two fields may be `null`. **2025 `captain_rule`: `null`** (sources in `.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md` §2). **`declined_team_may_become_captain`: `null`** in every season unless a FIRST source establishes it |
| `event_exclusions[]` **entry instruction (D-PX1-3)** | `2024isde2`, `2026tuak2`, `2026tuis4`: unresolved backup behaviour | list them in the 2024 and 2026 rulesets unless an authoritative FIRST document resolves them | the research finding (`P6_M1_P1_SCHEMA_V2.md` §5) | research + TBA | no: decided | reason codes, e.g. `backup_before_first_match`, `backup_never_played` |
| `brackets[]` | one bracket per alliance count used | required (≥ 1) | the playoff tournament section and its bracket diagram | manual / Team Update | D4 | one format per alliance count; each count in `alliance_counts` must have one |
| `brackets[].alliances` | the alliance count this bracket serves | required | same | same | no | integer ≥ 2 |
| `brackets[].slots[]` | every playoff match before the finals | required (≥ 1) | same | same | **yes (D2, D3)** | slot names unique; (level, set) pairs unique; every seed 1…N enters exactly once; sources only from **earlier** slots; no winner or loser routed twice |
| `slots[].slot` | your label for the match (e.g. the manual's match name) | required | — | — | yes (naming only) | non-empty, unique |
| `slots[].competition_level` | **TBA's** level for this match | required | TBA match keys (not the manual) | TBA | **yes (D2)** | one of `semifinal`, `quarterfinal`, `eighthfinal` |
| `slots[].set_number` | **TBA's** set number for this match | required | TBA match keys | TBA | **yes (D2)** | integer ≥ 1 |
| `slots[].round` | the match's round | required | the bracket diagram | manual | **yes (D3)** | integer ≥ 1 (no other check: U5) |
| `slots[].red` / `.blue` | where each side comes from: `{"kind": "seed", "seed": n}` or `{"kind": "winner"\|"loser", "slot": "<earlier slot>"}` | required | the bracket diagram | manual / Team Update | no (transcribe) | a seed source names a seed (≤ alliances); a winner/loser source names an earlier slot |
| `slots[].citation` | where this slot is defined | required | the section and diagram | — | no | non-empty |
| `brackets[].finals.competition_level` | TBA's finals level | optional (defaults `final`) | — | TBA | no | must be `final` |
| `brackets[].finals.set_number` | TBA's finals set number | required | TBA match keys | TBA | **yes (D2)** | integer ≥ 1 |
| `brackets[].finals.round` | the finals round | required | the bracket diagram | manual | **yes (D3)** | integer ≥ 1 |
| `brackets[].finals.wins_needed` | wins to take the finals (best-of-N → (N + 1) / 2) | required | the finals section | manual / Team Update | no | integer ≥ 1 |
| `brackets[].finals.red` / `.blue` | where the finalists come from | required | the bracket diagram | manual | no | must be winner/loser sources from earlier slots (no seed sources) |
| `brackets[].finals.citation` | where the finals are defined | required | — | — | no | non-empty |
| `tie_rule` | how a tied playoff match is resolved, **including its section** | required | the playoff tiebreaker section | manual / Team Update | no | non-empty free text. **Informational:** no computation reads it. Replays are handled by taking a slot's last decided match |

## 4. Decisions you must make (not transcription)

| ID | What the frozen schema permits | Where the ambiguity occurs | Your decision | Downstream |
|---|---|---|---|---|
| **D1 Mid-season rule changes** | One `SeasonRuleset` per season. Versions exist, but **only the currently approved version is served, and it applies to every event of the season**: there is no effective date. Approving a new version supersedes the old one for all events | A Team Update that changes selection, bracket or tie rules partway through a season | (a) transcribe the rules in force for most or all official events and accept that events under other rules fail reproduction and are excluded and counted; or (b) treat the season as unsupported if the change matters; or (c) authorize a schema change (an effective-date field). (c) is a schema and methodology change and needs a dated decision. **Record which Team Updates are reflected, in `manual.version` and the citations** | P6-M1 (a) and (b); PX-1 (rounds and slot mapping); PX-3/PX-4 (bracket); P6-M6 (b) and P6-M8 (selection rules) |
| **D2 Match numbering** | Slots are keyed by **TBA's** (`competition_level`, `set_number`). The manual's own match numbering is not stored, except as the free-text `slot` label | Every slot and the finals: you must establish which TBA (level, set) corresponds to each match in the manual's bracket | Establish the mapping from TBA's actual match keys, not from memory or the manual alone. **Data facts:** in 2024–2026 TBA uses only `semifinal` sets 1–13 and `final` set 1 (finals up to 4 match numbers). Whether set n is the manual's match n must be verified, not assumed | P6-M1 (a) reproduction, which detects mapping errors; PX-1 rounds; PX-3/PX-4; P6-M8 |
| **D3 Round numbering** | `round` is any integer ≥ 1 per slot and for the finals | What counts as a "round" (the manual's round labels, or another convention), and **consistency across 2024, 2025 and 2026** | One round convention used identically in all three seasons. PX-1 pools 2024–2025 and treats each round number as its own category, so if "round 3" means different things in different seasons, its interactions are not comparable | PX-1 features (frozen P6-Q2 interaction design); PX-3 (the round is passed to the probability function) |
| **D4 Smaller alliance counts** | `alliance_counts` maps roster ranges to alliance counts, and **every count listed needs its own bracket** | Whether, and how, to transcribe the manual's rules for small events | **Data facts:** every 2024–2026 event with other than 8 alliances is an unseeded division-champion event (each season: `micmp` with 4; `necmp`, `oncmp`, `txcmp` with 2). These are excluded by P6-Q2 regardless. Every seeded event has 8 alliances. So: transcribe the roster rule as the manual states it; if it defines other alliance counts, either transcribe their brackets too, or omit those counts and accept that matching events are counted `not_covered` | P6-M1 (a): an alliance-count mismatch means the event is excluded and counted |
| **D5 Four-team alliances and backups** | **One** `picks_per_alliance` per season, and `backup_robots` is a boolean only | **Data fact:** TBA's `picks` list holds **4 teams** for some alliances at 104 (2024), 100 (2025) and 126 (2026) **seeded** events, while TBA's `backup` field is null for every alliance. What the fourth listed team is must be established from the manual (and TBA), not inferred | (a) the meaning of a fourth listed team in each season; (b) the single `picks_per_alliance` value to transcribe; (c) whether events whose alliances do not match it are treated as unsupported for the draft-model checks (P6-M6 (b), P6-M8) and excluded and counted. **Note for the frozen PX-1 spec:** composition sums run over the alliance's listed picks, so a listed fourth team enters PX-1's inputs | P6-M1 (b) (captain and first pick only); P6-M6 (b) and P6-M8 (turn order uses `picks_per_alliance`); PX-1 inputs |
| **D5 decision (Kanav, 2026-10-05): P1** | Schema v2 adds `selection_variants` (explicit, cited event keys) and `event_exclusions`. The season `selection` is the standard-event default | See `.agent/phase6/decisions/P6_M1_P1_SCHEMA_V2.md` | The PX-1 composition question (a listed backup or round-3 pick enters PX-1's sums) is **open and STOPPED** there; it is not a P6-M1 entry question | PX-1, PX-4, P6-M8 |
| **D6 Unsupported rules** | Representable: serpentine order; highest-ranked-available captains; captains may join higher alliances; slot graphs over `semifinal`/`quarterfinal`/`eighthfinal` plus a best-of-N `final`; seeds entering at any slot (byes included); replays (the last decided match counts) | Rules the schema cannot express: a non-serpentine order; another captain rule; captains barred from joining higher alliances (the schema accepts it, the draft model refuses it); playoff matches outside the slot graph (e.g. extra levels or third-place matches: flagged "no slot"); finals with a non-constant format or a reset; division or Einstein round-robin formats; one season with mixed formats (D1, D5) | Record any such rule. **The frozen requirement:** affected events are excluded and counted, never approximated. More than 10% excluded in a season escalates (P6-Q13) | P6-M1 (a) and (b); everything downstream |
| **D7 Tie rule** | Free text | How a playoff tie is resolved | Transcribe it with its citation. It is informational only, so no modelling decision is needed | none computational |

## 5. Reviewer checklist (a DIFFERENT named person from the author; the CLI refuses self-approval)

- **R1 Identity.** Use your full name exactly as recorded (U3). You are not the author.
- **R2 Documents.** Use the same manual version and Team Updates the author used. Confirm that `manual.title` and `manual.version` match them, and that **Team Update precedence** is correctly reflected (a later Team Update overrides the manual).
- **R3 Every value.** Check each field in §3 against the cited section. Every boolean in `selection` must be actually transcribed. A research-draft value counts only once verified against its source.
- **R4 Alliance counts.** The ranges match the manual, do not overlap, have no unintended gaps, and have `max_teams ≥ min_teams` (U4). Every count has a bracket.
- **R5 Selection behaviour.** Order, captain rule, picks per alliance, the decline rules and the backup rule match the manual and Team Updates. Your D5 decision is applied consistently.
- **R6 The bracket.** Every slot's sources match the bracket diagram (seeds; winner and loser routing); the finals' sources and `wins_needed` match; rounds follow the D3 convention, identically across the three seasons.
- **R7 The TBA mapping.** Each slot's and the finals' (`competition_level`, `set_number`) match TBA's actual match keys for **at least one real event** of the season (D2).
- **R8 Tie behaviour.** `tie_rule` matches the cited section.
- **R9 Exclusions.** Any unsupported rule (D6) or D1/D4/D5 decision is recorded, and the resulting exclusions are acceptable.
- **R10 Stored content.** Review the **stored** ruleset (U2: read `season_rulesets.ruleset_json` for the id) and confirm it is what you checked.
- **R11 Fields populated or explicitly unresolved (schema v3).**
  - No `HUMAN_DECISION(...)` marker remains.
  - Every field has a value, or is `null` with exactly one `selection.unresolved` entry (field, note, sources checked), in the default **and** in every variant.
  - The only nulls are the decided ones: `declined_team_may_become_captain` (D-PX1-4, all seasons) and 2025 `captain_rule` (D-PX1-5); plus 2026 `captain_rule` only if H3 chose (b).
  - No inferred value was silently entered: every non-null value matches a row marked ESTABLISHED in `rulesets_entry/entry_<season>.md`, or a recorded dated decision.
- **R12 Citations exist.** `selection.citation`, every bracket slot and the finals, each `alliance_counts` row and `tie_rule` cite a section and page of the official PDF. Every variant event carries `rule`, `document`, `version`, `team_update` (named, or an explicit null), `section` and an https FIRST `url`.
- **R13 Event variants tied to the correct events.**
  - `first_championship_division` lists exactly the 8 FIRST Championship divisions of the season (`<year>arc cur dal gal hop joh mil new`).
  - Each `url` opens the FRC Events page of that division.
  - TBA's name for the key is that division.
  - No other event is listed.
  - The variant has 3 picks and no backups (2024 §12.2; 2025/2026 §13.2). Its other fields equal the default.
- **R14 Exclusions intentional and documented.**
  - `event_exclusions` contains the D-PX1-3 anomalies (2024: `2024isde2`; 2026: `2026tuak2`, `2026tuis4`) with their findings, unless an authoritative FIRST document resolving one is cited in the approval record.
  - The H1 small-event choice (O1 or O2) is applied as recorded.
  - No other exclusion appears without a dated decision.
- **R15 Approval recorded with its hash.** After `review --approve`, complete `rulesets_entry/APPROVAL_RECORD_TEMPLATE.md` as `.agent/phase6/decisions/P6_M1_APPROVAL_<season>.md`. Include the **full** approved `ruleset_sha256` (read-only query in the template), the decisions H1–H3, and this checklist's result. Commit it.
- **Decision:** approve (`--approve`, with an optional note), or return (`--return --note "what to fix"`; a note is required).

## 6. Procedure once you have the manuals

**Use the entry package (2026-10-06): `.agent/phase6/rulesets_entry/README.md`.** It holds:
- the v3 entry forms (`entry_<season>.json`), pre-filled with the ESTABLISHED and DECIDED values; every human decision is a marker the schema refuses;
- the per-field sheets (`entry_<season>.md`): value, source, status and downstream effect;
- the three remaining decisions: H1 small events, H2 round convention, H3 2026 captain rule;
- the exact commands;
- the gate that unblocks the validation runner.

The steps below still apply. Step 3.1 starts from the entry form instead of the blank template.

1. **Decide D1, D2, D3 and D5** (and D4 and D6 if they apply) and write the decisions down, dated, before entering values. D3 must be one convention for all three seasons.
2. **Get migration 0011 onto serving** (§7), with your explicit approval. The CLI writes to `DATABASE_URL`, and the authoritative rulesets belong in serving.
3. **For each season (2024, 2025, 2026):**
   1. `python -m scripts.phase6_rulesets template > ruleset_<season>.json`, then **replace every value**. Every placeholder is blank and fails validation (U1, fixed).
   2. Transcribe each field from the manual and Team Updates, with the citations (§3). Establish the TBA mapping from real match keys (D2).
   3. `python -m scripts.phase6_rulesets draft --file ruleset_<season>.json --by "<Author Full Name>"`. Schema errors are printed with their field paths; fix them and draft again (each draft is a new version).
   4. `python -m scripts.phase6_rulesets submit --id <id>`.
   5. The reviewer runs the §5 checklist, then `python -m scripts.phase6_rulesets review --id <id> --reviewer "<Reviewer Full Name>" --approve` (or `--return --note "…"`).
   6. `python -m scripts.phase6_rulesets list --season <season>` shows the version `approved`.
4. **When all three are approved,** tell me. The next step (not done now) is to clone a fresh isolated copy from serving and run `python -m scripts.phase6_playoff_track m1`, which records bracket reproduction and the captain-rule check with exclusion counts. Only after that, and in dependency order, do PX-1, PX-2, PX-4, P6-M6 (b) and P6-M8 become runnable.

## 7. Migration 0011 (APPLIED to serving 2026-10-06 with Kanav's approval; see `.agent/phase6/decisions/P6_M1_ENTRY_STATUS.md`; the text below is the pre-application plan)

- **What it is:** `database/migrations/0011_phase6_season_rulesets.sql` creates one table, `season_rulesets`, with its CHECK constraints and a partial unique index (one `approved` version per season).
  - **Schema-only and additive:** `CREATE TABLE IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS`.
  - It **modifies and deletes no existing data or table.**
- **Isolated-copy testing is sufficient for a schema-only additive migration:**
  - it applied cleanly to `stratai_test` on 2026-10-05 at 19:15 EDT;
  - the workflow tests pass there: lifecycle, self-approval refusal, supersession, schema refusal, runner refusal;
  - the full suite passed, 1,937 tests, with 0011 present.
- **Serving state (read-only check):** the latest applied migration is `0010_phase5_human_inputs.sql`, and `season_rulesets` does not exist.
- **Before applying (your action):**
  1. back up `stratai` (`pg_dump`);
  2. confirm that serving ends at 0010 and that `to_regclass('season_rulesets')` is null;
  3. check out **`phase6/build`**, because `database/migrate.py` applies every pending migration in the checked-out tree, and only `phase6/build` contains 0011;
  4. make sure nothing else is migrating.
- **Apply (only with your explicit approval):** with `DATABASE_URL` pointing at serving, `python database/migrate.py`. It runs as one transaction that rolls back on failure.
- **Verify:**
  - `migrations_applied` contains 0011;
  - `python database/verify_db.py` lists `season_rulesets`;
  - existing row counts are unchanged.

## 8. What stays blocked

PX-1 (P6-M2), PX-2 (P6-M3), PX-4 (P6-M5), P6-M6 (b) and P6-M8 (P6-DM1) refuse to run, writing nothing, until approved rulesets for 2024, 2025 and 2026 exist (`scripts/phase6_playoff_track.py` `require_rulesets`). No synthetic ruleset is stored or used for them.
