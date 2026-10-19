# Phase 8 — execution plan (2026-10-18)

**Order:** M0 spec → M1 foundation → M2 event dashboard → M3 team profile → M4 match strategy → M5 alliance
selection → M6 pre-match report → M7 cross-cutting quality → M8 docs, audit and acceptance proposal.

**Interfaces shared across milestones:**
- the generated API types and the one client (M1);
- the `useResource` loading hook;
- the refusal → unavailable map;
- the probability/validation display components;
- the strength-view renderer (M3, reused by M6);
- the strategy renderer (M4, reused by M6);
- the URL selection helpers.

**Risks:**
- **Contract drift:** mitigated by the generated types and the drift test.
- **Probability mislabelling in the UI:** mitigated by one display component per probability kind, plus tests.
- **Refusal states mistaken for errors:** mitigated by the refusal map.
- **Stale async responses:** mitigated by aborting and guarding requests.
- **Fabrication pressure from the report content (P8-Q6):** the items are explicit absences.
- **Coach writes:** no retry; gated.
- **Slow routes** (analysis about 8 s, candidates about 3 s locally): loading states, no duplicate fetches.

**Statistical/ML risks:** the frontend computes no statistics. The risk is presentation alone: rounding, upgrading a
label, or showing an unvalidated value as a probability. P8-Q4 rules it out; tests enforce it.

**High-risk areas:** the strategy editor (complex nested schema), the pick-list draft builder (engine rules), and the
report (completeness pressure).

**Independent review:** after M6, a targeted review covering contract/probability correctness, accessibility/UX, and
security/tests. It is also part of the Phase-Level Audit.

**Human decision points:** P8-Q6 (report narrative items), ratifying the freeze, the environment of record,
deployment and access (P8_M0_DECISIONS.md).

**Verification:**
- frontend: `npm test`, `tsc -b`, oxlint, `vite build`, axe in tests;
- backend: pytest (the contract and types-drift tests);
- the live smoke against the local API (`stratai_test`, `EPA_SOURCE=statbotics`, port 8765);
- the Phase 7 lock check;
- a full backend suite at the start and the end.
