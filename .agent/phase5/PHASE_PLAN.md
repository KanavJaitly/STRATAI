# Phase 5 execution plan (MASTER_BUILD Phase Execution Mode)

- **Spec (authoritative):** `docs/P5Milestones.md`, frozen at P5-M0 (`ffb67f8`, on origin/main `369687f`). Design: `LIVE_EPA_REFRESH_DESIGN.md`. Decisions: `P5_M0_DECISIONS.md`.
- **Branch:** `phase5/build`, created from `369687f`.
- **Gates:** pytest only. mypy, ruff and flake8 are not configured or installed in this repo; `py_compile` is used as the static check.

## Order (by the frozen dependency table)

M1 → M3 → M2 → M4 → M5 → M7 → **mid-phase audit** → M6 → M8 → M9 → M10 → phase-level audit → phase acceptance.

## Interfaces

- **`TeamFeatures` / assembler:** used by M3/M4/M5/M6.
- **`PointInTimeEpaProvider`:** M2's live provider implements it, adds `epa_source_state`, and the API consumes it.
- **Frozen D18 artifacts:** consumed read-only.
- **Write-once result records:** `.agent/phase5/results/`.

## Risks

- **M2 (high):** snapshot log and as_of semantics; L1 needs exact equality with D18 on 319,301 appearances.
- **M6 (high):** replay through the production ingestion path into an isolated, non-serving database. The serving database must never be touched.
- **M7:** breakdown component schemas per season, which need verification on real payloads.
- **Statistical:** M4 (b)/(c) and M5 (b) are new single measurements, each computed once and recorded write-once.

## Human decisions known up front (frozen spec assigns these to people)

- **P5-M2 adoption** is a recorded decision (P5-D3). M6's dependency table names "P5-M2 adopted".
- **P5-M8 codebook coding:** two independent human coders, with κ computed from their coding.
- **P5-M9:** a human-authored feasibility rubric and a mentor review.
- **DM1:** the 2026 game spec entered from the manual by a person, with no hindsight. The AI's training knowledge of 2026 would itself be leakage.

The infrastructure for these is built and tested; the human steps are flagged, never simulated.
