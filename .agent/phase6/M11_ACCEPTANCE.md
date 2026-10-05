milestone: P6-M11 Match strategy optimizer (AI recommendation)
status: ACCEPTED (optimization correctness); its odds carry P6-M10's status (not_validated)
implementation: ml/strategy/engine.py (assess() is the only evaluation path; exhaustive 21,952-strategy search; deterministic ties; maximum-over-candidates caveat; no superiority claims; no best-response)
tests: tests/test_phase6_strategy_engine.py (independent brute force; determinism; bit identity with a fresh evaluation; observations; coach opponent; insufficient data)
