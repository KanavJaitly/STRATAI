# P9 review R1 — adversarial review of P9-M1 to P9-M3 (2026-10-20)

**Reviewer:** an independent Claude Code subagent, with no part in writing the code. It was told to refute, not
confirm. **Scope:** `briefing/*`, `scripts/phase9_zero_llm_audit.py`, `tests/test_phase9_{zero_llm,briefing,llm}.py`,
`tests/phase9_fixtures.py`.

**Method:**
- It ran the 77 Phase 9 tests on `stratai_test` (exit 0).
- It wrote an attack harness that sends payloads through `make_briefing` with the tests' stub client, plus a planted
  evasive import.
- No network calls, no LLM calls, no access to the serving database. Its scratch files are outside the repository.

**Verdict:** "the phase's main guarantee does not hold": injected or misattributed content could be accepted as
`mode="llm"`. **All findings were accepted.** The fixes are described below and verified by tests.

## Findings and dispositions

| # | Sev. | Finding (abridged from the report) | Disposition |
|---|---|---|---|
| C1 | HIGH | Numbers were checked against the union of every cited fact's values, so citing an extra fact "laundered" a value. Seven attacks were accepted: a value moved to the wrong team; the win probability and the strategy odds swapped or combined; a number given for the unvalidated M6/M7 output; an unproduced item filled in; strategy roles reassigned; match times swapped | **FIXED by redesign** (decision P9-D1). The LLM no longer writes values. Each item it returns is its lead-in followed by the cited facts' statements, verbatim, so a value is only ever printed by its own fact. Regression test: `test_the_review_r1_value_laundering_attacks_cannot_be_expressed` |
| C2 | HIGH | "Every fact cited" did not mean "every fact stated": one empty sentence citing every id was accepted. The `not_produced` and `unvalidated` checks were substring checks, so negations passed | **FIXED.** Statements are printed verbatim, every fact exactly once, under its own section's heading (`wrong_section`, `fact_cited_twice`, `fact_not_cited`). Lead-ins ban negation and validation words |
| C3 | HIGH | Section headings were never validated locally (`"RED WILL WIN 99% - bet on 9901"` was accepted) | **FIXED.** A heading must be from the fixed list, appear at most once, and be in reading order (rule `heading`); tested |
| C4 | MED | Gaps in the word, sign and symbol checks: sign flips, dropped `<`/`>` bounds, values turned into percentages, non-`\d` numerals, missing number words, comparisons, outcome claims outside the regex, absences described as zero, invented capitalised labels, template constants, markup and links | **FIXED.** Lead-ins are at most 12 words / 100 characters of `[A-Za-z ,;:'().-]`, so no digits of any script, no symbols, markup, links or codes. Banned words and stems cover quantities, outcomes, comparisons, probability, quality and validation, negation and contractions, advice, and the unproduced items. Run-together number words and Roman numerals are also banned. Every review example is a test case |
| C5 | MED | Non-object JSON shapes raised `AttributeError`; deep nesting raised `RecursionError`; `content=None` raised `TypeError`, so the route would answer 500 | **FIXED.** The parser checks every shape and key set strictly (`schema`). `RecursionError` maps to `invalid_json`; a missing or non-list `content` maps to `no_text`. Every case is tested |
| C6 | MED | The facts left out caveats the dashboard shows: `calibration_status`, every `validation.reasons`, the strategy `selection_note` and `vs_baseline_label`, `coach_observations_applied`, `as_of_source`, the ± sd | **FIXED** in `briefing/facts.py`. Each caveat is now part of its value's fact (tested: `test_every_caveat_the_dashboard_shows_is_part_of_its_value_fact`) |
| C7 | LOW | Synergy was stated at 2 digits while the dashboard shows 3; `number()` did not group thousands as `toLocaleString` does | **FIXED.** Synergy uses 3 digits, and `number()` groups thousands as en-US Intl does (reference cases added). **Residual:** the dashboard uses the browser's locale and the briefing uses en-US (P9-R9) |
| C8 | MED | The zero-LLM scanner missed `from google import genai`, aliased or computed `import_module`, keyword forms, `exec`, `getattr(importlib, …)`, unlisted SDKs, and raw HTTP to a provider host. The try/except import pattern also defeated the import-time check | **FIXED.** `from x import y` is checked as `x.y`. Any dynamic import or string execution in the core is a violation, literal or not; the core had none. The SDK list is extended, with prefixes. Provider API hosts in strings are flagged. Every evasion is a test case. **Residual:** a static scanner is a guard, not a proof (P9-R10) |
| C9 | LOW | The inventory was a prefix allowlist checked against a hand-written set: it missed `GET /human-inputs/capability-profiles/{profile_key}/recommendation`. M1 scope (b) (no LLM SDK is a core dependency) had no test | **FIXED.** Every served operation is classified (`OPERATION_CLASSES`), and an unclassified one fails. The recommendation route is in the inventory and the route check. `requirements-briefing.txt` holds the SDK; a test checks that `requirements.txt` lists no LLM SDK |
| C10 | LOW | Test quality: the secret test could not fail; the scanner test lacked `from google import genai`; the number test used substring matching; REJECTIONS covered only the listed phrases | **FIXED.** The secret test now goes through the real client path (env credential, SDK class replaced by a recorder) and checks that the key is never passed. Exact token matching. The review's attacks are the rejection cases |

## Unconfirmed concerns

| Concern | Disposition |
|---|---|
| Text before a mid-output `fallback` block could be read | **ADDRESSED.** Only text after the last `fallback` block is read (tested) |
| `usage` covers only the serving attempt under a fallback | **ADDRESSED.** `usage.iterations` is summed when present, with `attempts` (tested); feeds P9-M6 |
| Prompt cache minimum (512 tokens on Opus 5.5) | OPEN until measured with a credential (P9-R1); P9-M6 records the request size |
| Latency: `max_retries=2` with a 60 s timeout | **ADDRESSED.** `MAX_RETRIES = 1`, default timeout 30 s; the dashboard fetches the briefing only on request (P9-R7) |
| `ANTHROPIC_BASE_URL` redirects egress | Recorded under P9-R2 (an environment-controlled destination; part of the egress decision) |

## Verification after the fixes (2026-10-20, isolated `stratai_test`)

| Check | Result |
|---|---|
| `pytest tests/test_phase9_zero_llm.py tests/test_phase9_llm.py tests/test_phase9_briefing.py` | 153 passed, exit 0 |
| With the contract and docs-contract tests | 448 passed, exit 0 |
| `python -m scripts.phase9_zero_llm_audit --routes` (EPA_SOURCE=statbotics) | exit 0. `runs/m1_zero_llm_audit_rerun1.json`: static [], unclassified [], imports 210/210, 18 inventory operations, all OK |
