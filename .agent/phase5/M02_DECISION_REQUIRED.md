# P5-M2 — flagged decision Q1 (human decision required; raised 2026-10-02, before any L1–L4 result)

**Status: OPEN.** No L1 or L2 result has been computed. L1 and L2 are not run until this is decided, so that the
decision is made before the affected result exists (P5-M0 freeze rule).

## The inconsistency in the frozen design

`LIVE_EPA_REFRESH_DESIGN.md` says two things that cannot both hold:

1. **§3 step 5:** "A D13 candidate with no servable value takes the §5 state for its situation. It never silently
   becomes 'use an older event'." §3 step 3 defines servable to include D18's A1/A2 availability, and §3 step 1
   counts a record only if `retrieved_at < as_of`.
2. **§10 L1:** the live provider in frozen mode ("root snapshot, with `retrieved_at` set to the D18 availability")
   must give results **identical to D18 on all 319,301 appearances**.

But **D18's A1/A2 rule skips** a candidate whose value is not yet available and considers the next (older) D13
candidate (`ml/ratings/statbotics_primary.py`; D18 spec §3). §0 of the design lists "A1/A2 availability rules"
as unchanged. P5-D1's rationale checked L1 only for the 450 fallback appearances, not for availability skips.

In L1's frozen setup, `retrieved_at` equals the D18 availability, so "not yet available" and "not yet retrieved"
coincide. Read literally (§3.1 + §3.5), such a candidate is "ended but not processed" and becomes
`pending` / `fallback_stratai` / `unavailable`. D18 instead skips it.

**Size (read-only count over the D18 provider; not a recorded result):** 1,817 of the 319,301 appearances
involve an availability skip.

| Season | Served an older event after a skip | Withheld after a skip |
|---|---|---|
| 2024 | 360 | 674 |
| 2025 | 353 | 0 |
| 2026 | 425 | 5 |

The 450 `stratai_fallback` appearances are not affected (their first D13 candidate is unprocessed, as P5-D1 found).

## Options

**Option 1 (recommended): A1/A2 keeps D18's skip.**
- The A1/A2 availability rule is unchanged, skip included. As in D18 and `ml/ratings/provider.py` ("only ever
  removes candidates"), it removes a candidate whose value is not yet available.
- It is evaluated before retrieval. In live mode it can only be evaluated on a retrieved record.
- A candidate that is A1/A2-available but not yet retrieved or processed takes its §5 state, so §3.5 still
  governs every retrieval or processing gap.
- **Effect:** L1 can pass as frozen. L2's "every difference is explained by the lag" is then exactly the
  retrieval effect.
- **Simulation caveat:** in simulated retrieval, A1/A2 is checked on the record before its simulated retrieval
  (it decides a skip, never a value).

**Option 2: literal §3.5.**
- Every candidate without a servable value takes a §5 state. A processed record not yet A1/A2-available is
  `unavailable` (refused).
- **Effect:** L1 fails on the 1,817 appearances. Under P5-M2's rule "a failure in L1–L4 stops and escalates",
  P5-M2 stops.
- **Live behaviour:** many week-1 and A1 (season-end) lookups would be refused rather than served from an older
  event.

## What was built meanwhile (no result computed)

- **Policy parameter:** the live provider takes the policy as a required, explicit argument
  (`a1a2_policy="d18_skip"` for Option 1, `"literal_state"` for Option 2), with no default. Both branches are
  unit-tested.
- **Not run:** L1 and L2.
- **Run:** L3 (an injected-outage drill) and L4 (an atomicity replay), each checked to give identical results
  under both policies. Their records say so.

**Decision needed from:** Kanav (P5-D3 owner). Record it as a new dated row in `P5_M0_DECISIONS.md`.
