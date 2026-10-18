milestone: P6-M10 Strategy-conditional outcome model
status: IMPLEMENTED AND EVALUATED -- GATE FAILED (D9); baseline odds served not_validated (p6_m10_gate_failed)
spec: .agent/phase6/P6_M10_MODEL_SPEC.md (frozen at 48ac1ea, before the fit)
fit: .agent/phase6/results/p6_m10_fit.json (15,956 2024-2025 matches; beta auto 0.741 teleop 0.950 endgame 0.885; sigma 0.899); registry strategy_outcome_component/p6m10-v1 sha256 aded2c829a1f...
evaluation: .agent/phase6/results/p6_m10_outcome_model.json (12,215 held-out 2026 EPA-complete qualification matches; G1 0.0266 pass, G2 FAIL 4/10 bins under-confident, G3 pass, G4 pass; reported paired log-loss vs M6/M7 -0.0384, CI -0.0613..-0.0170)
failure_record: .agent/phase6/P6_M10_FAILURE.md
note: the run-1 P6-M13 fix (math.fsum) changes served probabilities by at most a few ULP; the recorded evaluation is kept as computed
