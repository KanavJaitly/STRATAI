"""Phase 9: the briefing layer. It turns the P7-M7 pre-match report into a readable briefing.

Downstream only (P9-Q1). This package reads a finished pre-match report and writes text. Nothing in `ml/`, `data/`,
`database/` or the existing API routes imports it, so disconnecting it changes no prediction or recommendation;
`tests/test_phase9_zero_llm.py` checks that.

- `facts`: the report as an ordered list of identified facts, the only content a briefing may state.
- `render`: the deterministic briefing, from fixed templates. It is what is served when the LLM is off, and the
  fallback on every LLM failure (P9-Q7).
- `llm`: the optional LLM formatter, which is fail-closed (P9-M3).
"""
