Phase: 4

Current Milestone: M04 (M05, M06, M07 also code-complete; M08, M09, M10, M12 ACCEPTED — see below; M11 deferred, see below)

Status: IN_PROGRESS — M04/M05/M06/M07 code complete, real-number freezes still blocked on Statbotics. M08/M09/M10/M12 fully accepted (none needed real data). M11 deferred (no real work to guard yet).

Current Stage: Phase H — regression verification complete; awaiting external dependency to close M04's (and M05's, M06's, M07's) acceptance gate

Completed (pre-Phase-Execution-Mode, recorded in RUNNING_NOTES.md only):
- M01 ACCEPTED (2026-09-21)
- M02 ACCEPTED (2026-09-24)

Accepted (this phase execution, full artifact in .agent/phase4/):
- M03 ACCEPTED (see M03_ACCEPTANCE.md)
- M08 ACCEPTED (see M08_ACCEPTANCE.md) — built out of numeric order,
  dependency-independent progress while M04-M07 sit blocked on Statbotics;
  its own acceptance criteria need no real data at all.
- M09 ACCEPTED (see M09_ACCEPTANCE.md) — same rationale as M08; a pure
  scoring function with no real-data dependency.
- M10 ACCEPTED (see M10_ACCEPTANCE.md) — same rationale; registry
  mechanics need no real backtest numbers, only real model artifacts
  (which M5/M6 already produce).
- M12 ACCEPTED (see M12_ACCEPTANCE.md) — same rationale; the API layer's
  own wiring/error-handling is fully testable against synthetic-fixture
  registered models. No model is actually pinned in the real deployed
  Settings yet (both version-tag settings default to None), so in
  production /predictions/* correctly answers model_not_loaded until a
  real M4-M7 model is accepted and registered -- that is this milestone
  working as designed, not a gap.

Deferred (found not to have real scope yet, human-confirmed):
- M11 (cross-season generalization guard): nothing in this codebase's
  data/ or ml/ packages reads score_breakdown at all (confirmed by direct
  grep, not assumed) -- there is no existing consumer for "season-aware
  feature adapters" to adapt. Building the guard now would be speculative
  structure with no consumer, the same anti-pattern already rejected once
  this phase (M1's discarded schema-only draft). Human confirmed: skip to
  M12/M13 for now, revisit M11 if/when a feature that reads score_breakdown
  is actually added.

Progress this session (2026-09-24/25), all real, none fabricated:
- Database blocker fully resolved (see prior status entries).
- TBA-only sync (--no-statbotics) of full seasons 2024, 2025, 2026 complete:
  190/190, 203/203, 215/215 events, 0 errors.
- `ml/models/baselines.py`: both M4 baselines built (RawEpaRankingBaseline,
  EpaWinProbBaseline — genuine fit single-parameter logistic, no invented
  "standard Statbotics formula"), 24 tests, all synthetic and labeled as
  such, covering the milestone's 3 named tests + missing-EPA handling.
- `scripts/run_m4_baseline_backtest.py`: the real-backtest runner, not yet
  executed against real data (blocked on Statbotics — see below). Its own
  unit test caught and fixed a real bug (an empty alliance silently passing
  an EPA-completeness check).
- **Ranking-ground-truth gap CLOSED**, independent of the Statbotics outage:
  confirmed TBA's own /event/{event_key}/rankings is a real, separate
  endpoint (verified against TBA's live OpenAPI spec) with no dependency on
  Statbotics. Built `data/rankings.py` (sync_event_rankings,
  sync_season_rankings, read_final_ranks_for_season) plus
  TBAClient.fetch_event_rankings and EventRankings/TeamRanking schemas.
  **Ranking sync now complete and verified**: all 608 events across
  2024/2025/2026 (190+203+215) landed a ranking payload, 0 failures. All 16
  tests pass, including all 6 requires_db integration tests run for real
  against the live database (previously written but unrun). This resolves
  the gap PHASE_PLAN.md flagged during M03 for both M04's ranking baseline
  and M05's entire success criterion.
- **Concurrency artifact confirmed, not a code defect.** The earlier
  spurious failure (test_raw_writer_statbotics.py::
  test_integration_cleanup_deletes_only_its_own_sentinel) was root-caused to
  running the full pytest suite concurrently with the season sync, both
  writing to the same live database. A clean, fully isolated full-suite run
  (no other background DB writer active, verified via process check first)
  now passes completely: **1043 passed, 0 failed, 0 skipped, 2 warnings**
  (unrelated FastAPI/Starlette test-client deprecation notices), 375.79s.
  This is the trustworthy regression baseline for everything built so far
  in Phase 4 (M1-M3 plus the M4/ranking work above).
- **M05 (ranking model) built ahead of M04's freeze**, dependency-independent
  progress while genuinely blocked on Statbotics, per explicit instruction.
  `ml/models/ranking_xgb.py`'s `RankingXGBModel` (XGBoost regressor,
  `Model`-protocol conformant). Real architectural ambiguity surfaced and
  put to the human rather than guessed: M3's already-accepted `fit()`
  signature has no access to real final ranks (those are `run_ranking_
  backtest`-only), so there is no direct label to train a ranking regressor
  against. Human chose a signed per-team-appearance margin-contribution
  target (direction from `label`, magnitude from `score_margin`) over an
  XGBRanker pairwise formulation or holding M5 until Statbotics recovers.
  Missing features are `float("nan")`, handled by XGBoost's own native
  missing-value learning, not manually imputed. Saved feature list checked
  on load (refuses a schema mismatch), anticipating M10's own registry
  guarantee. 27 tests, all synthetic and labeled as such, including the
  milestone's own named label-shuffle leakage smoke test. Full suite now
  **1070 passed, 0 failed, 0 skipped**, isolated, zero regressions.
- **M06 (win-probability model) also built ahead of M04's freeze**, same
  dependency-independent-progress rationale as M05. `ml/models/win_prob.py`'s
  `WinProbXGBModel` (XGBoost binary classifier over concatenated
  red/blue alliance vectors, `Model`-protocol conformant). Symmetry
  (swap(red,blue) => p -> 1-p) is enforced *structurally*, not just
  observed: p(R,B) = (raw(R,B) + (1-raw(B,R))) / 2, which algebraically
  forces p(R,B)+p(B,R)=1 for ANY underlying predictor, including an
  arbitrary tree ensemble that is not itself an odd function of a feature
  difference (a raw-difference-input approach, the milestone's other
  offered option, was considered and rejected for exactly this reason: it
  would only make symmetry empirical, not guaranteed, for a boosted-tree
  model). `ml/models/team_vector.py` split out of `ranking_xgb.py` so both
  M5 and M6 share one team-vector construction rather than duplicating it.
  Alliance-level features are summed across rostered teams (mirroring
  `_alliance_epa_sum`'s existing precedent); any one team missing a given
  feature makes that alliance-level feature NaN via plain floating-point
  NaN propagation, per-feature not blanket. No-strategy-leakage is checked
  structurally against the real `TeamFeatures`/`MatchFeatureRow` schemas
  (no field name contains "strategy"/"recommendation"/"coach"/etc.), not by
  convention. 21 new tests plus 5 for the shared `team_vector` module,
  including the milestone's three own named tests (exact symmetry across
  25 random alliance pairs, order-independence, no-strategy-leakage) and a
  fully-missing-features case that must give exactly 0.5. Full suite now
  **1096 passed, 0 failed, 0 skipped**, isolated, zero regressions.
- **M07 (probability calibration) also built ahead of M04's freeze**, same
  dependency-independent-progress rationale. `ml/calibration/calibrator.py`:
  `IsotonicCalibrator`/`PlattCalibrator` (both wrapping scikit-learn's own
  implementations, newly added dependency, already listed in CLAUDE.md's
  tech stack), `compute_reliability_bins`/`check_calibration_band` (the
  milestone's own named "small-bin honesty" — an under-populated or empty
  bin reports `within_band=None`, never a silently-passing boolean), and
  `fit_calibrated_win_prob_model`/`apply_calibrated_model` — the workflow
  that structurally keeps the calibrator's own fitting data disjoint from
  both the underlying model's training rows AND the held-out test season
  (a temporal split carved from one Fold's own `train_rows` only; the
  fold's separate `test_rows` is never passed to the fitting function at
  all). 29 new tests, including a `_RecordingCalibrator` test double that
  directly proves calibration-fit isolation (which exact raw-probability/
  label pairs the calibrator saw) rather than only inferring it from
  timestamps, and an end-to-end exercise showing a deliberately
  miscalibrated fixed-output model's ECE strictly improves after isotonic
  calibration on a fresh evaluation slice. `scikit-learn` added to
  `requirements.txt`. Full suite now **1125 passed, 0 failed, 0 skipped**,
  isolated, zero regressions.
- **M08 (bias/symmetry/leakage audit) — ACCEPTED IN FULL**, see
  `M08_ACCEPTANCE.md`. `scripts/ml_bias_audit.py`: one command running
  symmetry, order-invariance, no-strategy-leakage, as-of-feature integrity,
  and label-shuffle leakage checks against the real M5/M6 models. Unlike
  M04-M07, this milestone's own acceptance criteria need no real data at
  all — verified against the real models (all 7 checks PASS) AND against
  two deliberately-broken fixture models (`_ConstantAsymmetricWinProbModel`,
  `_ConstantRatingModel`), each shown to fail the specific check it
  violates, proving the audit has teeth per its own named requirement.
  16 new tests. Full suite now **1141 passed, 0 failed, 0 skipped**,
  isolated, zero regressions.
- **M09 (alliance synergy scoring) — ACCEPTED IN FULL**, see
  `M09_ACCEPTANCE.md`. `ml/synergy/score.py`'s `alliance_synergy()`: since
  no "role" field exists anywhere in this codebase's schema, "role fit" and
  "scoring-distribution complementarity" are computed as unit-free share
  vectors (each team's value on one axis / the alliance's total on that
  axis), scored via `1 - mean pairwise cosine similarity`. **This design
  point was escalated to the human before implementation** (a genuine
  domain/strategy question, not just engineering) — human confirmed the
  implicit-role-vector approach over a fixed archetype rubric or deferring
  the milestone. Three non-redundant components (role_fit,
  scoring_distribution over EPA phases, defense/feeding coverage), weighted
  and configurable, renormalized over whichever components have real data.
  13 tests, including the milestone's own named complementarity test (two
  alliances with identical alliance-total average_score, the complementary
  one scores strictly higher) and insufficient-data honesty (missing
  defense/feeding lowers confidence, never zero-fills the term). Full
  suite now **1154 passed, 0 failed, 0 skipped**, isolated, zero
  regressions.
- **M10 (model registry, versioning & reproducibility) — ACCEPTED IN
  FULL**, see `M10_ACCEPTANCE.md`. `ml/registry.py`: `register_model`/
  `load_registered_model`/`list_registered_versions`, write-once storage
  per (model_type, version_tag), `ModelManifest` carrying model
  type/version/registry version/training-dataset hash/feature list/seed/
  metrics/creation timestamp. The registry's own feature-list guard is
  independent of (defense in depth alongside) each model class's own
  internal check. 13 tests, including two end-to-end tests against the
  real `RankingXGBModel` — a genuine fit-register-reload round trip, and a
  simulated feature-list drift (the milestone's own named "2024<->2026
  drift" scenario) correctly refused at load time. Full suite now
  **1167 passed, 0 failed, 0 skipped**, isolated, zero regressions.
- **M12 (ML API endpoints) — ACCEPTED IN FULL**, see `M12_ACCEPTANCE.md`.
  Four endpoints (`api/routes/predictions.py`): match-based and ad-hoc
  win probability, event team ranking, alliance synergy. Loads pinned
  models once at startup (`api/ml_loading.py`) via M10's registry; new
  Settings fields `ml_registry_dir`/`ml_ranking_model_version_tag`/
  `ml_win_prob_model_version_tag` (both version tags default to None --
  this project's honest current state). Found and fixed a real bug during
  testing: `model_not_loaded` initially used a 503, which this codebase's
  own established error-handling rule silently strips custom codes from
  at >=500 -- fixed to 404, matching the existing `metrics_not_computed`
  precedent exactly. `ml.features.assembler._build_team_features` promoted
  to public `build_team_features` (no behavior change) since the ranking
  and synergy endpoints both need one team's own point-in-time snapshot
  outside a specific match's context. New small additive module
  `ml/features/roster.py` for event/team/match lookups the API layer
  needs, deliberately NOT reusing Phase 3's own private equivalent. 18 new
  tests, including the milestone's own named symmetry-through-API test
  (the real HTTP round trip, not just the model object) and full coverage
  of model-not-loaded/insufficient-features/unknown-team-or-event across
  all four endpoints. Two pre-existing Phase 3 docs-contract tests fixed
  (scoped to exclude the new `/predictions/*` paths, which belong to a
  future `docs/ml_models.md`, not `docs/metrics_pipeline.md`). Full suite
  now **1185 passed, 0 failed, 0 skipped**, isolated, zero regressions.

Blocked, unchanged:
- Statbotics still returning HTTP 500, rechecked directly again this
  session against the *exact* endpoints this codebase's client calls
  (`/team_event/{team}/{event}` and `/matches?event=...`, not just similar
  ones), rechecked eight times across the session (after M04's code, after
  M05's, M06's, M07's, M08's, M09's, M10's, M12's), still down every time
  (last check returned HTTP 503 rather than 500, still not a real
  response). Both M04 baselines' real,
  dated backtest numbers remain blocked on this, and by extension M05/M06's
  beats-baseline acceptance gates (each requires M04's frozen numbers to
  compare against). Per instruction: not hammering the API — checked at
  sensible checkpoints only, not continuously.

Human Decisions Required:
- None new. Still open: how long to keep waiting on Statbotics before
  considering an alternative (see prior status entries).

Known Risks:
- Ranking-ground-truth gap: RESOLVED (see above) — removed from risk list.
- Statbotics outage: unchanged, see Blocked above. Its blast radius now
  explicitly includes M05 and M06's acceptance gates (beats-M04-baseline),
  not just M04's own freeze — noted so neither gets mistakenly marked
  accepted on model code + unit tests alone.

Last Verified:
- Database: PASS.
- Full suite: PASS, isolated — 1185 passed, 0 failed, 0 skipped (1043 after
  the concurrency-artifact re-run, +27 M05, +26 M06/team_vector, +29 M07,
  +16 M08, +13 M09, +13 M10, +18 M12). Confirms the earlier failure was
  the documented concurrency artifact, not a regression.
