# P7-M6 — Alliance selection: acceptance record

status: ACCEPTED (2026-10-18); real alliance-selection output DEFERRED with P6-DM1 (P7-Q1: needs P6-M1 human ruleset
approval and passed PX-1/PX-2/PX-4 gates); the playoff label decision, open at acceptance (P7-D5 item 1), was CLOSED by
P7-D7 on 2026-10-18 (see the addendum)
spec: docs/P7Milestones.md P7-M6 (a)-(c), acceptance (frozen); P7-Q1, R1, R2, R4, R13, R15, R17; post-freeze P7-D4,
P7-D5
base: main 4290a3d, branch phase7/m0-spec, uncommitted

## Files
- new: ml/playoffs/service.py, api/routes/alliance_selection.py, tests/test_phase7_alliance_selection_api.py
  (67 tests), tests/test_phase7_playoff_loading.py (9 tests), .agent/phase7/decisions/P7_D5_SELECTION_CORRECTIONS.md
- modified:
  - data/config.py: the ML_PX1_* / ML_PX2_* pins;
  - api/ml_loading.py: load_playoff_models, with the sha256, model-type and malformed-file checks;
  - api/dependencies.py: get_playoff_models;
  - api/app.py: state and router;
  - ml/playoffs/selection.py: one engine fix, P7-D5 item 7 (infeasible instead of an AssertionError);
  - tests/test_api_foundation.py (PHASE7_PATHS), docs/phase7.md, docs/api_contract_lock.json (+2 operations,
    P7-D5 relocks).

## Scope delivered
- (a) Candidate profiles: `GET /events/{event_key}/alliance-selection/candidates`.
  - Covers the qualification roster (playoff-only rows excluded, P7-D5 item 4), with the P6-M6 factors as
    {value, n, validation} and the engine's own statuses.
  - `as_of` defaults to the selection moment (the same rule as `EventPlayoffs.selection_as_of`), or to now while
    that is still ahead. A future `as_of` is refused (P7-D4).
  - No scheduled qualification match: 409 `selection_time_unavailable`.
  - A configuration adds synergy and role compatibility for its members. Reliability carries
    `reliability_score_interim`.
- (b) The pick list: `POST /events/{event_key}/alliance-selection/pick-list`, the P6-M7 engine behind its real
  gates, in the R4 order (ml/playoffs/service.py docstring; docs/phase7.md step table):
  1. the approved ruleset;
  2. for_event;
  3. the PX gate records;
  4. its inputs at the selection moment:
     - qualification finished (scored and passed);
     - final ranks fresh against both the schedule and the result payloads, and covering the roster;
     - the PX artifacts loaded, and named by sha256 in the gate records;
     - the EPA source, the P5-M4 ordering, and features for every ranked team;
  5. the engine, then the draft-state consistency check.
  - Odds are display strings only. Comparisons with the next candidate (win event and reach finals) are display
    labels.
  - Provenance: the ruleset sha256 and variant, the ordering policy, and the PX and ranking model sha256s.
  - `probability_status` is `validated_playoff`, set only because the PX-4 record passed, never by a caller. The
    scope is stated in `validation.reasons`.
- (c) `POST /predictions/alliance-synergy` is unchanged (locked at P7-M3).

## Acceptance criteria (spec)
- (1) No awaiting-review ruleset and no qualification model is ever used as a playoff model: PASS.
  - Only `data.rulesets.approved_ruleset` is read. An approved ruleset that fails its schema or sha256 is
    `storage_integrity`; no table means `not_approved`.
  - The PX-1 loader refuses any file that is not `playoff_px1`, including the seed-only baseline, and any hash
    mismatch.
  - The ordering comes from the P5-M4 event analysis, as P6-M8 used it.
  - Tested: `not_approved` with no approved ruleset (today's real state) and before the EPA source is consulted;
    the tampered-ruleset cases; the loader cases.
- (2) Every refusal code is tested: PASS.
  - Candidates: `epa_source_not_loaded`, `event_not_found`, `team_not_found` (unknown and playoff-only),
    `selection_time_unavailable`, `invalid_as_of` (future), `validation_error`.
  - Pick list, step 1: `not_approved`, and `storage_integrity` (sha256 mismatch; schema-invalid JSON; a missing
    table, unit test).
  - Pick list, step 2: `wrong_season`, `event_excluded`.
  - Pick list, step 3: `playoff_models_not_accepted` (missing records; one failed gate).
  - Pick list, step 4:
    - `selection_time_unavailable` (moment ahead; an unscored qualification match);
    - `rankings_unavailable` (none; fetched before the last scheduled match; fetched before the last result
      payload; missing a roster team);
    - `model_not_loaded` (PX models; the M5 v2 ordering);
    - `playoff_models_not_accepted` (records not naming the pinned sha256s, 3 cases);
    - `epa_source_not_loaded`;
    - `playoff_inputs_insufficient` (outside the PX-1 domain; an absent input).
  - Pick list, step 5:
    - `not_covered`, `not_established` (captain rule; declined-captain rule), `not_supported`;
    - `infeasible` (two declines, and the single decline that was a 500 before P7-D5);
    - `invalid_state`: 9 inconsistent states (not the seed's turn; alliance count; unknown team; unknown declined
      team; declined pick under a forbidding rule; captains listed up front; a captain the rule would not give;
      turns_taken beyond the draft; picks without turns).
  - The pick list also refuses `event_not_found` and `validation_error`.
  - Every refusal is checked against its declared OpenAPI code (`assert_declared_error`).
  - `event_rules_required` is unreachable, and is no longer declared (tested).
  - The gate reader takes only a JSON object whose `passed` is the JSON `true` (8 cases), and a missing record is
    not passed.
- (3) The success path is tested in an isolated DB against a synthetic approved ruleset, a stub match-probability
  function and synthetic gate records, and labelled synthetic: PASS.
  - Full shape; seed 1's captain is the top-ranked team.
  - Every available team is ranked, by P(win event) then P(reach finals) (service-level check).
  - Up to 5 alternatives, distinct, excluding the top configuration.
  - Scope reasons and evidence; provenance; model sha256s.
  - No raw-precision key anywhere in the body.
  - A valid real draft state (a declined team captaining where the rules allow it) is served.
- (4) Locked shapes: PASS. `python -m scripts.phase7_contract_lock check` exits 0 (24 operations after P7-M7).
  - P7-D5 relocks are recorded in the lock's `revisions`.

## Terminal verification
- Final full suite:
  - command: `DATABASE_URL=<.../stratai_test> venv/bin/python -m pytest tests -q --tb=line -p no:cacheprovider`
  - result: 5 failed, 2468 passed, 5 skipped (11:34); pytest exit 1 from the 5 baseline failures only.
  - The 5 failures are the same 5 baseline tests, by name. 0 regressions; skips unchanged.
  - The raw log stays local (`.agent/phase7/runs/m6m7_full.txt`, excluded from the commit). The run includes P7-M7,
    which was built in the same pass.
- Earlier runs, kept for the record:
  - Before the review fixes: 5 failed (the same 5), 2383 passed, 5 skipped.
  - One run was contaminated by a concurrent single-file run against the same `stratai_test` rows. It was stopped
    and is not used as evidence.
  - One run failed `test_phase7_contract::test_phase7_owned_endpoints...`: a docs mention of a pre-Phase-7 route,
    a P7-M7 docs defect fixed before the final run.
  - Another run's output was lost when the scratchpad was cleared, so it is not used.
- type check / lint: not configured. A local AST unused-import scan over the changed modules was clean, except the
  intentional `display_probability` re-export (R7).

## Phase F (independent review)
- **Round 1:** 11 findings, all resolved (P7-D5 items 1-6):
  - caller-triggerable KeyError 500s, and an under-validated draft state;
  - the label (resolved as item 1; see below);
  - PX artifacts not tied to the evaluated ones;
  - the INTERIM reason missing from reasons;
  - the qualification-finished and rank-freshness checks;
  - the qualification-only roster;
  - the gate reader;
  - the reach-finals label;
  - the ruleset storage refusals;
  - test gaps;
  - docs.
- **Round 2, verifying the fixes:** 4 defects, all resolved:
  - the single-decline AssertionError 500 (P7-D5 item 7);
  - declined teams on alliances judged without the rules;
  - captains accepted ahead of their turn, which silently skewed the pick list;
  - rank freshness against planned times only (item 8).
  - Nits applied: the docs on duplicates, the module docstring, and the supersede note.
- **Round 3:** a 5-dimension adversarial workflow was launched. All 5 agents failed at start on the org's monthly
  spend limit, so it produced NO review. It is recorded as not done, not as a clean result.

## Open human decision (does not block acceptance; must be settled before frontend work locks it, P7-DM2)
- **The playoff label.** The frozen P7-M6 spec says `validated_playoff` ("exactly as
  `scripts/phase6_playoff_track.py` sets it"), while the frozen P6 spec names event-level values
  `validated_playoff_success`.
  - The served label follows the P7 spec, with the scope stated.
  - It is not served today: the pick list refuses with `not_approved`.
  - Decision needed from Sven/Kanav (P7-D5 item 1).

## Remaining known risks
- **The PX gate records carry no artifact sha256s,** and the PX-2 calibrator lives only in the P6 rows cache. Even
  if the gates pass, the pick list refuses until a record names the evaluated files (P7-D5 item 2, deliberate).
- **The sha256 binding matches the record text,** not a named field: no such field exists yet.
- **The selection pool is the qualification roster,** whereas P6-M8 `run_m8` used every team with features. The two
  coincide for full historical rosters (documented).
- **Rank freshness against results** applies only when TBA match payloads exist.
- **Real output** needs P6-M1 human ruleset approval and passed PX gates: DEFERRED with P6-DM1 (P7-Q1).

## Decision
ACCEPTED. Every P7-M6 criterion that can run here passed with the evidence above. 0 regressions. Real output is
deferred with P6-DM1 by the frozen P7-Q1, not claimed. The label naming conflict is open for Sven/Kanav.

## Addendum (2026-10-18): P7-D7, the playoff label
The open label decision above was decided by Sven Morais on 2026-10-18 (`decisions/P7_D7_PLAYOFF_LABEL.md`).
- The pick list's `probability_status`, and its values' `validation.status`, are now `validated_playoff_success`.
- `validated_playoff` stays reserved for P6's single playoff-match probabilities after PX-2.
- Applied: the constant in ml/playoffs/service.py; the `Literal` and descriptions in api/routes/alliance_selection.py;
  the two test assertions; docs/phase7.md; and a contract relock citing P7-D7 (one changed leaf,
  `/schemas/PickListResponse/properties/probability_status/const`).
- Both frozen specs are unchanged. The text above records the state at acceptance, and is kept as it was.
- Verification results are in `decisions/P7_D7_PLAYOFF_LABEL.md`.
