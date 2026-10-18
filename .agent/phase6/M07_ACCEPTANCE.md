milestone: P6-M7 Alliance selection engine
status: OPTIMIZATION CORRECTNESS ACCEPTED (synthetic); real outputs need PX probabilities (blocked by P6-M1) and are not_validated until PX-2/PX-4 pass
implementation: ml/playoffs/selection.py SelectionEngine (objective P(win event) via the exact simulator; own later picks optimized by exhaustive nested search; ranked picks with structured reasoning; up to 5 distinct alternatives, never padded)
tests: tests/test_phase6_selection.py (independent brute force equality; not ranking by raw scoring; alternatives; serpentine; declines; unsupported rules refused)
