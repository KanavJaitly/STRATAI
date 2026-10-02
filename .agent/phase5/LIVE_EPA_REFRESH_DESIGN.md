# Live EPA refresh — pre-registered design

Status: **PROPOSED — decisions resolved (Kanav, 2026-10-02); freeze pending the P5-M0 checklist.** The P5-M0 approval commit is the freeze point. After it, nothing below changes except by a recorded decision made before the affected result exists. **No live refresh code exists.**

Decisions recorded in `.agent/phase5/P5_M0_DECISIONS.md`:
- **P5-D1:** fallback Option A with a 72 h threshold;
- **P5-D2:** explicit EPA source states;
- **P5-D3:** adoption gate.

## 0. Problem and constraints

**The problem.** The evaluated production source is D18:
- Statbotics team-event EPA from one verified snapshot (`statbotics_snapshot_20261001T220423Z`);
- the STRATAI fallback for target event 2026iscmp only;
- D13 selection;
- availability rules A1 / A2.

The snapshot is fixed and loaded once. A live Statbotics sync changes `team_event_stats`, after which the D18 loader refuses to load. Ratings therefore cannot use newly concluded events.

**Constraints, all unchanged:**
- **D13 selection:** only the team's other events that concluded before as_of, with the same ordering.
- **A1 / A2** availability rules.
- **No silent fallback** to an older event.
- **Frozen models:** the D18 M5 v2 and M7-pair artifacts. A refresh changes inputs, never models.
- **$0 cost; no LLM.**

**Why only prior events matter.** The target event's own EPA is never used (D13 excludes the target), and in-event information comes from canonical rows strictly before as_of. So a refresh only matters for **prior events that have concluded**.

## 1. Source, event end, and refresh cadence

- **Source:** Statbotics `GET /v3/team_events?event=<key>&limit=1000`. This is the D18 endpoint and schema (`statbotics-v3`), through the existing client and the Phase 2 landing path.
- **Event end.** `event_end(e)` = the scheduled time of the event's last completed match (canonical). This is more precise than `end_date`, a date with no time. The 72 h clock starts here.
- **Trigger.** An event becomes **due** when it has ended: `end_date` has passed and every scheduled match is completed, as detected by `--watch`.
  - A due event is fetched at +1 h, then every 2 h, until its records are processed, and at least once more after 72 h.
- **Processed** is defined per team-event.
  - A record counts as processed when its event's records all have `status` = `"Completed"` and the team's record exists.
  - Checked on the D18 snapshot (2026-10-02), this definition cleanly separates the 140 unprocessed 2026 Israeli records (`"Upcoming"`).
  - It also catches team 4744, which has no 2026isde2 record.
  - `record.total.count` is not used: it matches the canonical completed-match count for only 96.6% of completed team-events (usually off by 1).
- **Daily sweep:** one re-fetch per day of every event ended in the last 14 days, to detect late corrections (L5).
- **Rate:** at least 0.25 s between requests.

## 2. Snapshots and versioning

- **Each fetch** writes an immutable raw file: the canonical JSON, gzip, sha256, `retrieved_at`, endpoint and parameters. It also lands each record in `raw_source_payloads` through the Phase 2 path, as D17 did.
- **A snapshot** is a manifest: event_key → (raw sha256, `retrieved_at`, per-team processed flags). Each refresh writes a new manifest equal to the previous one plus the changed events (copy-on-write).
- **Snapshot identity:** `snapshot_id` = sha256 of the canonical manifest. Manifests form an append-only log, each recording its parent.
- **The frozen D18 snapshot is the log's first entry (its root).** Nothing is ever deleted or overwritten.

## 3. as_of semantics (the leakage rule)

For a lookup (team, target event, as_of):

1. **Snapshot.** Use the newest snapshot created before as_of. A record counts only if its `retrieved_at` < as_of.
2. **Selection.** Run D13 over canonical facts as of as_of. Facts are re-read at every refresh, fixing today's load-once gap.
3. **Statbotics value.** `available_at` = max(D18 `available_at` (A1/A2), `retrieved_at`), and the value is servable only if `available_at` < as_of.
4. **Fallback value.** For a STRATAI fallback value, `available_at` = max(STRATAI `available_at`, `event_end` + 72 h). The fallback can never be used earlier than the rule allows.
5. **Missing candidate.** A D13 candidate with no servable value takes the §5 state for its situation. It never silently becomes "use an older event".

**Why replays are honest.** A historical replay with real `retrieved_at` values cannot use anything that had not been retrieved. Validation therefore uses an explicitly labelled *simulated-retrieval* mode (§9).

## 4. Incremental update behaviour

- **Each refresh:**
  - fetch the due events;
  - verify each raw sha256;
  - normalize with the Phase 2 normalizer and confirm normalized `epa.total_points` equals the `team_event_stats` row (D18's S1 check, per event);
  - write the manifest;
  - re-read canonical facts;
  - swap the in-memory provider atomically.
- **In-flight requests** keep the provider they started with.
- **A refresh that fails any check** writes no manifest. The previous snapshot stays in service.
- **Values are read from snapshot files**, not the mutable table, so a later table change never alters what a past snapshot served.

## 5. EPA source states (P5-D2)

Every served team appearance carries `epa_source_state` and `epa_value_source`:

| `epa_source_state` | Meaning | Value served | `epa_value_source` |
|---|---|---|---|
| `current` | The D13 candidate has a processed Statbotics record, from a snapshot whose refresh cycle is healthy | yes | `statbotics` |
| `stale` | A processed Statbotics record for the D13 candidate, served from the last valid snapshot, while refreshes of *other* events are failing (Statbotics outage). The value is still correct for this candidate | yes, with `snapshot_retrieved_at` | `statbotics` |
| `pending` | The D13 candidate has ended but is not processed, and it ended less than 72 h before as_of | **no**: the lookup is refused (`epa_source_pending`, 422). No older event is used | — |
| `fallback_stratai` | The D13 candidate ended at least 72 h before as_of and is still unprocessed by Statbotics; STRATAI's independent EPA for that team-event is used | yes, labelled **STRATAI EPA** | `stratai_fallback`, with `fallback_reason` = `statbotics_unprocessed_72h` |
| `unavailable` | The D13 candidate has no servable value from either source (e.g. STRATAI has no value or it is not yet available) | **no**: refused (`epa_source_incomplete`, 422) | — |
| `withheld_no_prior_event` | No D13 candidate exists (legitimate absence, as D13 today) | EPA absent (null + reason), not refused | — |

**Rules:**
- A Statbotics record that exists but is unprocessed (e.g. `"Upcoming"`, `matches_played = 0`) is **never** treated as a valid Statbotics value. It is `pending` or `fallback_stratai` by the clock.
- STRATAI never replaces a processed Statbotics value.
- Fallback is decided per team-event and is always labelled.
- **Output level:** a response is `degraded` if any team is `stale` or `fallback_stratai`, and refused if any required team is `pending` or `unavailable`. It lists `stale_events` and `fallback_events`.

## 6. STRATAI fallback (P5-D1: Option A, 72 h)

- **When:** a D13 candidate event ended at least 72 h before as_of and the team's Statbotics record is still unprocessed.
- **What:** STRATAI's independent EPA for that team-event, from the STRATAI engine replayed over the canonical season (`scripts/run_epa_replay`, chained from the previous season as in D15), with STRATAI's own `available_at`.
- **Labelling:** labelled `stratai_fallback` / "STRATAI EPA", with `fallback_reason`.
- **Refresh:** the STRATAI season replay is rerun when a fallback first becomes needed and after each later sync while any fallback is in use. Each replay is a versioned artifact; the fallback value records its replay fingerprint.
- **Before 72 h:** an unprocessed candidate is `pending` and refused. Temporary Statbotics outages never switch methodology early.
- **Evidence:** STRATAI and Statbotics EPA agree closely on shared team-events (Pearson 0.9966–0.9996, mean absolute difference 0.3–0.6 points; `results/epa_source_comparison.json`). This is not a parity claim.

**Consistency with D18.**
- **Historical population:** D18's fallback, for target 2026iscmp, covers appearances whose source events (2026isde1 / 2026isde2) Statbotics never processed. In the historical population (as_of = match time), Option A reaches STRATAI for exactly those cases, and L1 must show identical results on all 319,301 appearances.
- **As-of-now requests:** Option A *does* change behaviour for "as of now" requests. 2026dal, refused today, would be served with the Israeli teams labelled `fallback_stratai`. That is the intended generalization.

**72 h — checked for technical contradictions, none found.**
- In 2024–2026, 107 of 19,554 team transitions into a qualification-bearing event (0.55%) start within 72 h of the team's prior event. Almost all are back-to-back Turkish regionals (2024–2026 tuis2/3/4/5, tuhc).
- For these, a slow Statbotics means `pending` (refused), not fallback. That is a coverage cost, not an inconsistency.
- 167 transitions into playoff-only events (Einstein, DCMP finals) start within 24 h, so they may often be `pending`. They are playoff-scope, which is unvalidated anyway.

## 7. Provenance

- **Per team appearance:**
  - `epa_value_source`, `epa_source_state`, `fallback_reason`;
  - `snapshot_id`, the record's `retrieved_at` and raw sha256;
  - the D18 rule (A1 / A2);
  - for fallbacks, the STRATAI replay fingerprint.
- **Per response:** `snapshot_id`, `snapshot_retrieved_at`, `stale_events`, `fallback_events`, and the model sha256 values.
- **Per refresh:** a log entry with events fetched, outcomes, checks, and parent and new `snapshot_id`.

## 8. Leakage prevention and reproducibility

**Leakage:**
- **Strict:** `retrieved_at` < as_of; fallback not before `event_end` + 72 h; D13's conclusion rule; A1 / A2.
- **Target event excluded:** the target's own (in-event) Statbotics EPA is never used.
- **Point in time:** in-event features come from canonical rows strictly before as_of.
- **Outcomes stay out:** alliance outcomes are never features.

**Reproducibility:**
- `(as_of, snapshot_id, STRATAI replay fingerprint, model sha256s, commit)` determines every output.
- A prediction log stores these per response; a replay tool re-serves any logged prediction bit for bit.

## 9. Adoption and validation status (P5-D3)

**Adoption.** Production keeps the frozen D18 provider until L1–L4 pass and a recorded decision switches it.

**Validation status after adoption.**
- The Phase 4 validation claims apply to the D18-evaluated configuration.
- An output that uses any value from a non-root snapshot, or any `fallback_stratai` value, keeps its base `validation_status` and adds `live_refresh_not_yet_validated`, until L6 passes.
- During 2027 that is every output: a new season is also outside M11's single held-out season.

## 10. Validation — pre-registered (criteria fixed here, before any result)

In-season Statbotics values as they were at the time cannot be retrieved: the API serves current values only. Validation is in two parts.

**Historical part (before adoption; every check must pass):**

- **L1 — equivalence.**
  - **Setup:** the live provider in frozen mode (root snapshot, with `retrieved_at` set to the D18 availability and STRATAI from the D15 chain).
  - **Pass:** results identical to the D18 provider on all 319,301 appearances of 2024–2026, including the 450 `stratai_fallback` appearances.
  - **Tolerance:** none (exact equality).
- **L2 — simulated cadence.** A record becomes retrieved at `event_end` + lag, for lag ∈ {6 h, 24 h, 72 h}, with values from the root snapshot.
  - **Pass (each lag):**
    - 0 served values with `available_at` ≥ as_of;
    - every appearance whose result differs from D18 is explained by the lag;
    - per-state counts are reported.
  - **Diagnostic only:** the M5 v2 midpoint Spearman and the qualification ECE on EPA-complete matches, at lag 24 h, with the frozen models.
- **L3 — outage drill.**
  - **Setup:** injected 5xx and timeouts.
  - **Pass:**
    - no manifest written for a failed refresh;
    - the previous snapshot serves, with `stale` labels;
    - `pending` before 72 h;
    - `fallback_stratai` after 72 h;
    - 0 unlabelled source mixing;
    - an unprocessed record is never served as `statbotics`.
- **L4 — atomicity and reproducibility.**
  - **Setup:** a match-by-match replay of a 2026 event under simulated retrieval.
  - **Pass:**
    - each response names one `snapshot_id`;
    - re-serving every logged prediction is bit-for-bit identical;
    - ratings change only with new canonical rows or new snapshots.

**Prospective part (2027 season):**

- **L5 — value drift.**
  - **Measured:** first processed value vs the value 14 days later, per team-event.
  - **Material drift:** median |Δ| > 0.5 EPA points, or more than 5% of team-events with |Δ| > 2 points.
  - **If material:** first-processed values are labelled `provisional` for 14 days.
- **L6 — live shadow evaluation.**
  - **Setup:** every qualification prediction logged from 2027 week 1.
  - **Evaluation:** after the 2027 regional and district qualification matches, the D18 methodology is applied *unchanged* to the logged EPA-complete live predictions.
  - **`live_validated` requires all of:**
    - qualification ECE < 0.05 (D6);
    - no qualification bin with ≥ 30 predictions deviating by more than 0.05;
    - M5 v2 midpoint Spearman > the live raw-EPA baseline under the same inputs.
