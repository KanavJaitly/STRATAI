# P9 review R2 — adversarial review of the redesign and of P9-M4 to P9-M7 (2026-10-20)

**Reviewer:** a second independent Claude Code subagent, told to refute.

**Constraints it worked under:**
- no database connection, because the full suite was running;
- no network and no LLM call;
- no repository edits. Its scratch harnesses are outside the repository.

**Verdict:** claims 1, 2, 3, 4 and 6 were refuted in part, and claim 5 held only on "never invents tokens".
**Every finding was accepted.** The fixes are listed below and verified by tests and by rerun evidence.

| # | Sev. | Finding (abridged) | Disposition |
|---|---|---|---|
| C1 | HIGH | **The filtered free-text lead-ins were still served while slanting or inverting the fact after them.** Prefixed forms ("Unlikely", "Uncalibrated", "Untrustworthy") passed, as did unlisted words ("dominant", "Victorious", "Lopsided"), dismissals ("Fabricated", "Obsolete"), and joins onto the next statement ("The opposite holds for", "Read as the blue side's figure:"). Numbers were smuggled as words ("Team twofivefour", "Team xxv", "Zwei, drei"), and a strategy was misattributed by side ("Strategy for the blue alliance:" on red's plan). All of these were served in `llm` mode | **FIXED by revising P9-D1:** a lead-in must be empty or exactly one of 13 fixed topic labels (`LEAD_INS`). None names a side, a team, a quantity or a judgement. The model writes no words. Every R1 and R2 lead attack is a test case (`LEAD_ATTACKS`), tried in every section, and each is rejected (`lead_not_allowed`) |
| C2 | MED | **A JSON integer over the 4,300-digit limit raised `ValueError` (a 500).** Duplicate keys were accepted | **FIXED.** `ValueError` and `RecursionError` from parsing map to `invalid_json`. Duplicate keys are refused (`schema`). Both are tested |
| C3 | MED | **Percentages used Python's half-to-even `round`; the dashboard uses `Math.round`** (0.125 gave 12% against 13%). Also, `number()` raised for values of 1e27 and above | **FIXED.** `percent()` is `floor(p*100 + 0.5)`, with the Node references as tests. `number()` quantizes with a 400-digit context (tested at 1e27 and 1.5e300) |
| C4 | MED | **Caveats missing from the facts:** a baseline-only side's `unavailable_reasons`; the unvalidated output's label, qualifiers, calibration status and scope; the EPA label and source; the scoring label; scout agreement; synergy confidence; the components of defenders and feeders. A scoring robot with no components rendered as "scoring ()" | **FIXED.** Each is in its fact, in the dashboard's terms: a `labels` fact per team; agreement in the scouting facts; confidence in synergy; "scores in …" for every role; "scoring (none)"; the baseline-only reasons; the full unvalidated caveats. Each is tested |
| C5 | HIGH | **The disconnection proof was largely vacuous.** 13 of 18 operations were refusals and nothing required a real output. The LLM path never ran (no stub). The briefing's outcome was ignored. A credential in the environment would have caused a real API call | **FIXED.** The connected run injects a stub model and removes every `ANTHROPIC_*` variable, pointing the config dir at nothing. `judge_disconnection` requires: the same operations; equal status and body; at least one 2xx output compared; and the briefing back in `llm` mode. It has 7 unit tests, including the vacuous cases. The rerun (`runs/m1_m7_zero_llm_and_disconnection_rerun2.json`) passes: 18 equal, 5 of them full outputs, and the LLM path ran end to end on a real 2026mrcmp report (`mode: llm`). **Residual:** the 13 model-backed refusals can only be compared as refusals here (P9-R13) |
| C6 | MED | **New scanner evasions:** re-export through the allowed route; `spec_from_file_location`/`exec_module`, `runpy`, `pkgutil.resolve_name`, `pydoc.locate`, `getattr(builtins, …)`; unlisted SDKs; the import blocker ignored name prefixes | **FIXED.** `api.routes.briefing` is forbidden to every core module except `api/app.py`'s optional router (`ALLOWED_IMPORTS`). The loader names and `getattr` on loader modules are flagged. 15 more SDKs are listed. The blocker covers the prefixes. Every case is tested. **Residual:** run-time-built hosts and `subprocess python -m` remain outside a static scan (P9-R10) |
| C7 | MED | **Cost tool.** Opus 5.5 cache reads are 0.05×, not 0.1×. Thinking tokens, the schema and fallback attempts are not counted. The "no cache hits" figure was not an upper bound. The prefix may be below the 512-token cache minimum | **FIXED.** Cache-read rates are per model. There are three figures: cache warm, every call writes, no caching. Everything is marked `lower_bound`, with the uncounted parts listed. The arithmetic is tested against hand-worked figures. The 512 minimum is in P9-R11 |
| C8 | LOW–MED | **Mode wording and moment.** "No language model was used" appeared even when a model was called and rejected. The intro said "it adds nothing" in `llm` mode. The panel passed the report's resolved `as_of`, so the briefing said "the requested moment" where the report said "now" | **FIXED.** The wording now distinguishes a model that was called (and rejected) from one that was never called. The intro is accurate. The panel passes the page's own `as_of` parameter, so the moment is chosen the same way as the report's, and it says so if the moments differ. All tested |
| C9 | MED | **Tests that could not fail:** the laundering test, a mislabelled "outcome without keywords" case, the tautological cost test, and no test of `disconnection_check` | **FIXED:** an adversarial laundering test, `LEAD_ATTACKS`, the hand-worked cost test, and the `judge_disconnection` tests |

## Unconfirmed concerns

| Concern | Disposition |
|---|---|
| The token size of the cached prefix compared with the 512 minimum | OPEN, P9-R11: it needs `count_tokens` (P9-R1). The prompt is now 1,387 bytes |
| Whether the server-side fallback model honours `output_config.format` | OPEN. Fail-closed parsing makes any unconstrained output a fallback, never a 500 (C2 fixed) |

## Verification after the fixes (2026-10-20, `stratai_test`)

| Check | Result |
|---|---|
| The four pure P9 test files | 200 passed, exit 0 |
| DB-backed briefing API, contract, docs-contract and the five regressed pins | 398 passed, 1 xfailed (the strict P7-M8 one), exit 0 |
| Types and lock | `--check` 0; lock `check` 0 |
| Frontend | vitest 173 passed (29 files), tsc 0, oxlint 8 (baseline), build 0 |
| Zero-LLM and disconnection rerun | exit 0, `ok: true` (above) |
| Cost rerun | `runs/m6_briefing_cost_2026mrcmp_rerun1.json`: sizes measured; tokens BLOCKED |
