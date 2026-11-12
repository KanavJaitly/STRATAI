# P11A autonomous build run (2026-11-11)

**Instruction:** Kanav's "Autonomous P11A build run" of 2026-11-11 (work queue items 1–6; ground rules and stop
conditions as given).
**Branch:** `p11a/autonomous`, created from `p11a/local-verify` at `ddcf60a`. Never pushed.
**Database:** only `stratai_test_p11a`, through the existing guards.

**Re-read this file first if the context is compacted.**

## Ground rules in force (summary)

- Never push. Commit after each finished work item.
- Never set an approval, review, `decided`, `registered` or `accepted` field. Never write into `data/season_scoring/`.
  Never register E5 or run E5 R1–R3. Never edit `PROTOCOL.json` decisions or any `.agent/phase5` / `.agent/phase6`
  record.
- Additive only. The Phase 3 metrics computation layer is not modified. Locked API contracts are unchanged, except the
  two P11A operations, and only if the spec requires it.
- A finding needs quoted lines.

## Log

### Item 1: requirements map

- **Stage 4 is undefined in the repository (stop condition, Stage 4 only).**
  - "Stage 4" appears once, in `.agent/phase11/decisions/P11A_HARDENING_2026-11-06.md:4`: "Stage 4 is not begun."
  - `PHASE_STATUS.md:122` names stages 1–3 only: "STAGES 1-3 IMPLEMENTED (foundation, plan, offline snapshot)".
    `PHASE_STATUS.md:150` repeats "stage_4: not begun".
  - The spec (`docs/P11-RecommendationIntelligence.md`) has no stage numbering: `grep -niE "stage [0-9]"` finds
    nothing in it, `docs/phase11.md` or `research/p11a_e5/`.
  - The stage list came from the owner's 2026-11-06 instruction ("P11A — Post-Implementation Hardening and
    Verification"; see `P11A_HARDENING_2026-11-06.md:3`), and that text is not recorded in the repository.
  - **Needed:** the owner's definition of Stage 4. Nothing is built under that name.

- **The map:** `docs/p11a_requirements_map.md`.
  - **Method:** three read-only passes over the spec, each quoting the lines it used.
  - **Spot-checks:** I re-checked 22 load-bearing quotes by exact-string search (13 + 9). All matched. Six claimed
    absences were confirmed by grep.
- **Decision (how stop conditions are applied):** a stop condition halts a work item when the *next step* depends on
  it. The run continues for everything else. Specifically:
  - The spec's behaviour-changing ambiguity (F2 `uncertain` vs C1; map §7.1) halts only that item: interpretations
    listed, nothing built.
  - The deviations (A3.2 (i)/(ii) prior source, cross-component covariance, per-robot cap on means) need a methodology
    decision. They are not "fixed" to match the spec. Doing so would change the estimator's method without a
    decision.
  - §12's B4 write routes conflict with the hardening record's file-registry trust root, and would add locked
    operations, which the ground rules forbid. Not built.
  - Q7 (a pre-selection plan without a record) would add an API operation, which the ground rules forbid. Not built.
- **Manuals for item 4:** fetched from FIRST's public blob store into a scratch directory (outside the repository):

  | Season | Status | Size | sha256 |
  |---|---|---|---|
  | 2024 | HTTP 200 | 6,712,480 B | `1b7e1dc3…9b94` |
  | 2025 | HTTP 200 | 9,979,998 B | `dc6aa9dd…d523` |
  | 2026 | HTTP 200 | 5,057,812 B | `5c67300f…5139` |

  Item 4 is feasible for all three seasons.
- **Baseline suite:** started in the background before any item-2 change, in four parts plus `test_config.py`
  alone. Reason: per a recorded note, `tests/test_config.py` pops the Settings env vars, so later tests in the same
  process would fall back to `.env`, which names the serving database.

### Item 2 plan (MISSING-BUILDABLE items chosen; order of work)

1. **Tests only** (no behaviour change):
   - criterion 4 (term list);
   - criterion 8 / Scenario D (seed 1 vs 8 against `turn_order`);
   - criterion 22 (analytic a′Σa; dropping cross-robot terms is detectable);
   - criterion 23 (common random numbers);
   - criterion 19 / Scenario O (always-together robots);
   - criterion 18 / Scenario N (a backup never in V);
   - Scenario B uncapped;
   - criterion 13 (profile equals plan);
   - criterion 6 (list identity after the recorded pick);
   - Scenario M (sentinel: outputs unchanged);
   - DM4 / Scenario J (offline CLI == online, without sandbox-exec);
   - §9.4 (brute force);
   - §13 (profile as strategy);
   - Scenario H (missing scouting).
2. **Disclosures inside the existing schema:**
   - A3.5 (no opponent adjustment);
   - B5.1 (per-robot cap on means);
   - B5.3 (components independent);
   - A3.2 (the `current_event_joint` card sentence).
3. **Additive response fields for the two P11A operations only (one relock, with a decision record citing this
   instruction):**
   - A3.7 (weak-identification reason, max |corr|);
   - A3.2 (prior mean and SD);
   - B5.7 (Monte Carlo run count and error);
   - B4/G2 (config and spec sha in the profile, exclusions);
   - A7 (`last_updated`);
   - B5.6 (`defense_effect_insufficient_data`).
4. **Snapshot:**
   - A3.6 (DQ/surrogate rules from `ml/dataset/builder.py`);
   - A7 (scouting agreement);
   - §7 (fit cached per snapshot id).
5. **Frontend:**
   - criterion 12 (stale-state test);
   - G2 / criterion 13 (card → profile link);
   - §11 (weak-identification / prior-dominated markers).

### Item 3: tooling for the human steps (built before item 2, committed first so the working tree stays small; it is independent of item 2)

- **(a) `scripts/p11a_gamespec_copy.py`:** export, import and verify one **approved** `game_spec_versions` row.
  - **Byte-for-byte:**
    - `spec_json` is carried as PostgreSQL's own JSONB text form.
    - Timestamps are carried to the microsecond (printed in UTC).
    - `manual_id` and `based_on_id` point at the source database. They are recorded in the file and imported as NULL.
  - **Checks:**
    - export: the row's `spec_sha256` equals `GameSpec.sha256()`;
    - import: the file's `row_sha256` and the spec sha256, before writing;
    - after inserting: the stored text and sha256 are read back and compared, or the transaction rolls back.
  - **Guards (database/target_guard.py, checked before connecting and confirmed by the server):**
    - the serving `stratai`, other names and remote hosts are refused;
    - import writes only to a local `stratai_test_<suffix>`, with `--confirm-database`;
    - export/verify may read the bare `stratai_test`, through a new opt-in `allow_bare_test` (default unchanged).
      Reason: the web app's human-input pages run there (`scripts/local_test_env.py:50`).
  - **Decision:** no test writes an `approved` row to any database, even a synthetic one, because the ground rules
    forbid setting approval fields. The import's SQL path is tested against a fake connection that checks the exact
    inserted values and the read-back refusal. The one DB test only reads: an export from `stratai_test_p11a`, which
    holds no approved spec (`no_approved_spec`).
  - **Limitation:** if a human approves a spec on the serving database, this tool cannot export it, because it refuses
    `stratai`. How that row reaches a test copy is the owners' decision.
- **(b) `scripts/p11a_check_scoring_config.py` plus `scoring_config.check_draft`:**
  - It validates a configuration of any status against a GameSpec without approval, lists every problem, and prints
    `content_sha256`.
  - The spec is either an approved-row export or a plain GameSpec file (reported as `game_spec_approved: false`).
  - `ResolvedScoring.resolve` now shares `_resolved_rules` with it. Behaviour is unchanged: same codes, same order of
    checks, and existing tests unchanged.
- **(c) Independent reviewer:** `require_approved` refuses (`scoring_config_not_approved`) a configuration whose
  `review.reviewer` equals `source.entered_by`, ignoring case and spacing.
  - Every scoring path goes through `require_approved`.
  - The synthetic fixtures already differ ("test" vs "Synthetic Reviewer"), so no existing test changed.
- **Tests:** `tests/test_p11a_tooling.py`, 28 tests.
  - Run with `tests/test_p11a_scoring_config.py` and `tests/test_migration_guard.py`: 68 passed, including the
    read-only DB test against `stratai_test_p11a`.

### Item 2, batch 1: missing tests, and one defect fixed (D2)

- **`tests/test_p11a_requirements.py`:** 17 tests, each naming the spec item it asserts.
  - **Criterion 4:** V equals the configured component terms plus the declared fouls, for both `fouls` settings.
  - **Criterion 8 / Scenario D:**
    - seed 1 vs 8 horizons from `turn_order` ([0, 15] vs [7, 8]);
    - each plan states its own `turns_before`.
  - **Criterion 22 / Scenario R:**
    - the capped value uses a′Σa with the cross-robot terms;
    - dropping them is detectable;
    - the capped expectation matches a 400k-draw Monte Carlo within 4 MC SE.
  - **Criterion 23:** Δ is taken draw by draw from common draws (exact match). The common-draw interval is
    narrower than with independent draws (7.07 vs 11.85 on the first run).
  - **Criterion 19 / Scenario O:** two robots that share every match are both `weakly_identified`, with
    max |corr| > 0.5, in every component.
  - **Criterion 18 / Scenario N:**
    - after a recorded backup, the backup is unavailable (`backup`) for every position;
    - the captain has `no_remaining_turn`;
    - a non-captain has no destinations, because backups exist only after every pick.
  - **Scenario B uncapped:** V is the plain sum, and A now ranks above B (the reverse of the capped run).
  - **Criterion 6:** after each of the top 5 first picks, the next-pick list equals that card's conditional list
    exactly.
  - **Criterion 13 (backend):** every card's profile has the same estimates as the card.
  - **§9.4:** the optimizer equals brute force over every ordered pair (12 teams), in order and value.
  - **Scenario H:** scouting changes no estimate or value; the defense value is shown, the missing feeding stays
    null.
  - **DM4 / Scenario J:** the offline CLI plan equals the served plan on the same snapshot, value for value. This
    runs on any OS; the network-denied version stays macOS-only.
  - **D2:** see the defect below.
- **`tests/test_p11a_db.py`, Scenario M (database):**
  - **What it does:** inserts a sentinel qualification match after `as_of` (a copy of the event's last match) inside
    one transaction that is always rolled back, then checks:
    - the snapshot id is unchanged;
    - positive control: the sentinel is visible to a snapshot after its own time.
  - **Passed** on `stratai_test_p11a` (44.6 s).
  - **Why a DB test:** an earlier fake-cursor draft was discarded, because the fake applied the cutoff itself and so
    tested nothing.
- **Defect found and fixed: D2 `backup_combinations` was not the top 5 complete alliances.**
  - **Cause:** the old code (`planner.py`, the block after `comparisons`) drew candidates only from the top 5 first-pick
    cards × their top 3 seconds, and sorted by *rounded* values.
  - **Probe on the unchanged code** (40 synthetic seeds):
    - 22 differed from the brute-force top 5;
    - seed 3 missed a top-5 alliance, `(9904, 9917)`;
    - seed 1 had two near-ties out of order.
  - **Fix:** `planner.top_combinations` ranks every pair by unrounded V, with ties by team numbers. The pair is
    reported sorted; `picks` is an unordered `list[int]`, and no UI renders it.
  - **Tests:** seeds 1, 3 and 8 against brute force, and a constructed case of disjoint best pairs.
- **Result:** P11A pure tests 123 passed, 4 skipped (the macOS `sandbox-exec` tests).

### Item 2, batches 2–3: disclosures, additive fields, one relock

- **Batch 2** (no contract change: `known_limitations` and `statements` are free text):
  - statements: the omitted opponent adjustment (A3.5), component independence (A3.3/B5.3), alliance-level variance
    (B5.2(b));
  - a per-robot-cap note (B5.1), only when a configuration has a per-robot cap;
  - the card sentence "prior estimated from this event's own matches" (A3.2), whenever a component's prior is
    `current_event_joint`.
- **Batch 3** (additive, optional fields on the two P11A operations only):
  - **A3.2:** `prior_mean` and `prior_sd` per component.
    - For `current_event_joint`: μ̂ and √(τ² + V_μ). μ is integrated, so this is the honest prior.
    - `posterior(..., with_population=True)` exposes (μ̂, V_μ) without changing its default 3-tuple; research
      callers are unchanged.
    - `w_eff` is unchanged, so no served value moved.
  - **A3.7:** `max_abs_corr` and `label_reasons` (each label with the threshold comparison that set it).
  - **B5.7:** `monte_carlo` (draws, seed basis, the bound on the MC SE of `p_delta_positive`).
  - **B5.6:** `defense_effect` = `defense_effect_insufficient_data`, 0 points.
  - **A7:** the profile's `last_updated` (the newest input time at or before `as_of`), plus scouting
    `defense/feeding_agreement` and `*_insufficient_data`. The snapshot now selects those `team_metrics` columns.
    The Phase 3 metrics layer is untouched; only the P11A read changed.
  - **G2/B4:** the profile provenance now has `exclusions` (typed), `scoring_config_sha256` and `game_spec_sha256`.
- **Relock:** `python -m scripts.phase7_contract_lock relock --reason ...` wrote 37 operations, **0 changed leaves**
  and 35 added leaves, all P11A schemas. A purely additive change needs only a reason (`scripts/phase7_contract_lock.py`
  docstring), so no decision document was required. The check is clean.
- **Types:** frontend types regenerated (`scripts.phase8_generate_api_types`); `--check` exit 0.
- **Test fixture changed, with its reason:** `tests/test_p11a_snapshot_builder.py`'s fake `team_metrics` rows went
  from 6 to 10 columns, because the builder's query now selects agreement and sufficiency. The assertions are
  unchanged.
- **Tests:** P11A 129 passed. Contract, foundation, zero-LLM and frontend-contract tests: 119 passed, 1 xfailed,
  **1 failed**.
  - The failure is `test_phase9_zero_llm::test_every_core_module_imports_and_the_app_builds_with_every_llm_sdk_blocked`:
    `scripts.phase10_connection_profile` → "ModuleNotFoundError: No module named 'resource'".
  - `resource` is Unix-only, so this is an environment failure on Windows, not caused by this run. It is handled in
    item 5.
