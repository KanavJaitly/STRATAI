# P10-M0 — decisions (2026-10-20, agent working freeze; Sven Morais's ratification required)

| # | Decision | Why |
|---|---|---|
| P10-Q1 [agent] | **The phase is split into what can be done here and what is blocked** (spec standing rule 1). M1–M3 and M7 proceed. M4–M6 are BLOCKED unless their prerequisites appear | Fabricating backtests, calibration or human spot-checks would breach the done-means and the mandate |
| P10-Q2 [human] | **2022/2023 support for the three-season backtest.** Syncing those seasons, extending the EPA constants and score-breakdown adapters, and choosing a cross-season split is a methodology change | Phase 4 D7/D9 froze the split and seasons; only Kanav/Sven can extend them |
| P10-Q3 [human] | **Models for M4:** use the D18 artifacts (on the Windows machine, environment of record) or retrain | No registry on this machine (P7-Q5) |
| P10-Q4 [human] | **A ruleset reviewer** (P6-M1) for M5, and **a defense/feeding reviewer** plus the defense-definition decision for M6 | Human inputs by design (P6-DM1, P3-M14) |
| P10-Q5 [agent] | **The stress harness uses a disposable empty database** fed with recorded public TBA payloads read from `stratai_test`. It never clones the serving database. Reads of `stratai_test` are read-only | The mandate forbids production data and `phase5_isolated_db` |
| P10-Q6 [agent] | **"Stale data" is measured, not assumed.** After every loading poll, the served views are compared with an independent recomputation from the matches loaded so far | DM3's own words |
| P10-Q7 [agent] | **Hardening fixes are additive.** The body limit is a middleware answering 413 in the error envelope. Timeouts are settings with defaults. Locked shapes are unchanged (R8 is a proposal) | Contract locks (P7-DM2) |
| P10-Q8 [human] | **R8 readiness shape, R9 pooling (new dependency `psycopg_pool`), R12 per-user auth, P8-R4 deployment** are proposals for a human decision | Locked contract, architecture or infrastructure |
