Phase 6 — Strategy & Alliance Selection Engines: Milestone Specification

Status: **FROZEN / APPROVED — P6-M0 (Kanav, 2026-10-04), revision 2.**
- **Freeze record:** `.agent/phase6/P6_M0_FREEZE.md`. The commit introducing it is the freeze point.
- **Decisions:** `.agent/phase6/P6_M0_DECISIONS.md`. P6-A1 … P6-A12 are approved and P6-Q0 … P6-Q13 decided.
- **After the freeze,** methodology and acceptance criteria change only by a dated decision made **before the affected result exists**, and D9 is binding.
- **Zero Phase 6 implementation exists.** Implementation must not begin until the P6-Q0 code baseline exists: the approved merge of `phase5/build` into `main`, which has not been performed.

**Sources, in authority order:**
1. `docs/ROADMAP.md` Phase 6: scope and done-means.
2. `docs/PROJECT_VISION.md`: "Match Strategy Engine", "Alliance Selection", "Artificial Intelligence Philosophy", "Core Principles".
3. `prompts/MASTER_BUILD.md`: execution protocol, the ML & Statistical Integrity Protocol, and the human-escalation rules.
4. `CLAUDE.md`: critical constraints.
5. The frozen Phase 5 specification (`docs/P5Milestones.md`): it places the playoff track PX-1 … PX-4 in Phase 6 as a prerequisite of alliance selection (P5-D4).

Phase 4 and Phase 5 contracts are consumed as they stand, never reopened (§ "Foundations consumed").

---

## Phase 6 done-means (immutable, from `docs/ROADMAP.md`)

Phase 6 is complete only when **both** hold. Neither may be redefined, weakened or removed. The operational definitions were fixed at P6-M0 (P6-Q1), before any result exists.

### P6-DM1 — alliance selection against real past events

> "run alliance selection against a real past event and it identifies most of the actual strong playoff alliances (or has a defensible reason where it differs)"

Demonstrated by P6-M8, run once on a pre-registered population of real past events (P6-A6: a population, not a single anecdotal event).
**Operational definition (P6-Q1, decided):**
- **Population:** held-out **2026** events; a seeded population stratified by week and event size, within the 45-minute budget. The exact sample is fixed in P6-M8's dated pre-run record.
- **Strong playoff alliances:** the event **winner** and the **finalist**.
- **Identifies:** a predicted alliance that contains the actual captain **and** at least one actual pick, **and** is among the engine's **top 2 predicted contenders**.
- **Most:** **> 50% pooled** over strong alliances, with an event-bootstrap CI reported.
- **Defensible reason:** a predefined reason category (fixed in P6-M8's pre-run record), reviewed by a **named mentor**. A miss without an accepted reason counts as a miss.
- **Baselines:** a raw-EPA draft; actual-seed ordering.

### P6-DM2 — no inflated odds for AI strategies

> "there is verifiably zero mechanism for AI strategies to receive inflated odds — same model, same inputs, for both paths"

Demonstrated by P6-M13: structural, metamorphic and adversarial evidence that the AI-recommended and coach-entered strategies are evaluated by one function, on one input set, with no input or code path that depends on where a strategy came from.

### Required outputs (roadmap scope; each owned by a milestone)

| Roadmap requirement | Milestone |
|---|---|
| Match strategy engine: role assignments, defensive assignments, scoring priorities via optimization, no LLM; inputs are your alliance, the opposing alliance, event context, season data, historical data, coach observations | P6-M9, P6-M10, P6-M11 |
| Coach scenario mode: a manual strategy runs through the same win-probability model | P6-M9, P6-M10, P6-M13 |
| Honest, purely data-driven odds for both paths, reported low when low | P6-M10, P6-M12, P6-M13 (P6-A5) |
| Alliance selection engine: score every candidate using synergy, defense, feeding, reliability, consistency and role compatibility | P6-M6, P6-M7 (P6-A3) |
| Optimize for playoff win probability, not raw scoring | P6-M2 … P6-M5, P6-M7 (P6-A2) |
| Ranked pick lists with reasoning, plus 3–5 alternative alliance configurations with predicted playoff performance | P6-M7 (P6-A7) |
| Real historical-event validation | P6-M5, P6-M8, P6-M12 |
| Verifiably zero inflation mechanism | P6-M13 |

---

## Standing rules (every milestone)

These are inherited from Phase 4 and Phase 5 and are not re-decided here.

- **No LLM in the core.** Models, statistics and optimization only. An LLM may only format or explain finished outputs, and only in Phase 9.
- **Point in time.**
  - Every input uses only data strictly before its `as_of`.
  - The alliance-selection moment: after the event's last qualification match and before alliance selection. Final qualification rankings are known then and are a legitimate input. Alliance seeds and picks are known only after selection.
  - Playoff and alliance outcomes are **labels only, never features** (`data/alliances.py`, P5-M1).
- **Frozen models.**
  - D18 (`ranking_xgb_v2` `1f0fe5aa…`, M6/M7 `win_prob_xgb_calibrated` `c76d3299…`) is never retrained or modified.
  - A new model (PX-1, P6-M10) is a new version with its own frozen spec and a **single** evaluation run.
- **EPA provenance.** `epa_value_source` / `epa_source_state` travel with every EPA-derived value. Historical evaluation uses the D18 snapshot semantics (P5-M2 L1 equivalence). Live use is P5-D3's adopted live source, with `live_refresh_not_yet_validated` where it applies.
- **Every output carries a `validation_status`**, and a reason when it is not validated. Nothing unvalidated is presented as validated.
- **Defense and feeding are measured, never inferred.**
  - They come only from scouting observations (CLAUDE.md constraint 1).
  - `insufficient_data` propagates, and absence is never 0.
  - **Data fact (checked 2026-10-04 on the isolated copy):** `scouting_observations` holds 0 rows, so every historical event's defense and feeding are `insufficient_data`. Phase 6 validation proceeds on that basis, with defense and feeding explicitly `insufficient_data` throughout. Nothing is fabricated, inferred from outcomes or backfilled (P6-Q12).
- **Evaluation discipline (D9).**
  - Each metric is computed once, on a population fixed before the run.
  - Records are write-once, with the frame/snapshot hash, seed and commit.
  - **A genuine failure stops and escalates.** Only objectively demonstrated implementation defects may be fixed. The model, features, metric, threshold, split, population or methodology are never changed to manufacture a pass.
- **Verification runtime (CLAUDE.md, permanent).**
  - No non-production verification run may exceed about 45 minutes.
  - If an exhaustive design cannot fit, the milestone uses a seeded, stratified sample plus targeted edge cases. The sample is fixed by a dated decision before the run, and harnesses carry their own time budget.
- **Databases.** Tests and replays run only on isolated `stratai_test` / `stratai_test_<suffix>` copies (the permanent test-database guard). The serving database is never written by verification, and production DDL needs Kanav's explicit approval.
- **Human inputs are genuine.** No human artifact (ruleset, review, coach strategy used as evidence) is fabricated, synthesized or substituted. Synthetic fixtures are allowed in tests and are labelled as such.
- **The same displayed-probability rule for every path** (P6-A5).

## Foundations consumed (not reopened)

| Foundation | Where | Used by |
|---|---|---|
| Point-in-time features (`TeamFeatures`, presence flags, causal scale) | `ml/features/assembler.py` (Phase 4 M1, D16) | P6-M2, M6, M10 |
| D18 EPA source and P5-M2 live source (adopted, P5-D3) | `ml/ratings/` | all |
| M5 v2 ranking; raw-EPA baseline; the P5-M4 event ordering policy | Phase 4 M5 v2 / M4; P5-M4 | P6-M6 (captains, opponent picks) |
| M6/M7 qualification win probability (EPA-complete: `approximately_calibrated_qualification`; M7 gate failed) | Phase 4 | P6-M2 (baseline), P6-M10 (comparator) |
| Alliance synergy primitive (share vectors; `not_validated_against_outcomes`) | `ml/synergy/score.py` (Phase 4 M9) | P6-M6 (descriptive profile; not a PX-1 feature under P6-Q2) |
| Bias audit (symmetry, order invariance, **no strategy leakage**, as-of integrity, label shuffle) | `scripts/ml_bias_audit.py` (Phase 4 M8) | P6-M13 (extended, not replaced) |
| Model registry with feature-list guard | `ml/registry.py` (Phase 4 M10) | P6-M2, M10 |
| Alliance and seed data: 606 events with alliances (591 seeded, 15 division-champion); backups unknown | `data/alliances.py` (P5-M1) | P6-M1 … M8 |
| Team strength views; event analysis; qualification forecasts | P5-M3, P5-M4, P5-M5 | P6-M6, M7, M10 |
| Score-component adapters (auto, teleop, endgame, fouls) for 2024–2026 | `ml/features/score_breakdown.py` (P5-M7) | P6-M9, M10 |
| Human-input infrastructure (versioned, raw-first, named reviewer, write token) | `data/human_inputs.py`, `api/routes/human_inputs.py`, `frontend/` (Phase 5) | P6-M1, M8, M9 |
| Validation-status labels; `insufficient_data`; as-of conventions | `docs/phase5.md` | all |

**Location of the Phase 5 implementation (P6-A11, P6-Q0).** The Phase 5 code is at the accepted checkpoint `phase5/build` @ `6e76520`, which is **not on `main`** and not pushed.
- **P6-Q0 decided:** merge it into `main` with Kanav's explicit approval, then branch Phase 6 from that `main`.
- **The merge has not been performed.** Phase 6 implementation must not begin until it has.

## The validated / unvalidated boundary at the start of Phase 6

| Validated (within documented limits) | Not validated |
|---|---|
| Qualification win probability on EPA-complete matches (M6/M7; ECE 0.015; M7 gate failed overall) | **Any playoff match, bracket, series or playoff-success probability** (D18 playoff ECE 0.119; higher seed wins 77.3% vs 62.4% predicted) |
| M5 v2 orderings from each team's mid-qualification point; raw-EPA orderings | Alliance synergy (M9) as a predictor |
| Descriptive strength views with n, uncertainty and provenance | Defense (quality-only definition decided, P6-Q11; no validated measurement) and feeding (no data) |
| | Any strategy effect (no historical record of which strategy an alliance played) |

- **Moving an item left:** only a milestone that meets its own pre-registered criteria may move an item to the left column.

---

## Milestones

Each table row is a required field. "Decision" points to `.agent/phase6/P6_M0_DECISIONS.md`.

### P6-M0 — Specification freeze

| | |
|---|---|
| **Objective** | Freeze this specification and its decisions before any Phase 6 result or implementation exists |
| **Scope** | This document; `.agent/phase6/P6_M0_DECISIONS.md`; a freeze record `.agent/phase6/P6_M0_FREEZE.md` with git blob hashes |
| **Depends on** | Phase 5 implementation checkpoint (accepted 2026-10-04) |
| **Inputs** | Kanav's decisions P6-Q0 … P6-Q13 and approval of P6-A1 … P6-A12 (given 2026-10-04) |
| **Acceptance / done-means** | An approval commit naming the frozen files and their blob hashes, with every P6-Q decided. **Zero Phase 6 implementation** in the checkpoint. **Status: FROZEN (2026-10-04)** |
| **Human input** | Yes: Kanav |
| **Prerequisite for** | Every Phase 6 milestone |

### P6-M1 — Season rulesets for alliance selection and playoffs

| | |
|---|---|
| **Objective** | A versioned, human-entered, manual-cited ruleset per season (2024, 2025, 2026, then each new season) for alliance selection and the playoff bracket. Every later milestone reads it instead of hard-coding rules |
| **Scope** | Alliance count by event size; selection order (serpentine or otherwise); captain rule; the decline rule and its consequences; backups; bracket format (2024–2026 double elimination) with match-to-bracket-slot mapping from TBA `competition_level` / `set_number`; finals series length; tie and replay handling; division-champion / Einstein structures |
| **Depends on** | P6-M0; P5-M1 (alliance data for checking) |
| **Inputs** | The official game manuals (human-entered, with section citations); TBA playoff match keys (`matches`: `semifinal` / `final` levels, ~200 events per season, 2024–2026) |
| **Implementation** | A schema extending the Phase 5 human-input infrastructure: draft → submit → named-reviewer approval → versions kept. A loader that refuses an unapproved or unknown-season ruleset. A bracket-graph builder from the ruleset |
| **Validation** | (a) **Bracket reproduction:** for every 2024–2026 event with playoff matches, the ruleset's bracket graph reproduces TBA's actual playoff match structure (slots, advancement edges). Mismatching events are listed, with a reason, and excluded from PX-3/PX-4 with counts. (b) **Selection-rule consistency** with P5-M1: the ruleset explains every recorded pick sequence; violations listed (P5-M1 found 9 seed–rank violations: 8 placeholder teams, 1 real anomaly) |
| **Acceptance criteria** | (a) and (b) recorded with counts. Every exclusion has a reason. No rule exists only in code |
| **Validation status** | Rulesets: `human_entered_reviewed`. Reproduction counts: descriptive |
| **Leakage** | None: rules are pre-season facts. The bracket reproduction reads outcomes only to check structure, never results |
| **Reproducibility** | Versioned, hashed rulesets; the reproduction check is recomputable from raw payloads |
| **Failure / escalation** | A format the ruleset cannot represent: the events are excluded with counts. If more than **10%** of events are excluded, escalate (P6-Q13) |
| **Evidence** | `.agent/phase6/results/p6_m1_ruleset_check.json` (write-once); approved ruleset versions with reviewer and date |
| **Non-goals** | Pre-2024 seasons; offseason events; inferring rules from data where a manual exists |
| **Human input** | **Yes:** entry from the manuals plus a named reviewer |
| **Prerequisite for** | P6-M4, P6-M6, P6-M7 |

### P6-M2 — PX-1: playoff match model

| | |
|---|---|
| **Objective** | A playoff-specific match win-probability model. The qualification model is not a playoff model (P5-D4) |
| **Scope** | Per playoff match: inputs as of match time; output P(red wins), **antisymmetric by construction** in alliance order and seed difference |
| **Depends on** | P6-M0; P5-M1 (seeds, alliance composition); Phase 4 features |
| **Inputs** | Alliance composition (three teams' point-in-time `TeamFeatures` at the selection moment); bracket round (from the P6-M1 slot mapping). **Features (P6-Q2), nothing else:** seed difference, alliance composition sums and bracket round (see the interpretation notes in the decision log). No earlier or in-playoff result is a feature. Absent values are never imputed |
| **Implementation** | One **regularized logistic regression** (P6-Q2) through the Phase 4 `Model` protocol and the registry.<br>• **Training:** the ~5,900 eligible 2024–2025 playoff matches.<br>• **Excluded:** EPA-incomplete rows and the 15 division-champion events with null seeds, counted.<br>• **Held out:** 2026 (the D7 split).<br>• **Never added:** XGBoost, hand-tuned weights, or features after seeing results |
| **Validation** | Single held-out 2026 run: log-loss, Brier, accuracy, ROC-AUC, ECE. **Baselines:** (i) M6/M7 applied to playoff matches (D18 playoff ECE 0.119); (ii) seed-only (historical higher-seed rate, fit on 2024–2025). Label-shuffle and as-of checks via the M8 audit |
| **Acceptance criteria** | **P6-Q3:** strictly better held-out 2026 playoff **log-loss** than **both** M6/M7 applied to playoff matches **and** the seed-only baseline. The paired event-bootstrap 95% CI of each comparison must exclude zero |
| **Validation status** | Until P6-M3 passes: `not_validated` (playoff_model_uncalibrated) |
| **Leakage** | Team features at the selection moment. No earlier or in-playoff result at the event is a feature (P6-Q2). No feature from the match itself or any later match. Seeds only after selection. The 2026 hold-out is never used for fitting or model selection |
| **Reproducibility** | Seeded; frame hash; registry manifest; write-once result |
| **Failure / escalation** | D9: if either P6-Q3 comparison fails, the failure is recorded, progression on the playoff track stops, and it is escalated. No change to the model, features, metric or population to manufacture a pass |
| **Evidence** | `.agent/phase6/results/p6_m2_px1.json`; frozen PX-1 spec; registry entry |
| **Non-goals** | Retraining M5 v2 or M6/M7; qualification predictions; bracket simulation |
| **Phase 4/5 foundations** | Assembler, registry, backtest harness (`Fold`), M8 audit, P5-M1 |
| **Human input** | No (beyond P6-M0 decisions) |
| **Prerequisite for** | P6-M3, P6-M4 (real probabilities), P6-M10 (playoff context) |

### P6-M3 — PX-2: playoff-only calibration and validation

| | |
|---|---|
| **Objective** | Calibrate PX-1 on playoff data only, and test calibration as M7 did, so that playoff match probabilities can be served as validated if, and only if, they pass |
| **Scope** | A calibrator fit on a temporally prior, playoff-only slice; a stratified, playoff-only per-bin test on held-out 2026 |
| **Depends on** | P6-M2 |
| **Inputs** | PX-1 outputs; the calibration slice = the **temporally last 20% of 2025 playoff matches** (P6-Q4) |
| **Implementation** | Reuse `ml/calibration/` (isotonic/Platt, symmetric serving) with antisymmetry in seed; fit isolation enforced structurally |
| **Validation** | The M7 gate structure (D16): G1 ECE; G2 exact Poisson-binomial per-bin test, Holm-corrected, on bins with enough predictions; G3 (anti)symmetry; G4 fit isolation |
| **Acceptance criteria** | **P6-Q4:** the M7/D16 constants unchanged: ECE < 0.05; 10 fixed bins; per-bin test on bins with ≥ 30 predictions, Holm α = 0.05; symmetry 1e-12; fit isolation. All four gates must pass |
| **Validation status** | Pass: playoff match probabilities `validated_playoff` (P6 label, scope stated). Fail: `not_validated` (`px2_gate_failed`) |
| **Leakage** | The calibration slice precedes every evaluated match; never 2026 |
| **Reproducibility** | Write-once result with bin counts |
| **Failure / escalation** | D9. A PX-2 failure is recorded, playoff probabilities stay `not_validated`, and the dependent selection outputs carry it. No change to calibrator, bins or test after the result |
| **Evidence** | `.agent/phase6/results/p6_m3_px2.json` |
| **Non-goals** | Recalibrating M7; qualification calibration |
| **Human input** | No |
| **Prerequisite for** | P6-M5; the validated status of P6-M7 and of playoff-context strategy odds (P6-M10) |

### P6-M4 — PX-3: bracket and series simulator

| | |
|---|---|
| **Objective** | Given eight (or the event's number of) alliances, the event's ruleset and a match-probability function, compute each alliance's probability of every bracket outcome: winning the event, reaching the finals, elimination round |
| **Scope** | 2024–2026 double elimination per P6-M1, with the finals series; division and Einstein structures where the ruleset represents them |
| **Depends on** | P6-M1; P6-M2 for real probabilities (built and tested with synthetic probability functions) |
| **Inputs** | Alliances; ruleset; match-probability function (PX-1/PX-2) |
| **Implementation** | **Exact** computation by dynamic programming over bracket states (deterministic, no sampling), with an independent seeded Monte Carlo used only as a test oracle |
| **Validation (implementation correctness)** | Probabilities sum to 1 per round; exact equals Monte Carlo within its standard error on randomized instances; known closed-form cases (e.g., every match at 0.5); bracket graph equals P6-M1's reproduced structure; invariance to alliance relabelling |
| **Acceptance criteria** | All correctness tests pass. Predictive validity is P6-M5's job, not this milestone's |
| **Validation status** | Inherits the probability function's status; with PX-1 before PX-2 passes: `not_validated` |
| **Leakage** | Pure function of its inputs; no data access |
| **Reproducibility** | Deterministic; Monte Carlo oracle seeded |
| **Failure / escalation** | A structure the simulator cannot represent is refused with a reason, never approximated silently |
| **Evidence** | Test suite; `.agent/phase6/results/p6_m4_simulator_check.json` |
| **Non-goals** | Predicting alliance formation (P6-M6); backup-robot substitutions (backups unknown in data) |
| **Human input** | No |
| **Prerequisite for** | P6-M5, P6-M7 |

### P6-M5 — PX-4: simulator validation against real brackets

| | |
|---|---|
| **Objective** | Test whether the simulator's playoff-success probabilities, computed from the **actual** alliances at the selection moment, match real 2024–2026 bracket outcomes (held-out 2026 is primary) |
| **Scope** | Event-level outcomes: event winner, finalists and elimination round per alliance |
| **Depends on** | P6-M3 passed, P6-M4. A P6-M3 failure is a D9 stop: the playoff track continues only by Kanav's dated decision |
| **Inputs** | Actual alliances (P5-M1) at the selection moment; PX-1/PX-2 probabilities; P6-M1 rulesets; outcomes as labels |
| **Validation** | Single run on held-out 2026 events (sample, if any, per P6-Q13's dated pre-run record). Proper scoring, **log-loss primary** (Brier reported), of P(win event) and P(reach finals). **Baseline:** seed-only bracket probabilities (fit 2024–2025). Event-bootstrap CIs of the paired differences. Reliability/calibration bins **reported, not gated** |
| **Acceptance criteria** | **P6-Q5:** for **each** of P(win event) and P(reach finals), held-out log-loss strictly better than seed-only, with the event-bootstrap CI excluding zero. Only after a pass are playoff, bracket, series or playoff-success probabilities served as validated (P5-D4) |
| **Validation status** | Pass: `validated_playoff_success`, scope stated. Fail or PX-2 failed: `not_validated` |
| **Leakage** | Predictions use only selection-moment data; no playoff result enters; events whose ruleset reproduction failed (P6-M1) are excluded with counts |
| **Reproducibility** | Write-once record (frame hash, PX-1/PX-2 hashes, seed) |
| **Runtime** | Exact computation is expected to be cheap. If the population cannot run in ≤ 45 min, a seeded, stratified sample is fixed by a dated decision before the run (P6-Q13) |
| **Failure / escalation** | D9 |
| **Evidence** | `.agent/phase6/results/p6_m5_px4.json` |
| **Non-goals** | Evaluating predicted alliance formation (P6-M8) |
| **Human input** | No |
| **Prerequisite for** | The validated status of P6-M7's predicted playoff performance; P6-M8 |

### P6-M6 — Selection-time candidate profiles and draft model

| | |
|---|---|
| **Objective** | At the selection moment, a complete, explainable profile for every eligible candidate, and a model of how the rest of the draft will unfold |
| **Scope** | **Candidate factors** (roadmap): synergy, defense, feeding, reliability, consistency, role compatibility, plus scoring ability (Vision). **Draft model:** eligible teams, captain order, availability under the ruleset's decline rule, and the predicted picks of other captains: **deterministic best-available by the validated P5-M4 ordering**, with P6-M1's decline rules (P6-Q6) |
| **Depends on** | P6-M1; P5-M3; P5-M4 (ordering policy, captain candidates) |
| **Inputs** | Point-in-time `TeamFeatures`; Phase 3 metrics (reliability, consistency) with n; scouting-only defense/feeding (`insufficient_data` when thin, which today is every event); M9 share vectors for role compatibility (P6-A10); final qualification rankings (known at the selection moment) |
| **Implementation** | Pure functions over point-in-time inputs; every factor carries its value, n, presence and `validation_status`; nothing imputed. The draft model is deterministic (P6-Q6); no probabilistic pick model |
| **Validation** | (a) Exact equality of each factor with its Phase 3/4/5 source function on a seeded sample. (b) **Opponent-pick prediction** measured once on held-out 2026 events against P5-M1 actual picks: top-1 / top-3 hit rate per pick slot, with CIs, next to a raw-EPA-order baseline |
| **Acceptance criteria** | (a) exact. (b) recorded as measured; draft-prediction accuracy **does not gate** the engine (P6-Q6) |
| **Validation status** | Factors: as their sources. Defense: quality only (P6-Q11), `descriptive_definition_pending` / `insufficient_data`. Feeding: `insufficient_data`. Synergy: `not_validated_against_outcomes`, descriptive only. Draft model: `validated_as_measured` at most |
| **Leakage** | Nothing after the selection moment; actual picks are labels only |
| **Reproducibility** | Deterministic given as_of, snapshot and commit |
| **Failure / escalation** | Missing inputs propagate as `insufficient_data`; a missing ruleset is refused |
| **Evidence** | `.agent/phase6/results/p6_m6_profiles_draft.json` |
| **Non-goals** | New defense/feeding measurement; any inferred defense or feeding |
| **Human input** | No (defense definition decided by P6-Q11) |
| **Prerequisite for** | P6-M7 |

### P6-M7 — Alliance selection engine (pick-list optimizer)

| | |
|---|---|
| **Objective** | For a given captain (seed) at a given event state, a ranked pick list that maximizes **playoff win probability** (P6-A2; confirmed by P6-Q7), with reasoning, and 3–5 alternative alliance configurations with predicted playoff performance |
| **Scope** | Each pick decision in the draft; the objective evaluated by PX-3 over the predicted field from P6-M6's draft model; the factor profiles reported for every candidate |
| **Depends on** | P6-M4, P6-M6 (P6-M5 for validated status) |
| **Inputs** | P6-M6 profiles and draft model; PX-1/PX-2; P6-M1 ruleset |
| **Implementation** | Exact enumeration where the candidate space allows; otherwise OR-Tools with a proven optimality certificate. Deterministic tie-breaking. **Reasoning** = structured attribution: each candidate's change in P(win event) and in P(reach finals) versus the next-best candidate, plus its factor profile (no LLM text) |
| **Validation (optimization correctness)** | On small instances, brute force equals the optimizer exactly. Monotonicity and sanity properties; determinism; never ranks by raw scoring alone (a test where the highest scorer is not the best pick under the model) |
| **Acceptance criteria** | All correctness checks pass; each output carries the probability's validation status (from P6-M3/M5) |
| **Validation status** | Predicted playoff performance: `validated_playoff_success` only if P6-M5 passed; otherwise `not_validated`. Factors: as P6-M6 |
| **Leakage** | Selection-moment inputs only |
| **Reproducibility** | Deterministic; output hash recorded |
| **Failure / escalation** | Infeasible draft states (ruleset conflicts) are refused with a reason |
| **Evidence** | Test suite; `.agent/phase6/results/p6_m7_optimizer_check.json` |
| **Non-goals** | HTTP endpoints and UI (Phase 7 / 8, P6-A1); backups |
| **Human input** | No |
| **Prerequisite for** | P6-M8 |

### P6-M8 — Alliance selection historical validation (P6-DM1)

| | |
|---|---|
| **Objective** | Demonstrate P6-DM1 on real past events, measured once |
| **Scope** | Replay each event in the pre-registered population at its selection moment; run the full engine (P6-M6 draft model + P6-M7) for every captain; compare with what actually happened |
| **Depends on** | P6-M5, P6-M7 |
| **Inputs** | Held-out events (P6-Q1 population), at selection-moment data; P5-M1 actual alliances and outcomes as labels |
| **Validation** | The P6-DM1 test exactly as P6-Q1 defines it (see "Phase 6 done-means"), with the raw-EPA-draft and actual-seed-ordering baselines. **A defensible-reason review:** each miss gets a reason from the predefined categories (fixed in the dated pre-run record before any result), and a **named mentor** accepts or rejects it |
| **Acceptance criteria** | **P6-Q1:** more than 50% of the strong alliances (winner and finalist) identified, pooled, with the event-bootstrap CI reported. Misses without an accepted reason count as misses |
| **Validation status** | Recorded as measured; P6-DM1 met or not met |
| **Leakage** | A selection-moment sentinel: a future playoff result inserted in the isolated copy must not change any output |
| **Reproducibility** | Write-once record (population seed, frame hash, commits); a re-executable replay |
| **Runtime** | ≤ 45 min with its own budget; a stratified sample if needed, fixed before the run (P6-Q13) |
| **Failure / escalation** | D9: a P6-DM1 miss is recorded; no change to the engine, draft model, definitions or population after the result |
| **Evidence** | `.agent/phase6/results/p6_m8_dm1.json`; the human review artifact |
| **Non-goals** | Live 2027 validation (recommended follow-up, not a gate) |
| **Human input** | **Yes:** the defensible-reason review (named reviewer) |
| **Prerequisite for** | P6-M14 (P6-DM1) |

### P6-M9 — Strategy representation, coach scenarios and coach observations

| | |
|---|---|
| **Objective** | One data type for a match strategy, used identically by the optimizer and by coaches; a structured, validated way to enter a coach strategy and coach observations |
| **Scope** | **Strategy** = per-robot role assignment over the season's role vocabulary, defensive assignments (defender → target robot), and scoring priorities over score components. The vocabulary is at the score-component level from the P5-M7 adapters (auto / teleop / endgame) plus defense and feeding roles (P6-A8); game-spec actions only when an approved P5-M8 spec exists. **Coach observations** = structured, timestamped, attributed measured inputs (e.g., a mechanism unavailable today), shared by both paths (P6-A9) |
| **Depends on** | P6-M0; P5-M7 adapters; Phase 5 human-input infrastructure |
| **Inputs** | Season vocabulary; coach entries |
| **Implementation** | A source-free `Strategy` value type: **no field records who proposed it**. Provenance (AI or coach, author, time) is stored beside it, never inside it. Coach strategies and observations land raw-first and are validated against the vocabulary. Free-text notes never enter any model |
| **Validation** | Schema tests; round trip; the extended M8 no-strategy-leakage check covers `Strategy` and every evaluation input |
| **Acceptance criteria** | Schema, validation and leakage tests pass; no source field reachable from the evaluation inputs |
| **Validation status** | Inputs: `human_entered` (coach) or `optimizer_output` (AI), stored as provenance only |
| **Leakage** | Coach observations are usable only for matches after their timestamp |
| **Reproducibility** | Versioned, hashed |
| **Non-goals** | UI and HTTP routes (Phase 7 / 8); LLM parsing of coach notes |
| **Human input** | No for the build. Real coach entries come later and are never fabricated as evidence |
| **Prerequisite for** | P6-M10, M11, M13 |

### P6-M10 — Strategy-conditional outcome model (the single odds model)

| | |
|---|---|
| **Objective** | **The** win-probability model both strategy paths use: P(win) for an alliance pair **given each side's strategy**, honest and data-driven (P6-A4) |
| **Scope** | Qualification context; playoff context only on top of PX-1/PX-2 (P6-A12) |
| **Depends on** | P6-M9; Phase 4 features; P6-M3 for the playoff context |
| **Inputs** | Point-in-time `TeamFeatures` (EPA components, Phase 3 metrics), measured defense/feeding where present, coach observations as measured adjustments, both strategies |
| **Implementation** | **The component model (P6-Q8):**<br>• per-component score distributions from measured robot/team capabilities and role allocation;<br>• P(win) from the score difference;<br>• role allocation re-weights component contributions **only within measured capability**;<br>• defense and feeding effects only from measured data, otherwise **zero assumed effect**, labelled `not_validated` / `insufficient_data`.<br>It reduces to a "no strategy specified" baseline. There is one evaluation entry point: `evaluate(context, strategy_red, strategy_blue)` |
| **Validation** | Baseline predictions on held-out 2026 **EPA-complete qualification** matches through the M7 gate constants. Paired log-loss vs M6/M7 is reported. Strategy effects are validated only where measured data exist (today none, so no defense or feeding effect is identifiable from 0 scouting rows) |
| **Acceptance criteria** | **P6-Q9:** the M7 gate constants pass on the baseline. P6-M10 is **not required to outperform** M6/M7, and is not declared successful merely because its numbers differ |
| **Validation status** | Baseline: by P6-Q9's result. Any non-baseline strategy: `not_validated` (`strategy_effect_unmeasured`) until measured. Playoff context: inherits P6-M3. Low odds are shown low (P6-A5) |
| **Leakage** | Features as of match time; outcomes labels only; strategy never derived from the match's own outcome |
| **Reproducibility** | Seeded, registry-pinned, write-once result |
| **Failure / escalation** | D9; a failed baseline gate is recorded, and its odds are served `not_validated` |
| **Evidence** | `.agent/phase6/results/p6_m10_outcome_model.json` |
| **Non-goals** | Modifying M6/M7 (frozen); inferring defense or feeding from scoring |
| **Human input** | No |
| **Prerequisite for** | P6-M11, M12, M13 |

### P6-M11 — Match strategy optimizer (AI recommendation)

| | |
|---|---|
| **Objective** | Recommend role assignments, defensive assignments and scoring priorities that maximize P(win) under P6-M10, with alternatives and explanations, and no LLM |
| **Scope** | Your alliance's strategy, given the opponent's strategy: the opponent's "no strategy specified" baseline, or a coach-specified opponent strategy. **No opponent best-response optimizer** in Phase 6 (P6-Q10) |
| **Depends on** | P6-M10 |
| **Implementation** | Exhaustive search over the finite strategy space where feasible (three robots × vocabulary), else OR-Tools with an optimality certificate; deterministic tie-breaking. **It calls only P6-M10's single entry point.** It never adds, adjusts or caches a probability itself |
| **Validation (optimization correctness)** | Brute force equals the optimizer on the full space for small vocabularies; determinism; the recommended strategy's odds equal a fresh `evaluate` call on the same inputs, bit for bit |
| **Acceptance criteria** | All correctness checks pass. **Presentation (P6-Q10):**<br>• the AI and coach paths are shown identically, as model odds with P6-A5 rounding;<br>• a difference below one display step is labelled "indistinguishable at model resolution";<br>• the maximum over candidate strategies is never presented as an unbiased probability;<br>• an AI strategy is never called superior merely because its estimate is higher |
| **Validation status** | That of P6-M10 for the chosen strategy (usually `not_validated` for non-baseline strategies) |
| **Leakage** | As P6-M10 |
| **Reproducibility** | Deterministic |
| **Non-goals** | Pre-match report text (Phase 8 / 9) |
| **Human input** | No |
| **Prerequisite for** | P6-M12, M13 |

### P6-M12 — Match strategy historical validation

| | |
|---|---|
| **Objective** | Real historical evidence for what can be validated: the outcome model's baseline on held-out matches, and the point-in-time correctness of the full strategy engine replayed at match time |
| **Scope** | A seeded, stratified sample of held-out 2026 qualification matches (and playoff matches if P6-M3 passed). Population and size fixed by decision before the run (P6-Q13), within 45 min |
| **Depends on** | P6-M10, P6-M11 |
| **Validation** | (a) The baseline calibration result of P6-M10 reproduced from the replayed engine. (b) Point-in-time sentinels: no output changes when future rows are inserted. (c) Honest-odds checks: the full range of reported odds is preserved (no floors), and the probabilities of the two sides sum correctly. (d) An optional qualitative mentor review of sampled recommendations, recorded and not gating (Vision "Definition of Success") |
| **Acceptance criteria** | (a) exact reproduction; (b) zero changes; (c) all hold. No claim that recommended strategies improve outcomes (unmeasurable from historical data, P6-A4) |
| **Validation status** | As measured |
| **Evidence** | `.agent/phase6/results/p6_m12_strategy_validation.json` |
| **Human input** | Optional mentor review (genuine only) |
| **Prerequisite for** | P6-M14 |

### P6-M13 — Odds parity and unbiasedness audit (P6-DM2)

| | |
|---|---|
| **Objective** | Verify P6-DM2: zero mechanism for AI strategies to receive inflated odds |
| **Scope** | All code paths from strategy input to displayed probability |
| **Depends on** | P6-M9, M10, M11 |
| **Validation** | **Structural:** one evaluation entry point, and no reachable input or branch depends on strategy provenance (import-graph and AST checks; the M8 audit extended). **Metamorphic:** a coach strategy identical to the AI's gets bit-identical odds; relabelling provenance changes nothing; robot-order permutation is invariant; a colour swap gives 1 − p; the same display rule applies. **Adversarial:** a deliberately broken fixture that favours the AI path is caught by each check (the Phase 4 M8 "teeth" standard). **Honest low odds:** values outside the validated display range are shown as bounds, identically for both paths (P6-A5) |
| **Acceptance criteria** | Every check passes on the real engine, and every planted defect is caught |
| **Validation status** | P6-DM2 met or not met |
| **Evidence** | `.agent/phase6/results/p6_m13_parity_audit.json` (write-once); a one-command audit script |
| **Human input** | No |
| **Prerequisite for** | P6-M14 (P6-DM2) |

### P6-M14 — Documentation, contract tests and sign-off

| | |
|---|---|
| **Objective** | `docs/phase6.md` documenting every output and its `validation_status`; contract tests pinning docs to code and records; `scripts/phase6_done_means.py` reporting P6-DM1 and P6-DM2 from the write-once records alone; a phase acceptance review |
| **Depends on** | All of the above |
| **Done-means** | P6-DM1 and P6-DM2 recorded with real evidence, or Phase 6 stays open |
| **Human input** | Kanav's phase acceptance |

---

## Dependency graph

```
P6-M0 (freeze; P6-Q0 code baseline)
 ├─ P6-M1 rulesets [human] ─┬─ P6-M4 PX-3 simulator ─┐
 │                          └─ P6-M6 profiles + draft model ─┐
 ├─ P6-M2 PX-1 ─ P6-M3 PX-2 ─┬─ P6-M5 PX-4 ◄─ P6-M4         │
 │                           │                               ▼
 │                           │        P6-M7 selection optimizer ◄─ P6-M4
 │                           │                 │
 │                           └──────────► P6-M8 DM1 validation [human review]
 ├─ P6-M9 strategy repr. ─ P6-M10 outcome model (playoff ctx ◄ P6-M3)
 │                              ├─ P6-M11 strategy optimizer
 │                              ├─ P6-M12 strategy validation
 │                              └─ P6-M13 parity audit (DM2) ◄─ P6-M9, M11
 └────────────────────────────────────────────── P6-M14 sign-off ◄─ all
```

| Milestone | Depends on | Human input | Prerequisite for |
|---|---|---|---|
| P6-M0 | Phase 5 checkpoint | Kanav | all |
| P6-M1 | M0, P5-M1 | yes (manual entry + reviewer) | M4, M6, M7 |
| P6-M2 (PX-1) | M0, P5-M1 | no | M3, M4, M10 |
| P6-M3 (PX-2) | M2 | no | M5, M7 status, M10 playoff |
| P6-M4 (PX-3) | M1 (M2 for real use) | no | M5, M7 |
| P6-M5 (PX-4) | M3, M4 | no | M7 status, M8 |
| P6-M6 | M1, P5-M3, P5-M4 | no | M7 |
| P6-M7 | M4, M6 (M5 for status) | no | M8 |
| P6-M8 (DM1) | M5, M7 | yes (review) | M14 |
| P6-M9 | M0, P5-M7 | no | M10, M11, M13 |
| P6-M10 | M9 (M3 for playoff) | no | M11, M12, M13 |
| P6-M11 | M10 | no | M12, M13 |
| P6-M12 | M10, M11 | optional mentor review | M14 |
| P6-M13 (DM2) | M9, M10, M11 | no | M14 |
| P6-M14 | all | Kanav | — |

**Independent tracks.** The strategy track (M9 → M13) does not depend on the alliance-selection track, except that M10's playoff context needs M3. Following the Phase 4 practice, independent milestones may proceed while another is blocked, but no milestone may be accepted ahead of its own gate.

**A D9 stop on the playoff track** (a P6-M2, P6-M3 or P6-M5 failure) has these consequences:
- the selection engine's probabilities stay `not_validated`;
- P6-M8 does not run until Kanav decides how to proceed, by a dated decision made before any P6-M8 result;
- P6-DM1 stays unmet meanwhile.

The strategy track's qualification context is unaffected.

## Explicit non-goals of Phase 6

- HTTP endpoints, locked response shapes and the UI. These are Phase 7 and 8 (P6-A1); the Phase 5 human-input web app is reused only for data entry.
- LLM report text (Phase 9).
- Re-validation across 2022–2023 (Phase 10).
- Any change to Phase 4 or Phase 5 models, criteria or records.
- New defense or feeding measurement (Phase 3 M14).
- Backup-robot modelling (backups unknown in data).
