# P8-M0 — Phase 8 decisions (revision 1, 2026-10-18)

**Status: WORKING FREEZE (agent), NOT human-approved.**
- Each decision is marked:
  - **[agent]**: an ordinary engineering decision, taken under Sven Morais's Phase 8 execution mandate
    (2026-10-18), which authorizes implementation decisions without per-decision approval;
  - **[human]**: needs Sven Morais or Kanav. It is not decided here.
- All of them are to be ratified at phase acceptance.
- A changed decision gets a dated record in `.agent/phase8/decisions/`.

| ID | Decision | Rationale |
|---|---|---|
| P8-Q1 [agent] | **Extend the existing `frontend/` app** (React 19, TypeScript, Vite, React Router 7, Vitest + Testing Library, oxlint). The dashboard is a new area next to the Phase 5 human-input area, which is kept unchanged | The repository's stack is already chosen and tested (Phase 1 locked the stack; Phase 5 built it). A second app would duplicate the client, session and test infrastructure |
| P8-Q2 [agent] | **API types are generated from the live OpenAPI document** by a repository script (`scripts/phase8_generate_api_types.py` → `frontend/src/api/generated.ts`), with no npm dependency. A backend test fails if regenerating changes the file. The existing `ENDPOINTS` ↔ OpenAPI test also covers every dashboard operation | The lock is defined over OpenAPI, so the types derive from it with no hand-copied shapes. Drift becomes a failing test, which carries P7-DM2 forward |
| P8-Q3 [agent] | **No new runtime dependencies.** Charts are small inline-SVG components; there is no chart library, UI kit or global state library. One dev dependency is allowed: `axe-core`, for automated accessibility checks in tests | The data is small (one event, one team). A chart library would add weight and decorative defaults. axe is the standard automated a11y checker |
| P8-Q4 [agent] | **Probabilities are displayed exactly as served.** Strategy and playoff odds are the served display strings (`StrategyOdds.display`). An M6/M7 value is shown from `CalibratedWinProbability`: a validated value as a percentage; an unvalidated value only as an explicitly marked "unvalidated model output" with its reason, never in the same visual form. Validation labels are shown verbatim, with a plain-language explanation. `validated_playoff_success` and `validated_playoff` are never merged. The client never computes, rounds or compares probabilities | P6-A5, P7-A7, R2, P7-D7. The frontend must not be the place a label gets upgraded |
| P8-Q5 [agent] | **One refusal-code → unavailable-state map** (e.g. `model_not_loaded`, `not_approved`, `playoff_models_not_accepted`, `epa_source_*`, `selection_time_unavailable`, `insufficient_features`). It gives a plain explanation and keeps the code and request id visible. Unknown codes still show the server's message | Refusals are the normal state outside the environment of record, and must read as truthful states, not crashes |
| P8-Q6 [human] | **The pre-match report's narrative items vs P8-DM2.** The roadmap's report "contains exactly" items that no engine produces. P7-Q12 serves them as explicit absences, and derivation rules need a dated decision. **The safest contract-compatible implementation [agent]:** render them as explicit "not produced by any engine" absences with their semantics. **Consequence:** P8-DM2 "complete" is **NOT met** until a human decides on derivation rules (a new engine output, outside Phase 8 frontend scope) or accepts the report with absences | Fabricating these would violate the no-fabrication and no-LLM rules (CLAUDE.md; Phase 9 is the LLM layer) |
| P8-Q7 [agent] | **"Shareable" means:** a stable URL `/report/{match_key}?as_of=…` that reproduces the report; copy-link; a print stylesheet (layout, labels and absences kept). Read routes need no token | The roadmap's "shareable with an alliance partner as-is". Hosting and access for an outside partner is a deployment matter (same-origin serving, Phase 5 README) and is recorded as a dependency |
| P8-Q8 [agent] | **Coach writes** reuse the session's in-memory token and name (Phase 5). They are gated by `WriteGate`, never retried automatically, disabled while in flight, and show the server's stored result or refusal | The Phase 5/P7-Q10 write model. The writes are not idempotent |
| P8-Q9 [agent] | **Selection lives in the URL** (season, event, team, match, `as_of`, tab), so views are shareable and back/forward works | Shareability; no global state |
| P8-Q10 [agent] | **Data fetching:** one client, with per-view loads through a hook that aborts on unmount or parameter change and ignores stale responses. A timeout gives a typed error. GETs may be retried by the user, never automatically. No cross-view cache | Correctness over cleverness. A cached prediction must not pass for a fresh one |
| P8-Q11 [agent] | **Time:** timestamps are shown in the viewer's local time, with the ISO value in a tooltip. `as_of` is entered as local date-time and sent as ISO-8601 with an offset (P7-D4: a future `as_of` is refused by the server, and that refusal is shown) | Unambiguous moments |
| P8-Q12 [agent] | **Testing:** Vitest + Testing Library + jsdom with fixtures **shaped from the generated types** and labelled synthetic; axe checks; a live smoke script against the local API (`stratai_test`, reference EPA source). A browser-level E2E runs only if a browser runtime is available offline; otherwise it is recorded as a gap | The available toolchain; live checks are honest about the environment |
| P8-Q13 [agent] | **Accessibility target:** WCAG 2.1 AA intent. Semantic landmarks and headings, labelled controls, keyboard operability, visible focus, colour never the only signal (status badges carry text), and chart text alternatives | Usable by the drive team and scouts, including at a field |

## Human decision points (not decided here)
1. **P8-Q6:** derivation rules for the six unproduced report items, or accepting the report with explicit
   absences.
2. **Ratification** of this working freeze and of the phase at acceptance.
3. **The environment of record (P7-Q5):** needed to verify views against real models, i.e. P8-DM1 beyond the local
   API.
4. **Deployment and access** for sharing the report outside the team's machine.
