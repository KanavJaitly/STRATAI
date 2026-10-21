# P9-M3 — LLM formatter (fail-closed): acceptance record

status: ACCEPTED on stubbed evidence (2026-10-20), under decision P9-D1 revision 2 (ratification PENDING, P9-Q14); **the live call is BLOCKED** (no credential, P9-R1)

| Verification state | Result |
|---|---|
| Implemented | `briefing/llm.py` (the arrangement design with the closed label list, P9-D1 revision 2), settings in `data/config.py` |
| Tested with a stubbed SDK (no network) | `tests/test_phase9_llm.py`, all passing among the 200 pure P9 tests: gates; request shape; the credential never leaking (through the real client path); faithful arrangements; every listed label accepted; structure rejections; 33 free-text lead attacks from R1 and R2, each tried in every section; an adversarial laundering case; 18 malformed-output and failure paths (huge integer, duplicate keys); fallback blocks and usage; real SDK error classes |
| Live call | BLOCKED: no credential (P9-R1). Not verified against the real API |
| Reviewed | Review R1 broke the frozen design (free text plus validator); review R2 broke filtered free lead-ins (C1) and found a crash path (C2). Both are fixed (P9-D1 revision 2) and retested. An end-to-end stubbed run on a real 2026mrcmp report passed validation (`mode: llm`, disconnection rerun2) |
| Accepted | YES for the stubbed scope; the live scope is BLOCKED |

## Deviation from the frozen M3 scope
- **"Structured output (sentences, each citing fact ids)" is now an arrangement** (items of lead-in plus fact ids, with statements printed verbatim). See P9-D1.
- **"Every number … must appear in the facts it cites"** now holds by construction: the model writes no value.
- **The acceptance cases** (invented numbers, teams, probabilities or filled-in absences rejected) are met more strongly: none can be expressed. Each attempt is a test.
