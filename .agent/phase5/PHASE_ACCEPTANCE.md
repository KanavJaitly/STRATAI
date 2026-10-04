# Phase 5 — phase acceptance review (2026-10-03; updated 2026-10-04)

**Update 2026-10-04.**
- **P5-D3 decided: the live EPA source is adopted for production** (Kanav). The live EPA source passed its frozen historical P5-M2 acceptance criteria and has been adopted for production; prospective 2027 validation remains pending.
  The record is `results/p5_m2_adoption.json`, and the production check is `.agent/production/p5_live_adoption_check_rerun1.json` (PASSED).
- **DM2 is MET.** **DM1 is still blocked** by required human input. **Phase 5 is not complete.**
- **The human-input workflows are built:** the `frontend/` web app plus the `/human-inputs` API. Every DM1 input can now be entered,
  reviewed and established through the website. None has been entered, and none may be fabricated.
- **Migration 0010 is on the serving database.** An un-isolated contract-test run applied it on 2026-10-04 at
  19:30:56Z, without prior approval. Its four tables are empty, and no serving data changed. Kanav kept it as the
  intended deployment migration. The incident is recorded separately (`.agent/phase5/INCIDENT_2026-10-04_0010_on_serving.md`); it is not a Phase 5
  acceptance failure. A permanent test-database guard now refuses any test session not pointed at an isolated
  `stratai_test` copy.

The review below is kept as written on 2026-10-03; where it says DM2 waits on P5-D3, the update above supersedes it.

**Verdict: Phase 5 is NOT complete.** Neither immutable done-means is met:
- **DM1** is blocked by required human input;
- **DM2** waits on one human decision: P5-M2 adoption, P5-D3.

Everything that can be completed without fabricating human inputs or decisions is built, verified and recorded.
`python -m scripts.phase5_done_means` reports this from the records alone.

## Milestones

| Milestone | Acceptance | Validation outcome |
|---|---|---|
| P5-M1 | ACCEPTED | data findings recorded |
| P5-M2 | ACCEPTED (L1–L4 passed) | **not adopted**; live outputs `live_refresh_not_yet_validated` until L6 (2027) |
| P5-M3 | ACCEPTED | descriptive; equality 0 / 1,000 mismatches |
| P5-M4 | ACCEPTED | raw-EPA ordering `validated`; M5 v2 after the switch `validated_as_measured` (+0.0183, CI [0.0082, 0.0288]); captain hit `validated_as_measured`, improvement not claimed |
| P5-M5 | ACCEPTED | per-match q validated only for EPA-complete matches; **80% range FAILED** its band (0.8532), so it is `not_validated` |
| P5-M6 | ACCEPTED on (a)–(e) | labelled rerun passed (0 problems); **first recorded run FAILED** on harness defects and is kept |
| P5-M7 | ACCEPTED | adapter parity 106,390 / 106,390; false alarms 0.0436 (CP 0.0469) passed; real flags `descriptive` |
| P5-M8 | NOT ACCEPTED | built and tested, rules decided (P5-D13); **blocked by required human input** |
| P5-M9 | NOT ACCEPTED | built and tested; DM1 **blocked by required human input** |
| P5-M10 | done | docs/phase5.md, tests/test_phase5_contract.py (33), scripts/phase5_done_means.py |

## Status categories

**Accepted:** P5-M1, M2, M3, M4, M5, M6 (on its criteria), M7.

**Validated** (within their recorded limits):
- raw-EPA event orderings, pre-event included;
- M5 v2 orderings after the event switch point (as measured);
- qualification probabilities on EPA-complete matches;
- expected-win records on EPA-complete schedules: unbiased (0.0000), MAE 1.1207;
- the M7 detector's false-alarm control;
- the M6 in-season loop's mechanics;
- the M2 live provider's equivalence and cadence (L1–L4).

**Not validated:**
- the 80% expected-win range;
- probabilities on EPA-incomplete matches;
- playoff anything (PX track, Phase 6);
- feeding ratings;
- defense (`descriptive_definition_pending`);
- captain-candidate improvement over raw EPA;
- live-refreshed EPA in production (until L6);
- every forward-looking P5-M8/M9 output (by spec).

**Failed:**
- the P5-M5 80% range coverage, a recorded failure that is not loosened;
- the first recorded P5-M6 run (harness defects, superseded by the approved labelled rerun);
- the first L4 run (sub-check defect, superseded by its labelled rerun).

**Blocked by required human input:**
- **DM1 / P5-M8 / P5-M9:**
  1. the 2026 spec entered from the manual;
  2. catalog specs;
  3. the codebook;
  4. two codings and a consensus coding;
  5. the action→function map;
  6. the rubric;
  7. at least 10 profiles;
  8. the mentor review.
- **DM2:** the P5-D3 adoption decision.

**Incomplete verification:**
- the P5-M8 κ report (needs human codings);
- the DM1 dry run, score and mentor review;
- L5 and L6 (prospective, 2027 season);
- the recommended, non-gating 2027 live DM2 confirmation.

## Expensive verification runs (all within the 45-minute rule)

| Run | Minutes | Result |
|---|---|---|
| P5-M6 debug (2026arli, after fixes) | 30.1 | 0 problems |
| P5-M6 recorded (P5-D14) | 30.9 | FAILED (harness), kept |
| P5-M6 labelled rerun | 32.6 | PASSED |
| P5-M2 L1 | 0.6 | PASSED |
| P5-M2 L2 | 1.9 | PASSED |
| P5-M7 (b)/(c) | 0.8 | (b) PASSED |
| Full test suite (phase audit) | 9.3 | 1,800 passed, 3 skipped, 0 failed |
| P5-D3 production adoption check (first) | 17.7 | FAILED (check defect), kept |
| P5-D3 production adoption check rerun1 | 18.8 | PASSED |

The only run that broke the rule was the first 2026arli debug run (about 52 min). It ran before the rule existed
and prompted it.

## Constraints honoured

- **Frozen work untouched:**
  - Phase 4 evidence, the D18 models and the D18 source;
  - PR #29;
  - P5-M0's criteria and thresholds (four spec gaps, Q1–Q4, were decided by Kanav before their results, as
    P5-D11 to P5-D14).
- **Core:** no LLM.
- **Databases:**
  - the serving database was read only;
  - every test and replay ran on isolated copies (`stratai_test`, `stratai_p5_replay_debug`,
    `stratai_p5_m6_verification`);
  - write-once records are kept, with commits, seeds and fingerprints.
- **Phase 3 audit item closed along the way:** metric quality-issue dedup (§9.10) was required before the watch
  recompute and was done (CLAUDE.md constraint 5 updated).
