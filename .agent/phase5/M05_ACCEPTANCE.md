milestone: P5-M5 Qualification match forecasts and expected qualification records
status: ACCEPTED (done-means met; (b) is a recorded failure of the range, which is served not_validated as the spec prescribes)
record: .agent/phase5/results/p5_m5_qualification_forecast.json (commit 2ebd83a)
files:
  - ml/views/qualification_forecast.py (new): Σ q records, central 80% Poisson-binomial range (gate.py recursion; gate.central_interval's convention at 10%/90%), labels, coverage; RANGE_COVERAGE_VALIDATED pinned to the record (tested)
  - api/routes/qualification_forecast.py (new): GET /events/{event_key}/qualification-forecast (qualification only; M12 gating; per-team record and range labels; low_confidence for Statbotics weeks 1-3)
  - scripts/phase5_m5_qualification_forecast.py (new): one-time (a)/(b)
  - tests/test_qualification_forecast.py (7), tests/test_qualification_forecast_api.py (4)
results:
  population: 12,245 matches, 7,845 team-events (equals the D18 diagnostic population); frozen M7 pair from the registry (sha256 c76d3299...b0a2), never refit
  a_reproduction: EXACT. Mean actual - expected 0.0000 (1.2e-17); mean |actual - expected| 1.1207
  b_range_coverage: 6,693 of 7,845 inside = 0.8532, outside [0.75, 0.85], so the range is labelled not_validated (recorded failure)
decisions: none new. The 80% bounds use gate.central_interval's existing convention (smallest k with CDF >= p) at p = 0.10 / 0.90
interpretation_of_b: coverage above the band means the range is slightly too wide (integer bounds are conservative). No adjustment was made after the result; any change would be a new pre-registered decision
tests: 52 passed (forecast, API foundation); isolated database
bug_hunt:
  - played matches keep their pre-match features (features_as_of = min(as_of, scheduled))
  - expected wins rounded to 1 dp in the API (MAE about 1.1)
  - an unknown Statbotics week gives low_confidence = null, never a guess
known_risks:
  - the frozen M7 limitation is inherited: probabilities are not certified calibrated
done_means: (a) exact; (b) recorded with its label -> MET
