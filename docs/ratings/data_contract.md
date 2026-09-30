# STRATAI rating engine — canonical input and output contract

Status: **implemented** -- the pure engine core (`ml/ratings/epa/`), the
read-only database reader of §2 (`ml/ratings/reader.py`) and the replay runner
(`ml/ratings/runner.py`, `python -m scripts.run_epa_replay`). Companion to
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

### 2.1 Reader issues
The canonical `events` and `matches` rows for the season decide which records
exist. Where the reader cannot build a record, or where canonical and raw
values disagree, it records a `ReaderIssue`; nothing is resolved silently.
Excluded records never reach the engine; noted ones use the raw value above.

| Code | Effect | Condition |
|---|---|---|
| `raw_event_payload_missing` | excluded (event and its matches) | no current raw TBA event payload |
| `raw_event_payload_invalid` | excluded (event and its matches) | event_type / week / district of the wrong type |
| `raw_match_payload_missing` | excluded | no current raw TBA match payload |
| `raw_match_payload_invalid` | excluded | comp_level, numbers, time, scores or breakdown of the wrong shape |
| `raw_match_event_mismatch` | excluded | the raw payload names a different event |
| `duplicate_current_payload` | excluded | more than one `is_current` payload for one object |
| `unparseable_team_key` | excluded | a team key that is not `frc` + digits (e.g. a B team) |
| `placeholder_team_key` | noted | `frc0`; the engine then filters the match (`invalid_alliance`) |
| `canonical_time_mismatch` | noted | canonical `scheduled_time` ≠ raw `time` |
| `canonical_score_mismatch` | noted | canonical score ≠ raw score (raw -1 vs canonical NULL is not a mismatch) |
| `canonical_roster_mismatch` | noted | `match_teams` ≠ raw team keys |

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

### 6.4 Replay artifacts
`python -m scripts.run_epa_replay --season Y --out ROOT` writes one directory
per run, `ROOT/epa_<season>_<first 16 hex of the results fingerprint>/`,
write-once: an identical rerun is recognised and not rewritten, and a
different result under the same name is refused. Nothing is written to the
database.

| File | Contents |
|---|---|
| `season_input.json.gz` | the exact SeasonInput, canonically serialized (replays offline, no database) |
| `match_records.jsonl.gz` | one line per processed match: unrounded record plus `reference_rounded` |
| `team_events.json`, `team_seasons.json` | §6.1 aggregates |
| `exclusions.json` | the full engine ExclusionReport (§5), every entry |
| `reader_issues.json` | every ReaderIssue (§2.1) |
| `execution_report.json` / `.md` | the per-season execution report, including verification |
| `manifest.json` | §6.3 provenance, the reader snapshot, results fingerprint, sha256 of every file |

gzip is written with mtime 0, so identical content gives identical bytes.

## 7. Provider boundary (Phase 4's EPA source, decision D15)

Consumers ask for EPA through `ml/ratings/provider.py` and the source is
configured, never implied:

```text
Settings.epa_source      "stratai" (default, production) | "statbotics" (optional reference)
Settings.stratai_epa_chain   path to chain_<hash>.json from `run_epa_replay --chain`
team_event_epa(team, event_key)               -> TeamEventEpa | Unavailable
point_in_time_epa(team, target_event, as_of)  -> TeamEventEpa | Unavailable   (what Phase 4 uses)
```

With `epa_source = "stratai"` and no chain configured, feature building fails
with `EpaSourceNotConfigured`; it never falls back to Statbotics.

`point_in_time_epa` applies decision D13 (`.agent/phase4/PHASE_STATUS.md`)
to STRATAI's team-event values: among the team's other events whose
`end_date::timestamptz` and whose latest completed match for the team are both
before `as_of`, take the latest end date, then the latest completed match,
then `event_key` ascending. The two D13 guards are read from the same
canonical columns as `EPA_SOURCE_SQL`. STRATAI then also requires
`available_at < as_of` (§9), so a season-end value, or a value whose week-1
statistics were incomplete, is never served in-season; like D13's own guard
it only removes candidates. The values served are the reference-rounded
end-of-event `epa`, `auto_epa`, `teleop_epa`, `endgame_epa` (§6.1).

Loading a chain checks each season's `team_events.json` against its manifest
digest and, by default, that the season's raw-payload snapshot still matches
the database (`StaleEpaArtifacts` otherwise). `ml/ratings/readiness.py` is the
D8-style gate for this source.

### 7.1 Prior-season chain (2024 -> 2025 -> 2026)

`ml/ratings/chain.py`; the reference chain back to 2002 is not rebuilt.

| Season | Prior history | Teams without history |
|---|---|---|
| 2024 | none; the run is labelled "initialized without prior-season history" | all: 1450 |
| 2025 | STRATAI 2024 `norm_epa` as the most recent TeamYear; 1450 for the second slot | 1450 for both slots |
| 2026 | STRATAI 2025 and 2024 `norm_epa` | 1450 for each missing slot |

`norm_epa` is a season-end value used only to start a strictly later season.
The prior's `source` names every contributing season's results fingerprint,
so the chain is reproducible end to end. The 2026 isr rule uses team
districts derived from the district events each team played; a team whose
district events disagree gets no district and is counted (none of the 2026
conflicts involve isr). In the first real chained run 3,240 of 3,690 2025
teams and 3,402 of 3,709 2026 teams received STRATAI history; 51 2026 teams
were isr.

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

## 9. Point-in-time semantics for consumers (read before using EPA as a feature)

The engine reproduces the reference EPA calculation. That calculation is not,
everywhere, a strictly information-available-at-match-time quantity. A
prediction consumer (Phase 5) must know which outputs are which.

| Output | Available when | Point-in-time? |
|---|---|---|
| `MatchRecord.pre` and the match prediction, for a match scheduled **after the last week-1 match** | before the match | **Yes**: only earlier results, plus week-1 statistics that are complete by then |
| `MatchRecord.pre` and the prediction, for a match scheduled **at or before the last week-1 match** (all of week 1; in 2024 also 96 early week-2 matches at 2024tuis) | -- | **No**: the season statistics that set every rating's scale and the win-probability spread include week-1 results not yet played. 2,869 / 2,177 / 2,401 matches in 2024 / 2025 / 2026 (13-17% of each season) |
| Starting ratings | after week 1 | **No** before then, for the same reason; they also depend on `prior` |
| `MatchRecord.post` | after the match | yes, as a post-match value |
| team-event `epa`, components | after the event ends (includes playoffs) | yes, after the event |
| team-event `epa` with `epa_is_season_end` / provider `lookahead=True` | after the season | **No** for any in-season use |
| team-season `epa`, `epa_max`, `epa_pre_champs` | at season end / before champs | yes, after the stated point |
| `unitless_epa` | after week 1 | a fixed transform of week-1 statistics; same caveat |
| `norm_epa` | after the season | **No**: fitted over every team's season-end EPA; never a feature |

Guidance:

* To predict match N, use its teams' `MatchRecord.pre` vectors, or an engine
  snapshot taken after the last match scheduled before N. Never use a
  team-event or team-season value from the event or season N belongs to.
* For matches exposed to the week-1 look-ahead, either accept the reference
  behaviour and label those predictions as such, or build a strictly causal
  variant (for example, statistics from the previous season, or a running
  estimate). No such variant exists yet; it would be a methodology change
  needing its own decision, and its values would no longer be the reference
  EPA.
* Without `prior`, relative starting ratings are uninformative, and an error
  in a team's start persists through roughly its first one or two events
  (spec §4.5). Early-season values from a run "initialized without
  prior-season history" should be treated as low-confidence.

