# STRATAI rating engine — canonical input and output contract

Status: **implemented by the pure engine core (`ml/ratings/epa/`)**; the database
reader of §2 is not built yet. Companion to
`docs/ratings/epa_specification.md` (the "spec"); section references like
"spec §5" point there.

The engine is a pure function of the inputs below. It performs no network
access, no database access and no Statbotics calls. Exactly one component —
a reader, specified in §2 — turns STRATAI's stored data into these inputs;
nothing else in the engine touches storage.

## 1. Principles

1. **Explicit or rejected.** Every required field is present and well-typed,
   or the record is rejected with a named reason. Nothing is zero-filled,
   defaulted, imputed or silently dropped (spec §11).
2. **Every exclusion is observable.** Each match that is excluded, not
   updated, or only predicted appears in the run's exclusion report (§5) with
   a reason code and detail.
3. **Point-in-time by construction.** The engine consumes one whole season and
   reports the rating state *before* and *after* every match; nothing about a
   match can reach a rating recorded before it (spec §2.3, §5.1).
4. **Deterministic.** Identical inputs and configuration produce
   byte-identical structured results (§6).
5. **Initialization is an input, not an assumption** (spec §4.5).

## 2. Where each input comes from in STRATAI

Canonical tables hold scores, rosters and schedule; the TBA fields the
reference needs beyond them (comp level, DQs, surrogates, score breakdowns,
event week and type, district) are read from the untouched raw TBA payload in
`raw_source_payloads` (`source='tba'`, `is_current`), the same raw-read pattern
Phase 4 M2 already uses. **No migration is required for this contract.**

| Input field | STRATAI source | Notes |
|---|---|---|
| season | `events.season` / `matches.season` | 2024, 2025, 2026 only; others → `unsupported_season` |
| event_key | `events.event_key` | |
| event start date | `events.start_date` | used only by the synthetic-time rule, which STRATAI does not apply (§4) |
| event type | raw event payload `event_type` (int) | canonical `events.event_type` is empty for all 608 events |
| event week | raw event payload `week` (int or null) | adjusted per spec §2.1 (+1, or 8 for championship) |
| event district | raw event payload `district.abbreviation` | needed only for the 2026 `isr` rule (spec §4.4) |
| match_key, event_key | `matches` | |
| comp level | raw match payload `comp_level` (`qm`/`ef`/`qf`/`sf`/`f`) | canonical `competition_level` merges levels |
| set_number, match_number | `matches` (= raw) | |
| time | raw match payload `time` (int epoch s; = canonical `scheduled_time`) | present for 100% of 2024-2026 matches |
| alliance teams | raw `alliances.<c>.team_keys` (`frcNNN` → NNN) | canonical `match_teams` agrees; raw keeps order |
| alliance DQs, surrogates | raw `alliances.<c>.dq_team_keys`, `surrogate_team_keys` | not in canonical tables |
| alliance score | raw `alliances.<c>.score` (= canonical `score_red/blue`) | -1 or null = not played |
| alliance breakdown | raw `score_breakdown.<c>` (object or null) | per-season adapter (spec §6) |

## 3. Input types

```text
SeasonInput
  season: int                         2024 | 2025 | 2026
  events: [EventInput]                every event of the season, before filtering
  matches: [MatchInput]               every match of those events, before filtering
  prior: PriorSeasonInput | None      spec §4.5; None = "no prior history supplied"
  team_districts: {team: str} | None  the team's district abbreviation this season, as
                                      the reference stores it; needed only for the 2026
                                      isr rule, and required when season = 2026 and
                                      prior is supplied

EventInput
  event_key: str
  event_type: int                     TBA event_type
  week: int | None                    TBA week, unadjusted
  district: str | None                TBA district abbreviation

MatchInput
  match_key: str                      unique within the season
  event_key: str                      must name an EventInput
  comp_level: "qm" | "ef" | "qf" | "sf" | "f"
  set_number: int
  match_number: int
  time: int | None                    TBA scheduled time, epoch seconds
  red, blue: AllianceInput

AllianceInput
  teams: tuple[int, ...]              as listed by TBA (reference uses the first 3)
  dq_teams: tuple[int, ...]
  surrogate_teams: tuple[int, ...]
  score: int | None                   None or negative = not played
  breakdown: dict | None              the raw TBA alliance breakdown, untouched

PriorSeasonInput
  source: str                         where these values came from (provenance)
  team_years: {team: [PriorTeamYear]} any order; seasons outside Y-4..Y-1 are ignored,
                                      a season >= Y rejects the run
PriorTeamYear
  season: int
  norm_epa: int | None                the reference's integer year-normalized EPA; None =
                                      the TeamYear exists without one (it still occupies
                                      a slot, and counts as 1450)
```

`prior = None` is a legitimate, fully supported input: every team then starts
as the reference starts a team with no prior TeamYear (spec §4.3). Results of
such a run are labelled **"initialized without prior-season history"** and
cannot support a Level B claim (spec §0). The engine never fills `prior` from
anywhere on its own.

## 4. Validation and filtering

Applied in this order. **Filter** reproduces the reference's own exclusions
(the match is outside the reference's season too). **Reject** is a STRATAI
refusal that the reference would not make, so it is a counted Level A
divergence. **Skip** means predicted and recorded but not updated (spec §5.4).

| Code | Condition | Action | Reference | Divergence? |
|---|---|---|---|---|
| `unsupported_season` | season ∉ {2024, 2025, 2026} | reject run | n/a | — |
| `duplicate_event_key` | an event_key appears twice | reject run | n/a | — |
| `duplicate_match_key` | a match_key appears twice | reject run | n/a | — |
| `event_season_mismatch` | an event_key does not start with the season | reject run | n/a | — |
| `unknown_event` | match names an event not in `events` | reject run | n/a | — |
| `prior_not_before_season` | a PriorTeamYear's season is ≥ the run's season | reject run | n/a | — |
| `team_districts_required` | 2026 with prior supplied but no team_districts | reject run | n/a | — |
| `no_week_one_data` | week-1 statistics give score_sd = 0 | reject run | reference divides by zero | — |
| `event_blacklisted` | key in spec §2.1 blacklist, or contains `tempclone` | filter event | same | no |
| `event_type_excluded` | TBA type 99/100 without override | filter event | same | no |
| `event_week_missing` | adjusted week is null | filter event | same | no |
| `invalid_alliance` | < 3 distinct teams on an alliance, or a team on both | filter match | same (`read_tba.py:201-205`) | no |
| `missing_time` | `time` is null | reject match | reference synthesizes a time from server-local midnight | **yes** (0 cases 2024-2026) |
| `upcoming` | either score null or < 0 | predict only | same | no |
| `missing_breakdown` | completed, score ≠ 0, breakdown null | reject match | reference zero-fills | **yes** |
| `malformed_breakdown` | breakdown present but a field the season adapter needs is absent or wrongly typed | reject match | reference zero-fills via `.get(f, 0)` | **yes** |
| `zero_score` | completed, score == 0 on an alliance | accept; empty breakdown (spec §11) | same | possible (`shared_empty_breakdown`, per alliance) |
| `skip_placeholder` | a team in 9970-9999 | skip update | same | no |
| `skip_elim_all_dq` | elim match, an alliance with ≥ 3 DQs | skip update | same | no |
| `skip_all_fouls` | both alliances no_foul == 0 and foul > 0 | skip update | same | no |

A rejected match is removed from the ordered stream: it neither updates nor
consumes a qual-count slot. That is the conservative choice, and it is why it
counts as a divergence.

Ordering is spec §2.3: ascending `time`, then **`match_key`** as the
deterministic tie-break [STRATAI]. Every group of retained matches sharing a
`time` is reported; it counts as a possible divergence (`tie_order`) only when
a team plays in two of them, the only case where order changes a rating.

## 5. Exclusion report

Every run returns, alongside its results:

```text
ExclusionReport
  counts: {code: int}                          every code in §4, zeros included
  entries: [ {code, event_key, match_key|None, detail} ]   sorted by (code, match_key)
  ties: [ {time, match_keys: [..], order_sensitive} ]
  divergences: {code: int}                     missing_time, missing_breakdown, malformed_breakdown
  possible_divergences: {tie_order, shared_empty_breakdown}
```
A run-level rejection raises `RunRejected(code, detail)` and returns nothing.

A run with a non-empty `divergences` is still valid, but it must never be
described as an exact Level A reproduction for the affected matches.

## 6. Outputs and provenance

### 6.1 Results
- **Per match** (processing order): match_key, status (`updated` or a §4
  code), pre-match rating vectors of the 6 teams, post-match vectors (unchanged
  when skipped), predictions (no-foul R and B, with-foul R and B, P(red), rp
  predictions). Values are exposed both **unrounded** (float64, what the engine
  computed) and **reference-rounded** (spec §7-§8, what Statbotics would store).
- **Per team-event**: `epa` (end of event, elims included), `start`,
  `pre_elim`, `mean`, `max`, component values (spec §7.2).
- **Per team-season**: `epa`, `start`, `pre_champs`, `max`, `unitless`, `norm`
  (norm and unitless are year-end artifacts, spec §7.2).

### 6.2 Determinism
Results are serialized canonically (sorted keys, fixed float formatting,
fixed record order). Byte-identical output is required for identical
`SeasonInput` plus configuration. Environmental facts that legitimately vary
(creation time, host) live only in the manifest, never in the results.

### 6.3 Manifest (provenance)
```text
engine_version, spec_version (git commit of this spec)
reference: {repo: avgupta456/statbotics, commit: a2cea5553e35693d423400f419bd770cb2143408}
configuration: {every constant in spec §4.1 and §5, hash}
season, input_fingerprint (sha256 of the canonical SeasonInput serialization)
prior: {source, fingerprint} | "none supplied"
data snapshot: {max raw_source_payloads.id read, per-table row counts}
libraries: {python, numpy, scipy versions}
exclusion counts, divergence counts
created_at (manifest only)
```
A stored result is traceable to exactly the raw TBA payloads that produced it
through the input fingerprint and the snapshot identifier. No result is
overwritten in place: a new run is a new artifact.

## 7. Provider boundary (interface only — no Phase 4 change)

Future consumers ask for EPA through one interface and choose the source:

```text
EpaSource = "statbotics" | "stratai"
team_event_epa(team, event_key, source) -> TeamEventEpa | Unavailable(reason)
TeamEventEpa: total, auto, teleop, endgame, source, provenance
```
`source="stratai"` returns the §6.1 team-event `epa` (end of event, the same
snapshot semantics Phase 4 reads from `team_event_stats` today). Phase 4's
assembler, features, models and acceptance criteria are **not** changed by
this work; switching any consumer is a separate, later decision.

## 8. Open items (to settle at the replay milestone, not now)

1. **Event universe.** STRATAI syncs TBA types 0-5 only; the reference also
   keeps types 6 (as Einstein) and other non-99/100 types (as INVALID). Check
   whether any such 2024-2026 events exist. Adding them would be a sync
   change, not an engine change.
2. **TeamYear universe for norm.** The reference fits norm over all of a
   season's TeamYears, including teams registered at events with no completed
   match. STRATAI derives teams from match rosters; teams that never played
   would be missing from the fit. Measure the effect before claiming anything.
3. **Initialization source.** `prior` has no in-repository source today; that
   is the separately approved initialization milestone.
4. **Team districts.** The 2026 isr rule keys on the team's district (TBA's
   district team lists), which STRATAI does not sync. It matters only when
   `prior` is supplied (with no prior every team reverts to 1450 either way),
   so the engine requires `team_districts` exactly then.
