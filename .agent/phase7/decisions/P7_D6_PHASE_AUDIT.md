# P7-D6 — Phase-Level Audit corrections (2026-10-18)

**Status:** implementation decision recorded by Claude Code during P7-M9, after the independent Phase-Level Audit
and Phase Acceptance Review, before any example was captured and before any frontend work. It changes behaviour
only for matches still ahead. No locked shape changes; the lock check passes without a relock.

**1. Scheduled-match routes use `min(now, scheduled_time)` (audit M1).**
- Before: the six scheduled-match strategy routes (`context_for_match` with no `as_of`) and
  `GET /predictions/matches/{match_key}/win-probability` (Phase 4) took the match's own scheduled time as the
  moment, even when it was still in the future. This caused three problems:
  - A response claimed a future moment while using only data up to now, so it could change between calls.
  - A coach observation dated between now and the match (`observed_at` is caller-asserted) entered the context.
  - The pre-match report for the same match (moment = now) could disagree with the routes it is documented to
    match.
- This contradicted the rule "anything describing a match uses `min(as_of, scheduled_time)`" (docs/phase7.md) and
  P7-D4 (no future moment on any route). It also re-opened the P7-D1 hazard in principle: an event still in
  progress could count as a completed prior event.
- Now: the strategy routes pass `as_of=now`, and the win-probability route uses `min(now, scheduled_time)`.
  - A past match is unchanged: its moment is still its scheduled time, and the predictions goldens pass.
  - An upcoming match is evaluated from what is known now, and the response's `as_of` / `context.as_of` says so.
- Tested: an upcoming match on the strategy route (moment ≤ now; a future-dated coach observation not applied), and
  on the win-probability route.

**2. The examples tooling honours `API_PREFIX` (audit M2; the same class as the Mid-Phase Audit's #1).**
`api.examples.served_path` resolves an example's unmounted path to where it is served. Capture and validation use
it, as `attach_examples` already did. Tested with `API_PREFIX=/api`.

**3. Smaller corrections.**
- Unused imports left by the refactors are removed.
- `ml.playoffs.selection.next_captain` is a public form of `_captain`; the P7-M6 service no longer imports a private
  name. `_captain` stays for the frozen P6 callers.
- The docs now say:
  - `analyze_event` is reused by the pick list, not by the pre-match report;
  - `GET /events/{event_key}/teams` includes playoff-only teams, while the selection pool is the qualification
    roster;
  - `StrategyContextOut.as_of` describes the moment rule.
- `.env.example` lists the strategy and PX pins.
- A misleading comment about the EPA source in the pick-list route is corrected. The source is resolved by the
  dependency on every request; its absence is refused only at step 4. A lazy load would bypass FastAPI's
  dependency overrides.
- The pre-match report passes its already-built match row into `context_for_match`, which reuses a row built at
  exactly the same moment for the same match instead of rebuilding it.
