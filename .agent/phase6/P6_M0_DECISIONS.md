# Phase 6 — P6-M0 decision log

## P6-M0 freeze statement

**P6-M0 is FROZEN.**

| | |
|---|---|
| Approved by | Kanav, 2026-10-04 |
| Freeze commit | The commit introducing `.agent/phase6/P6_M0_FREEZE.md` ("phase6: freeze P6-M0 specification"); blob hashes are in that file |
| P6-A1 … P6-A12 | All approved exactly as proposed in revision 1 (commit `471046f`) |
| P6-Q0 … P6-Q13 | All decided (below) |
| Phase 6 implementation | None |

**Revision history:** revision 1 (`471046f`) listed the ambiguity resolutions as proposed, and the open decisions with options and proposed defaults. Revision 2 (this file) records Kanav's approvals and decisions.

**From this freeze on:**
- Methodology and acceptance criteria change only by a new, dated decision row made **before the affected result exists**.
- A change made after seeing a result is never permitted.
- **D9 is binding:** a genuine failure stops and escalates, and only objectively demonstrated implementation defects may be fixed.

**Unchanged by Phase 6:**
- Phase 4 and Phase 5 decisions, criteria and records: P5-D3, P5-D4, P5-D11 and P5-D13 included;
- M6/M7, which stay frozen and unmodified;
- the 45-minute verification limit;
- the permanent test-database guard.

---

## Ambiguity resolutions — APPROVED (Kanav, 2026-10-04), exactly as proposed

| ID | Ambiguity | Approved resolution | Why |
|---|---|---|---|
| P6-A1 | ROADMAP Phase 7 lists the "match strategy" and "alliance selection" endpoints, but Phases 4 and 5 added endpoints within their own phases | Phase 6 delivers engines, service functions, write-once evaluation records and CLI entry points. **HTTP endpoints and locked response shapes are Phase 7**; UI is Phase 8. Coach entry in Phase 6 is the validated service function plus raw-first storage (as Phase 3 M7 did) | ROADMAP names these endpoints explicitly in Phase 7, and its done-means there ("no endpoint shape changes after frontend work begins") presumes they are designed then |
| P6-A2 | "Optimizing for playoff win probability": per match or per event? | The objective is **P(the alliance wins the event's playoffs)**, computed by PX-3 (P6-M4) from PX-1/PX-2 match probabilities over the predicted field. P(reach finals) is reported alongside, never optimized | Vision: "The objective is to maximize playoff success". Event-level success is what a pick changes |
| P6-A3 | ROADMAP: "score every candidate pick using synergy, defense, feeding, reliability, consistency, and role compatibility", while also "optimizing for playoff win probability" | Every candidate gets a **profile** of all six factors (plus scoring ability), with values, n and validation status: the reasoning shown to users. The factors **affect the objective only through PX-1's pre-registered features**: no hand-set weights, no second scoring formula. A factor PX-1 does not use, or that lacks data, is shown descriptively and never imputed | Vision: "data-driven"; never fabricate estimates |
| P6-A4 | "The same win probability model" for both paths, while M6/M7 has **no strategy input** | One new **strategy-conditional outcome model** (P6-M10) is "the same model" for both paths. M6/M7 stays frozen and unmodified and serves as the comparator for P6-M10's no-strategy baseline. **Historical strategy effects are `not_validated`** unless measured strategy data exists | Ad-hoc strategy fields on M6/M7 would be neither the same model nor honest |
| P6-A5 | "Report them low" vs the [0.05, 0.95] display clip | Phase 6 outputs show below 0.05 as **"<5%"** and above 0.95 as **">95%"**. Otherwise the Phase 4 rounding applies (0.05 steps, symmetric). The rule is identical for the AI and coach paths. M12's existing serving is not changed | Honest low odds without unsupported precision |
| P6-A6 | P6-DM1 says "against **a** real past event" | P6-M8 runs on a **pre-registered population** of held-out events (P6-Q1), not one cherry-picked anecdotal event | Vision "Accuracy Above All"; MASTER_BUILD ML integrity |
| P6-A7 | "3–5 alternative alliance configurations" | The 5 best distinct feasible alternatives when at least 5 exist, otherwise all feasible ones (minimum 3 when that many exist), each with predicted playoff performance and status. Fewer than 3 is stated with the reason | Literal, never padded |
| P6-A8 | Strategy roles vs game-spec actions not yet entered | The strategy vocabulary is the **score-component level** (P5-M7 adapters: auto, teleop, endgame) plus defense and feeding roles. Game-spec-level actions only when an approved P5-M8 spec exists | Data-backed; no hidden dependency on DM1 inputs |
| P6-A9 | Coach observations as input | **Structured, timestamped, attributed** measured inputs, applied identically to both strategy paths. Free text never enters a model | Vision "Data-Driven Decisions"; P6-DM2 "same inputs" |
| P6-A10 | ROADMAP Phase 4 "weighted combination" synergy vs M9 as built | M9 is consumed **exactly as built**. Its predictive value is tested only as a candidate PX-1 feature. Role compatibility = M9's role-fit share vectors | Phase 4 contract preserved |
| P6-A11 | Phase 5 implementation is on `phase5/build` @ `6e76520`, not on `main` | Recorded as a hard dependency; resolved by P6-Q0 | Explicit dependency |
| P6-A12 | Playoff strategy odds need a playoff model | The P6-M10 playoff context is served only on top of PX-1/PX-2. If P6-M3 fails, playoff strategy odds are `not_validated`. Qualification validation is independent | P5-D4 |

---

## Decisions — all DECIDED (Kanav, 2026-10-04)

| ID | Status | Decision | Affects |
|---|---|---|---|
| P6-Q0 | **DECIDED** | **Code baseline: option (a).** Merge `phase5/build` at `6e76520` into `main`, **with Kanav's explicit approval of that merge**, then branch Phase 6 from the resulting `main`. Not silent. The `phase5/build` branch and its history are preserved. Kanav's unstaged `.gitignore` is preserved. PR #29 is not touched. **The merge has NOT been performed** (see "Prerequisite before implementation" below) | all implementation |
| P6-Q1 | **DECIDED** | **P6-DM1 operational definition.**<br>• **Population:** held-out **2026** events; a seeded population stratified by **week and event size**, within the 45-minute budget. The exact sample is fixed in P6-M8's dated pre-run record (P6-Q13).<br>• **Strong playoff alliances:** the **event winner and the finalist**.<br>• **"Identifies":** a predicted alliance that (i) contains the actual captain, (ii) contains at least one actual pick, and (iii) is among the engine's **top 2 predicted contenders**.<br>• **"Most":** **> 50% pooled** over strong alliances, with an **event-bootstrap confidence interval** reported.<br>• **Defensible reasons:** use **predefined reason categories**, fixed in P6-M8's dated pre-run record before any result. Each is reviewed by a **named mentor**; a miss without an accepted reason counts as a miss.<br>• **Baselines:** a **raw-EPA draft** and **actual-seed ordering**.<br>Not changed after results | P6-M8 |
| P6-Q2 | **DECIDED** | **PX-1 playoff model.**<br>• **Model:** **regularized logistic regression**.<br>• **Features:** **seed difference**, **alliance composition sums**, **bracket round** — nothing else.<br>• **Excluded as features:** earlier playoff results from the same event, and any in-playoff result.<br>• **Excluded from training:** EPA-incomplete rows, and the **15 division-champion events with null seeds**; exclusion counts reported.<br>• **Training data:** the ~5,900 eligible 2024–2025 playoff training matches available.<br>No XGBoost, no hand-tuned weights, and no added features after seeing results | P6-M2 |
| P6-Q3 | **DECIDED** | **PX-1 gate.** PX-1 must have **strictly better held-out 2026 playoff log-loss than both** (1) the frozen M6/M7 model applied to playoff matches and (2) a seed-only baseline. The **paired event-bootstrap 95% CI for each comparison must exclude zero**. If either fails: D9, stop and escalate | P6-M2 |
| P6-Q4 | **DECIDED** | **PX-2:** the M7/D16 constants **unchanged**: ECE < 0.05; 10 fixed bins; per-bin exact Poisson-binomial test on bins with ≥ 30 predictions, Holm at α = 0.05; symmetry tolerance 1e-12; fit isolation. **Calibration slice = the temporally last 20% of 2025 playoff matches.** Not altered after results | P6-M3 |
| P6-Q5 | **DECIDED** | **PX-4 gate.** Evaluate both **P(alliance wins event)** and **P(alliance reaches finals)** against a **seed-only baseline**, with proper scoring rules (primarily **log-loss**). Each requires strictly better held-out performance, with the **event-bootstrap CI excluding zero**. Reliability and calibration bins are **reported, not an additional gate** | P6-M5 |
| P6-Q6 | **DECIDED** | **Draft model:** deterministic **best-available by the validated P5-M4 ordering**, with P6-M1's decline rules. Draft-prediction accuracy is **measured and reported and does not gate** the alliance-selection engine. No probabilistic pick model without a later, separately approved decision | P6-M6, M7, M8 |
| P6-Q7 | **DECIDED** | **P6-A2 and P6-A3 are approved.**<br>• Optimization target = **P(win event)**.<br>• The six roadmap factors are candidate explanatory/profile features. They enter the objective only through pre-registered PX-1 features.<br>• No weighted-factor scoring, no hand-set factor weights, and no fabricated values for unavailable factors | P6-M6, M7 |
| P6-Q8 | **DECIDED** | **Strategy-conditional model (P6-M10): the component model.**<br>• It models per-component score distributions from measured robot/team capabilities and role allocation, and derives P(win) from the score difference.<br>• Role allocation may re-weight component contributions **only within measured robot capability**.<br>• Defense and feeding effects enter **only when measured data exists**. Otherwise they are `not_validated` / `insufficient_data`, with **zero assumed effect**, never an invented estimate | P6-M10 |
| P6-Q9 | **DECIDED** | **P6-M10 baseline gate:** the M7 gate constants on held-out 2026 **EPA-complete qualification** matches. Paired log-loss vs M6/M7 is **reported**, and P6-M10 is **not required to outperform** M6/M7. It is not declared successful merely because its numbers differ. Failing its stated criteria: D9 | P6-M10 |
| P6-Q10 | **DECIDED** | **Presentation and opponent.**<br>• The AI and coach paths are presented **identically**: model odds, with P6-A5 rounding.<br>• A difference smaller than one display step is labelled **"indistinguishable at model resolution"**.<br>• **No opponent best-response optimizer** in Phase 6. The opponent input is the baseline strategy or a structured coach-entered strategy.<br>• The maximum over many candidate strategies is never presented as an unbiased probability, and an AI strategy is never called superior merely because its model estimate is higher | P6-M11, M13 |
| P6-Q11 | **DECIDED** | **Defense definition** (resolves the open Phase 3 M14 definition question for Phase 6 use): Phase 6 uses **defense quality only**, when a validated defense-quality measurement exists. No defended-frequency or volume term unless separately established and approved. Until then: defense `descriptive_definition_pending` / `insufficient_data` as appropriate, no invented value, no claimed predictive effect. **Feeding stays `insufficient_data`** until measured data exists | P6-M6, M10 |
| P6-Q12 | **DECIDED** | **Proceed with Phase 6 validation although `scouting_observations` has 0 rows.** Defense and feeding stay explicitly `insufficient_data` throughout validation. No fabricated observations, no observations inferred from outcomes, no backfilled hidden labels, no claim that defense or feeding effects are validated. A future Phase 3 extension may add measurements; it does not block Phase 6 | P6-M6, M8, M10, M12 |
| P6-Q13 | **DECIDED** | **Sampling protocol (frozen):**<br>• every sampling decision is made **before its run**, in a dated decision record per run;<br>• samples are seeded and stratified;<br>• each run has a hard **45-minute** maximum, and a projected or actual overrun means redesign before proceeding;<br>• no massive historical replay merely for verification when a seeded/stratified sample answers the question;<br>• a P6-M1 excluded-event share above **10%** escalates;<br>• no post-result sampling change.<br>The exact sample for each milestone is recorded in its own dated pre-run decision | P6-M1, M5, M8, M12 |

## Interpretation notes (necessary for consistency; not new decisions)

- **P6-Q2, "alliance composition sums":** the existing Phase 4 alliance representation, i.e. M6's input: `TEAM_FEATURE_NAMES` summed per alliance (`docs/ml_models.md` §2).
  - Antisymmetry (P5-D4) is preserved by entering seed difference and composition as **red − blue differences, with no intercept**.
  - A symmetric quantity such as **bracket round** can affect an antisymmetric probability only through its **interaction with those differences**.
  - Defense and feeding sums carry presence flags and are absent everywhere today (P6-Q12).
  - "Qualifying training matches" is read as the eligible 2024–2025 **playoff** matches, because PX-1 is a playoff model. The held-out 2026 population applies the same exclusion rules, counted.
- **P6-Q2 with P6-A3 and P6-A10:** M9 synergy is not among PX-1's decided features. In Phase 6 it is therefore shown descriptively in candidate profiles, and it does not enter the objective.
- **P6-Q4 with G4:** as in M7, the calibration slice lies inside the model's training period. Fit isolation means never fitting on the 2026 evaluation data.

## Prerequisite before implementation (P6-Q0)

**P6-M0 is frozen, but Phase 6 implementation must not begin until the P6-Q0 baseline exists.** The Phase 5 baseline merge has **not** been performed. It requires two things:
1. Kanav's explicit approval of the merge of `phase5/build` (`6e76520`) into `main`, and of the push that publishes the Phase 5 code on GitHub;
2. the merge itself, without rewriting history.

Phase 6 is then branched from the resulting `main`.
