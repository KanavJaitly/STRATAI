# P7-D2 — Discovery read corrections before P7-M4 acceptance (2026-10-18)

**Status:** implementation decision recorded by Claude Code during P7-M4. It was made after the P7-M4 independent
review and before acceptance, before any example was captured and before any client used these routes. It changes
locked entries, so the lock records it with this decision.

**1. Playoff matches appear only once available (look-ahead fix, review finding high).**
`GET /events/{event_key}/matches` listed every playoff match and its alliances regardless of `as_of`. That revealed
the alliance-selection outcome before selection, and, through which alliances fill later bracket matches, results
the route was withholding. Now a playoff match is listed only once it was scheduled before `as_of`, and a playoff
match without a scheduled time is never listed (data/replay.py: playoff matches "appear only once played").
The qualification schedule stays always visible, because it is published before the event.

**2. `event_type` removed from `GET /events`.** Nothing writes `events.event_type`
(data/serving/repository.py: "canonical-only column ... NULL on insert"), so the field was always null. A locked
field that can never carry a value would mislead Phase 8.

**3. Documentation corrections (no shape change).**
- `winning_alliance` is red, blue or tie (data/staging/normalizer.py), and null only when the record has none.
- Results use `scheduled_time` as the availability proxy, as the feature assembler does: a late match's result can
  show early, and a result is the score as stored now.
- Match order is scheduled time, then qualification before playoffs, then set and match number.
