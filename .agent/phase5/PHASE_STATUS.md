phase: 5
branch: phase5/build (from origin/main 369687f); nothing pushed
current_milestone: none (phase review done)
status: PHASE_REVIEW_COMPLETE; Phase 5 NOT complete (done-means unmet; see PHASE_ACCEPTANCE.md)
accepted: [P5-M1, P5-M2, P5-M3, P5-M4, P5-M5, P5-M6 (criteria a-e, labelled rerun), P5-M7]
not_accepted: [P5-M8, P5-M9 (blocked by required human input)]
done_means: {DM1: NOT MET (human inputs), DM2: MET (replay passed; P5-M2 adopted by P5-D3, 2026-10-04)}
decided: [P5-D11 (Q1), P5-D12 (Q2), P5-D13 (Q3), P5-D14 (Q4)] 2026-10-03; P5-D3 adoption 2026-10-04
adopted: P5-M2 live EPA in production (P5-D3, 2026-10-04): historical acceptance passed; prospective 2027 validation (L5/L6) pending
human_input_workflows: frontend/ web app + /human-inputs API (migration 0010, NOT yet applied to the serving database)
human_inputs_required (DM1):
  - the 2026 game spec entered from the manual (starts the 5-day clock); catalog specs; codebook; two codings; consensus coding; action->function map; feasibility rubric; >= 10 team profiles; mentor review
known_risks:
  - live T_w1 early in 2027 untested until L6
  - the P5-M5 80% range is served not_validated
last_verified: phase audit at 9a867fa on stratai_test: 1,800 passed, 3 skipped, 0 failed (9.3 min)
last_checkpoint: PHASE_ACCEPTANCE.md (2026-10-03)
