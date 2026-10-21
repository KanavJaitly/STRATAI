# Phase 10 — human decisions (Sven Morais, 2026-10-21)

Recorded from Sven Morais's instruction of 2026-10-21.

| Item | Decision | Conditions as given |
|---|---|---|
| **P10-D1** (connection reuse) | **Option B selected: one database connection per request, with no new dependency.** This authorises a **controlled implementation experiment, not unconditional acceptance** | No sharing of connections across requests or threads. No `psycopg_pool` and no other dependency. Transaction semantics, `read_snapshot` consistency, timeouts, rollback, exception cleanup and the connection lifecycle are preserved. B is kept **only if** it meets the acceptance criteria of P10-D1 §5 with no correctness or reliability regression; otherwise A is restored, without discarding unrelated work. Criteria are not weakened. VM-suspended runs are kept separate |
| **P10-Q9** (413 in the contract) | **Approved: declare HTTP 413 in the API contract.** Make the smallest justified change that documents the actual 413 on the affected endpoints | Update the lock and the types only through the prescribed workflow. Change no unrelated contract behaviour; weaken no lock check |
| **Phase 10 spec** | **Ratified without changing its acceptance criteria:** `docs/P10Milestones.md` revision 1 and `.agent/phase10/P10_M0_DECISIONS.md` (blobs `8bb7dddd…`, `601c3175…`, unchanged) | — |

## Statuses to keep, as evidenced

- **M1:** implemented, not fully accepted (failing-first evidence only partly recorded).
- **M2:** meets its six criteria on local evidence.
- **P10-DM3:** met for the local setup only.
- **M3:** profiling complete; the optimisation experiment is still to be evaluated.
- **M4–M6:** blocked on their documented prerequisites.
- **Backend suite:** exits 1 with 4 identified baseline failures and 0 identified regressions. It is not called passing.
