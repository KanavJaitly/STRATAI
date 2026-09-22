Phase 4 — ML Models: Milestone Plan
Phase done means: the win probability model is calibrated (when it says 60%, that alliance historically wins 58–62% of the time across the backtest) and the ranking model beats a naive baseline (e.g., raw EPA ranking) on the held-out season. If it doesn't beat the baseline, iterate before checking the box.
Standing rules carried into Phase 4:
All work is additive — new /ml package. Do not modify Kanav's M3–M10 computation logic without coordination.
No LLM API calls anywhere in the ML core. Models, stats, and optimization only.
Point-in-time correctness is non-negotiable. Only data generated before a match may be used to predict it.
insufficient_data propagates — a missing defense/feeding value is never silently 0.
Every model closes on a "done means" pass condition, not a checkbox.

☐ Milestone 1: Leakage-safe feature assembly layer
What to do
Create the new ml/ package (additive; no changes to existing computation logic).
Implement ml/features/assembler.py: build_match_feature_row(match_key, as_of) returning a per-alliance feature vector using only data with a match number / timestamp strictly before the target match.
Feature sources: Statbotics EPA (total + components), Phase 3 team_metrics (avg, stddev, consistency, reliability), defense/feeding profile where present.
Represent every optional feature with an explicit value plus a presence flag (e.g. defense_score + defense_score_present). Never impute missing values to 0.
Define a Pydantic v2 MatchFeatureRow documenting each feature, its source, and its null semantics.
Success looks like
Features for a given match are reproducible and contain nothing generated at or after that match.
Absent defense/feeding surfaces as present=False, distinguishable from a real low score.
Feature provenance (source + as-of window) is inspectable.
What to test
Point-in-time test: build features for match N; assert no match ≥ N contributed (seeded sentinel event).
Missing-feature test: team with no scouting observations → defense/feeding present=False.
Determinism test: same match_key + as_of → identical row.
Sentinel-collision test: a real feature value equal to the sentinel is still distinguishable via the presence flag.

☐ Milestone 2: Labeled match-outcome dataset builder
What to do
ml/dataset/builder.py: build_training_frame(season_keys) → rows of (red features, blue features, label, meta).
Label: red_win / blue_win / tie; expose score margin as an auxiliary target.
Documented inclusion/exclusion rules for comp level (qual vs playoff), surrogates, replays, DQ / no-show, and unplayed matches.
Attach match timestamp + event week for temporal splitting.
Persist as a versioned artifact (parquet + manifest recording season_keys, row count, code version, build date, content hash).
Success looks like
Every playable, completed match in a synced season appears exactly once with a correct label.
Ties, surrogates, and DQs are handled per documented rules — never silently dropped or mislabeled.
The dataset is regenerable and version-stamped.
What to test
Label-correctness test vs hand-checked matches (include one tie and one DQ).
No-leakage-in-label test: label from final score only; features from before only.
Count reconciliation: rows == completed-playable matches in the seed event.
Idempotency: rebuild → identical manifest hash.

☐ Milestone 3: Temporal backtesting harness + model interface
What to do
Define a Model protocol (fit, predict_win_prob, predict_rating, save, load) so every model plugs in identically.
ml/backtest/harness.py: hold-out-season split + optional within-season walk-forward (train weeks 1..k, test week k+1).
Metrics: accuracy, log-loss, Brier score, ROC-AUC, calibration error (ECE); ranking metrics (Spearman vs final rank, top-8 recall).
Report per-season and aggregate; emit a structured result object + plain-text summary. No LLM calls.
Success looks like
Any conforming model runs through one entry point and gets the same metric suite.
Splits provably respect time order — no future data in any train fold.
This is the single gate everything after Phase 4 validates through.
What to test
Split-integrity test: for every fold, max(train timestamp) < min(test timestamp).
Metric-correctness test: feed known predictions/labels, assert hand-computed Brier / log-loss / ECE.
Protocol-conformance test: a dummy model implementing the interface runs end-to-end.

☐ Milestone 4: Locked naive baselines
What to do
Implement two baselines as first-class models: (a) ranking = raw Statbotics EPA; (b) win prob = logistic on EPA-sum difference (or the standard EPA win-prob formula), symmetric by construction.
Run both through M3 and freeze the held-out numbers as the documented bar every StratAI model must beat.
Log baseline results (dated) in RUNNING_NOTES.md.
Success looks like
A reproducible, dated baseline score exists for both ranking and win prob on the held-out season.
"Beats baseline" is now a concrete number, not a vibe.
What to test
Baseline symmetry test: swapping red/blue gives p → 1−p exactly.
Reproducibility: same seed/data → identical baseline metrics.
Sanity: baseline win-prob is monotonic in EPA difference.

☐ Milestone 5: Team rating / ranking model (XGBoost)
What to do
ml/models/ranking_xgb.py using team_metrics + EPA features (M1) to predict team-strength / final ranking.
Train on ≥2 historical seasons, validate on a held-out season via M3.
Fixed random seed, early stopping on a temporal validation fold, saved feature list + model version.
Gate: must beat the M4 EPA baseline on the held-out season, or iterate before closing.
Success looks like
Held-out ranking beats raw-EPA baseline on the agreed metric (Spearman / top-8 recall).
Training is reproducible from the versioned dataset + seed.
Feature importances are sane — no single leaked feature dominating.
What to test
Beats-baseline assertion in the backtest (milestone is gated on it).
Reproducibility test: retrain → identical metrics.
Label-shuffle leakage smoke test: shuffle labels → performance collapses to chance (catches hidden leakage).

☐ Milestone 6: Win probability model (symmetric by construction)
What to do
ml/models/win_prob.py: two 3-robot alliance feature vectors in → P(red win) out.
Enforce alliance-order antisymmetry structurally (model on red−blue feature differences, or average f(R,B) with 1−f(B,R)) so swapping sides gives exactly complementary probabilities. This is the "unbiased" requirement made mechanical.
Train + backtest through M3; compare vs M4 baseline.
The model sees alliances, not who proposed them — no field encodes "AI strategy" vs "coach strategy."
Success looks like
swap(red, blue) ⇒ p → 1−p to floating-point tolerance, guaranteed rather than merely observed.
Beats or matches baseline log-loss / Brier on the held-out season.
Identical alliances always yield identical probability regardless of caller or context.
What to test
Exact-symmetry test across many random alliances.
Order-independence test: same inputs, different call order → identical output.
No-strategy-leakage test: model input contains no field encoding recommendation source.
Beats-baseline log-loss assertion.

☐ Milestone 7: Probability calibration
What to do
Add a calibration layer (isotonic or Platt) fit on a temporal validation fold — never on the test season.
Produce reliability diagrams + per-bin ECE on the held-out season.
Target the phase done-means: when it says 60%, held-out win rate in that bin is 58–62% (subject to bin sample size).
Success looks like
Reliability diagram near-diagonal on held-out data; ECE below an agreed threshold.
The 60% → 58–62% band holds where bins have enough samples; under-populated bins are reported as such, not hidden.
What to test
Calibration-fit-isolation test: the calibrator never sees test-season data.
Reliability test: computed empirical rate per bin within tolerance on held-out data.
Small-bin honesty test: under-populated bins are flagged, not silently "passing."

☐ Milestone 8: Bias, symmetry & leakage audit
What to do
scripts/ml_bias_audit.py: one command running symmetry, order-invariance, label-shuffle leakage, and as-of-feature checks across ranking + win-prob models.
Confirm no feature encodes match outcome, alliance color as identity, or recommendation source.
Record a dated audit result in RUNNING_NOTES.md (same honesty discipline as M14/M15).
Success looks like
A single command demonstrates the unbiasedness guarantees instead of scattered ad-hoc checks.
Every future model must pass this audit before shipping.
What to test
The audit is the deliverable; add a regression test that fails loudly if any guarantee breaks.
Deliberately-leaky model fixture is caught by the audit (proves the audit has teeth).

☐ Milestone 9: Alliance synergy scoring function
What to do
ml/synergy/score.py: alliance_synergy(team_a, team_b, team_c) → score from a documented weighted combination of role fit, scoring-distribution complementarity, and defense/feeding coverage.
Pure function on team_metrics + model outputs; weights documented and configurable; degrades gracefully when defense/feeding is insufficient_data (uses M1 presence flags).
Explicitly not the pick-list optimizer (that's Phase 6) — this is the scoring primitive it will call.
Success looks like
Deterministic, explainable score an experienced strategist could reconstruct from the docs.
Two high scorers with redundant roles score lower than a complementary pairing — synergy ≠ sum of EPA.
Missing defense/feeding lowers confidence rather than silently zeroing coverage.
What to test
Complementarity test: complementary roles > redundant roles at equal raw scoring.
Determinism + weight-config test.
Insufficient-data test: coverage term reflects absence via presence flag, not 0.

☐ Milestone 10: Model registry, versioning & reproducibility
What to do
ml/registry.py: save/load models with a manifest (model type, version, training-dataset hash, feature list, seed, metrics, date).
Refuse to load a model whose feature list doesn't match the current assembler — this guards the whole 2024↔2026 drift class of silent bugs.
Store artifacts outside the request path; the API loads a pinned version.
Success looks like
Any served prediction traces to an exact model version + training dataset + feature list.
A feature-schema mismatch fails loud at load time, never silently mispredicts.
What to test
Round-trip save/load equivalence (predictions identical).
Mismatch-rejection test: altered feature list → load refused with a clear error.
Manifest-completeness contract test (every field present).

☐ Milestone 11: Cross-season generalization guard
What to do
Encode the 2024 (Crescendo) vs 2026 score_breakdown difference at the feature boundary: season-aware feature adapters, raw-body preservation, and an explicit "unsupported season" error rather than a silent miscompute.
Backtest at least one season the model was not trained on to confirm features resolve and metrics don't collapse.
Add season coverage to the assembler's contract tests.
Success looks like
A new season either produces correct features or a loud, specific failure — never a plausible-but-wrong number.
Held-out-season metrics confirm the model generalizes beyond its training seasons.
What to test
Unsupported-season test: an unseen score_breakdown schema raises a clear error, not a silent 0.
Cross-season feature-parity test: the same logical feature computed correctly under both schemas.
Generalization test: held-out-season metrics above baseline and above chance.

☐ Milestone 12: ML API endpoints
What to do
Extend the Phase 3 api/ package (additive): win probability for a match / for two supplied alliances; team ranking for an event; alliance synergy for three teams.
Read pinned model versions from the registry — no training or heavy recompute in the request path.
Reuse the M12–M13 structured error envelope + distinct outcome codes (model-not-loaded, insufficient features, team/event not found, normal).
Response schemas are Pydantic models that echo model version + calibration status so consumers know what they got.
Success looks like
Endpoints return complete, versioned predictions; degraded inputs return documented codes, not 500s or silent guesses.
No LLM calls anywhere in the path.
What to test
FastAPI TestClient: happy path per endpoint; insufficient-features; unknown team/event; model-not-loaded.
Symmetry-through-API test: swapping alliances flips the probability.
Response schema validated against the canonical models.

☐ Milestone 13: Phase 4 documentation, contract tests & sign-off
What to do
Write docs/ml_models.md: feature list + sources + null semantics, dataset rules, backtest methodology, frozen baseline numbers, each model's algorithm + metrics, calibration approach, unbiasedness guarantees, known limitations, extension guide.
Extend docs contract tests so every documented feature / endpoint / metric matches live code (mirrors M15).
Record a dated human sign-off in RUNNING_NOTES.md: win prob calibrated (60% → 58–62%) and ranking beats baseline on the held-out season — the two done-means conditions, each with the actual numbers.
Success looks like
Phase 4 documented to the Phase 3 standard, enforced by tests rather than trust.
The two done-means pass conditions are recorded with real held-out numbers, or the phase stays open.
What to test
Docs contract tests: documented features / endpoints / constants match live schema and code.
Done-means gate test: the backtest asserts the calibration band and beats-baseline, wired so the box literally can't be checked until both pass.

