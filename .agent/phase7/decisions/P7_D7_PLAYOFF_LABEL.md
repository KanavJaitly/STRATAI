# P7-D7 — Canonical playoff validation label (cross-phase decision, 2026-10-18)

**Status: APPROVED.** Approved by Sven Morais on 2026-10-18, in session, in these words: "I approve the proposed
direction to use `validated_playoff_success` for the pick list's event-level win and reach-finals values, reserving
`validated_playoff` for Phase 6's single-playoff-match probabilities after the PX-2 gate passes".
- Sven has confirmed he holds the same decision-making authority as Kanav for Phase 7 (recorded with P7-M0's
  approval).
- Recorded by Claude Code before any code change. The proposal, unchanged in substance, follows.
- It resolves the open item P7-D5 item 1, and supersedes the label wording of P7-Q1 and R17 in the frozen
  `P7_M0_DECISIONS.md` and of P7-M6 in the frozen `docs/P7Milestones.md`.
- Both frozen specifications, and the frozen P6 specification, are NOT edited.

**Decision:**
- The pick list's `probability_status`, and the `validation.status` of its displayed P(win event) and P(reach
  finals), are **`validated_playoff_success`**.
- **`validated_playoff`** is reserved for Phase 6's single playoff-match probabilities after a PX-2 pass. The API
  serves no such value today.

**Applied:** see "Change set" below. It was applied on 2026-10-18; the results are in "Verification".

## The conflict (repository evidence)

| Source | Text | What it labels |
|---|---|---|
| docs/P6Milestones.md:189, P6-M3 (PX-2) | "Pass: playoff match probabilities `validated_playoff`" | single playoff **match** probabilities, after PX-2 |
| docs/P6Milestones.md:228, P6-M5 (PX-4) | "Pass: `validated_playoff_success`, scope stated" | the bracket simulator's **event-level** outcomes, after PX-4 |
| docs/P6Milestones.md:269, P6-M7 (pick-list engine) | "Predicted playoff performance: `validated_playoff_success` only if P6-M5 passed" | **the pick list's** P(win event) / P(reach finals) |
| docs/phase6.md:60 (P6 label vocabulary) | "`validated_playoff` / `validated_playoff_success`: reserved for PX-2 / PX-4 passes" | the same split: PX-2 → match, PX-4 → event |
| .agent/phase6/P6_M2_PX1_SPEC.md:66 | "pass gives `validated_playoff`" | PX-1/PX-2 match probabilities |
| scripts/phase6_playoff_track.py:542 (P6-M8 run) | `SelectionEngine(..., probability_status="validated_playoff")` | the pick list, with the **match** label |
| docs/P7Milestones.md:145 (P7-M6), P7-Q1, R17 | "`validated_playoff` only when the PX-4 record's `passed` is true, exactly as `scripts/phase6_playoff_track.py` sets it" | the pick list, copying the script |
| Served today (P7-D5 item 1) | `PickListResponse.probability_status: Literal["validated_playoff"]`; lock `const: "validated_playoff"` | the pick list |

So the P6 specification is internally consistent: match-level → `validated_playoff` (PX-2), and event-level →
`validated_playoff_success` (PX-4). The P6-M8 script departed from it, and the P7 spec copied the script.

## Consumers (searched in the repository, 2026-10-18)
- **API:** only `POST /events/{event_key}/alliance-selection/pick-list` (`probability_status`, and each value's
  `validation.status`). It is **never served today**: the pick list refuses with `not_approved`, and the label
  needs an approved ruleset and passed PX gates.
- **Clients:** no frontend file references either label (`frontend/src`). No captured example exists (P7-M8
  BLOCKED). No Phase 8 work exists.
- **Records:** no P6 or P7 write-once result JSON contains either label. The P6-M8 script's label is passed to the
  engine at run time and is not written to `p6_m8_*` records.
- **Tests:** tests/test_phase7_alliance_selection_api.py (the synthetic success path) asserts the current value.

## Proposal (as approved)
**One canonical API label:** the pick list's `probability_status`, and the `validation.status` of its displayed
P(win event) / P(reach finals), become **`validated_playoff_success`**.
- `validated_playoff` stays reserved, with its P6 meaning: single playoff-match probabilities after a PX-2 pass. The
  API serves no such value today. Strategy playoff odds are null (`playoff_model_unavailable`), and M6/M7 playoff
  values are `not_validated` (`playoff_scope`).
- No mapping layer is needed. The engine already takes the label from its caller, and the service passes one
  constant, gated on the PX-4 record.

**Rationale:**
1. The value is an event-level outcome, gated on PX-4. That is exactly what P6-M5 and P6-M7 name
   `validated_playoff_success`, and what docs/phase6.md:60 reserves for a PX-4 pass.
2. Using the PX-2 label for an event-level value would tell a client the value had been validated as a match
   probability, which it has not.
3. The P7 spec's intent ("exactly as the script sets it") was to inherit P6's label, not to invent one. The script is
   the inconsistent source.
4. The scope reasons already served (`px4_scope`, `predicted_field_not_validated`) describe the PX-4 scope.

## Compatibility
- **Breaking in form, not in practice:** a locked `const` changes. No client, example or record depends on it, and
  it is unreachable today.
- **It must be applied before Phase 8 freezes frontend types (P7-DM2).** After that, it becomes a real breaking
  change.
- **The P6 track:** aligning `scripts/phase6_playoff_track.py:542` to `validated_playoff_success` changes no written
  record. It is a Phase 6 code change, owned by the P6 track and applied under its own process. It is optional for
  the API, because the service sets its own label.

## Change set (applied 2026-10-18)
1. `ml/playoffs/service.py`: the constant becomes `VALIDATED_PLAYOFF_SUCCESS = "validated_playoff_success"`.
   `api/routes/alliance_selection.py`: `Literal["validated_playoff_success"]`, with the description and docstring.
2. tests/test_phase7_alliance_selection_api.py: the two assertions.
3. `python -m scripts.phase7_contract_lock relock --reason "P7-D7 canonical playoff label" --decision
   ".agent/phase7/decisions/P7_D7_PLAYOFF_LABEL.md 2026-10-18"`.
4. Docs:
   - docs/phase7.md: the alliance-selection section and the decisions table;
   - M06_ACCEPTANCE.md: an addendum;
   - PHASE_ACCEPTANCE.md and PHASE_STATUS.md: close the open item.
5. NOT applied here: aligning `scripts/phase6_playoff_track.py:542` is a Phase 6 code change, left to the P6 track
   owner (risk register). It changes no written record, and the API sets its own label.
6. Then run the full suite and the lock check.

The frozen files (`docs/P7Milestones.md`, `P7_M0_DECISIONS.md`, `docs/P6Milestones.md`) are never edited. This
decision supersedes P7-Q1/R17's label wording, as P7-D2…D6 supersede other frozen details.

## Verification (2026-10-18, after the change set)
- **Contract lock:**
  - `relock` wrote 24 operations, 1 changed leaf: `/schemas/PickListResponse/properties/probability_status/const`,
    `validated_playoff` → `validated_playoff_success`. The revision cites this decision.
  - `python -m scripts.phase7_contract_lock check`: exit 0, with nothing changed and nothing added.
- **Contract, docs and selection tests:** test_phase7_contract, test_api_contract, test_api_foundation,
  test_metrics_docs_contract, test_ml_models_docs_contract, test_phase6_contract, test_phase7_examples,
  test_phase7_alliance_selection_api and test_defense_feeding_constraint: 404 passed, 1 skipped, 1 xfailed (the
  strict P7-M8 check); pytest exit 0.
- **Full suite** (`DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest tests -q --tb=line -p
  no:cacheprovider`):
  - 2,483 passed, 5 failed, 5 skipped, 1 xfailed (10:09); **pytest exit 1**.
  - The 5 failures are the same 5 baseline tests by name; 0 regressions; counts identical to the run before this
    change.
- **Frozen specs unchanged:**
  - `git hash-object docs/P7Milestones.md` = 61de5046… and `.agent/phase7/P7_M0_DECISIONS.md` = 548c28c6…, both
    equal to P7_M0_FREEZE.md;
  - docs/P6Milestones.md has no diff against main.

## Alternative considered
Keep `validated_playoff` everywhere and amend the P6 vocabulary instead. Rejected: it would need a change to the
frozen P6 spec and phase6.md, and it would merge two different validations (PX-2 match calibration and PX-4 bracket
outcomes) into one label.
