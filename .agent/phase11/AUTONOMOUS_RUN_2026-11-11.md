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
