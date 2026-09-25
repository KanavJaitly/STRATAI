# Phase 4 Execution Plan — ML Models

Source: `docs/P4Milestones.md` (13-milestone authoritative plan). Phase done-means:
win-prob calibrated (60% → 58–62% held-out), ranking beats raw-EPA baseline on a
held-out season.

## Status at plan time

M1 (leakage-safe feature assembly) and M2 (labeled dataset builder) are already
done, both dated before Phase Execution Mode's adoption (2026-09-24) — see
`RUNNING_NOTES.md`. Per `.agent/README.md`, no retroactive `.agent/` artifacts are
created for them. This plan covers M3–M13.

## Milestone order and dependencies

M3 (backtest harness + Model protocol) is the foundation everything after it
validates through — built first, no dependency beyond M1/M2's existing outputs.
M4 (locked baselines) depends on M2 (dataset) + M3 (harness). M5 (ranking model)
and M6 (win-prob model) each depend on M1+M2+M3+M4. M7 (calibration) depends on
M6. M8 (bias/leakage audit) depends on M5+M6. M9 (alliance synergy) depends on
M1 (team_metrics-shaped features) + M5/M6 outputs. M10 (model registry) depends
on M5+M6 existing as artifacts to register. M11 (cross-season guard) touches
M1's feature adapters, M2's dataset builder, and M5/M6's models. M12 (API
endpoints) depends on M10 (registry) + M6 + M9. M13 (docs + sign-off) depends
on all of the above.

## Major interfaces

- `Model` protocol (M3): `fit`, `predict_win_prob`, `predict_rating`, `save`,
  `load` — every model from M5 onward must conform to exactly this.
- `TrainingFrameResult`/`TrainingRow` (M2, already built): the dataset
  interface the backtest harness consumes.
- `MatchFeatureRow`/`TeamFeatures` (M1, already built): the feature interface
  every model ultimately reads from.

## Architectural / statistical risks

1. **Primary phase risk, updated 2026-09-25 — partially resolved, partially
   still open.** The original database blocker (no reachable PostgreSQL) is
   fully resolved: PostgreSQL 18.6 is running, migrated, and full seasons
   2024/2025/2026 are synced TBA-side (608/608 events, 0 errors), and event
   rankings are synced for all 608 events too. A clean isolated full-suite
   run passes completely (1043/1043). What remains open is Statbotics: the
   API has been returning HTTP 500 on every substantive endpoint since this
   was first checked (independently verified via direct curl against the
   codebase's own exact endpoints, not just similar ones, and not just this
   codebase's own retry wrapper), and both M4 baselines are defined in terms
   of real EPA, so their real, dated numbers stay blocked until Statbotics
   recovers — and by extension M5/M6's beats-baseline acceptance gates,
   which need M4's frozen numbers to compare against. Rechecked at sensible
   intervals, not hammered. The ranking-ground-truth gap named below in item
   4a is now CLOSED (`data/rankings.py`, built 2026-09-25) — it turned out
   to depend on TBA's own `/event/{event_key}/rankings`, entirely
   independent of Statbotics.
2. ~~Symmetry-by-construction for the win-prob model (M6) is a structural
   requirement~~ — **RESOLVED 2026-09-25.** `ml/models/win_prob.py`'s
   `WinProbXGBModel` uses p(R,B) = (raw(R,B) + (1-raw(B,R))) / 2, which
   algebraically forces exact symmetry for any underlying predictor,
   including a tree ensemble that is not itself an odd function of a
   feature difference — designed in from the start, not retrofitted.
3. ~~M8's bias audit needs a deliberately-leaky fixture model~~ —
   **RESOLVED 2026-09-25.** `scripts/ml_bias_audit.py` built and ACCEPTED
   (`M08_ACCEPTANCE.md`); two deliberately-broken fixtures
   (`_ConstantAsymmetricWinProbModel`, `_ConstantRatingModel`) each proven
   to fail the specific check they violate.
4. **M11 (cross-season) — investigated 2026-09-25, found to have no real
   scope yet, DEFERRED (human-confirmed).** Grepped the entire `data/` and
   `ml/` packages for `score_breakdown`: it is never parsed or consumed
   anywhere, only mentioned in two comments. There is no existing feature
   for "season-aware feature adapters" to adapt, so building the guard now
   would be speculative structure with no consumer -- the same
   anti-pattern this phase already rejected once (M1's discarded
   schema-only draft, RUNNING_NOTES.md 2026-09-21). Revisit if/when a
   future feature actually reads score_breakdown.
5. ~~No canonical source of a team's real final event ranking anywhere in
   this codebase (found during M03's own Challenge step)~~ — **RESOLVED
   2026-09-25.** TBA's own `/event/{event_key}/rankings` (confirmed against
   TBA's live OpenAPI spec) needed no Statbotics dependency at all.
   `data/rankings.py` lands and reads it back via the existing
   RawPayloadWriter, no new canonical table. Unblocks M04's ranking baseline
   and M05's entire success criterion once real rankings are synced for the
   held-out season.

## Milestones likely to need independent (adversarial) review beyond the
normal Phase F pass

M6 (win-prob symmetry is a CLAUDE.md critical constraint — "unbiased"), M8
(the audit's whole job is catching bias, so it must be tested against a known-
bad model), M11 (cross-season silent-miscompute risk).

## Verification strategy

Pure logic/math (Model protocol conformance, harness split integrity, metric
correctness against hand-computed values) is tested unconditionally — no
database required, so no environment gap excuses skipping it. Anything
touching real historical data follows the established `requires_db` pattern:
written, DB-gated, skips cleanly here. Milestones whose own "Success looks
like" text requires a *real* frozen/held-out number (M4 onward) will be
built and unit-tested in full, but their acceptance gate cannot fully close
without a reachable database with real synced season data — this will be
reported plainly when reached, not silently waived.

## Next

M3, M8, M9, M10, M12 ACCEPTED. M4/M5/M6/M7 code-complete, acceptance
blocked on Statbotics (real EPA data, and M7's real reliability diagram
needs M6's real backtest) — see PHASE_STATUS.md. M11 DEFERRED: nothing in
this codebase reads score_breakdown at all (confirmed by grep), so there
is no existing consumer for "season-aware feature adapters" to adapt;
human confirmed skipping it for now rather than inventing speculative
scope. Remaining dependency-independent work: M13 (docs + sign-off) can
have its docs-contract-test infrastructure built now, but its actual
sign-off content needs M4-M7's real numbers, so it is naturally blocked
too until Statbotics recovers. Recheck Statbotics at sensible intervals;
once it recovers, run M4's real backtest, freeze real numbers, accept M4,
then M5/M6/M7 in turn, then close M13.
