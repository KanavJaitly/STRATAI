milestone: P5-M2 Live EPA refresh
status: ACCEPTED (done-means met). ADOPTED for production by P5-D3 (Kanav, 2026-10-04): historical P5-M2 acceptance passed; prospective 2027 validation (L5/L6) pending
spec: .agent/phase5/LIVE_EPA_REFRESH_DESIGN.md (frozen at P5-M0); A1/A2 semantics per P5-D11 (Q1, 2026-10-03)
files: ml/ratings/live_snapshots.py, live_epa.py, live_source.py, prediction_log.py; data/config.py and ml/ratings/provider.py (EPA_SOURCE=p5_live_statbotics); api/routes/common.py (epa_source_pending); scripts/live_epa_refresh.py, phase5_m2_live_epa_checks.py (L3/L4), phase5_m2_l1_l2.py (L1/L2); tests/test_live_epa.py, test_live_epa_root.py
results:
  L1 PASSED: p5_m2_l1.json (sha 67a3df01..., commit 5d39052, 0.6 min)
    - all 319,301 appearances identical to D18, 0 mismatches
    - statbotics 263,726 / stratai_fallback 450 / withheld 55,125, equal to D18's recorded counts
  L2 PASSED: p5_m2_l2.json (sha b86f5fd8..., commit 5d39052, 1.9 min)
    - lag 6 h: 522 differences; lag 24 h: 547; lag 72 h: 1,726
    - every difference is a pending refusal explained by the lag
    - 0 values served with available_at >= as_of
    - diagnostic at 24 h: M5 v2 midpoint 0.6112; qualification ECE 0.0153 on 12,245 matches; feature substitution 0 / 200 mismatches against the assembler
  L3 PASSED: p5_m2_l3_outage_drill.json (commit 7b2d29c)
  L4 PASSED: p5_m2_l4_atomicity_rerun1.json (commit 35c2536). The first run (p5_m2_l4_atomicity.json) failed on a sub-check defect and is kept
  L5, L6: scheduled prospectively for 2027 (docs/phase5.md)
validation_status: live-refreshed outputs carry live_refresh_not_yet_validated until L6
decisions: P5-D11 (Q1): A1/A2 keeps D18's skip; production rule d18_skip
adoption: P5-D3 decided 2026-10-04 (row in P5_M0_DECISIONS.md; record results/p5_m2_adoption.json, commit 6b75843).
  The live EPA source passed its frozen historical P5-M2 acceptance criteria and has been adopted for production; prospective 2027 validation remains pending.
  production check: .agent/production/p5_live_adoption_check_rerun1.json PASSED (18.8 min); the first check (p5_live_adoption_check.json) FAILED on a check defect and is kept
done_means: "implemented to the frozen design; L1-L4 recorded as passed; L5-L6 scheduled" -> MET
