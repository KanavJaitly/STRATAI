# P10-M1 — Platform hardening: acceptance record

**status:** IMPLEMENTED and verified locally (2026-10-21). **Not fully accepted on its own terms:**
- the failing-first evidence is partial (below);
- the 413 declaration on locked operations needs a decision (P10-Q9).

| Verification state | Result |
|---|---|
| Implemented | `api/body_limit.py`, `api/app.py`, `database/connection.py`, `database/readonly.py`, `api/dependencies.py`, `ml/ratings/live_epa.py`, `api/routes/human_inputs.py`, `data/human_inputs.py`, `data/config.py`, `tests/test_phase5_contract.py` |
| Tests | `tests/test_phase10_hardening.py`: 23 tests, 22 pure plus 1 on `stratai_test` (statement timeout); all pass. `tests/test_database_connection.py`: its connect stubs were widened to accept the new `connect_timeout` keyword, with an added assertion that it is passed (2 pass) |
| Reviewed | Review R1 (`reviews/R1_M1_M2_ADVERSARIAL_2026-10-21.md`): F3 (chunked upload 500), F4 (backoff burst and reload), F5 (LRU race) and F13 (DSN options) were all fixed, each with a regression test |
| Contract | `scripts.phase7_contract_lock check` exit 0 (`changed: []`, `added: []`); `phase8_generate_api_types --check` exit 0 |
| Full suite (final, `stratai_test`) | exit 1: 2,750 passed, **4 failed (all from the original baseline 5)**, 5 skipped, 1 xfailed. **0 regressions.** The fifth baseline failure (R16, CRLF hash) is now fixed (`runs/backend_final_p10_m1m2.txt`) |
| Frontend (after M1) | vitest 173 passed (exit 0), tsc 0, oxlint 8 baseline warnings, build 0. No frontend file changed in Phase 10 |

## Against the spec's criteria

**1. "Each fix has a failing-first test": PARTLY MET.** The tests were written together with the fixes, not
recorded failing first. A failure against the pre-fix code is demonstrated for:

| Fix | How the failure is shown |
|---|---|
| R16 | It was a baseline failure |
| Chunked-upload 413 and EPA burst | `runs/p10_r1_prefix_check.txt`: the pre-fix code gives 500 and 10 attempts |
| F1 download header | The old `filename="…"` header raises on `.encode("latin-1")` for a non-latin-1 name, which is what the test asserts |
| The race (R9, P10-M2) | `tests/test_phase10_snapshot.py` reproduces it against the pre-fix path |

**Not demonstrated by a recorded pre-fix run:**
- the declared and streamed JSON body limits;
- the connect and statement timeouts;
- the sequential EPA backoff;
- the LRU bound;
- F2 off the event loop;
- F7.

Each of these tests asserts behaviour that the old code lacked (for example, the old cache dict was unbounded). But
there is no pre-fix run on record, so the criterion is not claimed as met.

**2. "No locked-contract changes": MET for the lock** (the check is clean). **However, a 413 is now served on
locked operations without being declared in OpenAPI** (review F12). Declaring it is a relock: DECISION P10-Q9.

**3. "Full suites show no new failure": MET.** 0 regressions; one baseline failure fixed.

## Scope (f): the portability of `test_m8_future_playoff_sentinel…`

**Investigated, not changed.** It needs:
- the D18 Statbotics snapshot (`C:/Dev/StratAI-artifacts/…`);
- 2026 playoff alliance data from the environment of record.

That is missing data, not a test defect, so the spec's "(f) … where that is a test defect" does not apply. It
stays a baseline failure (CARRIED).

## Not in scope (proposals and decisions)

| Item | Status |
|---|---|
| R8 readiness | Locked shape: a relock needs a decision |
| R9 pooling | P10-D1 |
| R12 auth | A design decision |
