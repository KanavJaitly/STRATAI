# P6-M12 run 1 — FAILED (kept); harness defect confirmed by diagnosis (D9)

2026-10-05. This file is a failure record, not an acceptance record.

**Run 1:** `.agent/phase6/results/p6_m12_strategy_validation.json`, write-once and kept unchanged. It ran under `.agent/phase6/decisions/P6_M12_SAMPLING.md` (with its dated null-week amendment) at commit `c0fcf97`, in 5.2 min.

| Criterion | Result |
|---|---|
| (a) reproduction | **pass**: 155 / 155 matches reproduced the P6-M10 odds bit for bit; features equal on 155 / 155 |
| (b) point-in-time sentinels | **FAIL**: 13 / 20 unchanged |
| (c) honest odds | **pass**: 0 violations; 14 raw probabilities below 0.05 and 14 above 0.95, all shown by the rule |
| (d) mentor review | not performed (optional; nothing fabricated) |

## Diagnosis: a harness defect, not leakage

**The defect.** The harness timestamped each sentinel **coach observation** at its own match's `as_of + 1 hour`. The other sentinel rows were far in the future (2026-12-31). The 20 sentinel matches span 12 events, so a sentinel observation inserted for an earlier sampled match is legitimately in the past for a later sampled match at the same event. The engine then (correctly) used it.

**The confirmation.** A non-recorded diagnostic on the retained clone `stratai_test_p6m12` inserted each sentinel kind separately and re-ran the engine:
- **+1 h coach observations:** exactly 7 matches changed. They are exactly the 7 matches that have an earlier sampled sentinel at the same event: `2026arc_qm80`, `2026dal_qm35`, `2026dal_qm94`, `2026joh_qm105`, `2026joh_qm118`, `2026mil_qm121`, `2026mil_qm87`.
- **Far-future coach observations:** **0 matches changed.**
- **The other two kinds:** the future match rows and future scouting observations were far-future in run 1 and changed nothing there.

**The second harness gap:** the record stored only counts, not per-match sentinel outcomes. That is why a diagnostic was needed.

## Fix (harness only; plan, sample and criteria unchanged)

- Sentinel coach observations are timestamped at the same far-future instant as the other sentinel rows. That is "a future coach observation", exactly as the plan states.
- The record stores the outcome of every sentinel match.
- **One labelled rerun:** `p6_m12_strategy_validation_rerun1.json`, with `supersedes`, the same sample and seed, on a fresh clone.
