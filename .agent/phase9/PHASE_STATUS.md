phase: 9
branch: phase8/build at 45859dc (local main = origin/main = 111bc04). Nothing staged or committed; no Git publication authorized
status: CONDITIONALLY ACCEPTED, NOT COMPLETE (Sven Morais, 2026-10-20; decisions/P9_PHASE_ACCEPTANCE_DECISION_2026-10-20.md). MASTER_BUILD gate not satisfied on its own terms; P9-DM2 and live LLM verification DEFERRED to final remediation. Phase 10 authorised
spec: docs/P9Milestones.md (revision 1, working freeze RATIFIED by Sven Morais 2026-10-20); blobs in P9_M0_FREEZE.md, rechecked 2026-10-20 after M7: unchanged
decisions:
  - P9_M0_DECISIONS.md (P9-Q1..Q13; Q3 egress, Q4 credential, Q5 model are human decisions, open)
  - decisions/P9_D1_M3_ARRANGEMENT_DESIGN_2026-10-20.md (revision 2: the LLM arranges facts and writes no words; RATIFIED 2026-10-20)
  - decisions/P9_PHASE_ACCEPTANCE_DECISION_2026-10-20.md (conditional acceptance; Q3/Q4 kept off and deferred)
milestones:
  - P9-M0: ACCEPTED (working freeze; RATIFIED 2026-10-20)
  - P9-M1: ACCEPTED (local; model-backed success paths only as refusals)
  - P9-M2: ACCEPTED
  - P9-M3: ACCEPTED (stubbed); live call BLOCKED (no credential)
  - P9-M4: ACCEPTED (GET /matches/{match_key}/briefing locked additively)
  - P9-M5: ACCEPTED (fixtures)
  - P9-M6: tool ACCEPTED, sizes measured; tokens and cost BLOCKED
  - P9-M7: proof and docs ACCEPTED; phase decision PENDING
done_means:
  - P9-DM1: MET locally (runs/m1_m7_zero_llm_and_disconnection_rerun2.json; model-backed successes not comparable here, P9-R13)
  - P9-DM2: NOT MET (BLOCKED: credential; figures will be lower bounds; model choice open)
reviews: reviews/R1_M1_M3_ADVERSARIAL_2026-10-20.md (10 findings), reviews/R2_M3_M7_ADVERSARIAL_2026-10-20.md (9 findings); all fixed
final_checks (2026-10-20):
  backend: exit 1; 2697 passed, 5 failed (exactly the baseline 5), 5 skipped, 1 xfailed (runs/backend_final_p9.txt). The suite does NOT pass
  frontend: vitest 173 passed (29 files) exit 0; tsc 0; oxlint 8 baseline warnings; build 0 (single run; P9-R5 flake not observed this run)
  contract: lock check 0 (25 operations); types --check 0
baseline: runs/backend_baseline_p9.txt (exit 1; 2489 passed, the same 5 failed)
risks: RISK_REGISTER.md (P9-R1..R13 plus carried P8 risks)
human_decisions_required (deferred to final remediation):
  - P9-Q3 data egress (name the destination), P9-Q4 credential, P9-Q5 model
recovery:
  - pure tests: DATABASE_URL=<stratai_test URL> venv/bin/python -m pytest tests/test_phase9_zero_llm.py tests/test_phase9_llm.py tests/test_phase9_briefing.py tests/test_phase9_cost.py -q -p no:cacheprovider
  - API tests (DB): tests/test_phase9_briefing_api.py on stratai_test
  - evidence: EPA_SOURCE=statbotics venv/bin/python -m scripts.phase9_zero_llm_audit --routes --disconnection --out FILE
  - cost: EPA_SOURCE=statbotics venv/bin/python -m scripts.phase9_briefing_cost --event 2026mrcmp [--measure]
