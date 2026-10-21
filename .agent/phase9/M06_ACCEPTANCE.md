# P9-M6 — Cost per event: acceptance record

status: **BLOCKED** for tokens and cost (no credential, P9-R1); the tool is ACCEPTED, and sizes are measured

| Verification state | Result |
|---|---|
| Implemented | `scripts/phase9_briefing_cost.py`; `tests/test_phase9_cost.py` (4 passed): the reference output is a valid arrangement; no tokens without a credential; the arithmetic, against hand-worked figures. Per-model cache-read rates (Opus 5.5: 0.05×). Three figures, all marked lower bounds: thinking, schema and fallbacks are uncounted (review R2 C7 fixed) |
| Run (`stratai_test`, EPA_SOURCE=statbotics) | Final: `runs/m6_briefing_cost_2026mrcmp_rerun1.json`. 40 of 132 qualification matches (seed 9), 52 s, none refused. System prompt 1,387 B; schema 926 B; facts message median 11,979 B (11,692–13,296); reference output median 2,187 B; 55–58 facts. The first run (`m6_briefing_cost_2026mrcmp.json`, before the final prompt and facts) is kept |
| Tokens, cost per event | **BLOCKED** (no credential). No count is invented or estimated in their place |
| Accepted | The acceptance criterion's "Without: BLOCKED, with no invented token count" is MET. The "With a credential" half is not met |

**P9-DM2 ("cost per event is known and minimal") is NOT MET.** It needs:
1. a credential (P9-R1);
2. `--measure`;
3. a judgement of "minimal" against the measured cost, with the model choice (P9-Q5).

Caching may not apply (P9-R11).
