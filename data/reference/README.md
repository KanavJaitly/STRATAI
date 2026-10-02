# Reference data

## `frc_robot_design_curated.csv`

A manually curated set of FRC robot-design observations, supplied by Kanav on 2026-10-02. It was transcribed verbatim from the attached CSV "FRC Game Archtype Data - Take this date and put it into a spreadsheet, but....csv".

- **sha256:** `40aef13982eba6589136806150d9f1e5f92ce49bea588e1ee561ca44c77139e1`
- **Size:** 77 rows; 6 columns: `Year`, `Team`, `Game Name`, `Robot Micro-Archetype`, `Technical Specifications`, `Key Characteristic & Competitive Advantage`. The request described 78 observations; the file has 77.

**Status: curated design metadata, unverified.**
- The technical and "competitive advantage" text is not sourced, and its numeric claims (e.g. "85% volume", "100ms", "18 ft/s") are unverified.
- None of it is a measured outcome.
- It must not be used to produce success rates, win-probability effects or causal claims.
- Its audited role in Phase 5 is recorded in `.agent/phase5/robot_design_audit/AUDIT.md` (decision P5-D10).

**Rules:**
- Never edit this file in place. Corrections go in a new versioned file, with the change recorded.
