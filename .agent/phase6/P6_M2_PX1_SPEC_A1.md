# PX-1 specification, amendment A1: `playoff_before_selection_moment` (versioned; Kanav, 2026-10-08)

**Status: adopted by Kanav (2026-10-08), as a versioned amendment.** Kanav accepted the rule "subject to confirming
that it is compatible with the frozen leakage requirements". This record is that confirmation.

**Effect:** A1 amends `.agent/phase6/P6_M2_PX1_SPEC.md` §1. That file is **not edited**: blob `24b427f2…`, recorded in both PX-1 results.

## Rule

An event yields no PX-1 rows when any of its playoff matches has a `scheduled_time` strictly before the event's
selection moment (§1: its latest qualification match's `scheduled_time` + 1 minute).
- **Counted:** each of the event's playoff matches counts once, as `playoff_before_selection_moment`.
- **Order:** the check runs before every per-row reason.
- **Missing times:** a playoff match with no `scheduled_time` cannot enter the point-in-time history (`scheduled_time IS NOT NULL`), so it never triggers the rule.
- **Implementation:** `EventPlayoffs.playoffs_precede_selection()` and `playoff_rows` in `ml/playoffs/data.py` (`28a89e4`).
- **Determinism:** the rule is a pure function of stored scheduled times. It reads no outcome and has no parameter.

## Compatibility with the frozen leakage requirements

- **P6-Q2** (frozen; restated in §1): "No earlier or in-playoff result is ever a feature." It is a hard requirement with no stated exception.
- **The conflict.** §1 fixes the selection moment as the last qualification match + 1 minute. The assembler's history is every match of the event with `scheduled_time < as_of`.
  - In 2024micmp2 and 2025alhu the data schedules playoff matches before the last qualification match.
  - For those events, §1's selection moment and P6-Q2 **cannot both hold**: at that moment the features contain the predicted playoff results.
- **How A1 resolves it.** A1 is the only resolution that changes neither the selection-moment definition nor the feature definitions: it removes the rows that cannot satisfy P6-Q2.
- **Precedent.** It is the same kind of rule as §1's existing exclusion of an event whose bracket reproduction failed.
- **Conclusion:** A1 is **compatible with, and required by,** the frozen leakage requirement.

**Why A1 is a versioned amendment rather than a reading of §1.** §1's exclusion list is enumerated and does not name this case. Treating the rule as already permitted would broaden §1 silently, so it is recorded here as a versioned amendment instead.

**Disclosure.** A1 was written after PX-1 run 1 and rerun1 were observed.
- It touches only training rows: 24 rows of 2024–2025 that enter the fit (30 matches counted), and none of 2026.
- The rerun shows it cannot change the PX-1 verdict.
- Run 1 (`p6_m2_px1.json`), which predates A1, is kept unchanged. `p6_m2_px1_rerun1.json` applied A1.

## Scope

A1 governs PX-1 rows from rerun1 on. PX-1b (`P6_M2_PX1B_SPEC.md`) states the same rule in its own text and does not depend on this amendment.
