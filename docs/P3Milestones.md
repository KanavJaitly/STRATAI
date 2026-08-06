☐ Milestone 3: Pure statistical functions
 What to do
 Implement data/metrics/statistics.py: average_score, score_stddev, consistency_rating, classify_match_days, reliability_score
 Pure functions only — no DB, no I/O
 Return None (not 0 or an exception) for undefined cases: empty input, single match for stddev
 Document each function's edge-case behavior in its docstring
Success looks like
 Every function is total — no documented input crashes it
 Every function is deterministic and side-effect-free
 Math can be verified from the docstring alone
What to test
 tests/test_statistics.py
 Per function: normal case, empty input, single-element input, uniform input, one large outlier
 At least one hand-computed expected value per function
 reliability_score: low-DQ/low-variance team scores high, frequent-no-show team scores low

☐ Milestone 4: Match history retrieval layer
 What to do
 Implement data/metrics/history.py to fetch one team's match score history at one event
 Join matches + match_teams, resolve correct alliance color per match, exclude unplayed matches
 Return matches_scheduled vs matches_used alongside the score list
Success looks like
 Retrieved history matches manual inspection of the database exactly
 Played-vs-scheduled distinction is available to every downstream consumer
What to test
 tests/test_metrics_history.py against seeded sentinel-event data
 Team with 0 matches; team with only future/unplayed matches; team on mixed alliance colors
 Event where roster and match data disagree (Milestone 8 backfill scenario) doesn't drop/double-count

☐ Milestone 5: Scouting observation validation
 What to do
 Add validate_human_scout_observation_payload (and a registry slot for scoutradioz) to the validator module
 Required-field checks: match_key, team_number, scout_identifier, at least one rating present
 Range checks against the Milestone 1 rating scale
 Reuse PayloadValidationError/ValidationIssue as-is
Success looks like
 Malformed submissions rejected with the same structured, field-level errors as TBA/Statbotics
What to test
 tests/test_scouting_validator.py
 Valid payload accepted; each required field individually missing; each rating out of range
 Malformed match_key rejected; "at least one rating" rule enforced

☐ Milestone 6: Scouting observation normalization
 What to do
 Add normalize_human_scout_observation to data/metrics/normalizer.py (NOT
 data/staging/normalizer.py -- corrected 2026-08-04, Milestone 5. This
 originally said data/staging/normalizer.py, written before Milestone 1's
 data/metrics/schemas.py made its dependency-direction decision:
 ScoutingObservation and everything that builds one lives in data.metrics,
 since data.staging is a foundational layer nothing may import data.metrics
 into. Milestone 5's validator already lives in data/metrics/validator.py
 for the identical reason)
 Reuse the existing validate-then-build (_build_or_raise) pattern -- as a
 pattern to follow, since data.staging.normalizer's own _build_or_raise is
 private; decide on implementation whether that warrants promoting a shared
 copy or writing an equivalent one in data.metrics
 Register in the source-dispatch registry with a "scoutradioz" slot reserved for Milestone 9
 Deterministic natural key derivation matching the DB unique constraint
Success looks like
 Valid payload normalizes deterministically into a canonical ScoutingObservation
 No duplicated validate-then-build logic vs the TBA/Statbotics normalizers
What to test
 tests/test_metrics_normalizer.py additions (or equivalent new file, matching wherever the module lands)
 Valid payload normalizes with correct field values
 Required-field/malformed-payload rejection
 Determinism test; unknown-source dispatch raises clear ValueError

☐ Milestone 7: Human scouting submission path
 What to do
 Reuse RawPayloadWriter/raw_source_payloads for submissions (source="human_scout") — document this decision
 Add a submission service wrapping validated input into RawPayloadRecord
 Decide submission surface: minimal HTML form or documented JSON POST contract
 Add a lightweight anti-abuse gate (e.g. per-event access code) — no full auth yet
 Wire staging stage to pick up object_type="scouting_observation" via existing read_pending/stage_batch
Success looks like
 Submitted observation lands, is picked up by the existing pipeline, becomes a canonical row
 Resubmission dedupes; corrected resubmission creates a new version
What to test
 tests/test_scouting_submission.py end-to-end (submit → land → stage → canonical)
 Dedup test (identical resubmission, no new row)
 Correction test (new rating creates new version)
 Access-gate rejection test

☐ Milestone 8: Defense/feeding aggregation logic
 What to do
 Implement data/metrics/aggregation.py: aggregate_defense_feeding(observations) -> DefenseFeedingProfile
 Decide and document: minimum-observation threshold before trusting a score, median over mean, an agreement/confidence measure
 Pure function, no database
 Log this as a design decision in RUNNING_NOTES.md
Success looks like
 Deterministic, documented aggregation an experienced scout could have explained
 insufficient_data is a real, tested outcome, never a confident score from one data point
What to test
 tests/test_aggregation.py
 Zero observations; one observation (per documented threshold); multiple agreeing observations; multiple disagreeing observations with an outlier

☐ Milestone 9: ScoutRadioz connector (second scouting source)
 What to do
 Research ScoutRadioz's actual API/export shape against real documentation
 If available: data/clients/scoutradioz.py using the existing SourceConnector/SourceResponse pattern
 Add validate_scoutradioz_observation_payload and normalize_scoutradioz_observation into the existing registries
 Land via the existing RawPayloadWriter with source="scoutradioz"
 If unavailable, document that human-form is the sole measurement path for Phase 3
Success looks like
 ScoutRadioz and human-form observations coexist in scouting_observations, distinguishable by source
 Registry required zero structural changes to accept a third source
What to test
 tests/test_scoutradioz_client.py with mocked HTTP responses
 Coexistence test: both sources' observations for the same team+event aggregate together correctly

☐ Milestone 10: Metrics computation pipeline
 What to do
 Implement compute_team_metrics(event_key, team_number) combining history (M4) + statistics (M3) + aggregation (M8)
 Add a MetricsRepository (or extend CanonicalRepository) with upsert into team_metrics
 Hook as a follow-on stage after sync_event, reusing PipelineRunRecorder with pipeline_name="metrics_compute"
 Decide: always fully recompute on trigger, no incremental watermark — document why
 Extend lineage so a team_metrics row traces to every contributing match and observation
Success looks like
 Computation over existing canonical + scouting data produces correct, persisted team_metrics rows
 Re-running produces identical stored values
 Team with matches but no observations gets a complete object with insufficient_data=True, never a crash
What to test
 tests/test_metrics_pipeline.py end-to-end with seeded data, asserting hand-computed expected values
 Idempotency test (re-run, no duplicate/changed rows)
 Partial-data case (no scouting observations)
 Lineage test tracing a team_metrics row back to its sources

☐ Milestone 11: Metrics data quality checks
 What to do
 Extend data/staging/quality.py with checks for implausible consistency_rating/reliability_score values and low-sample-size warnings
 Wire into the existing data_quality_issues table and rejection mechanism — no second mechanism
Success looks like
 Low-confidence or implausible metrics are flagged and queryable, not indistinguishable from high-confidence ones
What to test
 tests/test_metrics_quality.py
 Each implausibility rule triggered individually
 Low-sample-size metrics flagged as warning but still loaded

☐ Milestone 12: API foundation
 What to do
 Create api/ package with an app factory, reusing existing Settings
 Add health/readiness endpoint, structured error response schema, request logging middleware
 Configure CORS for a future frontend
 No metrics endpoint yet — infrastructure only
Success looks like
 App boots under uvicorn; health check returns 200
 Invalid route and forced error return documented structured responses, no leaked internals
What to test
 tests/test_api_foundation.py using FastAPI TestClient
 Health check, 404 shape, forced-500 shape, CORS headers

☑ Milestone 13: Team metrics API endpoint (done — Sven, 2026-08-06)
 What to do
 Add GET /teams/{team_number}/events/{event_key}/metrics returning the exact TeamMetrics model
 Distinct handling for: team/event not found, metrics not yet computed, normal case
 Read directly from team_metrics — no on-the-fly recomputation in the request path
Success looks like
 Given any team number and event with computed metrics, the endpoint returns the complete object
What to test
 tests/test_metrics_api.py
 Happy path; team not found; event not found; metrics not yet computed; insufficient_data surfaced correctly
 Response schema validated against the canonical TeamMetrics model

☐ Milestone 14: Human validation and acceptance harness
 What to do
 Build scripts/metrics_spot_check.py, mirroring spot_check.py, printing computed metrics with no automated verdict
 Run against real synced events/teams the user has direct scouting knowledge of
 User manually confirms or rejects defense/feeding scores against their own assessment
 If scores don't match, surface which observations contributed so Milestone 8 can be revisited
Success looks like
 A documented, dated human sign-off recorded in RUNNING_NOTES.md, naming the teams/events checked
What to test
 No automated test — the human review record is the deliverable

☐ Milestone 15: Documentation and Phase 3 contract tests
 What to do
 Write docs/metrics_pipeline.md: architecture, schema, rating scale, reliability formula, aggregation methodology, API contract, known issues, extension guide
 Extend docs contract tests to cover the new schema/API
 Update RUNNING_NOTES.md with the Phase 3 milestone tracker and design-decision log entries
Success looks like
 Phase 3 documented to the same standard as Phase 2, enforced by tests rather than trust
What to test
 Docs contract tests pass: every table, column, endpoint, and constant documented matches the live schema/code
