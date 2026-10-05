milestone: P6-M4 PX-3 bracket and series simulator
status: IMPLEMENTATION CORRECTNESS ACCEPTED (synthetic); the criterion 'bracket graph equals P6-M1's reproduced structure' is BLOCKED by P6-M1
implementation: ml/playoffs/simulator.py (exact path enumeration; vectorized production version, 1.9 ms per 8-alliance double elimination; independent recursive exact version; seeded Monte Carlo oracle)
tests: tests/test_phase6_simulator.py (distributions sum to 1; closed form; series probability; exact == Monte Carlo within 5 SE; vectorized == recursive within 1e-12; relabelling; round reaches the probability function; invalid graphs refused)
