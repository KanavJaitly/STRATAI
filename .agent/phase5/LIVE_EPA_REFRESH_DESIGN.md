# Live EPA refresh — pre-registered design (PROPOSED; not frozen, not implemented)

Status: **PROPOSED for Kanav's review, 2026-10-02.** It becomes frozen only by an explicit decision. The commit that records the approval will be the freeze point, and nothing below may change after any live or replay result exists. **No live refresh code exists.**

## 0. Problem and constraints

**The problem.** The evaluated production source is D18:
- Statbotics team-event EPA from one verified snapshot (`statbotics_snapshot_20261001T220423Z`);
- the STRATAI fallback for target event 2026iscmp only;
- D13 selection;
- availability rules A1 / A2.

The snapshot is fixed and loaded once. A live Statbotics sync changes `team_event_stats`, after which the D18 loader refuses to load. Ratings therefore cannot use newly concluded events. That blocks the roadmap's "ratings visibly update as new matches flow in".

**Constraints, all carried over unchanged:**
- **D13 selection** is unchanged: only the team's other events that concluded before as_of, with the same ordering.
- **A1 / A2** are unchanged.
- **No silent fallback** to an older event.
- **Models stay frozen:** the D18 M5 v2 and M7-pair artifacts. A refresh changes *inputs*, never models.
- **$0 cost; no LLM.**

**Why only prior events matter.** The target event's own EPA is never used (D13 excludes the target). In-event information comes from canonical match rows strictly before as_of. So a refresh only matters for **prior events that have concluded**. Live freshness means picking up a team's just-finished previous event, not tracking mid-event EPA.

## 1. Source and refresh cadence

- **Source:** Statbotics `GET /v3/team_events?event=<key>&limit=1000`. This is the D18 endpoint and schema (`statbotics-v3`), through the existing client (`fetch_event_team_metrics`) and the Phase 2 landing path.
- **Trigger:** event conclusion, not a clock.
  - An event becomes due when its canonical end date has passed and its last scheduled match is completed. Detected by the existing `--watch` sync.
  - A due event is fetched at +1 h, then every 2 h, until it is **processed** or 72 h have passed.
- **Processed** (an objective test, checked against the D18 snapshot on 2026-10-02):
  - every record's `status` is `"Completed"`;
  - every team on the canonical roster has a record.
- **Not usable as the test:** the per-team `record.total.count`. It equals the canonical completed-match count for only 96.6% of completed team-events (it is usually off by one), so it is too inexact.
- **The 2026 Israeli events** are exactly the records with `status` `"Upcoming"` (140), so the test separates them correctly.
- **Daily sweep:** one re-fetch per day of every event concluded in the last 14 days, to detect late corrections (§9 measures drift).
- **Rate:** at least 0.25 s between requests (as D17). Expected volume is about 30–60 requests per event week.

## 2. Snapshots and versioning

- **Each fetch** writes an immutable raw file: the canonical JSON, gzip, sha256, `retrieved_at`, endpoint and parameters. It also lands each record in `raw_source_payloads` (Statbotics team_event, `{team}_{event}`) through the Phase 2 path, as D17 did.
- **A snapshot** is a manifest mapping event_key → (raw file sha256, `retrieved_at`, processed true/false). Each refresh creates a new manifest equal to the previous one plus the changed events (copy-on-write).
- **Snapshot identity:** `snapshot_id` = sha256 of the canonical manifest. Manifests form an append-only log, each recording its parent.
- **Nothing is ever deleted or overwritten.** The frozen D18 snapshot is the log's first entry (its root).

## 3. as_of semantics (the core leakage rule)

For a lookup (team, target event, as_of):

1. **Snapshot.** Use the latest snapshot whose creation time is before as_of. Within it, an event's record counts only if that event's raw file has `retrieved_at` < as_of and processed = true.
2. **Selection.** Run D13 over canonical facts as of as_of. Facts are re-read at every refresh, which fixes today's load-once gap.
3. **Value availability.** `available_at(value) = max(D18 available_at (A1/A2), retrieved_at of the record)`. A value is servable only when `available_at` < as_of. Otherwise the next D13 candidate is considered, as in D18.
4. **Candidate failure.** A D13 candidate that concluded before as_of but has no processed Statbotics record by as_of is handled by §6. It is never silently skipped to an older event.

**Why replays are honest.** A historical replay through this provider, using real `retrieved_at` values, serves nothing that had not actually been retrieved by then. So replays cannot leak. Validation uses an explicitly labelled *simulated-retrieval* mode instead (§9).

## 4. Incremental update behaviour

- **Each refresh:**
  - fetch the due events;
  - verify each raw file's sha256;
  - apply the Phase 2 normalizer and confirm, for every record, that normalized `epa.total_points` equals the `team_event_stats` row (D18's S1 check, per event);
  - write the new manifest;
  - re-read canonical facts;
  - swap the in-memory provider atomically.
- **In-flight requests** keep the provider they started with. Every response names its `snapshot_id`.
- **A refresh that fails any check** writes no manifest. The previous snapshot stays in service.
- **The live provider reads values from snapshot files, not the mutable table.** So a later `team_event_stats` change cannot alter what a past snapshot served. The table is still kept current for other consumers.

## 5. Statbotics outage behaviour

- **Requests that fail** (5xx, timeout, schema error) are retried with the existing backoff. Failure is per event: one failed event never blocks others, and no partial file is written.
- **During an outage** the latest good snapshot keeps serving. Responses carry `snapshot_retrieved_at` and `stale_events`: due events not yet processed.
- **A lookup whose needed prior event is due but unprocessed:**
  - within the 72 h window it is refused as `epa_source_pending` (a new code);
  - after 72 h, §6 applies.
- **Outages are counted** in a refresh log. Recovery needs no manual action.

## 6. STRATAI fallback behaviour — **decision needed**

D18's fallback covers one event, 2026iscmp, chosen by a human after Statbotics never processed the 2026 Israeli events. Live operation needs a rule for the next such event. Options:

**A (recommended).** Objective fallback with a 72 h trigger.
- **Trigger:** a prior event concluded more than 72 h before as_of and still has no processed Statbotics record (§1).
- **Value:** STRATAI's own EPA for that team-event, from the STRATAI engine replayed over the canonical season. It has its own `available_at`, as in D15, and is labelled `stratai_fallback` with `fallback_reason` = `statbotics_unprocessed_72h`.
- **Evidence for it:** STRATAI and Statbotics EPA agree closely (Pearson 0.9966–0.9996, mean absolute difference 0.3–0.6 points).
- **Cost:** it requires an incremental STRATAI season replay, about 30 min per season today, run when the trigger fires.
- **Nature:** this is a **new source rule**. It generalizes D18's single-event decision.

**B. No automatic fallback.** The lookup is refused (`epa_source_incomplete`) until a human adds the event to a fallback list, as D18 did.

**C. Fallback immediately** on outage. *Not recommended:* it mixes sources whenever Statbotics has a bad hour.

Whatever is chosen, fallback values never replace a processed Statbotics value. They are per team-event and always labelled.

## 7. Provenance

**Every served appearance records:**
- `epa_value_source` (`statbotics` / `stratai_fallback`);
- `snapshot_id`;
- the record's `retrieved_at` and raw sha256;
- the D18 rule (A1 / A2);
- `fallback_reason` when it applies.

**Every response records:** `snapshot_id`, `snapshot_retrieved_at`, `stale_events`, and the model sha256 values (unchanged).

**Every refresh writes a log entry:** events fetched, outcomes, checks passed or failed, parent and new `snapshot_id`.

## 8. Leakage prevention and reproducibility

**Leakage:**
- **Strict:** `retrieved_at < as_of`, plus D13's conclusion rule, plus A1 / A2.
- **Target event excluded:** the target's own (live, in-event) Statbotics EPA is never used.
- **Point in time:** in-event features come from canonical rows strictly before as_of (unchanged).
- **Outcomes stay out:** alliance outcomes are never features (`data.alliances`).

**Reproducibility:**
- `(as_of, snapshot_id, model sha256s, code commit)` fully determines every output.
- A prediction log stores these per response, and a replay tool re-serves any logged prediction bit for bit.
- Snapshots are immutable and content-addressed.

## 9. Validation — pre-registered (criteria fixed here, before any result)

Historical Statbotics values *as they were in-season* cannot be retrieved: the API serves current values only. So validation has two parts, kept apart.

**Historical part (before any live use; every check must pass):**

- **L1 — equivalence.**
  - **Setup:** the live provider in frozen mode (root snapshot only, with `retrieved_at` replaced by the D18 snapshot's availability, so the provider behaves exactly as D18).
  - **Pass:** it returns results identical to the D18 provider on all 319,301 appearances of 2024–2026.
  - **Tolerance:** none (exact equality).
- **L2 — simulated cadence.** Simulated retrieval: an event's record becomes retrieved at its conclusion + lag, with lag ∈ {6 h, 24 h, 72 h}, values taken from the root snapshot.
  - **Pass (each lag):**
    - 0 served values with `available_at ≥ as_of`;
    - every appearance whose served EPA differs from D18 is explained by the lag (its D18 source event concluded within `lag` of as_of);
    - the number of such appearances is reported per lag.
  - **Diagnostic only:** the M5 v2 midpoint Spearman and the qualification ECE are recomputed on the lag-24 h features with the frozen models, and reported next to D18. No gate; no model change.
- **L3 — outage drill.**
  - **Setup:** injected 5xx and timeouts during refresh.
  - **Pass:**
    - no manifest written for a failed refresh;
    - the previous snapshot keeps serving;
    - `epa_source_pending` inside the window;
    - §6 behaviour after it;
    - 0 unlabelled source mixing.
- **L4 — atomicity and reproducibility.**
  - **Setup:** a match-by-match replay of a 2026 event under simulated retrieval.
  - **Pass:**
    - each response names one `snapshot_id`;
    - re-serving every logged prediction reproduces it bit for bit;
    - ratings change only when new canonical matches or new snapshots arrive.

**Prospective part (2027 season; cannot be done earlier):**

- **L5 — value drift.**
  - **Measured:** for every event, the difference between the first processed value and the value 14 days later.
  - **Reported:** the distribution.
  - **Material drift (proposed, to freeze with this design):** median |Δ| > 0.5 EPA points, or more than 5% of team-events with |Δ| > 2 points. If drift is material, ratings that use first-processed values are labelled `provisional` for 14 days.
- **L6 — live shadow evaluation.**
  - **Setup:** from 2027 week 1, every qualification prediction is logged with its as_of.
  - **Evaluation:** after the season's regional and district qualification matches, the D18 methodology is applied *unchanged* to the logged live predictions:
    - qualification ECE, plus the per-bin table;
    - the M5 v2 midpoint Spearman against the raw-EPA baseline under the same live inputs.
  - **Proposed criteria for the label `live_validated`:**
    - qualification ECE < 0.05 (D6);
    - no qualification bin with ≥ 30 predictions deviating by more than 0.05;
    - M5 v2 midpoint Spearman > live raw-EPA baseline.
  - **Until then:** live-refreshed outputs carry `live_refresh_not_yet_validated`.

## 10. Decisions needed before freezing

1. The §6 fallback option: A, B or C.
2. The 72 h window and the fetch schedule (§1).
3. The L5 drift thresholds and L6 criteria as proposed.
4. Whether `epa_source_pending` should be a 404 or a 422 (follow the existing convention: 422 for an input state, as `epa_source_incomplete`).
