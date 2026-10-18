# Phase 7 — execution plan (API Layer)

- **Spec:** `docs/P7Milestones.md` (revision 1, DRAFT). **Decisions:** `.agent/phase7/P7_M0_DECISIONS.md` (proposed).
- **Gate:** P7-M0 freeze by Kanav. No implementation before it.

## Milestone order

M0 freeze → M1 contract foundation → M2 metrics/strength → M3 win probability/rankings → M4 event
analysis/discovery → M5 match strategy → Mid-Phase Audit → M6 alliance selection → M7 pre-match report →
M8 real examples → M9 docs and sign-off.

## Interfaces shared between milestones

- The M1 shared `validation` block and per-engine probability objects (P7-Q3), used by M3, M5, M6 and M7.
- The M1 shape-lock snapshot and example registry, extended by every family milestone.
- The M4 event-analysis services and the M5 match-context service, reused by M7.

## Risks

- **Environment:** the model registry and the serving data of record are on Kanav's machine only. On Sven's
  machine every model-backed route returns `model_not_loaded`, and the local DB is an older snapshot
  (191 events; migrations to 0009; no 2025 data). Integration checks on real models and the real examples need
  P7-Q5.
- **Contract coupling:** `test_phase6_contract.py` (route regex and frozen-blob pins),
  `test_api_foundation.py` (exact path list), `test_metrics_docs_contract.py` (documented endpoints and the
  INTERIM caveat), `test_phase5_contract.py` (P5 paths) and `test_frontend_api_contract.py` (`/human-inputs`
  only). Each change is deliberate and recorded.
- **Look-ahead:** the stored `team_metrics` snapshot includes later matches and must never describe a past match
  (pre-match report).
- **Statistical:** no endpoint may relabel an output. Specific traps: M7 failed, P6-M10 G2 failed, PX not run,
  defense/feeding insufficient, and M5 v2 is worse than raw EPA pre-event.
- **Performance:** recommend is 21,952 evaluations per request; event routes build features per team per request
  with no connection pooling.
- **Security:** no auth beyond the Phase 5 write token. CORS allows only GET/POST/OPTIONS.

## Verification strategy

- pytest on an isolated `stratai_test` copy at every gate. Baseline before Phase 7 on this machine:
  2,019 passed, 5 failed, 5 skipped. Four failures are local-data or Windows-path environment issues. One is a
  Phase 5 portability defect (CRLF-computed hashes; see PHASE_STATUS.md), which needs a decision outside Phase 7.
- Bit-identical regression tests wherever a route is consolidated or extracted (M3, M4).
- HTTP-path parity checks for strategy (M5): defects planted in the HTTP layer via dependency overrides, plus
  the unchanged engine-level P6-M13 audit re-run.
- Independent subagent review: security (M5 writes), statistical labelling (M3, M5, M6, M7) and the phase-level
  audit.
- Type check and lint: not configured (P7-A9, P7-Q6).
