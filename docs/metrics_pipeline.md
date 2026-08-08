# StratAI Metrics Pipeline (Phase 3)

How a scouting observation and a match score become one served `TeamMetrics` object, and
what that object may and may not be used to claim.

This page is Phase 3. **[docs/data_pipeline.md](data_pipeline.md) remains the reference for
Phase 2** — the landing/staging/serving layers, the canonical tables, watermarks, and the
DDL-level schema reference — and this page cross-links it rather than restating it. Where
both describe the same table, §4 here gives the *semantic* reference (what a column means
and which invariant it carries) and `data_pipeline.md` §4.1 gives the DDL. Contract tests
pin both to the live schema, so the two cannot drift apart silently.

Milestone status, the design-decision log, and the M14 human sign-off live in
`RUNNING_NOTES.md`.

---

## 1. Scope

**What Phase 3 delivers.** Given a team number and an event key, return a complete metrics
object: scoring statistics computed from that team's own match history, and defense/feeding
ratings aggregated from direct scouting observations. That object is computed by a pipeline
stage, stored in `team_metrics`, and served over HTTP.

Phase 3 Milestones 1–14, by module:

| Milestone | Module | What it does |
|---|---|---|
| 1 | `data/metrics/schemas.py` | The canonical models and every cross-field invariant |
| 2 | `database/migrations/0008_metrics_schema.sql` | Storage for observations and metrics |
| 3 | `data/metrics/statistics.py` | Pure statistical functions over a score list |
| 4 | `data/metrics/history.py` | One team's own score history at one event |
| 5 | `data/metrics/validator.py` | Structural validation of a raw scouting submission |
| 6 | `data/metrics/normalizer.py` | Raw submission → canonical `ScoutingObservation` |
| 7 | `data/metrics/submission.py` | The human scouting submission path, access-code gated |
| 8 | `data/metrics/aggregation.py` | Observations → `DefenseFeedingProfile` |
| 9 | `data/metrics/scoutradioz.py` | ScoutRadioz CSV import, caller-supplied column mapping |
| 10 | `data/metrics/compute.py` | Composes 3+4+8 into `TeamMetrics`, writes `team_metrics` |
| 11 | `data/metrics/quality.py` | Confidence/consistency checks on a computed metric |
| 12 | `api/app.py` | The FastAPI application, health probes, error envelope |
| 13 | `api/routes/metrics.py`, `data/metrics/read.py` | The team metrics endpoint |
| 14 | `scripts/metrics_spot_check.py` | The human validation harness |

**What Phase 3 does not deliver**, and where each is discussed:

- No authentication and no rate limiting on the API (§8.6).
- No HTTP write endpoint — Milestone 7's submission path is a service function with no
  route (§8.6).
- No season- or career-level rollup. `TeamMetrics` is event-scoped only.
- No scouting user-identity system; `scout_identifier` is free text (§4.1).
- No validated feeding metric — no source carries a feeding-quality field (§9.3).
- No validated `reliability_score` — the intended formula is not yet computable (§6.3).

---

## 2. Architecture

### 2.1 Two independent measurement tracks

`TeamMetrics` composes two sub-models that share nothing but an identity:

```
matches, match_teams ──► get_team_match_history ──► statistics ──► ScoringProfile ──┐
                                                                                    ├──► TeamMetrics
scouting_observations ──► aggregate_defense_feeding ──► DefenseFeedingProfile ──────┘
```

They are kept as named sub-objects rather than flattened into one model because they are
two genuinely independent computations, with independent source data and independent
confidence signals. Only their *storage* is flat (§4.2).

**The critical constraint.** `CLAUDE.md` and `RUNNING_NOTES.md` both carry it:

> Defense/feeding scores = **directly measured**, NOT inferred from point output.

There is no code path anywhere from a match score to a defense or feeding number. That is
enforced in four places, deliberately:

1. `DefenseFeedingProfile`'s pydantic invariants in `data/metrics/schemas.py` — a score
   exists if and only if its `insufficient_data` flag is false, so a confident-looking
   score built on no observations is unconstructible.
2. The `team_metrics_defense_sufficiency_check` / `team_metrics_feeding_sufficiency_check`
   `CHECK` constraints in `database/migrations/0008_metrics_schema.sql` — the same rule at
   the storage layer, so such a row is also unstorable.
3. `aggregate_defense_feeding` is only ever handed `list[ScoutingObservation]`. It has no
   access to a score, so it could not infer one if it wanted to.
4. `tests/test_defense_feeding_constraint.py` — a regression guard with two teams whose
   scouting is identical and whose match scores are not, asserting their defense/feeding
   output is identical.

A team with no observations gets no rating. It never gets one synthesized from its scoring.

### 2.2 Module map

Read top to bottom; nothing below imports anything above it.

- `data/metrics/schemas.py` — models, the rating scale, the z-score thresholds,
  `MIN_MATCHES_FOR_STDDEV`. No I/O, no database.
- `data/metrics/statistics.py` — `average_score`, `score_stddev`, `consistency_rating`,
  `classify_match_days`, `reliability_score`. Pure functions over `list[int]`.
- `data/metrics/history.py` — `get_team_match_history`, the read that produces that list.
- `data/metrics/aggregation.py` — `aggregate_defense_feeding`. Pure, no database.
- `data/metrics/validator.py`, `data/metrics/normalizer.py` — raw submission →
  `ScoutingObservation`, reusing `data.staging.validator`'s `ValidationIssue` /
  `PayloadValidationError`.
- `data/metrics/submission.py` — `submit_human_scout_observation`.
- `data/metrics/scoutradioz.py` — `ScoutRadiozFieldMapping`, `import_scoutradioz_csv`.
- `data/metrics/quality.py` — `check_team_metrics`.
- `data/metrics/compute.py` — `compute_team_metrics`, `compute_event_team_metrics`.
- `data/metrics/read.py` — `look_up_team_metrics`. A sibling of `history.py`, *not* a
  wrapper over `compute.py`.
- `api/routes/metrics.py` — the HTTP layer, which calls `read.py` and nothing else.

**Dependency direction.** `data.metrics` may import `data.staging`; `data.staging` must
never import `data.metrics`. This is why `check_team_metrics` lives in `data.metrics` even
though every other quality check lives in `data.staging.quality` — it must import
`data/metrics/schemas.py`. The thresholds it uses still live in `data/staging/quality.py`
with every other plausibility bound. `api` imports `data`; `data` never imports `api`.

### 2.3 Three ways in, one table

`scouting_observations` has exactly two writers and no third path:

| Source label | Entry point | Shape |
|---|---|---|
| `human_scout` | `submit_human_scout_observation` | One submission at a time, access-code gated |
| `scoutradioz` | `import_scoutradioz_csv` | One event's CSV export, batch |

Both land in `raw_source_payloads` via `RawPayloadWriter`, then stage and load through
`data.pipeline`'s existing `read_pending` / `stage_batch`. Neither has a parallel
validation, normalization, or loading path — `data.metrics.validator` and
`data.metrics.normalizer` are registered for both sources against the same underlying
functions, because the rules describe the payload's shape, not its origin.

Observations from both sources coexist in the table, are distinguishable by `source`, and
pool into one aggregated score.

### 2.4 When metrics are computed

`compute_event_team_metrics(event_key, ...)` computes and upserts a row for every team
`match_teams` rosters at the event, records its own `pipeline_runs` row
(`pipeline_name="metrics_compute"`), and deletes the rows of teams a schedule correction
has dropped from that roster. It is wired as a follow-on stage immediately after a
single-event sync in `data.orchestrator.main`.

It is deliberately **not** wired into `sync_season` or `watch_event`: recomputing every
team of every historical event during a full-season backfill is an unbounded-cost operation
nobody asked for, and `watch_event`'s live-poll loop is a separately-tested state machine
that deserves its own integration decision.

**It always fully recomputes. There is no incremental watermark.** A `TeamMetrics` row's
inputs span two entity types across three sources, each already watermarked for its own
purpose; reconstructing "has anything this depends on changed" would mean comparing against
the maximum of several existing watermarks — real complexity for a marginal gain, since
recomputing is a handful of indexed reads plus pure-Python arithmetic. It is also the most
literal way to satisfy the project principle that calculated metrics be reproducible from
stored source data: there is no partial, possibly-stale incremental state to reason about.

---

## 3. Data flow, end to end

**Defense/feeding track.**

1. A scout submits a form, or a team exports a ScoutRadioz CSV.
2. The payload is validated structurally (`data/metrics/validator.py`). An invalid payload
   is rejected *before* anything lands.
3. The untouched payload lands in `raw_source_payloads`, versioned and checksum-deduplicated.
   For a CSV import the complete raw row rides along under `_raw_csv_row`, so a column the
   mapping does not name is still preserved permanently.
4. `stage_batch` normalizes it into a `ScoutingObservation` and runs the referential check
   (does this match/team/event exist canonically?).
5. `CanonicalRepository.load_scouting_observation` upserts one `scouting_observations` row.

**Scoring track.** `matches` and `match_teams` are already populated by the Phase 2 pipeline.
Nothing extra is collected.

**Composition.** `compute_team_metrics` calls `get_team_match_history` for the score list,
runs the five statistics functions over it to build a `ScoringProfile`, fetches the team's
observations and runs `aggregate_defense_feeding` over them to build a
`DefenseFeedingProfile`, and composes both into a `TeamMetrics`.

**Quality.** `check_team_metrics` runs between computing a metric and loading it. Every
issue it raises is a warning and the row loads anyway (§7.6).

**Load and lineage.** The metric is upserted into `team_metrics`, and `canonical_lineage`
records every contributing match and every contributing scouting observation — so a served
number can be traced back to each raw payload behind it. Lineage is best-effort audit
information: a match or observation with no traceable payload is skipped, not an error.

**Serve.** `GET /teams/{team_number}/events/{event_key}/metrics` reads the stored row and
reassembles it. It never computes (§8).

---

## 4. Schema reference (semantic)

Both tables are created by `0008_metrics_schema.sql`. **The DDL-level reference — every
constraint, index, and cascade rule with its full reasoning — is
[docs/data_pipeline.md §4.1](data_pipeline.md#41-phase-3-metrics-tables).** This section
says what each column *means*.

Every column is a field of a model in `data/metrics/schemas.py`, under its own name, with
two marked exceptions. The `CHECK` constraints are transcriptions of that module's
`model_validator`s, not new policy.

### 4.1 `scouting_observations`

One scout's (or ScoutRadioz's) direct assessment of one team in one match — one row per
`ScoutingObservation`. **This is the source of truth for defense and feeding.**

| Column | Meaning |
|---|---|
| `id` | Surrogate key. *Not* a model field — the natural key is the four-column unique index below |
| `match_key` | The match observed. FK → `matches` |
| `event_key` | Denormalized from `match_key`; "every observation for this event" is the dominant access pattern |
| `team_number` | The team observed. FK → `teams` |
| `scout_identifier` | Who reported it. **Free text, not a foreign key** |
| `defense_rating` | 0–5, or NULL if this scout did not rate defense |
| `feeding_rating` | 0–5, or NULL if this scout did not rate feeding |
| `notes` | Free-text scout notes, optional |
| `source` | `human_scout` or `scoutradioz` |
| `submitted_at` | Ordering/audit timestamp for this observation |
| `raw_payload_id` | *Not* a model field — lineage to the landed payload. Nullable |

Four facts about this table carry weight:

- **The natural key is `(match_key, team_number, scout_identifier, source)`**, enforced by a
  unique index. One scout rates one team in one match once per source; a resubmission
  updates that row rather than adding a second opinion. Two different scouts, or the same
  name arriving from a different source, are distinct observations.
- **At least one of `defense_rating` / `feeding_rating` must be present.** An observation
  asserting neither is meaningless and is rejected by both the model and a `CHECK`.
- **This is the only irreplaceable data in the system.** Every other table is re-fetchable
  from TBA or Statbotics; a human's rating of a match played three weeks ago is not. That
  is why `raw_payload_id` is `ON DELETE SET NULL` — purging a raw payload, which integration
  teardown does routinely, must never take scouting data with it — and why the three
  canonical foreign keys carry **no `ON DELETE` action at all**, so deleting a scouted match
  fails loudly instead of silently destroying the observations.
- **`scout_identifier` is free text.** There is no scouting user-identity system in Phase 3.
  Nothing prevents identity spoofing or duplicate scout names. A documented MVP limitation,
  not an oversight.

### 4.2 `team_metrics`

The complete served metrics object for one team at one event — one row per `TeamMetrics`,
keyed `(team_number, event_key)`.

| Column | Meaning |
|---|---|
| `team_number`, `event_key` | Composite primary key — the same keying as `team_event_stats` |
| `season` | The event's season |
| `computed_at` | When this row was computed. The roadmap's `last_computed_at`, under the model's name |
| `matches_scheduled` | Matches this team is rostered into at this event |
| `matches_used` | Matches with a usable recorded result. The confidence signal for the whole scoring track |
| `average_score` | Mean of the team's own match scores |
| `score_stddev` | Population standard deviation of those scores |
| `consistency_rating` | 0–100; how tightly clustered the output is (§6.1) |
| `reliability_score` | 0–100; **an interim placeholder** (§6.3) |
| `good_day_count` | Matches scoring more than one stddev above the team's own mean |
| `average_day_count` | Matches within one stddev of that mean |
| `bad_day_count` | Matches scoring more than one stddev below it |
| `defense_score` | Median of the team's defense ratings, 0–5, or NULL |
| `defense_observation_count` | How many observations carried a defense rating |
| `defense_agreement` | 0–1 spread signal. **Not inter-scout agreement — see §9.1** |
| `defense_insufficient_data` | True when no defense score is reported |
| `feeding_score` | The same four fields for feeding |
| `feeding_observation_count` | |
| `feeding_agreement` | |
| `feeding_insufficient_data` | |
| `contributing_sources` | TEXT[] — which sources produced a real (non-insufficient) score |

**The two sub-models are flattened into columns.** The nesting is fixed-arity — exactly one
of each, never optional, never a list — and the two share no field names, so every column
keeps its model name unprefixed and reassembly is mechanical. JSONB would have made the
column types and the `CHECK` constraints unenforceable; separate tables would have turned
one upsert into two writes for no gain. The served object stays composed; only its storage
is flat. Float columns are `DOUBLE PRECISION`, not `NUMERIC`, specifically so psycopg
returns `float` and not `Decimal` on the read path.

**A current-state snapshot, upserted in place** — not an append-only history. Recomputing
during a live event overwrites the previous value. "What did we know as of match 5" is
answered by replaying the pipeline against a historical cut of the already-versioned
`raw_source_payloads`, not by storing every intermediate snapshot.

**How "no data" is represented — the two tracks use different mechanisms, deliberately.**

- **`ScoringProfile` has no flag.** `matches_used` *is* the signal, and NULL always means
  "not computed" for a reason it determines: `0` means there is no data at all; `1` means
  variance is undefined for a single sample.
- **`DefenseFeedingProfile` has explicit flags.** A score is non-NULL if and only if its
  `insufficient_data` flag is false, and zero observations force the flag.
  `contributing_sources` is empty if and only if both tracks are insufficient.

### 4.3 `scouting_access_codes`

Created by `0009_scouting_access_codes.sql`. A lightweight per-event anti-abuse gate on the
human submission path — not an identity system. A row's *absence* is the default-open state.
Documented in full at
[docs/data_pipeline.md §4.2](data_pipeline.md#42-phase-3-scouting-submission-table).

---

## 5. The 0–5 rating scale

Both defense and feeding use one integer scale, `MIN_RATING` = 0 to `MAX_RATING` = 5,
defined once in `data/metrics/schemas.py`.

**`0` is a real, meaningful rating** — "confirmed none observed" — and never a missing-data
sentinel. Missing data is represented by `DefenseFeedingProfile`'s `insufficient_data`
flags, never by a `0` standing in for "unknown". This distinction runs through the whole
pipeline and is the reason for two of the rescaling controls in §5.2.

The SQL bounds in `0008` are hardcoded, because SQL cannot import `MIN_RATING`/`MAX_RATING`.
Changing the scale requires a migration.

### 5.1 What each rating means

Defense (`DEFENSE_RATING_DESCRIPTIONS`):

| Rating | Meaning |
|---|---|
| 0 | No defense observed -- team played offense/support only. |
| 1 | Minimal/incidental defense -- occasional positioning, no sustained effect on an opponent. |
| 2 | Light defense -- contested space part of the match but rarely disrupted scoring. |
| 3 | Moderate defense -- consistently contested one opponent, measurably slowed their cycle time. |
| 4 | Strong defense -- effectively shut down or severely hampered a specific opponent for extended periods. |
| 5 | Elite defense -- alliance-defining shutdown; opponent's offense was neutralized for most of the match. |

Feeding (`FEEDING_RATING_DESCRIPTIONS`):

| Rating | Meaning |
|---|---|
| 0 | No feeding observed -- team did not deliver game pieces to teammates. |
| 1 | Minimal/incidental feeding -- rare or accidental hand-offs. |
| 2 | Light feeding -- occasional, unreliable delivery to a teammate. |
| 3 | Moderate feeding -- regular, functional feeding role for part of the match. |
| 4 | Strong feeding -- reliable, high-volume feeding that materially fed a teammate's scoring. |
| 5 | Elite feeding -- feeding was the team's primary role, executed at a rate that defined the alliance's cycle. |

These strings are reproduced verbatim from the code and pinned by a contract test.

### 5.2 Rescaling a source scale onto 0–5

A scouting form rarely uses 0–5 natively. `_rescale_rating` in `data/metrics/scoutradioz.py`
maps one raw column linearly onto the canonical range, configured per column by a
`ScoutRadiozRatingMapping`:

| Field | What it declares |
|---|---|
| `column` | Which raw CSV column this is |
| `source_min`, `source_max` | The column's own native scale |
| `excluded_values` | Raw values on this column that are **not a rating at all** |
| `target_min` | The bottom of the canonical range this column rescales onto |

```
scaled = (raw - source_min) / (source_max - source_min) * (MAX_RATING - target_min) + target_min
```

An empty cell means "not recorded" and yields no rating. A present `0` is *not* an empty
cell — it rescales like any other value, unless the column opts into `excluded_values`.

**`excluded_values` and `target_min` solve different problems and compose.**

- `excluded_values` says *this value is not a rating*. 2026's `qDefenseQuality` uses raw 0
  for "played no defense", not "defended badly" — established by cross-tabulating the
  zero-rated rows against on-field participation (all 33 participated normally and
  out-scored the rated defenders roughly 2:1), not assumed. Rescaling that as a rating would
  publish a confident `defense_score` of 0.0 for a team that never defended, which is the
  inference-from-absence the critical constraint forbids.
- `target_min` says *the ratings that exist do not reach the bottom of the canonical scale*.
  A 1–10 source scale rescaled onto 0–5 maps raw 1 — a genuine "barely defended" — to
  `(1-1)/9 * 5 + 0 = 0.0` exactly. That is an **endpoint artifact of two scales sharing no
  common bottom**, and it published the same canonical 0 that `excluded_values` exists to
  prevent, by a completely different route. Setting `target_min=1` maps raw 1 to canonical 1
  and leaves canonical 0 unreachable for that column.

Both are opt-in and per-column, and `target_min` defaults to `MIN_RATING`, so every mapping
written before it existed behaves byte-identically. See §9.5 and §10.1.

---

## 6. Scoring statistics

Implemented in `data/metrics/statistics.py` as pure functions over a `list[int]` of the
team's own scores in the matches it actually played, supplied by `get_team_match_history`.

Every function returns `None` — never `0`, never an exception — when its result is
statistically undefined.

### 6.1 The three `matches_used` buckets

| `matches_used` | What is defined |
|---|---|
| `0` | Nothing. Every value field is `None` |
| `1` | `average_score` only — the average of one value is itself |
| `>= MIN_MATCHES_FOR_STDDEV` (2) | Everything |

`ScoringProfile`'s `model_validator` encodes exactly this as an invariant, so the models and
the functions cannot drift apart, and `0008`'s `team_metrics_no_data_check` /
`team_metrics_variance_check` transcribe it into the storage layer.

- **`score_stddev`** is the *population* standard deviation, not the sample one. These
  matches are not a sample used to infer a larger population's variance — they are literally
  every match this team played at this event. Dividing by `n` rather than `n-1` is the
  semantically correct choice for a descriptive statistic.
- **`consistency_rating`** is `100 * (1 - stddev/mean)`, clamped to 0–100. A team whose
  scores are all identical rates 100. A mean of `0` is handled explicitly rather than
  dividing by zero: if every score is genuinely `0` the answer is 100 (perfectly consistent,
  even at a level of zero); if the mean is `0` with a non-zero score present — only possible
  for input outside this function's assumed domain — the answer is `None`, because reporting
  "perfectly consistent" there would be a confident wrong answer no downstream range check
  could ever catch.

### 6.2 Good, average, and bad days

`classify_match_days` classifies each match relative to the team's *own* mean:

- **good**: `score > mean + GOOD_DAY_ZSCORE_THRESHOLD * stddev`, where the threshold is `1.0`
- **bad**: `score < mean + BAD_DAY_ZSCORE_THRESHOLD * stddev`, where the threshold is `-1.0`
- **average**: everything else

The three counts always sum to `matches_used`, enforced by both the model and
`team_metrics_day_counts_check`. A team with `stddev == 0` has every match classified
average — by definition it is neither better nor worse than its own mean.

The thresholds live in `data/metrics/schemas.py`, not in `statistics.py`, so the policy was
fixed before the implementation rather than re-decided mid-implementation.

### 6.3 `reliability_score` is an interim placeholder

**The formula actually in use:**

```
reliability_score = 100 * (matches_used / matches_scheduled)
```

**The intended definition, which is not yet computable:**

```
reliability_score = 100 * (1 - (no_shows + disqualifications) / matches_scheduled)
```

Reliability is meant to measure whether a robot *shows up and finishes a match without a
catastrophic failure* — a different question from consistency, which measures how tightly
clustered its output is when it does perform. The formula in use measures neither. It
measures **"did we get a recorded result at all"**, which is a statement about missing data,
not about robot failure. In practice it reads `100.0` for very nearly every team. It is a
documented placeholder, not a final answer.

**Why the intended formula is blocked.** It needs per-team no-show and disqualification
status per match, and that data does not exist anywhere in this system:
`data/clients/schemas.py`'s `MatchAllianceResult` models only `score` and `team_keys`, and
neither status is carried by `StagingMatch` or `match_teams` either.

> **UNVERIFIED — candidate field names only.** TBA's alliance object is *believed* to expose
> something like `dq_team_keys` and `surrogate_team_keys`. These names are moderately
> confident general knowledge and have **not** been verified against TBA's live API docs the
> way every other TBA field mapping in this codebase was. They are recorded here as
> candidates to investigate, not as fact. **Confirm the real field names against TBA's
> documentation before building anything on them**, then extend
> `MatchAllianceResult` → `StagingMatch` → `match_teams` before changing this formula.

Until that is done: **validating `reliability_score` validates nothing.** The M14 harness
prints a caveat at every site the number appears, specifically so it cannot be signed off as
validated by accident.

---

## 7. Aggregation methodology

`aggregate_defense_feeding(observations)` in `data/metrics/aggregation.py` takes one team's
`ScoutingObservation` rows at one event and returns a `DefenseFeedingProfile`. It is pure —
no database, no I/O — and it trusts the caller to have scoped the list correctly.

### 7.1 The two-observation minimum

`MIN_OBSERVATIONS_FOR_SCORE = 2`. Below it, that metric's `insufficient_data` is true and
its score and agreement are both `None`.

Two, not one. The model itself only forces the flag at exactly zero observations; deciding
whether *one* is enough is this layer's policy. One observation cannot establish agreement —
agreement is a statement about consensus among multiple observations — and reporting a
single point's trivial zero variance as `agreement = 1.0` would be fabricated confidence.
This mirrors `MIN_MATCHES_FOR_STDDEV = 2` exactly.

### 7.2 Median, not mean

The reported score is the **median** of the ratings.

Ratings are discrete ordinal tiers (§5.1), not a continuous measurement, and a scouting lead
summarizing "what did everyone say" reaches for "most scouts said X" — which is the median —
not "the arithmetic average of everyone's tier number". The median is also robust to exactly
the failure this data is prone to: one scout misidentifying a team or fat-fingering a rating
should not drag a 3-3-3-3 consensus down to 2.4.

### 7.3 Agreement

```
agreement = max(0, 1 - pstdev(ratings) / ((MAX_RATING - MIN_RATING) / 2))
```

`1.0` means every observation agreed exactly; `0.0` means maximal disagreement. Population
standard deviation, for the same reason `score_stddev` uses it: the observations in hand are
the complete population of opinions collected, not a sample of a larger one.

Agreement is **independent of observation count**. Six observations that all disagree is a
real, low-confidence result, and is not the same fact as relying on one opinion — which is
why both numbers are reported and neither is folded into the other.

> ⚠️ **Read §9.1 before showing this number to a user or feeding it to a model.** On every
> dataset StratAI has actually measured, `defense_agreement` is **not** an inter-scout
> reliability signal. It is one team's match-to-match variance, confounded with unknown
> scout calibration. The field name's natural reading is not what the data supports.

### 7.4 Independence, and which sources get credit

Defense and feeding aggregate entirely independently. An observation that rates only one of
them contributes to that metric and nothing to the other.

`contributing_sources` is the union of the sources that contributed to whichever metric
actually produced a real, non-insufficient score — not every source that submitted anything.
A source whose only rating was for the metric that ended up insufficient did not "produce" a
score and is not named as having done so. This is what satisfies the model's own invariant
that `contributing_sources` is empty if and only if both metrics are insufficient.

### 7.5 Known scope boundary: no per-scout weighting

Observations are **not** deduplicated or down-weighted by `scout_identifier`.

A team plays several matches at one event and the same scout legitimately rates it in more
than one of them; each of those is a genuine, independent data point about a different
match, so counting all of them is correct. What this does *not* address is one scout
dominating a sample: ten observations from one repeat scout currently aggregate identically
to ten observations from ten different scouts, even though the latter is a stronger
consensus signal. No milestone has assigned weighting-by-distinct-scout-count, and inventing
one would be guessing at a policy nobody has asked for.

### 7.6 Quality checks on a computed metric

`check_team_metrics` (`data/metrics/quality.py`) judges a computed `TeamMetrics` on
confidence and internal consistency — the axis neither the structural validator nor
`data/staging/quality.py`'s plausibility checks cover. Thresholds:

| Threshold | Value | Fires when |
|---|---|---|
| `LOW_SAMPLE_MATCHES` | 4 | `matches_used < 4` |
| `LOW_SAMPLE_OBSERVATIONS` | 4 | `observation_count < 4` |
| `LOW_AGREEMENT` | 0.5 | `agreement < 0.5` |

Two properties matter more than the numbers:

- **Nothing here can be out of range.** Pydantic and `0008`'s `CHECK`s already make an
  impossible metric unconstructible and unstorable, so "implausible" at this layer can only
  mean *jointly* suspicious — fields that are each individually valid but cannot both be
  true of one team's match set.
- **Every rule is a warning, and the row loads anyway.** A metric from two matches is
  untrustworthy, not corrupt; it is the honest summary of the two matches that exist, and
  rejecting it would leave the team with no metrics at all. There is deliberately no
  metrics-side rejection path to write.

This extends Phase 2's quality layer rather than adding a second one: the same `QualityIssue`,
the same severity constants, the same `DataQualityRecorder`, the same `data_quality_issues`
table, no migration. See
[docs/data_pipeline.md §6.4](data_pipeline.md#64-quality-checks-on-computed-metrics).

---

## 8. API contract

### 8.1 The endpoint

```
GET /teams/{team_number}/events/{event_key}/metrics
```

Mounted under `Settings.api_prefix`, which defaults to `""`. The `/health` and `/ready`
probes deliberately sit *outside* the prefix, so they do not move when the API is remounted.

`team_number` is constrained `gt=0`, matching `TeamMetrics`' own bound — a request for team
`0` is a 422, because that is not a team number rather than a missing team.

### 8.2 A successful response

`200`, body is the canonical `TeamMetrics`:

```json
{
  "team_number": 10070,
  "event_key": "2026mrcmp",
  "season": 2026,
  "computed_at": "2026-08-08T17:42:11.402913+00:00",
  "scoring": {
    "matches_scheduled": 12,
    "matches_used": 11,
    "average_score": 88.3,
    "score_stddev": 14.2,
    "consistency_rating": 83.92,
    "reliability_score": 91.67,
    "good_day_count": 2,
    "average_day_count": 7,
    "bad_day_count": 2
  },
  "defense_feeding": {
    "defense_score": 1.0,
    "defense_observation_count": 7,
    "defense_agreement": 0.458,
    "defense_insufficient_data": false,
    "feeding_score": null,
    "feeding_observation_count": 0,
    "feeding_agreement": null,
    "feeding_insufficient_data": true,
    "contributing_sources": ["scoutradioz"]
  }
}
```

### 8.3 Thin data is a 200, not an error

A team with one played match and no scouting returns the **complete object** with
`score_stddev`, `consistency_rating` and the day counts `None`, and
`defense_insufficient_data` true. That is "we measured this team and have little to say",
and it is a success.

This endpoint reports low confidence. It never converts low confidence into a failure and
never fills it in.

### 8.4 Four ways to have nothing, four codes

All four are `404` — the addressed resource is not there. The request was well formed (that
is 422's job), the server did not fail (500's), and the service can serve (503's).

| Code | Means | Actionable? |
|---|---|---|
| `team_not_found` | This team is not in StratAI's `teams` table | No — sync the team first |
| `event_not_found` | This event is not in StratAI's `events` table | No — sync the event first |
| `team_did_not_attend` | Both exist, but the team is not rostered in any match at the event | **Never resolves** |
| `metrics_not_computed` | Both exist and the team is rostered, but no metrics row is written yet | **Resolves by waiting** |

The last two are why this distinction is carried by a code rather than by a status. What
separates them is not existence but *actionability*: `compute_event_team_metrics` writes
rows only for rostered teams, and `_delete_orphaned_team_metrics` removes the row of a team
dropped from that roster — so "not computed" resolves by waiting or triggering a compute,
while "did not attend" never resolves at all. HTTP status has no vocabulary for that
difference; a stable machine-readable code does.

**Why "not computed" is not a 200 with an empty body.** Because a thin-data team genuinely
*is* a 200 with a mostly-empty body (§8.3). If an absent row also returned 200, a client
would have to reconstruct "we have not measured this team" from which nullable fields happen
to be set — precisely the confusion the `insufficient_data` flags exist to prevent. Absent
stays a 404; thin stays a 200.

### 8.5 The error envelope

Every non-2xx response — including FastAPI's own 404, 405, and 422 — uses one shape:

```json
{
  "error": {
    "code": "metrics_not_computed",
    "message": "Metrics for team 10070 at event '2026mrcmp' have not been computed yet.",
    "status": 404,
    "request_id": "0f9c2a1e-...",
    "details": null
  }
}
```

`details` is omitted entirely rather than sent as null, and is only ever populated on a 422,
where it is allow-listed down to `(field, message, type)` — the caller's own raw input and
any custom validator's context are never copied out.

**For any status ≥ 500 the body is assembled from module constants and the request id, and
the exception is never read into it.** That is structural, not a careful habit: there is no
expression in the 500 handler through which the exception's text could reach the response.
The real detail goes to the log, correlated by request id. Route-supplied codes are honoured
only below 500, so that guarantee stays intact.

### 8.6 What this endpoint deliberately does not do

- **It never recomputes.** `look_up_team_metrics` reads `team_metrics` directly — one
  primary-key query on the happy path — and `compute_team_metrics` is not called. A test
  asserts that a read adds no `pipeline_runs` row, which is an external witness that nothing
  recomputed.
- **It re-validates on the way out.** Reassembly constructs real
  `ScoringProfile`/`DefenseFeedingProfile` objects rather than `model_construct`, so a stored
  row contradicting its own invariants fails loudly instead of being served as a model that
  lies about itself.
- **No writes and no authentication.** Both are out of scope, and neither is needed by a
  read-only endpoint. They become a real prerequisite the moment Milestone 7's submission
  path gets an HTTP route, which it does not have — that is separate, later work.

---

## 9. Known issues and limitations

Each entry states whether it needs a code change or a collection-time change. Several of
these bound what an M14 sign-off is allowed to claim; see `RUNNING_NOTES.md` for the signed
validation record.

### 9.1 🔴 `defense_agreement` is not an inter-scout signal

**Measured on the full 2026mrcmp export, 2026-08-08.** Across all 331 observations, the
number of `(match_key, team_number)` pairs rated by more than one scout is **zero**. Two
scouts have never rated the same robot in the same match anywhere in this dataset.

What `aggregate_defense_feeding` pools for a team is therefore a set of *different matches*,
each seen by a *different* one of the event's 26 scouts — 4.3 distinct scouts per team on
average, up to 9. The resulting standard deviation mixes two effects it cannot separate:
(a) the team genuinely defended better in some matches than others, and (b) scouts disagree
about what a given rating means.

**Consequences.** `agreement` must **not** be described to a user as "how much the scouts
agreed", and must **not** be used as an observer-reliability feature in any model. The honest
framing is *per-team consistency of defense, with unknown calibration noise baked in*.

Nothing in `DefenseFeedingProfile` is wrong — the docstring says "agreement among
observations", which is literally what this is — but the field name's natural reading is not
what the data supports. **Fixing this needs a collection-time change**, not a code change:
two scouts assigned to the same robot in the same match, which no ScoutRadioz export will
produce on its own.

### 9.2 🟡 Agreement is normalized over the full canonical span

Documented, **deliberately not fixed**. The denominator is `(MAX_RATING - MIN_RATING) / 2` =
2.5, on the assumption that ratings can occupy the whole 0–5 scale. A column with
`target_min = 1` produces ratings confined to `[1, 5]`, whose maximum population standard
deviation is 2.0, not 2.5. Agreement for such a column therefore reads **slightly high**,
with a floor near 0.2 rather than 0.0.

One-directional, small, and it never inflates a *score* — only the confidence attached to
one. Not fixed because the correction belongs to the aggregation formula, not to a
per-column mapping, and varying the denominator per column would make two teams' agreement
numbers incomparable across sources — a worse property than a known, bounded, documented
optimism. Revisit if agreement ever becomes a model feature or a pick-list threshold rather
than a human-facing display number.

### 9.3 🔴 Feeding is unvalidatable

No feeding-quality column exists in the ScoutRadioz export or in any other raw source. The
2026 scouting form simply has no feeding question, so `feeding_rating` is never populated by
that path and every team's feeding track reports `insufficient_data`.

The DCMP summary does carry a Feeding Score, but it is **pre-aggregated output, not raw
observations** — importing it would bypass the aggregation engine entirely and validate
nothing about this pipeline. Feeding validation requires a feeding-quality field captured
**at scout time**. Blocked until collection changes.

### 9.4 🔴 `reliability_score` is a placeholder

See §6.3. It reads `100.0` for nearly every team, measures missing data rather than robot
failure, and its intended formula is blocked on no-show/DQ data that does not exist. The
candidate TBA field names are **unverified**. Validating it validates nothing.

### 9.5 Rescaling: one defect fixed, one open

**Fixed, 2026-08-08 — low-end compression.** A 1–10 source column rescaled onto 0–5 mapped
raw 1 to canonical 0, an endpoint artifact that made a genuine weak rating indistinguishable
from the "no defense" value `excluded_values` protects. Team 10070's `[1, 8, 1]` became
`[0, 4, 0]` → `defense_score` **0.0** on three real observations. Fixed by the opt-in
`target_min` (§5.2); with `target_min=1` the same team becomes `[1, 4, 1]` → **1.0**.

Two caveats survive the fix:

- **It is opt-in.** The ML-training-label concern is discharged only for columns that
  actually set `target_min`. A future source with the same shape must set it too.
- **Already-imported data is not retroactively corrected.** Changing a mapping requires
  deleting the event's observations *and* its watermark row before re-importing — see §10.1.

**Open — integer buckets cost rank resolution.** The 0–5 integer scale collapses 15 distinct
median values into 8, with 24 teams tying at 2.0 or 3.0 on the 2026mrcmp data. Measured
effect on rank correlation against the human reference: ρ 0.54 for the raw median versus
0.51 for the stored value. A float 0–5 score would recover the lost resolution. This is a
schema plus compute change and belongs in its own PR.

**Same item, second symptom — half-tier scores have no anchor (found 2026-08-08, audit).**
The stored score is not an integer either. `aggregate_defense_feeding` reports
`statistics.median`, which averages the two middle values at an *even* observation count, so
a team rated `[2, 2, 3, 3]` stores **2.5** — a value with no entry in
`DEFENSE_RATING_DESCRIPTIONS`, which is `dict[int, str]` (§5.1). **13 of the 58 scored rows**
on the live 2026mrcmp data are half-tiers, 2.5 the most common. Nothing crashes and nothing
is wrong arithmetically: no code indexes the description table by score. But the tier
vocabulary §5.1 publishes cannot name what is stored, and §7.2's rationale for the median
("most scouts said X") does not hold at an even count, where nobody said 2.5. This is the
same schema-plus-compute decision as the paragraph above — an explicit float 0–5 score,
with a documented reading for a half-tier ("the observations split between the two
neighbouring tiers") — and belongs in the same PR. Deferred.

### 9.6 Open product decision: quality versus volume

The served metric today is **"quality when defending", not "how much a team defended"**.
Excellent-but-rare defenders rank high; frequent mediocre defenders rank low.

Three options are on the table — serve quality only, add a defended-frequency term (defended
in N of M matches), or serve quality × volume. This drives Alliance Selection and Match
Strategy, so it is a product decision, not an implementation detail. Unresolved.

### 9.7 Smaller limitations

- **No scout identity.** `scout_identifier` is free text; spoofing and duplicate names are
  possible and undetected (§4.1).
- **No per-scout weighting** in aggregation (§7.5).
- **No connection pooling.** `database/connection.py` opens a fresh connection per
  `Database.connection()` call. Harmless for the CLI and pipeline, which are
  single-connection-per-invocation by design; it is worth revisiting now that a long-lived
  API process serves concurrent requests.
- **Sentinel event keys must agree with their payload year.** The staging layer derives a
  match's season from its event key, so a `9997…` key with `"year": 2025` yields season-9997
  matches and trips plausibility warnings.

### 9.8 🟡 An off-roster observation is stored, then never aggregated

**Found 2026-08-08 by audit. Latent — zero live rows. Needs a code change; deferred.**

`check_scouting_observation_references` verifies that an observation's `match_key`,
`team_number`, and `event_key` each exist canonically. It does **not** verify that the team
is rostered into that match. `compute_event_team_metrics` iterates only the teams
`match_teams` rosters at the event (§2.4), so an observation naming a team that is not on
that roster feeds no metric at all, and `_delete_orphaned_team_metrics` removes any row a
previous roster once produced. The API then answers `team_did_not_attend` (§8.4) while
`scouting_observations` holds rows asserting that team was there.

Nothing errors, and no quality issue names it — which is what makes it worth writing down.
Scouting observations are the only irreplaceable data in the system (§4.1), and this is a
path by which some of them become invisible to every consumer while still sitting in the
table. It is reachable through exactly the failure §7.2 already anticipates — a scout
misidentifying the robot they watched — whenever the mistyped number belongs to a team that
exists but is not at this event.

**Measured on the live database, 2026-08-08: zero off-roster observations**, on either the
(team, event) or the (team, match) relation. The gap is real and currently unrealized.

A fix would either extend the referential check to roster membership — rejecting at staging,
while the observation is not yet irreplaceable — or add a metrics-side quality warning
naming the orphan. Which of those is right is a real decision and was not made here.

### 9.9 Metrics do not recompute during a live event

**By design for Phase 3**, recorded here because a project-level constraint reads as
promising otherwise. `compute_event_team_metrics` is wired as a follow-on stage after a
single-event sync only; `--watch` returns before reaching it, and §2.4 records why that
integration was deferred. During a live event the canonical tables track matches as they are
played, while `team_metrics` — the table the API actually serves — does not move until
someone runs the single-event path again.

`CLAUDE.md`'s critical constraint *"Real-time updates must sync **during an event** as
matches are played"* is therefore satisfied today for **ingestion**, not for the served
metrics. It is a target for the real-time phase, not a description of what Phase 3
guarantees. Closing the gap is the deliberate `watch_event` integration §2.4 defers — and it
has a prerequisite: §9.10.

### 9.10 🟡 Quality issues are re-inserted on every recompute

**Found 2026-08-08 by audit. Harmless at today's cadence.** `DataQualityRecorder.record`
writes one row per detection with no deduplication, and deliberately so: on the ingestion
side a watermark holds short of a bad payload, so each re-detection is a genuinely new event
whose timestamp answers "how long has this been broken". `compute_event_team_metrics` holds
no watermark and fully recomputes every team on every trigger (§2.4), so that reasoning does
not carry over — every warning is written again, in full, on every run. Measured 2026-08-08:
39 rows for 36 distinct `(object_id, field, issue_type)` triples across 5 recomputes.

⚠️ **TAG — this must be fixed BEFORE compute is wired into the watch loop (§9.9).** At manual
cadence the growth is negligible. At live-poll cadence it is one row per warning per poll:
the 33 `low_sample_size` warnings one `2026mrcmp` recompute produces become thousands over an
event, and `data_quality_issues` stops being readable exactly when it is most needed. The fix
is either metrics-side deduplication or an upsert-and-count path in the recorder for computed
rows; both are small, and neither is urgent until the watch loop lands.

---

## 10. Extending Phase 3

### 10.1 Adding a season's column mapping

**The mapping is Python configuration supplied by the caller, not a data file and not
library code.** `data/metrics/scoutradioz.py` contains zero field names for any FRC game —
no `qDefenseQuality`, nothing tied to 2026 — and it must stay that way. Which raw column
represents defense or feeding quality, and on what native scale, is a property of one
season's scouting *form*.

The worked reference is `scripts/import_2026mrcmp_scouting.py`. Its docstring *is* the
record of that event's mapping, which is the point: an import whose mapping nobody wrote
down cannot be reproduced, audited, or compared against a later one.

**Steps.**

1. **Read the export's header.** ScoutRadioz's own metadata columns (`org_key`, `event_key`,
   `match_key`, `time`, `alliance`, `team_key`, `scouter`) are stable across seasons and are
   already modeled by `ScoutRadiozMatchScoutingRow`. Everything else comes from the form.
2. **Identify the rating column, if any.** Leaving `defense_rating` or `feeding_rating`
   unmapped (`None`) is a legitimate configuration, not an error — the 2026 form has no
   feeding question at all.
3. **Determine its native scale**, `source_min` and `source_max`, *by inspecting the real
   export*. Do not assume.
4. **Decide `excluded_values`.** Ask what the column's bottom value actually means. If a raw
   `0` means "did not do this" rather than "did this badly", exclude it — and establish that
   from the data, as the 2026 mapping did by cross-tabulating zero-rated rows against on-field
   participation, rather than by assumption.
5. **Decide `target_min`.** If the source scale's own bottom endpoint is a real, weak rating
   (a 1–10 scale), set `target_min=1` so it does not collapse onto canonical 0. If the scale
   genuinely starts at "none of this", you want `excluded_values` instead. They compose.
6. **Choose `notes_columns`** — free-text columns to fold into `notes`.
7. **Run the import** via `import_scoutradioz_csv`, or write a small script beside the 2026
   one that records the mapping in its docstring.

```python
mapping = ScoutRadiozFieldMapping(
    defense_rating=ScoutRadiozRatingMapping(
        column="qDefenseQuality",
        source_min=1,
        source_max=10,
        excluded_values=("0",),   # 0 means "played no defense" on this column
        target_min=1,             # raw 1 is a real weak rating, not canonical 0
    ),
    feeding_rating=None,          # the 2026 form has no feeding question
    notes_columns=("superNotes",),
)
```

**Three rules that are not negotiable.**

- Nothing game-specific goes into `data/metrics/scoutradioz.py`.
- A column the mapping does not name is still preserved: every raw row lands verbatim under
  `_raw_csv_row`, permanently, in the versioned landing layer.
- A mapping that names a column absent from the file fails immediately and loudly, before
  any row is processed.

**⚠️ The re-import trap.** `import_scoutradioz_csv` is idempotent for an *unchanged* file:
`RawPayloadWriter` deduplicates on `(source, type, object_id, payload_checksum)` and
`read_pending` filters `id > watermark`. That same mechanism means re-importing the same CSV
under a *changed* mapping silently does nothing for every row whose canonical rating happens
not to change — those payloads are byte-identical, land nothing, and are never re-read. To
re-import under a new mapping you must delete the event's `scouting_observations` rows **and**
its `source_watermarks` row (`WatermarkStore.advance` uses `GREATEST` and cannot move a
watermark backwards, so this requires direct SQL). Raw payloads are never deleted — the
landing layer is append-only and the old-scale payloads remain as the audit record.

### 10.2 Adding a field to `TeamMetrics`

1. Add the field to the model in `data/metrics/schemas.py`, with its `Field` bounds and any
   cross-field invariant in the existing `model_validator`.
2. Add a migration adding the column, transcribing that invariant as a `CHECK` — `0008` is
   the pattern to follow.
3. Compute it in `data/metrics/compute.py`.
4. Extend `CanonicalRepository`'s `team_metrics` upsert.
5. Extend **both** `_TEAM_METRICS_COLUMNS` and the positional unpacking in
   `data/metrics/read.py`. They must stay in step — the column list is spelled out rather
   than `SELECT *` precisely so a new column cannot silently shift the unpack.
6. Document it in §4.2 here **and** in `docs/data_pipeline.md` §4.1.
7. The contract tests in `tests/test_metrics_docs_contract.py` will fail until step 6 is
   done, in both directions.

### 10.3 Adding an endpoint

Add a router under `api/routes/`, mount it in `api/app.py` under `settings.api_prefix` (data
routes go under the prefix; probes do not), declare `ErrorResponse` for every non-2xx status
it can produce, and use `ApiError` when one status covers several situations a client must
branch on. Then document the path in §8 — a route that exists and is undocumented fails the
contract tests.

### 10.4 Adding a metric quality check

Add the rule to `data/metrics/quality.py`, building a `QualityIssue` through the existing
`_issue_builder`. Put any new threshold in `data/staging/quality.py` with the other
plausibility bounds, and quote it in §7.6. Before writing the rule, confirm it can actually
fire on a *constructible, storable* row — pydantic and `0008`'s `CHECK`s already make most
impossible states unreachable, and a rule that cannot fire is dead code.

Every metric rule is a warning. There is deliberately no parameter through which a future
rule could acquire the power to discard a computed metric.
