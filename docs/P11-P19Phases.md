# Phases 11–19 — Competition-day alliance selection, simulation, match intelligence and dashboards

**Status: PROPOSED (2026-11-04). Not approved.**
- **Origin:** written by Claude Code on Kanav Jaitly's instruction of 2026-11-04 to turn 13 planned additions into
  sequential development phases.
- **Approval:** Kanav must approve this document before Phase 11 starts. Each phase starts only on his explicit
  instruction, as every earlier phase did.
- **Changes after approval:** any change to a phase's scope, definition of success or acceptance criteria needs a
  dated decision, recorded in `.agent/phase<N>/decisions/` as in Phases 6–10.
- **Scope:** this document is the planning specification only. Nothing in it is implemented.

**Relationship to the existing roadmap.**
- `docs/ROADMAP.md` defines Phases 1–10. Each of those has its own detailed specification in `docs/P<N>Milestones.md`.
- This document continues the sequence with Phases 11–19.
- Unlike `P<N>Milestones.md`, it deliberately defines **phases only, with no milestones**. A phase may be implemented
  in whatever internal order its implementer finds sensible, but it is complete only when its own definition of
  success and acceptance criteria are met.
- Like the earlier specifications, each phase states what it consumes from earlier phases and what it must not
  reopen.

**Who reads this.** A future Claude Code session implementing one of these phases, starting with no memory of how
the document was written, and the project owners who approve each phase. Every statement about the current
repository is dated 2026-11-04 and **must be re-verified against the repository before it is relied on** (section 2).

---

## Contents

1. Summary of the phases
2. The starting point (verify before building)
3. Global engineering requirements (every phase)
4. Phase ordering and dependencies
5. Phase 11 — Live alliance selection: manual draft tracking and dynamic picklist
6. Phase 12 — Go Local: offline alliance-selection operation and safe resynchronization
7. Phase 13 — Alliance captain pick prediction
8. Phase 14 — Match simulation engine with per-robot decisions
9. Phase 15 — Strategy-specific simulation
10. Phase 16 — Robot assessment: strengths and weaknesses, defensive threats, key match risks
11. Phase 17 — Match forecast intelligence: critical matchups, key success factors, predicted match flow
12. Phase 18 — Robot performance heatmaps
13. Phase 19 — Role-based operational and outputs dashboards
14. Open product decisions (all phases)
15. Coverage check: the 13 requested additions

---

## 1. Summary of the phases

| Phase | Title | Requested additions | Priority |
|---|---|---|---|
| 11 | Live alliance selection: manual draft tracking and dynamic picklist | A | 1 — competition-critical |
| 12 | Go Local: offline alliance-selection operation and safe resynchronization | B | 1 — competition-critical |
| 13 | Alliance captain pick prediction | C | 1 — competition-critical |
| 14 | Match simulation engine with per-robot decisions | D | 2 — match strategy and simulations |
| 15 | Strategy-specific simulation | E | 2 — match strategy and simulations |
| 16 | Robot assessment: strengths and weaknesses, defensive threats, key match risks | F, G, H | 3 — advanced match intelligence |
| 17 | Match forecast intelligence: critical matchups, key success factors, predicted match flow | I, J, K | 3 — advanced match intelligence |
| 18 | Robot performance heatmaps | L | 4 — visualization and administration |
| 19 | Role-based operational and outputs dashboards | M | 4 — visualization and administration |

**Why the additions are grouped this way:**
- **Two of the Priority 1 additions stay as separate phases (11 and 12).**
  - Manual alliance selection (A) and Go Local (B) share one data model: the event-day draft state.
  - Go Local also adds an offline runtime and a resynchronization protocol, which are substantial and independently
    verifiable.
  - Phase 11 builds the draft state local-first, so that Phase 12 extends it rather than reworking it.
- **Captain prediction (C) is its own phase (13).** It is a new trained model, with its own pre-registered
  evaluation, consuming Phase 11's live state.
- **Match simulation (D) and strategy simulation (E) are separate phases (14 and 15).** Strategy simulation must run
  on the match-simulation infrastructure, so the two have a hard dependency and distinct definitions of success.
- **The six Priority 3 additions form two phases (16 and 17).**
  - Phase 16 holds the per-robot assessments (F, G, H). They share one evidence layer and need no simulation.
  - Phase 17 holds the match-level forecasts (I, J, K). They need the simulation phases and Phase 16's assessments.
  - Together they produce the six pre-match report items that Phases 7–9 left as explicit absences (P7-Q12;
    section 2).
- **Heatmaps (L) and dashboards (M) are separate phases (18 and 19).** They are different products: one visualizes
  engine metrics, the other extends the role-based dashboards and adds operational status.

---

## 2. The starting point (verify before building)

The following describes the repository on 2026-11-04 (`main` at `85148c6`). **A phase implementer must inspect the
repository first and must not assume any of this is still accurate.** Where a description here and the code
disagree, the code wins, and the difference is reported before work proceeds.

**Project rules that bind every phase** (`CLAUDE.md`, "Critical Constraints" and "Coding Standards"):
- Defense and feeding scores are **directly measured**, never inferred from point output.
- Win probabilities are **unbiased**: an AI strategy can never receive inflated odds.
- The core engine makes **no LLM API calls**. ML, statistics and optimization only. An LLM is allowed only for
  natural-language report generation and explanations (Phase 9, `docs/P9Milestones.md`), and only downstream of
  finished outputs.
- Every test, simulation, replay or verification run finishes within about **45 minutes**.
- Database-backed tests run only against isolated `stratai_test` / `stratai_test_<suffix>` copies
  (`tests/db_guard.py`). The guard is never weakened.

**Existing capabilities these phases build on** (each phase names the ones it consumes):
- **Data pipeline (Phase 2):**
  - TBA and Statbotics clients;
  - raw-first landing (`raw_source_payloads`), staging, canonical tables and lineage;
  - incremental sync and live-event polling (`python -m data.orchestrator --watch`), which since Phase 5 also
    recomputes `team_metrics` after each poll (`data.orchestrator.after_watch_sync`).
- **Team metrics (Phase 3):** `data/metrics/` (average score, consistency, reliability, defense/feeding aggregation
  from scouting only) and `team_metrics`.
- **EPA:**
  - the frozen D18 source (`ml/ratings/d18_source.py`), the evaluated configuration;
  - the live Statbotics source adopted in Phase 5 (P5-D3; `ml/ratings/live_epa.py`, `live_source.py`,
    `live_snapshots.py`).
  - Per-team EPA components (auto / teleop / endgame) come from Statbotics.
- **Season score-breakdown adapters** (`ml/features/score_breakdown.py`): verified alliance-level auto and teleop
  points for 2024–2026. A season without an adapter is refused (`UnsupportedSeasonError`), never guessed.
- **Models (Phase 4):**
  - the pinned ranking and win-probability models (`ml/models/`, `ml/registry.py`, `api/ml_loading.py`);
  - win-probability calibration FAILED its gate on 2026 (P4-M7), and playoff probabilities are miscalibrated. A
    failed gate is not re-run to obtain a pass (D9).
- **Alliance selection (Phase 6, served by Phase 7):**
  - **Rulesets:** per-season P6-M1 rulesets.
  - **Candidate profiles and draft model** (P6-M6): the draft model is **deterministic best-available by the
    validated ordering**, and **"no probabilistic pick model"** by decision **P6-Q6**.
  - **The pick-list optimizer** (P6-M7): it maximizes P(alliance wins the event) using the playoff models PX-1/PX-2
    and the bracket simulator (`ml/playoffs/simulator.py`).
  - **Served routes** (`api/routes/alliance_selection.py`):
    - `GET /events/{event_key}/alliance-selection/candidates` works.
    - `POST /events/{event_key}/alliance-selection/pick-list` accepts a draft state (alliances by seed, declined
      teams, turns taken). It **returns its real refusal until every gate passes**: an approved ruleset and the PX
      gates.
  - P6-DM1 is NOT MET. PX-1 failed its gate, and the replacement candidate PX-1b needs an untouched **2027 holdout**.
    That holdout is reserved and must not be consumed by any phase here.
  - The current ruleset and PX gate state must be read from the repository (`docs/phase6.md`, `docs/phase7.md`,
    `.agent/phase6/`), not assumed.
- **Actual alliances** (`data/alliances.py`): TBA's final alliances per event (seed, captain, picks, backup,
  declines), landed raw. They hold final alliances, not the pick-by-pick sequence. TBA's `backup` field was null for
  every 2024–2026 alliance at ingestion.
- **Strategy engine (Phase 6):**
  - the source-free `Strategy` value type (per-robot roles over the season's component vocabulary, defensive
    assignments, scoring priorities) and coach observations (P6-M9; `ml/strategy/representation.py`,
    `coach_inputs.py`);
  - the single strategy-conditional outcome model with one entry point, `evaluate(context, strategy_red,
    strategy_blue)` (P6-M10, the component model of P6-Q8);
  - the strategy optimizer (P6-M11).
  - Non-baseline strategy odds are served `not_validated`. P6-M10 failed its gate (D9); P6-M10b is a frozen
    candidate awaiting 2027.
- **Event analysis, qualification forecast and team strength** (`ml/views/`): qualification forecast uses a
  Poisson-binomial range, served `not_validated`.
- **Pre-match report** (P7-M7, `GET /matches/{match_key}/pre-match-report`): six ROADMAP report items are served
  as explicit absences, `{value: null, reason: not_produced_by_any_engine, semantics}`:
  - `strengths_and_weaknesses`;
  - `defensive_threats`;
  - `key_risks`;
  - `predicted_flow`;
  - `critical_matchups`;
  - `key_success_factors`.

  A derivation rule for any of them needs its own dated decision (P7-Q12, P8-Q6). The Phase 9 LLM layer may never
  fill them.
- **API contracts (Phase 7):**
  - `docs/api_contract_lock.json` locks 24 operations, checked by `python -m scripts.phase7_contract_lock check`.
  - A change to a locked entry needs a dated decision (`relock --decision`); additive operations use `lock`.
  - Every served operation must be classified in `scripts/phase9_zero_llm_audit.py`.
  - `tests/test_api_foundation.py` pins the exact set of paths.
- **Frontend (Phase 8):**
  - React/TypeScript/Vite in `frontend/`.
  - The dashboard (`frontend/src/dashboard/`) calls only locked operations (`tests/test_phase8_frontend_contract.py`).
  - Charts are inline SVG with no chart library (P8-Q3). They plot only served values, list missing points as
    missing, and always carry a data table.
- **Team workspaces** (2026-11-02; `docs/team_workspaces.md`, migration `0012_team_workspaces.sql`, `workspaces/`).
  **This authentication foundation is implemented and must be extended, never replaced.**
  - Accounts and sessions: individual accounts, server-side sessions, CSRF, rate limits.
  - Roles: admin, strategy (drive team), scouter, with administrator-configurable permissions.
  - Team Management, the activity log, and team-private scouting (`workspace_scouting_reports`: defense and feeding
    ratings 0–5 with notes).
  - The role dashboards: `/team` (Admin Dashboard), `/drive-team`, `/scouting`.
  - The event chooser: pick by year, region and name.
  - The workspace always comes from the server-side session.
  - Existing analytics routes carry permission gates, which are open under the default `ACCESS_POLICY=open`.
- **Deployment** (`docs/DEPLOYMENT.md`): web app on Vercel, API on Render, PostgreSQL on Render. The hosted app
  cannot work without internet access. This matters for Phase 12.

**Data limits that shape Phases 14–18.** Measured per-robot evidence is thin today:
- TBA score breakdowns are **alliance-level** for most components.
- EPA components are **team-level** estimates, not observations of individual actions.
- Scouting records **only defense and feeding** quality, and the coverage of any one event is usually thin.
- Coach observations record a few structured facts, such as a mechanism being unavailable.

Phases 14–18 must work honestly within these limits. Where a capability needs richer per-robot observations, it says
so, labels its output accordingly, and names the additional data. It never synthesizes the missing observations.

---

## 3. Global engineering requirements (every phase)

These apply to every phase in this document, in addition to `CLAUDE.md`. A phase is not complete if it violates any of
them, whatever its own acceptance criteria say.

### 3.1 Preserve existing functionality
- **Do not break existing behavior:** StratAI analytics, predictions, scouting, alliance selection, team
  authentication, team management, the dashboards, the pre-match report or the briefing layer.
- **Extend, do not duplicate:**
  - Extend existing engines, services, routes and pages where appropriate, instead of creating parallel systems.
  - In particular: one strategy outcome model (P6-M10's single entry point), one simulation engine (Phase 14), one
    authentication system (team workspaces), one draft-state model (Phase 11).
- **Replacing working functionality** needs a documented technical reason in the phase's decision record.
- **Locked API contracts stay unchanged.**
  - New operations are added and locked with `scripts/phase7_contract_lock lock`.
  - A change to an already-locked entry needs a dated decision.
  - New operations are classified in the zero-LLM audit and pinned in `tests/test_api_foundation.py`.
  - New frontend calls go through a client whose routes are checked against the live OpenAPI document, as
    `frontend/src/auth/api.ts` is.

### 3.2 Data integrity
- **Real data only:** use actual, validated data, and preserve provenance from every output back to its sources (raw
  payloads, scouting rows, manual entries, model versions).
- **Missing data stays missing:** handle missing or incomplete information honestly. A missing input is reported as
  missing (`insufficient_data`, an explicit absence with a reason), never imputed silently, never zero.
- **Never fabricate** historical records, scouting observations, robot performance, alliance selections or
  simulation results. Synthetic data appears only in tests, labelled synthetic, and never in a served output.
- **Label every value as one of three kinds, in the API and the interface:**
  - **observed data:** a recorded fact, such as a match score, a scouting rating or an administrator's recorded pick;
  - **model prediction:** the output of a trained or statistical model, with its validation status;
  - **simulation output:** a result of repeated sampling under stated assumptions, with its run parameters.
- **Raw-first:** manually entered data (selections, overrides) is stored raw-first and attributed (who, when, from
  which device or mode), like every other human input in this project.

### 3.3 AI and model integrity
- **Appropriate data:** train and evaluate on data that existed at prediction time.
- **No leakage:** prevent temporal and train/test leakage. Every feature for a prediction at time `t` uses only data
  available before `t`, enforced structurally where possible (as `ml/backtest/harness.py`'s `Fold` does) and tested
  with a sentinel (a future fact inserted in an isolated copy must not change the output).
- **Pre-registration:** fix the evaluation population, split, metrics, baselines and pass criteria in a dated,
  write-once record **before** evaluating a new model.
- **No moving the goalposts:** never change thresholds, populations or methodology after seeing results to force
  acceptance. A failed gate is recorded as failed and not re-run to obtain a pass (D9).
- **Honest outputs:** report model limitations and uncertainty with every output. Never present a speculative
  prediction as a certainty. Probabilities that are not validated are labelled `not_validated` and shown with their
  reason.
- **The 2027 holdout** reserved for PX-1b and P6-M10b is not consumed, inspected for model selection, or used for
  tuning by any phase here.
- **Frozen records stay frozen:** existing frozen evaluation results, fingerprints (D18), seeds, provenance records
  and the commits they cite are preserved unchanged.

### 3.4 Security and permissions
- **One authentication system:** preserve team workspaces (accounts, sessions, memberships, roles, permissions,
  invitations, the activity log). No second authentication or identity system.
- **Backend enforcement:** enforce every permission on the backend, at the API and in the service function, not only
  by hiding frontend controls. A route that must be restricted is tested by calling it directly as each role.
- **Team isolation:** team-private data (manual selections, local state, private scouting, team-specific outputs) is
  stored with the workspace id taken from the server-side session, and is unreachable from any other team.
- **Administrative operations** are restricted to authorized administrators, and every one is recorded in the
  activity log.
- **New permissions:** if a phase adds a capability that some roles should and others should not use, it adds a
  configurable or administrator-only permission to the existing permission model (`workspaces/permissions.py`, the
  `workspace_role_permissions` CHECK constraint, the Permissions tab) rather than hard-coding a role check. This is
  supporting infrastructure, not a new product feature.

### 3.5 Go Local reliability (Phase 12 and every phase after it)
- **No silent cloud dependency:** local mode never depends on cloud services or internet access. Any operation that
  would need them in local mode is unavailable, and says so.
- **Manual changes are preserved** across mode switches, restarts and loss of connectivity.
- **No data loss when switching modes:** no local change is overwritten by incoming cloud data without an explicit,
  recorded resolution (Phase 12's synchronization rules).
- **Later capabilities say what they do offline:** every phase after Phase 12 states whether its capability works in
  local mode, works there with reduced inputs, or is unavailable there.

### 3.6 Testing constraints
- **Isolated databases only:** use isolated test databases (`stratai_test_<suffix>`), created for the purpose and
  disposable.
- **Never the serving database:** never read-write or modify the serving database `stratai`.
- **No production migrations:** never apply migrations to production or to the serving database as part of ordinary
  development or testing. Applying a migration to a deployed database is a separate, explicitly authorized step.
- **45 minutes at most:** every expensive test, simulation, replay or verification run stays within the permanent
  45-minute runtime limit and carries its own time budget.
  - If a verification would exceed 45 minutes, redesign it before running it: a seeded random or stratified
    representative sample plus targeted edge cases, fixed before the run.
- **Frozen evidence is preserved:** existing frozen evaluation results, fingerprints, seeds, provenance records and
  commits.
- **Separate verification states, reported honestly:**
  - implemented;
  - tested with fixtures;
  - verified on an isolated real-data copy;
  - validated against real outcomes;
  - accepted by a human.

  A phase never claims a stronger state than it has evidence for.

### 3.7 Git and deployment
- **No push, merge or deploy** as part of implementing a phase unless the project owner explicitly authorizes it at
  that time.
- **Preserve unrelated work:** unrelated local work and uncommitted changes are preserved, never reset or discarded.

---

## 4. Phase ordering and dependencies

```
                 existing: alliance selection (P6/P7), team workspaces, data pipeline, EPA, strategy engine
                                   │
        ┌──────────────────────────┼──────────────────────────────────────────┐
        ▼                          │                                          ▼
   Phase 11  manual draft +        │                                    Phase 14  match simulation
   dynamic picklist (A)            │                                      (D)         │
        │          │               │                                      │           │
        ▼          ▼               │                                      ▼           │
   Phase 12    Phase 13            │                                  Phase 15        │
   Go Local    captain pick        │                                  strategy        │
   (B)         prediction (C) ◄────┘ (uses Phase 12 offline if built)  simulation (E)  │
                                                                          │           │
                                   Phase 16  robot assessment (F, G, H) ──┤           │
                                   (independent of 11–15)                 ▼           ▼
                                                                     Phase 17  match forecast (I, J, K)

   Phase 18  heatmaps (L): after Phase 16 for its assessment metrics; existing metrics need nothing new
   Phase 19  dashboards (M): independent core; adds each earlier phase's outputs as they exist
```

| Phase | Hard dependencies (must exist first) | Soft dependencies (integrate if present) | Can start in parallel with |
|---|---|---|---|
| 11 | existing alliance-selection engine and routes; team workspaces; event rulesets | — | 14, 16, 19 |
| 12 | Phase 11 (its draft state is what local mode preserves and recomputes) | 13 (its predictions should also work offline) | 14, 16, 19 |
| 13 | Phase 11 (live selections and the available pool); historical alliances (`data/alliances.py`) | 12 (offline inference) | 14, 16 |
| 14 | P6-M9 strategy representation and P6-M10 component model; score-breakdown adapters; EPA components | — | 11, 12, 13, 16, 19 |
| 15 | Phase 14; P6-M11 strategy optimizer | — | 16 |
| 16 | existing metrics, EPA, scouting, coach observations | 14 (to quantify a risk's effect) | 11–15, 19 |
| 17 | Phases 14, 15 and 16 | — | 18, 19 |
| 18 | existing metrics (for the first heatmaps); Phase 16 (for assessment heatmaps) | 14 (phase-level simulated contributions, labelled as simulation) | 17, 19 |
| 19 | team workspaces | every earlier phase's outputs, added as they exist | any |

**Product-mandated integrations:**
- Manual alliance selection integrates with Go Local.
- Captain predictions use actual selections and the available pool.
- Match simulation is the infrastructure for strategy simulation.
- Match intelligence reuses existing data and simulation.
- Heatmaps visualize real engine metrics.
- Dashboards integrate with the existing authentication and roles.

None of the phases depends on every earlier phase; the table states exactly which do.

---

## 5. Phase 11 — Live alliance selection: manual draft tracking and dynamic picklist

**Requested addition covered:** A.

### Phase description
- **What happens today:** during alliance selection at a real event, the actual picks happen faster than any data
  feed reports them. StratAI's alliance-selection engine can rank candidates for a given draft state
  (`POST /events/{event_key}/alliance-selection/pick-list`), but nothing records the live draft as it unfolds, and
  every recommendation must be requested by hand with the full draft state typed in.
- **What this phase introduces:** a team-private, event-day **draft record** that a team's administrators update as
  each real selection is made (an accepted pick, a declined invitation, a captain change). StratAI immediately
  recomputes:
  - the pool of available teams;
  - the team's recommended primary picks;
  - the team's backup picks.
- **The result:** the team's picklist always reflects what has actually happened in the room. A team that has been
  selected never appears as an available recommendation.

### Objectives
1. Administrators can record every real alliance-selection action at an event as it happens: invitation accepted,
   invitation declined, captain promoted, and corrections.
2. The pool of available teams updates immediately after each recorded action, under the event's ruleset (for
   example, decline rules and whether a captain can be picked).
3. Recommended primary and backup picks are recalculated from the actual draft state after every change, without
   anyone re-entering the state.
4. Recommendations never include a team that is no longer available.
5. The draft record is complete, ordered, attributed and correctable, with a history of every change.

### Detailed functional requirements

**Administrators (the people at the selection):**
- **Start the draft:** open a live draft record for an event their team attends, at the selection moment.
  - The record starts from the event's final qualification rankings, the eligible captains in seed order, and the
    event's alliance count from its ruleset.
  - If any of these is missing, the record says exactly what is missing, and administrators can still record
    actions manually.
- **Record each action, one at a time, in real order:**
  - "Alliance N captain invites team T. T accepts" (T joins alliance N).
  - "T declines" (T becomes ineligible to be picked under the ruleset's decline rule).
  - "Alliance N's captain is now team C" (a captain promotion when a captain was picked by a higher seed).
  - Backup / reserve robots, if the event and ruleset use them.
- **Each entry is checked before it is accepted:**
  - It is rejected, with a reason, if it is impossible under the current state and ruleset: for example, picking a
    team already on an alliance, a team that declined, or the wrong captain's turn.
  - An administrator can explicitly **override** a check when the room did something the ruleset does not model
    (for example, an event-specific rule).
  - An override is recorded as an override, with its reason.
- **Correct mistakes:**
  - "Undo last" removes the most recent action.
  - "Correct an earlier action" replaces it, after which later actions are re-validated and any now-invalid one is
    flagged.
  - Nothing is ever deleted from the history: corrections are new entries that supersede old ones.
- **Close the record** when selection ends. A closed record is read-only unless reopened, and reopening is recorded.

**Coaches and the drive team (strategy role):**
- **A live view of the draft:** alliances by seed, the current turn (whose pick, which round), available teams and
  unavailable teams with the reason (picked, declined, captain).
- **The team's own recommended primary pick list and backup list:**
  - recalculated after every recorded action, without a page reload;
  - with the time of the last recalculation and the draft position it reflects.
- **Each recommendation shows:**
  - its supporting evidence, from the existing candidate factor profiles;
  - its validation status, as the engine serves it;
  - why it moved, when it moved after an action ("T was picked by alliance 3; S is now first").
- **Primary versus backup:**
  - primary = the best available pick for the team's next turn;
  - backups = the next candidates, in order, should the primary be taken before the team's turn.

  The definitions are documented, and both lists exclude unavailable teams.

**Scouters and other roles:**
- What they see follows their permissions (`alliance_selection` for the live view).
- Recording actions requires the administrative permission this phase adds (see Technical requirements).

**The StratAI system:**
- **The draft record is the single source of truth** for this team's event-day state. Recommendations are always
  computed from it, never from a separately typed state.
- **Recalculation is deterministic** given the record, the event data and the model versions, and completes fast
  enough to keep up with a real selection (a target set by decision P11-Q3).
- **A failed recalculation** (a refusal, a missing input, an engine error) keeps the previous recommendations visible
  but marked **stale**, with the reason and the time they were computed. It never shows them as current.
- **Recording never waits for recalculation:** recording an action always succeeds or fails on its own; the
  recommendation recalculates after it.

### Technical requirements
- **Inspect before designing.** Read `ml/playoffs/selection.py`, `ml/playoffs/service.py`,
  `api/routes/alliance_selection.py` (its `DraftState` and refusal paths), the P6-M1 ruleset model and decline rules
  (`data/rulesets.py`), and `docs/phase6.md` / `docs/phase7.md`. Reuse the existing draft-state type and ruleset
  validation; do not write a second draft model.
- **Storage:**
  - a team-private, append-only **event-log** model for draft actions, with a new migration (the next sequential
    number) and workspace-scoped tables with composite keys to `team_memberships`, following
    `0012_team_workspaces.sql`;
  - the current state is derived by replaying the log.
  - This choice is deliberate: Phase 12 synchronizes logs, not snapshots, so this phase designs the log to be
    **local-first** (stable action ids created on the client or the local server, a per-record sequence, the author,
    a timestamp, and a `source` of `manual` or `imported`).
- **API:** new workspace-scoped operations under `/workspace/...`:
  - start or read a draft record;
  - append an action;
  - undo or correct;
  - close or reopen;
  - read the current state;
  - read recommendations for the current state.

  Each uses the CSRF and session rules of `api/session.py`. The existing locked alliance-selection operations are
  **not changed**; the new recommendation operation calls the same engine service.
- **Recommendation source** (decision P11-Q1, section 14):
  - The P6-M7 optimizer currently refuses until the ruleset and PX gates pass.
  - This phase must not lower those gates or present a refused output as a recommendation.
  - Whichever source the decision chooses is served with its true validation status.
- **Permissions:** add an administrator-only (or administrator-configurable, per decision P11-Q2) permission for
  recording draft actions to `workspaces/permissions.py`, the migration's CHECK constraint, and the Permissions tab.
  The live view uses the existing `alliance_selection` permission.
- **Frontend:** a live alliance-selection page reachable from the drive team dashboard and the Admin Dashboard:
  - the recording controls (administrators);
  - the live board;
  - the primary and backup lists;
  - the change history.

  Large tap targets, usable on a tablet at the event. Updates arrive by polling or server push (a decision for the
  implementer, documented).
- **Activity log:** each recorded action, override, correction, close and reopen is written to `activity_logs`.

### Dependencies
- **Hard:**
  - the existing alliance-selection engine and routes (P6-M6, P6-M7; P7-M6);
  - the P6-M1 ruleset for the event's season;
  - team workspaces (sessions, roles, permissions, activity log);
  - final qualification rankings (TBA rankings ingestion).
- **None:** this phase needs no simulation and no new model.
- **Feeds:** Phase 12 (local mode preserves and recomputes this record) and Phase 13 (predictions consume this
  record).

### Data and methodology requirements
- **Sources:**
  - the draft record (observed, manually entered);
  - final qualification rankings and rosters (TBA, raw-first);
  - the event's ruleset;
  - the candidate factor profiles and engine outputs (as served, with their status).
- **Provenance:** every recommendation is traceable to the draft-record version (sequence number) and the
  engine/model versions it used. Every action is traceable to its author and time.
- **Missing data:**
  - missing rankings or an unapproved ruleset are reported;
  - recording continues without them;
  - recommendations are withheld with the exact reason rather than computed from a guess.
- **Uncertainty:** recommendations carry the engine's probability labels and validation status unchanged. Factor
  values carry their n and `insufficient_data` flags.
- **Interaction with existing engines:** the draft record only supplies state to them; it never changes their logic,
  inputs or gates.
- **Reconciliation with TBA:** when TBA later publishes the event's alliances, they are shown beside the manual record
  as a comparison. They never overwrite it automatically; Phase 12's rules govern reconciliation.

### Definition of success
- **P11-DM1:** at a replayed real past event, an administrator records the event's actual selection sequence. After
  every action, the available pool and the team's primary and backup recommendations reflect exactly the recorded
  state, and no selected or ineligible team ever appears as an available recommendation.
- **P11-DM2:** every recorded action, correction and override is preserved in an ordered, attributed history from
  which the state at any point can be reconstructed exactly.
- **P11-DM3:** recommendations are never presented as current when they are stale, refused or computed from an older
  state, and they never carry a stronger validation status than the engine served.

### Acceptance criteria
1. **Validation and overrides:** recording an impossible action (team already on an alliance, declined team, wrong
   turn) is refused with a reason, unless an administrator records an explicit override with a reason. The override
   is visible in the history.
2. **Immediate pool update:** after each accepted action, the available-pool response no longer contains the picked
   team, and does not contain a declined team where the ruleset's decline rule applies, before any recommendation
   is requested.
3. **Recalculation tracks the record:** primary and backup lists are recomputed after each action. Each response
   carries the record sequence number it reflects, and no recommendation ever contains an unavailable team.
4. **Undo and correction:** undo and correction produce the same state as if the corrected sequence had been recorded
   originally, and the history keeps both versions.
5. **Permissions:** only roles holding the recording permission can append, undo, correct, close or reopen,
   verified by calling each route directly as admin, strategy and scouter.
6. **Team isolation:** another team's administrators cannot read or change a team's draft record (verified
   directly).
7. **Unchanged contracts:** no locked operation's contract changes (`phase7_contract_lock check` passes).
8. **Gates are respected:** with the current alliance-selection gates unmet, recommendations follow decision P11-Q1.
   No refused engine output is presented as a recommendation.
9. **Usability:** a full event's selection (8 alliances × 3 picks, plus declines) can be recorded on a tablet-sized
   screen without typing team numbers that are already listed.

### Testing and verification requirements
- **Unit tests:**
  - log replay gives exactly the state;
  - every ruleset rule: declines, captain promotion, serpentine order, backup robots;
  - undo/correct equivalence;
  - override recording.
- **API tests on an isolated database:**
  - every route as each role and as another team;
  - CSRF;
  - refusal paths;
  - stale-recommendation behavior when the engine refuses or fails.
- **Replays of real past events** (a pre-chosen sample, within 45 minutes):
  - reconstruct each event's actual draft from `data/alliances.py` and the rankings (documenting where the true pick
    order cannot be reconstructed);
  - record it action by action;
  - assert that the pool is correct and no unavailable team is ever recommended.
- **Edge cases:**
  - a captain picked by a higher seed;
  - consecutive declines;
  - an event with fewer teams than picks;
  - a correction in the middle of the draft that invalidates later actions;
  - two administrators recording at once (conflicting appends are serialized; the second is re-validated).
- **Frontend tests** (Vitest) for the recording flow and the live board, and a real-browser run of a full replayed
  draft.

---

## 6. Phase 12 — Go Local: offline alliance-selection operation and safe resynchronization

**Requested addition covered:** B.

### Phase description
- **The problem:** competition venues often have unreliable internet, and alliance selection is the worst possible
  moment to lose StratAI.
- **What this phase introduces:** a prominent **Go Local** control for alliance selection. When activated:
  - StratAI stops external data ingestion and cloud-dependent updates;
  - it keeps all downloaded and processed data;
  - all further selections and picklist changes are entered manually;
  - recommendations are recalculated from local data only.
- **Going back online** is a controlled return that never loses or silently overwrites manual work.

**An architectural fact this phase must address:** the hosted deployment runs the web app on Vercel and the API and
database on Render. A browser cannot reach them without internet, so "remains usable if internet connectivity is
lost" is impossible for the hosted app alone. Go Local therefore requires an offline-capable local runtime. Decision
P12-Q1 (section 14) chooses which:
- a local StratAI instance on a laptop at the event (API, database and built web app, all local); or
- an offline-capable web client with its own local store and computation;
- or both.

Whichever is chosen, the behavior below is required.

### Objectives
1. A visible Go Local control on the alliance-selection page (and the drive team dashboard) that switches the team's
   event-day operation to local mode.
2. In local mode:
   - no request leaves the local environment;
   - no ingestion, sync, live-EPA refresh or other cloud update runs;
   - nothing depends on internet access.
3. All data needed for alliance selection at that event is available locally before connectivity is lost, and its
   completeness is checked and shown.
4. Manual selections and picklist changes continue to work in local mode (Phase 11's recording), and recommendations
   are recalculated from local data and the current manual state.
5. The interface shows unmistakably, at all times, that StratAI is in local mode, and since when.
6. A controlled return to online mode that preserves every manual change and resolves conflicts explicitly.

### Detailed functional requirements

**Preparing for local mode ("Prepare to go local"), before the selection while internet is available:**
- **What it gathers:** a local, self-sufficient **event package** for the team's event:
  - rosters;
  - matches and results so far;
  - rankings;
  - EPA values as currently served (with their source and snapshot identity);
  - the team's private scouting;
  - the ruleset;
  - the model artifacts and the alliance-selection inputs the recommendation needs;
  - the current draft record.
- **Integrity and completeness:** it verifies integrity (hashes, counts) and lists anything missing.
- **When it is safe:** a team can prepare well before alliance selection, so local mode is ready before it is needed.

**Going local:**
- **Who and when:** an administrator activates Go Local, from the event page or the alliance-selection page, with a
  one-step confirmation.
- **What changes:**
  - live polling and external refreshes stop for this team's local operation;
  - the mode, its start time and the package's data cut-off time are recorded and shown;
  - every view in local mode states the data cut-off ("Data as of 14:32; local mode since 14:35").
- **The interface:** a persistent banner on every page and a distinct visual treatment of the alliance-selection
  page. No view in local mode may look identical to online mode.
- **Offline availability:** whatever is unavailable offline (for example, refreshing EPA from Statbotics) is shown as
  unavailable in local mode. It never silently fails or hangs.

**Working locally:**
- **Recording and recommendations:** recording selections (Phase 11) works unchanged, and recommendations recompute
  from the event package and the local draft record.
- **Additional manual updates:** administrators can enter the updates alliance selection needs that would normally
  come from the cloud, such as a late-posted final ranking correction. These are marked `manual (local)`.
- **Losing connectivity mid-session** has no effect on anything already in local mode.

**Returning online ("Go back online"):**
- **The decision:** an administrator chooses to return.
- **The reconciliation summary:** before anything changes, StratAI shows:
  - the local changes made since going local;
  - the external data that arrived or changed in the meantime (for example, TBA's published alliances, new match
    results);
  - every **conflict** between them.
- **Local changes are uploaded** to the team's online record as they were made, with their original ids, authors and
  times.
- **Conflicts are never resolved by overwriting manual data automatically.** Each conflict is shown with both
  versions, and an administrator chooses which version to keep, or keeps both with a note. The choice is recorded.
  - The default for every conflict is to keep the manual entry.
- **Repeatable and safe:** reconnection can be interrupted and retried. Partial synchronization never loses or
  duplicates an action; actions are idempotent by id.
- **After reconciliation:** the team returns to online mode, and ingestion resumes.

### Technical requirements
- **Inspect first:**
  - the sync and watch machinery (`data/orchestrator.py`, `after_watch_sync`);
  - the live EPA source and its snapshot log;
  - the deployment (`docs/DEPLOYMENT.md`, `render.yaml`, `frontend/vercel.json`);
  - Phase 11's draft-record design;
  - how models and EPA sources are loaded (`api/ml_loading.py`, `ml/ratings/`).
- **A mode flag** that every ingestion and refresh path checks, so that local mode provably makes no outbound
  request. Implemented by refusing at the client layer, not merely by not scheduling jobs.
- **The event package:** a defined, versioned format with a manifest (contents, hashes, data cut-off, source
  identities), built from the serving data. It never modifies frozen D18 artifacts or fingerprints.
  - It can carry the live EPA values as served at preparation time, labelled with their snapshot identity.
- **Synchronization:** built on Phase 11's local-first event log.
  - Each action has a globally unique id and its origin.
  - Uploads are idempotent.
  - Conflicts are detected by comparing the online and local logs from the last common sequence.
  - Conflict resolutions are themselves log entries.
- **The offline runtime** (P12-Q1). If a local instance:
  - a packaged, documented way to run the API, a local database and the built web app on a laptop;
  - a one-command preparation;
  - no cloud credentials needed in local mode.

  If an offline web client:
  - a local store (for example IndexedDB) for the package and the log;
  - the recommendation computation available offline.

  In either case, there is no second authentication system: local sessions derive from the team's existing accounts
  (for example, credentials or a signed offline grant issued online before going local; decision P12-Q2).
- **API:** operations to:
  - prepare the package;
  - read its status;
  - go local;
  - read the mode;
  - start and complete reconciliation, and resolve each conflict.

  All are workspace-scoped and administrator-only, and every one is recorded in the activity log.

### Dependencies
- **Hard:** Phase 11 (the draft record and its local-first log; the recommendation path to recompute).
- **Soft:**
  - Phase 13: if present, its predictions must also run offline, from the event package;
  - Phase 19: its dashboards show the mode.
- **Independent:** the simulation and match-intelligence phases. Later phases state their own local-mode behavior
  (section 3.5).

### Data and methodology requirements
- **Sources:** the event package, built from validated serving data with its provenance carried in the manifest;
  the local draft record; manual local updates.
- **Provenance:**
  - every value used in local mode is traceable to the package manifest (source, snapshot, cut-off) or to a manual
    entry;
  - every reconciliation decision is recorded with its author and both versions.
- **Missing data:**
  - a package missing something the recommendation needs is shown before going local;
  - in local mode, the affected outputs are withheld with the reason, never computed from substitutes.
- **Uncertainty:** local recommendations carry the same validation labels as online ones, plus a statement of the
  data cut-off. Nothing computed in local mode is labelled as reflecting data after the cut-off.
- **Interaction with existing engines:** local mode runs the same engine code and model versions on packaged data. It
  never runs a simplified or different engine without saying so.

### Definition of success
- **P12-DM1:** with the network physically disconnected, a team that prepared its package can conduct a full
  alliance selection, recording every action and receiving recalculated recommendations, and every view states that
  it is in local mode with the data cut-off.
- **P12-DM2:** in local mode no outbound request is made by any StratAI component (verified by observing network
  activity), and no ingestion or refresh runs.
- **P12-DM3:** after returning online, every action recorded locally exists online exactly once, with its original id,
  author and time. Every conflict with external data was shown to an administrator and resolved by a recorded choice.
  No manual entry was overwritten without that choice.

### Acceptance criteria
1. **The control:** Go Local is a prominent, labelled control on the alliance-selection page, restricted to
   administrators (verified by calling its route as each role).
2. **Package checks:** package preparation reports completeness. A missing required component blocks Go Local with a
   reason, or proceeds only after an explicit acknowledgement, per decision P12-Q3.
3. **No outbound traffic:** in local mode, an automated test with outbound network access blocked runs a full draft
   and its recommendations without error or hang.
4. **Visible mode:** a persistent local-mode banner and the data cut-off appear on every page in local mode.
5. **Survives disconnection:** losing connectivity in the middle of local operation changes nothing.
6. **Reconciliation summary:** reconciliation lists every local change, every external change since the cut-off, and
   every conflict, before anything is written.
7. **Conflict handling:** a conflict (for example, TBA's alliances differing from the manual record) is never
   auto-resolved against the manual entry. Each resolution is recorded in the activity log.
8. **Idempotent sync:** interrupting synchronization part-way and retrying produces no duplicates and no losses.
9. **Isolation:** another team's data is not included in a team's package, and a package from one team cannot be
   loaded into another team's workspace.
10. **Frozen artifacts untouched:** D18 artifacts, frozen records and the serving database are never modified by
    preparing a package or synchronizing.

### Testing and verification requirements
- **Unit tests:**
  - the package manifest and integrity checks;
  - the mode flag refusing every outbound client;
  - log merge and conflict detection;
  - idempotent upload.
- **Integration tests on isolated databases:**
  - prepare, then go local, then record a full replayed draft, then make external changes online, then reconcile
    with conflicts;
  - interrupt the reconciliation at every step.
- **An offline test:** a real-browser run with the network blocked at the operating-system or browser level, not
  merely mocked, for the chosen runtime.
- **Edge cases:**
  - going local with an empty draft;
  - going local mid-draft;
  - two devices in local mode (if the chosen runtime allows it; decision P12-Q4);
  - the package prepared, then the event schedule changing before going local;
  - returning online after TBA has published final alliances that differ from the manual record.
- **Timing:** each run stays within 45 minutes.

---

## 7. Phase 13 — Alliance captain pick prediction

**Requested addition covered:** C.

### Phase description
- **What exists:** StratAI's draft model today assumes captains pick deterministically, by the best available team in
  the validated ordering (P6-M6), and by decision P6-Q6 it has no probabilistic pick model.
- **What this phase introduces:** a trained model that predicts which teams alliance captains are likely to select:
  first picks, second picks and later rounds. It:
  - accounts for team performance, compatibility and the remaining available teams;
  - accounts for historical alliance-selection behavior where reliable data exists;
  - updates its predictions after every real selection recorded in Phase 11;
  - attaches calibrated uncertainty to every prediction.
- **It integrates with the live draft and the dynamic picklist.** It helps a team anticipate which of its targets
  are likely to be taken before its turn.
- **This phase changes a recorded decision.** It needs a dated decision (P13-Q1) on whether and how its predictions
  may also feed the pick-list optimizer's model of the rest of the draft, which P6-Q6 fixed as deterministic.

### Objectives
1. A model that, for any draft state, gives each remaining eligible team a probability of being chosen by the captain
   whose turn it is, and the distribution of picks for the following turns.
2. Predictions for first picks, second picks and subsequent picks, using:
   - team performance features;
   - compatibility with the captain's alliance;
   - the available pool;
   - historical selection behavior where it is reliable.
3. Predictions recomputed immediately after each action recorded in the Phase 11 draft record.
4. Calibrated probabilities, with honest uncertainty, evaluated against a pre-registered baseline on held-out events.
5. Integration with the live draft view: "likely to be taken before your turn" for each of the team's targets, and,
   if decision P13-Q1 allows, in the optimizer's model of the remaining draft.

### Detailed functional requirements

**Coaches and administrators (live draft view):**
- **For the captain currently picking:** the most likely picks, each with its probability and an uncertainty
  statement, and the factors that drive it.
- **For each team on the team's own picklist:** the probability that it will still be available at the team's next
  turn, computed from the predicted picks of every captain who picks before then.
- **After each recorded action:** all predictions refresh, and the view shows how they changed ("T's chance of being
  available at your turn: 62% → 31%").
- **Every prediction is labelled** as a model prediction with its validation status. A prediction is never shown as
  "will pick".

**The StratAI system:**
- **Determinism:** predictions are deterministic given the draft state, data and model version.
- **Withholding:** a draft state outside what the model was trained for (for example, an unusual ruleset, or an
  event with too few teams) produces a withheld prediction with a reason, not a guess.

### Technical requirements
- **Inspect first:**
  - `data/alliances.py` (actual alliances, declines; `backup` is null in 2024–2026);
  - the rankings ingestion;
  - `ml/playoffs/selection.py` and P6-M6's draft model and its recorded opponent-pick measurement (P6-M6
    validation (b));
  - `ml/backtest/harness.py` (folds, leakage guards);
  - `ml/registry.py` (write-once model storage and pins).
- **Training data:** reconstruct the pick-by-pick sequence of past drafts from the final alliances, rankings and the
  ruleset (serpentine order, captain promotions, declines).
  - Document exactly where the true sequence cannot be reconstructed (for example, the order of declines), and
    exclude or label those cases by a rule fixed before evaluation.
- **Model:** a per-turn choice model over the eligible pool, conditioned on the draft state.
  - Examples: a conditional-logit model, or a gradient-boosted ranking model calibrated to probabilities. The
    implementer chooses and documents why.
  - Features are computed point-in-time at the selection moment only, from data that existed before selection.
  - Explainability is preferred (`CLAUDE.md`, Machine Learning Principles).
- **Registration:** registered in the model registry with a pinned version and hash, loaded like the existing models.
- **API:** a workspace-scoped operation returning predictions for the team's current draft record, and an
  event-level operation for a hypothetical state if needed. Both are classified in the zero-LLM audit.
- **Integration with the optimizer** only as decision P13-Q1 allows. Any change to P6-M7's draft model is a
  re-validation event for P6-M8 and follows the D9 rules.

### Dependencies
- **Hard:**
  - Phase 11 (the live draft record and the available pool);
  - historical alliances and rankings (existing ingestion);
  - the model registry.
- **Soft:** Phase 12 (predictions must run offline from the event package when local mode exists).
- **Decision:** P13-Q1 (relationship to P6-Q6 and the optimizer); P13-Q2 (evaluation population).

### Data and methodology requirements
- **Sources:**
  - historical final alliances, declines and rankings (TBA, raw-first);
  - point-in-time team features (EPA as of the selection moment, qualification performance, the existing candidate
    factor profiles);
  - the ruleset.
  - Optionally, captain-specific history (the same captain team's past picks) only if a pre-registered analysis shows
    it is reliable.
- **Additional data:** the true pick order and timing of declines are not in TBA's final alliances. The phase states
  what it can reconstruct and what it cannot, and never fabricates the missing sequence.
- **Leakage:**
  - features use only data before each event's selection moment;
  - outcomes (playoff results) are never features;
  - train and test events are split by season or time, fixed before evaluation;
  - a sentinel test proves that a later fact does not change a prediction.
- **Evaluation:**
  - **Pre-registered** in a dated, write-once record before any held-out result is seen: population, split, metrics
    and baselines.
  - **Metrics:** top-1 / top-3 hit rate per pick slot, log-loss, calibration (reliability curve and ECE), with
    event-bootstrap confidence intervals.
  - **Baselines:** P6-M6's deterministic best-available ordering, and raw-EPA order.
- **The 2027 holdout** reserved by Phase 6 is not used.
- **Uncertainty:** every served probability carries its validation status. If the pre-registered criteria are not
  met, predictions are served `not_validated` (or withheld, per decision P13-Q1). Thresholds are not changed after
  seeing results.

### Definition of success
- **P13-DM1:** on pre-registered held-out events, the model's pick predictions are evaluated once against the
  pre-registered baselines. The result is recorded as measured, and predictions are served with the status the result
  supports.
- **P13-DM2:** during a replayed live draft, predictions update after every recorded action, exclude every
  unavailable team, and give each of the team's targets an availability probability for its next turn.
- **P13-DM3:** no prediction is presented as a certainty, every prediction carries its uncertainty and validation
  status, and a structural test proves the predictions use no post-selection information.

### Acceptance criteria
1. **Pre-registration:** the evaluation record exists, dated and write-once, before the held-out evaluation runs, and
   it is not edited afterwards.
2. **Calibration is reported** per pick slot with confidence intervals. If served as validated, calibration is within
   the pre-registered tolerance.
3. **Only available teams:** a prediction never assigns probability to an unavailable team (picked, declined,
   captain), tested on every state of every replayed draft.
4. **Per-turn probabilities are a distribution:** they sum to 1 over the eligible pool, within numerical tolerance.
5. **No leakage:** the leakage sentinel test passes.
6. **Registered model:** registered, pinned, hash-checked at load, and loadable offline when Phase 12 exists.
7. **Unchanged optimizer** unless decision P13-Q1 authorizes a change. If it does, P6-M8's validation status is
   re-derived honestly, and no earlier result is overwritten.
8. **Scope:** predictions are workspace-scoped where they read a team's private draft record.

### Testing and verification requirements
- **Unit tests:** sequence reconstruction (with fixtures of known drafts), feature point-in-time correctness,
  probability normalization, unavailable-team exclusion.
- **The held-out evaluation:** one pre-registered run on an isolated copy, within 45 minutes (sampled if needed,
  with the sample fixed in advance).
- **Replays:** the Phase 11 replays extended with predictions, checking that updates follow each action.
- **Edge cases:**
  - a captain picked by a higher seed (the captain changes);
  - a decline;
  - a pool smaller than the remaining picks;
  - a ruleset or season the model was not trained on (a withheld prediction).

---

## 8. Phase 14 — Match simulation engine with per-robot decisions

**Requested addition covered:** D.

### Phase description
- **What exists:** StratAI predicts a match's win probability and evaluates strategies through one component model
  (P6-M10: per-component score distributions, then P(win)). It does not simulate what happens when individual robots
  make different decisions.
- **What this phase introduces:** a **match simulation engine**. Given both alliances and a specified decision for
  each of the six robots (what it attempts in each match phase, whether it defends and whom, and so on), it runs
  many stochastic simulations of the match. It produces:
  - predicted score distributions for both alliances;
  - the probability of different scoring outcomes;
  - the win/tie/loss probabilities.

  Each comes with its uncertainty and run parameters.
- **What it is not:** a relabeling of the existing win prediction. It models robot actions and their consequences,
  drawing each robot's capabilities from measured data.
- **What it underpins:** strategy simulation (Phase 15) and parts of match intelligence (Phase 17).

### Objectives
1. A simulation engine that samples complete matches from per-robot capability distributions and per-robot
   decisions, for every robot on both alliances.
2. Robot decisions expressed in the existing strategy vocabulary, the P6-M9 `Strategy` type (roles over the season's
   score components, defensive assignments, scoring priorities), extended only where needed, and only for actions the
   data can support.
3. For a given set of decisions:
   - the predicted score distribution of each alliance;
   - the win, tie and loss probabilities;
   - the probabilities of named outcomes (for example, "red scores 150 or more", "margin within 10");
   - intervals for each.
4. Interaction effects:
   - defense on a robot reduces that robot's contribution, but only by measured effects (zero assumed effect when
     unmeasured, labelled as such);
   - robots share an alliance's capacity where the season's rules impose it.
5. Results that coaches can understand and compare: side-by-side decision sets, distributions as charts with tables,
   and plain statements of the assumptions.

### Detailed functional requirements

**Coaches and the drive team:**
- **Setting up a simulation:** choose a scheduled match, or a hypothetical one (six teams), then set each robot's
  decision, or leave a robot on "as usual" (its measured typical behavior).
- **Comparing decision sets:** compare several decision sets for the same match. For each, StratAI shows:
  - each alliance's expected score and its interval;
  - the score distribution;
  - P(win), P(tie), P(loss);
  - the outcome probabilities;
  - how each robot's contribution changed versus "as usual".
- **Plain-language assumptions:** every result states its assumptions, for example "defense effect: no measured data,
  assumed zero", "team 1234's endgame: 6 observations", and so on.

**The StratAI system:**
- **Reproducibility:**
  - simulations are reproducible: the seed, number of runs and model versions are recorded with each result;
  - the number of runs is enough for the reported precision, which is stated as a Monte Carlo error.
- **Within measured capability only:** a decision that asks a robot to do something its data shows it cannot do (for
  example, an endgame action it has never been observed attempting) is refused or flagged as unsupported, never
  simulated as if possible.
- **Consistency:** under "as usual" decisions for all robots, the engine's predicted P(win) is consistent with the
  existing outcome model's baseline for the same match. Any systematic difference is measured and reported.
- **Labels:** results are labelled **simulation output**, with validation status `not_validated` until a
  pre-registered validation passes.

### Technical requirements
- **Inspect first:**
  - `ml/strategy/` (`representation.py`, `outcome.py`, `engine.py`, `service.py`): reuse the component model and the
    single evaluation entry point;
  - `ml/features/score_breakdown.py` (the season adapters);
  - the EPA component sources;
  - `ml/playoffs/simulator.py` (the existing bracket simulator's seeding and reproducibility conventions);
  - `ml/views/qualification_forecast.py` (its uncertainty presentation).
- **One modelling foundation:** the simulator extends P6-M10's component model (a sampling view of the same
  per-component distributions) rather than introducing an unrelated model.
  - Any new per-robot parameters must be estimated from measured data, with their n.
  - If the simulator needs distributions the component model does not have, they are added to the shared model,
    documented, and validated.
- **Robot capability model:** per robot, per score component, a distribution with its data basis:
  - EPA components;
  - per-robot breakdown fields where a season's breakdown has them (endgame and auto leave are per robot in some
    seasons; verify per season);
  - team-private scouting where the workspace has it;
  - coach observations.

  Each parameter carries its source and n.
- **Decisions:** in the `Strategy` type. Any extension (for example, an explicit "does not attempt endgame") is
  versioned and validated against the season vocabulary.
- **Performance:** bounded run counts with a stated Monte Carlo error. A single match's comparison returns fast
  enough for interactive use (target by decision P14-Q2). Batch runs carry time budgets.
- **API:** new operations to simulate a match or hypothetical under given decision sets. They are classified in the
  zero-LLM audit (outputs) and locked when stable.
- **Frontend:** a match simulation view, reachable from match pages and the drive team dashboard:
  - the decision editor;
  - the side-by-side comparison;
  - distribution charts in the existing inline-SVG style, with data tables;
  - the assumptions list.
- **Local mode:** the simulator runs entirely on local data and artifacts (it makes no outbound calls), so it works
  in Go Local when the event package includes its inputs.

### Dependencies
- **Hard:**
  - the P6-M9 strategy representation and the P6-M10 component model (existing);
  - the season score-breakdown adapters (existing: 2024–2026);
  - EPA components (existing).
- **None** on Phases 11–13.
- **Feeds:** Phase 15 (hard), Phase 17 (hard), Phases 16 and 18 (soft).

### Data and methodology requirements
- **Sources:**
  - match results and score breakdowns (alliance-level, per-robot where they exist);
  - EPA components;
  - workspace scouting (defense and feeding only today);
  - coach observations.
- **Additional data** (named, not invented): realistic per-robot action modelling for a season needs per-robot,
  per-phase scouting fields (for example, auto actions attempted and completed, endgame attempts and successes).
  - These do not exist today.
  - Until they do, the simulator uses team-level and alliance-level measured quantities and says so.
  - Adding such scouting fields is supporting infrastructure that needs a season scouting design (decision P14-Q1).
- **Provenance:** every simulation result records its inputs' sources, the model versions, the seed and the number
  of runs.
- **Missing data:**
  - a robot with too little data for a component gets a wide, explicitly labelled prior with stated assumptions, or
    the simulation is withheld for that decision, per a rule fixed before validation;
  - it is never filled with a plausible-looking value.
- **Uncertainty:** report both the Monte Carlo error (simulation precision) and the parameter uncertainty (what the
  data does not determine). They are different, and both are shown.
- **Validation:** a pre-registered comparison on held-out matches (seasons and split fixed before the run):
  - calibration of the simulated P(win) under "as usual" decisions;
  - coverage of the simulated score intervals against actual scores;
  - all reported as measured.

  Strategy-specific effects (non-"as usual" decisions) stay `not_validated` unless real data measuring them exists.

### Definition of success
- **P14-DM1:** for any scheduled or hypothetical match with supported data, a coach can set per-robot decisions for
  all six robots and receive simulated score distributions, outcome probabilities and P(win), with the Monte Carlo
  error, the assumptions and the data basis shown.
- **P14-DM2:** different decision sets produce different results only through modelled robot actions and measured
  effects. The engine refuses or flags decisions the data cannot support.
- **P14-DM3:** under "as usual" decisions, the simulation's calibration and interval coverage on pre-registered
  held-out matches are measured once and reported, and the outputs carry the status that evidence supports.

### Acceptance criteria
1. **Reproducible:** re-running with the same seed and inputs gives identical results.
2. **Converges:** the Monte Carlo error decreases as the run count increases, as theory predicts (tested).
3. **Monotonic:** increasing a robot's measured capability in a component never decreases its alliance's expected
   score (property test).
4. **Unmeasured effects default to zero:** with no measured defense data, a defensive assignment changes nothing and
   says why.
5. **Unsupported decisions:** a decision outside a robot's measured capability is refused or flagged, never silently
   simulated.
6. **Consistent with the existing model:** "as usual" P(win) agrees with the existing outcome model's baseline
   within a stated tolerance on a test set, or the difference is reported.
7. **One foundation:** the simulator does not create a second strategy outcome model; the shared model's tests still
   pass and the strategy parity audit (P6-M13) still passes.
8. **No inflated odds:** a coach-specified and an AI-specified decision set are simulated identically (the source is
   not an input).
9. **Contracts and audit:** no LLM call (zero-LLM audit passes); locked contracts unchanged.

### Testing and verification requirements
- **Unit tests:** per-component sampling, decision application, interaction effects, seeding, Monte Carlo error
  estimation, and refusal of unsupported decisions.
- **Property tests:** monotonicity, symmetry (swapping red and blue swaps the results), and no-effect defaults.
- **Validation:** one pre-registered held-out run on an isolated copy, sampled to fit 45 minutes.
- **Performance tests** for the interactive target.
- **Edge cases:**
  - a team with no EPA (no prior event);
  - a season without an adapter (refused);
  - a hypothetical match with a team not at the event;
  - all six robots set to defend.

---

## 9. Phase 15 — Strategy-specific simulation

**Requested addition covered:** E.

### Phase description
- **What exists:** StratAI recommends match strategies (P6-M11) and evaluates them through the single outcome model,
  but a coach cannot see how each recommended strategy plays out.
- **What this phase introduces:** every strategy option StratAI recommends, and any strategy a coach enters, can be
  run through the Phase 14 simulation engine under the same assumptions. For each strategy, StratAI shows:
  - each alliance's P(win);
  - expected scores;
  - outcome probabilities.

  Strategies are compared consistently, the strongest expected outcome is identified, and the uncertainty and
  assumptions are communicated.
- **Built on Phase 14:** it is not a second simulation engine.

### Objectives
1. Simulate every strategy option the strategy engine recommends for a match, and any coach strategy, on the Phase 14
   engine.
2. For each strategy:
   - each alliance's P(win);
   - expected scores with intervals;
   - outcome probabilities;
   - the per-robot contribution changes.
3. Compare strategies under identical assumptions: the same opponent behavior, data, seed policy and number of runs.
4. Identify the strategy with the strongest expected outcome, and state whether its advantage over the next one
   exceeds the combined uncertainty.
5. Communicate uncertainty and assumptions, including the `not_validated` status of strategy effects, in plain
   language.

### Detailed functional requirements

**Coaches and the drive team (match strategy view):**
- **Simulate and compare:** next to the existing recommended strategies and coach scenarios, a "Simulate and compare"
  action runs all of them.
- **The comparison table:** one row per strategy, with P(win), expected scores, the margin interval and key outcome
  probabilities. The highest expected outcome is marked.
- **When strategies are indistinguishable:** if two strategies are within simulation and parameter uncertainty of
  each other, the view says so plainly ("no meaningful difference at this precision"), rather than declaring a winner.
- **Opponent behavior:** the opponent's behavior is the stated assumption: the "no strategy specified" baseline, or a
  coach-specified opponent strategy, as in P6-M11. It is the same for every compared strategy.
- **Scope:** strategies for qualification and playoff contexts follow the existing context rules (a playoff context
  only where the playoff models allow; otherwise labelled).

**The StratAI system:**
- **Same entry point, no source input:** AI-recommended and coach strategies are simulated through the same entry
  point with no field identifying the source, preserving the odds-parity guarantee (P6-DM2, P6-M13).
- **Common random numbers:** all strategies in one comparison share the same random-number stream, so differences
  reflect the strategies and not sampling noise.
- **Reproducible:** comparisons record their seed, run count and inputs.

### Technical requirements
- **Inspect first:**
  - `ml/strategy/engine.py`, `service.py`, `serving.py`, `parity_audit.py`;
  - `api/routes/strategy.py` (the locked assess/recommend/compare operations, which stay unchanged);
  - Phase 14's engine.
- **The adapter:** a strategy-to-decisions adapter maps each `Strategy` (roles, defensive assignments, priorities)
  to Phase 14 per-robot decisions. It is deterministic, versioned, and the only place that mapping lives.
- **Comparison service:** runs all strategies with common random numbers and reports differences with their
  uncertainty (paired comparison).
- **API:** new operations, for example "simulate these strategies for this match", additive. The existing locked
  strategy operations are not changed. The new operations are locked when stable.
- **Frontend:** extends the existing strategy lab and match pages with the comparison table, distributions and
  assumptions, in the existing chart style.
- **Local mode:** works offline when Phase 14's inputs are in the event package.

### Dependencies
- **Hard:** Phase 14 (the simulation engine); the existing P6-M9/M10/M11 strategy engine and its parity audit.
- **Independent of:** Phases 11–13 and 16.
- **Feeds:** Phase 17 (key success factors draw on strategy comparisons).

### Data and methodology requirements
- **Sources:** the same as Phase 14, plus the strategy engine's recommendations and stored coach strategies.
- **Provenance:** each comparison records the strategies (with their provenance kept beside them, never inside),
  the adapter version, the simulation version, the seed and the run count.
- **Missing data:** a strategy that needs an unsupported decision for some robot is reported as not simulatable, with
  the reason, and excluded from the ranking. It is never simulated with a substitute.
- **Uncertainty:**
  - report the paired difference between strategies with its interval;
  - strategy effects stay `not_validated` (as the outcome model's non-baseline strategies are) unless measured;
  - the "strongest" strategy is identified only when its advantage exceeds the stated uncertainty.
- **Interaction with existing engines:** P(win) per strategy must be consistent with the outcome model's evaluation of
  the same strategy, within a stated tolerance, or the difference is reported. Phase 15 never overrides the outcome
  model's served odds.

### Definition of success
- **P15-DM1:** for a match, every strategy the engine recommends, and any coach strategy, can be simulated and
  compared in one view, with P(win) for both alliances, expected scores, outcome probabilities and paired-difference
  uncertainty.
- **P15-DM2:** the strongest-expected strategy is identified only when its advantage exceeds the stated uncertainty;
  otherwise the view says the strategies are indistinguishable.
- **P15-DM3:** odds parity holds. An AI strategy and an identical coach strategy receive identical simulated results,
  verified by an extended parity audit.

### Acceptance criteria
1. **Built on Phase 14:** strategy simulation calls the Phase 14 engine. There is no second sampler, and code review
   finds no duplicated simulation logic.
2. **Common random numbers:** comparing a strategy with itself gives a zero difference exactly.
3. **Odds parity:** the extended P6-M13 parity audit (AI versus coach, identical strategies) passes.
4. **Unchanged contracts:** the existing locked strategy operations are unchanged.
5. **Unsimulatable strategies** are excluded from the ranking with a reason.
6. **Consistency with the outcome model** is within tolerance on a test set, or the difference is reported.
7. **Clear uncertainty:** the interface communicates uncertainty and the `not_validated` status in plain language,
   and states the opponent assumption.

### Testing and verification requirements
- **Unit tests:** the adapter's mapping for every vocabulary role; common-random-number pairing; ranking with
  uncertainty.
- **The parity audit** extended to simulations.
- **Real-data checks on an isolated copy:** a sample of held-out matches. For each, simulate the recommended
  strategies and the baseline, and check consistency with the outcome model, within 45 minutes.
- **Frontend tests** and a real-browser comparison on a real match.
- **Edge cases:**
  - only one strategy available;
  - identical strategies;
  - a strategy with an unsupported decision;
  - a playoff context without validated playoff models.

---

## 10. Phase 16 — Robot assessment: strengths and weaknesses, defensive threats, key match risks

**Requested additions covered:** F, G, H.

### Phase description
- **What is missing:** coaches need to know, for every robot at an event, what it does well, what it does poorly,
  which opponents are likely to defend effectively, and what could go wrong in a match. These are three of the six
  pre-match report items StratAI has served as explicit absences since Phase 7: `strengths_and_weaknesses`,
  `defensive_threats` and `key_risks` (P7-Q12).
- **What this phase introduces:** an evidence-based **robot assessment engine** producing:
  - each robot's strengths and weaknesses relative to the event field;
  - the opposing robots likely to play effective defense, and their estimated effect;
  - the key risks that could significantly reduce an alliance's probability of winning.

  Each item comes with its evidence, and observed evidence is distinguished from inference.

### Objectives
1. **Strengths and weaknesses (F):**
   - for every team at an event, its notable strengths and weaknesses relative to the relevant teams at that event
     (the full field, and its likely playoff peers);
   - using match, EPA, scouting and other validated data;
   - each with an explanation and supporting evidence.
2. **Defensive threats (G):**
   - for a match or an alliance, the opposing robots likely to play effective defense;
   - with the defensive evidence;
   - with the estimated effect on the alliance (through Phase 14 when available, otherwise as a measured-only
     statement);
   - and why each is considered a threat.
3. **Key match risks (H):**
   - for an alliance in a match, the events or conditions that could significantly reduce its P(win): for example,
     a mechanism failure, inconsistent performance, or unreliable autonomous execution;
   - each supported by available data;
   - with observed evidence clearly separated from inferred risk.
4. These items fill the corresponding pre-match report fields, by a dated derivation decision (P16-Q1).

### Detailed functional requirements

**Coaches and the drive team:**
- **Team pages:** a "Strengths and weaknesses" section for the event. Each item:
  - states the dimension (for example, "teleop scoring", "endgame", "consistency", "defense quality");
  - gives the robot's value and its percentile among the relevant comparison group;
  - names the comparison group;
  - gives the evidence (n, the source, a link to the matches);
  - says whether the item is **observed**, such as "scored 0 endgame points in 6 of 8 matches", or **inferred**,
    such as "below-median teleop EPA".
- **Match pages and the pre-match report:**
  - **Defensive threats:** for each opposing robot judged a threat, its defensive evidence (scouting defense ratings
    with n and agreement; defended-frequency if measured), the estimated effect on our alliance, and the reasons.
  - **Key risks for our alliance:** each risk names its type (for example, mechanism, consistency, autonomous,
    endgame), the evidence behind it, whether it is observed or inferred, and, where Phase 14 is available, the
    simulated change in P(win) if the risk occurs.
- **Ordering and empty states:** items are ranked by evidence-backed importance. A robot with too little data gets
  "insufficient data", not invented assessments.

**The StratAI system:**
- **Deterministic rules:** assessments are deterministic functions of point-in-time data, with documented rules
  (thresholds, comparison groups, minimum n) fixed by decision before evaluation.
- **Defense threats use measured defense only:** defense threats derive only from measured defense data (scouting),
  never from point output (`CLAUDE.md`'s first critical constraint). A team with no defense observations is not a
  measured threat, and says so.
- **No invented failure rates:** risks never invent failure rates. "Mechanism failure" is reported only from
  observations (coach observations of an unavailable mechanism, scouting notes classified by a defined, reviewed
  procedure, or match data such as zero points in a component the team usually scores). It is labelled as observed
  with its count.
- **Team-private scouting stays team-private:** outputs that use it are visible only within that workspace, and the
  shared outputs use only shared data.

### Technical requirements
- **Inspect first:**
  - `data/metrics/` (statistics, aggregation, quality);
  - `ml/views/strength.py`;
  - the candidate factor profiles (P6-M6);
  - `ml/strategy/coach_inputs.py`;
  - `workspaces/scouting.py`;
  - the pre-match report service (P7-M7) and its locked contract;
  - `docs/metrics_pipeline.md`.
- **One evidence layer:** a shared per-team, per-event layer (dimension values with n, sources, comparison-group
  percentiles) used by F, G and H, and by Phase 18's heatmaps.
- **Rules:** documented in one module, versioned, and fixed by decision before evaluation.
- **API:**
  - new operations for a team's assessment at an event, and for a match's threats and risks;
  - workspace-scoped variants where team-private scouting contributes.
- **Filling the pre-match report fields** changes a locked contract (null to a value). It needs the P16-Q1 decision
  and a recorded relock, and the Phase 9 briefing layer then formats these items like any other fact.
- **Frontend:** team-page and match-page sections, the report fields, and an evidence drill-down.
- **Local mode:** works offline from the event package.

### Dependencies
- **Hard:** the existing metrics, EPA components, scouting (shared and team-private), coach observations, and the
  candidate factor profiles.
- **Soft:** Phase 14 (to quantify a threat's or a risk's effect on P(win)). Without it, effects are stated
  qualitatively with evidence and labelled unquantified.
- **Independent of:** Phases 11–13 and 15.
- **Feeds:** Phase 17 (matchups use threats; success factors use risks); Phase 18 (heatmaps of assessment
  dimensions).

### Data and methodology requirements
- **Sources:**
  - match results and per-robot breakdown fields where they exist;
  - EPA components;
  - Phase 3 metrics (consistency, reliability with its INTERIM caveat);
  - scouting defense and feeding ratings (with n and agreement);
  - coach observations.
- **Additional data:**
  - robust defensive-threat and mechanism-risk assessment benefits from per-robot scouting of defense played, of
    being defended, and of mechanism problems. These do not exist today;
  - the phase names them, and needs decision P14-Q1 / P16-Q2 to add any;
  - **feeding cannot be validated** (no feeding-quality field exists at collection time; Phase 3 M14), so feeding
    appears only as `insufficient_data` / `not_validated`.
- **Defense definition:** the defense metric definition is an open product decision (quality only, a frequency term,
  or quality × volume; Phase 3 M14, P6-Q11). Defense threats use the definition in force, and say which.
- **Provenance:** every item links to its rows (matches, scouting ids, observation ids) and the rule version.
- **Uncertainty:** each item carries its n and, where applicable, an interval or agreement. Items below the minimum n
  are withheld as insufficient. Inferred risks are labelled as inferred.
- **Validation:** a human review on real past events (a named mentor judges whether the assessments match what a
  knowledgeable scout would say), recorded as measured. This mirrors Phase 3's done-means for defense.

### Definition of success
- **P16-DM1:** for every team at a supported event, the engine returns its strengths and weaknesses relative to a
  named comparison group, each with evidence, n and an observed/inferred label, or "insufficient data".
- **P16-DM2:** for a match, opposing defensive threats are derived only from measured defense data, each with its
  evidence, its estimated effect (quantified when Phase 14 exists) and its reasons. A team without measured defense is
  never shown as a measured threat.
- **P16-DM3:** for a match, key risks are listed with their type, evidence and observed/inferred status. No risk
  carries an invented probability or failure rate.
- **P16-DM4:** a named human reviewer has compared the assessments for a sample of real past events with their own
  knowledge, and the review is recorded with its agreements and disagreements.

### Acceptance criteria
1. **No point-output defense:** no defensive-threat output reads point output as defense evidence (a regression test
   in the style of `tests/test_defense_feeding_constraint.py`).
2. **Observed versus inferred:** every item states which it is, and every observed item links to the observations.
3. **Minimum n:** items below the minimum n are withheld with "insufficient data".
4. **Team-private scouting stays private:** it never appears in another team's outputs or in shared outputs
   (verified directly).
5. **Contract changes are recorded:** pre-match report fields are filled only after the P16-Q1 decision and a
   recorded relock. Before that, they remain explicit absences.
6. **The briefing layer** formats the new items without adding content (the Phase 9 validator passes).
7. **Determinism:** the rules are deterministic, versioned and point-in-time (a leakage sentinel test passes).

### Testing and verification requirements
- **Unit tests:** each rule, comparison-group construction, percentile computation, observed/inferred labelling, and
  the minimum-n behavior.
- **Constraint tests:** the defense-from-measured-only regression test; the team-private isolation test.
- **Real-data runs on an isolated copy:** a sample of past events, within 45 minutes; output sanity checks; the human
  review artifact.
- **Edge cases:**
  - a team with one match;
  - a team with no scouting;
  - an event with no scouting at all;
  - contradictory scouting (low agreement);
  - a season without an adapter.

---

## 11. Phase 17 — Match forecast intelligence: critical matchups, key success factors, predicted match flow

**Requested additions covered:** I, J, K.

### Phase description
- **What is missing:** the remaining three pre-match report items StratAI serves as explicit absences:
  `critical_matchups`, `key_success_factors` and `predicted_flow` (P7-Q12).
- **What this phase introduces:** a **match forecast intelligence** layer that, for a match:
  - identifies the robot-versus-robot interactions most likely to influence the outcome, both favorable and
    unfavorable;
  - states the actionable conditions, actions and decisions most likely to produce a win for our alliance;
  - predicts how the match unfolds across autonomous, teleop and endgame, with expected scoring by phase and, where
    the data supports it, the expected sequence of events.
- **Built from earlier phases:** the simulation engine (Phase 14), strategy simulation (Phase 15) and robot
  assessments (Phase 16). It adds no new predictive model of its own.

### Objectives
1. **Critical matchups (I):** the robot-versus-robot interactions with the largest measured or simulated influence on
   the match outcome.
   - Favorable versus unfavorable.
   - Each with an explanation of how it affects the outcome.
   - Incorporating defensive capabilities (Phase 16) and other evidence.
2. **Key success factors (J):** actionable recommendations for our alliance, each tied to a quantified effect where
   the simulation supports one. For example: "if robot X completes its endgame, P(win) rises from 48% to 61%";
   "assigning Y to defend Z is worth +4 expected points (not validated)". Never generic statements.
3. **Predicted match flow (K):** expected scoring contributions by phase (autonomous, teleop, endgame) for each
   robot and alliance, with intervals, the expected score trajectory, and an explanation of the predicted sequence of
   events where the data supports one.
4. All three fill their pre-match report fields, by a dated derivation decision (P17-Q1).

### Detailed functional requirements

**Coaches and the drive team (match page and pre-match report):**
- **Critical matchups:** a short ranked list. Each entry:
  - names the two robots (or a robot and an alliance);
  - says whether the matchup is favorable or unfavorable for us;
  - states the interaction (for example, "Z defends X: X's teleop contribution falls by an expected 8 points, based
    on 5 defended matches"; "both alliances' endgames compete for one climb position", where the season's rules
    create such contention);
  - gives the estimated effect on P(win) with its uncertainty;
  - gives the evidence.
- **Key success factors:** three to five actionable items, ranked by effect. Each:
  - is phrased as something the alliance can do or ensure;
  - gives its effect (from Phase 14/15 simulation) with its uncertainty and validation status;
  - states the evidence it rests on.

  Items without a measurable effect are omitted, not padded with generic advice.
- **Predicted flow:**
  - a phase-by-phase view of expected points per robot and per alliance, with intervals;
  - the expected lead at the end of autonomous and of teleop;
  - the probability of each alliance leading after each phase;
  - a short sequence narrative where supported (for example, "red is expected to lead after auto; blue's endgame is
    expected to decide the match"), generated **deterministically from the numbers**, not by an LLM. The Phase 9
    briefing may reword it.

**The StratAI system:**
- **Grounded in earlier phases:** every item is derived from Phase 14/15 simulation and Phase 16 assessments, by
  documented rules. Nothing is invented where the data does not support it, which yields an explicit absence with a
  reason.
- **Time ordering within a phase:** the predicted flow reports time-ordered events within a phase only if the data
  supports it. TBA breakdowns and EPA are per-phase totals, so the default is per-phase granularity, stated as such.

### Technical requirements
- **Inspect first:** Phase 14/15 services, Phase 16's evidence layer and rules, the pre-match report service and its
  locked contract, and the strategy engine.
- **Critical matchups:** interaction effects estimated by controlled simulation contrasts (for example, simulate with
  and without the interaction, using common random numbers), ranked by effect, with a minimum-effect threshold fixed
  by decision.
- **Key success factors:** derived from Phase 15 strategy comparisons and Phase 14 sensitivity analyses (the effect
  of each robot's key component succeeding or failing), filtered to actions the alliance controls.
- **Predicted flow:** Phase 14's per-phase contributions, aggregated per robot and alliance, with probabilities of
  leading after each phase.
- **API:** new operations, or the pre-match report's fields after the P17-Q1 decision and a recorded relock.
- **Frontend:** match-page and report sections, phase charts in the existing inline-SVG style, with data tables.
- **Local mode:** works offline with the event package.
- **Runtime:** the controlled contrasts multiply simulation work. Bound the number of contrasts and runs so that a
  match's intelligence returns within the interactive target (decision P14-Q2), and state the precision.

### Dependencies
- **Hard:**
  - Phase 14 (simulation, per-phase contributions);
  - Phase 15 (strategy comparisons for success factors);
  - Phase 16 (defensive threats for matchups, risks for success factors).
- **Independent of:** Phases 11–13.
- **Feeds:** Phase 18 (phase-level heatmaps may show predicted flow, labelled as simulation).

### Data and methodology requirements
- **Sources:** Phase 14/15 outputs and Phase 16 assessments, which carry their own sources.
- **Additional data:** matchup effects beyond defense (for example, contested field resources) require season-specific
  rules and measured data, and appear only where both exist.
- **Provenance:** each item records the simulations and contrasts that produced it (seed, runs, versions) and the
  assessments it used.
- **Uncertainty:** every effect carries its paired-difference interval and validation status (`not_validated` for
  strategy-dependent effects unless measured). An effect smaller than its uncertainty is not presented as a matchup or
  a success factor.
- **Interaction with existing engines:** P(win) values agree with Phase 14/15 for the same scenarios. Phase 17 never
  computes odds of its own.

### Definition of success
- **P17-DM1:** for a match with supported data, StratAI returns ranked critical matchups (favorable and unfavorable),
  each with a simulated or measured effect on P(win), its uncertainty, its evidence and an explanation, or an
  explicit absence when none exceeds its uncertainty.
- **P17-DM2:** it returns three to five actionable key success factors, each with a quantified effect and status, and
  none that is generic or unsupported.
- **P17-DM3:** it returns a predicted flow by phase for every robot and alliance, with intervals and lead
  probabilities, and a deterministic narrative consistent with the numbers.
- **P17-DM4:** the pre-match report serves these three items (after the P17-Q1 decision and relock), and the briefing
  layer formats them without adding content.

### Acceptance criteria
1. **Consistent with simulation:** every effect reported agrees with a re-run of the underlying simulation contrast
   with the same seed.
2. **Within uncertainty means omitted:** matchups and success factors below their uncertainty are omitted (tested).
3. **The flow adds up:** phase contributions sum to the simulated total score, within Monte Carlo error.
4. **Deterministic narrative:** the narrative is deterministic, and its statements are checked against the numbers.
5. **No new odds:** Phase 17 makes no probability computation that does not come from Phase 14/15 (code review and
   test).
6. **Constraints:** defense effects come from measured defense only; the zero-LLM audit passes.
7. **Report contract:** the report fields are filled only after the P17-Q1 decision and a recorded relock.

### Testing and verification requirements
- **Unit tests:** contrast computation, ranking with uncertainty, phase aggregation, narrative generation.
- **Consistency tests against Phase 14/15.**
- **Real-data runs on an isolated copy:** a sample of past matches, within 45 minutes; human review of a sample for
  usefulness and correctness, recorded.
- **Edge cases:**
  - a lopsided match (no influential matchups);
  - a match with no defense data;
  - a season with no endgame component in its adapter;
  - a hypothetical match.

---

## 12. Phase 18 — Robot performance heatmaps

**Requested addition covered:** L.

### Phase description
- **The need:** coaches need to see patterns across many teams and dimensions at once: who is strong where, who is
  weak where, how performance changes across match phases and conditions.
- **What this phase introduces:** heatmaps of robot performance across:
  - metrics;
  - match phases (autonomous, teleop, endgame);
  - event conditions (for example, qualification versus playoff, early versus late in the event);
  - other meaningful dimensions the data supports.

  Each heatmap is built from real values the engines produce, with explicit metric definitions and scales.

### Objectives
1. Heatmaps for an event (teams × dimensions) and for a team (dimensions × matches, or × events), built only from
   served engine values.
2. Every cell links to its value, n and source, and every heatmap states each metric's definition, unit and scale.
3. Strengths, weaknesses and patterns are easy to identify: sortable and filterable rows and columns, and Phase 16's
   strength and weakness designations marked.
4. Missing and insufficient values are visibly distinct from low values.

### Detailed functional requirements

**Coaches, the drive team and administrators** (per their permissions):
- **Event heatmap:** rows are teams; columns are the chosen dimensions (for example, auto, teleop and endgame
  contributions; consistency; defense quality where measured). Choosing the comparison group and the scaling sets the
  colors: percentile within the event, or z-score, as stated.
- **Team heatmap:** a team's per-match values across phases, showing trends and outliers.
- **Event-condition views,** where the data supports them: qualification versus playoff; day 1 versus day 2; a
  sliding window over match number.
- **Accessibility:**
  - every heatmap has a data table and a text summary;
  - color is never the only carrier of meaning: values are shown on hover/focus and in the table;
  - the palette is accessible in light and dark modes.
- **Missing values:** a cell with no data is drawn as "missing" (with the reason), never as a low color.

**The StratAI system:**
- **Served values only:** heatmaps show only values served by the engines (Phase 3 metrics, EPA components,
  score-breakdown phases, Phase 16 assessments, Phase 14 simulated contributions labelled as simulation). No new
  derived metric is introduced without its own definition and owner.

### Technical requirements
- **Inspect first:** `frontend/src/dashboard/charts.tsx` (the inline-SVG chart conventions under P8-Q3, "no chart
  library"); the metrics and assessment APIs; Phase 16's evidence layer.
- **Rendering:** inline SVG following P8-Q3. Adding a chart library needs a dated decision.
- **API:** a served operation returning a matrix of values with n, source and definition per dimension, or the
  existing operations composed, documented. Workspace-scoped where team-private scouting contributes.
- **Local mode:** works offline from the event package.

### Dependencies
- **Hard:** the existing metrics and EPA components (for the first heatmaps).
- **For assessment heatmaps:** Phase 16 (its evidence layer).
- **Soft:** Phase 14 (simulated per-phase contributions, clearly labelled as simulation output).
- **Independent of:** Phases 11–13, 15 and 17.

### Data and methodology requirements
- **Sources:** served engine values only, each with its n and source.
- **Scales:** each heatmap states its scale (percentile within a named group, z-score, or raw units) and its color
  mapping. A heatmap never mixes scales without saying so.
- **Missing data:** shown as missing with its reason (`insufficient_data`, not measured, unsupported season).
- **Uncertainty:** cells built from small n are marked (for example, hatched, or with an n badge), and the minimum n
  for coloring is stated.
- **Interaction with existing engines:** reads served values; computes nothing new except the stated scaling.

### Definition of success
- **P18-DM1:** for a supported event, the event and team heatmaps render real served values for every stated
  dimension, and every cell traces to its value, n and source.
- **P18-DM2:** every heatmap states its metric definitions, units and scale, and missing or small-n cells are visibly
  distinct from low values.
- **P18-DM3:** the heatmaps meet the project's accessibility rules (data table, text summary, no color-only meaning;
  automated accessibility checks pass).

### Acceptance criteria
1. **Values match the API:** every heatmap cell equals the served value it claims to show (tested against the API).
2. **Missing is not low:** missing and insufficient cells never render as a low value (tested).
3. **Scaling is correct:** percentile and z-score scaling are computed as documented and tested.
4. **Accessibility checks pass:** automated accessibility checks (axe) report no violations, and keyboard focus
   reveals values.
5. **Permissions apply:** the same permissions as the underlying data; team-private scouting never appears outside
   its workspace.
6. **Chart conventions:** the rendering follows P8-Q3 (no chart library) unless a dated decision changes it.

### Testing and verification requirements
- **Unit tests** for scaling and missing-value handling.
- **Component tests** for rendering, sorting and filtering, tables and accessibility.
- **Real-data check:** a supported event on an isolated copy, comparing every cell with the API.
- **Edge cases:**
  - an event with one match;
  - a dimension missing for all teams;
  - a mix of large and tiny n;
  - dark mode.

---

## 13. Phase 19 — Role-based operational and outputs dashboards

**Requested addition covered:** M.

### Phase description
- **What exists:** the team-workspace dashboards: the Admin Dashboard (Team Management, permissions, analytics,
  settings, activity), the drive team dashboard and the scouting dashboard.
- **What this phase extends them with:**
  - **For administrators:**
    - system readiness;
    - engine status (which models and EPA sources are loaded and verified, and with which pins);
    - system health;
    - data freshness;
    - Go Local status;
    - other important operational and administrative information;

    alongside the existing Team Management.
  - **For regular users:** a focused view of what StratAI generates (data, predictions, analytics, match simulations,
    strategies and other outputs), organized for use at an event.
- **What does not change:** this phase **extends the existing authentication and role-based dashboard foundation**;
  it does not build a second authentication system. Accounts, memberships, roles and permissions are preserved
  unchanged.

### Objectives
1. An administrator operational view showing:
   - system readiness (database, migrations, the readiness tasks);
   - engine status (models pinned and loaded with their hashes; the EPA source and its integrity state; the playoff
     and strategy model states; the gate states that cause refusals);
   - system health;
   - data freshness (the last sync per source; live-sync state);
   - Go Local mode;
   - important administrative information (pending invitations, verification status, recent activity).
2. A regular-user outputs view, organized around the team's current event: predictions, analytics, simulations,
   strategies, and the alliance-selection and match intelligence outputs, each shown with its validation status.
3. Both views follow the existing permission model: each section appears only to roles holding its permission, and
   every underlying route enforces it on the backend.
4. No regression in existing authentication, account management, memberships or permissions.

### Detailed functional requirements

**Administrators:**
- **The Admin Dashboard gains "System status" and "Engines" sections.**
  - **Each component** shows a clear state (ready, degraded, refusing, not configured), the reason, and the time it
    was last checked.
  - **Refusals are explained:** for example, "pick list refuses: ruleset not approved", "win probability: model
    pinned, calibration gate failed, served not_validated".
- **Data freshness:** the last successful sync per source, live-sync state, and the event package and Go Local mode
  (Phase 12).
- **Operational information:** pending invitations, the workspace's verification status, recent activity, and
  workspace usage (existing analytics).
- **Read-only, nothing secret:** administrators see this state but cannot change server configuration from the
  dashboard, unless a later decision adds specific controls. No secrets, credentials or connection strings are ever
  shown.

**Regular users (strategy and scouter roles):**
- **An outputs view for the team's event (the default event or a chosen one):**
  - **predictions:** match win probabilities, qualification forecast, rankings;
  - **analytics:** team metrics, heatmaps (Phase 18), assessments (Phase 16);
  - **simulations and strategies:** Phases 14–15;
  - **alliance selection:** the live board and picklist (Phases 11–13);
  - **match intelligence:** Phase 17.
- **Each section** appears only when the role holds the matching permission.
- **Validation status is preserved:** every output keeps its validation status and labels exactly as served.
- **Scouters:** the outputs view is secondary to the existing scouting dashboard, as configured by administrators.

**The StratAI system:**
- **Engine status comes from real checks:** the same loading and integrity checks the API performs (model pins and
  hashes; EPA source integrity; gate records), never from a hard-coded list.
- **Backend enforcement:** operational information is available only to administrators, enforced on the backend.

### Technical requirements
- **Inspect first:**
  - `api/routes/health.py` (`/health`, `/ready`, which today checks only the database; P10 risk R8);
  - `api/ml_loading.py` and `api/dependencies.py` (what is loaded and how failures are recorded);
  - `ml/playoffs/service.py` (gate checks);
  - `frontend/src/dashboard/pages/StatusPage.tsx`;
  - the readiness page (`/readiness`);
  - `frontend/src/workspace/` and `workspaces/permissions.py`.
- **API:**
  - an administrator-only, workspace-scoped operation returning the engine, health and freshness state (assembled
    from the real loaders and checks, with secrets excluded);
  - extend the existing health/readiness only additively (`/ready`'s response is relied on by deployments).
- **Frontend:** extend the Admin Dashboard's tabs and the role dashboards. Reuse the existing components, chooser and
  styles.
- **Permissions:** if regular-user sections need finer control, add configurable permissions to the existing model
  (supporting infrastructure, section 3.4).
- **Local mode:** in Go Local the dashboards show the local state and data cut-off, and make no outbound checks.

### Dependencies
- **Hard:** team workspaces (existing).
- **Soft:** every earlier phase. Each section appears when its phase exists; the core operational view needs none of
  them.
- **Can start any time.** The outputs view grows as Phases 11–18 land.

### Data and methodology requirements
- **Sources:** live checks of the running system (loaders, integrity checks, gate records, sync records), and the
  served outputs of the other phases.
- **Provenance:** each status shows when and how it was determined. Each output keeps its own provenance.
- **Missing data:** an unavailable component is shown as unavailable with its reason, never hidden or shown as
  healthy.
- **Uncertainty:** outputs carry their own validation status; the dashboards never strengthen it.

### Definition of success
- **P19-DM1:** an administrator sees, on the Admin Dashboard, the true current readiness, engine status (including
  every refusal's reason), health, data freshness and mode, and each matches what the API's own checks report.
- **P19-DM2:** a regular user sees a focused view of the generated outputs their permissions allow for their event,
  each with its served validation status, and sees no operational or administrative information.
- **P19-DM3:** no existing authentication, account, membership or permission behavior regresses. The existing
  team-workspace test suites pass unchanged, apart from additive tests.

### Acceptance criteria
1. **Accurate status:** every engine status shown matches the corresponding check's result (tested by configuring
   components loaded, unloaded and failing in an isolated environment).
2. **Restricted to administrators:** operational routes are administrator-only, verified by calling them directly as
   strategy, scouter, another team's administrator and an anonymous user.
3. **Nothing secret:** no secret, credential or connection string appears in any response or page (tested with a
   scan).
4. **Outputs follow permissions:** the outputs view's sections follow the configured permissions, and changing a
   permission changes the view on the next request.
5. **Additive only:** `/health` and `/ready` remain backward compatible; locked contracts are unchanged.
6. **Local mode is shown correctly:** in Go Local, the dashboards show the local state without outbound checks.

### Testing and verification requirements
- **API tests** for each status under loaded, unloaded and failing configurations, and for permissions and isolation.
- **Frontend tests** for each role's view.
- **A real-browser check** as administrator, strategy and scouter.
- **The existing team-workspace suites** (`tests/test_workspaces_*.py`, `frontend/src/auth/`,
  `frontend/src/workspace/`) pass.
- **Edge cases:**
  - the database down;
  - the EPA source failing integrity;
  - no models pinned;
  - a pending (unverified) workspace;
  - local mode.

---

## 14. Open product decisions (all phases)

These are genuine decisions for the project owners. An implementer raises them before building the parts that depend
on them, and records the answer as a dated decision. Each is referenced in its phase.

| ID | Phase | Decision needed | Why it matters |
|---|---|---|---|
| P11-Q1 | 11 | **What produces recommendations while the alliance-selection gates are unmet?** The P6-M7 pick list refuses until the ruleset is approved and the PX gates pass. Options: (a) keep the refusal and show only the live board and candidate profiles; (b) serve a clearly labelled `not_validated` ranking from a pre-declared rule over the existing candidate profiles; (c) complete the ruleset review and the PX gates first | A's "recalculate recommended picks" needs a recommendation source. This must not lower existing gates or present refused output as validated |
| P11-Q2 | 11 | Is recording draft actions administrator-only, or an administrator-configurable permission (for example, delegated to a trusted drive-team member)? | The request says administrators record selections; events often have one person at the table |
| P11-Q3 | 11 | The recalculation time target at a live event | It sets the engine-performance requirement |
| P11-Q4 | 11 | Which roles see the live board and the team's picklist during selection? | Picklists are sensitive; the default is the existing `alliance_selection` permission |
| P12-Q1 | 12 | **What is the offline runtime?** A local StratAI instance on a laptop (API, database, web app), an offline-capable web client with a local store, or both | The hosted Vercel/Render deployment cannot work without internet; offline use is impossible without one of these |
| P12-Q2 | 12 | How do people sign in locally without the online server? (For example, a signed offline grant issued online before going local, or local accounts synchronized from the team's accounts.) | There must be no second authentication system, but local mode must still authenticate |
| P12-Q3 | 12 | May Go Local proceed with an incomplete event package after an explicit acknowledgement, or is it blocked? | A trade-off between availability and completeness |
| P12-Q4 | 12 | Are several devices in local mode at once supported (and synchronized locally), or one device per team? | It sets the synchronization design |
| P13-Q1 | 13 | **Do captain predictions feed the pick-list optimizer's model of the remaining draft?** That would supersede P6-Q6, the deterministic draft model, and re-open P6-M8's validation. Or are they shown alongside only? And are they served when they fail their pre-registered criteria (`not_validated`), or withheld? | This changes a recorded Phase 6 decision |
| P13-Q2 | 13 | The training/evaluation population and split (for example, 2024–2025 train, 2026 test), excluding the reserved 2027 holdout | Pre-registration requires it before any evaluation |
| P14-Q1 | 14, 16 | Should per-robot, per-phase scouting fields (auto, endgame, defense played and received, mechanism problems) be added to team scouting, and for which season? | Realistic per-robot simulation and assessment need observations that do not exist today. This is supporting infrastructure needing a season scouting design |
| P14-Q2 | 14, 15, 17 | The interactive response-time target and the precision (Monte Carlo error) to report | It sets run counts and performance work |
| P16-Q1 | 16 | The derivation rules (thresholds, comparison groups, minimum n) for strengths/weaknesses, defensive threats and key risks, and authorization to fill those pre-match report fields (a relock) | P7-Q12 requires a dated decision for any derivation, and the report contract is locked |
| P16-Q2 | 16 | The defense metric definition in force (quality only, a frequency term, or quality × volume) | It is open since Phase 3 M14 and P6-Q11, and drives defensive threats |
| P17-Q1 | 17 | The rules (minimum effect, ranking) for critical matchups and key success factors, and authorization to fill those report fields (a relock) | The same reason as P16-Q1 |
| P19-Q1 | 19 | Should administrators get any controls (for example, re-run a sync, reload a model) on the dashboard, or is it read-only? | Controls are a security-sensitive extension |
| — | all | Should `docs/ROADMAP.md` gain short entries for Phases 11–19 pointing to this document? | `ROADMAP.md` is the master checklist and is quoted as immutable by earlier phase specifications. Adding entries is the owner's call |

---

## 15. Coverage check: the 13 requested additions

| Addition | Phase | Where its requirements are specified |
|---|---|---|
| A. Manual alliance selection and dynamic picklist management | 11 | Section 5: recording, the available pool, recalculated primary and backup picks, unavailable teams excluded, an immediate update, a consistent record |
| B. Go Local mode | 12 | Section 6: the prominent control, data preserved, ingestion stopped, no outside dependence, manual entry, local recalculation, a clear indication, usable offline, a controlled return, conflict handling |
| C. Predict alliance captain selections | 13 | Section 7: first, second and later picks, performance and compatibility, historical behavior where reliable, the remaining pool, updates as picks occur, picklist integration, confidence |
| D. Match simulations with different robot decisions | 14 | Section 8: per-robot actions, all six robots, scores for both alliances, outcome probabilities, variation between runs, coach-friendly comparison; not a relabelled prediction |
| E. Strategy-specific simulations | 15 | Section 9: every recommended strategy simulated, P(win), expected scores, consistent assumptions, the strongest outcome identified, uncertainty; on Phase 14's engine |
| F. Robot strengths and weaknesses | 16 | Section 10: strengths, weaknesses, relative to the event field, validated data, explanations and evidence |
| G. Defensive threats | 16 | Section 10: threats identified, defensive evidence, the estimated effect, explanations |
| H. Key match risks | 16 | Section 10: mechanism, consistency, autonomous and other data-supported risks; observed versus inferred; no invented statistics |
| I. Critical matchups | 17 | Section 11: favorable and unfavorable, interactions, effect on the outcome, defense incorporated |
| J. Key success factors | 17 | Section 11: actionable, quantified, not generic |
| K. Predicted match flow | 17 | Section 11: autonomous, teleop and endgame contributions; a sequence where supported |
| L. Robot performance heatmaps | 18 | Section 12: metrics, phases, conditions, real data, definitions and scales |
| M. Admin and regular-user dashboards | 19 | Section 13: readiness, engine status, health, operational information, Team Management; outputs for regular users; on the existing authentication |
