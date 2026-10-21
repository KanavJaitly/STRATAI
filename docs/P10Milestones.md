# Phase 10 — Polish, Backtesting and Hardening: milestones (revision 1, 2026-10-20)

**Status: WORKING FREEZE by Claude Code, 2026-10-20.** It was written under Sven Morais's instruction of 2026-10-20 to
execute Phases 9 and 10, after he authorised Phase 10 (`.agent/phase9/decisions/P9_PHASE_ACCEPTANCE_DECISION_2026-10-20.md`).
**It is not human-approved.**
- Ratification by Sven Morais is required.
- Decisions: `.agent/phase10/P10_M0_DECISIONS.md`. Integrity: `.agent/phase10/P10_M0_FREEZE.md`.
- Any change after the freeze needs a dated decision in `.agent/phase10/decisions/`.

**Source:** `docs/ROADMAP.md`, Phase 10 (immutable). This file was empty before revision 1.

## Phase 10 scope and done-means (from `docs/ROADMAP.md`, immutable)

> Run the full backtesting suite against the 2022, 2023, and 2024 seasons. Re-validate win probability calibration
> across all three. Re-validate alliance selection against real playoff outcomes. Re-validate defense/feeding metrics
> against manual scouting spot-checks. Stress-test real-time sync under simulated live-event match load. Fix anything
> wrong or biased before calling it launch-ready.
>
> Done means: all three seasons backtest cleanly, calibration holds across seasons (not just one), and the system
> survives a simulated event without stale data or crashes.

- **P10-DM1:** all three seasons backtest cleanly.
- **P10-DM2:** calibration holds across seasons.
- **P10-DM3:** the system survives a simulated event without stale data or crashes.

## Binding inputs from earlier phases

- **Phase 7 risks deferred to Phase 10** (`.agent/phase7/PHASE_ACCEPTANCE.md`):
  - R6: no request-body limit;
  - R7: no DB timeouts, and a failed EPA load is retried on every request;
  - R8: readiness ignores model and EPA state;
  - R9: no pooling and per-team connections;
  - R10: an unbounded live-EPA cache;
  - R11: the human-input defects F1, F2 and F7;
  - R12: one shared write token, no rate limits;
  - R16: the CRLF evidence hash.
- **Phase 8:**
  - P8-R4: deployment;
  - P8-R5: slow routes;
  - P8-R6: re-carries the Phase 7 risks above.
- **Phase 9:** P9-R7 (briefing latency).
- **Phase 4 D18 results:** win-probability calibration (P4-M7) FAILED its G2 gate on 2026, and playoffs are
  miscalibrated. **A failed gate is not re-run to obtain a pass** (Phase 4 D9).
- **Phase 6:** P6-DM1 is NOT MET. The rulesets await a named, qualified reviewer, and the PX gates have never run.
- **Phase 3 M14:** defense was signed off on 2026mrcmp. Feeding cannot be validated: no feeding field exists. The
  defense definition is an open product decision.
- **CLAUDE.md:**
  - every verification run must finish within about 45 minutes;
  - DB-backed tests run only on `stratai_test*`;
  - never weaken the guard.

## Standing rules (every milestone)

1. **Nothing is re-validated by assumption.** A milestone that needs data, models or a human that are absent is
   **BLOCKED**, with the exact prerequisite named. No substitute result is produced.
2. **Write paths use disposable databases only** (`stratai_test_p10_*`, created empty and migrated, then dropped).
   Never the serving database, and never `scripts/phase5_isolated_db.py`, which clones the serving database.
3. **Locked API contracts:** no locked entry changes without a dated decision by Sven Morais. Additive, unlocked
   changes are allowed.
4. **No frozen methodology changes** (seasons, splits, gates) without a dated human decision.
5. **No new runtime dependency or architectural change** (for example a connection pool) without approval, per
   CLAUDE.md. Such changes are proposed.

## Milestones

### P10-M0 — Specification, decisions and baseline
| | |
|---|---|
| **Acceptance** | Every roadmap clause and every inherited Phase 10 obligation maps to a milestone or a recorded disposition. The baseline is recorded |

### P10-M1 — Platform hardening (self-contained fixes)
| | |
|---|---|
| **Scope** | (a) R6: a request-body size limit for every route (413, in the error envelope), sized for the largest legitimate body. (b) R7: DB `connect_timeout` and `statement_timeout` (settings with safe defaults), and a backoff on a failed EPA-source load. (c) R10: bound the live-EPA snapshot cache. (d) R11: F1, a safe `Content-Disposition` for any filename; F2, no blocking body read on the event loop; F7, no server path in error messages. (e) R16: the evidence hash over normalized line endings (baseline failure `test_p5_d3_adoption_record…`). (f) The portability of baseline failure `test_m8_future_playoff_sentinel…` (a hard-coded Windows path), where that is a test defect rather than missing data |
| **Acceptance** | Each fix has a failing-first test. There are no locked-contract changes (an added error status on an unlocked route is fine). Full suites show no new failure |
| **Not in scope (proposals only)** | R8 readiness (its shape is locked: a relock needs Sven's decision). R9 pooling (a new dependency and an architectural change). R12 auth (a design decision) |

### P10-M2 — Live-sync stress harness and simulated event (P10-DM3)
| | |
|---|---|
| **Scope** | A harness on a **disposable, empty, migrated** database. It replays one event's recorded TBA match results in schedule order through the production sync path (`data.orchestrator`'s load path, with HTTP replaced by the existing replay client), at a configurable compressed rate. Concurrently, API readers load the event's served views (strength, metrics, event analysis, pre-match report, briefing). Recorded payloads come from `stratai_test` (public TBA data in the sanctioned test copy), never the serving database |
| **Acceptance** | No 5xx and no crash. **No stale data:** after each poll that loads results, the served team metrics and strength reflect exactly the matches loaded so far, checked against an independent recomputation. No look-ahead. Latency is recorded under load. The run stays within the time budget. The disposable DB is dropped afterwards |

### P10-M3 — Performance measurement
| | |
|---|---|
| **Scope** | Measure route latencies (P8-R5, P9-R7) locally under the M2 load and alone. Fix self-contained hot spots that need no new dependency or architecture. Propose pooling and caching (R9) with measurements |
| **Acceptance** | Measurements recorded. Any fix is regression-tested. Proposals are recorded for a human decision |

### P10-M4 — Three-season backtest and cross-season calibration (P10-DM1, P10-DM2)
| | |
|---|---|
| **Scope** | Run the backtesting suite for 2022, 2023 and 2024, and re-validate calibration in each |
| **Prerequisites** | (1) 2022 and 2023 TBA and Statbotics data synced (absent everywhere). (2) Season support for 2022 and 2023 in the EPA constants, the score-breakdown adapters and the snapshot. That is a methodology extension needing a Kanav/Sven decision. (3) Trained, registered models, or an approved retraining plan; none are on this machine. (4) A decision on the cross-season split, because the frozen harness holds out only the last season (Phase 4 D7/D9) |
| **Acceptance** | Real per-season metrics and gate results, or BLOCKED with every prerequisite named. Calibration failures are reported, never re-run to a pass |

### P10-M5 — Alliance selection against real playoff outcomes
| | |
|---|---|
| **Prerequisites** | P6-M1 ruleset approval by a named, qualified FRC reviewer; the PX-1/PX-2/PX-4 runs and artifact hashes; `event_alliances` and `event_ranking` data |
| **Acceptance** | A real comparison, or BLOCKED with the prerequisites named |

### P10-M6 — Defense and feeding against manual scouting spot-checks
| | |
|---|---|
| **Prerequisites** | A human reviewer who watched the matches. For feeding: scouting data with a feeding-quality field. The defense-definition decision |
| **Acceptance** | A recorded human spot-check, or BLOCKED with the prerequisites named. The tooling (`scripts/metrics_spot_check.py`) is checked to still run |

### P10-M7 — Documentation, phase audit, acceptance and final remediation plan
| | |
|---|---|
| **Scope** | `docs/phase10.md`, the phase-level audit, the acceptance proposal, and the prioritized final remediation plan. That plan covers the deferred Phase 8 and 9 items, the baseline failures, the environment of record, deployment, and the application-completion gaps |
| **Acceptance** | Done-means evaluated honestly. Full suites run, with baseline failures named. Human acceptance stays PENDING |

## Order and dependencies

M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7.
- M4–M6 are expected to be BLOCKED here; their records name the prerequisites.
- M3 uses M2's load.
