milestone: P6-M9 Strategy representation, coach scenarios and coach observations
status: ACCEPTED
implementation: ml/strategy/representation.py (Strategy with no origin field, extra forbidden; StrategyProvenance stored beside it; CoachObservation structured, timestamped, attributed, no free text); ml/strategy/coach_inputs.py (raw-first, source coach_input; point-in-time loading)
tests: tests/test_phase6_strategy_model.py, tests/test_phase6_coach_inputs.py; extended no-strategy-leakage in the P6-M13 audit (S1)
