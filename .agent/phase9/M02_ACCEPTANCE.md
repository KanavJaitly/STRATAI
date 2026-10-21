# P9-M2 — Briefing facts and the deterministic briefing: acceptance record

status: ACCEPTED on local evidence (2026-10-20)

| Verification state | Result |
|---|---|
| Implemented | `briefing/facts.py`, `briefing/render.py` |
| Tested (synthetic) | `tests/test_phase9_briefing.py`: 48 passed. Every fact traces to a real field; every section is covered; numbers match Intl en-US (28 reference cases from Node 24); every caveat is in its value's fact; absences keep their reasons, never 0; the unproduced items carry no value; an unvalidated M6/M7 value is never stated; the output is byte-stable |
| Live local reports | 40 real 2026mrcmp reports (`stratai_test`, EPA_SOURCE=statbotics) were turned into facts with no error by the cost tool (`runs/m6_briefing_cost_2026mrcmp.json`: 55–58 facts each). The disconnection run served the deterministic briefing of 2026mrcmp_qm1 |
| Reviewed | Review R1 found C6 (missing caveats) and C7 (synergy precision, grouping): FIXED. The locale residual is P9-R9 |
| Accepted | YES |
