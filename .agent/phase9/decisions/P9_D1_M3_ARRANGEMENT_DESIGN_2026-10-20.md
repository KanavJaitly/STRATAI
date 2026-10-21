# P9-D1 — the LLM formatter arranges facts; it writes no words (2026-10-20, revision 2)

**Status: RATIFIED by Sven Morais on 2026-10-20** (`P9_PHASE_ACCEPTANCE_DECISION_2026-10-20.md`), with the working freeze.
It changes how P9-Q6 is met. It does not change `docs/P9Milestones.md` or `P9_M0_DECISIONS.md`; their blobs are
unchanged (`P9_M0_FREEZE.md`).

**Revision 2 (same day, after review R2):** free lead-ins, even when short and filtered, could slant or invert
the statement after them (review R2 C1: "Read as the blue side's figure:", "Unlikely:", "Strategy for the blue
alliance:" on red's plan). A lead-in is now empty or exactly one of 13 fixed topic labels (`briefing.llm.LEAD_INS`).
None names a side, a team, a quantity or a judgement. Where revision 1 below speaks of lead-ins of up to 12 words
with banned words, read "a label from the closed list". Revision 1's text is kept for the record.

## What changed

**P9-Q6 as frozen:**
- the model writes free sentences, each citing fact ids;
- a fidelity validator checks that every number, team number, percentage and label in a sentence appears in the
  cited facts.

**Why it failed:** review R1 (`reviews/R1_M1_M3_ADVERSARIAL_2026-10-20.md`) showed this cannot be made sound. A value
can be moved to another subject by citing an extra fact. Meaning can be inverted by negation. Content can be
dropped while every id is still cited. Free text has unbounded ways to say what the facts do not say.

**P9-D1:**
- The model returns an **arrangement**. Under each fixed section heading it returns items, and each item is a short
  lead-in plus the ids of the facts it groups.
- The served text of an item is the lead-in followed by **the cited facts' own statements, verbatim**. (Revision 2:
  the lead-in is a fixed label or nothing.)
- Every fact appears exactly once, under its own section.
- A lead-in is at most 12 words of plain letters and simple punctuation, with no digits or codes, and none of the
  banned words. Those cover quantities, outcomes, comparisons, probability, quality and validation claims,
  negation, advice, and the unproduced items.
- All other P9-Q6 rules stand: structured output, no partial acceptance, and the deterministic fallback with its
  reason.

## Why this meets the frozen intent

- **The roadmap:** the LLM is "purely a formatting/explanation layer"; disconnecting it "changes nothing except
  readability" (P9-DM1).
- **Values are bound by construction, not by inspection.** Every value, caveat, label and absence is printed by the
  fact that owns it, beside its own subject.
- **The facts carry their caveats** (review C6): calibration status, validation reasons, the selection note, the
  comparison with the baseline, the sd, and how the moment was chosen. So no arrangement can show a value without
  them.
- **The model never sees the values list** (`facts_payload` sends id, kind, section and statement). It has no
  reason to restate one.

## What it costs (for the ratification)

- **Readability.** The LLM's contribution is limited to grouping, ordering and choosing fixed labels (revision 2). It cannot paraphrase
  a fact into smoother prose, summarise, or explain. A briefing in `llm` mode reads like the deterministic one,
  reorganised. That is a smaller readability gain than free prose.
- **The trade-off is deliberate:** fidelity is the done-means (P9-DM1), and readability is the benefit.
- **The residual** is ordering and emphasis (P9-R6). An arrangement could put a fact first or group facts
  suggestively. It cannot change or drop one.

**Question for Sven (P9-Q14, non-blocking):** ratify P9-D1, or ask for one of these instead:
- (b) free prose under a stronger validator, accepting residual risk;
- (c) LLM-written paraphrases of each fact, each checked by a second, independent model pass. This raises cost
  and still relies on inspection.

The recommendation is to ratify P9-D1: it is the only option whose fidelity is checkable without trusting a model.

## Also recorded here

- **Timeout and retries.** `briefing_timeout_seconds` defaults to 30 (was 60), and the SDK client uses
  `max_retries=1` (was 2). A request-path briefing should fall back quickly; review R1 found that a slow API could
  block a request for 180 s or more.
- **Dependencies.** The SDK is in `requirements-briefing.txt` (optional), never in `requirements.txt` (P9-Q1, M1
  scope (b)).
- **The audit's own file.** `scripts/phase9_zero_llm_audit.py` is in the audit's allowed files: it names every
  forbidden module and host, because it is the list.
