# Phase 6 — Strategy & Alliance Selection Engines

The specification is `docs/P6Milestones.md`, **frozen at P6-M0** (`9964001`). Its decisions are
`.agent/phase6/P6_M0_DECISIONS.md` (P6-A1 … A12 approved; P6-Q0 … Q13 decided). The implementation branch is
`phase6/build`.

**Phase 6 is NOT complete.**
- **P6-DM2** (verifiably zero AI-odds inflation) is **met**.
- **P6-DM1** (alliance selection on real past events) is **not met**. It is blocked by **required human input**: the
  P6-M1 season rulesets, entered from the game manuals and approved by a named reviewer. The whole playoff track
  and P6-M8 need them.

`python -m scripts.phase6_done_means` reports this from the records alone.

**Standing rules:**
- There is no LLM in the core.
- Everything is point in time, and outcomes are labels only.
- M6/M7 and every D18 model stay frozen.
- Every output carries a `validation_status`, and `insufficient_data` propagates.
- D9 applies: a genuine failure is recorded and stops dependent validation, and no methodology changes after a
  result.
- Non-production runs have a hard 45-minute budget, and every sample is fixed by a dated pre-run record (P6-Q13).
- Tests use isolated `stratai_test*` copies only.
- **Phase 6 has no HTTP endpoints or UI:** engines, service functions, CLIs and write-once records only (P6-A1).

## Status at a glance

| Milestone | Implementation | Validation | Record |
|---|---|---|---|
| P6-M0 Specification freeze | — | **FROZEN** (`9964001`) | `.agent/phase6/P6_M0_FREEZE.md` |
| P6-M1 Season rulesets | built: schema, migration 0011, review workflow, CLI, reproduction and selection-rule checks | **BLOCKED: required human input** (no approved ruleset) | not run |
| P6-M2 PX-1 playoff model | built: frozen spec `.agent/phase6/P6_M2_PX1_SPEC.md`, model, data assembly, gate | **not run** (needs P6-M1) | — |
| P6-M3 PX-2 calibration | built: calibration and M7/D16 gate pipeline | **not run** (needs PX-1) | — |
| P6-M4 PX-3 simulator | built: exact vectorized plus recursive, Monte Carlo oracle | **implementation correctness passed** (synthetic brackets); the real-structure criterion needs P6-M1 | tests |
| P6-M5 PX-4 simulator validation | built | **not run** (needs PX-2) | — |
| P6-M6 Candidate profiles and draft model | built | (a) profile equality **passed** (768 teams, 30 events, 0 mismatches); (b) draft accuracy **not run** (needs P6-M1) | `p6_m6a_profiles.json` |
| P6-M7 Alliance selection engine | built: P(win event) objective, exact nested search, alternatives | **optimization correctness passed** (brute force, synthetic); probabilities `not_validated` until PX-2/PX-4 | tests |
| P6-M8 P6-DM1 validation | built: run plus named-mentor review finalization | **not run** (needs P6-M1 … M5, its pre-run record and a named mentor) | — |
| P6-M9 Strategy representation, coach inputs | built | **passed** (schema, leakage, raw-first, point-in-time tests) | tests |
| P6-M10 Strategy outcome model | built, fit and registered | **FAILED** its M7/D16 gate (G2), so it is served `not_validated` (D9) | `p6_m10_fit.json`, `p6_m10_outcome_model.json` |
| P6-M11 Strategy recommender | built | **optimization correctness passed** (exhaustive search, brute force, bit identity) | tests |
| P6-M12 Strategy historical validation | built | run 1 **FAILED** on a harness defect (kept); rerun1 **PASSED** | `p6_m12_strategy_validation.json`, `p6_m12_strategy_validation_rerun1.json` |
| P6-M13 Parity audit (P6-DM2) | built | run 1 **FAILED** (kept); rerun1 **PASSED**, so **P6-DM2 met** | `p6_m13_parity_audit.json`, `p6_m13_parity_audit_rerun1.json` |
| P6-M14 Docs, contracts, sign-off | this page, `tests/test_phase6_contract.py`, `scripts/phase6_done_means.py` | — | — |

## Labels served

| Label | Meaning |
|---|---|
| `validated` | met its pre-registered criterion. **No Phase 6 probability carries it today** |
| `not_validated` | never validated, or its validation failed, with the reason |
| `insufficient_data` | a required measured input is absent; nothing is imputed |
| `strategy_effect_unmeasured` | any non-baseline strategy: no historical record of which strategy an alliance played (P6-A4) |
| `defense_effect_insufficient_data` / `feeding_effect_insufficient_data` | a defense or feeding role. With 0 scouting rows the effect is zero by rule, never estimated (P6-Q11, Q12) |
| `coach_observation_effect_unmeasured` | a coach observation was applied (to both paths identically) |
| `p6_m10_gate_failed` | the strategy model's baseline odds: the P6-M10 gate failed (D9) |
| `playoff_model_unavailable` | the playoff context: PX-1/PX-2 have not passed (P6-A12) |
| `descriptive_definition_pending` | defense quality in candidate profiles (P6-Q11) |
| `not_validated_against_outcomes` | M9 synergy and role compatibility, as built (P6-A10) |
| `validated_playoff` / `validated_playoff_success` | reserved for PX-2 / PX-4 passes; **not served today** |

**Display (P6-A5):** below 0.05 is shown as "<5%", above 0.95 as ">95%", otherwise 0.05 steps. The rule is identical
for the AI and coach paths, and the internal probability is never clamped. A difference below one step is
"indistinguishable at model resolution" (P6-Q10).

## Strategy track (P6-M9 … P6-M13)

### P6-M9: one representation for both paths

- **One type for both paths.** `ml/strategy/representation.py` defines `Strategy`, used by the optimizer and by
  coaches.
  - Each robot has a teleop role (scoring, defense with an opponent target, or feeding with an ally target) and the
    score components it pursues (auto, teleop, endgame).
  - **No field records a strategy's origin, and extra fields are forbidden.** Provenance (`StrategyProvenance`) is
    stored beside the strategy, never inside it.
- **Coach observations** (`CoachObservation`) are structured, timestamped and attributed, with no free-text field
  (P6-A9).
- **Storage:** `ml/strategy/coach_inputs.py` lands every submission raw-first (source `coach_input`) and validates it
  afterwards. Observations are usable only strictly after `observed_at`.

### P6-M10: the single odds model

The model is frozen by `.agent/phase6/P6_M10_MODEL_SPEC.md`, committed at `48ac1ea` before the fit.

**The model:**
- **Capability:** each team's capability per component is max(0, prior-event EPA component) / its EPA source's
  causal scale.
- **Strategies:** a strategy can only withhold capability, never exceed it.
- **Score difference:** each normalized component difference is beta_c × the predicted difference, plus
  multivariate-normal noise; P(red) = Φ(m / s).
- **Entry point:** there is one evaluation entry point, `evaluate(context, strategy_red, strategy_blue)`.

**Fit** (`p6_m10_fit.json`):
- 15,956 EPA-complete 2024–2025 qualification matches;
- beta auto 0.741, teleop 0.950, endgame 0.885; σ = 0.899 (season-scale units);
- registered as `strategy_outcome_component` / `p6m10-v1` (sha256 `aded2c829a1f…`).

**Evaluation** (`p6_m10_outcome_model.json`), on 12,215 held-out 2026 EPA-complete qualification matches (excluding
33 ties and 30 matches without a causal scale):

| Gate (M7/D16, unchanged) | Result |
|---|---|
| G1 ECE < 0.05 | pass (0.0266) |
| G2 per-bin test | **FAIL**: 4 of 10 bins rejected, all under-confident (`.agent/phase6/P6_M10_FAILURE.md`) |
| G3 symmetry | pass |
| G4 fit isolation | pass |

**Reported, not gated (P6-Q9):** the paired log-loss of P6-M10 minus M6/M7 is −0.0384 (95% CI −0.0613 to −0.0170).
P6-M10's log-loss is lower: 0.5004 vs 0.5388.

**Served:** baseline odds are `not_validated` (`p6_m10_gate_failed`). There is no redesign without Kanav's dated
decision (D9).

**Forensic diagnosis** (diagnostic only; nothing changed): `.agent/phase6/P6_M10_DIAGNOSIS.md`.
- **The likely cause is misspecification already present in training:** the in-sample calibration slope is
  1.274. The per-component least-squares design discards cross-component information; a diagnostic joint fit
  gives an in-sample slope of 1.066.
- **Compounding it:** EPA-source-season heterogeneity, and a smaller 2026 shift.
- **On the same rows,** M6/M7 also fails G2 (1 bin).
- **Redesign directions are listed but not implemented.** Each needs Kanav's dated decision.

### P6-M11: the recommender

`ml/strategy/engine.py`:
- **One evaluation path:** `StrategyEngine.assess` is the only one. The coach path calls it directly. The AI path
  (`recommend`) calls it for every candidate in the **exhaustive** 21,952-strategy space.
- **Ties** are broken deterministically.
- **Selection caveat:** the output states that the recommendation is the maximum over N model estimates, not an
  unbiased probability.
- **No superiority claims, no best-response:** no strategy is claimed superior, and there is no opponent
  best-response (P6-Q10).
- **Today it recommends the baseline.** With no measured defense or feeding effect, withholding any measured
  capability can only lower the odds under the model, and the output says why.

### P6-M12: what historical data can validate

**Plan:** `.agent/phase6/decisions/P6_M12_SAMPLING.md`.
- 15 matches per TBA-week stratum from the P6-M10 population (155 matches); 20 point-in-time sentinels;
- a dedicated retained clone, `stratai_test_p6m12`.

**Run 1** (`p6_m12_strategy_validation.json`) **FAILED** criterion (b): 13 of 20 sentinel matches unchanged.
- **Diagnosis** (`.agent/phase6/P6_M12_RUN1_FAILURE.md`): a harness defect. Coach sentinels were timestamped 1 hour
  after their own match, so they were legitimately past data for later sampled matches at the same event. A
  diagnostic reproduced exactly those 7 matches, and far-future coach sentinels changed nothing.
- **The other criteria passed:**
  - (a) reproduction 155 / 155 bit for bit;
  - (c) honest odds: 0 violations, with 14 raw probabilities below 0.05 and 14 above 0.95, all shown by the rule.

**Rerun1** (`p6_m12_strategy_validation_rerun1.json`) **PASSED** in 4.9 min, with the same plan, sample and seed:
- (a) 155 / 155 reproduced bit for bit;
- (b) 20 / 20 sentinels unchanged, with per-match outcomes recorded;
- (c) honest odds held.
- (d) The mentor review was not performed (optional; nothing fabricated).

**Cannot be validated from history:**
- strategy effects (no strategy records);
- defense and feeding effects (0 scouting rows);
- the baseline calibration (the P6-M10 gate failed);
- the playoff context.

### P6-M13: the parity audit (P6-DM2)

- **Plan:** `.agent/phase6/decisions/P6_M13_AUDIT_PLAN.md`.
- **The audit** (`ml/strategy/parity_audit.py`):
  - S1–S3 structural: no origin field on any evaluation input; one entry point; the engine computes no probability.
  - M1–M7 metamorphic:
    - an identical coach strategy gets bit-identical odds;
    - the recommended odds are the exhaustive maximum;
    - order invariance;
    - the colour swap;
    - one display rule;
    - missing-data parity;
    - honest low odds.
  - **Seven planted defects** must each be caught: source-dependent weighting, a hidden AI-only feature, an AI-only
    adjustment, different rounding, different calibration, different missing-data handling, and AI probability
    inflation.
- **Run 1** (`p6_m13_parity_audit.json`) **FAILED** on two objectively demonstrated defects (`.agent/phase6/P6_M13_RUN1_FAILURE.md`):
  - the alliance sum was order-dependent in the last bit;
  - the planted missing-data defect missed the score-scale case.
- **Fixes:** `math.fsum`, and full imputation in the planted fixture. Both have regression tests proven to fail on
  the run-1 code.
- **Rerun1** (`p6_m13_parity_audit_rerun1.json`) **PASSED** in 5.8 min:
  - all 10 checks on the real engine with real held-out 2026 contexts;
  - all 7 planted defects caught by their target checks.
- **P6-DM2 is met.** The record's provenance commit (`3d96c94`) is HEAD at the moment of writing. The audit code is
  identical to the run's `249ff34`, since only the P6-M12 plan was committed in between.

## Alliance-selection and playoff track (P6-M1 … P6-M8)

### P6-M1: rulesets (human input)

- **Workflow:** `data/rulesets.py` and migration `0011_phase6_season_rulesets.sql`.
  - A season ruleset is entered by a person from the manual, citing a section for every rule. The rules cover
    alliance count by roster size, serpentine selection, captain and decline rules, and the bracket as a slot graph
    keyed by TBA (`competition_level`, `set_number`), plus a best-of-N finals.
  - It becomes authoritative only through approval by a named, qualified human FRC-domain reviewer.
    - The reviewer independently verifies the stored ruleset against the authoritative FIRST sources and
      completes R1–R15. They may also be the author (review control of 2026-10-07,
      `.agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md`).
    - Approval needs the stated qualification, the full R1–R15 checklist and the full stored sha256.
  - `approved_ruleset` refuses an unapproved season. No rule exists in code.
- **Schema v2 (`p6-ruleset-v2`, Kanav's P1 decision, 2026-10-05; decision record
  `.agent/phase6/decisions/P6_M1_P1_SCHEMA_V2.md`):**
  - `selection` is the season default.
  - `selection_variants` give a complete alternative `selection` for an explicit, cited list of event keys, e.g.
    FIRST Championship divisions: 3 picks, no backups. Each listed event carries its own FIRST provenance: rule,
    document, version, Team Update or explicit null, section, and a FIRST URL.
  - `event_exclusions` list events the ruleset cannot represent faithfully, each with a reason code and the
    finding. Consumers exclude and count them. `2024isde2`, `2026tuak2` and `2026tuis4` are listed at entry unless
    a FIRST document resolves them (D-PX1-3).
  - **Schema v3 (`p6-ruleset-v3`, D-PX1-4/5, 2026-10-06):** `captain_rule` and `declined_team_may_become_captain`
    may be `null`, meaning not established by an authoritative FIRST source, each with an `unresolved` note and the
    sources checked.
    - Consumers raise `not_established` only where the value would decide an outcome.
    - P6-M1 (b) counts unchecked alliances (`captain_rule_not_established`, `decline_rule_not_established`).
    - 2025 `captain_rule` is `null`: the official 2025 sources do not establish who replaces a Lead who accepts an
      invitation.
  - **Precedence:** an explicit variant listing the event, otherwise the season default. Nothing is inferred
    (not from `events.event_type`, not from data).
  - Selection consumers take one event's rules from `SeasonRuleset.for_event(event_key)`. `ml.playoffs.selection`
    refuses a bare season ruleset.
  - No DDL change: `ruleset_json` is JSONB, and there is still one approved ruleset per season.
- **CLI:** `scripts/phase6_rulesets.py` (template, draft, submit, review, list).
- **Checks:** `scripts/phase6_playoff_track.py m1` checks:
  - (a) bracket reproduction against every real 2024–2026 event (ruleset exclusions counted by reason);
  - (b) the serpentine captain rule, under each event's own selection rules (the variant applied is recorded).
- **Prerequisites:**
  1. migration 0011 applied to the serving database, which is a production step that needs Kanav's explicit
     approval;
  2. the 2024, 2025 and 2026 rulesets entered and approved.

### P6-M2 … P6-M5: the playoff track

- **Frozen specification:** `.agent/phase6/P6_M2_PX1_SPEC.md`, committed before any playoff data was assembled.
- **PX-1** (`ml/playoffs/px1.py`): a regularized logistic regression (C = 1.0, no intercept).
  - Inputs: the seed difference, the M6 composition-sum differences and bracket-round interactions.
  - Point in time: selection-moment features only.
  - It is antisymmetric by construction, and absent columns are dropped and recorded, never imputed.
- **PX-2:** the symmetric isotonic calibrator on the last 20% of 2025 playoffs, with the M7/D16 gate.
- **PX-3** (`ml/playoffs/simulator.py`): exact enumeration of every bracket path, vectorized (1.9 ms per bracket),
  checked against an independent recursive implementation and a seeded Monte Carlo oracle.
- **PX-4:** P(win event) and P(reach finals) against the seed-only baseline, with event-bootstrap CIs.
- **Runs:** `scripts/phase6_playoff_track.py m2 | m3 | m5`. Each refuses, writing nothing, until the P6-M1 rulesets
  exist and its prerequisite passed.
- **Composition and populations** (Kanav, 2026-10-06: D-PX1-1/2 and C1/C2;
  `.agent/phase6/decisions/P6_PX1_COMPOSITION_DECISIONS.md`). The frozen spec is unchanged; these decisions sit
  alongside it.
  - **Members:** an alliance's composition is its selection-time members, the captain and its picks
    (`ml.playoffs.data.selection_members`). TBA lists a backup as an extra `picks` entry; it is never a member. This
    applies to PX-1, the M6/M7 baseline, PX-4, P6-M8's "actual pick" and the engine.
  - **Four-member exclusion:** FIRST Championship divisions have four members, per the ruleset's cited variant.
    That is outside PX-1's frozen three-team representation, so they are excluded and counted per event:
    - from PX-1 rows (`four_member_alliance`);
    - from the PX-4 population (C1);
    - from the M8 population (C2).
  - **Records:** each record keeps the intended population next to the validated one, plus the decisions' blob.
  - **Guard:** `alliance_match_probability` refuses an alliance that is not three teams (`OutsidePX1Domain`).

### P6-M6 … P6-M8: selection and P6-DM1

**P6-M6 (a) passed** (`p6_m6a_profiles.json`, plan `.agent/phase6/decisions/P6_M6A_PLAN.md`):
- 768 alliance teams across 30 seeded held-out 2026 events, at their selection moments;
- every profile factor equals its Phase 3/4 source, and synergy and role compatibility equal `alliance_synergy`
  exactly;
- defense and feeding are `insufficient_data` throughout (0 scouting rows).

- **Selection** (`ml/playoffs/selection.py`):
  - candidate profiles, with each factor's value, n and status;
  - the deterministic best-available draft model on the validated P5-M4 ordering;
  - the engine, which maximizes P(the alliance wins the event) through the simulator, with its own later picks
    optimized by exhaustive nested search;
  - up to 5 distinct alternative configurations, with no padding.
- **P6-DM1** (`ml/playoffs/evaluation.py`, `scripts/phase6_playoff_track.py m8`, `m8-review`):
  - the frozen P6-Q1 identification rule, applied to the actual winner and finalist;
  - the raw-EPA-draft and actual-seed-order baselines;
  - every miss is reviewed by the named mentor against predefined categories. A miss counts only when its reason is
    accepted.

## Remaining human inputs and prerequisites

1. **P6-M1 rulesets** for 2024, 2025 and 2026: entered from the manuals and approved by a named, qualified
   human FRC-domain reviewer.
   **All of P6-DM1 waits on this.**
   The fields, sources, reviewer checks, open decisions and migration 0011 steps are in
   `.agent/phase6/P6_M1_HUMAN_INPUT_GUIDE.md`.
   A Claude-prepared, cited research draft per season (Kanav's workflow, 2026-10-05; not verified, not entered,
   not approved) is in `.agent/phase6/rulesets_research/`. It reports schema mismatches (D5 Championship
   divisions; small-event byes) that need a decision before entry.
   Schema v2 (P1, 2026-10-05) represents the Championship-division variant. Its review, and the open items in
   `.agent/phase6/decisions/P6_M1_P1_SCHEMA_V2.md`, come before any entry.
   **Entry package (2026-10-06):** `.agent/phase6/rulesets_entry/` holds the v3 forms, per-field sheets, the three
   remaining human decisions (H1 small events, H2 round convention, H3 2026 captain rule), the approval-record
   template, and the gate that unblocks the runner.
2. **Migration 0011 on the serving database:** applied 2026-10-06 with Kanav's approval (backup and checks in
   `.agent/phase6/decisions/P6_M1_ENTRY_STATUS.md`). The 2024–2026 rulesets are stored as `awaiting_review`
   (ids 1–3); approval by a named, qualified human FRC-domain reviewer is outstanding.
3. **The P6-M8 pre-run record** (`.agent/phase6/decisions/P6_M8_PRE_RUN.md` and `p6_m8_pre_run.json`: seed, strata,
   per-stratum count, reason categories, the named mentor), committed before the run. Then the **named mentor's
   review** of every miss.
4. **P6-M10:** any redesign after its gate failure needs Kanav's dated decision (D9).
5. **Optional:** a genuine named mentor review of sampled strategy recommendations (P6-M12 (d)).

## Records

| Record | What |
|---|---|
| `p6_m10_fit.json` | P6-M10 fit and registration |
| `p6_m10_outcome_model.json` | P6-M10 evaluation (gate FAILED) |
| `p6_m12_strategy_validation.json` | P6-M12 run 1 (FAILED on a harness defect; kept) |
| `p6_m12_strategy_validation_rerun1.json` | P6-M12 labelled rerun |
| `p6_m13_parity_audit.json` | P6-M13 run 1 (FAILED; kept) |
| `p6_m13_parity_audit_rerun1.json` | P6-M13 rerun1 (PASSED; P6-DM2 met) |
| `p6_m6a_profiles.json` | P6-M6 (a) profile equality |
