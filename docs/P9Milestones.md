# Phase 9 — LLM Report Layer: milestones (revision 1, 2026-10-20)

**Status: WORKING FREEZE by Claude Code, 2026-10-20**, under Sven Morais's instruction of 2026-10-20 to execute
Phases 9 and 10. It is **not human-approved**: Sven Morais must ratify it. Decisions are in
`.agent/phase9/P9_M0_DECISIONS.md`, and integrity in `.agent/phase9/P9_M0_FREEZE.md`. Any change after the freeze
needs a dated decision in `.agent/phase9/decisions/`.

**Source:** `docs/ROADMAP.md`, Phase 9 (immutable). This file was empty before revision 1.

## Phase 9 scope and done-means (from `docs/ROADMAP.md`, immutable)

> Confirm every prediction, ranking, strategy, and pick list works with zero LLM involvement. Then wire up an LLM
> API purely as a formatting/explanation layer that turns the engines' structured outputs into readable pre-match
> briefings. Estimate token cost per event.

- **P9-DM1:** disconnecting the LLM entirely changes nothing except report readability. No prediction or
  recommendation is affected.
- **P9-DM2:** the cost per event is known and minimal.

## Binding inputs from earlier phases

- **CLAUDE.md critical constraints.** The core engine makes **no LLM API calls**: ML, statistics and optimization
  only. An LLM is allowed only for natural-language report generation and explanations.
- **P6/P7 rule.** An LLM may only format or explain finished outputs, and only in Phase 9 (`docs/P6Milestones.md`).
- **The input.** The P7-M7 pre-match report (`GET /matches/{m}/pre-match-report`) is "one structured aggregate per
  match that a Phase 8 report or Phase 9 LLM formatter can render without calling the engines again". Its modules
  import no LLM or HTTP client (tested).
- **P7-Q12 and P8-Q6.** The six unproduced report items stay explicit absences. **The LLM layer must never fill
  them, paraphrase them into content, or add any analysis that no engine produced.**
- **P7-DM2 and the contract lock.** No change to an existing locked shape. New operations are added only through
  `scripts/phase7_contract_lock lock`, which adds operations and nothing else.
- **Phase 8.** The dashboard reads only locked operations (`tests/test_phase8_frontend_contract.py`). Probabilities
  and labels are shown as served.

## Standing rules (every milestone)

- **Downstream only.** The LLM layer reads the finished report and writes text. Nothing in `ml/`, `data/`,
  `database/` or the existing API routes imports it or any LLM SDK, and this is tested.
- **No invented content.**
  - Every number, team, label and probability in a briefing must come from the report.
  - Absences are stated as absences.
  - The LLM output is validated against the facts it was given. Anything unverifiable is rejected, and the
    deterministic briefing is served instead.
- **Fail closed.** With the LLM disabled, unconfigured, unapproved, failing or rejected, the briefing is the
  deterministic rendering of the same facts. No prediction path ever waits on or reads the LLM.
- **Data egress is a human decision.** Sending report contents to a third-party LLM API is off by default. It needs
  a configured credential **and** an explicit approval setting (P9-Q3).
- **Secrets.** The API key comes only from the environment or the SDK's credential chain. It is never logged,
  stored, served or committed.
- **Verification states** are kept separate: implemented; tested with stubs/fixtures; verified against the local
  API; verified with the live LLM (needs a credential); verified in the environment of record; accepted.

## Milestones

### P9-M0 — Specification and decisions
| | |
|---|---|
| **Objective** | This file, `P9_M0_DECISIONS.md` and a working freeze, plus the verified baseline |
| **Acceptance** | Every roadmap clause maps to a milestone, human-decision items are listed, and the baseline is recorded |

### P9-M1 — Zero-LLM verification
| | |
|---|---|
| **Scope** | (a) An inventory of every prediction, ranking, strategy and pick-list path (engine function, API route, dashboard view). (b) Guard tests: no module under `ml/`, `data/`, `database/` or `api/` (except the P9 briefing module and its route) imports an LLM SDK or the briefing package; no LLM SDK is a dependency of the core. (c) A runtime check: every inventoried route answers with the LLM package unavailable |
| **Acceptance** | The inventory is complete against the API's OpenAPI operations. The guard tests fail when a violation is planted. The runtime check passes |

### P9-M2 — Briefing facts and the deterministic briefing
| | |
|---|---|
| **Scope** | (a) `facts`: a pure extraction of an ordered, identified list of facts from a pre-match report. Each fact carries its values, label, absence code and source path. (b) A deterministic plain-language renderer of those facts: the briefing when the LLM is off. Absences and the six unproduced items are stated explicitly |
| **Acceptance** | Every fact traces to a report field, and every report section is covered. No value appears that is not in the report. Rendering is deterministic (same input, same bytes). Tests use synthetic report fixtures and a live local report |

### P9-M3 — LLM formatter (fail-closed)
| | |
|---|---|
| **Scope** | (a) A configuration: enabled flag, data-egress approval flag, model, timeouts; the credential from the SDK's chain. (b) A formatter using the official Anthropic Python SDK: a frozen system prompt, the facts as the only input, and structured output (sentences, each citing fact ids). (c) A fidelity validator: every number, team number, percentage and label in each sentence must appear in the facts it cites, and no unproduced item may be described as anything but absent. (d) A fallback to the deterministic briefing on any disabled, unapproved, missing-credential, API-error, refusal, truncation or validation-failure state, with the reason recorded |
| **Acceptance** | With the SDK stubbed (no network): valid output is accepted, and invented numbers, teams, probabilities or filled-in absences are rejected (each case tested). Every failure path falls back. The key never appears in logs or responses (tested). The live call is verified only with a credential (otherwise BLOCKED) |

### P9-M4 — Briefing API
| | |
|---|---|
| **Scope** | `GET /matches/{match_key}/briefing?as_of=` returns the briefing (mode `llm` or `deterministic`, the fallback reason, sentences with their cited facts, the model, token usage when present). It is built from the same report function, so no engine runs differently. The operation is added to the contract lock through `lock` (additive). Documentation |
| **Acceptance** | Contract and lock tests pass, and no existing locked entry changes. The report and every engine response are identical with the briefing enabled or disabled (tested) |

### P9-M5 — Dashboard briefing panel
| | |
|---|---|
| **Scope** | The pre-match report page shows the briefing in its own section, labelled with its mode (an LLM-written explanation of the engines' outputs, or a deterministic summary). It never replaces or alters the served values, labels and absences |
| **Acceptance** | Tests for both modes and for an unavailable briefing; axe checks; the print layout keeps the briefing |

### P9-M6 — Cost per event
| | |
|---|---|
| **Scope** | A tool that builds every briefing request for an event and measures its input tokens with the API's token counter (`count_tokens`), adds output tokens from the response limit and observed usage, and prices them from a recorded, dated price table. Without a credential it reports the request sizes and states the tokens as **unmeasured** |
| **Acceptance** | With a credential: tokens per briefing and per event are measured and priced for the configured model and the alternatives. Without: BLOCKED, with no invented token count |

### P9-M7 — Disconnection proof, documentation, audit and acceptance
| | |
|---|---|
| **Scope** | (a) A proof of P9-DM1: with the LLM enabled (stubbed) and disabled, every prediction, ranking, strategy and pick-list response is identical, and only the briefing text differs. (b) `docs/phase9.md`. (c) The phase-level audit and the acceptance proposal |
| **Acceptance** | P9-DM1 and P9-DM2 are evaluated honestly. The full suites are run, with baseline failures named. Human acceptance stays PENDING |

## Order and dependencies
M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. M3 needs M2's facts, M4 needs M3, M5 needs M4, and M6 needs M3 and M4.
