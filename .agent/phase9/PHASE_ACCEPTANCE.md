# Phase 9 — LLM Report Layer: phase acceptance record (2026-10-20)

**Status: CONDITIONALLY ACCEPTED, NOT COMPLETE (Sven Morais, 2026-10-20; §10).** The MASTER_BUILD Phase Acceptance
Gate is NOT satisfied on its own terms. P9-DM2 and the live LLM verification are deferred to final remediation.
Phase 10 is authorised.

**Git:** branch `phase8/build` at `45859dc`. Nothing is staged and nothing is committed, as instructed. The changed
files are listed in `PHASE_STATUS.md`.

## 1. Milestones

| Milestone | Status | Record |
|---|---|---|
| P9-M0 spec, decisions, baseline | ACCEPTED as an agent working freeze; ratification PENDING | `M00_ACCEPTANCE.md` |
| P9-M1 zero-LLM verification | ACCEPTED (local); the model-backed success paths are only refusals here | `M01_ACCEPTANCE.md` |
| P9-M2 facts and deterministic briefing | ACCEPTED | `M02_ACCEPTANCE.md` |
| P9-M3 LLM formatter | ACCEPTED on stubbed evidence under P9-D1 rev. 2 (ratification PENDING); **live call BLOCKED** (no credential) | `M03_ACCEPTANCE.md` |
| P9-M4 briefing API | ACCEPTED (locked additively) | `M04_ACCEPTANCE.md` |
| P9-M5 dashboard panel | ACCEPTED on fixtures | `M05_ACCEPTANCE.md` |
| P9-M6 cost per event | Tool ACCEPTED, sizes measured; **tokens and cost BLOCKED** | `M06_ACCEPTANCE.md` |
| P9-M7 disconnection, docs, audit | ACCEPTED for the proof and docs; phase decision PENDING | `M07_ACCEPTANCE.md` |

## 2. Done-means

| | Status |
|---|---|
| **P9-DM1:** disconnecting the LLM changes nothing except readability | **MET locally.** 18 operations are identical with the LLM layer blocked and with it enabled (stubbed). 5 of them are full outputs; the stubbed LLM path ran end to end on a real report. The report is identical with the layer used (synthetic stub models). The app builds and serves every other route without the `briefing` package. Model-backed successes are not comparable here (P9-R13) |
| **P9-DM2:** cost per event is known and minimal | **NOT MET.** BLOCKED on a credential (P9-R1). The sizes are measured; the token figures will be lower bounds (P9-R11); "minimal" depends on the model choice (P9-Q5) |

The roadmap's first clause, that every prediction, ranking, strategy and pick list works with zero LLM involvement,
is verified in three ways:
- statically;
- at import time (210/210 modules, with every LLM SDK blocked);
- at runtime: 18 operations, with the limits in M1.

## 3. Major decisions

- **P9-D1 (revision 2):** the LLM arranges facts and writes no words. Its only freedom is grouping, order and a label
  from 13 fixed topic labels; every fact is printed verbatim, exactly once. Two adversarial reviews broke the frozen
  free-text validator and then filtered free lead-ins. This trades readability for provable fidelity, and is
  **pending ratification (P9-Q14)**.
- **The optional layer:**
  - the LLM SDK is only in `requirements-briefing.txt`;
  - the app builds without the `briefing` package;
  - the operation is in the contract lock, added with no change to existing entries.
- **Fail-closed gates:**
  - LLM off by default;
  - data egress off by default (a human decision);
  - the credential never in settings or logs;
  - any failure serves the deterministic briefing with a reason.

## 4. Bugs found and resolved

Review R1 (`reviews/R1_*`, 10 findings) and review R2 (`reviews/R2_*`, 9 findings), all accepted and fixed:
- value laundering, dropped content and unvalidated headings (R1);
- slanting lead-ins (R1, R2);
- crashes on malformed output (R1, R2);
- missing caveats (R1, R2);
- rounding mismatches with the dashboard (R1, R2);
- scanner evasions (R1, R2);
- a vacuous disconnection proof (R2);
- cost-tool pricing errors (R2);
- misleading UI wording (R2);
- tests that could not fail (R1, R2).

The final full suite also found 5 endpoint-inventory pins broken by the new operation. They were updated as
recorded contract-test changes (`docs/phase9.md`).

## 5. Phase-level audit (the Mid-Phase Audit checklist, applied to the whole phase)

| Item | Finding |
|---|---|
| Regressions | None. The backend has exactly the 5 baseline failures; the frontend passes |
| Architectural drift | None. The layer is downstream only, and the scanner enforces it (P9-Q1). Only `api/app.py` imports the route |
| Coupling | The briefing depends on the report's JSON shape (locked). `report_facts` is checked against the real response model through fixtures validated by `PreMatchReportResponse` |
| Duplicated logic | `number()` and `percent()` mirror the dashboard's formatters by design (parity tests). `reference_arrangement` (cost tool) and the test fixture's `arrangement` are similar but serve different purposes |
| Stale documentation | `docs/phase9.md`, the `docs/phase7.md` lock row and the decision record are current. `docs/P9Milestones.md` is frozen; its M3 wording is superseded by P9-D1 (recorded) |
| Hidden assumptions | The en-US locale (P9-R9). Report size and time (P9-R7). The prompt cache minimum (P9-R11) |
| Missing tests | None known for the implemented scope. The live LLM call is untestable here (P9-R1) |
| Race conditions | None introduced. The briefing is stateless; the panel's fetch is keyed and abortable (existing `useResource`) |
| Data quality | Facts never synthesise values. Absences keep their reasons; unproduced items stay absent |
| Statistical validity | No new statistic. Unvalidated outputs are never stated as numbers. Every caveat travels with its value |
| Performance | The briefing rebuilds the report (P9-R7); it is fetched on request only. The LLM call is limited to 30 s and 1 retry |
| Extension | A new operation must be classified (test). New facts need statements; the label list is closed |
| Interface stability | One operation added to the lock, no entry changed; types regenerated |
| Technical debt | The scanner's residuals (P9-R10); the locale (P9-R9) |

## 6. Phase Acceptance Review (nine dimensions)

| Dimension | Assessment |
|---|---|
| Architecture | Sound: a downstream optional layer with fail-closed gates and verbatim facts |
| Maintainability | The facts are one module with tests per caveat; the validator is small (structure plus a closed label list) |
| Scalability | Per-request report build (P9-R7); LLM cost linear in matches (P9-DM2 pending) |
| Extensibility | New report fields need a fact; the parity and caveat tests guide that |
| Performance | Local: the report takes seconds; the briefing adds negligible deterministic work. The LLM latency is unmeasured (P9-R1) |
| Reliability | Every model failure path falls back (18 cases tested); the briefing route never 500s on model output |
| Developer experience | `docs/phase9.md`, a CLI for audit and cost, and clear fallback reasons |
| Security | Credentials are never in settings, logs or results (tested through the real client path). Egress is off by default and is a human decision (P9-R2). Text is rendered as text. No LLM in the core (four checks) |
| Production readiness | **Not established.** No live LLM call, no environment of record, no deployment (P8-R4) |

## 7. Gate evaluation (MASTER_BUILD, "Phase Acceptance Gate")

| Gate condition | Status |
|---|---|
| Every milestone individually accepted | **No:** M3's live scope and M6's token cost are BLOCKED |
| Phase-level audit run, meaningful issues fixed | Yes (section 5) |
| Nine dimensions examined | Yes (section 6); issues fixed or recorded as risks |
| Full phase-relevant suite passes | **No:** the backend exits 1 on the 5 pre-existing baseline failures. The Phase 9 tests all pass |
| Type check and lint | Frontend tsc 0; oxlint 0 errors, 8 baseline warnings. Python has none configured |
| No meaningful unresolved defect | None known in Phase 9's work. The blocked items are not defects |
| Production readiness | **No** (section 6) |
| This record | Written |

**The gate is NOT satisfied on its own terms.** As with Phases 6–8, the phase can only be accepted conditionally by a
human decision, with DM2 and the live verification deferred. **Under MASTER_BUILD, Phase 10 must not begin until that
decision is made.** It must not start in order to work around an unresolved gate.

## 8. Decisions requested from Sven Morais

1. **Phase 9 acceptance:** accept conditionally, with P9-DM2 and the live LLM verification deferred, and authorise
   Phase 10 to begin; or keep Phase 9 open.
2. **P9-Q14:** ratify P9-D1 revision 2 (the LLM writes no words), and the working freeze `docs/P9Milestones.md`.
3. **P9-Q3 / Q4 / Q5** (not blocking acceptance):
   - approve data egress, naming the destination;
   - provide a credential, so DM2 can be measured;
   - choose the model.

## 9. Remaining known risks

`RISK_REGISTER.md`: P9-R1 to R13, and the carried Phase 8 risks.

## 10. Human decision (2026-10-20)

Sven Morais decided (`decisions/P9_PHASE_ACCEPTANCE_DECISION_2026-10-20.md`):
- Phase 9 is **conditionally accepted**, with P9-DM2 and the live LLM verification deferred to final remediation;
- **Phase 10 is authorised**;
- **P9-D1 revision 2 and the working freeze are ratified**;
- data egress and the credential are **kept off and deferred**.
