# P7-D4 — Mid-Phase Audit corrections (2026-10-18)

**Status:** implementation decision recorded by Claude Code at the Phase 7 Mid-Phase Audit, after P7-M5 and before
P7-M6. No client uses these routes yet, and no example has been captured. Items 2 and 3 change locked entries;
item 1 changes the behaviour of earlier phases' routes without changing their locked shapes.

**1. No route accepts a future `as_of` (extends P7-D1 to every route).**
P7-D1 refused a future `as_of` only on the P7-M3 POST routes. The GET routes, which are the Phase 5 strength, event
analysis and qualification forecast views plus the P7-M4 match discovery, accepted one. Every one of these builds
point-in-time features from the same EPA providers. At a future `as_of` an event still in progress counts as a
completed prior event, so its mid-event EPA could be served as prior EPA, inside outputs labelled for an evaluated
population. P7-M7 composes these views. One rule now applies everywhere
(`api.routes.common.parse_as_of`): a time more than 5 minutes past now is `invalid_as_of` (422), and one within the
skew is now. `invalid_as_of` was already declared on every affected route, so no locked shape changes. Before
this, the Phase-Level Audit risk list carried the exposure on the GET routes.

**2. `GET /events`: `state_prov` is renamed `state_province`.** The same module serves `state_province` on
`GET /events/{event_key}/teams` (P7-M4). One name for one meaning.

**3. Strategy `model.model_version_tag` and `model.model_sha256` are no longer nullable.** The pin requires both,
since P7-M5 refuses a version tag without a sha256, so a served strategy model always has them. A nullable type
would tell Phase 8 to handle a case that cannot occur.

**Not changed (documented instead, docs/phase7.md):**
- **Codes:** the same condition gets different codes on different families. A match with no scheduled time is
  `insufficient_features` on win probability and `match_not_scheduled` on strategy. A match with no competition
  level is an unvalidated 200 on win probability and `match_context_unknown` on strategy. Both are locked earlier
  shapes or engine-driven semantics.
- **Validation vocabularies:** pre-Phase 7 routes keep top-level `validation_status`; Phase 7 results use the
  `validation` block. This is per the spec.
- **Human-input routes:** not locked; decided at P7-M9.
