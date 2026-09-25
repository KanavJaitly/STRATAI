# Phase 4 — Milestone 9 Acceptance: Alliance Synergy Scoring Function

## Completed Milestone

Milestone 9 of `docs/P4Milestones.md`'s 13-milestone plan: `ml/synergy/score.py`'s
`alliance_synergy(team_a, team_b, team_c) -> AllianceSynergyScore`, a pure,
deterministic scoring function over three teams' point-in-time `TeamFeatures`.

**Accepted in full.** Like M8, this milestone's own "Success looks like"/"What to
test" criteria need no real Statbotics/EPA data and no real backtest — every
requirement is a property of the documented formula itself, verifiable against
hand-constructed fixtures with a known, deliberately-designed relationship between
inputs and expected output. Nothing here is blocked by the ongoing Statbotics outage.

## Files Modified/Created

- `ml/synergy/score.py` (new) — `SynergyWeights`, `DEFAULT_SYNERGY_WEIGHTS`,
  `AllianceSynergyScore`, `alliance_synergy`.
- `ml/synergy/__init__.py` (new).
- `tests/test_ml_synergy_score.py` (new) — 13 tests.

## Architectural Decisions

1. **No stored "role" field exists anywhere in this codebase's schema** — confirmed
   directly against `TeamFeatures` before writing any code, not assumed. "Role fit"
   and "scoring-distribution complementarity" are therefore both computed as SHARE
   VECTORS (each team's value on one axis divided by the alliance's total on that
   same axis), a dimensionless `[0, 1]` quantity — the only way to make
   `average_score` (raw game points), `defense_score`/`feeding_score` (0–5 scale),
   and `epa_auto`/`epa_teleop`/`epa_endgame` (Statbotics' own units) comparable at
   all without inventing a cross-unit conversion.
2. **This decision point was escalated to Kanav before implementation**, per
   `MASTER_BUILD.md`'s "explain the proposed solution, wait for approval" instruction
   — the milestone's own brief leaves the actual synergy formula genuinely
   underspecified (a real strategy/domain question, not just an engineering one), so
   an "implicit role vectors + diversity score" approach (over a fixed rubric of
   named archetypes, or deferring the milestone) was proposed and confirmed rather
   than guessed at.
3. **Three components, matching the milestone's own literal three-part wording, kept
   deliberately non-redundant:** `role_fit` (share-vector diversity over
   average_score/defense_score/feeding_score — does the alliance cover distinct
   *functions*), `scoring_distribution` (share-vector diversity over
   epa_auto/epa_teleop/epa_endgame — WITHIN scoring, does the alliance cover distinct
   *game phases*), and `defense_feeding_coverage` (mean of present defense/feeding
   values, never zero-filled for absence).
4. **An axis is only usable for role_fit/scoring_distribution if ALL THREE teams have
   that field's presence flag True** — mirrors `ml.models.baselines._alliance_epa_sum`'s
   existing "any absence excludes the whole aggregate" precedent, applied per-axis
   rather than blanket-across-every-axis (a team missing only `feeding_score` should
   not also blank out an otherwise-computable `average_score` comparison).
5. **Diversity is `1 - mean pairwise cosine similarity`**, a real, well-understood
   metric rather than an invented one: three identical share vectors give similarity 1
   (diversity 0, fully redundant); three vectors on non-overlapping axes give
   similarity 0 (diversity 1, fully complementary). A single usable axis structurally
   gives diversity exactly 0.0 (cosine similarity of any two same-signed 1-D vectors
   is always 1) — real linear algebra, documented in the module docstring, not an
   approximation — and is distinct from the zero-usable-axes case, which reports
   `None`, not a fabricated `0.0`.
6. **`overall_score` renormalizes the configured weights over only the components
   that computed to a real value** (mirrors `run_ranking_backtest`'s "excluded, not
   fabricated" handling of an event with no `final_ranks` entry), and is `None` only
   when literally none of the three components could be computed. `confidence` is
   tracked separately from `overall_score` itself — a low-confidence score and a low
   score are different claims, and conflating them would assert certainty the
   function never actually had.

## Tests Added & Executed

`tests/test_ml_synergy_score.py` — 13 tests, all passing on first real run:
- **Complementarity** (the milestone's own named test): two alliances with the
  identical alliance-total `average_score` (190) — one three near-identical "pure
  scorers", one a scorer+defender+feeder — the complementary alliance scores
  strictly higher, both overall and on `role_fit_term` alone.
- Three identical teams give exactly `0.0` diversity (real math, not approximate);
  three orthogonal EPA specialists give `scoring_distribution_term > 0.9`.
- **Determinism + weight-config** (the milestone's own named test): identical inputs
  give an identical result object; an all-weight-on-one-component configuration
  makes `overall_score` exactly equal that one component's own term.
- `SynergyWeights` rejects a negative component and an all-zero configuration.
- **Insufficient-data honesty** (the milestone's own named test): a team missing all
  defense/feeding data does not change the coverage *term* (present values only,
  never zero-filled) but does reduce `present_count`/`confidence` — the exact
  "reflects absence via presence flag, not 0" requirement, checked as two separate
  assertions so a term-value regression and a confidence regression would each be
  caught independently.
- Zero usable axes reports `None`; exactly one usable axis reports `0.0` — the two
  are deliberately different and both pinned.
- One team missing one field excludes only that axis, not the whole axis group.
- Default weights sum to 1.0 (documented starting point); `overall_score`/`confidence`
  stay within their documented `[0, 1]` bounds on a fully-populated fixture.

## Terminal Verification Status

```
python -m pytest tests/test_ml_synergy_score.py -v
13 passed in 1.37s
```

Full repository suite, isolated (no concurrent background job):

```
python -m pytest -q
1154 passed, 2 warnings in 352.39s
```

Zero regressions against the 1141-passed baseline immediately prior (1154 = 1141 + 13 new).

## Issues Found During Implementation

None requiring a fix — every test passed on first write, including the deliberately
tight `test_complementary_alliance_scores_higher_than_redundant_at_equal_raw_scoring`
fixture (constructed so both alliances share the exact same alliance-total
`average_score`, isolating that the score rewards distribution shape, not raw total).

## Remaining Known Risks

None new. Not affected by the Statbotics outage. The chosen weights
(`role_fit=0.4, scoring_distribution=0.3, defense_feeding_coverage=0.3`) are a
documented starting point, not validated against any real strategist judgment or
real event outcomes — explicitly out of scope for this milestone (there is no ground
truth for "correct" synergy to validate against), and callable with different weights
via the `weights` parameter without any code change.

## Roadmap Satisfaction

- "Deterministic, explainable score an experienced strategist could reconstruct from
  the docs" — every component and the exact formula is in this file's own module
  docstring; `AllianceSynergyScore` exposes each component and which axes
  contributed, not just a final number. ✅
- "Two high scorers with redundant roles score lower than a complementary pairing —
  synergy != sum of EPA" — pinned directly, at equal alliance-total raw scoring. ✅
- "Missing defense/feeding lowers confidence rather than silently zeroing coverage" —
  pinned directly, as two independent assertions (term unaffected, confidence
  reduced). ✅
- "Pure function on team_metrics + model outputs" — no database, no model fitting;
  operates only on `ml.features.assembler.TeamFeatures`. ✅
- "Explicitly not the pick-list optimizer" — no alliance-selection, ranking, or
  optimization logic anywhere in this module; scores exactly one supplied triple. ✅

## Production Readiness

Ready for a future pick-list optimizer (Phase 6) to call per-candidate-alliance.
`weights` is a keyword parameter with a documented default, so a future product
decision to retune it needs no code change to this module.

## Readiness for Next Milestone

M9 is fully accepted. Continuing dependency-independent progress into M10 (model
registry) next — fully mechanical, needs no new domain judgment calls, and M5/M6
already produce real `save()`-able artifacts to register.
