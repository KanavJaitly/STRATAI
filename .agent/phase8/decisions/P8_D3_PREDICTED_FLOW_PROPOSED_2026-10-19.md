# P8-D3 — `predicted_flow`: derivation rule and contract change (PROPOSED, 2026-10-19)

**Status: PROPOSED. Not approved, and not implemented.**
- This needs Sven Morais's approval before any code, schema or lock change.
- Prepared by Claude Code under Sven's closeout instruction of 2026-10-19: "prepare the dated derivation decision for
  predicted_flow and the required contract-change plan. Do not implement the field until the decision and contract
  requirements are recorded and consistent with the frozen-spec governance."

## 1. Governance this decision must satisfy

| Rule | Source | How this proposal complies |
|---|---|---|
| A derivation rule for an unproduced report item needs its own dated decision | P7-Q12 (`.agent/phase7/P7_M0_DECISIONS.md`); `ml/views/pre_match_report.py:40` | This document is that decision, once approved |
| No client-side derivation | `docs/P8Milestones.md` P8-M6 ("Nothing is derived client-side"), frozen | The value is computed in the backend engine and served; the dashboard only renders it |
| No fabrication; nullable stays nullable | The Phase 8 standing rules, frozen | No partial sums; every absence is served with a code and reason |
| P8-Q6 staging | `P8_Q6_DECISION_2026-10-19.md` (Option C now, then D; predicted flow first) | This is step D1 |
| The contract lock (P7-DM2): a change to a locked entry needs a named, dated decision | `scripts/phase7_contract_lock.py`; `docs/phase7.md` §"The contract lock" | `not_produced.predicted_flow` is a **locked required property** of type `NotProduced` (value always null), so the change in §3 is a change to a locked entry and is relocked with `--decision` naming this document |
| Frozen spec text is not edited | `P8_M0_FREEZE.md` | Nothing in `docs/P8Milestones.md` or `P8_M0_DECISIONS.md` changes. This decision is the dated record that the freeze requires |

## 2. The derivation rule

**What the roadmap item becomes.** The roadmap's "predicted flow" is served as **expected points by phase for each
alliance**. The currently served semantics are "the expected sequence of the match by phase (auto, teleop, endgame)".
This is an **interpretation that needs Sven's explicit approval**: it describes the match by phase in points. It does
not predict events, order, or which alliance leads.

**Definition.** For each alliance (red, blue) and each phase *p* in (auto, teleop, endgame):

    expected_points[alliance][p] = Σ over the alliance's three robots of strength.epa.<p>.value

- Each term is the robot's **served EPA component** in the point-in-time strength view **already in the report**.
  That view is taken at the report's `as_of` (`min(as_of, scheduled_time)`), with no look-ahead, so the same inputs
  the report already shows are used.
- **The total is not served.** A robot's served EPA total need not equal the sum of its served parts, and a second
  total would invite the reader to compare two numbers that differ.

**Absences (never a partial sum).**
- If any of the three robots lacks the component for phase *p*, that phase's value is `null`, with `absent_code`
  `epa_component_absent` and a reason naming the teams and their served absence reasons.
- An alliance without three teams is absent with `alliance_incomplete`, the existing report code.

**What is served alongside each phase value:**
- the three per-robot terms (team number, value, `n`);
- the EPA source (`epa` block, already served);
- each robot's `epa_value_source` and `source_event_key`, for provenance.

**Label.** `validation.status = "descriptive"`, with these reasons:
- `sum_of_independent_robot_epa`;
- `ignores_defense_and_robot_interaction`;
- `not_validated_against_match_outcomes`.

It is not a probability and is never combined with the strategy odds or the M6/M7 value. No red-against-blue
difference or "leading alliance" is served or computed.

**Statistical caveat.**
- EPA components are each robot's expected contribution. Summing them is the standard EPA reading of an alliance's
  expected points, but it ignores interaction, defense and phase dependence.
- Validating the sum against actual phase scores would need the score-breakdown adapter. Its real-data test is one of
  the five known backend baseline failures
  (`test_ml_features_score_breakdown.py::test_adapter_resolves_every_real_alliance_breakdown_and_matches_the_official_score`).
- So this field ships **descriptive only**. No validation claim is made until a separate decision approves an outcome
  check.

## 3. Contract-change plan (each step to be done only after approval)

| # | Change | Where | Evidence and acceptance |
|---|---|---|---|
| 1 | Pure function `predicted_flow(teams, scheduled red/blue) -> PredictedFlow`, computed from the already-built strength views. Remove `predicted_flow` from `NOT_PRODUCED` | `ml/views/pre_match_report.py` | Unit tests: the sums; absence when any robot lacks a phase (no partial sum); `alliance_incomplete`; no look-ahead (the existing point-in-time test pattern: later matches change nothing); label and reasons verbatim |
| 2 | New response model `PredictedFlowSection` (per alliance, per phase: `value` (nullable), `absent_code`, `absent_reason`, `terms[]`; plus `validation`). `PreMatchReportResponse` gains the required `predicted_flow`. `NotProducedItems` drops `predicted_flow` and keeps the other five | `api/routes/pre_match_report.py` | Route tests on the isolated `stratai_test`: the shape, absences, and that the five remaining items are still absences |
| 3 | Relock: `python -m scripts.phase7_contract_lock relock --reason "P8-D3 predicted_flow" --decision ".agent/phase8/decisions/P8_D3_PREDICTED_FLOW_<approved>.md <date>"` | `docs/api_contract_lock.json` (a revision is appended) | `scripts.phase7_contract_lock check` exits 0; `tests/test_phase7_contract.py` passes; the revision names this decision |
| 4 | Documentation: the report section of `docs/phase7.md` and the declared absence code `epa_component_absent` | `docs/phase7.md` (and `docs/ml_models.md` if its contract test requires the code) | The docs contract tests pass |
| 5 | Regenerate the frontend types | `python -m scripts.phase8_generate_api_types` | `tests/test_phase8_frontend_contract.py` passes (types current) |
| 6 | Dashboard: render `predicted_flow` under "Match forecast". Each phase shows its value with the per-robot terms, or "—" with its plain reason and raw code (the D1.7 rule), plus the label badge. Remove it from the not-produced grid. Nothing computed client-side | `frontend/src/dashboard/pages/ReportPage.tsx` | Tests that fail against the current UI; axe checks; A4 print re-check (R11 method) |
| 7 | Verification | — | **Full backend suite (backend changed):** expected 5 failed, the same 5 baseline tests, and nothing new. **Frontend:** suite, type check, lint, build. **Live smoke:** run against the local API on a match whose six robots all have a served EPA, so a populated value is seen, plus one with an absence. **Not claimed:** environment-of-record verification (P8-R1) |
| 8 | Records | `RISK_REGISTER.md` P8-R2, `PHASE_ACCEPTANCE.md`, `PHASE_STATUS.md` | P8-R2 lists five remaining items. **P8-DM2 stays NOT MET** |

**Compatibility:**
- Clients that read `not_produced.predicted_flow` break. The only known client is this repository's dashboard,
  which is updated in the same change (step 6).
- No other locked operation changes.

## 4. Decision requested from Sven Morais

1. Approve or reject the interpretation of "predicted flow" as **expected points by phase per alliance** (§2).
2. Approve or reject the derivation rule: the sum of served EPA components, no partial sums, label `descriptive`.
3. Approve or reject the locked-entry contract change in §3: `not_produced.predicted_flow` is removed, and a new
   required `predicted_flow` section is added, relocked under this decision.

On approval, this file is renamed (or copied) to `P8_D3_PREDICTED_FLOW_<date>.md` with the approval recorded
verbatim, and only then does implementation start.
