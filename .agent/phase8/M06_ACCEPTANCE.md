# P8-M6 — Shareable pre-match report: acceptance record

status: IMPLEMENTATION (report UI) ACCEPTED (2026-10-19); P8-DM2 NOT MET, DEFERRED (P8-Q6: Option C now, then D)
date: 2026-10-18 (agent record); updated 2026-10-19: conditional acceptance as directed by Sven Morais (confirmed by Sven Morais on 2026-10-19; PHASE_ACCEPTANCE.md §7); audited 2026-10-19 (final audit)
branch: phase8/build, uncommitted

| Verification state | Result |
|---|---|
| Implemented | yes |
| Tested with fixtures (synthetic) | `ReportPage.test.tsx` 6 |
| Verified against the local API (`stratai_test`, `EPA_SOURCE=statbotics`) | page `report` OK: the report returns 200 (0.81 s); the model parts show `model_not_loaded`; desktop and 390 px screenshots reviewed |
| Verified in the environment of record | BLOCKED (P7-Q5): no pinned models or serving data here |
| Accepted | CONDITIONALLY: directed by Sven Morais and **confirmed by him on 2026-10-19** (PHASE_ACCEPTANCE.md §7) |

## Acceptance criteria
- **Every field traces to the report response, and every absent part shows its `absent_code`.** MET. Each absence shows its code, and the strategy and synergy show theirs. The hard-coded "not-validated" text was removed (R1-4).
- **Nothing is derived client-side.** MET:
  - each role comes from the engine's recommended strategy, or from its labelled baseline;
  - the expected contribution is the served EPA by phase.
- **Shareable.** MET (P8-Q7):
  - a stable URL with `as_of` and `side`;
  - Copy link, with a fallback to showing the link;
  - Print: the print styles hide the chrome; closed sections open for printing and close afterwards (tested); the page title names the match.
- **P8-DM2 "complete" is evaluated honestly.** NOT MET. The six roadmap items no engine produces are shown as "not produced by any engine", each with its semantics (P7-Q12). **Decided 2026-10-19 (Sven Morais): Option C now, then D. DM2 stays unmet and deferred** (`decisions/P8_Q6_DECISION_2026-10-19.md`). M6 accepts the report UI only.

## Gaps
- The report needs a deployment before an alliance partner can open it.
- Printing to A4 was not verified with a PDF renderer.

## Closeout 2026-10-19
- **Print pagination fixed and verified on A4** for locally servable content (P8-R11; 16 → 10 pages, every page inspected). The model-populated sections are not printed (depends on P8-R1).
- **`predicted_flow`:** a decision is PROPOSED (`decisions/P8_D3_…`) and not implemented. **P8-DM2 stays NOT MET.**
