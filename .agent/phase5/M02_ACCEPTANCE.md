milestone: P5-M2 Live EPA refresh
status: NOT ACCEPTED (BLOCKED_ON_HUMAN: open decision Q1; then L1/L2; then the P5-D3 adoption decision)
spec: .agent/phase5/LIVE_EPA_REFRESH_DESIGN.md (frozen at P5-M0)
files:
  - ml/ratings/live_snapshots.py: append-only manifest log rooted at the D18 snapshot; copy-on-write; snapshot_id = sha256(manifest); processed flags (§1, §2)
  - ml/ratings/live_epa.py: LiveStatboticsEpa (§3 as_of, §5 states, §6 Option A 72 h, §7 provenance); simulated retrieval (frozen D18 / lag)
  - ml/ratings/live_source.py: loader; refresh cycle (fetch, raw file, Phase 2 landing, S1, manifest; failed cycle -> no manifest); §1 cadence; STRATAI rerun hook; atomic ProviderHolder
  - ml/ratings/prediction_log.py: §8 prediction log and bit-for-bit re-serve
  - data/config.py, ml/ratings/provider.py: EPA_SOURCE=p5_live_statbotics (needs LIVE_EPA_LOG_DIR and an explicit LIVE_EPA_A1A2_POLICY); not the default, not the evaluated configuration
  - api/routes/common.py: epa_source_pending (422) next to epa_source_incomplete
  - scripts/live_epa_refresh.py (operator CLI), scripts/phase5_m2_live_epa_checks.py (L3, L4), scripts/phase5_isolated_db.py
  - tests/test_live_epa.py (24), tests/test_live_epa_root.py (3)
results:
  L1: NOT RUN, waits for Q1 (decision before result)
  L2: NOT RUN, waits for Q1
  L3: PASSED, p5_m2_l3_outage_drill.json (commit 7b2d29c). Synthetic season 9983, isolated database
    - injected 503 / timeout / 503 then Upcoming then Completed records
    - pending at +1 h and +3 h; fallback_stratai at +73 h and +80 h (the Upcoming record is never served as statbotics); current at +90 h
    - the other team is stale while refreshes fail and current once they succeed
    - 3 manifests (root + 2 successful refreshes), 5 refresh log entries
    - both A1/A2 policies identical
  L4: first run p5_m2_l4_atomicity.json (commit 7b2d29c) FAILED on an additional sub-check defect (epa_scale miscounted as provider output; every L4 criterion passed). Kept unchanged
  L4 rerun: PASSED, p5_m2_l4_atomicity_rerun1.json (commit 35c2536)
    - 2026iscmp, 60 qualification matches, simulated lag 24 h
    - one snapshot_id per response; 120 logged predictions re-served bit-for-bit
    - 0 feature changes without an input change; 0 EPA changes without a retrieval or clock change
    - 360 team appearances, all fallback_stratai; both policies identical
  root integrity (test): the root's 24,022 normalized records equal D18's values; 140 unprocessed (2026isde1-4); T_w1 and T_end equal D18's
  L5, L6: scheduled prospectively for 2027 (docs/phase5.md, P5-M2)
decisions:
  - Q1 OPEN (.agent/phase5/M02_DECISION_REQUIRED.md). The frozen §3.5 and L1 conflict on D18's A1/A2 skip (1,817 of 319,301 appearances). The policy is an explicit, required argument with no default
  - live T_end exists only for seasons the operator lists as concluded (A1 values are season-end values). T_w1 is D18's rule over the snapshot in use
  - L4 pre-declared 2026iscmp at a 24 h simulated lag
  - tests and replays write only to an isolated template copy (stratai_test), never the serving database
bug_hunt:
  - Phase 2 landing dedups identical payloads; the L3 cleanup now removes landed raw payloads, lineage, runs and watermarks (found while dry-running)
  - P5-M3's strength endpoint was missing from the API path pin (tests/test_api_foundation.py); added
known_risks:
  - live T_w1 early in 2027 is computed from Completed week-1 events in the snapshot; its fidelity is untested until L6
  - the --watch trigger for refreshes is wired in P5-M6
  - running the refresher against the serving database changes team_event_stats, so the D18 loader refuses it; it must not be done before adoption
done_means: "implemented to the frozen design; L1-L4 recorded as passed; L5-L6 scheduled" -> NOT MET (L1/L2 wait for Q1)
