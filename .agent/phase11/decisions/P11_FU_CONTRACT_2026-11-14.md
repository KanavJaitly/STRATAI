# P11 follow-up: contract changes to the live-draft operations (2026-11-14)

**Decided by:** Kanav (owner), 2026-11-14, in the session that approved the Phase 11 follow-up plan
("alliance-aware recommendations and team profiles on the live draft page").

**Countersignature (Sven Morais):** ______________________ (date: __________)

**Status:** decided by Kanav. Nothing in this record is accepted or validated; it only permits the contract changes
below.

## What is permitted

The Phase 7 contract lock (`docs/api_contract_lock.json`, `python -m scripts.phase7_contract_lock`) pins the ten
`/workspace/alliance-selection/drafts…` operations. Kanav approved these changes to two of their response shapes:

1. **Additive, optional: `HistoryOut.team_number` and `HistoryOut.seed`** (Part A).
   - They give the team and alliance a history entry is about: a draft action's own, or a correction's replacement's.
     They are null for entries about no single team (configure, undo, close, reopen).
   - Why: the live page opens a team's profile from every team number, including history entries. Without these
     fields the client would have to parse the server's summary text.
   - Applies to: `GET/POST /workspace/alliance-selection/drafts…` (every operation returning `DraftOut`).
2. **Additive, optional fields on `RecommendedOut` and `RecommendationsOut`** (Part B, P11-FB2).
   - On `RecommendedOut`: the projected alliance score, the members it assumes, the per-component gaps filled, the
     qualification rank, the decline flag, and the fixed-template reasons.
   - On `RecommendationsOut`: `candidate_projections`, the same projection and reasons for every available team, so
     the profile drawer can show "projected score with your alliance" for any team.
   - Every new field is optional, so a consumer of the old shape is unaffected.
3. **A changed leaf: `RecommendationsOut.source` gains the value `"fallback_p11_fb2"`** (Part B).
   - Why: FB2 replaces FB1 as the served fallback (decision P11-FB2,
     `P11_FB2_DECISION_2026-11-14.md`). Serving it under the label `fallback_p11_fb1` would mislabel it.
   - `"engine_p6_m7"` and `"fallback_p11_fb1"` stay valid values. FB1 stays in the code as a pure function, used by
     tests and by the replay comparison; it is no longer served.

## What is not permitted

- No new operation.
- No other locked leaf changes.
- No change to any `/events/{event_key}/alliance-selection/…` operation.

## How it is applied

- Part A: `relock --reason … --decision ".agent/phase11/decisions/P11_FU_CONTRACT_2026-11-14.md … 2026-11-14"` for
  the two additive `HistoryOut` leaves.
- Part B: one relock for the additive fields and the `source` value, citing this record and the P11-FB2 record.
- After each relock, `python -m scripts.phase7_contract_lock check` must show no changed and no added leaves.
