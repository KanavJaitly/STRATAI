# P5-M8 / P5-M9 / DM1 — flagged decision Q3 and the human inputs DM1 needs (raised 2026-10-03)

**Status: DECIDED 2026-10-03 by Kanav: the proposed rules, with a pooled-κ gate, per-function `provisional` labels below 0.6, and consensus reconciliation. Recorded as P5-D13 in `P5_M0_DECISIONS.md`.** Earlier status: OPEN. The DM1 dry run (P5-M9 (a)–(c)) cannot run until the rules below are decided and the human
inputs exist. No dry-run result exists, and none is simulated.

## Q3: rules the frozen spec requires but does not define

P5-M8: "Similarity and archetype rules are fixed before the dry run". P5-M9 (b) scores "predicted vs actual
dominant scoring components" and the "coverage of expected scoring ranges". None of these rules is specified.
Each is a slot in `ml/gameanalysis/analysis.py` (`Rules`) that refuses until a decided, versioned rule is
registered:

| Slot | Open question | Proposal (for the decision, not implemented) |
|---|---|---|
| `similarity` | How a new game is compared with catalog games | Cosine similarity of the games' period-share vectors from the value table (each period's max points per unit × period seconds), plus the Jaccard overlap of field-element types; reported, never thresholded |
| `candidate_archetypes` | How candidate archetypes are proposed for a new game | Codebook functions whose scoring action exists in the new spec, mapped by a human-authored action→function table fixed before the reveal |
| `expected_ranges` | How past seasons' component ranges become a new game's expected ranges | The most similar catalog season's per-component p10–p90, rescaled by the ratio of the two games' max points per period; labelled `not_validated` |
| `dominant_components` | What "predicted dominant scoring components" means | Components ordered by the expected-range median; the top one is "dominant". Actual = the component with the largest mean share in 2026 weeks 1–3 (P5-M7 adapters) |

Also open:
- **κ gate:** whether "κ ≥ 0.6" applies to the pooled (row × function) κ or to every function's κ
  (`data/design_reference.label_status`, required argument).
- **Reconciliation:** how two codings become the served labels (consensus meeting, intersection, or the first
  coder).

## Human inputs DM1 needs (never simulated; an AI must not author them)

1. **Catalog game specs** for the pre-2026 games, each entered by a person from that game's manual
   (`data/game_spec.GameSpec`), plus their manifest.
2. **The 2026 game spec**, entered from the 2026 manual at the start of the dry run.
   - Its `entry_started_at` starts the 5-day clock.
   - It must use manual facts only. AI knowledge of 2026 is hindsight, i.e. leakage.
   - Spec entry is audited against the manual.
3. **The codebook:** functions and families, frozen and hashed before coding.
4. **Two independent codings** of the 77 reference rows (the 2026 rows are excluded at use), then the κ report.
5. **The feasibility rubric:** human-authored, deterministic, fixed before the dry run (`ml/gameanalysis/capability.Rubric`).
6. **At least 10 sample team capability profiles**, fixed before the dry run.
7. **A mentor review** of the sample recommendations (P5-M9 (c)).

## What is built

- **Spec schema and catalog:** with integrity checks and the pre-reveal filter (`data/game_spec.py`).
- **Curated reference:** loaded with sha256 verification, verbatim text, `curated_reference_unverified` labels
  and the pre-reveal filter. The codebook and coding schemas, and the κ computation, are in
  `data/design_reference.py`.
- **Value table, past-season component ranges and the analysis pipeline:** in `ml/gameanalysis/analysis.py`.
- **Capability intake and recommendations:** raw-first capability intake, and deterministic rubric evaluation
  with explanations, in `ml/gameanalysis/capability.py`.
- **The DM1 dry-run runner** (`scripts/phase5_dm1_dry_run.py`):
  - it validates and hashes every input;
  - it records the clock and writes predictions write-once before any 2026 match data is read;
  - it then scores against 2026 weeks 1–3 and records the mentor review.

**Decision needed from:** Kanav (rules, as a new dated row in `P5_M0_DECISIONS.md`), plus the people above for
the inputs.
