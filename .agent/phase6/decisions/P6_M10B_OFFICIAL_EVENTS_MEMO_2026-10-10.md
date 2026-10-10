# P6-M10b: what "official events" means for the 2027 population (decision memo, 2026-10-10)

**Status: for Kanav's decision. It changes nothing.**
- The frozen spec `P6_M10B_SPEC.md` (blob `d699afaf`) is unchanged.
- `scripts/phase6_m10b.py final` refuses until a definition is approved (`OFFICIAL_EVENTS_RULE = None`).
- No filter has been guessed or added.

## 1. The question

§5's adopted population text reads: "2027 EPA-complete qualification matches **of official events**, in a 2027 D18 frame built by the same procedure". The spec never defines "official events". v1's population text ("held-out 2026 EPA-complete qualification matches in the same D18 frame") has no such clause.

## 2. Evidence

All of this was read from the isolated `stratai_test` copy and the code, read-only.

| Source | What it says |
|---|---|
| Canonical `events.event_type` | **NULL for every event.** The serving loader does not carry the field (`data/serving/repository.py:81`). It is evidence of nothing and is not used. |
| Raw TBA event payloads (`raw_source_payloads`, `tba` / `event`, current) | TBA's `event_type` integer is present for every stored event: 608 in `events` and all 606 events in the D18 frame. **Every one is type 0–5.** No type 6 (Festival of Champions), 7 (Remote), −1, 99 (Offseason) or 100 (Preseason) event is stored. |
| Ingestion | `data/orchestrator.py`: `OFFICIAL_EVENT_TYPES = {0, 1, 2, 3, 4, 5}` (Regional, District, District Championship, Championship Division, Championship Finals, District Championship Division). `sync_season` loads only these, via `official_event_keys`. The `event_keys` override and single-event or `--watch` syncs bypass this filter. |
| EPA engine | `ml/ratings/epa/constants.py`: excludes only types {99, 100} and overrides `2026isrtp` to District. **`2026isrtp` is not in the store at all**: ingestion's 0–5 filter dropped it. This is a real case where the two existing rules disagree. |
| Other population code | Phase 5's selection uses explicit type sets (`REGIONAL_OR_DISTRICT = (0, 1)`, Championship Division = 3). `data/rulesets.py` never derives ruleset membership from `events.event_type`. No Phase 6 code defines "official". |

**Existing populations by raw TBA type.** These are EPA-complete qualification matches, ties excluded:

| Season | Regional (0) | District (1) | DCMP (2) | CMP Division (3) | DCMP Division (5) | Total | Other types |
|---|---|---|---|---|---|---|---|
| 2024 | 303 | 1,911 | 658 | 983 | 871 | 4,726 | 0 |
| 2025 | 3,222 | 5,333 | 704 | 995 | 884 | 11,138 | 0 |
| 2026 | 2,750 | 6,594 | 1,032 | 975 | 894 | 12,245 | 0 |

Type 4 (Championship Finals) has no qualification matches. v1's 2026 evaluation scored 12,215 of the 12,245 rows; the 30 others lack a causal scale.

## 3. Plausible definitions

| | Definition | Effect on 2024–2026 populations | Effect on 2027 | Risks |
|---|---|---|---|---|
| **D1** | TBA `event_type` ∈ {0, 1, 2, 3, 4, 5}, read from each event's current raw TBA payload. This is ingestion's existing `OFFICIAL_EVENT_TYPES`. | None: all stored rows already qualify. v1's population is unchanged. | Identical to a frame built from `sync_season`. Removes any event added outside it (single-event or `--watch` syncs, `event_keys`) whose type is outside 0–5. | Excludes events TBA mislabels that the EPA reference treats as official (cf. `2026isrtp`); such events are not ingested anyway. Excludes Festival of Champions. Depends on a raw payload existing for each event. |
| **D2** | Every event except offseason and preseason: `event_type` ∉ {99, 100}, after `EVENT_TYPE_OVERRIDES`. This is the EPA engine's rule. | None (no such events are stored). | Would also admit Festival of Champions (6), Remote (7) and override events, **if** they were ingested. `sync_season` does not ingest them, so in practice it equals D1 unless ingestion changes. | Festival of Champions is a post-season exhibition with an atypical field. The override list is maintained for EPA, not for evaluation populations. Two rules for one population raise the chance of drift. |
| **D3** | Regional and district play only: {0, 1, 2, 5}, excluding Championship divisions (3). | **Changes v1's population:** 2026 loses 975 rows (8.0%). | Removes Championship divisions, the strongest field. | Breaks "built by the same procedure" relative to v1. Smaller n. Removes the highest-skill matches, so the gate would be tested on a narrower population. Not recommended. |
| D4 | No explicit rule: whatever the 2027 frame contains. | None. | Equals D1 only if every 2027 event entered through `sync_season`. | Implicit, and not checkable from the frame. This is the silent reuse of the v1 population that the instruction excludes. **Considered and rejected.** |

The 2027 effect cannot be measured yet: no 2027 data exists. Every stored row from 2024–2026 satisfies D1 and D2, so on this history D1 and D2 select identical populations.

## 4. Recommendation

**D1, made explicit and checked.** It is the codebase's existing definition of an official event, the rule that produced every row v1 and the 2024–2026 frame contain, and the narrowest rule that never changes the historical population.

**Proposed amendment text** (versioned amendment A1 to `P6_M10B_SPEC.md`, written before any 2027 data):

> "Official events" in §5 means TBA `event_type` ∈ {0, 1, 2, 3, 4, 5} (`data.orchestrator.OFFICIAL_EVENT_TYPES`), read from each event's current raw TBA event payload in `raw_source_payloads`. Rows of any other type are excluded and counted by type. If any evaluated event has no current raw TBA event payload, the run is refused, since its type cannot be established. Canonical `events.event_type` is never used.

**Implementation after approval:**
- `OFFICIAL_EVENTS_RULE` set to A1's blob;
- the check in `final`;
- the per-type counts in the outcome record;
- tests.

**Process:**
- The frozen blob `d699afaf` stays.
- A1 is its own file with its own blob, recorded in the outcome record.
- Kanav's authorization file for the 2027 run should name it.

## 5. Decisions needed from Kanav

1. Choose a definition (D1 recommended; D2 or D3, or another).
2. Approve the versioned amendment text, dated, before any 2027 data is synced.
