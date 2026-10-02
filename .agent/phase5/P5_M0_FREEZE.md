# P5-M0 — Phase 5 specification freeze

**FROZEN / APPROVED by Kanav, 2026-10-02.** The commit introducing this file is the P5-M0 freeze point.

From here on, methodology and acceptance criteria change only by a new, dated decision in `P5_M0_DECISIONS.md` made **before the affected result exists**. A change made after seeing a result is never permitted.

**P5-M0 contains zero Phase 5 implementation.** No P5-M1 … P5-M10 or playoff-track code exists.

## Frozen documents (git blob hashes at the freeze)

| File | Blob |
|---|---|
| `docs/P5Milestones.md` (revision 3) | `2d7bc67480005cef908bbc3e611342471b3bec49` |
| `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md` | `553bbee916d28eb42dbb2634866c64d45808b500` |
| `.agent/phase5/P5_M0_DECISIONS.md` (P5-D1 … P5-D10) | `7d26fc230851c2a9cbd8a9792ff955bc541e889e` |
| `.agent/phase5/robot_design_audit/AUDIT.md` | `40a6d37bef1f4c0dd5501cae7312ebbc224d3af7` |
| `.agent/phase5/robot_design_audit/audit.py` | `dae1b8cdea189041e6fdfb9f1a662ec3ed2fa86b` |
| `.agent/phase5/robot_design_audit/audit_result.json` | `268947434477379fb0c7c44ec943198636f3285c` |
| `data/reference/frc_robot_design_curated.csv` | `e2c0e42ce155864998d2c2542c55bb58006f9e14` (file sha256 `40aef13982eba6589136806150d9f1e5f92ce49bea588e1ee561ca44c77139e1`) |
| `data/reference/README.md` | `e34330d54130b7b74d220c4b1b5dfd7ddfdf16ab` |
| `docs/ROADMAP.md` (source of DM1 / DM2) | `d7517b09f62056ec3155047c0efac31fb1640896` |

Check: `git hash-object <file>` must equal the blob above.

## What the freeze fixes

- **Dataset:** the curated robot-design dataset is the authoritative **77-row** CSV. The original statement of 78 is a documented discrepancy; no row was reconstructed.
- **Done-means (immutable):**
  - **DM1:** one end-to-end pre-season run within 5 days of a dry-run reveal (2026), covering P5-M8 and P5-M9.
  - **DM2:** real mid-season 2026 matches flowing through the production ingestion and serving paths, with ratings updating and no retraining. A live 2027 confirmation is not required (P5-D8, revised).
- **Live EPA:**
  - fallback Option A, STRATAI EPA after 72 h unprocessed;
  - explicit source states;
  - production keeps the frozen D18 provider until L1–L4 pass and a recorded switch.
- **P5-M7 / M8 / M9:** as justified by the audit (P5-D10).
  - P5-M7 is unchanged, with its gap documented.
  - P5-M8 adds the reference layer, a human multi-label codebook with κ ≥ 0.6 (else `provisional`), `curated_reference_unverified` labelling, and the pre-reveal-only dry-run rule.
  - P5-M9 uses a human-authored feasibility rubric.
- **Unchanged:** all quantitative acceptance criteria as written in revision 3. No Phase 4 criterion or record is changed.
- **Playoff track:** model → playoff-only calibration → simulator → simulator validation → only then validated probabilities. It is a Phase 6 alliance-selection prerequisite.
