# D-PX1-1..5 implementation: pre-run report (2026-10-06)

**Implementation:** `f5dba21` on `phase6/build`. Decisions: `P6_PX1_COMPOSITION_DECISIONS.md` (`b5b02dd`, approved by Kanav 2026-10-06 together with C1 and C2).

**Validation was not run.** `scripts/phase6_playoff_track.py` refuses every milestone, writing nothing, until approved P6-M1 rulesets exist for 2024, 2025 and 2026. Checked on the isolated copy:

> `BLOCKED: no approved P6-M1 ruleset for [2024, 2025, 2026]`

**Rulesets are human input:**
- entered from the manuals by a person;
- approved by a different named person;
- migration 0011 applied to serving with Kanav's approval.

None of these can be done by Claude. PX-1, PX-2, PX-4, M6 (b) and M8 therefore remain unrun, so there are **no metrics and no pass/fail** yet.

## Unchanged (verified)

**Byte-for-byte unchanged** (`git diff HEAD` empty):
- `docs/P6Milestones.md`, `.agent/phase6/P6_M0_DECISIONS.md`, `docs/ROADMAP.md`, `docs/P5Milestones.md` (also hash-checked by `tests/test_phase6_contract.py`);
- `.agent/phase6/P6_M2_PX1_SPEC.md`, `.agent/phase6/P6_M10_MODEL_SPEC.md`;
- every record in `.agent/phase6/results/`;
- the research package.

**Semantically unchanged:**
- the PX-1 objective, features (composition sums, seed difference, round interactions), C = 1.0, scaling, train 2024–2025 / held-out 2026;
- the PX-2 slice definition and gate constants;
- the PX-4 metrics and gate;
- the M8 / P6-Q1 identification rule and > 50% criterion;
- P6-M10 and the Phase 4 models.

## Schema

`p6-ruleset-v3` adds `selection.unresolved: [{field, note, sources_checked}]`.
- `captain_rule` and `declined_team_may_become_captain` may be `null` **only** with a matching entry.
- v1 and v2 rulesets are refused (none was ever stored).

## Projected populations (DRY RUN with SYNTHETIC rulesets; not evidence)

**What this is:** a read-only dry run of the implemented code on the isolated copy, 0.7 min.
- It uses the test-fixture bracket and roster rule, a 3-pick variant for the 8 division keys, and the 3 anomaly exclusions.
- It confirms the code reproduces the diagnostic counts.
- The real numbers will come from the approved rulesets. Their roster rule decides the small-event cases, which here depend on the fixture's 24-team threshold.

| | 2024 | 2025 | 2026 |
|---|---|---|---|
| Championship-division events (from the variant) | `arc` `cur` `dal` `gal` `hop` `joh` `mil` `new` | same | same |
| **PX-1 rows excluded, `four_member_alliance`** | **120** | **122** | **122** |
| PX-1 events excluded at P6-M1, anomalies (`event_exclusions`) | `2024isde2` (0 EPA-complete rows) | — | `2026tuak2`, `2026tuis4` (16 rows) |
| PX-1 eligible rows (projected) | 1,006 | 2,459 | 2,645 |
| **PX-4 / M8 (2026): intended → validated events** | — | — | **204 → 196** (8 excluded, 64 alliances, `four_member_alliance`, variant `three_picks`) |

- **PX-2 slice:** the last 20% of the 2025 eligible rows, about 492 rows projected.
- **Real exclusion counts** are recorded per event in each run record: `rows.excluded_by_event` (PX-1) and `population` (PX-4, M8). Each record carries the decisions' git blob.

## Rules

- **2025 `captain_rule`:** `null`. P6-M1 (b) records `captain_rule_not_established` for every 2025 alliance, not violations. The draft model and engine raise `not_established` for a 2025 event. PX-1 to PX-4 do not use it, and M6 (b) and M8 are 2026-only.
- **`declined_team_may_become_captain`:** `null` raises `not_established` only when a declined team would be the next captain. TBA records 0 declines, so no historical run changes.

## Tests

`tests/test_phase6_px1_composition.py` (21 new tests). Isolated suite: **1993 passed, 3 skipped** (11.5 min).

## Remaining blockers

1. 2024–2026 rulesets entered, with:
   - the 8 division keys per season as a cited variant;
   - `event_exclusions` for the 3 anomalies;
   - small-event decisions;
   - `unresolved` entries.
2. Approval by a different named reviewer.
3. Migration 0011 applied to serving (Kanav).
4. Then, in order: M1, then PX-1 (m2), PX-2 (m3), PX-4 (m5), M6 (b). M8 also needs its dated pre-run record and a named mentor.
