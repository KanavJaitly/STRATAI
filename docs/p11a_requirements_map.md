# P11A requirements map

**Spec:** `docs/P11-RecommendationIntelligence.md` (PROPOSED, NOT APPROVED; unchanged).
**Written:** 2026-11-11, on branch `p11a/autonomous` (autonomous run; `.agent/phase11/AUTONOMOUS_RUN_2026-11-11.md`).
**Code state:** `ddcf60a`, plus this run's commits (listed in the run log).

**Statuses:**
- **BUILT:** implemented, with file:line evidence and a test.
- **PARTIAL:** part of it is built; the missing part is named.
- **MISSING-BUILDABLE:** nothing implements it, and it needs no human approval, decision or unavailable data.
- **HUMAN-GATED:** it needs a human approval, a decision (named), a registered evaluation, or external data.
- **DEVIATION:** the code does something other than the spec, and resolving it is a methodology decision. This is a
  kind of HUMAN-GATED; the code was not changed to match the spec.

**How it was made.**
- Three read-only passes over the spec, each quoting the lines it relied on: §6 A–B; §6 C–L and §7–16; and §17–21
  plus Appendix A.
- The load-bearing quotes were re-checked by exact-string search; all 13 sampled quotes matched, and so did the
  absences listed in the run log.
- Line numbers refer to the files at `ddcf60a`. This run's additions are marked "(this run)".

---

## 0. "Stage 4": cannot be determined from the repository

- **Where it appears:**
  - "Stage 4" appears once, in `.agent/phase11/decisions/P11A_HARDENING_2026-11-06.md:4`: "Stage 4 is not begun."
  - `.agent/phase11/PHASE_STATUS.md:122` names three stages: "STAGES 1-3 IMPLEMENTED (foundation, plan, offline
    snapshot)". `:150` says "stage_4: not begun".
- **Where it does not appear:** the spec, `docs/phase11.md`, `docs/p11a_verification.md` and `research/p11a_e5/`
  have no stage numbering (`grep -niE "stage [0-9]"`).
- **Where the stages came from:** the 2026-11-06 owner instruction ("P11A — Post-Implementation Hardening and
  Verification", quoted in `P11A_HARDENING_2026-11-06.md:3`). It is not recorded in the repository.
- **Status:** stopped for Stage 4 only. Nothing in this run is built under the name "Stage 4". Needed: the owner's
  definition.

---

## 1. Summary

| Area | BUILT | PARTIAL | MISSING-BUILDABLE | HUMAN-GATED / DEVIATION |
|---|---|---|---|---|
| §6 A (robot evaluation) | 6 | 13 | 6 | 7 (incl. 2 deviations) |
| §6 B (alliance value) | 11 | 10 | 5 | 9 (incl. 3 deviations) |
| §6 C–L, §7–16 | see §3 | | | |
| §18 acceptance criteria 1–24 | 5 (3, 5, 9, 15, 16) | 14 | 4 (4, 8, 12, 13) | 3 (20, 24; 2's bound) |
| §17 DM1–DM4 | 0 | 2 (DM3, DM4) | 0 | 2 (DM1, DM2) |
| §20 E1a–E5 | 0 | 0 | 0 | 6 (no registration exists) |

Counts are before this run's builds. §4 lists what this run built, and each row says "(this run)" where that
applies.

---

## 2. Capability A (robot evaluation) and B (alliance value): spec lines 263–670

| ID | Requirement | Status | Evidence | Test | Gate / note |
|---|---|---|---|---|---|
| A1 catalogue | Versioned per-season capability catalogue | MISSING-BUILDABLE | only `snapshot.py:40` `COMPONENTS = ("auto", "teleop", "endgame")` | — | game-specific dimensions are HUMAN-GATED (approved GameSpec + B4) |
| A1 refusal | Unsupported season refused (`season_not_supported`) | MISSING-BUILDABLE | 0 hits; rows excluded at `snapshot.py:248-249` | — | the plan is refused via `scoring_config_not_approved` |
| A2 | One observation type per value | PARTIAL | per-section `kind` in `contract.py:54,191,211,221,245` | `test_p11a_contract.py:79` | untyped: `matches_played`, card score, `w_eff` |
| A3 output | μ̂, σ̂ per team × component at `as_of`, strictly earlier | BUILT | `snapshot.py:99-101` leakage refusal; `planner.py:209` | `test_p11a_planner.py:175`; `test_p11a_snapshot_builder.py:99`; `test_p11a_db.py:121` (real data) | |
| A3.1 | Decompose alliance component points over 3 robots | BUILT | `snapshot.py:247` `score_components(...)`; `estimator.py:7` | `test_p11a_estimator.py:57,49` | REML hierarchical model (a justified alternative the spec permits) |
| A3.2 shrinkage | One match cannot set capability | BUILT | `estimator.py:219-225` | `test_p11a_estimator.py:94,82` | the prior's strength must be fixed in pre-registration (§20): HUMAN-GATED |
| A3.2 τ² method | Noise-removing τ² | BUILT | `estimator.py:163-168` `reml` | `test_p11a_estimator.py:49` | |
| **A3.2 (i) prior** | Prior-event **EPA**, scaled by `ml/features/scale.py` | **DEVIATION** | `snapshot.py:6`, `:297`: an A3 re-fit of the earlier same-season event plus drift; no EPA | `test_p11a_estimator.py:82,150` | Spec 325–328 vs E2 report line 203 (`AS1_indep_prior`); reason at E2 line 104: "point-in-time EPA cannot be reconstructed here". No decision record ratifies it. **Decision needed.** |
| **A3.2 (ii) population prior** | Independent population prior before (iii) | **DEVIATION** (absent) | `contract.py:55` has no third kind; `estimator.py:271` | — | "the first available level is used" (spec 324) is not followed. Building it needs the (i)/(ii) source decision above |
| A3.2 (iii) joint prior | μ_event joint; no plug-in | BUILT | `estimator.py:11-14,206-208` | `test_p11a_estimator.py:57` | |
| A3.2 (iv) no prior | `insufficient_data` per component | PARTIAL | event-level only, `estimator.py:241-242` | `test_p11a_estimator.py:142` | spec tension: once (iii) exists, (iv) cannot fire (map §6, item 3) |
| A3.2 reported | Prior kind, mean, SD, w, n | PARTIAL | `planner.py:210-213` (kind, w_eff, n) | `test_p11a_planner.py:212` | prior mean/SD not served: MISSING-BUILDABLE |
| A3.2 structural test | Joint SD ≥ plug-in SD | PARTIAL | coverage half only, `test_p11a_estimator.py:69` | | plug-in comparator test MISSING-BUILDABLE; tolerance HUMAN-GATED (pre-registration) |
| A3.2 disclosure | `current_event_joint` card sentence | PARTIAL | label `estimator.py:271` | `test_p11a_estimator.py:82` | the card sentence: MISSING-BUILDABLE |
| A3.2 prior_dominated | Label; never supports strength statements | PARTIAL | `estimator.py:262`; caution line `planner.py:229-230` | `test_p11a_estimator.py:108` | `prior_dominated_population` absent (needs (ii)); thresholds HUMAN-GATED (Q3) |
| A3.3 | Covariance across robots **and components** | **DEVIATION** | per-component fits, `snapshot.py:146`; scalar σ² `estimator.py:86` | `test_p11a_estimator.py:72` (cross-robot) | cross-component dropped with no pre-registered test (spec B5.3); E2 report:634 records it. **Decision needed** |
| A3.4 | Verified per-robot TBA fields as observed | HUMAN-GATED | not used | — | the fields are UNVERIFIED (spec 296); numerical use needs E1b |
| A3.5 | Opponent adjustment only if pre-registered | PARTIAL | omitted; the omission is not stated in `LIMITATIONS` (`planner.py:70-79`) | — | the statement: MISSING-BUILDABLE |
| A3.6 | DQ/surrogate rules as `ml/dataset/builder.py` | MISSING-BUILDABLE | 0 hits in `ml/alliance`; reusable `builder.py:457` `_parse_dq_and_surrogates` | — | |
| A3.7 diagnostics | Partners, opponents, max \|corr\|, rank | PARTIAL | `estimator.py:258,263,197` | `test_p11a_estimator.py:108` | opponents, rank flag and condition number not served; `max_abs_corr` not served |
| A3.7 weakly_identified | Label **with reason** | PARTIAL | `estimator.py:263-264` (bare label) | `test_p11a_estimator.py:108` | reason: MISSING-BUILDABLE; thresholds HUMAN-GATED |
| A3 validation status | `not_validated` until E1 | BUILT | `contract.py:168,228`; `profile.py:39` | `test_p11a_contract.py:71,79,149` | upgrade needs E1a: HUMAN-GATED |
| A4 | No same-event EPA | BUILT | no EPA input in `ml/alliance` | — | Q5 gates experimental use |
| A5 | Matches played/scheduled, DQ, surrogate, unavailability | PARTIAL | `profile.py:72` `matches_played` only | `test_p11a_planner.py:212` | scheduled/DQ/surrogate: MISSING-BUILDABLE (with A3.6) |
| A6 | Recompute after sync; id over raw ids + fetch times | PARTIAL | manual CLI only; fetch times dropped `snapshot.py:232` | `test_p11a_integration.py:125` | watch hook: MISSING-BUILDABLE (touches `data.orchestrator`; see run log) |
| A7 envelope | Type, n, uncertainty, source, `last_updated`, snapshot id | PARTIAL | `profile.py:66-67` | `test_p11a_planner.py:212` | `last_updated`: MISSING-BUILDABLE |
| A7 defense/feeding | With n and agreement | PARTIAL | `profile.py:53` | `test_p11a_planner.py:236` | agreement columns exist (0008 `:171,:175`), not selected: MISSING-BUILDABLE |
| B1 own robot | Estimated like every robot | BUILT | `planner.py:329,295-296` | `test_p11a_planner.py:114` | |
| B1 self-reported | Self-reported capability | HUMAN-GATED | none | — | P11A-Q6 |
| B2 gap / overlap | Per-component gap vs peers; capped overlap | MISSING-BUILDABLE | 0 hits | — | |
| B2 marginal gain | Gain from adding the candidate | PARTIAL | `planner.py:354,378` (fourth-member stage only) | `test_p11a_planner.py:156` | |
| B3 lineups | Two-robot partial; three-robot lineup | BUILT | `planner.py:330,339,124-131,371` | `test_p11a_planner.py:114,156` | |
| B3 backup never in V | — | BUILT, UNTESTED | backups unavailable `draft_log.py:354`; `planner.py:276` | — | test: MISSING-BUILDABLE (criterion 18) |
| B3 resilience | Separate `resilience_analysis` | MISSING-BUILDABLE | 0 hits | — | adding it to V is HUMAN-GATED (Q3) |
| B4 schema | Sum/cap with citation; per-robot caps | PARTIAL | `scoring_config.py:75-81` | `test_p11a_scoring_config.py:26,33,114` | general "cannot both reach maxima" constraints absent |
| B4 workflow | Draft → submit → reviewer; versions kept | PARTIAL | `scoring_config.py:115,149`; one file per season | `test_p11a_scoring_config.py:44` | reviewer-independence check and draft checker (this run, §4); versions kept only by git |
| B4 refusal | `scoring_config_not_approved` | BUILT | `scoring_config.py:149-152`; `planner.py:141-142` | `test_p11a_planner.py:23`; `test_p11a_integration.py:140` | |
| B4 provenance | Config sha256 in every output | PARTIAL | plan `planner.py:291-293`; not in the profile | `test_p11a_contract.py:64` | profile: MISSING-BUILDABLE |
| B4 configs 2024–2026 | Entered and approved | HUMAN-GATED | `data/season_scoring/` has only `README.md` | `test_p11a_contract.py:228` | approved GameSpecs, then entry and independent review |
| B4 / Q4 | Extend GameSpec, or reference by sha256 | BUILT (fallback) | `scoring_config.py:111`; resolution from GameSpec actions | `test_p11a_scoring_config.py:59,69` | P11A-Q4 undecided; fallback chosen in the 2026-11-06 record |
| B5 inputs/outputs | Per-component and total; predictive SD, 80% interval, component covariance | PARTIAL | total plus estimation interval only, `planner.py:366-370` | `test_p11a_planner.py:54` | per-component expectations and the predictive interval: MISSING-BUILDABLE |
| B5.1 | Cap under the predictive distribution, not means | BUILT (alliance cap); **DEVIATION** (per-robot cap on means) | `scoring_config.py` `expected_component_points`; `alliance_component_mean` | `test_p11a_scoring_config.py:89,97`; `test_p11a_planner.py:99` | spec B5.2(c) "not to their means". The disclosure the docstring promises is not served: MISSING-BUILDABLE |
| B5.2 / B5.3 | Cross-component terms; no independence | **DEVIATION** | `planner.py:242` independent draws per component | — | as A3.3 |
| B5.4 | Common random numbers | BUILT, UNTESTED | `planner.py:299,252-253` | — | test: MISSING-BUILDABLE (criterion 23) |
| B5.6 | Defense effect zero, labelled `defense_effect_insufficient_data` | PARTIAL | no defense term in V; `planner.py:77` | `test_p11a_planner.py:236` | the literal label: MISSING-BUILDABLE; Q8 HUMAN-GATED |
| B5.7 | Seeded; run count and MC error recorded | PARTIAL | `planner.py:240-241`; `DRAWS = 400` | `test_p11a_planner.py:168` | run count and MC error in output: MISSING-BUILDABLE |
| B5 validation | AS-1 on formed alliances (E2) | HUMAN-GATED | E2 is research, not registered | — | registered E2 |
| B6 quantities | Expected score never a probability | BUILT | `planner.py:282-283`; `contract.py:165-166`; UI `ExpectedScorePlan.tsx:106` | `test_p11a_planner.py:54`; `test_p11a_contract.py:71,131` | |
| B6 P(win) objectives | `p_win_event`, `p_win_playoff_match` | HUMAN-GATED | not served | — | PX gates (P6-DM1), E3, Q3 |
| B6 outcome table | δ, π outcomes | HUMAN-GATED (δ, π) | `contract.py:130` pins `unresolved` | `test_p11a_planner.py:61-62` | a pure rule with synthetic δ/π is buildable, but it can never be served until δ, π are approved |
| B6 until approved | Every comparison `unresolved` | BUILT | `planner.py:258`; `contract.py:131` | `test_p11a_planner.py:54` | extra reason `same_lineup` not in the spec (hardening H3) |
| B7 | Explanations from the calculation | BUILT | `planner.py:219-220` | `test_p11a_planner.py:99` | G1 thresholds HUMAN-GATED |

---

## 3. Capabilities C–L and §7–16 (spec lines 671–1144)

| ID | Requirement | Status | Evidence | Test | Gate / note |
|---|---|---|---|---|---|
| C1 value | V₁(c) = max_d V(us,c,d), in points | BUILT | `planner.py:336-339`; `contract.py:176-177` | `test_p11a_planner.py:114,54`; `test_p11a_contract.py:71` | |
| C1 availability | Treat not-confirmed-unavailable as available; label | BUILT | `planner.py:78,285` | `test_p11a_planner.py:54` | label is `availability_model: "not_modelled"`, not `availability_not_modelled` |
| C1 expectation over availability | Only after E4 | HUMAN-GATED | not built (correct) | — | P11A-Q1, E4 |
| C1 P6-M6 projection | Report the deterministic projection (top-1 0.211) | MISSING-BUILDABLE | 0 hits for `0\.211`, `P6-M6` | — | |
| C2 list | Ranked; V with interval and unit; conditional seconds | BUILT | `planner.py:341,366-368,375-376` | `test_p11a_planner.py:83,114`; `test_p11a_contract.py:64` | interval is estimation-only, `not_calibrated` |
| C2 P(available) | At our first turn | HUMAN-GATED | absent | — | F, Q1 |
| C2 flags | n and data-quality flags | PARTIAL | `contract.py:76` n; labels | `test_p11a_planner.py:212` | DQ/surrogate/stale flags: MISSING-BUILDABLE (§8) |
| C2 seed-specific | From our seed and the real record | BUILT | `alliance_plan.py:232,254` | `test_p11a_integration.py:34`; `test_p11a_availability.py:74` | |
| D1 | Conditional lists for top K ≥ 5; after the pick, the list | BUILT | `planner.py:67,330-331,343` | `test_p11a_integration.py:45`; `test_p11a_planner.py:99,114` | K is a constant, not configuration; lists cut at `MAX_LIST = 15` while the spec says "rank every candidate" |
| D2 | Top ≥ 5 complete alliances; never padded | BUILT, UNTESTED | `planner.py:387-396` | — | UNSURE whether it is the global top 5 (drawn from top 5 cards × top 3 seconds) |
| D3 | Scenario statements ("If A is your first pick…") | MISSING-BUILDABLE | 0 hits | — | |
| E1 | Position from `selecting_seed`; turns from `turn_order` | BUILT | `alliance_plan.py:231-249` | `test_p11a_integration.py:57,65`; `test_p11a_availability.py:74` | |
| E2 horizons | Seed 1 vs 8 availability differs | HUMAN-GATED | needs F | — | the turn-index list itself: MISSING-BUILDABLE |
| E3 | Non-captain destinations; invitation withheld; partners not a choice | BUILT | `planner.py:301-321` | `test_p11a_planner.py:144`; `test_p11a_integration.py:73` | likelihoods HUMAN-GATED (F, E4) |
| E3 declined-captain rule | Rule null: "outcome not determined" | MISSING-BUILDABLE | `draft_log.py:317-318`; silently skipped `alliance_plan.py:240` | — | |
| F1–F4 | Pick model, sampler, predicted states | HUMAN-GATED | not built | — | P11A-Q1, E4 |
| **F2 `uncertain`** | "Shown as uncertain" while F is withheld | **AMBIGUOUS (stop for this item)** | `contract.py:126` pins `confirmed_available` | — | see §7, item 1 |
| F2 separation | Predictions never change `availability()` | BUILT (vacuous) | `alliance_plan.py:230` | `test_p11a_planner.py:131` | no predictions exist |
| G1 card | Team, position, V ± interval, objective, unit | PARTIAL | `contract.py:117-127` | `test_p11a_contract.py:64` | team name absent |
| G1 statements | Marginal-gain, overlap, uncertainty, missing-data statements; only past a threshold | PARTIAL / conflicts | `planner.py:219-235` | `test_p11a_planner.py:99` | "Largest estimated contribution" and the cap line always print (spec 802 "no generic text"); thresholds HUMAN-GATED (Q3) |
| G2 profile | Estimates, observed matches, alliance fit, provenance | PARTIAL | `profile.py:66-126` | `test_p11a_planner.py:212`; `test_p11a_integration.py:140` | reuse of the dashboard team page; fits with proposed picks; model/config versions and exclusions in provenance: MISSING-BUILDABLE |
| G2 anomalies | Beyond a pre-declared bound | HUMAN-GATED | `profile.py:107` `not_flagged` | `test_p11a_planner.py:212` | G2 bound not approved |
| G2 link | Each recommended team links to its profile | MISSING-BUILDABLE (UI) | `liveDraft.teamProfile` unused (`auth/api.ts:445`) | — | criterion 13 |
| G3 | One-line reasons; details one tap | PARTIAL | reasons only in a hover `title` (`ExpectedScorePlan.tsx:105`) | — | |
| H1 | Plan from `DraftView` only | BUILT | `alliance_plan.py:223` | `test_p11a_integration.py:34` | |
| H2 / Q7 | Pre-selection plan without a record | HUMAN-GATED (this run) | no route | — | building it adds an API operation; this run's ground rules forbid that |
| H3 | Taken team removed; recomputed from scratch | BUILT | stateless `build_plan` | `test_p11a_integration.py:45`; `test_p11a_planner.py:131` | |
| H4 provenance | record_seq, snapshot id, versions, config sha | PARTIAL | `alliance_plan.py:261`; `planner.py:279,291-293` | `test_p11a_integration.py:108` | ruleset sha256 and AS-1/availability versions: MISSING-BUILDABLE |
| H4 stale | `current`/`stale`; failure keeps the last plan, stale | PARTIAL | client-only `ExpectedScorePlan.tsx:46,67`; server `contract.py:315` has no `stale` | — | vitest for the stale state: MISSING-BUILDABLE |
| H5 | Withheld while an action is flagged | BUILT | `alliance_plan.py:227-228` | `test_p11a_integration.py:85` | |
| §7 caching | Component 1 cached per (event, snapshot id) | MISSING-BUILDABLE | `snapshot.py:140-156` re-fits per request | — | affects §16 warm p95 |
| §7 other | Pure components; one consistent read; no LLM; no new dependency | BUILT | `planner.py:3`; `p11a_snapshot.py:109`; zero-LLM audit `:179-180` | `test_p11a_planner.py:168`; `test_p11a_db.py:86`; `test_phase9_zero_llm.py:61,160` | `EstimatorPolicy` not hashed |
| §8 inputs | Before `as_of`; labels never inputs; missing never zero | BUILT | `snapshot.py:99-101,193`; `contract.py:66-68` | `test_p11a_planner.py:175`; `test_p11a_snapshot_builder.py:99`; `test_p11a_db.py:121` | edge: `planner.py:177` `float(fouls or 0.0)` |
| §8 flags | Stale data; parity failures served; DQ/surrogate; scout conflicts | MISSING-BUILDABLE | exclusions kept in the snapshot only (`snapshot.py:249`) | — | |
| §8 sentinel | Later match inserted → outputs unchanged | PARTIAL | refused, not "unchanged" | `test_p11a_snapshot_builder.py:99` | MISSING-BUILDABLE |
| §9.4 | Optimizer equals brute force | MISSING-BUILDABLE | no test | — | |
| §9.5 | Seed from (record id, record_seq, snapshot id) | BUILT (deviation) | `planner.py:299` uses team_number, not record id | `test_p11a_planner.py:168` | deterministic either way |
| §9.6–9.7 | `not_validated`; engine unfed | BUILT | `contract.py:179`; `alliance_plan.py:145` | `test_p11a_contract.py:71,79`; `test_p11a_availability.py:96` | |
| §10 | Confirmed availability from `availability()`; every seed; 3-pick fourth member | BUILT | `alliance_plan.py:230,244-257`; `planner.py:127,354,357` | `test_p11a_availability.py:74`; `test_p11a_planner.py:156` | turn-index list and the decline statement: MISSING-BUILDABLE |
| §10 resilience | `resilience_analysis`, separate | MISSING-BUILDABLE | 0 hits | — | |
| §11 | Extends `/alliance-selection/live`; points, never % | BUILT | `LiveDraftPage.tsx:212`; `ExpectedScorePlan.tsx:65-66,106` | `ExpectedScorePlan.test.tsx:48,59` | |
| §11 panels | Top-5/show-all; second-pick selector; backup combinations; markers; resilience | MISSING-BUILDABLE | absent in `ExpectedScorePlan.tsx` | — | |
| §11 tests | Vitest per state + axe | PARTIAL | current, withheld, non-captain | `ExpectedScorePlan.test.tsx:59,70,79` | stale state; axe on every state |
| §12 operations | Plan and profile; locked; classified; pinned; client | BUILT | `live_draft.py:426,440`; `api_contract_lock.json:1277,1447`; `auth/api.ts:60-61` | `test_phase7_contract.py:64`; `test_api_foundation.py:363`; `test_frontend_workspace_contract.py:39` | the profile serves the whole G2 profile, not just the "fit" (§7, item 8) |
| §12 B4 routes | Platform write routes and a review page | **CONFLICT** (HUMAN-GATED) | none | — | conflicts with `data/season_scoring/README.md` and the hardening trust root (§7, item 3); would add locked operations |
| §13 | `alliance_selection` permission; other team 404 | BUILT | `live_draft.py:74`; `workspaces/live_draft.py:218,60` | `test_p11a_db.py:209,221,238` | profile route as strategy: MISSING-BUILDABLE |
| §14 snapshot | Id = sha256; offline from the local log | BUILT | `snapshot.py:93-95`; `p11a_snapshot.py:67` | `test_p11a_planner.py:175,197`; `test_p11a_offline.py` (macOS) | rules, artifact shas, component versions; `snapshot_incomplete` manifest: MISSING-BUILDABLE |
| §14 Scenario J | Offline output == online output | MISSING-BUILDABLE | — | — | |
| §15 | Phase 11 verified; B4 configs; evaluations | HUMAN-GATED | `PHASE_STATUS.md:7` | — | |
| §16 / Q9 | Performance targets | HUMAN-GATED (partly measured) | `test_p11a_db.py:190` asserts a cold plan < 2.0 s (labelled with the warm target); not recorded | — | P11A-Q9: "not requirements until those benchmarks are recorded" |

---

## 4. What this run built (2026-11-11, branch `p11a/autonomous`; commits in the run log)

**Behaviour changes:**
- **D2:** `backup_combinations` is now the global top 5 complete alliances over every pair, by unrounded V
  (`planner.top_combinations`). It was drawn from the top 5 cards × 3 seconds and sorted by rounded values; on 22 of
  40 synthetic events it differed from brute force.
- **A3.6:** matches with a disqualified team are excluded (`dq_affected`). Surrogate appearances are kept and recorded,
  as the labelled-dataset rules do.
- **§7:** the A3 fit is cached per (snapshot id, policy).

**Disclosures inside the existing schema:**
- A3.5 (no opponent adjustment); A3.3/B5.3 (components treated as independent: the deviation is stated, not
  resolved); B5.2(b);
- B5.1 (the per-robot cap on means, when configured);
- A3.2 (the card sentence "prior estimated from this event's own matches").

**Additive optional fields** (two relocks, 0 changed leaves in total):
- A3.2: `prior_mean`, `prior_sd`.
- A3.7: `max_abs_corr`, `label_reasons`.
- B5.7: `monte_carlo`.
- B5.6: `defense_effect` = `defense_effect_insufficient_data`.
- A7: `last_updated` and scouting agreement.
- G2/B4: profile provenance `exclusions`, `scoring_config_sha256`, `game_spec_sha256`.
- A5: `participation`.
- H4: `ruleset_sha256` and `rules_source` in the plan's `versions` (free-form; no relock).

**Web:**
- G2/G3, criterion 13: a card opens its own profile in one tap, with the full reasons.
- §11: markers on cards.
- Criterion 12: the stale state is tested.

**Tests for previously unasserted criteria and scenarios:** 4, 6, 8/D, 13, 18/N, 19/O, 21/Q (the plug-in half), 22/R,
23/S (common random numbers), B uncapped, H, J/DM4 (offline == online), M (database sentinel), §9.4 (brute force),
D2.

**Tooling (item 3):** the GameSpec row copy, the draft config checker, and the independent-reviewer rule.

### MISSING-BUILDABLE items not built in this run (scope; none is gated)

| Item | Why not now |
|---|---|
| B2 per-component gap vs playoff peers, capped overlap | needs a definition of "playoff peers" (spec 490–491 names the median but not the peer set); low value until a configuration exists |
| B3/§10 `resilience_analysis` | a new analysis and output section; larger than this run's remaining budget |
| C1 P6-M6 deterministic projection beside V₁ | needs the P6-M6 projection wired into the plan (engine-side code); deferred |
| D3 scenario statements; G1 marginal-gain, overlap, uncertainty and missing-data statements | they should fire only past pre-declared thresholds (spec 802), which are HUMAN-GATED (Q3); building them without thresholds would add the "generic text" the spec forbids |
| E3 "outcome not determined" when the declined-captain rule is null | small; deferred to keep the contract stable |
| A6 recompute after each watch sync | touches `data.orchestrator` (Phase 2/5 code); deferred to avoid changing the live-sync path in an unattended run |
| §14 `snapshot_incomplete` required-inputs manifest; rules and artifact shas in the snapshot | snapshot format change (new snapshot version); deferred |
| §11 top-5/show-all, second-pick selector, backup-combinations panel | UI work; deferred |
| A1 catalogue and `season_not_supported` | depends on the catalogue design; game-specific parts are HUMAN-GATED |
| B6 outcome rule with synthetic δ/π (criterion 23) | the contract pins `outcome: unresolved`; serving any other outcome needs δ, π approved |

## 5. Definition of success, acceptance criteria, scenarios (§17–19)

| ID | Status | Test / evidence | Missing / gate |
|---|---|---|---|
| DM1 replayed real event | HUMAN-GATED | synthetic `test_p11a_planner.py:114`; real rows with a made-up config `test_p11a_db.py:190` | approved, registered B4 configs |
| DM2 measured value | HUMAN-GATED | E5 harness only | registration of E1–E5 |
| DM3 honesty | PARTIAL | `test_p11a_planner.py:58,64`; `test_p11a_contract.py:71,79` | per-recommendation factor decomposition; n and uncertainty on destinations |
| DM4 live and offline | PARTIAL | determinism `test_p11a_planner.py:172` | offline == online on the same snapshot: MISSING-BUILDABLE; §16 targets pending (Q9) |
| 1 profile | PARTIAL | `test_p11a_planner.py:220-221` | `last_updated`; unsupported-season refusal |
| 2 small samples | PARTIAL | `test_p11a_estimator.py:105,112` | no pre-declared shrinkage bound (HUMAN-GATED); σ̂ at n = 1 and the population μ not asserted |
| 3 no double counting | BUILT | `test_p11a_scoring_config.py:93-103` | |
| 4 term list exact | MISSING-BUILDABLE | — | |
| 5 objective honesty | BUILT | `test_p11a_planner.py:57`; `test_p11a_contract.py:108,141`; `ExpectedScorePlan.test.tsx:66` | |
| 6 separation | PARTIAL | `test_p11a_planner.py:122,128` | list identity after the recorded pick |
| 7 combination logic | PARTIAL | `test_p11a_planner.py:109` | inside a first-pick card's conditional list |
| 8 positions | MISSING-BUILDABLE | — | seed 1 vs 8 against `turn_order` |
| 9 non-captain | BUILT | `test_p11a_planner.py:151-152`; `ExpectedScorePlan.test.tsx:87` | |
| 10 F separation | PARTIAL | `test_p11a_planner.py:140` | vacuous until an F model exists (Q1) |
| 11 unexpected outcomes | PARTIAL | `test_p11a_planner.py:139`; `test_p11a_integration.py:54` | Scenario G as specified |
| 12 staleness | MISSING-BUILDABLE | UI code `ExpectedScorePlan.tsx:46,67`, untested | |
| 13 profiles | MISSING-BUILDABLE | `liveDraft.teamProfile` unused | card → profile link; plan/profile equality |
| 14 offline | PARTIAL | `test_p11a_offline.py` (macOS only; passed on the Mac 2026-11-06) | identity with the online plan |
| 15 security | BUILT | `test_p11a_db.py:215-227` (run 2026-11-11) | strategy role on /profile |
| 16 contracts | BUILT | `test_phase7_contract.py:66` | |
| 17 performance | PARTIAL | `test_p11a_db.py:190` | timings not recorded; targets pending (Q9) |
| 18 three robots | PARTIAL | `test_p11a_planner.py:164` | backup test; resilience |
| 19 identifiability | PARTIAL | `test_p11a_estimator.py:113` | always-together construction; reason; dependent flags |
| 20 validation scope | HUMAN-GATED | `contract.py:228` pin | E1a |
| 21 prior dependence | PARTIAL | `test_p11a_estimator.py:69,89` | plug-in comparator; tolerance (HUMAN-GATED) |
| 22 joint uncertainty | PARTIAL | `test_p11a_estimator.py:77` | analytic a′Σa test; drop-terms test; cross-component (DEVIATION) |
| 23 comparisons | PARTIAL | `test_p11a_planner.py:61-62` | CRN test; synthetic δ/π rule |
| 24 anomalies | HUMAN-GATED | `test_p11a_planner.py:218` | G2 bound |

Scenarios A–T follow the criteria they reference. Two are distinct:
- **D** is MISSING-BUILDABLE.
- **M** is PARTIAL: an inserted later match is refused, but no test shows "outputs unchanged". `run_e5.py` has no
  sentinel, although §20 says "The sentinel test (Scenario M) runs in every harness".

## 6. §20 evaluations and §21.3 decisions

- **E1a, E1b, E2, E3, E4, E5:** all HUMAN-GATED. None is registered. E2 exists as research only
  (`docs/P11-E2-Benchmark-Report.md:637`: "**No pre-registration.**"). The E5 harness exists, and its
  `PROTOCOL.json` is `draft_not_registered`.
- **Q1–Q10:** all proposed, none approved (`P11A_IMPLEMENTATION_START_2026-11-06.md:7`).
  - The code follows the defaults of Q1, Q2 and Q8.
  - Q3: mostly. The thresholds are candidates taken from E2, not a pre-registration.
  - Q4: the fallback, not the extension.
  - Q5 and Q6: not used.
  - **Q7 is not followed:** plans exist only per draft record. Following it would add an API operation, which this
    run's ground rules forbid.
  - Q9: partly.
  - Q10: the holdout is protected; the split is undecided.

## 7. Contradictions and ambiguities (none resolved here)

1. **F2 `uncertain` vs C1 (behaviour-changing; stopped for this item).**
   - C1 (spec 681–682): "every team not confirmed unavailable is available", labelled `availability_not_modelled`.
   - F2's table (spec 767): `uncertain`, "F withheld, or the model is outside its domain", effect "Shown as
     uncertain".
   - Today F is always withheld. The code serves `availability: Literal["confirmed_available"]`
     (`contract.py:126`).
   - Interpretations:
     - (a) Every not-confirmed team is displayed `uncertain` while V still treats it as available.
     - (b) `uncertain` describes only the predicted dimension: the card keeps `confirmed_available`, and the
       `predicted` field reads `uncertain` instead of null.
     - (c) `uncertain` applies only when an F model exists but is outside its domain, so it never applies today.
   - (a) and (b) change the locked plan schema. Not built.
2. **A3.2 (i) prior source (DEVIATION).** The spec prescribes the prior-event EPA scaled by `ml/features/scale.py`.
   The code uses the E2 benchmark's earlier-event A3 posterior plus drift. E2 report line 104 explains why EPA was not
   used. No decision record ratifies the substitution, and (ii) is absent.
3. **§12 B4 write routes vs the file registry.** §12 asks for platform write routes and a `/rulesets`-like review page.
   The 2026-11-06 hardening record (H3) made the version-controlled file the trust root. The README says no tool
   approves a configuration.
4. **Cross-component covariance (DEVIATION).** A3.3, B5.2 and B5.3 require it, and forbid dropping terms without a
   pre-registered test. Components are fitted and drawn independently. E2 report:634 records the limitation.
5. **Per-robot cap applied to means (DEVIATION).** B5.2(c) says caps apply "to sampled per-robot contributions, not
   to their means". `scoring_config.py` `alliance_component_mean` applies them to means. Its docstring promises a
   disclosure that no output carries.
6. **A3.2 (iii) vs (iv).** Once ≥ 12 rows exist, the joint prior always exists, so per-robot `insufficient_data`
   (criterion 2, Scenario P "rookie") cannot fire. The 12-row minimum is not a spec-declared n_min.
7. **Thresholds chosen after seeing results.**
   - The candidate n_min, w_min, max|corr|, min_partners and collapse ratio came from the E2 report.
   - E2 ran on 2024–2026 playoffs.
   - A future pre-registration on 2024–2026 would not be blind to them (Q3 default; Appendix A "never change thresholds
     after seeing results").
8. **G1 "no generic text" vs `_statements`.** The "Largest estimated contribution" and cap lines print on every card.
9. **Scenario A is non-discriminating.** Under sum rules, "ranking follows V, not individual totals" cannot differ
   (`test_p11a_planner.py:84-85` says so).
10. **D1 "rank every candidate" vs `MAX_LIST = 15`; K fixed "in the configuration" vs the constant `TOP_K = 5`.**
11. **§9.5 seed tuple:** the spec has (record id, record_seq, snapshot id); the code has (snapshot id, record_seq,
    team).
12. **§16 label:** `test_p11a_db.py:190` asserts a *cold* plan < 2 s and calls it the P11-Q3 budget. §16's cold target
    is ≤ 30 s, and 2 s is the *warm* p95.
13. **Stale records.**
    - `PHASE_STATUS.md:123` says `committed: false` and `:131` "DB builder UNVERIFIED".
    - But P11A is committed, and the DB tests ran on 2026-11-11 (`docs/p11a_verification.md` §6).
