# P9-M1 — Zero-LLM verification: acceptance record

status: ACCEPTED on local evidence (2026-10-20); environment of record BLOCKED for model-backed success paths (P9-R4)

| Verification state | Result |
|---|---|
| Implemented | `scripts/phase9_zero_llm_audit.py`, `tests/test_phase9_zero_llm.py`, `requirements-briefing.txt` |
| Tested | All pass, among the 200 pure P9 tests. The scanner catches planted violations and every review R1 and R2 evasion (31 cases). Only the app may import the briefing route. The blocker blocks, name prefixes included. The core requirements list no LLM SDK. Every served operation is classified. The disconnection verdict cannot pass vacuously (7 cases) |
| Runtime (`--routes`, `stratai_test`, EPA_SOURCE=statbotics) | Final: `runs/m1_m7_zero_llm_and_disconnection_rerun2.json`. Exit 0; static []; unclassified []; 210/210 core modules import with every LLM SDK blocked; the app builds (46 operations, all but the briefing); 18 output operations all OK. Earlier runs are kept: `m1_zero_llm_audit.json`, `m1_zero_llm_audit_rerun1.json` |
| Reviewed | Review R1 C8 and C9, review R2 C5, C6 and C9: all FIXED and retested. The static scan remains a guard, not a proof (P9-R10) |
| Accepted | YES, for local evidence |

## Acceptance criteria
- **Inventory complete against OpenAPI.** MET. Every operation is classified (`OPERATION_CLASSES`): 18 outputs, 1 LLM layer, 28 not outputs. An unclassified one fails a test. This adds the P5-M9 recommendation, which the first, prefix-based inventory missed.
- **Guard tests fail on a planted violation.** MET (planted static, dynamic and try/except forms).
- **The runtime check passes.** MET, with these limits:
  - **Exercised with full 200 bodies (5):** candidates, synergy, pre-match report, strength, metrics.
  - **Refusals:** the 11 model-backed operations refuse with `model_not_loaded`, because no models are registered (P9-R4). The pick list refuses with `not_approved` (P6-DM1). The recommendation refuses with `not_found`, because there is no stored profile (P9-R12).
  - **Coverage of those paths:** the import-block and static checks cover their code, but their success paths did not run.
