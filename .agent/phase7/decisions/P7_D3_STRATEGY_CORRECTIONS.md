# P7-D3 — Match strategy corrections before P7-M5 acceptance (2026-10-18)

**Status:** implementation decision recorded by Claude Code during P7-M5. It was made after the P7-M5 independent
review and before acceptance, before any example was captured and before any client used these routes. Item 1
changes locked entries; item 2 adds an optional parameter to a Phase 6 function without changing its default
behaviour.

**1. The strategy responses carry the EPA source envelope (`epa: EpaSourceInfo`).**
Strategy odds come from features built through the configured EPA source, like every other EPA-backed route. Every
such route serves `epa_info(...)`: the source's identity, whether it is the evaluated configuration, the P5-D3
adoption, and `live_refresh_not_yet_validated` when it applies. Without it, a client could not see that the source
in use is not the configuration P6-M10 was fitted on, or that a live-refresh value was used. That is a label the
other routes carry, so its absence was a labelling gap. Added to all three read response types: `assess`,
`recommend` and `compare`.

**2. Coach observations count only once stored before `as_of`.**
`observed_at` is caller-asserted. Filtering only on it let an observation posted later, but back-dated, change the
evaluation of an earlier moment, so a past evaluation was not reproducible.
`ml.strategy.coach_inputs.load_coach_observations` gains `landed_before=`, which also requires
`raw_source_payloads.ingested_at < landed_before`. It defaults to None, keeping the Phase 6 behaviour and
leaving the frozen P6 scripts and records unaffected. The P7 service passes `landed_before=as_of` for both
paths. The invalid-submission count is restricted the same way.

**Considered, not changed:** restricting a context's observations to the six teams in the match. It would cut the
recommend cost and drop the `coach_observation_effect_unmeasured` reason for observations about other teams. That
changes the engine's labelling rule as P6-M12/P6-M13 used it, so it is left for a separate decision. The latency's
dependence on observation count is measured and documented instead (M05_ACCEPTANCE.md).
