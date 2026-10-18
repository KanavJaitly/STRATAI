# P7-M2 — Team metrics and strength: acceptance record

status: ACCEPTED (2026-10-17)
spec: docs/P7Milestones.md P7-M2 (frozen); P7-Q13, R9, R18
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- modified: ml/views/strength.py (stored_metrics_labels, RELIABILITY_INTERIM), api/routes/metrics.py (MetricsValidation,
  TeamMetricsResponse, _with_validation, description), tests/test_metrics_api.py (key set + validation, dated),
  docs/phase7.md ("Locked endpoint contracts": metrics, strength), docs/metrics_pipeline.md §8.1/§8.2,
  docs/api_contract_lock.json (+2 ops)
- new: tests/test_phase7_team_api.py (19 tests, sentinel namespace 9977, isolated DB)

## Decisions
- The metrics validation block is per part (scoring/defense/feeding), using only labels ml/views/strength.py already
  assigns. It is derived only from the stored *_insufficient_data flags plus the INTERIM caveat as a reason (R18).
  It never says validated.
- It is a response subclass of TeamMetrics, so TeamMetrics and the §8.2 docs example are untouched (R9).
- The defense_agreement caveat (no two-scout pairs) is a doc note, not a reason: P7-Q13 limits reasons to the flags.

## Acceptance criteria (spec)
- metrics: success: PASS (stored object unchanged + validation block)
- metrics: every 404/422 code: PASS (team_not_found, event_not_found, team_did_not_attend, metrics_not_computed;
  validation_error for 0 and "abc"; each checked against declared codes with assert_declared_error)
- metrics: thin-data team is a 200 with its *_insufficient_data flags: PASS (status 200, both flags true, null stddev)
- metrics documented as a current-state snapshot, not point in time: PASS (route description, docs/phase7.md)
- strength: success; invalid_as_of; epa_source_*; point-in-time as_of: PASS
  - invalid_as_of (unparseable, no offset); event_not_found; team_not_found; epa_source_not_loaded,
    epa_source_incomplete, epa_source_pending; validation_error
  - point in time: scoring n 1 -> 2 across qm2; scouting n 0 -> 2 across the observations' submitted_at (the test
    would fail if as_of were ignored)
- defense keeps descriptive_definition_pending; feeding keeps not_validated / insufficient_data: PASS (labels and
  feeding absent_reason asserted)
- both operations locked: PASS (lock: 4 operations, 20 schemas; check exit 0)

## Terminal verification
- full suite (after implementation, before review fixes): `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest -q
  --tb=line -p no:cacheprovider` -> 5 failed, 2248 passed, 5 skipped; pytest exit 1 (the 5 baseline failures).
  The failures are the same 5 tests as the baseline by name; 0 regressions; skips unchanged.
- after review fixes (tests and docs only): tests/test_phase7_team_api.py, test_metrics_api.py,
  test_metrics_docs_contract.py, test_phase7_contract.py -> 106 passed, pytest exit 0.
- `python -m scripts.phase7_contract_lock check` -> exit 0.
- type check / lint: not configured.

## Phase F (independent review)
No blocking or medium issues. 4 low, all fixed:
1. metrics_pipeline.md §8.2 wording and the lock location -> fixed.
2. Reason strings imprecise in docs -> exact strings and prefix-matching guidance.
3. Strength tests did not assert feeding insufficient_data or scouting point in time -> added.
4. Thin-team test did not assert 200 and the flags -> added.
Informational: Validation.status is free text, so the lock cannot forbid a label upgrade; label tests guard it.

## Remaining known risks
- Labels are guarded by tests, not by the lock (status vocabulary is free text).
- Real-environment examples for these routes: P7-M8 (needs P7-Q5).

## Decision
ACCEPTED. All P7-M2 criteria passed with the evidence above; 0 regressions against the baseline. Next: P7-M3.
