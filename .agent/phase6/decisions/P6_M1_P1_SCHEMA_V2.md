# P6-M1 decision P1: ruleset schema v2 (per-event selection variants)

**2026-10-05. Decision by Kanav: P1, not P2.** The data model must represent FIRST's real rules before any ruleset is entered. Championship divisions are not excluded because the first schema was too coarse.

**Implemented here:** the schema and workflow change only.
- No ruleset was entered, submitted or approved.
- Migration 0011 was not applied to serving.
- PX-1, PX-2, PX-4, M6 (b) and M8 were not run.
- The research package (`.agent/phase6/rulesets_research/`, written for schema v1) is unchanged. When entering, a person adds the v2 fields.
- No frozen specification, P6-Q decision, threshold, population, acceptance criterion, P6-M10 or Phase 4 model was changed.

## 1. The schema change (`data/rulesets.py`, `SCHEMA_VERSION = "p6-ruleset-v2"`)

```
SeasonRuleset
  schema_version      "p6-ruleset-v2"   (v1 is refused: it cannot hold more than one selection structure)
  ...unchanged v1 fields...
  selection           SelectionRules     the season DEFAULT (unchanged shape)
  selection_variants  [SelectionVariant] REQUIRED key; [] when every event uses the default
  event_exclusions    [EventExclusion]   REQUIRED key; [] when none

SelectionVariant
  name       non-empty, unique
  selection  a COMPLETE SelectionRules (order, picks_per_alliance, captain rule, the three decline/captain booleans,
             backup_robots, citation). No field is inherited, so nothing is implicit
  events     >= 1 VariantEvent

VariantEvent: the per-event provenance, every field required
  event_key    TBA event key of THIS season (^\d{4}[a-z0-9]+$, season prefix)
  rule         the relevant FIRST rule
  document     source document
  version      source version
  team_update  the Team Update that applies, or an explicit null (the key must be present; "" is refused)
  section      section or rule citation
  url          https URL on a FIRST host (firstinspires.org or a subdomain; firstfrc.blob.core.windows.net)

EventExclusion
  event_key  of this season, at most once
  reason     lower_snake_case code
  finding    non-empty: what was found and why it cannot be represented
```

**Validation**, at draft time and again on every read of an approved ruleset (`approved_ruleset` re-validates the stored JSON):
- variant names are unique;
- an event appears in **at most one** variant;
- a variant identical to the default (citation aside) is refused;
- every variant and exclusion event key belongs to the season;
- exclusions are unique per event;
- all v1 checks still apply.

**No DDL change.** `ruleset_json` is JSONB. Migration 0011's one-approved-per-season index still holds, because one ruleset still covers the whole season.

**Template:** `scripts/phase6_rulesets.py template` emits blank v2 entries. A fresh template fails validation on every variant, provenance and exclusion field.

## 2. Why this represents FIRST's standard and Championship rules faithfully

- **Standard events:** `selection` = 2 picks, backups. Source: 2024–2026 §10.6.1 ("each ALLIANCE Lead chooses 2 other teams"), §10.6.3 (BACKUP TEAMS).
- **FIRST Championship divisions:** a variant with `picks_per_alliance` 3 and `backup_robots` false. Source: 2024 §12.2; 2025 and 2026 §13.2 ("a third round of selection ... reversed again, with ALLIANCE 1 picking first"; "There is no provision for BACKUP TEAMS at the FIRST Championship").
- **The draft order falls out of the existing logic:**
  - `turn_order(n, 3)` is the serpentine 1→8, 8→1, 1→8, exactly the manual's Round 3.
  - The draft model, engine, P6-M6 (b) turn reconstruction and the captain-rule check now read the event's own rules.
  - Tested: a listed event drafts 4-team alliances; any other event drafts 3-team ones.
- **The bracket needs no variant.** TBA confirms the divisions use Table 10-2 at 8/8 events per season (research §3).

## 3. Event-key representation

Each non-default event is listed **explicitly**, by its TBA key, inside its variant, with its own FIRST provenance. Nothing is inferred:
- `events.event_type` is NULL for every event in the canonical data, so it cannot be used;
- membership is never derived from data patterns (e.g. "every alliance lists 4 teams").

The 8 division keys per season (`<year>arc cur dal gal hop joh mil new`) are a **research observation**. A person must enter them from FIRST's own division list and cite it.

## 4. Precedence

`SeasonRuleset.for_event(event_key)` returns `EventRules` (`event_key`, `variant` name or None, `selection`), resolved in this order:
1. an `event_exclusions` entry: **refused** (`event_excluded`, with the reason). An excluded event has no rules, so it can only be excluded and counted;
2. the explicit variant listing the event;
3. the season default.

A key from another season is refused (`wrong_season`).

Every consumer goes through this method:
- `ml.playoffs.selection` refuses a bare `SeasonRuleset` (`event_rules_required`), so the default can never be applied to a variant event by accident.
- `scripts/phase6_playoff_track.py` uses `for_event` in `m1`, `m6b` and `m8`.
- `m1` counts exclusions as `ruleset_exclusion:<reason>`, and records per event and per season which variant governed it.

## 5. The three anomalous events

I checked them against the FIRST documents and found no explanation:
- **Backup before the first match:** a backup may not be requested before the alliance's first playoff match (2024 T604; 2025 and 2026 T608).
- **A recruited backup must play:** it "must be included in the LINEUP for the ALLIANCE'S next MATCH" (2024 T605; 2025 and 2026 T609).
- No provision covers replacing a selected team before the first match.

| Event | Alliance | Listed (TBA `picks`) | Recorded behaviour | FIRST explanation |
|---|---|---|---|---|
| `2024isde2` | seed 7 | 5554, 4590, 2212, 4416 | 4416 (listed 4th) played both playoff matches. 2212 (listed 3rd, a round-2 pick) never played | none: no backup is allowed before the first match. Whether TBA's list order differs from the selection order cannot be settled from FIRST documents |
| `2026tuak2` | seed 8 | 9583, 10940, 9247, 10998 | 10998 (listed 4th) played sf1 and sf7, and 10940 (round-1 pick) sat out; 10940 played sf9 and 10998 did not | none (same rule) |
| `2026tuis4` | seed 4 | 9427, 9519, 8151, 8042 | 8042 (listed 4th) played none of the alliance's 4 matches (sf2, sf7, sf9, sf12) | none: T609 requires a recruited backup to play the next match |

**Disposition: UNRESOLVED, and not interpreted.**
- Schema v2 can **exclude and count** them through `event_exclusions`, e.g. reason `backup_before_first_match` or `backup_never_played`, with the finding.
- Listing them is a decision for the person entering the 2024 and 2026 rulesets. Nothing has been entered.

## 6. M1–M8 disposition

**A** = faithfully representable; **B** = descriptive only, does not affect a validated Phase 6 number; **C** = explicitly excluded and counted; **D** = needs another schema change before M1 can be approved.

| ID | Rule | Class | Exact population and dependency |
|---|---|---|---|
| **M1** | Championship divisions: 3 picks, no backups | **A** | A v2 variant. 8 events per season (24). Affects the P6-M1 (b) captain check (unchanged: it reads `picks[:2]`), M6 (b) turn order, M8 drafts and the P6-M7 engine. All now use the event's rules |
| **M2** | TBA records a backup as the 4th `picks` entry | **A** (representation) | With per-event rules, a listed entry beyond `1 + picks_per_alliance` at an event with `backup_robots: true` is a backup. At a Championship division, the 4th entry is a round-3 pick. **Its consumption by PX-1, PX-4 and M8 is a separate frozen-spec mismatch: STOPPED, §7.1** |
| **M3** | Small-event byes (§10.6.6): TBA records placeholder alliances (teams 9990–9999) with recorded "bye" results | **C** | 5 events: `2024vapor`, `2025ncash`, `2026mefal`, `2026txfor`, `2026txmca`. Also `2026isde2`: 24 teams, 8 real alliances, contrary to §10.6.6, unexplained. Shares: 1 of 190, 1 of 203, 4 of 213 events (0.5%, 0.5%, 1.9%). Exclusion either way: listed in `event_exclusions` with a reason (recommended, so the count is specific), or, if only the 25+ → 8 roster rule is transcribed, refused as `not_covered`. They never reach PX-1 rows, PX-4, M6 (b) or M8, which use only reproduced events. Representing them faithfully would need a bye/placeholder concept in the bracket schema. **Not implemented; say if you want it** |
| **M4** | Captaincy after a decline is conditional: a decliner who is already a Lead keeps captaincy (all seasons); in 2026 a team "will become captain if not picked" too; other decliners are not addressed | **D** | One boolean cannot hold a conditional rule, and the documents are silent on part of it, so entering any boolean is a guess for the uncovered case. **Effect on validated numbers today: none.** TBA records 0 declines in 2024–2026; M8 drafts start from no declines; M6 (b) uses TBA declines (none). It matters only when the P6-M7 engine is given declines (coach input). Needed: e.g. a tri-state per case (`current_lead`, `would_be_captain`, `other`: true / false / unestablished), with the engine refusing a state that hits an unestablished case. Or your decision to accept a value. **Not implemented** |
| **M5** | Pick timer, T605 (2025, 2026): a skipped alliance is revisited later, or receives the next highest-ranked unselected team | **B** | A procedural rule for a timer violation. TBA records final alliances, not the sequence, so no data shows when it happened. The frozen draft model (P6-Q6, deterministic best-available) predicts the nominal serpentine. M6 (b) (non-gating) reconstructs states in nominal order; a skipped turn would be undetectable there. PX-1, PX-4 and M8 do not depend on the sequence |
| **M6** | Finals: a tied Finals MATCH stays a tie; up to 3 Overtime MATCHES; a tied Overtime MATCH goes by Table 10-3. Non-finals ties: Table 10-3, else replay | **A** | `wins_needed: 2`. `reproduce_bracket` counts only decided matches, so tied finals matches, overtime (TBA final set 1, up to 4 match numbers in the data) and replays (the last decided match counts) are reproduced. PX-1 has no tie outcome; ties are excluded from fit and evaluation, counted, per the frozen PX-1 spec §1. The Einstein replay rule is under M7 |
| **M7** | District Championship multi-division playoffs (§11.4, Table 11-7, Figures 11-1/11-2) and Einstein (§12.4 / §13.4) | **C** | Exactly the frozen P6-Q2 population: **15 division-champion events** (`cmptx`, `micmp`, `necmp`, `oncmp`, `txcmp` × 2024–2026), 90 playoff matches (30 per season). Dependencies: P6-M1 counts them `excluded:division_champion` (5 of 190, 5 of 203, 5 of 213 = 2.6%, 2.5%, 2.3%); PX-1 and PX-2 exclude them by P6-Q2; PX-4, M6 (b) and M8 consume only reproduced events; M6 (a) excludes them; P6-M10 to M13 use qualification matches, unaffected. **Not excluded:** the division events that feed them (e.g. `2024micmp1`–`4`, `necmp1`/`2`, `oncmp1`/`2`, `txcmp1`/`2`, and the Championship divisions). These are seeded 8-alliance events under §10.6.1 (and §13.2 for the Championship divisions, via M1). §11.4's own-division backup restriction applies only inside the excluded finals events |
| **M8** | Backup mechanics: one coupon, highest-ranked from the BACKUP POOL, not before the first match; at District Championship playoffs, from the alliance's own division's pool | **B** | Recorded (`backup_robots` per event), not modelled: a frozen non-goal (P6-M4 non-goals "backup-robot substitutions (backups unknown in data)"; P6-M7 non-goals "backups"). How a listed backup is consumed is §7.1 |

## 7. Remaining unresolved items

### 7.1 STOPPED: backups and round-3 picks in PX-1 composition (frozen-spec mismatch, nothing changed)

**What the frozen texts say:**
- P6-Q2 decides "alliance composition sums" = "M6's input: `TEAM_FEATURE_NAMES` summed per alliance".
- `docs/P6Milestones.md` P6-M2 *Inputs*: "Alliance composition (**three teams'** point-in-time `TeamFeatures` at the selection moment)".
- The frozen PX-1 spec §1 maps sides by "at least two of that side's three teams. **Backups are unknown**, so substitutes are tolerated".
- P5-M1 recorded "0 backups" (TBA's `backup` field).

**The specification did not intend backups to contribute.** It assumed none existed.

**What the implementation does:**
- `ml/playoffs/data.py::playoff_rows` sums over **every** listed `picks` entry.
- So PX-1's training and evaluation composition includes:
  - backups at 96 (2024), 92 (2025) and 118 (2026) events;
  - round-3 picks at the 8 Championship divisions per season, where the spec's "three teams" does not say which three of four.
- The same listed teams feed:
  - the M6/M7 baseline inside the PX-1 gate (`_m6m7_on`: `MatchFeatureRow` with 4 teams a side for these alliances);
  - PX-4's `field_outcome` (actual alliances);
  - P6-M8's `identifies`, where P6-Q1's "at least one actual pick" can be met by a backup;
  - the seed-order baseline.

**Not changed:** no consumer, objective, spec or population was modified.

**This needs your explicit decision before PX-1, PX-4 or M8 run. It does not block P6-M1.** Some readings that would each be a new dated interpretation decision:
- composition over the **selected** teams only (captain plus `picks_per_alliance` picks per the event's rules), which keeps 4 at Championship divisions;
- over the three teams **on the field** in each match (in-playoff lineup information, arguably excluded by P6-Q2);
- keep the listed teams and document that meaning.

### 7.2 Other open items

| Item | Status |
|---|---|
| M4: conditional captaincy after a decline | **D**: needs a schema change or your decision (§6) |
| 2025 `captain_rule` | UNRESOLVED: the 2025 manual does not state who replaces a Lead who accepts an invitation (2024 does; 2026 implies it). TBA agrees at 1,583 of 1,584 alliances, but data is not a rule. Needs an official FIRST source (Q&A or Playoff Communication Document) or your decision |
| `declined_team_may_become_captain` value | Follows M4 |
| M3 small events | C as designed. A bye/placeholder extension is possible if you want them represented |
| The three anomalies; `2026isde2` | Exclusion decisions for the person entering the rulesets (§5) |
| Research drafts | Written for v1. When entering, add `selection_variants` (the 8 divisions per season, each cited from FIRST) and `event_exclusions` |
| P6-M7 engine profiles at 4-team alliances | `candidate_profile` computes synergy only for a 3-team configuration, so a 4-team (Championship) configuration shows synergy as not computed. Descriptive only (M9 synergy is not a PX-1 feature, P6-A3); unchanged |
| Migration 0011 | Deferred. No DDL change is needed for v2 |

## 8. Frozen Phase 6 specifications

- **The schema change itself alters no frozen specification.** P6-Q2, P6-Q6, the PX-1 spec, the gates, the populations and the thresholds are unchanged.
- **The selection-module change is plumbing.** It reads the event's rules instead of the season default. P6-Q6's "best-available ... with P6-M1's decline rules" now uses the rules P6-M1 actually assigns to the event.
- **One frozen-spec issue is exposed, not created: §7.1.** The frozen PX-1/P6-M2 texts specify three-team composition on the premise "backups unknown". That premise is false, and the implementation sums all listed teams.
  - The frozen files are unchanged, including `docs/P6Milestones.md` ("backups unknown in data").
  - The issue is stopped for your decision.
