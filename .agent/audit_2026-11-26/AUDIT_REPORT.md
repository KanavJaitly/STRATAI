# StratAI audit (2026-11-26)

**Scope:**
- the code as of `origin/main` `34cefb5`, on local branch `audit/2026-11-26`;
- databases: isolated copies only (`stratai_test_audit`, `stratai_test_pit`, `stratai_test_e2e`, plus read-only reads of
  `stratai_test`);
- the serving `stratai` was never written. It is still at 0011, with its latest data timestamps from Sep–Oct 2026.

**Nothing is committed, pushed, merged or deployed.**

**Evidence:**
- the baseline: `BASELINE.md`;
- the result files and the scripts that produced them: `results/`.

---

## A. Executive summary

**Overall.**
- The application works.
  - Every section opened and behaved correctly in a real browser for every role (72 of 72 checks).
  - The backend enforces the same permissions as the frontend.
  - The live draft workflow passed 17 of 17 checks through the real API.
- The point-in-time machinery is sound: corrupting every fact after a cutoff changed none of 132 cutoff-pinned served
  outputs.

**The most important problems are statistical, not functional.**

1. **The served win-probability model (M6+M7) is beaten by a one-parameter baseline on the held-out season.**
   - On 2026 qualification matches with complete EPA, a logistic on the scale-normalised EPA difference (fit on
     2024–2025 only) scores:
     - log-loss 0.478 vs 0.524;
     - Brier 0.157 vs 0.172;
     - AUC 0.852 vs 0.823.
   - The served model's log-loss is worse by 0.046 (95% CI 0.032–0.060, clustered by event).
   - Cause: M6 uses raw game-point features, and the 2026 scale is 2.5–3.8 times the training seasons. Its recorded
     "beats baseline" was against an equally mis-scaled baseline.
2. **The served ranking model (M5 v2) is beaten by an unfitted baseline at its own evaluated snapshot.**
   - At the midpoint on 2026, the blend of prior EPA and the in-event average scores a Spearman of 0.717 against M5
     v2's 0.611 (difference −0.105, 95% CI −0.119 to −0.093). M5 v2 is better in only 14 of 208 events.
   - The event analysis serves M5 v2 as `validated_as_measured` after the switch point.
3. **The hosted API's EPA source leaked season-end values.**
   - The hosted API runs `EPA_SOURCE=statbotics`, not the evaluated D18 source. That provider did not apply rule A1.
   - So 28, 57 and 101 team-events in 2024, 2025 and 2026 (0.7–1.3%) took a Statbotics **season-end** value, which is
     future information, as their "prior event" EPA.
   - **Fixed.**
4. **Live alliance selection.**
   - FB2's projected alliance scores are informative. On 4,714 alliances that were actually formed (2024–2026), FB2
     beats the team-average baseline on playoff-score MAE (21.5 vs 35.3) and on within-event ranking (Spearman 0.729
     vs 0.687; better at 314 of 591 events).
   - But FB2 is not an alliance optimizer in practice.
     - Its gap term almost never activates for a top captain, so it ranks by individual contribution.
     - Its second pick is effectively independent of the first.
   - Without the season's scoring caps and thresholds (P11A, gated on a human-entered scoring configuration), that is
     the correct behaviour of an additive model, not a defect.
5. **Labels overstate validation in places:**
   - predictions served on the training seasons (2024/2025) carry the same "approximately calibrated" or "validated"
     labels as held-out predictions;
   - `validated_as_measured` is served at any moment after the switch point, although it was measured at one snapshot;
   - the 2026 hold-out has been reused for many decisions.

   These need your decision. They change locked labels or frozen specifications.
6. **Operations.**
   - A real scouting export with scouts' full names is committed to the public repository (`data/imports/`).
   - `AUTH_TRUSTED_PROXY_HOPS` is unset on the hosted API, so every per-IP rate limit is one global bucket.

**Can the models be trusted?**
- Point-in-time integrity: **yes**, as far as tested.
- Win probabilities for qualification matches: reasonably calibrated in 2026 (ECE 0.015). But the model is
  measurably worse than a trivial alternative, and its label is optimistic.
- Rankings after the event starts: **no better than a simple average.**
- The live draft's projections: **useful, and better than a team-average baseline.**

---

## B. Frontend audit

The tool is Playwright with Chrome, against the API on `stratai_test_e2e`, members-only access, the production model
pins and the evaluated D18 EPA source. Accounts were created by the real join-code sign-up, and roles were set by the
admin.

**Result: 72 of 72 checks** (`results/e2e_browser_results.json`). There were no page errors and no 5xx on any page.

| Tab | Tested | Problems found | Fixed |
|---|---|---|---|
| **Events** | List, season, search; event page tabs (rankings, teams, matches, forecast); as-of; team page; match page; report; strategy lab | The old standalone Alliance Selection page (removal requested); invalid HTML nesting on the match and report pages (a `<ul>` inside a `<p>`, from validation-badge qualifiers) | The page was removed and the event header now links to live alliance selection. Badge qualifiers now render as valid phrasing elements with list semantics |
| **Team** (admin) | Overview, members, analytics, settings, activity | `OverviewTab` crashed when the analytics response lacked a role (seen as an intermittent test failure) | It treats a missing role as zero |
| **Drive team** | Dashboard, event chooser, tool cards, next-match card | **The event chooser called an admin-only route**, so it failed for strategy, drive and scout members | That one list is now gated on `team_info`; every other explorer route stays admin-only (backend and test) |
| **Scouting** | Report submit, validation, CSRF, duplicate submits, summary | **A retried or double-tapped submit stored a second row**, counted twice in the team's summary | Identical resubmits return the stored report; the summary uses each scout's latest report per match and team (test added) |
| **Admin** | Status, explorer, inputs, readiness, manuals, rulesets, game spec, profiles, review, account | The `/inputs/game` manual upload skipped the file checks and never started processing | It now matches `/manuals`: file checks before upload, and processing after it (test added) |
| **Permissions** | Every role against allowed and forbidden pages; direct API calls as a base member; anonymous access | None: the backend refuses what the frontend hides | — |

**Not changed:**
- **The write-access probe.** Every page load of a non-admin sends one 403 `GET /human-inputs/write-access`. It is
  harmless, and moving it needs the session and auth providers restructured.
- **Scouting CSV upload in the web app.** There is no web UI for it. The ScoutRadioz import exists only as a script.
  Building it is a product decision; see K.

## C. Predictive model validation

**Method.** All numbers are from the D18 frame (`ab1adbf3…`) and the registered artifacts, recomputed independently.
- Baselines are fit on 2024+2025 only.
- 2026 is the already-consumed D7 hold-out.
- The 2027 hold-out was neither read nor touched (no 2027 data exists).
- Confidence intervals resample whole events.

| Model | Leakage found? | Evaluation | Recorded | This audit (2026 held out) | Baseline comparison | Calibration | Status |
|---|---|---|---|---|---|---|---|
| **M6+M7 win probability** (served) | No (PIT test: 0 of 132 changed) | Temporal (train 24–25, test 26) | Log-loss 0.546 overall, M7 gate FAILED | Quals, EPA-complete: log-loss 0.524, Brier 0.172, accuracy 0.750, AUC 0.823 | **Worse** than a normalised-EPA logistic (0.478 / 0.157 / 0.771 / 0.852) | ECE 0.015 (quals); 0.119 (playoffs); weeks 1–2 0.047–0.083; last week AUC 0.65 | Validated with limitations: reasonably calibrated, inferior to a simpler model |
| **M5 v2 ranking** (served after the switch) | No | Midpoint snapshot, 208 events | Spearman 0.611 vs raw EPA 0.596 | Same | **Worse** than the in-event average (0.702) and the EPA + average blend (0.717) | n/a | Not validated relative to simple alternatives |
| M4 raw-EPA baselines | No | Temporal | — | Quals log-loss 0.635 (mis-scaled) | — | ECE 0.112 | Reference only |
| P5-M5 qualification forecast | No | Temporal | Coverage 0.853 vs target [0.75, 0.85] | Not re-run | — | Range `not_validated` | Inherits the M6/M7 findings |
| P6-M10 strategy odds | No | Temporal | Gate FAILED | Not re-run | — | `not_validated` | Labelled correctly |
| PX-1 / PX-1b playoff | No | Temporal | FAILED / pending 2027 | Not re-run | Seed-only beats PX-1 | — | Not served |
| P11-FB2 projection (live draft) | No | **New:** formed alliances' actual no-foul playoff scores | — | MAE 21.5, within-event Spearman 0.729 (591 events) | Beats the team average (35.3 / 0.687) | No interval | `not_validated` (kept); useful evidence |
| Synergy (M9) | No | — | — | — | — | — | Heuristic, not validated |
| Statbotics EPA (hosted source) | **Yes (fixed):** season-end values used as prior-event EPA | Measured exposure | — | 0.7–1.3% of team-events | — | — | Fixed with rule A1 |

**Negative control.** Permuting the labels gives AUC 0.497 and accuracy 0.500 for the served model, so the metric code
is not leaking.

**In-sample optimism.** On its training seasons the served model scores AUC 0.88 (2024) and 0.86 (2025), against 0.82
held out. Those predictions are still labelled as on held-out data.

**No model was changed** (frozen specifications). The recommendations are in K.

## D. Data leakage investigation

**Static trace.** Every model's data path was traced: features, EPA selection, scale, labels, splits, calibrators and
caches.
- All feature filters are strict (`scheduled_time < as_of`). The target event's own EPA is always excluded.
- No random split, no global scaler, and no calibrator fitted on test data.

**Empirical point-in-time test** (`results/pit_invariance_summary.json`, `results/scripts/pit_invariance.py`):
- **Sample:** 6 events across 2024–2026, at a mid-qualification cutoff.
- **Outputs captured:**
  - 12 teams' strength views per event;
  - event analysis, forecast, candidates and matches;
  - ad-hoc and scheduled-match win probability;
  - synergy;
  - hypothetical and scheduled strategy recommendations;
  - the pre-match report.
- **Corruption, in a disposable clone, of everything after the cutoff:**
  - every later match result (red and blue swapped, 33,124 matches);
  - their score breakdowns;
  - the rankings payload;
  - `team_metrics`;
  - 1,404 future scouting observations.
- **Result:** 132 cutoff-pinned outputs, **0 changed**.
- **Sanity check:** 105 selection-moment outputs, whose window includes the corrupted data, did change.

**Leak found and fixed:** the hosted `statbotics` provider (section A, item 3). There is a regression test with a
break-it check (`tests/test_statbotics_season_end_epa.py`).

**Point-in-time integrity could not be fully established for:**
- **Statbotics' own retroactive recomputation.** The snapshot was taken after the seasons.
- **Planned vs actual match times.** All cutoffs use the planned time.
- **Scouting `submitted_at`,** which is claimed by the submitter.

These are documented and low impact.

## E. Live alliance selection

**What was tested.**
- **Workflow, through the real API** (17 of 17):
  - start, captain, out-of-turn refusal (`wrong_turn`), pick, undo (superseded), correction;
  - decline, then a declined pick refused (`team_declined`), then recorded with an override;
  - close (actions refused), reopen;
  - a drive member cannot record;
  - recommendations cite the record number, 0.28–0.75 s.
- **Scenarios** (`results/fb2_scenarios.json`): 6 events, captains of alliances 1, 4 and 8, and six alternative first
  picks.
  - The first-pick list equals the individual-contribution order at all 6 events.
  - The gaps are 0 for captain 1. For captain 8 they reached at most 5.95 points (teleop, 2026onwat); otherwise at most
    1.6.
  - The second-pick order across first picks gives Kendall τ 0.999–1.0. It is not conditional in any material way.
- **Projection accuracy:** see C.
- **Exclusions:** only teams the rules make unavailable (projected captains of earlier alliances are a rules
  certainty, not a prediction of other captains' choices). Confirmed selections come from the record only.

**Limits.**
- No GameSpec-based scoring (caps, thresholds, shared resources), so complementarity cannot be valued.
- The fourth member is scored by its own contribution, not as a backup.
- Non-captain destinations are not on main (P11A, E3).
- No counterfactual claim: alliances that were never formed have no observed result.

## F. API and database

**Changes:**
- **Explorer:** the gating is per route (`api/routes/explorer.py`, `api/app.py`).
- **Scouting reports:** idempotent submit, and a deduplicated summary (`workspaces/scouting.py`).
- **ScoutRadioz import:**
  - a row failing the export-column validation no longer aborts the file; it is reported per row;
  - files: `data/clients/scoutradioz.py` (`read_rows_with_errors`) and `data/metrics/scoutradioz.py`.

**Upstream drift fixed:**
- `/workspace/team-events` pinned in `tests/test_api_foundation.py`;
- migration 0016 documented in `docs/data_pipeline.md`.

**Findings left for decision:**
- no connection pool (P10-R3, accepted);
- raw-payload demotion rewrites old versions;
- two unindexable `raw_source_payloads` filters;
- the deprecated ranking route is N+1;
- sessions and reset codes are never pruned;
- the access code is stored in plaintext (Phase 3 M7).

## G. Manual uploading

**Game manual PDF (`/manuals`, `/inputs/game`):**
- Tested in the existing suites. `/inputs/game` was fixed (see B).
- Server-side checks: checksum, de-duplication, the 100 MB limit, `%PDF-`.

**ScoutRadioz CSV (script):** the importer and client suites pass, 80 tests:
- valid rows; malformed team keys; blank scouter; truncated rows;
- bad export columns (new); excluded values; repeat imports (idempotent); several events (refused).

**Gap:** there is no in-app scouting CSV upload. Data provenance (raw landing, lineage) is preserved by the script path.

## H. Bugs and fixes

| Bug | Location | Cause | Fix | Verification |
|---|---|---|---|---|
| Season-end EPA used as prior-event EPA (hosted) | `ml/ratings/provider.py` | Rule A1 not applied in the reference source | Skip explicit zero-qualification Statbotics records until the season's last match, on both paths | 3 tests and a break-it check |
| Event chooser failed for non-admins | `api/routes/explorer.py`, `api/app.py` | It read an admin-only route | Season event list gated on `team_info` | API test and browser test |
| Duplicate scouting reports counted twice | `workspaces/scouting.py` | No idempotency | Identical resubmit returns the stored report; latest-per-scout in the summary | API test and browser test |
| ScoutRadioz import aborted on one bad row | `data/clients/scoutradioz.py`, `data/metrics/scoutradioz.py` | Validation raised inside the generator | Tolerant reader; reported per row | Test |
| `<ul>` inside `<p>` (invalid HTML) | `frontend/src/dashboard/display.tsx` | Badge qualifiers placed in the odds line | Phrasing elements with list roles | Browser and suite |
| Overview crashed on a missing role | `frontend/src/workspace/TeamManagementPage.tsx` | Assumed every role is present | `?. ?? 0` | Suite, twice |
| `/inputs/game` upload skipped checks and processing | `frontend/src/pages/GameSpecPage.tsx` | Diverged from `/manuals` | Same checks and processing | Test |
| Endpoint pin and migration docs drift | `tests/test_api_foundation.py`, `docs/data_pipeline.md` | Upstream PR #58 | Updated | Suite |

## I. Removed functionality

**The old standalone Alliance Selection page** (on request):
- removed: the route, page, tests, pick list, its icons and CSS, and the Drive team card;
- kept: `SynergyView`, moved to `dashboard/synergy.tsx` for the report;
- the three operations it called stay locked, and the client lists them in `NOT_CALLED`;
- docs updated: `phase8.md`, `team_workspaces.md`, `pick_list_sync.md` (superseded) and the frontend README.

**Lost with it:** "Our pick list", which was browser-only. It is recoverable from git.

## J. Testing results

| Suite | Before (`34cefb5`) | After (this audit) |
|---|---|---|
| Backend, full: `pytest` in 4 parts plus `test_config` on `stratai_test_audit`, each under 45 minutes | 3,462 passed, **2 failed**, 4 skipped, 1 xfailed (~40 min) | **3,469 passed, 0 failed**, 4 skipped, 1 xfailed (~33 min) |
| Frontend vitest | 280 passed, 6 skipped | 272 passed, 6 skipped (10 tests of the removed page gone, 2 new) |
| tsc / oxlint / vite build | 0 / 8 baseline warnings / OK | 0 / 8 / OK |
| Contract lock check | — | clean (0 changed, 0 added) |
| Zero-LLM audit | — | ok |
| Browser (Playwright, Chrome, 5 roles) | — | 72 of 72, run twice |
| Live draft API workflow | — | 17 of 17 |
| Point-in-time perturbation | — | 132 of 132 unchanged |
| Model evaluations | — | `results/eval_winprob.json`, `eval_ranking.json`, `eval_fb2_alliances_summary.json` |

**The 7 extra backend passes:**
- the 2 baseline failures, fixed;
- 3 rule-A1 tests;
- 1 scouting-report test;
- 1 ScoutRadioz test.

**Serving `stratai`:** unchanged. It is still at 0011, and its latest data timestamps are from Sep–Oct 2026.

## K. Needs your approval

1. **The served win-probability model.**
   - **Finding:** a normalised-EPA logistic beats it on 2026.
   - **Options:** a new frozen spec (for example, M6 on causally normalised features, or the logistic itself) evaluated
     on 2027; or relabel the current model.
   - **Why it needs you:** it changes a frozen, registered model and its pins.
2. **The served ranking policy (P5-M4 after the switch, and the FB1 ordering).**
   - **Finding:** an unfitted EPA + in-event-average blend beats M5 v2 at the midpoint.
   - **Recommendation:** pre-register the blend (or a model with in-event features) as a candidate, and evaluate it on
     2027.
   - **Why it needs you:** P5-M4 is frozen.
3. **Labels.**
   - Do not label predictions on 2024/2025 (training seasons) as calibrated or validated.
   - Limit `validated_as_measured` to the snapshot it was measured at.
   - These change label values in the locked contract (a decision record and a relock).
4. **Committed personal data.** `data/imports/matchscouting_frc11_2026mrcmp_full.csv` and
   `data/imports/DCMP_2026_Scouting_Data.xlsx` hold scouts' full names in a public repository. Removing them from
   history needs a force push, which is your call.
5. **`AUTH_TRUSTED_PROXY_HOPS=2` on Render.** It is unset, so every per-IP rate limit is one global bucket that anyone
   can exhaust. It needs dashboard access.
6. **`stratai_test` is at 0014,** but the current auth code needs 0015/0016. **Migration 0015 deletes every account and
   team-private row,** including your local 2024njfla replay record. So the documented local startup
   (`scripts.local_test_env --serve`) no longer signs in. Decide whether to migrate it (after a backup) or to point the
   local environment at a new copy.
7. **Live alliance selection.**
   - Valuing complementarity needs the season scoring configuration (P5-D7, human-authored) and P11A.
   - A fourth-member (backup) value needs a rule version (P11-FB2.1).
8. **An in-app scouting CSV upload** is not built. Building it is a product decision (format, mapping UI, permissions).
9. **`P11-P19Phases.md`:** an uncommitted stray `#` was found and kept as found.
