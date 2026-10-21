# P9-M7 — Disconnection proof, documentation, audit and acceptance: acceptance record

status: ACCEPTED for the disconnection proof and documentation on local evidence (2026-10-20). **Phase acceptance
is PENDING Sven Morais's decision** (`PHASE_ACCEPTANCE.md`).

| Verification state | Result |
|---|---|
| (a) P9-DM1 proof | `python -m scripts.phase9_zero_llm_audit --routes --disconnection` (`stratai_test`, EPA_SOURCE=statbotics, `as_of` pinned at 2026-06-01): `runs/m1_m7_zero_llm_and_disconnection_rerun2.json`, exit 0, `ok: true` |
| (b) `docs/phase9.md` | Written: the layers, zero-LLM checks, facts, formatter, API, dashboard, cost, contract-test changes, tests |
| (c) Phase-level audit and acceptance proposal | `PHASE_ACCEPTANCE.md` |
| Full suites | Backend: exit 1, 2,697 passed, **5 failed (exactly the 5 baseline tests, 0 regressions)**, 5 skipped, 1 xfailed (`runs/backend_final_p9.txt`). Frontend: vitest 173 passed (exit 0), tsc 0, oxlint 8 baseline warnings, build 0 |

## The disconnection proof

The same 18 output operations are called twice:
- with every LLM SDK and the `briefing` package blocked;
- with the LLM layer enabled, approved and backed by a stub model, and with every credential removed.

The result:
- all 18 answer the same status and the same body, request ids aside;
- **5 are full outputs** (candidates, synergy, pre-match report, strength, metrics);
- 13 are refusals: `model_not_loaded` ×11, `not_approved`, `not_found`. They are the same in both runs, but no model
  output exists locally (P9-R4, P9-R12, P9-R13);
- in the connected run the briefing of 2026mrcmp_qm1 came back in **`mode: llm`**. The whole LLM path ran on a real
  report, and the stub's arrangement passed validation.

**Supporting tests:**
- `tests/test_phase9_briefing_api.py`: the report is byte-identical with the LLM layer off, then used, then off
  again, on a synthetic event with stub engine models (so the model-populated report is covered).
- `judge_disconnection`'s 7 unit tests: the verdict fails on refusals only, on a briefing that is not `llm`, and on
  a missing operation.

**Superseded evidence (kept):** `runs/m7_disconnection_2026mrcmp.json` was the first run. It passed vacuously (no stub,
and the briefing stopped at `no_credential`). Review R2 C5 caught this, and rerun2 replaces it.

## Done-means

- **P9-DM1 (disconnecting the LLM changes nothing except readability): MET locally**, within the limits above. In the
  environment of record, with registered models, rerun `--disconnection` to compare the 11 model-backed successes
  (P9-R13).
- **P9-DM2 (cost per event is known and minimal): NOT MET.** Tokens need a credential (P9-R1), and the figures are
  lower bounds (P9-R11). "Minimal" needs the model decision (P9-Q5).
