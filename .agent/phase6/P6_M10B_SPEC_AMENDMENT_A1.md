# P6-M10b specification, amendment A1: "official events" (Kanav, 2026-10-10)

**Amends:** `.agent/phase6/P6_M10B_SPEC.md`, blob `d699afafc01d42904c7afc7c7e209f8007a6a207`, §5 (evaluation population) only. That file is not edited; its blob is unchanged. This amendment is its own versioned file with its own blob, frozen by `decisions/P6_M10B_A1_FREEZE_2026-10-10.md` before any 2027 data exists.

**Source:** definition D1 of `decisions/P6_M10B_OFFICIAL_EVENTS_MEMO_2026-10-10.md`, adopted by Kanav on 2026-10-10.

## A1.1 Definition (the memo's draft text)

"Official events" in §5 means TBA `event_type` ∈ {0, 1, 2, 3, 4, 5} (`data.orchestrator.OFFICIAL_EVENT_TYPES`), read from each event's current raw TBA event payload in `raw_source_payloads`. Rows of any other type are excluded and counted by type. If any evaluated event has no current raw TBA event payload, the run is refused, since its type cannot be established. Canonical `events.event_type` is never used.

## A1.2 Conditions of adoption (Kanav, 2026-10-10)

- The type is the raw TBA event payload's `event_type`. Only the existing `OFFICIAL_EVENT_TYPES` set (0–5) is accepted.
- **Fail closed:** the run is refused if, for any evaluated event, the current raw TBA event payload is unavailable, or its `event_type` is absent or not an integer (a boolean is not an integer).
- An event type is never inferred from the canonical `events.event_type`, which is NULL because the serving loader does not carry it.
- The reported scope and exclusions are preserved: the outcome record reports the evaluated rows' counts by event type and the excluded rows by reason, including `non_official_event_type:<type>`.

## A1.3 Unchanged

Everything else in `P6_M10B_SPEC.md`: the model, groups, fit, DEV-M10b (§4, whose 2024–2026 populations are v1's and are not governed by this §5 text), gates, thresholds, constants, run controls, the serving guard and the tests.

**Application:** `scripts/phase6_m10b.py final` applies A1 and pins this file's blob. Kanav's 2027 authorization file names that blob as `amendment_a1_blob`.
