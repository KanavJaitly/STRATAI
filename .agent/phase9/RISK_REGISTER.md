# Phase 9 — risk and dependency register

**Status values:** OPEN, MITIGATED (with residual), CLOSED (with evidence), or CARRIED (named target phase or the
final remediation pass).

| # | Risk / dependency | Owner | Impact | Disposition |
|---|---|---|---|---|
| P9-R1 | **No LLM credential** (P9-Q4) | Sven | The live LLM briefing and the measured token cost cannot be verified. **P9-DM2 cannot be met** | OPEN, blocked on Sven. The code fails closed (`no_credential`) |
| P9-R2 | **Data egress to the LLM provider** (P9-Q3): the report holds scouting-derived and coach-derived data | Sven | Sending it publishes team-internal data to a third party. The destination is environment-controlled (`ANTHROPIC_BASE_URL` redirects it; review R1) | OPEN, a human decision. The default is OFF (`briefing_data_egress_approved=false`), so the deterministic briefing is served. The approval should name the destination |
| P9-R3 | **Model choice versus "minimal" cost** (P9-Q5). The default is `claude-opus-5-5` | Sven | Cost per event depends on the model | OPEN. P9-M6 prices three models from the same measured token counts once a credential exists |
| P9-R4 | **No trained models locally** (inherited from P8-R1 and P7-Q5). The model-backed routes refuse with `model_not_loaded` | Sven / Kanav | The zero-LLM runtime check executes only the non-model routes. For model-backed routes the evidence is static (the import scan plus the blocked import check). The LLM briefing has only been tested on synthetic model-populated reports | CARRIED to the final remediation pass (the environment of record) |
| P9-R5 | **Frontend test reliability on slow or cold runs** (P8-R14). On 2026-10-20, 2 of 7 full runs failed, both cold starts (88 s against about 30 s), on the axe-heavy ReportPage test's 15 s timeout | Phase 8 follow-up | Intermittent false failures | CARRIED to final remediation. Re-runs pass |
| P9-R6 | **Arrangement and emphasis.** Since P9-D1 (revision 2) the LLM writes no words: statements are verbatim, every fact appears once in its own section, and a label is one of 13 fixed topic labels. Review R1 broke the free-text validator; review R2 broke filtered free lead-ins; both are closed. The model still chooses grouping, order and labels | Phase 9 | An arrangement could put one fact first or group facts suggestively; it cannot change, drop or add one | MITIGATED (P9-D1). The residual needs a human review of real outputs once a credential exists (P9-R1). Ratifying P9-D1 is P9-Q14 |
| P9-R7 | **Briefing latency and cost.** A briefing builds the full pre-match report, which runs about two strategy recommendations | Phase 10 | Slow briefings; doubled work if the report and the briefing are both requested | MITIGATED: the dashboard fetches the briefing only on request; the LLM call has a 30 s timeout and 1 retry (P9-D1). Report-build performance is CARRIED to Phase 10 (with P8-R5) |
| P9-R8 | **`requirements.txt` does not list `scipy`,** which `ml/` imports (pre-existing, found at baseline) | Final remediation | A fresh environment could fail to import `ml` | CARRIED to final remediation; not changed silently in Phase 9 |
| P9-R9 | **Number locale.** The dashboard formats with the browser's locale (`toLocaleString(undefined, …)`); the briefing uses en-US. A non-en-US browser shows "1.234,5" where the briefing says "1,234.5" (review R1, C7) | Final remediation | The same value looks different on the two surfaces outside en-US | OPEN, LOW. Values below 1,000 with the same decimal separator are identical. Either pin the dashboard to en-US or pass the locale |
| P9-R10 | **The zero-LLM scanner is a guard, not a proof.** It catches the import forms, dynamic code and provider hosts it knows (including review R1's evasions); a determined author could still evade a static scan | Phase 9 / code review | An LLM call slipped into the core | MITIGATED: static scan, import-time block, runtime route check, disconnection comparison, and code review. CLAUDE.md's constraint remains a review obligation |
| P9-R11 | **The prompt cache may never apply, and the cost figures are lower bounds.** The system prompt is 1,387 bytes, probably below the 512-token minimum cacheable prefix. Thinking tokens (always on for Opus 5.5) bill as output and are uncountable without a real call; the schema and fallback attempts are not counted either (review R2 C7) | Phase 9 (needs a credential) | Every briefing may pay full input price, plus unmeasured thinking output | OPEN until measured (P9-R1). The cost tool reports cache warm, every call writing the cache, and no caching, each marked `lower_bound`. A real call's `usage` gives the thinking tokens. Padding the prompt to reach the minimum would be decided from measured cost, not assumed |
| P9-R12 | **The P5-M9 recommendation was exercised only to its refusal** in the runtime and disconnection checks: `stratai_test` has no capability profile | Final remediation | Its success path is checked statically (scan and import block), not at runtime | OPEN, LOW. A disposable profile on a test copy would close it |
| P9-R13 | **The model-backed outputs are compared only as refusals** in the disconnection check (no models, P9-R4). The success-path equality of the report with the LLM layer used is tested on synthetic stub models (`tests/test_phase9_briefing_api.py`) | Final remediation (environment of record) | P9-DM1 is verified locally on: 5 full real outputs; 13 refusals; the stub-model report; and an end-to-end stubbed LLM run on a real report (review R2 C5 fixed) | CARRIED with P9-R4: rerun `--disconnection` where models are registered |

## Carried from Phase 8 (unchanged by Phase 9 unless noted)

| Phase 8 risk | Disposition in Phase 9 |
|---|---|
| P8-R2: six report items unproduced (DM2 deferred; P8-D3 proposed) | Still OPEN. **The briefing must never fill them.** This is enforced by the validator rule `not_produced_described`, and the deterministic briefing states them as absences |
| P8-R3: alliance selection is refusal-only | Still OPEN (P6-DM1). Pick-list facts are not part of the report |
| P8-R4: deployment | CARRIED to Phase 10 / final remediation |
| P8-R5: slow routes | CARRIED to Phase 10 |
| P8-R6: Phase 7 hardening (R6–R12) | CARRIED to **Phase 10**, which owns platform hardening |
| P8-R10: smoke request bodies are a copy | CARRIED to final remediation |
| P8-R11 (residual): model-populated print | CARRIED to final remediation (needs P9-R4) |
| P8-R14 | Becomes P9-R5 |
| P8-R15: duplicated loading and error code | CARRIED to final remediation |
