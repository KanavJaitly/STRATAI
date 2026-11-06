# Phase 11 Addendum A (P11A): alliance-selection recommendation intelligence

**Status: PROPOSED (2026-11-05). Not approved. Nothing in this document is implemented.**

**Revision 1 (2026-11-05), after the owners' review.** It is narrow, and no requirement was removed. It:
- separates aggregate validation from validation of each robot's own estimate, and requires identifiability
  disclosure (A3, A7, E1);
- specifies the priors, how strongly estimates shrink toward them, and the fallback for thin evidence (A3);
- keeps expected score and win probability distinct throughout (B6, C, G1, §11, §17);
- defines the three active robots, and keeps a fourth alliance member and the event's backup robots out of the
  expected score (B3, §10);
- strengthens E5's counterfactual limits (§17, §20);
- makes the 45-minute limit apply to each individual run (§19, §20, Appendix A);
- adds **proposed defaults, not approved decisions**, for P11A-Q1 … Q10 (§21.3).

**Revision 2 (2026-11-05), a final narrow technical revision.** No requirement was removed. It:
- prevents the same match evidence from counting twice in the prior (A3.2);
- propagates the joint covariance of the robots' estimates through the scoring rules (A3, B5);
- tightens what counts as individual-robot ground truth (A2, A3, E1b);
- defines comparisons between candidates against a pre-registered margin, with an `unresolved` outcome (B6);
- separates alliance-level anomalies from robot-level outliers (G2).

**What this document is**
- It extends Phase 11 (`docs/P11-P19Phases.md` §5; built as `docs/phase11.md`). It does not replace that
  specification, and it does not change it.
- Requirement IDs are prefixed `P11A-`. Open product decisions are `P11A-Q<n>` (§21).

**Approval and change control**
- The project owners approve this document before any of it is built. Work starts only on their explicit
  instruction.
- After approval, a change to scope, a definition of success or an acceptance criterion needs a dated decision in
  `.agent/phase11/decisions/`, as in Phases 6–11.

**Who reads it**
- A future Claude Code session implementing it, which will start with no memory of this conversation.
- The project owners who approve it.

**Statements about the repository are dated 2026-11-05** (`main` at `3757d2a`). Re-verify each against the code
before relying on it (§3.0). Where this document and the code disagree, the code wins, and the difference is
reported before work proceeds.

---

## Contents

1. Title and scope
2. Relationship to the Phase 11 implementation
3. Current implementation inventory
4. Existing, partial and new functionality
5. Product objectives
6. Functional requirements (capabilities A–L)
7. Technical requirements and architecture
8. Data and methodology requirements
9. Model and optimization requirements
10. Draft-position and availability requirements
11. Frontend and user experience
12. API and backend integration
13. Security and permissions
14. Offline compatibility
15. Dependencies
16. Performance requirements
17. Definition of success
18. Acceptance criteria
19. Testing and verification
20. Historical evaluation
21. Risks, limitations and unresolved decisions

Appendices:
- Appendix A: global engineering constraints
- Appendix B: coverage check

---

## 1. Title and scope

**Purpose.** Today StratAI tracks the live draft and produces a picklist. This addendum turns that into
**team-specific alliance optimization**. Before alliance selection starts, StratAI should already:
- understand the event and the season's game;
- understand the team's own robot;
- evaluate every other robot at the event;
- work out which partners complement the team's robot best;
- produce first-pick and second-pick recommendations for the team's real draft position.

During selection, an administrator records every real action in the existing Phase 11 draft record, and the
recommendations follow the real draft.

**The question the system answers.** Given:
- the team's robot;
- the event;
- the season's scoring structure;
- the team's qualification rank and real draft position;
- the robots already selected;
- the robots likely to still be available;

which available robot, or combination of robots, gives the team the strongest alliance?

**In scope:**
- per-robot capability estimation at the event (A);
- combination-level alliance value (B);
- separate first-pick (C) and conditional second-pick (D) optimization;
- draft-position awareness, including non-captain teams (E);
- predicted availability, kept apart from confirmed availability (F);
- evidence-based explanations and the team profile (G);
- live integration with the Phase 11 record (H);
- offline readiness (I);
- the hybrid architecture (J);
- pre-registered evaluation (K);
- live-event performance (L).

**Out of scope:**
- the Go Local runtime and its synchronization (Phase 12);
- match-level strategy simulation (Phases 14–15);
- the pre-match report items (Phases 16–17).

This addendum consumes those phases where they exist, and states what it needs from them.

**Not allowed:**
- a second draft model, draft log, recommendation engine, team-profile system or authentication path;
- an LLM anywhere in the numerical path (`CLAUDE.md`, Critical Constraints).

---

## 2. Relationship to the Phase 11 implementation

**Phase 11's real status: implemented, NOT accepted** (`.agent/phase11/PHASE_STATUS.md`, `docs/phase11.md`).
- It is committed in `3757d2a`.
- The pure-logic tests, the contract tests and the page tests pass.
- The DB-backed API tests (`tests/test_phase11_live_draft_api.py`) are written but **not run**, because the build
  machine had no PostgreSQL.
- The real-data replay (`scripts/phase11_replay.py`) is written but **not run**.
- So **P11-DM1 is NOT MET**, and the phase has no human acceptance.

The brief for this addendum calls Phase 11 "complete and extensively verified". The records do not support that.
**P11A depends on Phase 11 being verified** (§15).

**What P11A consumes from Phase 11, unchanged:**
- **The draft record** (`workspaces/draft_log.py`).
  - It is an append-only log. The state is always `replay(entries)`.
  - It is the single source of truth for confirmed selections.
  - `DraftView.availability()` decides confirmed availability under the event's rules. Since the 2026-11-04 review
    fix, it includes `captain_may_accept_higher_alliance`.
- **The service and its permissions** (`workspaces/live_draft.py`; migration 0013):
  - `alliance_selection` to view;
  - `alliance_selection_record` to change.
- **The recommendation sources and their precedence** (`workspaces/draft_recommendations.py`, decision P11-Q1):
  - first the P6-M7 engine, which refuses today;
  - then P11-FB1, served `not_validated` with no probability.
- **The recommendation response contract.** `GET /workspace/alliance-selection/drafts/{record_id}/recommendations`
  is locked in `docs/api_contract_lock.json`, and every response carries `record_seq`.
- **The page** `/alliance-selection/live`, with its stale-marking rules.

**What P11A changes in Phase 11**, each only through a dated decision:
- P11-Q1's source precedence, which gains a new source (P11A-Q2);
- the page's main panel, which gains first-pick, conditional second-pick and combination views. The board,
  recording and history stay as they are.

---

## 3. Current implementation inventory

### 3.0 How to re-verify

Read the files named below before building. Useful checks:
- `grep -rn "alliance_synergy\|candidate_profile\|SelectionEngine\|turn_order" ml workspaces api`;
- `python -m scripts.phase7_contract_lock check`;
- the Phase 6/7/11 status files.

### 3.1 Inventory

| Area | Where | What it does today | Status |
|---|---|---|---|
| Draft state and order | `ml/playoffs/selection.py` (`DraftState`, `turn_order`, `pickable_teams`, `highest_ranked_captain`, `available_for_pick`) | Serpentine order, lazy captain naming (which covers promotion), and the decline and captain rules from the event's `SelectionRules` | Built, tested |
| Rulesets | `data/rulesets.py` (`SeasonRuleset.for_event`, `EventRules`, `SelectionRules`) | Approved 2024–2026 rulesets (ids 4–6). Per-event variants (FIRST Championship divisions use 3 picks, no backups) and exclusions. `null` means not established | Approved 2026-10-08 |
| Candidate profiles | `ml/playoffs/selection.py` `candidate_profile`; `ml/playoffs/service.py` `candidate_profiles` | Per team: scoring EPA, average score, reliability, consistency, defense, feeding, plus synergy and role compatibility for a given 3-team configuration. Each has a value, n and status. Nothing is imputed | Built; served by `GET /events/{event_key}/alliance-selection/candidates` (locked) |
| Draft model | `ml/playoffs/selection.py` `run_draft`, `best_available` | Deterministic: every other captain takes the first available team in the P5-M4 ordering (P6-Q6). The measured accuracy is top-1 **0.211** [0.199, 0.224] and top-3 0.451, against raw-EPA order at 0.227 / 0.470 (`.agent/phase6/results/p6_m6b_draft_accuracy_rerun1.json`) | Built; it predicts real picks poorly |
| Alliance-selection engine | `ml/playoffs/selection.py` `SelectionEngine.recommend` | For the advised seed's next turn it tries every available candidate. It completes the draft with the draft model, but **optimizes the advised alliance's own later picks by exhaustive search**. It ranks by P(win event) from the exact bracket simulator (`ml/playoffs/simulator.py`) over the predicted field. Ties break on P(reach finals). It gives up to 5 alternative configurations | Built; **refuses at every event**: PX-1 failed, and the PX-2/PX-4 records do not exist (D9) |
| Playoff match model | `ml/playoffs/px1.py` | Regularized logistic regression on red−blue seed and alliance-composition differences (sums of per-team vectors; `ml/models/team_vector.py`) | **Failed** its gate. PX-1b is a frozen candidate that needs the reserved 2027 holdout |
| Service gates | `ml/playoffs/service.py` `pick_list` | Checks, in order: ruleset → event rules → PX gate records → final ranks (`ranks_are_final`) → models → ordering → state | Built |
| Live recommendations | `workspaces/draft_recommendations.py` | The engine, else P11-FB1. FB1 is: primary = the first available team in the P5-M4 ordering; backups = the next max(3, m). It excludes the own alliance and projected captains that act first, and gives movement text | Built (Phase 11), not accepted |
| P5-M4 ordering | `ml/views/event_analysis.py` `analyze_event` | Raw EPA before the event's switch point, then M5 v2 (`ranking_xgb_v2`) | Validated as a strength ordering (`validated` / `validated_as_measured`) |
| Team features | `ml/features/assembler.py` `TeamFeatures`, `build_team_features` | Point in time. EPA total/auto/teleop/endgame from the team's **most recent concluded prior event only**, never the current one. Average alliance score, SD, consistency, reliability. The event's average alliance auto points. Defense and feeding from scouting. Each has a presence flag | Built, leakage-tested |
| Score components | `ml/features/score_breakdown.py` (auto), `ml/features/score_components.py` (auto/teleop/endgame/fouls/adjust) | Alliance-level component points from TBA breakdowns for 2024–2026, with a parity check on every row. Other seasons refuse (`UnsupportedSeasonError`) | Built |
| Synergy | `ml/synergy/score.py` `alliance_synergy` | A unit-free complementarity index for three teams: 1 − the mean pairwise cosine similarity of share vectors over (average score, defense, feeding) and (EPA auto/teleop/endgame), plus defense/feeding coverage | Built; `not_validated_against_outcomes`; **not an expected-score model** |
| Strategy outcome model | `ml/strategy/outcome.py` `ComponentOutcomeModel.evaluate` | Alliance component means are additive sums of each team's normalized prior-event EPA components, then P(win) = Φ(m/s). Defense and feeding effects are zero, labelled | Gate **failed** (D9); served `not_validated` |
| Strategy vocabulary | `ml/strategy/representation.py` | Per robot: a role (scoring, defense, feeding) and pursued components (auto, teleop, endgame). Coach observations: `component_unavailable`, `robot_unavailable` | Built |
| Game spec | `data/game_spec.py` `GameSpec`; `data/human_inputs.py` `approved_spec` | A human-entered, versioned season spec: scoring actions with points by period, endgame actions, ranking-point rules, field elements and match length. No LLM | Schema built; **no approved spec exists for any season** (P6-M9 note) |
| Team strength view | `ml/views/strength.py`; `GET /teams/{team_number}/events/{event_key}/strength` | EPA with provenance, Phase 3 statistics, good/average/bad days, season auto points per event. Each value has n and an uncertainty or an explicit "none" | Built, locked |
| Team page | `frontend/src/dashboard/pages/TeamPage.tsx` at `/events/:eventKey/teams/:team` | Strength, match history (alliance score per match), stored metrics, defense and feeding | Built (Phase 8) |
| Scouting | `scouting_observations` (shared); `workspace_scouting_reports` (team-private) | Defense and feeding quality, 0–5, only. Thin coverage. No pair has been rated by two scouts | Built |
| Final alliances and ranks | `data/alliances.py`; `data/rankings.py` | TBA final alliances (picks in order, declines; `backup` null 2024–2026), and final ranks | Built |
| EPA sources | `ml/ratings/` (D18 frozen; live Statbotics P5-D3 with `retrieved_at` snapshots) | Prior-event values selected by the D13 rule | Built |
| Workspaces | `workspaces/` (sessions, roles, permissions, activity log) | Accounts, roles (admin, strategy, scouter) and configurable permissions, scoped to a team | Built |

### 3.2 Answers to the brief's inventory questions

| # | Question | Answer (with location) |
|---|---|---|
| 1 | What does the engine calculate? | P(the advised alliance wins the event) and P(reach finals) for each available pick, from PX-1/PX-2 and the bracket simulator over the deterministic predicted field (`SelectionEngine`). Up to 5 alternatives. It refuses today |
| 2 | How are candidates ranked now? | When the engine serves: by P(win event). Today: P11-FB1, by the P5-M4 strength ordering, which is not team-specific. The `/candidates` operation is unranked profiles |
| 3 | What metrics exist? | `TeamFeatures` (§3.1), candidate profiles, the strength view and `team_metrics`. Per-robot event-specific scoring is **not** measured; only alliance scores and prior-event EPA components are |
| 4 | Is synergy calculated? | Yes, as a unit-free diversity index (`alliance_synergy`), reported in profiles and never used by any objective. It is not validated against outcomes |
| 5 | Combinations or individuals? | The engine evaluates combinations: the full predicted field, with exhaustive search over the advised alliance's own remaining picks. P11-FB1 ranks individuals only |
| 6 | Separate first and second picks? | Not as separate outputs. The engine's ranked entry carries the predicted `configuration` (the alliance the pick leads to), which implies a second pick. There is no conditional second-pick list and no "if A is taken" view |
| 7 | Does it account for rank and draft position? | Yes, by seed: the engine and P11-FB1 work for the alliance the team is on, or is projected to captain. FB1's backup count follows the picks before the next turn. Availability is never predicted, only confirmed |
| 8 | Does it predict availability before our turn? | Only implicitly: the engine's deterministic draft model fills other captains' picks. There are no probabilities. Phase 13 (proposed) specifies a pick-probability model |
| 9 | Auto/teleop/endgame/defense/reliability data? | Auto/teleop/endgame: per-team prior-event EPA components, and alliance-level component points per match. Defense and feeding: scouting quality only (0–5). Reliability: an INTERIM attendance ratio (`matches_used / matches_scheduled`), **not** a robot-failure rate. Penalties: alliance-level foul points only. Game-specific actions: none, because no approved GameSpec exists |
| 10 | Models, gates and records? | P5-M4 ordering (validated as a strength ordering); M5 v2 ranking; PX-1 FAILED; PX-1b frozen, awaiting 2027; P6-M10 FAILED; P6-M10b frozen, awaiting 2027; P6-M6 draft accuracy measured. Records: `.agent/phase6/results/`, `docs/phase6.md`, `docs/phase7.md` |
| 11 | Which interfaces can be extended? | `workspaces/draft_recommendations.recommend`; the draft-record API (additive operations under `/workspace/alliance-selection/drafts/{record_id}/…`); `candidate_profile` and `TeamFeatures`; the strength view and team page; GameSpec; the P5-M7 component adapters; the model registry (`ml/registry.py`); the backtest harness (`ml/backtest/harness.py`) |

---

## 4. Existing, partial and new functionality

**Legend:**
- **Reuse:** exists and meets the requirement; build nothing.
- **Extend:** exists in part; the added work is stated.
- **New:** nothing comparable exists.

| Cap. | Requirement | Classification | What exists → what P11A adds |
|---|---|---|---|
| A | Per-robot, event-specific capability | **Extend + New** | Exists: prior-event EPA components, alliance-level component points, scouting defense/feeding, the strength view. **New:** an in-event per-robot component estimator with uncertainty (P11A-A3), the observation-type labels (P11A-A2), and a season capability catalogue |
| A | Continuous updates | **Extend** | The `--watch` sync already recomputes `team_metrics` after each poll. **New:** a recompute trigger and cache for the per-robot estimator, keyed by data snapshot |
| B | Season scoring architecture | **Extend** | GameSpec and the P5-M7 component adapters exist. **New:** a versioned, reviewed *alliance scoring configuration* per season (P11A-B4), covering per-robot vs alliance-shared components and capacity limits. No season has an approved GameSpec today |
| B | Combination-level alliance value | **New** | The `alliance_synergy` index and the P6-M10 additive alliance means exist; neither estimates the expected alliance score with interactions. **New:** the alliance score model AS-1 (P11A-B5) |
| B | Objective: P(win) vs expected score | **Extend** | The engine's P(win event) objective exists but is gated. **New:** an objective selector with an honest fallback to expected score (P11A-B6) |
| C | Separate first-pick list | **Extend** | The engine ranks first picks by P(win event), gated. **New:** a first-pick list valued by the two-stage expected alliance value (P11A-C1), served without the PX gates |
| D | Conditional second picks | **New** | The engine's `configuration` implies one second pick per first pick. **New:** a conditional second-pick list for each first-pick scenario, and backup combinations |
| E | Draft-position awareness (captain) | **Extend** | Seed-aware engine and FB1. **New:** availability-weighted values per seed |
| E | Non-captain situations | **New** | Today it is `team_not_selecting`. **New:** destination fit per alliance, and invitation likelihood when F supports it |
| F | Predicted availability | **New** (overlaps Phase 13) | The deterministic draft model only. **New:** availability probabilities from Phase 13's model, or a pre-declared interim estimator (P11A-Q1), kept apart from confirmed availability |
| G | Explanations | **Extend** | FB1 movement templates, and profile factors with n and status. **New:** factor decomposition of each recommendation into fixed-template strengths and weaknesses |
| G | Team profile | **Reuse + Extend** | Reuse `/events/:eventKey/teams/:team` and the strength view. **New:** an "Alliance fit" section (team-private), and component estimates with intervals |
| H | Live integration | **Reuse + Extend** | Reuse the record, replay and `record_seq` staleness. **New:** recalculation of the plan on every recorded action |
| I | Offline readiness | **New** (with Phase 12) | Nothing. **New:** a snapshot-based input interface and a required-inputs manifest |
| J | Hybrid architecture | **Extend** | The components exist in pieces (§3.1). **New:** the AS-1 and optimizer layers |
| K | Pre-registered evaluation | **New** | The backtest harness and its leakage guards exist. **New:** the P11A evaluation record and its runs |
| L | Live performance | **Extend** | P11-Q3 (≤ 2 s at p95, warm). **New:** targets for the plan and the profile |

---

## 5. Product objectives

1. **Team-specific value.** A candidate's value is the gain in *our* alliance's strength, not its individual rank.
2. **Combination-level.** The second pick is judged in the complete alliance. The first pick is judged together
   with the realistic second picks it leaves open.
3. **Grounded in the season's game.** Complementarity and redundancy come from the season's scoring structure and
   measured evidence. There are no generic specialization bonuses.
4. **Honest objectives.** Maximize P(win) only where a validated, calibrated model exists. Otherwise maximize expected
   alliance score, and say so.
5. **Draft-position realism.** Values account for who can realistically still be picked at our turn. Predicted
   availability never changes confirmed availability.
6. **Live and offline.** Every recorded action updates the plan within the P11-Q3 budget. The plan works from a
   local snapshot.
7. **Explainable.** Every recommendation can be decomposed into the calculated factors behind it.

**Non-goals:**
- predicting or prescribing other teams' strategy;
- any match-level simulation beyond what AS-1 needs (that is Phase 14);
- replacing the P6-M7 engine or its gates.

---

## 6. Functional requirements

Each requirement states what is calculated, from what, how it is presented, and its acceptance criterion (§18).

### Capability A — Event-specific robot performance evaluation

**P11A-A1 Season capability catalogue.** For each supported season, a versioned list of the capability dimensions
StratAI evaluates. Each dimension has:
- a definition;
- a source;
- an observation type;
- a unit;
- whether it is per-robot or alliance-level.

**Minimum catalogue for 2024–2026**, from the data that exists:
- auto, teleop and endgame contribution (points);
- total contribution;
- match-to-match variability;
- defense quality (scouting);
- feeding quality (scouting);
- availability or participation (matches played, DQ, surrogate);
- per-robot TBA breakdown facts, where verified (P11A-A2).

**Game-specific dimensions** (for example, a particular game-piece category) are added only from an approved GameSpec
and an approved alliance scoring configuration (P11A-B4).

A season without a catalogue is refused, never approximated (`season_not_supported`).

**P11A-A2 Observation types.** Every value carries exactly one of the following, and the API and UI never present
them as interchangeable:

| Type | Meaning | Examples |
|---|---|---|
| `observed` | A recorded fact about this robot | Matches played; a per-robot TBA breakdown field (UNVERIFIED: 2024–2026 breakdowns are believed to carry per-station robot fields for some components, for example leave/mobility and endgame state; verify against stored raw payloads before use). An `observed` per-robot fact is not, by itself, the robot's point contribution: only fields meeting the E1b individual ground-truth standard (§20) count as numerical ground truth |
| `observed_alliance` | A recorded fact about the robot's alliance, not the robot | Alliance auto, teleop or endgame points; opponent foul points |
| `scouted` | A human observation (shared or team-private), with n and agreement | Defense and feeding quality |
| `estimated` | A statistical estimate with uncertainty | The in-event per-robot component contribution (P11A-A3) |
| `model_prediction` | A trained or registered model's output, with its validation status | The M5 v2 rating, the AS-1 alliance score |
| `inferred` | A derived judgement with limited evidence | "Likely endgame specialist" from n < the minimum |

**P11A-A3 In-event per-robot component estimator (new).** For each team at the event and each scoring component c
of the season (auto, teleop, endgame; game-specific components where configured):
- **Output:** an estimated mean contribution μ̂ and its standard error σ̂. Both are computed at an `as_of`, from
  qualification matches played strictly before it.
- **Required properties:**
  1. **It uses current-event evidence.** Alliance component points per match (`ml/features/score_components.py`)
     are decomposed across the alliance's three robots. A regularized least-squares (component-OPR) approach is the
     reference candidate; the implementer may choose another approach if it is justified.
  2. **It shrinks toward a prior** when evidence is thin, so **one exceptional match cannot set a team's capability**
     (Scenario I). The prior and its strength are fixed in the pre-registration record (§20) before any held-out
     result. They are never tuned on the event being served.

     **Three variances, never conflated.**
     - **τ² (latent between-team variance):** the spread of true per-robot contributions across teams.
     - **σ²_ε (match-level residual noise):** match-to-match variation of an alliance's component points around the
       sum of its robots' true contributions.
     - **V_μ (uncertainty in an estimated population or event mean).**

     **How τ² is estimated.** By a method that removes estimation noise: method of moments, REML, or a fully Bayesian
     hierarchical fit. It is **never** the raw variance of per-robot point estimates, which includes σ²_ε and
     estimation error.

     **The prior hierarchy** (most to least independent; the first available level is used):
     - **(i) Independent individual prior (preferred).** The team's most recent prior-event EPA component
       (`TeamFeatures.epa_*`), converted to this event's point scale with the existing scale machinery
       (`TeamFeatures.epa_scale` / `score_scale`; `ml/features/scale.py`).
       - Its variance τ²_team is the variance of (true in-event contribution − scaled prior-event EPA), estimated on
         the training split by a noise-removing method (above).
       - It uses no match of the event being estimated, so it is statistically independent of that event's
         observations.
     - **(ii) Independent population prior.** Used when (i) is absent, for example at a team's first event.
       - **Mean and τ²:** the mean and latent between-team variance of per-robot contributions for component c, from
         events independent of this one: same-season events concluded before `as_of`, else the training split's
         events.
       - **Scale:** both are converted to this event's point scale with the same scale machinery.
       - **Variance:** its variance includes V_μ from that independent estimate.
       - It uses no match of this event.
     - **(iii) Current-event population prior (last resort).** Used only when neither (i) nor (ii) exists, for example
       the first week of a new season, before any event has concluded.
       - The event's population mean μ_event (and τ², if no independent τ² exists) is estimated **jointly with every
         robot's contribution, in one hierarchical model over the same matches**. Examples: a random-effects model
         fitted by REML or empirical Bayes with the mean's uncertainty integrated, or a fully Bayesian fit.
       - **Plugging in a mean computed from these matches, then treating it as an independent known prior, is
         prohibited.** Doing so counts the same evidence twice: once in the prior, and again in the likelihood.
       - The posterior for each robot therefore carries V_μ and the covariance between its own estimate and
         μ̂_event: the robot's own matches inform μ̂_event.
     - **(iv) No prior.** If none of these exists, the component is `insufficient_data` (see below).

     **Shrinkage strength.**
     - **With an independent prior (i, ii)**, the data weight is the closed form w = τ²/(τ² + SE²_data). Here τ² is the
       prior's variance (including its V_μ), and SE_data is the robot's unshrunk-estimate standard error. This form
       is valid only because the prior is independent of the data.
     - **With a current-event prior (iii)**, there is no closed-form w. The reported weight is the joint model's
       effective data weight, w_eff = 1 − Var_posterior / Var_prior-marginal, computed from that model with the
       dependence included.
     - **Reported with every output:**
       - the prior's kind: `prior_event_individual`, `independent_population` or `current_event_joint`;
       - its mean and SD;
       - w or w_eff;
       - n;
       - for (iii), the matches that informed the prior.

     **Testing and disclosing the dependence (iii).**
     - **Structural test.** On synthetic schedules with known truths, the joint model's posterior SD for every robot
       is at least the SD the prohibited plug-in would report. Its posterior intervals reach the nominal coverage
       within a pre-registered tolerance, while the plug-in is shown to under-cover. The test proves the same
       evidence is not counted twice.
     - **Evaluation.** E1a, and E1b where possible, report interval coverage separately for each prior kind.
     - **Disclosure.**
       - Every output that uses (iii) is labelled `current_event_joint`.
       - Cards (G1) say "prior estimated from this event's own matches".
       - A `current_event_joint` estimate is treated as `prior_dominated` under the same w_min rule, using w_eff.

     **Fallback for insufficient evidence.**
     - **Prior-dominated estimates.**
       - When w (or w_eff) is below the pre-declared minimum w_min, or n is below n_min, the value is labelled
         `prior_dominated` (`prior_dominated_population` for a population prior, (ii) or (iii)).
       - It is shown with its full (wide) interval.
       - It is never used to support a preference or practical-equivalence conclusion (B6), or a strength or
         weakness card statement (G1).
       - Any recommendation whose value depends on one is flagged.
     - **No prior.** When there is no prior and n < n_min, the component is `insufficient_data`. The alliance values
       that need it are withheld for that candidate, with the reason, never computed from zero.

     **Comparisons (§20 E1a, and E1b where per-robot evidence exists).** The prior choices are compared, in the
     pre-registered evaluation, against these baselines:
     - the individual prior-event EPA alone;
     - the independent population prior alone;
     - the current-event joint model;
     - the prohibited plug-in, as a diagnostic comparator only, never served;
     - no shrinkage;
     - the raw alliance average.

     Whichever wins is reported as measured. A loss is never re-tuned.
  3. It reports n (matches used), σ̂, the prior used and its weight.
     - **Joint covariance.** It also outputs the **joint posterior covariance** of all robots' component estimates
       at the event (across robots and across components), not only the marginal σ̂.
     - **Residual covariance.** It outputs the estimated alliance-level residual covariance across components
       (shared match effects; σ²_ε generalized to a matrix).
     - **Use.** Both are inputs to AS-1 (B5) and to the identifiability diagnostics (A3.7).
  4. Where verified per-robot TBA fields exist for a component (for example per-robot endgame state), they enter as
     `observed` per-robot evidence. The estimator must not double-count them against the alliance total.
  5. It accounts for opponent strength only if a pre-registered comparison shows it improves held-out prediction
     (§20). Otherwise the opponent adjustment is omitted, and the omission is stated.
  6. Surrogate appearances and DQ'd matches follow the Phase 4 dataset rules (`ml/dataset/builder.py`: excluded or
     labelled, never silently counted).
  7. **It discloses identifiability.**
     - **Why this is needed.** Alliance-level points identify the *sum* of three robots' contributions. Splitting that
       sum among the robots works only as well as the schedule varies who plays with whom.
     - **What is reported.** For each robot and component, the estimator reports diagnostics computed from the
       design matrix and the estimate's covariance:
       - the number of distinct partners and opponents;
       - the posterior-variance reduction relative to the prior;
       - the largest absolute correlation between this robot's estimate and another robot's;
       - whether the event's design matrix is rank-deficient, or ill-conditioned beyond a pre-declared bound.
     - **When an estimate is weakly identified.** It is labelled `weakly_identified`, with the specific reason:
       - limited observations;
       - repeated partners;
       - a strongly correlated partner estimate;
       - an ill-conditioned schedule;
       - other confounding the diagnostics detect.

       This applies when any diagnostic crosses its pre-declared threshold. The thresholds are fixed in the
       pre-registration (§20) before any result.
     - **How the label is shown.** The label reaches the profile (A7), the cards (G1) and every recommendation that
       depends on the estimate.
- **Validation status.** The estimator is **pre-registered and validated** (§20, E1) before its output is served as
  anything stronger than `not_validated`.
  - **Aggregate validation is not individual validation.** Passing E1a (aggregate alliance predictions) makes the
    *aggregate* predictions `validated`. It does not make the per-robot split validated: individual estimates stay
    labelled `estimated_aggregate_validated`.
  - **What can validate an individual estimate.** Only ground truth meeting the E1b individual ground-truth standard
    (§20) can do that, and only for the (sub-)components that ground truth exactly determines. That means either
    direct per-robot points in compatible units, or a pre-registered, validated conversion under the approved
    GameSpec.
  - **What cannot.** Categorical, partial or ambiguous per-robot observations do not qualify.
  - **Where no qualifying ground truth exists,** individual estimates keep the `estimated_aggregate_validated` or
    `not_validated` status and are never described as independently validated.

**P11A-A4 Same-event EPA is not used** unless decision P11A-Q5 allows it.
- `TeamFeatures` deliberately never offers same-event EPA (`_point_in_time_epa`).
- The live snapshot log's `retrieved_at` would make a current-event Statbotics value point-in-time-safe *for
  serving*.
- But no such snapshots exist for the 2024–2026 events, so it **cannot be backtested** (§20).
- **Proposed default (P11A-Q5).** It may be explored experimentally only:
  - with explicit labelling and its `retrieved_at` point-in-time provenance;
  - never as the basis of a historical validation claim, unless it can be reconstructed without temporal leakage.

**P11A-A5 Reliability and penalties.**
- **Reliability:** shown only as what is measured: matches played and scheduled, DQ, surrogate, and coach
  `robot_unavailable` / `component_unavailable` observations. The INTERIM `reliability_score` is never labelled a
  failure rate.
- **Penalties:** foul points are alliance-level (`observed_alliance`). A per-robot penalty tendency is reported only
  if a validated attribution exists; otherwise it is `insufficient_data`, with the reason.

**P11A-A6 Continuous updates.** After every sync that loads new qualification results (`data.orchestrator.
after_watch_sync`), the estimator recomputes for the event. Its results are cached under a **data snapshot id**: a
hash of the inputs' raw-payload ids and fetch times. Recomputation is incremental where exact; least squares on the
event's matches is cheap. No model is retrained during an event.

**P11A-A7 Profile output (per team).** Every value has its type (A2), n, uncertainty and source, plus a
`last_updated` and the snapshot id. The profile contains:
- overall estimate;
- per-component μ̂ ± σ̂, each with:
  - the prior's kind and its weight;
  - any `prior_dominated` / `insufficient_data` label (A3.2);
  - the identifiability diagnostics and any `weakly_identified` label (A3.7);
  - the validation scope: aggregate only, or individually validated for that component (A3, E1b);
- consistency (SD of alliance totals, and residual SD from A3);
- defense and feeding (scouted, with n and agreement);
- participation;
- per-robot observed facts.

### Capability B — Team-specific alliance synergy and optimization

**P11A-B1 Our robot.** Our robot's capability is estimated exactly as every other robot's (A3), so it is never
optimistic about itself. The team may add **self-reported** capability entries; whether this is allowed is decision
P11A-Q6. If allowed, they are:
- stored raw-first and attributed;
- labelled `self_reported`;
- shown beside the estimate;
- never used in a served objective unless P11A-Q6 allows it.

**Proposed default (P11A-Q6):** self-reports are displayed separately from measured estimates, and are not included in
the optimization objective initially.

**P11A-B2 Capability matching.** For our robot and each candidate, report:
- per component, our estimate, the candidate's, and the alliance gap (where our robot is below the event's
  playoff-peer median);
- overlap: both robots draw on the same alliance-capped component (B4);
- the *marginal* gain in the expected alliance score from adding the candidate (B5).

There is never a "complementary" label without a computed marginal gain behind it.

**P11A-B3 Pairs and triples.** Compute:
1. the two-robot partial alliance, our robot plus a candidate first pick, as the input to C;
2. the complete alliance's **active lineup**: our robot, the first pick and the second pick.

**Terminology** (used throughout this document):

| Term | Meaning | In the expected score? |
|---|---|---|
| **Active robots** | The three robots that play a given match. An FRC alliance always fields exactly three | Yes. This is the only thing V scores |
| **Fourth alliance member** | At events whose rules give 3 picks (for example FIRST Championship divisions), the fourth team selected onto the alliance. It plays only when substituted into a three-robot lineup | **No.** It is never a fourth simultaneous scorer |
| **Backup robot** | A robot from the event's backup pool, available to replace an alliance robot under the event's backup rules (`SelectionRules.backup_robots`). It is not a selected alliance member | **No** |

**Rules:**
- **The value is for three robots.** V is always the value of a **three-robot active lineup**.
  - With three alliance members, the lineup is fixed.
  - With a fourth member, V is the value of the best three-robot lineup that can be drawn from the members. This is
    a choice among lineups, never a sum over four robots.
  - The reported value always names the lineup it scores.
- **Replacement and resilience analysis is separate.** It is reported beside V, never inside it, and covers:
  - the value of each lineup with one robot unavailable;
  - the value with the fourth member (or a backup robot) substituted in.

  It is labelled `resilience_analysis`, and it is never added to V, the expected score or the objective.
  - **Proposed default (P11A-Q3):** resilience stays a separate analysis initially.
  - Including it in the objective needs its own dated decision and validation.
- **A test enforces this** (§18 criterion 18): no expected score includes a fourth member or a backup robot as a
  simultaneous contributor.

**P11A-B4 Season alliance scoring configuration (new, versioned, reviewed).** One per supported season. It is
human-entered from the game manual, with citations, and follows the P6-M1 ruleset workflow: draft → submit → a named
qualified reviewer approves; every version is kept; it is read only through an approved-version accessor. It
declares:
- the season's components, mapped to the P5-M7 adapters (alliance points per component);
- for each component, whether alliance points are the **sum of independent per-robot contributions** or **subject
  to an alliance-level cap or shared resource**. Examples: a limited number of scoring locations, game pieces or
  endgame positions. Each declared cap has its manual citation;
- per-robot caps: the maximum points one robot can earn in a component;
- constraints that make two robots unable to reach their independent maxima at once.

**Rules:**
- No interaction is declared without either a manual citation (a hard rule) or an empirical estimate that passed
  validation (§20, E2).
- A season without an approved configuration is refused (`scoring_config_not_approved`). This is the season-change
  mechanism, so new seasons need no engine rewrite.
- The configuration's sha256 is recorded in every output's provenance.
- **2024–2026 configurations must be entered and approved before any P11A output is served for those seasons.** The
  2027 configuration is entered from the 2027 manual.
- **Proposed default (P11A-Q4):** extend the existing GameSpec (`data/game_spec.py`), if that is technically
  appropriate, rather than creating a second artifact. There is one source of truth for a season's scoring rules.
  If a separate artifact is unavoidable, it references the approved GameSpec by sha256 and never restates its point
  values.

**P11A-B5 Alliance score model AS-1 (new).**
- **Inputs:**
  - the robots' per-component estimates, with their **joint posterior covariance** (A3.3);
  - the alliance-level residual covariance (A3.3);
  - the season configuration (B4).
- **Outputs:** the alliance's expected score per component and in total, with a joint predictive distribution (mean,
  SD, 80% interval, and the component covariance).
- **Required:**
  1. **No double counting.** For an independent component, the expectation is the sum of the robots' expectations.
     For a capped or shared component, the configuration's rule applies; for example, the expectation of
     min(cap, Σ contributions), computed under the predictive distribution, not on the means.
  2. **Joint uncertainty propagation.** The predictive distribution of the three-robot active lineup's component
     points is built from three sources:
     - **(a) Estimation uncertainty.** The 3-robot × C-component block of the joint posterior covariance (A3.3),
       *including* the cross-robot terms (negative or positive correlation between robots who often played
       together) and the cross-component terms.
     - **(b) Shared match effects and residual noise.** The alliance-level residual covariance across components
       (A3.3).
       - Per-robot match-to-match variance cannot be separated from alliance-level residuals using alliance-level
         data. So it is modelled at the alliance level, except where per-robot evidence (E1b-grade) identifies it.
       - This limitation is disclosed in the provenance.
     - **(c) The season's scoring rules** (B4), applied to sampled per-robot contributions, not to their means.

     **How the rules are applied.**
     - **Linear, uncapped components:** the exact sum of the covariance terms is acceptable.
     - **Nonlinear components** (caps, shared resources, minimum or maximum constraints): the distribution is
       propagated by seeded Monte Carlo over the joint distribution (a)+(b), with the run count and Monte Carlo error
       recorded. Analytic approximations (for example the delta method on a cap) are allowed only if a pre-registered
       check shows they match the Monte Carlo reference within a pre-declared tolerance.
  3. **No independence by default.**
     - Robot estimates are **not** assumed independent, and the cross-robot covariance terms are **not** dropped,
       unless a pre-registered test shows the simplification changes predictive coverage (E1a, E2) and comparison
       outcomes (B6) by less than a pre-declared tolerance.
     - That test's result is recorded, and the simplification is disclosed in provenance.
  4. **Comparisons use the joint distribution.**
     - Candidate alliances are compared (B6) through the joint predictive distribution of their **difference**.
     - Alliances that share members (always our robot, often a first pick) are sampled with common random numbers
       and the shared members' covariance, so the shared parts cancel correctly.
     - Comparing two marginal intervals is not allowed.
  5. **Empirical interaction terms**, such as saturation beyond the configuration, are allowed only as
     pre-registered terms that improve held-out prediction of actual playoff-alliance scores (§20, E2). Otherwise
     there are none.
  6. **Defense and feeding effects are zero, labelled `defense_effect_insufficient_data`**, until a measured effect
     exists. This is the P6-M10 rule, and P11A-Q8 records the defense definition in force. Scouted defense quality is
     *reported*, never converted to points.
     - **Proposed default (P11A-Q8):** defense stays a separately reported capability until its effect on scoring
       and on match outcomes is validated.
  7. **Deterministic** given the inputs. Any Monte Carlo is seeded and records its run count and Monte Carlo error.
- **Validation:** AS-1 is validated on **actual formed playoff alliances** (§20, E2). This is the one place where
  whole-alliance outcomes are observable.

**P11A-B6 Objective selection.**

**Two different quantities.** They are distinct throughout this document, the API and the UI:

| Quantity | What it measures | Unit |
|---|---|---|
| **Expected alliance score** | The predicted scoring strength of our three-robot active lineup (AS-1). It says nothing by itself about beating anyone | Points |
| **Probability of winning** | The likelihood that our alliance beats a *specific* opponent, or wins the event. It needs both an opponent-strength model and calibration | Probability |

**Rules for the distinction:**
- **Expected score is never a probability.** It is never described, labelled, scaled or displayed as a win
  probability or as a percentage chance, and never converted into one.
- **Separate fields.** Responses carry them in separately named fields, and the score always shows its unit (points).

**The objective** is chosen by a fixed rule, and recorded in each response's `objective` field:
1. **`p_win_event`:** the existing P6-M7 engine's objective. It is used only when that engine serves, meaning its own
   predefined gates (PX-1, PX-2, PX-4) have all passed. Unchanged.
2. **`p_win_playoff_match`:** available only after **both** of these pass their predefined, pre-registered criteria
   (§20, E3) on playoff matches:
   - an opponent-strength model: who we would face, from the predicted field (F) in the bracket simulator or a
     representative-opponent rule fixed in advance;
   - probability calibration of P(win) over AS-1 alliance distributions.
3. **`expected_alliance_score`:** the AS-1 expected total, in points. **This is the initial objective.**

**What is shown when P(win) is unvalidated:**
- Unvalidated win probabilities are **not displayed as meaningful predictions**.
- **Proposed default (P11A-Q3):** they are kept out of user-facing recommendations entirely. The response states
  `win_probability: not_available` with the reason.
- They are never fabricated, never presented as calibrated, and never inferred from expected score.

**Comparing candidates under uncertainty.** Two candidates are never called equivalent just because their predicted
means are close.

**The compared quantity.** For two candidate alliances A and B (for example adjacent entries in a list), let Δ be the
difference in their **expected** alliance values, V(A) − V(B).
- Its distribution is the joint distribution induced by estimation uncertainty (B5.2 (a), with shared members'
  covariance, B5.4).
- It is not the spread of a single match's outcome.
- Single-match outcome spread (B5.2 (b)) is reported separately, and never decides a comparison.

**Two pre-registered parameters** fix the rule:
- **δ:** a practical-equivalence margin, in points;
- **π:** a decision probability threshold.

**Each compared pair gets exactly one outcome:**

| Outcome | Condition |
|---|---|
| `A_preferred` | P(Δ > δ) ≥ π |
| `B_preferred` | P(Δ < −δ) ≥ π |
| `practically_equivalent` | P(−δ < Δ < δ) ≥ π |
| `unresolved` | None of the above: the evidence does not support a preference or an equivalence |

**What every comparison reports:** P(Δ > 0), P(|Δ| < δ), the 80% interval of Δ, and the outcome.

**Rules:**
- **Closeness is not equivalence.** Close means with wide uncertainty give `unresolved`, never
  `practically_equivalent`.
- **Ordering vs conclusions.** A list is still ordered by expected value. Only the outcome labels carry conclusions.
- **No numbers are chosen here.** δ and π are not chosen by this document.
  - They require benchmark evidence: for example, the size of score differences that change playoff outcomes, and
    the AS-1 error magnitudes from E2.
  - They require approval, under P11A-Q3, and are recorded in the pre-registration.
  - **Until they are approved,** no comparison emits `A_preferred`, `B_preferred` or `practically_equivalent`.
    Every comparison reports its probabilities and Δ interval with the outcome `unresolved` and the reason
    `comparison_threshold_not_approved`.
- No weights or bonuses outside the declared objective are allowed. Any proposed term needs a dated decision and a
  validation.

**P11A-B7 Explanations** are derived from the calculation (see G1).

### Capability C — First-pick optimization

**P11A-C1 First-pick value.** For each candidate c available to our alliance, the value is:

> **V₁(c) = E_availability [ max over d available at our second turn of V(us, c, d) ]**

- V is the selected objective (B6) for the complete alliance's three-robot active lineup (B3).
  - Under the initial objective, V is an **expected alliance score in points**, never a probability.
- The expectation is over availability scenarios between our first and second turns (F). It is taken **only once the
  availability model has passed its independent validation** (E4).
- Until then, V₁ is computed under the stated assumption "every team not confirmed unavailable is available",
  labelled `availability_not_modelled`.
  - Predicted availability may be *displayed* beside the value, labelled with its status, but it does not enter V₁.
  - **Proposed default (P11A-Q1):** no probabilistic availability enters recommendation decisions until it is
    validated.
  - The P6-M6 deterministic projection is also reported, labelled with its measured top-1 0.211.

**P11A-C2 Output:** a ranked first-pick list. Each entry gives:
- V₁(c) with its interval, and its unit;
- the expected alliance score (points);
- a win probability **only** when B6's `p_win_*` objective has passed its validation; otherwise none;
- the best conditional second pick (D) and its runner-up;
- P(c available at our first turn) (F);
- the advantages and weaknesses (G1);
- n and data-quality flags.

The list is specific to our seed and the real draft state.

### Capability D — Second-pick optimization

**P11A-D1 Conditional second picks.** For each first-pick scenario (the top K first picks, with K fixed in the
configuration, at least 5), rank every candidate d by V(us, c, d), together with its availability at our second turn.
- After our real first pick is recorded, the conditional list for that pick becomes *the* second-pick list.
- The highest individually ranked robot is not assumed to be best; d is ranked by its marginal value to {us, c}.

**P11A-D2 Backup combinations.** List at least the top 5 complete alliances {us, c, d} by V, each with its joint
availability probability. Combinations that depend on an unlikely availability are flagged. The list is not padded:
fewer than 3 is stated with the reason.

**P11A-D3 Scenario statements**, as fixed templates over the computed results: "If A is your first pick, C is the
best second pick (V …)" and "If A is taken before your turn, B is the strongest first pick, and the second-pick list
changes to …".

### Capability E — Captain and draft-position awareness

**P11A-E1 Our selecting position** comes from the record (`selecting_seed` in `workspaces/draft_recommendations.py`):
- the alliance we are on;
- or the alliance we are projected to captain under the rules and ranks.

**The turn sequence** comes from `turn_order` and the event's rules: picks per alliance, variants, declines, and
`captain_may_accept_higher_alliance`.

**P11A-E2 Captain-specific plans.**
- C and D use our real seed's turns. Seed 1 and seed 8 plans differ because their availability horizons differ.
- The number of picks before each of our turns is shown.

**P11A-E3 Non-captain teams.** If we are neither on nor projected to captain an alliance:
- **Destinations:** for each alliance that will pick, the value V of that alliance *with our robot added*. This is
  deterministic and needs only AS-1.
- **Invitation likelihood:** shown only when F supplies per-turn pick probabilities **that have passed validation**
  (E4). Otherwise it is withheld with `pick_model_unavailable`.
- **What is available if invited:** for each likely destination, the pool that would remain.
- The team's potential partners are **never** presented as the team's choice.

**Two special cases:**
- **A projected captain** keeps the captain view, but shows the probability that a higher seed invites it, when F
  supports that.
- **Under a declined-captain rule** that is `null` (not established), the view says the outcome is not determined.

**P11A-E4 Availability enters the values** (C1). A candidate's value-if-available and its P(available) are always
both shown, never only their product.

### Capability F — Predicted availability

**P11A-F1 Source.** There is one pick-probability model, and P11A does not build a second one.
- When the proposed **Phase 13** model exists and is served, P11A uses it.
- Until then, P11A uses an interim, pre-declared estimator, chosen by decision P11A-Q1. Candidates:
  - (a) none: availability is withheld and C1 uses `availability_not_modelled`;
  - (b) a conditional-logit choice model on point-in-time features, built *as* Phase 13's model (bringing Phase 13
    forward);
  - (c) a fixed, documented rule, for example "the top k of the P5-M4 ordering among the available are taken in
    order", served `not_validated`, with its measured accuracy.
- **Any probabilistic model of other captains' picks must not enter the P6-M7 engine** without decision P13-Q1, which
  supersedes P6-Q6.
- **Proposed default (P11A-Q1).** Probabilistic availability enters no recommendation decision (C1, E3) until the
  availability model has been independently validated (E4).
  - Until then, it may be displayed only as labelled, `not_validated` information.
  - **Predicted availability never alters actual availability** (F2), whatever its validation status.

**P11A-F2 State separation (mandatory).** The API and UI keep these states apart:

| State | Source | Effect |
|---|---|---|
| `confirmed_unavailable` | The draft record and the rules (`availability()`) | Removed from every list |
| `confirmed_available` | The draft record and the rules | Eligible |
| `predicted_taken_before_turn` | F, with a probability | Shown as a probability. **Never removed** from the pool |
| `uncertain` | F withheld, or the model is outside its domain | Shown as uncertain |

**Predictions never change `availability()`**, and a structural test enforces this (§19).

**P11A-F3 Scenarios.**
- **When probabilities exist:** values are expectations over S sampled draft continuations. S and the seed are fixed
  in the configuration, and the Monte Carlo error is reported. Each sampled continuation respects the rules and the
  record.
- **When no probabilities exist:** no single speculative continuation is ever treated as fact.

**P11A-F4 Updates.** On every recorded action, availability is recomputed from the new state, and the change is
explained ("Team T: available at your turn 62% → 31%").

### Capability G — Explanations and team profiles

**P11A-G1 Recommendation cards.** Each card is derived from the calculation. It shows:
- team number and name;
- position;
- V with its interval, the objective used, and its unit;
- the expected alliance score (points), never phrased as a chance of winning;
- a win probability only when validated per B6. Otherwise no probability is shown;
- availability per F2;
- n and data-quality flags;
- validation status.

**Card statements.** Each advantage and weakness is a fixed template filled from a computed factor:
- the largest positive marginal component gains (for example "adds +14.2 ± 5.1 expected teleop points our alliance
  lacks");
- the largest overlaps under a cap (for example "overlaps on the endgame cap: +0.8 of a possible 6.0");
- the highest uncertainty ("6 matches; teleop SE 4.9");
- missing data ("no scouting observations");
- weak identifiability or a prior-dominated estimate, with its reason (A3.2, A3.7), for example "teleop estimate
  weakly identified: played with team 1234 in 5 of 6 matches".

**Card rules:**
- A statement appears only when its factor passes a pre-declared threshold (P11A-Q3). There is no generic text.
- An LLM may rephrase only through the Phase 9 briefing layer, downstream, and every number stays verbatim.

**P11A-G2 Team profile.** Reuse `/events/:eventKey/teams/:team` and the strength view. Add:
- the A7 component estimates with intervals and observation types;
- per-match component points of the team's alliance (`observed_alliance`, labelled), with **alliance-level
  anomalies**: matches whose alliance residual (observed alliance points minus the AS-1/A3 prediction for that
  alliance) exceeds a pre-declared bound.
  - **What an anomaly means.** It identifies an unusual *alliance match outcome* and nothing more. It is shown as
    "alliance scored unusually low/high in match M", on the match and the alliance.
  - **What it does not mean.** It never establishes that this robot, or any particular robot, was an outlier or
    caused the result.
  - **Robot-level outliers.** One is reported for a robot only when independent, direct supporting evidence about
    that robot in that match exists:
    - a per-robot observation meeting the E1b ground-truth standard (§20);
    - a coach observation recorded for that robot and match (`robot_unavailable`, `component_unavailable`);
    - a scouting observation of that robot in that match, for the component concerned.

    It is labelled with that evidence. Without such evidence, the anomaly is reported at the alliance/match level
    only, and never moves into the robot's strengths, weaknesses or card statements;
- a team-private **"Alliance fit"** section: fit with our robot, with the proposed first pick and with the proposed
  second pick; complementary and overlapping components; the expected combined score;
- provenance: sources, snapshot id, model and configuration versions, the missing-data list.

Every recommended team links to *its own* profile, at the same event, with the current draft context (Scenario K).

**P11A-G3 Usability.** The primary screen shows the top recommendations and their one-line reasons. Details are one
tap away.

### Capability H — Live integration with the Phase 11 draft record

**P11A-H1** The plan (C, D, E, F) is computed from `DraftView` only. No separate state is ever typed in.

**P11A-H2 Before selection.** As soon as the record exists, or earlier from the event's data with no record, the plan
is computed for the team's projected position. It is labelled pre-selection and uses the latest snapshot.
- **Proposed default (P11A-Q7):** a pre-selection planning view is supported **without** creating a draft record.
- It reads the event's data and the team's projected position.
- It stores nothing in the draft log, and it never stands in for the record once one exists.

**P11A-H3 Unexpected outcomes:**
- **A team predicted to be taken, but still available** (Scenario F), is evaluated as available on the next
  recalculation.
- **A recommended team that gets taken** (Scenario G) is removed from every list. The plan is recomputed from
  scratch, not by deleting a row from the old ranking.

**P11A-H4 Every response carries:**
- `record_seq`;
- the data snapshot id;
- the AS-1, estimator, availability and optimizer versions;
- the scoring configuration sha256;
- the ruleset sha256;
- the objective;
- the timestamp;
- the validation status;
- `current` or `stale`.

**Failures:**
- A failed recalculation keeps the last valid plan visible, marked **stale**, with the reason, as the Phase 11 page
  already does.
- A plan computed for an older `record_seq` is never shown as current.

**P11A-H5** The Phase 11 log, its corrections and its flags are unchanged. While any action is flagged, the plan is
withheld (`record_needs_review`), exactly as Phase 11's recommendations are.

### Capability I — Offline readiness

See §14.

### Capability J — Hybrid architecture

See §7.

### Capability K — Quality, uncertainty and evaluation

See §20.

### Capability L — Performance and usability

See §11 and §16.

---

## 7. Technical requirements and architecture

**The six components**, each mapped to the repository:

| # | Component | Builds on | New work |
|---|---|---|---|
| 1 | Robot performance estimation | `TeamFeatures`, `ml/features/score_components.py`, `ml/ratings/`, `ml/views/strength.py` | The A3 estimator, as a pure function of (event match rows ≤ as_of, priors, configuration); a module beside `ml/features/` |
| 2 | Alliance compatibility | GameSpec, the P5-M7 adapters | The B4 configuration (storage and review like `data/rulesets.py`), and AS-1 as a pure function |
| 3 | Optimization | `SelectionEngine` and `turn_order` (unchanged) | A two-stage optimizer over the available pool (C1, D1). Exhaustive at event sizes (§16); no new solver dependency unless §16's limits demand one |
| 4 | Draft position and availability | `DraftView`, `selecting_seed`, Phase 13's model | The F interim estimator (per P11A-Q1) and the scenario sampler |
| 5 | Recommendation generation | `workspaces/draft_recommendations.py` (source precedence) | The "P11A plan", served through its own additive operations (§12). Proposed default (P11A-Q2): the existing precedence and endpoint contracts stay unchanged until a separately approved transition |
| 6 | Explanation and presentation | FB1 movement templates; the dashboard team page | G1 templates, the G2 section, the page panels |

**Rules:**
- **Pure functions.** Components 1–4 are pure functions of an `EventSnapshot` (§14) plus the `DraftView`.
- **Database access** goes through one snapshot builder (a `consistent_reads` read, as `analyze_event` uses), so
  offline mode only swaps the snapshot's source.
- **Versioning.** Each component has a `*_VERSION` constant, and its configuration is hashed. Trained artifacts
  (estimator hyperparameters, any interaction terms, the F model) go into `ml/registry.py` (write-once, sha256-pinned)
  and are loaded at startup, as `api/ml_loading.py` does. Nothing is ever loaded in the request path.
- **Caching.** Component 1 is cached per (event, snapshot id). Components 2–5 are recomputed per `record_seq` and
  cached per (record, `record_seq`, snapshot id, versions). Team-private inputs (§13) put the workspace id in the key.
- **No LLM** anywhere in components 1–5 (enforced by `scripts/phase9_zero_llm_audit.py`).
- **Dependencies.** None are added unless a component's validated design needs one, and the reason is recorded.
  numpy, scipy and scikit-learn are present. OR-Tools is in `CLAUDE.md`'s stack but **not** in `requirements.txt`;
  it is added only if §16 shows exhaustive search is insufficient.

---

## 8. Data and methodology requirements

- **Sources.** Reuse the existing ingestion: TBA matches, breakdowns, rankings and alliances; Statbotics/STRATAI EPA
  (D18/P5-D3); shared and team-private scouting; coach observations; rulesets; GameSpec.
  - Raw-first, as always.
  - Manual inputs (scouting, self-reports, configurations) keep their author and time, and are labelled manual.
- **Provenance.** Every value traces to: event, season, team, data snapshot id (raw payload ids and fetch times),
  scouting row ids, model, estimator, AS-1 and optimizer versions, configuration and ruleset sha256, and
  `record_seq`.
- **Missing data.**
  - It is never zero, unless the metric's definition makes zero a real value; for example, endgame points scored is
    0 when observed.
  - It is never imputed silently.
  - The A3 prior is the only allowed fallback, and it is labelled with its weight.
  - Missing data widens σ̂, and is listed.
- **Data quality.** Each team is flagged for:
  - stale data: the snapshot is older than the last played match;
  - inconsistency: a breakdown parity failure (the adapters raise; the match is excluded and listed);
  - surrogate or DQ matches;
  - conflicting scouts (low agreement).

  Flags are shown as data-quality problems, distinct from poor performance.
- **Temporal integrity.**
  - Every input is restricted to before `as_of`.
  - Historical runs use the event's selection moment (`event_selection_moment`).
  - A sentinel test inserts a later match and shows the output is unchanged (as Phase 4 M1 does).
  - Labels (playoff results, actual picks) are never inputs.

---

## 9. Model and optimization requirements

1. **Pre-registration first.** The A3 estimator, AS-1, any P(win) model (B6.2) and the F model are each fixed in a
   dated, write-once evaluation record **before** their held-out evaluation (§20): population, split, metrics,
   baselines, pass criteria. A failed gate is recorded as failed and not re-run to pass (D9).
2. **Model preference.** The candidates are named in §6. The simplest model that passes is preferred (`CLAUDE.md`:
   explainable). ML is used only where the evaluation shows it beats the statistical baseline.
3. **Uncertainty everywhere.** σ̂ from A3; predictive intervals from AS-1; Monte Carlo error from F's scenarios; the
   comparison outcomes from B6 (including `unresolved`). Intervals are checked for coverage in E1 and E2.
4. **Optimizer correctness.** On small events, the optimizer's choices equal brute force over all feasible (c, d)
   with exact scenario enumeration, bit-identical, as the P6-M11 test does.
5. **Determinism.** Identical inputs and versions give identical outputs. All sampling is seeded from (record id,
   `record_seq`, snapshot id).
6. **Status labelling.** A component that has not passed its gate is served `not_validated`. A recommendation's
   status is the weakest status of its inputs; it is never raised.
   - The **scope** of a validation is part of its status. An aggregate (alliance-level) validation never upgrades a
     per-robot estimate (A3, E1).
   - An expected-score validation never upgrades a win probability (B6).
7. **The P6-M7 engine stays unchanged.** P11A neither feeds it nor relaxes its gates.

---

## 10. Draft-position and availability requirements

- **Confirmed availability** is only `DraftView.availability()`. Predicted states never alter it (F2).
- **Turn horizon.** For our next turn index t, every pick in (current, t) is another alliance's. Availability at t is
  computed for every candidate. Declines (they do not consume a turn) are modelled only if the F model covers them;
  otherwise they are stated as not modelled.
- **Seed-specific output.**
  - Every plan names our seed, our turn indices and the picks before each.
  - Every captain position is supported.
  - At events whose rules give 3 picks (FIRST Championship divisions), our third pick selects the **fourth alliance
    member** (B3).
    - Its value is the change in the best three-robot active lineup available to the alliance. That is non-zero only
      if the new member would play in that lineup.
    - Its replacement value is reported separately as `resilience_analysis`.
    - It is never valued as a fourth simultaneous scorer.
- **Non-captains** follow E3.
- **Re-planning.** Every recorded action recomputes the plan and the availability (H).

---

## 11. Frontend and user experience

**Page.** Extend `/alliance-selection/live`. Do not add a new page.

**Main panel, in priority order:**
1. **First picks:** the top 5 cards (G1), with "show all".
2. **Second picks:** the conditional list for the selected or recorded first pick, with a first-pick selector.
3. **Backup combinations** (D2).
4. **The current draft state:** the existing board, compact.
5. **Reasons:** each card's one-line statements.
6. **Profile access:** a tap on a team opens G2.

**Rules:**
- **Labels.** Each card shows:
  - the objective used and the validation status;
  - availability per F2, with predicted states visually distinct from confirmed ones;
  - `weakly_identified` and `prior_dominated` markers (A3).
- **Expected score vs win probability.**
  - Expected alliance score is shown in points, with words such as "expected alliance score", never as a percentage
    or "chance".
  - No win probability is shown unless B6's `p_win_*` objective has passed its validation.
- **Resilience** (B3) is a separate panel or row, never part of the headline value.
- **Staleness:** a plan for an older `record_seq` gets the existing "Stale" treatment, and a stale plan's cards are
  never highlighted.
- **Tablet:** usable at tablet width, with large targets (the Phase 11 tiles). Charts follow P8-Q3 (inline SVG, data
  table, missing points listed).
- **Tests:** Vitest for every panel state (current, withheld, stale, non-captain), and axe with no violations.

---

## 12. API and backend integration

**New operations are additive and workspace-scoped**, under `/workspace/alliance-selection/drafts/{record_id}/`. The
names below are proposals; the implementer confirms them:
- `GET …/plan`: C, D, E and F, with the provenance in H4;
- `GET …/teams/{team_number}/fit`: the team-private part of G2.

A pre-selection plan without a record is decision P11A-Q7. Proposed default: it is supported, through an event-scoped
workspace operation that reads the team's projected position and creates no draft record (H2).

**Unchanged:**
- The locked `GET …/recommendations` stays as it is.
- Its source precedence changes only per P11A-Q2, through a relock with that decision.
- **Proposed default (P11A-Q2):** the existing endpoint contracts and the P11-Q1 source precedence are preserved until
  a separately approved transition is defined. Until then, the plan is reachable only through its own operations.

**Every new operation:**
- is locked with `scripts/phase7_contract_lock lock`;
- is classified in `scripts/phase9_zero_llm_audit.py` (`plan` and `fit` are outputs);
- is pinned in `tests/test_api_foundation.py`;
- is added to `frontend/src/auth/api.ts` (checked against OpenAPI by `tests/test_frontend_workspace_contract.py`);
- is listed as not-called in `frontend/src/api/dashboard.ts`;
- is excluded from the P7-Q4 examples (`TEAM_PRIVATE_PREFIX`).

**Shared, non-private parts** (per-team estimates, A7) may extend the strength view only as an additive operation,
or as an additive relock with a dated decision.

**The season configuration** (B4) gets platform write routes like the rulesets (`platform_gate`), and a review page
like `/rulesets`.

---

## 13. Security and permissions

- **Permissions:**
  - The plan and fit operations require `alliance_selection` (P11-Q4).
  - Writing B4 configurations is a platform write, never a team role.
  - Self-reported capability (if P11A-Q6 allows it) requires `alliance_selection_record`, or a new configurable
    permission added to the permission model.
- **Team-private inputs:**
  - The workspace's own `workspace_scouting_reports` and self-reports may feed **only that workspace's** plan.
  - They never feed shared estimates, other workspaces, shared caches or public routes.
  - Their use is labelled in provenance.
- **Server-side enforcement:** the workspace always comes from the session. Every route is tested directly as admin,
  strategy, scouter and another team.
- **Audit:** recording, configuration changes and self-reports go to `activity_logs`.

---

## 14. Offline compatibility

**The `EventSnapshot` interface.** Components 1–5 read only an `EventSnapshot`:
- the event's matches and breakdowns up to `as_of`;
- rosters;
- ranks;
- EPA priors;
- scouting rows;
- the rules;
- the B4 configuration;
- the GameSpec;
- model artifacts by sha256;
- the component versions.

**Snapshot id:** the sha256 of a canonical manifest of those inputs.
- **Online:** the snapshot is built from the database.
- **In local mode (Phase 12):** it comes from the event package.

**Required-inputs manifest.** It lists every artifact the plan needs. The Phase 12 package builder must include it.
Missing items are reported by name (`snapshot_incomplete: …`), never fetched.

**In local mode:**
- no network calls;
- no remote inference;
- manual actions update the plan immediately from the local draft log, which stays authoritative.

**Verification:** Scenario J, a plan run with networking disabled from a packaged snapshot, gives outputs identical
to the online run on the same snapshot.

The Go Local runtime and synchronization themselves are Phase 12's, not this addendum's.

---

## 15. Dependencies

**Hard:**
1. **Phase 11 verified:** its DB-backed tests and its real-data replay run on an isolated copy.
2. **Approved B4 configurations** for every season served. That needs approved GameSpecs, or a decision that B4
   stands alone (P11A-Q4).
3. **The A3 and AS-1 evaluations recorded** (§20) before any output is served stronger than `not_validated`.

**Soft:**
- **Phase 13:** pick probabilities (F); an interim estimator per P11A-Q1 until then.
- **Phase 12:** local mode (§14).
- **Phase 16:** strengths/weaknesses wording may reuse G1 factors. Shared derivations need P16-Q1.
- **Phase 14:** AS-1 is not a match simulator. Phase 14 must be consistent with AS-1 under "as usual" decisions, or
  report the difference.

**Decisions:** P11A-Q1 … Q10 (§21).

---

## 16. Performance requirements

**Proposed targets** (to confirm per P11A-Q9), on the reference deployment, for an event of up to 80 teams (FIRST
Championship divisions are about 75).
- **Proposed default (P11A-Q9):** keep these targets, labelled **targets pending benchmarks on the actual reference
  hardware**.
- They are not requirements until those benchmarks are recorded.

| Operation | Target |
|---|---|
| Per-event estimator (A3), cold | ≤ 30 s |
| Per-event estimator, after a new match | ≤ 5 s |
| Plan after a recorded action (warm; P11-Q3) | ≤ 2 s at p95 |
| Plan, cold (first after a new snapshot) | ≤ 30 s, paid before selection (H2) |
| Team profile (warm) | ≤ 1 s |
| Offline plan on the reference laptop | the same targets |

**Search size.**
- AS-1 is analytic per alliance, so exhaustive evaluation fits these targets: at most 80 first picks × 79 second
  picks ≈ 6,300 alliances per scenario.
- With S scenarios, cost is S × 6,300 analytic evaluations. Numpy vectorization is required.
- If S × the pool exceeds budget, use pruning: an upper bound on V from each candidate's best case.
- An approximation's agreement with exhaustive search is measured on the §20 sample (top-1 agreement and value
  regret) and reported.

**Timings** are recorded in every response (`timing_ms`), as Phase 11 does.

---

## 17. Definition of success

- **P11A-DM1 (replayed real event).** On a pre-chosen sample of replayed past events, at the selection moment, using
  only pre-selection data:
  - the plan gives seed-specific first picks, conditional second picks and combinations;
  - after every recorded action, no confirmed-unavailable team appears anywhere;
  - predicted states never alter confirmed availability.
- **P11A-DM2 (measured value).** The pre-registered evaluations (§20 E1–E4) run once.
  - The results are recorded as measured.
  - Each component is served with the status, and the validation scope (aggregate or individual), that its result
    supports.
  - The optimizer's comparison with the baselines (E5) is reported as **descriptive and observational**, including if
    it adds nothing. It is never presented as evidence that the optimizer selects superior alliances or causes better
    outcomes (§20).
- **P11A-DM3 (honesty).**
  - No P(win) is shown as calibrated without a passed gate.
  - Expected alliance score is never presented as a win probability.
  - No individual robot estimate is described as independently validated on the strength of aggregate evidence
    alone. Weak identifiability is disclosed (A3.7).
  - No prediction is shown as confirmed.
  - Every recommendation decomposes into its computed factors.
  - Every value carries its observation type, n and uncertainty.
- **P11A-DM4 (live and offline).**
  - Recalculation meets §16 on the replay.
  - A plan from an offline snapshot equals the online plan on the same snapshot.

---

## 18. Acceptance criteria

1. **A, per-team profile.** Each team at a replayed event has per-component μ̂ ± σ̂ with n, observation types,
   snapshot id and `last_updated`. Unsupported seasons are refused.
2. **A, small samples (Scenario I).** For a team with one extreme match, μ̂ moves toward the match value by at most
   the pre-declared shrinkage bound, and σ̂ reflects n = 1. The output reports the prior's kind, its mean, its SD and
   the data weight w. Below w_min or n_min the value is labelled `prior_dominated`. With no prior and n < n_min it is
   `insufficient_data`, and no value is computed from zero.
3. **B, no double counting.** For a capped component in a test configuration, AS-1's expectation equals the
   analytically computed E[min(cap, Σ)] within tolerance. For independent components it equals the sum.
4. **B, no arbitrary bonus.** No term appears in V other than those of the declared objective. A test asserts the
   term list is exactly the configuration's.
5. **B, objective honesty.** With the PX or AS-1 P(win) gates unmet, `objective = expected_alliance_score` (points).
   - Under the proposed default, no win probability appears in any user-facing recommendation.
   - Expected score never appears in a probability field, as a percentage, or worded as a chance of winning; tests
     cover both the API and the UI.
6. **C/D, separation.** First-pick values use C1. Each first-pick scenario has its own second-pick list. After a
   recorded first pick, the second-pick list equals that scenario's list.
7. **C/D, combination logic (Scenario C).** In a constructed configuration where d₂ adds more to {us, c} than the
   individually stronger d₁, d₂ ranks above d₁.
8. **E, positions (Scenario D).** Plans for seeds 1 and 8 at the same event differ in turn horizons and availability.
   Both are correct against `turn_order`.
9. **E, non-captain (Scenario E).** A non-captain gets destinations and no first-pick/second-pick "choice" lists.
   Invitation likelihood is withheld without F.
10. **F, separation.** Predicted states never change `availability()`. Every probability is labelled with its model
    and status.
11. **H, unexpected outcomes (Scenarios F, G).** A team predicted taken but still available is evaluated as
    available. A taken team disappears from every list on the next response. The replacement is recomputed.
12. **H, staleness (Scenario L).** A forced failure after an action leaves the previous plan visible, marked stale
    with the reason, never current.
13. **G, profiles (Scenario K).** Every card links to its own team's profile at the same event. The profile's values
    equal the plan's for that team.
14. **I, offline (Scenario J).** Identical outputs offline, with network calls blocked by test.
15. **Security.** Every new route is tested as each role and as another team. Team-private inputs never appear in
    another workspace's response.
16. **Contracts.** `phase7_contract_lock check` passes, with only additive entries (or relocks with their decision).
    Zero-LLM, foundation and frontend contract tests pass.
17. **Performance.** §16 targets are met on the replay sample, or the miss is recorded.
18. **B, three active robots.** Every expected score is for exactly three active robots, and names its lineup.
    - At a 3-pick event, a fourth alliance member never adds to an expected score as a simultaneous contributor.
    - A backup robot is never part of an expected score.
    - The resilience and replacement analysis is reported separately and is absent from V.
19. **A, identifiability disclosure.** On a constructed schedule where two robots share every match, both robots'
    affected components are labelled `weakly_identified`, with the reason. Every recommendation that depends on them
    is flagged.
20. **A, validation scope.** With only E1a passed, individual estimates are served as `estimated_aggregate_validated`,
    never as independently validated. A per-robot field that does not meet the E1b individual ground-truth standard
    (§20) never upgrades that status. A conversion that fails its parity check (§20, condition 2(c)) is rejected.
21. **A, prior dependence (Scenario Q).**
    - On synthetic schedules with known truths and a current-event prior, the joint model's posterior SD is at least
      the plug-in's for every robot.
    - The joint model's interval coverage meets the nominal level within the pre-registered tolerance.
    - Outputs are labelled `current_event_joint`, with w_eff.
    - No served path uses the plug-in.
22. **B, joint uncertainty (Scenario R).**
    - For a linear, uncapped configuration, AS-1's predictive variance equals the analytic variance including every
      cross-robot and cross-component covariance term, within numerical tolerance.
    - For a capped component, it matches a high-run Monte Carlo reference within the recorded Monte Carlo error.
    - Dropping the cross-robot terms is shown to change the result on correlated inputs, so the test can tell.
23. **B, comparisons (Scenario S).**
    - Close means with wide uncertainty give `unresolved`, never `practically_equivalent`.
    - With synthetic δ and π (labelled synthetic), each outcome in B6's table is produced exactly under its
      condition.
    - With δ and π unapproved, every comparison is `unresolved` (`comparison_threshold_not_approved`).
    - Comparisons of alliances that share members use common random numbers (B5.4).
24. **G, anomalies (Scenario T).**
    - An extreme alliance residual with no direct per-robot evidence appears only as an alliance/match-level anomaly,
      never in any robot's profile, card, strengths or weaknesses.
    - With a qualifying direct observation (G2), a robot-level outlier is reported, labelled with that evidence.

---

## 19. Testing and verification

**Unit tests** (pure, synthetic, labelled synthetic):
- the estimator: shrinkage, n, σ̂, priors, exclusion rules;
- AS-1: independent and capped components, variance, determinism;
- the objective selector;
- optimizer vs brute force;
- the scenario sampler, which respects the rules and the record;
- the F2 state separation;
- explanation templates firing only on their thresholds.

**Required scenarios.** Expected answers derive from the test configuration's mechanics, never hard-coded
preferences:

| Scenario | Setup | Asserts |
|---|---|---|
| A, complementary | Our robot strong in auto and weak in teleop; A strong in teleop; B strong in auto and weak in teleop; independent components | V(us, A) − V(us, B) equals the analytic difference. The ranking follows V, not individual totals |
| B, redundant | Our robot and A excel on component k; B on component j. Run with k uncapped and then capped | Uncapped: A's redundancy adds its full contribution. Capped: A's marginal gain is limited by the cap. The ranking follows each analytic result |
| C, interaction | A is the top first pick; B is the second-best individual; C adds more to {us, A} | C ranks above B in A's conditional list |
| D, positions | The same event, our team as seed 1 vs seed 8 | Turn horizons and availability differ, and each matches `turn_order` |
| E, non-captain | Our team ranked below the captains | Destinations only; no choice lists |
| F, unexpectedly available | F predicts A taken; the record shows another pick | A is evaluated available on the next plan |
| G, unexpectedly taken | Our top recommendation A is picked by another alliance | A is absent everywhere; the plan is recomputed |
| H, missing scouting | A candidate with 0–1 scouting observations | Defense/feeding `insufficient_data`; σ̂ unaffected for the scoring components; no defense points |
| I, small sample | One extreme match | Acceptance criterion 2 |
| J, offline | A packaged snapshot, network blocked | Acceptance criterion 14 |
| K, profiles | Click every card | Acceptance criterion 13 |
| L, stale | Recalculation forced to fail | Acceptance criterion 12 |
| M, temporal integrity | Historical replay with a later match inserted (sentinel) | Outputs unchanged |
| N, three active robots | A 3-pick event, plus an event using backup robots | Acceptance criterion 18 |
| O, weak identifiability | Two robots always scheduled together; a robot with few distinct partners | Acceptance criterion 19 |
| P, prior fallback | A rookie with no prior-event EPA and n below n_min; a veteran with a strong prior and one extreme match | Acceptance criteria 2 and 20; a population prior's τ² is the latent between-team variance (noise removed), not the variance of point estimates or of the mean |
| Q, prior dependence | Synthetic schedules with known truths and no independent prior (A3.2 (iii)) | Acceptance criterion 21 |
| R, joint uncertainty | Robots that often shared matches (correlated estimates); a capped component | Acceptance criterion 22 |
| S, comparisons | Pairs with close means and wide uncertainty; pairs with close means and narrow uncertainty (synthetic δ and π, labelled synthetic); δ and π unapproved | Acceptance criterion 23 |
| T, alliance-level anomaly | An extreme alliance residual with no direct per-robot evidence; then the same with a coach `robot_unavailable` observation | Acceptance criterion 24 |

**Other tests:**
- **DB-backed API tests** on an isolated `stratai_test_<suffix>`: every route, role and team; CSRF; staleness;
  withheld paths; idempotency with the Phase 11 record.
- **Frontend:** Vitest for every panel state, axe, and a real-browser run of a replayed draft at tablet width.
- **Regression:** the full backend suite, against the baseline recorded on the same machine. Every existing Phase 6,
  7 and 11 test passes unchanged; any pinned test changed must give its reason, as Phase 11 did.

**Run-duration limit (binding; Appendix A).**
- **No individual task may exceed 45 minutes.** This covers every test, replay, simulation, evaluation and
  verification task.
- **A longer suite or evaluation is divided** into independently executable runs, each at most 45 minutes, each with
  its own time budget.
- **Each run is reported separately** with its own result. A split is fixed before the first run.
- **A multi-hour combined task is never described as one verification.** A run that hits its budget stops and
  reports partial results; it is not extended.

---

## 20. Historical evaluation

**The counterfactual problem.** The value of an alliance that was not formed is never observed, so "the
recommendation was right" cannot be measured directly. The evaluation therefore validates each component against
what *is* observed, and reports the optimizer's end-to-end comparison as descriptive only.

**Aggregate vs individual validation.** Two kinds of claim are evaluated separately:

| Claim | What can test it | What cannot |
|---|---|---|
| **Aggregate:** an alliance's predicted component and total points (E1a, E2) | Observed alliance points: qualification alliances (E1a) and playoff alliances (E2) | — |
| **Individual:** one robot's numerical contribution estimate (E1b) | Only ground truth meeting the **individual ground-truth standard** below, held out from the estimator | Alliance totals alone, because many different splits of a total fit the same alliance sums equally well; prior- or next-event EPA (a noisy external reference, reported as agreement, not as truth); any per-robot field that does not meet the standard |

**Individual ground-truth standard (E1b).** A per-robot data field is **not** automatically a measurement of that
robot's scoring contribution. A robot's numerical estimate for a (sub-)component may be validated only against one of
two things.

1. **Direct per-robot point contributions in compatible units.** A recorded value that *is* the points this robot
   earned in exactly that (sub-)component and period, in the same units and scope as the estimate.
2. **A documented, pre-registered, validated conversion** from raw per-robot observations to exact point
   contributions, under the applicable approved GameSpec. All of the following must hold:
   - **(a)** The conversion is written down and pre-registered (§20) before any E1b result.
   - **(b)** Under the season's rules, the observation fully determines that robot's points for the (sub-)component.
     No alliance-level bonus, shared credit or unobserved quantity may enter.
   - **(c)** On every stored alliance row, the converted per-robot points of the alliance's robots sum exactly to the
     alliance's breakdown value for that (sub-)component. This is a parity check like P5-M7's, and the conversion is
     rejected if it fails.

**What does not qualify.**
- Categorical, partial or ambiguous observations are **never** treated as complete numerical ground truth for a
  component. Examples:
  - a per-robot "left the zone" flag, when auto points also include game pieces;
  - an endgame state whose points depend on alliance-level conditions;
  - a scouting quality rating.
- At most, such an observation can validate the narrower sub-component it exactly determines, under 2, and only if
  the estimator estimates that sub-component separately.

**Without qualifying ground truth.** For a component with no ground truth meeting this standard, individual
estimates keep their existing status: `estimated_aggregate_validated` if E1a passed, otherwise `not_validated`. They
are never described as individually validated.

**Synthetic recovery tests** check whether the method can recover known per-robot truths on real schedules with
simulated contributions. They test **identifiability under realistic schedules**, not real-world accuracy, and are
labelled so.

**Pre-registration.** One dated, write-once record in `.agent/phase11/decisions/`, written before any held-out
result. It fixes:
- the populations;
- the split;
- the metrics;
- the baselines;
- the pass criteria;
- the seeds;
- the sample;
- the 45-minute budget design.

**Evaluations:**

| ID | What | Observed truth | Metrics | Baselines |
|---|---|---|---|---|
| E1a | A3, aggregate predictions | Held-out qualification matches' alliance component points (the sum of the estimates of the three robots), at each match's time | MAE/RMSE per component; interval coverage; stability (Kendall τ between successive snapshots) | Prior-event EPA sums (P6-M10 alliance means); the event mean; raw alliance averages; each prior choice (A3.2: individual prior-event EPA only, independent population prior only, current-event joint model, the plug-in as a diagnostic only, no shrinkage), with interval coverage reported per prior kind |
| E1b | A3, individual estimates (only where ground truth meeting the standard below exists) | Per-robot point contributions meeting the **individual ground-truth standard** (below), held out from the estimator, only for the (sub-)components they exactly determine | Per-robot error and interval coverage on those (sub-)components; calibration of the `weakly_identified` labels (are flagged estimates measurably worse?) | The scaled prior-event EPA component alone; the independent population prior alone |
| E2 | AS-1 alliance model | **Actual playoff alliances' component and total scores**, with features at the selection moment | MAE/RMSE; 80% interval coverage; any interaction terms' held-out gain | Additive sum of A3; additive prior-event EPA; PX-1 composition sums |
| E3 | P(win) over AS-1 (if attempted) | Playoff match outcomes | Log-loss, Brier, ECE with event-bootstrap CIs | Seed-only; PX-1 recorded results |
| E4 | F availability (if built here) | Reconstructed pick sequences (`scripts/phase11_replay.py` `reconstruct`; declines' timing not reconstructible) | Top-1/top-3 per slot, log-loss, calibration | P6-M6 draft model (top-1 0.211), raw EPA (0.227) |
| E5 | End-to-end (descriptive and observational only) | For actual alliances: the AS-1 value of the real first and second picks vs the plan's, at the selection moment, and their realized playoff results | Regret under AS-1 (a model-internal quantity); association with playoff outcomes | Individual EPA ranking; P11-FB1; P5-M4 ordering |

**E5's limits (binding on how its results are described).**
- **What playoff results can and cannot evaluate.** They evaluate only alliances that were **actually formed**. They
  cannot establish what an alternative, unformed alliance would have scored, or whether it would have won.
- **Regret under AS-1** measures disagreement with AS-1's own valuation. It is not evidence about real outcomes.
- **Association between "agreed with the plan" and playoff success is observational.** It is subject to selection
  effects (stronger captains pick earlier and choose from better pools) and confounding (seed, captain strength,
  bracket position, opponents).
- **E5 never supports a claim** that the optimizer would have selected superior alliances, or that following it
  causes better outcomes. Its record says so in its first line.
- The existing framework and its temporal-leakage rules (below) apply to E5 unchanged.

**Leakage rules:**
- Features use data before the selection moment (E2–E5) or before each match (E1a, E1b).
- Labels are never features.
- Splits are by season or time.
- The sentinel test (Scenario M) runs in every harness.

**Populations:**
- Use 2024–2026 events with approved rulesets, alliances and breakdowns.
- **The 2027 holdout reserved for PX-1b and P6-M10b is not used, inspected or tuned on.**
- Which 2024–2026 split is used, given that PX-1b's final fit used 2024–2026, is decision P11A-Q10. It is recorded
  before any run.
- **Proposed default (P11A-Q10):** the reserved 2027 holdout stays protected, and the split, criteria and thresholds
  are defined and recorded before any evaluation runs.

**Runtime.**
- **No individual evaluation run may exceed 45 minutes** (§19 run-duration limit).
- Each run uses a seeded stratified sample (by season and event size, with FIRST Championship divisions included),
  plus targeted edge cases, fixed before the run.
- An evaluation that needs more is divided, before it starts, into independently executable runs of at most 45
  minutes. Each is reported separately, and the set is never described as a single verification.
- Each harness carries its own budget and reports partial results, as `scripts/phase11_replay.py` does.

**Frozen evidence.** Existing frozen records, fingerprints, seeds and commits are preserved. Thresholds are never
changed after seeing results.

---

## 21. Risks, limitations and unresolved decisions

### 21.1 Data limitations

- **Per-robot evidence is thin.**
  - Current-event scoring is alliance-level.
  - Per-robot EPA components exist only from prior events.
  - Scouting covers defense and feeding quality only, with thin coverage and no inter-scout pairs.
  - Per-robot TBA breakdown fields are unverified (A2).

  A3's per-robot decomposition is a statistical estimate with real uncertainty, especially early in an event.
  - It is identifiable only as far as the schedule varies partners. It is disclosed as `weakly_identified` where it
    is not (A3.7).
  - It can be individually validated only for components that per-robot evidence observes (§20, E1b). Today that may
    be none.
- **Game-specific capabilities** (game pieces, locations, cycle rates) are not observable in the data at all.
  - They need an approved GameSpec plus new per-robot scouting fields (P14-Q1).
  - Until then the catalogue stays at the component level.
- **No defense effect is measured.** Defense contributes zero points, labelled. The defense definition is still open
  (Phase 3 M14; P16-Q2; P11A-Q8).
- **No approved GameSpec exists, and no B4 configuration exists**, so nothing in P11A can be served until they are
  entered and reviewed.
- **Reliability is an attendance ratio**, not a failure rate.
- **Availability prediction is hard.** The existing draft model predicts the real pick 21.1% of the time (top-1).
  - A probabilistic model may do better, but has no evaluation yet.
  - Decline timing is not reconstructible from TBA.
- **Win probabilities are unvalidated:** PX-1 failed, P6-M10 failed, and the 2027 holdout is reserved. Expected score
  is therefore the realistic objective for the foreseeable future.
- **Recommendation quality is not directly measurable** (§20, the counterfactual problem).
- **Phase 11 itself is not yet verified** on a database or real data.

### 21.2 Risks

- **Overfitting the configuration's interaction rules to one season.** Mitigation: manual citations or validated
  terms only.
- **Users reading predicted availability as fact.** Mitigation: the F2 states and visual separation.
- **Optimizer instability between close candidates.** Mitigation: the B6 comparison outcomes (including `unresolved`) and stability
  metrics.
- **Duplication with Phases 13, 14 and 16.** Mitigation: §15's boundaries, and decisions P11A-Q1 and Q2.

### 21.3 Unresolved product decisions

**Proposed defaults.** The defaults below are **proposed, not approved**. They are the working assumption of this
document until the owners decide each question in a dated decision record. An approved decision that differs
replaces its default.

| ID | Decision needed | Why it matters | Proposed default (not approved) |
|---|---|---|---|
| P11A-Q1 | **Availability source until Phase 13 exists:** (a) withheld; (b) build Phase 13's pick model now, as part of P11A; (c) a fixed rule served `not_validated`. Also: may any pick probabilities feed the P6-M7 engine? That is P13-Q1, which would supersede P6-Q6 | It sets C1's expectation and E3's invitation likelihood | No probabilistic availability enters recommendation decisions until the availability model is independently validated (E4). Predicted availability never alters actual availability |
| P11A-Q2 | **Precedence:** where the P11A plan sits relative to the P6-M7 engine and P11-FB1 (it changes decision P11-Q1). Does `…/recommendations` keep serving FB1 or the plan's first pick? | One recommendation source at a time, never mixed | Preserve the existing endpoint contracts and the P11-Q1 source precedence until a separately approved transition is defined |
| P11A-Q3 | **Objective details:** whether P(win) is hidden or shown `not_validated` when ungated; the representative-opponent rule for B6.2; the B6 comparison parameters (equivalence margin δ and decision threshold π); the explanation thresholds; whether resilience (B3) enters V | These fix the objective before evaluation | Use expected alliance score initially. Keep unvalidated win probability out of user-facing recommendations. Resilience stays a separate analysis. Thresholds are set in the pre-registration. δ and π are **not chosen now**: they need benchmark evidence (§20 E2) and approval, and until then every B6 comparison is `unresolved` (`comparison_threshold_not_approved`) |
| P11A-Q4 | **The B4 configuration:** does it extend GameSpec (`data/game_spec.py`) or stand alone? Who enters and reviews it for 2024–2026 and 2027? | No output is servable without it | Extend the existing GameSpec if technically appropriate. No competing source of truth for a season's scoring rules |
| P11A-Q5 | **Same-event EPA** from `retrieved_at`-stamped live snapshots: allowed for serving even though it cannot be backtested? | Better in-event estimates vs an unvalidatable input | Experimental only, explicitly labelled, with point-in-time provenance. Never used to support a historical validation claim unless reconstructable without temporal leakage |
| P11A-Q6 | **Self-reported own-robot capability:** allowed? Shown only, or usable in the objective? Which permission? | A team knows its own robot best, but self-report is biased | Display it separately from measured estimates. Do not include it in the optimization objective initially |
| P11A-Q7 | **A pre-selection plan before a draft record exists:** a separate operation, or "start the record early"? | H2 and the API shape | Support a pre-selection planning view without requiring a draft record to be created early |
| P11A-Q8 | **The defense metric definition in force:** quality only, a frequency term, or quality × volume (open since Phase 3 M14) | It decides how defense is reported in cards | Defense stays a separately reported capability until its scoring and match-outcome effects are validated |
| P11A-Q9 | **Confirm the §16 performance targets** and the reference deployment | The engineering budget | Keep the proposed targets, labelled as targets pending benchmarks on the actual reference hardware |
| P11A-Q10 | **The evaluation population and split** within 2024–2026 (2027 is reserved), and whether part of 2027 is reserved for P11A | Pre-registration needs it before any run | Protect the reserved 2027 holdout. Define the split and criteria before running any evaluation |
| — | **Naming:** is this addendum Phase 11 work, or folded into Phase 13 (pick model) and a new phase (alliance optimization)? | Its relationship to `docs/P11-P19Phases.md` and `docs/ROADMAP.md` |

---

## Appendix A — Global engineering constraints (binding on all P11A work)

- **Preserve functionality.**
  - Do not break analytics, predictions, scouting, the Phase 11 draft tracker, authentication or permissions.
  - Extend; never duplicate the draft log, the draft model, the team profile or the recommendation engine.
  - Locked contracts change only through additive locks or dated relocks.
  - Validation gates are never bypassed.
  - Workspace isolation is never weakened.
- **Databases.**
  - Never write to, migrate or test against the serving `stratai`.
  - Use isolated `stratai_test_<suffix>` copies only (`tests/db_guard.py` is never weakened).
  - Never apply development migrations to production; applying a migration to a deployed database is a separately
    authorized step.
  - Do not assume `.env` points to a safe database: verify the target before any write.
- **Time limits.**
  - **No individual test, replay, simulation, evaluation or verification task may exceed 45 minutes.**
  - Each carries its own budget, and stops and reports partial results when it hits it.
  - Redesign a run before it can exceed the limit.
  - If a complete suite or evaluation takes longer, divide it into independently executable runs of at most 45 minutes
    each, fixed in advance and reported separately.
  - Never present a multi-hour combined task as one verification.
- **Methodology.** Preserve frozen results, fingerprints, seeds, provenance and commits. Never change thresholds,
  populations, splits or criteria after seeing results.
- **Git.**
  - No commit, push, merge or deploy unless the owner authorizes it at the time.
  - Never discard or overwrite unrelated local changes, or touch unrelated branches.
- **Verification states, reported honestly:** implemented → tested with fixtures → verified on an isolated real-data
  copy → validated against real outcomes → accepted by a human. Never claim a stronger state than the evidence
  supports.
- **No LLM in the numerical path.** An LLM may only rephrase finished, verbatim facts through the Phase 9 layer.

---

## Appendix B — Coverage check

**The brief's capabilities:**

| Brief section | Covered by |
|---|---|
| 3 (A) Robot performance evaluation | §6 A1–A7; §8; §20 E1 |
| 4 (B) Synergy and optimization | §6 B1–B7; §9; §20 E2–E3 |
| 5 (C) First-pick optimization | §6 C1–C2; acceptance criterion 6 |
| 6 (D) Second-pick optimization | §6 D1–D3; acceptance criteria 6–7 |
| 7 (E) Captain and draft position | §6 E1–E4; §10; acceptance criteria 8–9 |
| 8 (F) Predicted availability | §6 F1–F4; §10; acceptance criterion 10; P11A-Q1 |
| 9 (G) Explanations and profiles | §6 G1–G3; §11; acceptance criterion 13 |
| 10 (H) Live integration | §6 H1–H5; acceptance criteria 11–12 |
| 11 (I) Offline readiness | §14; acceptance criterion 14 |
| 12 (J) Hybrid architecture | §7; §9 |
| 13 (K) Quality and evaluation | §9; §20 |
| 14 (L) Performance and usability | §11; §16; acceptance criterion 17 |
| 15 Data rules | §8 |
| 16 Integration | §3; §7; §12 |
| 18 Test scenarios A–M | §19 |
| 19 Global constraints | Appendix A |

**The brief's final review items:**

| Final-review item | Where |
|---|---|
| 1 Phase 11 inspected | §2, §3 |
| 2 Existing vs proposed | §4 |
| 3 Event-specific robot evaluation | A3–A7 |
| 4 Season-specific game understanding | A1, B4 |
| 5 Combination-level synergy | B3, B5 |
| 6 First pick separate from second | C, D |
| 7 Second pick depends on the first | D1 |
| 8 Captain positions 1–8 | E2, §10 |
| 9 Non-captains | E3 |
| 10 Expected vs actual availability | F2 |
| 11 Predictions vs confirmed selections | F2, acceptance criterion 10 |
| 12 Unexpectedly available or selected teams | H3 |
| 13 Evidence-based explanations | B7, G1 |
| 14 Clickable profiles | G2 |
| 15 Expected score and P(win) | B6 |
| 16 P(win) not reliable without calibration | B6, acceptance criterion 5 |
| 17 Complementary and redundant capabilities | B2, B4, B5, Scenarios A–B |
| 18 Automatic updates on draft actions | H |
| 19 The Phase 11 log preserved | §2, H5 |
| 20 Offline | §14 |
| 21 Provenance and uncertainty | §8, §9 |
| 22 Temporal leakage prevented | §8, §20 |
| 23 Historical evaluation and baselines | §20 |
| 24 Global constraints | Appendix A |
| 25 No implementation in this task | This document only |

**Revision 1 review items (2026-11-05):**

| Review item | Where |
|---|---|
| 1 Aggregate vs individual validation; identifiability disclosure | A3.7, A3 validation status, A7, G1, §9.6, §17 DM3, §18 criteria 19–20, §19 Scenario O, §20 (table, E1a/E1b), §21.1 |
| 2 Event-mean priors, shrinkage strength, fallback, comparisons | A3.2, §18 criterion 2, §19 Scenario P, §20 E1a/E1b baselines |
| 3 Expected score vs probability of winning | B6, C1, C2, E3, G1, §9.6, §11, §17 DM3, §18 criterion 5 |
| 4 Three active robots vs a fourth member and backup robots | B3 (terminology and rules), §10, §11, §18 criterion 18, §19 Scenario N |
| 5 E5's counterfactual limits | §17 DM2, §20 (E5 and its limits) |
| 6 The 45-minute limit applies to each individual run | §19 run-duration limit, §20 runtime, Appendix A |
| Proposed defaults Q1–Q10 | §21.3 (column), plus the requirements they affect: A4, B1, B3, B4, B5.6, B6, C1, E3, F1, H2, §7, §12, §16, §20 |

**Revision 2 review items (2026-11-05):**

| Review item | Where |
|---|---|
| 1 No double counting in the prior; dependence modelled, tested and disclosed | A3.2 (variances, hierarchy (i)–(iv), shrinkage, dependence tests), §18 criterion 21, §19 Scenario Q, §20 E1a |
| 2 Joint covariance propagated through the scoring rules | A3.3, B5.2–B5.4, §18 criterion 22, §19 Scenario R |
| 3 Individual-robot ground truth | A2, A3 validation status, §20 (individual ground-truth standard; E1b), §18 criterion 20 |
| 4 Comparisons with a pre-registered margin, and `unresolved` | B6 (comparison rule), §9.3, §18 criterion 23, §19 Scenario S, §21.2, §21.3 Q3 |
| 5 Alliance-level anomalies vs robot-level outliers | G2, §18 criterion 24, §19 Scenario T |
