milestone: P6-M2 PX-1 playoff match model
status: IMPLEMENTED; NOT RUN -- blocked by P6-M1 (bracket round comes from the approved slot mapping)
spec: .agent/phase6/P6_M2_PX1_SPEC.md (frozen at 27dd14a, before any playoff data was assembled)
implementation: ml/playoffs/px1.py (regularized logistic, C=1.0, no intercept; seed difference, M6 composition-sum differences, round interactions; RMS scaling; absent columns dropped and recorded, never imputed; antisymmetric by construction); ml/playoffs/data.py; scripts/phase6_playoff_track.py m2 (gate P6-Q3 vs M6/M7-on-playoffs and seed-only, paired event-bootstrap CIs)
tests: tests/test_phase6_px1.py (antisymmetry <= 1e-12, determinism, design rules, insufficient_data) -- SYNTHETIC
