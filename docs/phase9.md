# Phase 9 — LLM Report Layer

Phase 9 confirms that every prediction, ranking, strategy and pick list works with no LLM involvement. It then adds
an optional language-model layer that only makes the pre-match report easier to read.

- **Spec:** `docs/P9Milestones.md` (revision 1, a working freeze pending Sven Morais's ratification), with
  `.agent/phase9/P9_M0_DECISIONS.md`.
- **Changes after the freeze:** `.agent/phase9/decisions/`.
- **Status and acceptance:** `.agent/phase9/PHASE_STATUS.md`.

## The rule

The engines (`ml/`, `data/`, the API routes that serve them) never call an LLM (CLAUDE.md, critical constraints). The
LLM layer is downstream of the pre-match report only.

| Layer | What it may do | Where |
|---|---|---|
| Engines | Predict, rate, rank, recommend. No LLM import, no dynamic import, no provider host | `ml/`, `data/`, `database/`, `api/` (except the briefing route), `automation/`, `scripts/` |
| Briefing facts | Turn the served report into identified facts, each with its caveats, in fixed wording | `briefing/facts.py` |
| Deterministic briefing | Print every fact under fixed headings. Always available | `briefing/render.py` |
| LLM formatter | Group and order the facts, and label an item from a fixed list. **It never writes a word** | `briefing/llm.py` |
| Briefing API | `GET /matches/{match_key}/briefing` | `api/routes/briefing.py` |
| Dashboard | A "Readable briefing" panel on the report page, labelled by mode, fetched on request | `frontend/src/dashboard/briefing.tsx` |

## Zero-LLM verification (P9-M1)

`python -m scripts.phase9_zero_llm_audit [--routes] [--disconnection] [--event 2026mrcmp] [--out FILE]`

1. **Static.** No core module may:
   - import an LLM SDK or the `briefing` package, including `from google import genai` as `google.genai`;
   - import dynamically or execute strings (`import_module`, `__import__`, `exec`, `eval`, `compile`);
   - name a provider's API host.
2. **Import-time.** In an interpreter where every LLM SDK and `briefing` are unimportable:
   - all 210 core modules import;
   - the API builds with 46 operations, which is all of them except the briefing.
3. **Runtime (`--routes`).** In that blocked interpreter, every output operation is called on an isolated
   `stratai_test*` database. Each must answer 200 or a refusal it declares.
4. **Disconnection (`--disconnection`, P9-DM1).** The same calls are made twice: once with the LLM layer blocked,
   once with it enabled and approved. Status and body must match; `as_of` is pinned and request ids are ignored.

Every served operation is classified in `OPERATION_CLASSES` as output, LLM layer, or not an output. A new operation
fails the tests until it is classified. The LLM SDK is listed only in `requirements-briefing.txt`;
`requirements.txt` must list none (tested).

## Facts and the deterministic briefing (P9-M2)

`briefing.facts.report_facts(report)` returns the report as an ordered list of `Fact`s. Each fact has:
- an id;
- a kind: `context`, `value`, `absence`, `not_produced` or `label`;
- a section;
- a fixed-wording statement;
- its values;
- the JSON path of its source field.

The rules:
- **Numbers read exactly as the dashboard shows them.** This is the en-US `Intl` rounding: 1 decimal, 2 for the
  0-5 scouting scale, 3 for synergy, thousands grouped, ± sd where one is served.
- **Every caveat the dashboard shows travels with its value.** That covers labels, `validation.reasons`, the
  calibration status (`m7_gate_failed`), the strategy's selection note and its comparison with the baseline, coach
  observations applied, and how the moment was chosen.
- **An unvalidated M6/M7 output is stated as existing and unvalidated; its number is never stated.**
- **Absences keep their reason codes.** The six unproduced items are `not_produced` facts with their meaning.
  Nothing fills them (P7-Q12, P8-Q6).

`briefing.render.deterministic_briefing(facts)` prints each statement under its section heading. The same facts give
the same bytes.

## The LLM formatter (P9-M3, decision P9-D1)

The model receives a frozen system prompt and the facts (id, kind, section, statement). It returns an
arrangement:

```json
{"sections": [{"heading": "Red alliance", "items": [{"lead": "Team record:", "fact_ids": ["red.9901.epa.total", "..."]}]}]}
```

**The served text of an item is its label followed by the cited facts' statements, verbatim.** The validator
rejects the whole arrangement, and the deterministic briefing is served with the reason, unless:
- the shape is exact, with no duplicate JSON keys;
- headings come from the fixed list, appear once each, and are in reading order;
- every fact is cited exactly once, under its own section's heading;
- every label is empty or one of `LEAD_INS`: "Match details:", "The alliances:", "Team record:",
  "EPA by phase:", "Scoring record:", "Scouting ratings:", "Qualifiers:", "Alliance synergy:", "Model forecast:",
  "Strategy:", "Coach observations:", "Unproduced items:", "Sources:".

None of the labels names a side, a team, a quantity or a judgement. Free lead-ins were tried first. Review R2 showed
that even short, filtered ones can slant or invert the statement after them ("Read as the blue side's figure:",
"Unlikely:"). So the model writes no words at all (decision P9-D1).

**The gates, in order:**
1. `BRIEFING_LLM_ENABLED`, default false;
2. `BRIEFING_DATA_EGRESS_APPROVED`, default false: a human decision, P9-Q3;
3. a credential the Anthropic SDK can resolve: never a setting, and never logged (P9-Q11);
4. the SDK installed (`requirements-briefing.txt`).

**Model and request:** `BRIEFING_MODEL` (default `claude-opus-5-5`; the choice is a human decision, P9-Q5). The
request uses:
- structured output (`output_config.format`, a JSON schema);
- server-side refusal fallbacks (`server-side-fallback-2026-07-01`, `fallbacks="default"`);
- `BRIEFING_TIMEOUT_SECONDS` (default 30) and one retry.

Usage is summed over `usage.iterations` when a fallback ran.

**Fallback reasons:** `disabled`, `egress_not_approved`, `no_credential`, `sdk_unavailable`, `api_error:<class>`,
`refusal`, `truncated`, `no_text`, `invalid_json`, `validation_failed:<rule>`.

## Endpoints owned by Phase 9

| Operation | Milestone |
|---|---|
| `GET /matches/{match_key}/briefing` | P9-M4 (P9-Q8), locked additively on 2026-10-20 |

## The API (P9-M4)

`GET /matches/{match_key}/briefing?as_of=…` builds the pre-match report through the report route's own handler, so
the moment, the engines and the refusals are the report's. It returns:
- `mode`, `fallback_reason`, `model` and `usage`;
- the sections, each with `fact_ids` per sentence;
- the facts, with their source paths;
- a disclaimer.

The operation is in the contract lock, added with no change to any locked entry (`docs/api_contract_lock.json`).
The app builds without the `briefing` package; the route is then absent and every other route is unchanged.

## The dashboard (P9-M5)

The report page has a "Readable briefing" panel:
- It is fetched only when asked for, because it rebuilds the whole report.
- It is requested with the report's own `as_of` parameter. If the moment it was taken at differs from the report's
  (a "now" report, then a later click), the panel says so.
- It is labelled "arranged by a language model" (with the model) or "fixed layout". The fixed layout gives the
  reason in words and as a code, and says whether a model was called (and its arrangement rejected) or not called
  at all.
- It renders text as text.

## Cost per event (P9-M6)

`python -m scripts.phase9_briefing_cost --event 2026mrcmp [--limit 40] [--measure] [--out FILE]` builds the requests
for a seeded sample of matches and measures their sizes.

- **Tokens:** with `--measure` and a credential, `count_tokens` (free) counts them for each priced model.
- **Without a credential, tokens and cost are BLOCKED; nothing is estimated in their place.**
- **Prices:** the claude-api skill table, cached 2026-10-06 (USD per million tokens, input / output):
  - Opus 5.5: 4 / 20;
  - Sonnet 5.5: 2 / 10;
  - Haiku 5.5: 0.10 / 0.50.
- **Cache multipliers:** cache writes 1.25×, cache reads 0.1×.

Measured on 2026-10-20 (`.agent/phase9/runs/m6_briefing_cost_2026mrcmp_rerun1.json`, 40 of 132 qualification
matches, seed 9, models not loaded, final prompt):

| Part | Size |
|---|---|
| System prompt | 1,387 bytes |
| Output schema | 926 bytes |
| Facts message | median 11,979 bytes (11,692 to 13,296) |
| Reference output | median 2,187 bytes |
| Facts per report | 55 to 58 |

The system prompt is small. It may be below the model's 512-token minimum cacheable prefix, in which case nothing is
cached. The tool reports three costs: cache warm, every call writing the cache, and no caching.

**All three are lower bounds on output.** Thinking tokens (always on for Opus 5.5) bill as output and are visible only
in a real call's `usage`. The structured-output schema and refusal-fallback attempts are not counted either.

## Running it

```sh
# core (no LLM)
pip install -r requirements.txt
# optional LLM layer
pip install -r requirements-briefing.txt
export BRIEFING_LLM_ENABLED=true BRIEFING_DATA_EGRESS_APPROVED=true   # only after the P9-Q3 decision
# plus a credential in the SDK's chain (for example ANTHROPIC_API_KEY in the environment; never in .env committed)
```

## Contract-test changes

Each one is a deliberate, recorded addition for the new operation, made the way earlier phases added theirs.

| Date | Test | Change | Why |
|---|---|---|---|
| 2026-10-20 | `tests/test_api_foundation.py::test_exactly_the_intended_endpoints_are_exposed` | `PHASE9_PATHS` (the briefing) joins the pinned set | The pin's purpose: a reviewed addition |
| 2026-10-20 | `tests/test_metrics_docs_contract.py` (documented endpoints; the INTERIM caveat) | Phase 9's endpoints are read from this page's "Endpoints owned by Phase 9" section and excluded, like Phase 7's | The briefing serves no `ScoringProfile`. Its reliability fact states the INTERIM caveat in words (tested in `tests/test_phase9_briefing.py`) |
| 2026-10-20 | `tests/test_phase7_examples.py` | The P7-M8 examples scope is 23, not 22. The plan template gains the briefing's two real examples, mirroring the report's | P7-Q4 requires examples for every locked operation, and the briefing is locked |
| 2026-10-20 | `docs/phase7.md` lock table | One row for the briefing | `tests/test_phase7_contract.py` requires every locked operation to be documented there |

## Tests

| File | What |
|---|---|
| `tests/test_phase9_zero_llm.py` | Scanner (including review R1's evasions), import-time check, operation classification, requirements |
| `tests/test_phase9_briefing.py` | Facts: sources, numbers (Intl parity), caveats, absences, unproduced items, deterministic bytes |
| `tests/test_phase9_llm.py` | Gates, request shape, the credential never leaks, arrangement rules, review R1's attacks, malformed output, fallback blocks and usage |
| `tests/test_phase9_briefing_api.py` | The route on `stratai_test`: modes, refusals equal the report's, and the report is unchanged when the LLM layer is used |
| `tests/test_phase9_cost.py` | The reference output is a valid arrangement; no tokens without a credential; the cost arithmetic |
| `frontend/src/dashboard/briefing.test.tsx` | Lazy fetch at the report's moment, mode labels, text not HTML, refusals, axe |
