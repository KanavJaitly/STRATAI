# P6-M1 — what people must provide to unblock the playoff track (and migration 0011)

2026-10-05. **No ruleset was drafted, inferred or generated here.** This guide describes the required inputs only. Every rule value must come from the official game manual, entered by a person.

## Official documents needed (none is in the repository)

There is no game manual in the repository, in the artifact store, or in the `game_manuals` table (0 rows on serving). Provide, for each season, **the official FIRST Robotics Competition Game Manual** in the version in force for that season's official events:

| Season | Game (name as recorded in `data/reference/frc_robot_design_curated.csv`) |
|---|---|
| 2024 | CRESCENDO |
| 2025 | REEFSCAPE |
| 2026 | REBUILT |

Bring any **Team Updates** that amended the tournament, alliance-selection or playoff sections, so the cited version is the right one.

Optionally, upload each manual through the Phase 5 web app (Game manual page). That keeps the PDF write-once with its sha256 as provenance, and requires a write token and migration 0010, which serving already has.

## What to enter, per season (schema: `data/rulesets.py` `SeasonRuleset`)

Run `python -m scripts.phase6_rulesets template` for the empty JSON skeleton, then fill one file per season.

| Field | What it is | Source | Citation |
|---|---|---|---|
| `season`, `game_name` | season year; the game's name | the manual's cover | — |
| `manual.title`, `manual.version` | exact title and version or revision of the manual used | the manual | the version string |
| `alliance_counts[]` | for each roster-size range (`min_teams`, `max_teams`, `null` = no upper bound): the number of playoff alliances | the tournament or alliance-selection section | `citation`: the section number(s) |
| `selection.order` | the draft order. The engine represents `serpentine` only | the alliance-selection section | `selection.citation` |
| `selection.picks_per_alliance` | picks per alliance after the captain | same | same |
| `selection.captain_rule` | `highest_ranked_available` is the only representable value | same | same |
| `selection.captain_may_accept_higher_alliance` | may a would-be captain join a higher alliance? `false` is refused by the draft model (not represented) | same | same |
| `selection.declined_team_may_be_picked_later` | after declining, can a team be picked by a later alliance? | same | same |
| `selection.declined_team_may_become_captain` | after declining, can a team still become a captain? | same | same |
| `selection.backup_robots` | does the format use backup robots? (Backups are not modelled; the field records the rule) | same | same |
| `brackets[]` | **one bracket per alliance count used in `alliance_counts`** | the playoff tournament section, with its bracket diagram | per slot and finals |
| `brackets[].slots[]` | for **every** playoff match before the finals: a `slot` name, TBA's `competition_level` and `set_number` for that match, its `round`, and where each side comes from (`{"kind": "seed", "seed": n}`, or `{"kind": "winner"\|"loser", "slot": name}`) | the manual's bracket, **plus TBA's match keys** for the level and set number (see ambiguity 2) | `citation` per slot |
| `brackets[].finals` | the finals level and `set_number`, `round`, `wins_needed` (best-of-N → wins needed), and where both sides come from | the manual | `citation` |
| `tie_rule` | how a tied playoff match is resolved (tiebreakers or replay), with its section | the manual | inside the text |

The schema enforces, before the draft can even be saved:
- every seed enters the bracket exactly once;
- every slot depends only on earlier slots;
- no slot's winner or loser is routed twice;
- every alliance count has a bracket format.

## Where and how (the CLI; Phase 6 has no HTTP form, per P6-A1)

**Prerequisite:** migration 0011 on the serving database (below).

```
python -m scripts.phase6_rulesets draft  --file ruleset_2024.json --by "Author Name"
python -m scripts.phase6_rulesets submit --id <id>
python -m scripts.phase6_rulesets review --id <id> --reviewer "Different Person" --approve [--note "checked against §…"]
python -m scripts.phase6_rulesets review --id <id> --reviewer "Different Person" --return --note "what to fix"
python -m scripts.phase6_rulesets list   --season 2024
```

The CLI writes to the database `DATABASE_URL` names. For authoritative rulesets, that is the serving database.

## The independent reviewer

- **A different named person** from the author. The workflow refuses self-approval.
- **The reviewer checks every value and citation against the cited manual version,** in particular:
  - the alliance counts;
  - every selection rule;
  - every bracket slot's sources;
  - the finals series length;
  - the tie rule.
- **The reviewer also checks the TBA mapping:** each slot's (`competition_level`, `set_number`) against TBA's actual match keys for at least one real event of that season.
- **Approving** makes the version authoritative and supersedes any earlier approved version. **Returning** a ruleset requires a note.

## When a ruleset counts as accepted

1. It satisfies the schema.
2. Its status is `approved` by a named reviewer different from its author. `approved_ruleset` then serves it, with its sha256 verified.
3. All three seasons (2024, 2025, 2026) are approved. Then `python -m scripts.phase6_playoff_track m1` (on an isolated copy cloned from serving afterwards) records:
   - (a) bracket reproduction against every real event;
   - (b) the captain rule.

   **An excluded-event share above 10% escalates (P6-Q13).** Exclusions caused by an entry error are corrected by a new reviewed version. That is fixing a data entry, not changing methodology. Record why.

## Points that need a human decision

1. **Mid-season rule changes:** if a Team Update changed the playoff or selection rules during a season, one ruleset per season cannot represent both. Decide how to handle it (a split season is not supported by the schema today).
2. **Manual match numbers vs TBA set numbers:** the manual numbers playoff matches, while TBA keys them by level and set number. The person entering must establish the mapping, and the reviewer must verify it against TBA.
3. **Events with fewer alliances,** if any roster-size rule yields another format: each such format needs its own bracket, or those events are excluded and counted.
4. **Division and Einstein formats:** events with null seeds (division champions) are excluded by P6-Q2. No bracket is needed for them unless you decide otherwise.
5. **Any rule the schema cannot represent** (non-serpentine order, captains barred from accepting): record it. Those events are excluded with counts, never approximated.

## Migration 0011 (NOT applied to serving)

**What it changes:** `database/migrations/0011_phase6_season_rulesets.sql` creates one new table, `season_rulesets`, with its constraints and a partial unique index (one `approved` version per season).
- It is **schema-only and additive.** `CREATE TABLE IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS`.
- It **alters, rewrites and deletes nothing** in any existing table.

**Why serving needs it:** the authoritative rulesets (human inputs) live in the serving database, like the Phase 5 human inputs. Evaluations run on isolated copies cloned from serving afterwards.

**Tested:** applied to the isolated `stratai_test` on 2026-10-05 at 19:15 EDT. `tests/test_phase6_rulesets.py` passes there: the lifecycle, refusal of self-approval, supersession, schema refusal and runner refusal. The full suite passed: 1,937 passed.

**Serving state (read-only check):** the latest applied migration is 0010, and `season_rulesets` does not exist. **0011 was not applied.**

**Safety checks before applying:**
1. Take a backup (`pg_dump` of `stratai`) and keep it until verified.
2. Confirm the current state: `migrations_applied` ends at 0010, and `to_regclass('season_rulesets')` is null.
3. Confirm no other process is mid-migration.
4. Apply from a checkout of **`phase6/build`**. `database/migrate.py` applies every pending migration in the checked-out tree; `main` does not contain 0011, and `phase6/build` adds only 0011 beyond serving's 0010.
5. Afterwards:
   - `migrations_applied` contains `0011_phase6_season_rulesets.sql`;
   - `python database/verify_db.py` lists `season_rulesets`;
   - the existing data counts are unchanged.

**Exact action** (only with your explicit approval), from `phase6/build`, with `DATABASE_URL` pointing at the serving `stratai`:
```
python database/migrate.py
```
The runner applies the pending files inside one transaction, which rolls back on failure. It records each file in `migrations_applied`.
