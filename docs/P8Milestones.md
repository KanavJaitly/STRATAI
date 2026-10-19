# Phase 8 — Frontend / Dashboard: milestones (revision 1, 2026-10-18)

**Status:** WORKING FREEZE by Claude Code, 2026-10-18, under Sven Morais's Phase 8 execution mandate. It is
NOT human-approved: ratification by Sven Morais or Kanav is required at phase acceptance. Decisions are recorded
in `.agent/phase8/P8_M0_DECISIONS.md`, and integrity in `.agent/phase8/P8_M0_FREEZE.md`. Any change after the freeze
needs a dated decision in `.agent/phase8/decisions/` (the Phase 6/7 precedent).

**Source:** `docs/ROADMAP.md`, Phase 8 (immutable). This file was empty before revision 1.

## Phase 8 done-means (from `docs/ROADMAP.md`, immutable)
- **P8-DM1:** every view runs off the real API endpoints.
- **P8-DM2:** the pre-match report is complete and shareable with an alliance partner as-is.

**Roadmap scope:**
- the team profile page (metrics, performance history, charts);
- the match strategy view (AI vs coach strategy side by side, with win probabilities and role assignments);
- the alliance selection view (pick list, synergy scores, playoff probability, alternative combos);
- the event dashboard (team list, predicted rankings, playoff contenders);
- the shareable pre-match report: our alliance (role, expected scoring contribution, strengths/weaknesses per
  robot), opposing alliance (roles, contributions, defensive threats, key risks), and match forecast (predicted
  flow, critical matchups, key success factors, win probability).

## Binding inputs from earlier phases
- **The Phase 7 contract** (`docs/api_contract_lock.json`, 24 operations; `docs/phase7.md`) is the only data source.
  The frontend never adds, rounds, clips or relabels a probability (P6-A5, P7-A7, R2). A validation label is shown
  as served; `validated_playoff_success` and `validated_playoff` stay distinct (P7-D7).
- **Phase 7 is conditionally accepted.** P7-M8 (real examples) is blocked, P7-DM1 is unmet, and alliance selection is
  refusal-only under P6-DM1. Model-backed routes answer `model_not_loaded` outside the environment of record
  (P7-Q5).
- **P7-Q12:** the six report items no engine produces (strengths and weaknesses, defensive threats, key risks,
  predicted flow, critical matchups, key success factors) are served as explicit absences. A derivation rule needs
  its own dated decision. **This conflicts with P8-DM2's "complete"** (P8-Q6).
- **Phase 5 conventions:** same-origin `/api`; a write token held in memory only; the existing human-input app is
  kept.

## Standing rules (every milestone)
- **No fabricated data.** No hardcoded sample data in shipped views. Fixtures are for tests only, labelled
  synthetic.
- **Nullable values render as absence,** with the served reason, never as 0, 100% or a guess. Every refusal code
  maps to an explanatory state.
- **No secrets in the bundle.** No new backend endpoint or contract change. The Phase 7 lock and tests stay intact.
- **Each view lists the API operations it calls.** `tests/test_frontend_api_contract.py` checks every one against
  OpenAPI.
- **Verification states are kept separate:**
  - implemented;
  - tested with fixtures;
  - verified against the local API (`stratai_test`, reference EPA source);
  - verified in the environment of record (BLOCKED, P7-Q5);
  - accepted.

## Milestones

### P8-M0 — Specification and decisions
| | |
|---|---|
| **Objective** | This file, P8_M0_DECISIONS.md (P8-Q1…Q13), and a working freeze with blob hashes |
| **Acceptance** | Every roadmap scope item maps to a milestone. Conflicts with earlier phases are recorded. Human-decision items are listed |

### P8-M1 — Frontend foundation
| | |
|---|---|
| **Scope** | (a) An app shell with two areas: the **dashboard** (new) and **human inputs** (existing, unchanged). Routing, with selection kept in the URL (season, event, team, match, `as_of`). (b) Design tokens and primitives: layout, cards, tables, badges, tabs, status and absence components, and small inline-SVG charts (no chart library). (c) **Generated API types:** `scripts/phase8_generate_api_types.py` writes `frontend/src/api/generated.ts` from the live OpenAPI document. A backend test fails on drift. (d) The typed client extended to the Phase 7 operations, in the one `ENDPOINTS` registry. It supports cancellation (AbortController), a timeout, a stale-response guard, envelope errors, network errors and malformed JSON. (e) Formatting: served probability displays; `CalibratedWinProbability` (validated vs unvalidated, kept visually distinct); validation labels; timestamps; absence. (f) One mapping from refusal codes to user-facing unavailable states. (g) A system status page (`/health`, `/ready`) |
| **Acceptance** | The types drift test and the endpoint contract test pass. Client behaviour is tested (abort, timeout, stale, envelope, network, malformed). The existing human-input pages and their 32 tests are unchanged |

### P8-M2 — Event dashboard
| | |
|---|---|
| **Scope** | (a) A season event list (`GET /events`). (b) An event page: team list (`/teams`), matches with results (`/matches`), predicted rankings (`/analysis` `ordering`), playoff contenders (`/analysis` `captain_candidates`, `strongest_teams`), team comparison, and the qualification forecast (`/qualification-forecast`), with `as_of` control. Each part shows its own validation label and its own refusal |
| **Acceptance** | Each section is fed by its route. `model_not_loaded` and `epa_source_*` render as unavailable states with the reason. The ordering shows its model (raw EPA / M5 v2) and the switch point |

### P8-M3 — Team profile
| | |
|---|---|
| **Scope** | For a team at an event: (a) the stored Phase 3 metrics (`/metrics`), with the INTERIM reliability caveat. (b) The point-in-time strength view (`/strength`, `as_of`): EPA components with provenance, scoring statistics with n and uncertainty, defense and feeding with explicit insufficient data. (c) Performance history: the team's matches at the event and their results (`/events/{e}/matches`, filtered client-side to the team; no new endpoint). (d) Charts: match scores over the event, and season auto points by event (`strength.auto_points.season_by_event`) |
| **Acceptance** | Absent values show their reasons. The charts plot only served values, with labelled axes and units. A text summary sits alongside each chart |

### P8-M4 — Match strategy view
| | |
|---|---|
| **Scope** | (a) For a scheduled match, the AI recommendation (`/strategy/matches/{m}/recommend`) and a coach strategy (an editor using the `Strategy` schema), side by side. Odds come from `compare`/`assess`, shown as display strings with the engine's status and reasons. The compare label is shown verbatim, plus role and defensive assignments and the baseline. (b) Hypothetical pairings (`/strategy/hypothetical/*`). (c) The M6/M7 win probability (`/predictions/matches/{m}/win-probability`), in its own panel and never in the same field as strategy odds (P7-A7). (d) Coach writes (`/strategy/coach-strategies`, `/strategy/coach-observations`): the write token from the session, no automatic retry, duplicate-submit prevention, and the server's result shown |
| **Acceptance** | Both paths are shown identically (the P6-DM2 presentation). `selection_note` is shown. A playoff context and missing inputs render the engine's null odds with reasons. Writes are gated. `model_not_loaded` renders as unavailable |

### P8-M5 — Alliance selection view
| | |
|---|---|
| **Scope** | (a) Candidate profiles (`/alliance-selection/candidates`): the factor table with value, n and status; an optional three-team configuration for synergy and role compatibility; sorting. (b) A pick-list draft-state builder (seed, alliances, declined, turns) that posts to `/pick-list`. It renders the ranked picks, the reach-finals comparison, alternatives, provenance and the PX scope reasons when served; otherwise it shows the **real refusal** (`not_approved` today) with its explanation. (c) The alliance synergy tool (`POST /predictions/alliance-synergy`) |
| **Acceptance** | The refusal-only state is clear and truthful. The success rendering is tested with a fixture shaped from the locked schema and labelled synthetic. `validated_playoff_success` is shown as served |

### P8-M6 — Shareable pre-match report
| | |
|---|---|
| **Scope** | A report page `/report/{match_key}?as_of=…` (`GET /matches/{m}/pre-match-report`): our alliance and the opposing alliance (strength per robot, EPA components as the expected-contribution evidence, strategy roles from the recommended and baseline strategies), synergy, the M6/M7 win probability, and the six unproduced items as explicit absences with their semantics. Shareable: a stable URL, copy-link, and a print stylesheet that keeps the absences and labels |
| **Acceptance** | Every field traces to the report response, and every absent part shows its `absent_code`. Nothing is derived client-side. P8-DM2's "complete" is evaluated honestly (P8-Q6) |

### P8-M7 — Cross-cutting quality
| | |
|---|---|
| **Scope** | (a) Accessibility: automated axe checks on every view in tests, keyboard and focus, and accessible chart summaries. (b) Responsive layouts (tables scroll in their own container). (c) Live integration: `scripts/phase8_live_smoke.py` drives every dashboard operation against a running local API and records statuses and codes, plus a browser-level smoke where tooling permits. (d) Performance: no duplicate fetches per view; the bundle size recorded |
| **Acceptance** | axe reports no violations in the tested views. The live smoke records each operation's result. Every gap is recorded |

### P8-M8 — Documentation, audit and acceptance proposal
| | |
|---|---|
| **Scope** | `docs/phase8.md` (configure, run, test, build, deploy; each view's data sources and states), frontend README, Phase-Level Audit, Phase Acceptance Review, `.agent/phase8/PHASE_ACCEPTANCE.md` and a proposed acceptance decision |
| **Acceptance** | P8-DM1 and P8-DM2 are evaluated honestly. The full frontend and backend suites are run, and baseline failures are named. Human acceptance stays PENDING |

## Order and dependencies
M0 → M1 → (M2, M3) → M4 → M5 → M6 → M7 → M8. M6 reuses the M3 strength rendering and the M4 strategy rendering.
M7 runs across all views.
