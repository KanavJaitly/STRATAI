# P11A E5: end-to-end comparison (descriptive and observational only)

**Status (2026-11-06):**
- The harness is ready and tested on synthetic data (`tests/test_p11a_e5.py`).
- The protocol is a DRAFT, not registered.
- Nothing has run on real data.

E5 never supports a claim that the plan selects superior alliances, or that following it causes better outcomes
(spec §20, E5's limits).

## What E5 measures

For each actual pick in a sampled 2024–2026 event, at the selection moment:
- the plan's top choice, and its AS-1 value V;
- the actual pick's V;
- **regret** = V(plan top) − V(actual), a model-internal disagreement;
- the actual pick's rank in the plan, and top-1 and top-3 agreement;
- each baseline's top available choice: individual EPA ranking, the P5-M4 ordering and P11-FB1.

Each actual alliance's TBA playoff result is a **label**. Summaries use event-cluster bootstrap intervals. The
regret / playoff association is labelled observational and confounded.

## Before it can run (in this order)

1. **An isolated real-data copy** passes `python -m scripts.p11a_db_preflight` (docs/p11a_verification.md).
2. **Reviewed, approved scoring configurations for 2024, 2025 and 2026** in `data/season_scoring/`, each
   referencing an approved P5-M8 GameSpec. That is a human review. Without it every event is
   `not_evaluable: scoring_config_not_approved`.
3. **The human decisions in `PROTOCOL.json`:** P11A-Q10 (the split), the as_of rule, the sample design and the
   baselines.
4. **Draw the frozen sample:** `python -m research.p11a_e5.run_e5 --draw-sample --per-stratum 2 --seed 20261106`.
   It reads event metadata, alliance presence and rosters only: no score, ranking or outcome. Paste the events into
   the runs.
5. **Register:**
   - set `status: registered` and mark each decision `decided: true`;
   - then write `.agent/phase11/decisions/P11A_E5_REGISTRATION_<date>.md` containing the file's sha256
     (`shasum -a 256 research/p11a_e5/PROTOCOL.json`).
   - The harness refuses a draft, an undecided protocol, or a protocol altered after its record was written.
6. **Run each of R1, R2 and R3 separately** (each ≤ 40 minutes):
   `python -m research.p11a_e5.run_e5 --protocol research/p11a_e5/PROTOCOL.json --run R1`.
   - Each writes `.agent/phase11/results/p11a_e5_<run>.json`.
   - Report each run separately. Never change the protocol after seeing a result.

## Safeguards built in

- **Database:** read-only session on an isolated `stratai_test` copy only (`scripts.phase6_common.isolated_database`).
- **The 2027 holdout:**
  - refused in the sample;
  - refused in every run;
  - checked by the preflight.
- **Leakage:** features come only from the snapshot at as_of.
  - A result posted after as_of is excluded, and so are rankings and scouting summaries from after it.
  - Playoff outcomes are labels only.
- **Time:** each run carries its budget and reports partial results when it hits it.
