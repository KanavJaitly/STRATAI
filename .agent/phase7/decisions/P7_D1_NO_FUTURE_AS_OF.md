# P7-D1 — No future `as_of` on the P7-M3 POST routes (2026-10-17)

**Status:** implementation decision recorded by Claude Code during P7-M3 (before acceptance and before any example
or result exists). It narrows P7-Q7 and does not widen any contract. It is recorded here, not as a row in the
frozen `P7_M0_DECISIONS.md`, whose blob the freeze pins (the Phase 6 `decisions/` precedent). Sven may reverse it.

**Finding (P7-M3 independent review).** P7-Q7 gave `POST /predictions/win-probability` and
`POST /predictions/alliance-synergy` an optional `as_of`. Both EPA providers treat an event as "prior" when its end
and last completed match are before `as_of` (`ml/ratings/statbotics_primary.py`, `ml/ratings/live_epa.py`). With
`as_of` in the future, an event still in progress counts as prior, so its mid-event EPA could be served as prior
EPA. A qualification pairing could then be labelled `approximately_calibrated_qualification` for a population M7
never evaluated. Before P7-M3 this was impossible, because `as_of` was always now.

**Decision.** On those two routes, an `as_of` later than now by more than 5 minutes (clock skew) is refused with
`invalid_as_of` (422, already declared). One within the skew is treated as now. The default (omitted) is unchanged:
now. Implemented as `api.routes.common.parse_as_of(..., allow_future=False)`.

**Not changed.** The Phase 5 routes (strength, event analysis, qualification forecast) keep their existing `as_of`
behaviour. The qualification forecast already clamps each match to `min(as_of, scheduled_time)`. Whether a future
`as_of` on the strength and event-analysis views has the same exposure is recorded as a known risk for the
Phase-Level Audit, not changed here: changing Phase 5 behaviour is outside P7-M3's scope.

**Contract effect.** None on the locked shapes: `invalid_as_of` was already declared at 422 on both routes.
