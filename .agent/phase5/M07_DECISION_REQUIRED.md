# P5-M7 — flagged decision Q2 (human decision required; raised 2026-10-03, before any (b) or (c) result)

**Status: OPEN.** Criterion (a), adapter parity, is run and recorded. Criteria (b) (false alarms) and (c) (real
flags) are not run until Q2 is decided. The decision must be made before their results exist (P5-M0 freeze rule).

## What the frozen spec leaves open

P5-M7's methodology says: "a two-sample test of a component's share, week w vs weeks < w, Holm-corrected across
components at α = 0.05, reported with its effect size". Criterion (b) checks it with "1,000 within-season
week-label permutations". The spec does not fix three things:

1. **The test statistic.** Welch t, Mann–Whitney, a permutation test, or something else.
2. **The unit of analysis.** Either alliance-match rows or events. A week label belongs to an event, so (b)'s
   permutation null moves whole events. Alliance-match shares within one event are not independent: the same
   teams, field and referees. So a row-level test is likely anti-conservative against an event-level null,
   which (b) would then record as a failure.
3. **The share's denominator** (minor). Recommended: the official score, `totalPoints`, with total = 0 rows
   excluded as undefined. "Family-wise" is read as the Holm family, i.e. the four components at one
   (season, week).

These choices are outcome-relevant: they decide whether (b) can pass. Choosing one after looking at (b) would be
fitting the method to the test.

## Options

**Option 1 (recommended): event-level Welch.**
- **Unit:** the event. Each event's mean component share.
- **Test:** Welch's two-sample t-test, week w's events against earlier weeks' events.
- **Effect size:** the difference in mean share, in percentage points.
- **Why:** it matches the unit that (b)'s permutation null exchanges.

**Option 2: row-level Welch.**
- **Unit:** alliance-match rows.
- **Test:** Welch's t-test.
- **Effect size:** the difference in mean share.
- **Trade-off:** more power, but within-event dependence makes its p-values too small under an event-level
  null.

Both are implemented in `ml/meta/weekly.py`, selected by a required `test` argument (`event_welch` or
`row_welch`), with no default.

## Also recorded (not a decision)

- **Endgame per season** follows TBA's own labels:
  - 2024: `endGameTotalStagePoints`;
  - 2025: `endGameBargePoints`;
  - 2026: `hubScore.endgamePoints` + `endGameTowerPoints`.
  Each is verified to sit inside that season's teleop total on 100% of rows (`ml/features/score_components.py`).
- **Events without a TBA week** (championship and off-season) are outside the weekly series, and are counted in
  the (a) record.

**Decision needed from:** Kanav. Record it as a new dated row in `P5_M0_DECISIONS.md`.
