# P9-M0 — Phase 9 decisions (revision 1, 2026-10-20)

**Status: WORKING FREEZE (agent), not human-approved. To be ratified by Sven Morais.**
- **[agent]** marks an engineering decision taken under Sven's Phase 9/10 execution instruction of 2026-10-20.
- **[human]** marks a decision that needs Sven. It is not decided here, and the build fails closed until it is made.
- A changed decision gets a dated record in `.agent/phase9/decisions/`.

| ID | Decision | Rationale |
|---|---|---|
| P9-Q1 [agent] | **The LLM layer is a separate top-level package `briefing/`.** It is **downstream only**: it imports the report models and functions, and nothing in `ml/`, `data/`, `database/` or the existing API routes imports it. Its one route is `api/routes/briefing.py` | CLAUDE.md: no LLM in the core. A package boundary checked by import-graph tests makes "disconnecting the LLM changes nothing" structural, not just observed |
| P9-Q2 [agent] | **The input is the P7-M7 pre-match report**, built by the same function the report route uses. The briefing never calls an engine directly | P7-M7 was built as the Phase 9 formatter's input. One source of truth means the briefing cannot diverge from the report |
| P9-Q3 [human] | **Sending report contents to a third-party LLM API.** The report holds team-internal data: scouting-derived defense and feeding aggregates, and coach-observation effects on strategy. **Implementation default: OFF.** The LLM is used only when `BRIEFING_LLM_ENABLED=true` **and** `BRIEFING_DATA_EGRESS_APPROVED=true` **and** a credential resolves. Otherwise the deterministic briefing is served | Sending data to an external service publishes it. Whether the team's scouting and coach data may go to the provider is Sven's decision, not an engineering one |
| P9-Q4 [human] | **Provider credential.** No Anthropic credential exists here (no key, no `ant` profile). Live LLM verification and measured token counts are **BLOCKED** until Sven provides one in the environment (never in a file) | An external credential cannot be obtained safely by the agent |
| P9-Q5 [agent; model choice is [human]] | **The provider is Anthropic Claude, through the official `anthropic` Python SDK.** **Default model `claude-opus-5-5`,** configurable through `BRIEFING_MODEL`. P9-DM2 asks for a "minimal" cost, but choosing a cheaper model trades explanation quality for cost, which is Sven's decision. P9-M6 prices Opus 5.5, Sonnet 5.5 and Haiku 5.5 from the same measured token counts so he can choose | The project's existing tooling is Claude. The default model is the current Opus; a downgrade for cost is a product decision |
| P9-Q6 [agent] | **Output is structured.** The model returns sentences, each citing the fact ids it uses. **A fidelity validator** checks every sentence: each number, percentage, team number and label it contains must appear in the cited facts' values. No unproduced item may be described as anything but absent. On any failure the whole briefing falls back to the deterministic one, with the reason. **No partial acceptance** | A formatting layer must not introduce content. Checking claims against the facts is the enforceable form of "purely formatting/explanation" |
| P9-Q7 [agent] | **The deterministic briefing is a first-class output.** The same facts are rendered by fixed templates. It is what "the LLM disconnected" means for readability, and the fallback on every failure | P9-DM1: disconnecting the LLM may change readability only, so a readable non-LLM briefing must exist |
| P9-Q8 [agent] | **New operation `GET /matches/{match_key}/briefing`**, added to the contract lock with `scripts.phase7_contract_lock lock` (adds operations only; refuses any change to a locked entry). No existing locked shape changes | P7-DM2 forbids changing existing shapes after frontend work; the lock tool's documented rule permits adding a new operation with a reason |
| P9-Q9 [agent] | **Cost per event is measured, not guessed.** Input tokens come from the API's `count_tokens` (never an offline tokenizer). Output is taken as the observed usage, bounded by `max_tokens`. Prices come from a dated, recorded table: the claude-api reference, cached 2026-10-06, with Opus 5.5 at $4/$20, Sonnet 5.5 at $2/$10 and Haiku 5.5 at $0.10/$0.50 per million input/output tokens. Without a credential, token counts stay **unmeasured** | P9-DM2 says "known". An invented token count would be a fabricated result |
| P9-Q10 [agent] | **Prompt caching.** The system prompt (rules plus fact vocabulary) is frozen and byte-stable, with `cache_control` on it. Per-match facts follow it. No timestamps or ids go in the system prompt | The same prefix for every match in an event is what makes caching pay. A volatile prefix silently disables it |
| P9-Q11 [agent] | **Secrets and logging.** The key comes only from the SDK's credential chain (`ANTHROPIC_API_KEY` and others). It is never put in Settings dumps, logs, responses or evidence. Only the model id, token usage and the fallback reason are recorded | The standing secret rules |
| P9-Q12 [agent] | **The dashboard shows the briefing labelled by mode,** in its own section of the report page. It never replaces served values, labels or absences | Phase 8 display rules (P8-Q4/Q5) |
| P9-Q13 [agent] | **Verification states** are kept separate (spec), and P9-DM2 is not claimed while tokens are unmeasured | Honest acceptance |

## Human decision points

1. **P9-Q3:** approve or refuse sending report contents (including scouting and coach-derived data) to the LLM
   provider. Until approved, only the deterministic briefing is served.
2. **P9-Q4:** provide an Anthropic credential in the environment for the live verification and the cost measurement.
3. **P9-Q5:** the model for production briefings. The default is `claude-opus-5-5`; the cost table in P9-M6 informs
   the choice.
4. **Ratification** of this working freeze and of the phase at acceptance.
