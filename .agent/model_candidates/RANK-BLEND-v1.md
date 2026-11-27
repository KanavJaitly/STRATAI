# RANK-BLEND-v1 — frozen candidate specification (event rankings)

- **Status:** RESEARCH CANDIDATE. Not served, not validated, not approved. Event analysis keeps its policy: raw EPA
  before the switch point, served M5 v2 (`ranking_xgb_v2`, d18) after it, unchanged.
- **Frozen:** 2026-11-26 (audit follow-up, workstream 2). Any change below is a new candidate (RANK-BLEND-v2), frozen
  before it is run on 2027 data.
- **Code:** `ml/candidates/ranking_blend.py` (definition), `scripts/evaluate_model_candidates.py` (evaluation),
  `tests/test_model_candidates.py` (properties and point-in-time), as committed with this spec.
- **Evaluation of record:** 2027, run once (section 6). Every 2026 number is retrospective evidence only.

## 1. Formula

For a team at a decision snapshot:

    rating = mean of the available values in { epa_total, average_score / 3 }

- **`epa_total`:** the team's EPA from its latest strictly earlier event (D13/D18 source), in that source's points.
  Never from the event being ranked.
- **`average_score / 3`:** the team's mean **alliance** score over its qualification matches at this event that were
  played strictly before the snapshot match (Phase 3 `average_score`), divided by three robots.
- Equal weights, **unfitted**. No parameter was estimated on any season.

## 2. Missing data

- No in-event matches yet (every team at the first snapshot): the rating is `epa_total` alone.
- No EPA (a rookie, or no earlier event with a usable EPA): the rating is `average_score / 3` alone.
- Both missing: no rating. The team is ranked last (`MISSING` = −1e9, the evaluation's convention, the same one the
  audit used for every rule).

## 3. Snapshots and point-in-time rules

Snapshots follow D16 §1.5 (`ml/backtest/ranking_midpoint.py`). Team i has n_i qualification matches at event e,
taken in scheduled order. Its snapshot is its k-th match: **k = ceil(n_i / 2), the midpoint (primary)**; k = 1 (first)
and k = n_i (last) are secondary.

The rating reads two fields of that match's `TeamFeatures`, built as of its scheduled time. So it uses nothing from
the snapshot match or any later match: no later score, rank or EPA. n_i comes from the qualification schedule, which
is published before qualification starts.

The truth is TBA's final qualification ranks (`data.rankings.read_final_ranks_for_season`).

`tests/test_model_candidates.py` checks this: changing every later match's features leaves the snapshot rating
unchanged, and the rating reads no other field.

## 4. Metrics

For each event, the score is the Spearman correlation of rating with −(final rank) over teams with both, at least two.
The reported value is the mean over events (the D16 statistic). Secondary: top-8 recall. Differences between methods
are per-event differences, averaged, with 95% CIs from bootstrap resampling of events (seed 20261126; 2,000
replicates for the evaluation of record).

## 5. Baselines

1. **Served M5 v2** at the same snapshots. This is the baseline that decides; it is what event analysis serves after
   the switch point.
2. **In-event average alone** (`average_score / 3`).
3. **Raw prior EPA alone** (the pre-switch policy).

## 6. The pre-registered 2027 evaluation, and conditions for production

**The run.** Once, after a 2027 data cutoff that the owners record before running it, on every 2027 event with final
qualification ranks in the database copy used:

    python -m scripts.evaluate_model_candidates --season 2027 --pre-registered-2027-run --reps 2000 --out <record>

**The candidate passes only if both hold at the midpoint snapshot:**
1. candidate − served M5 v2 mean Spearman has a 95% CI **entirely above 0**;
2. the in-event average alone does **not** beat the candidate: the CI of candidate − in-event average is not
   entirely below 0. If it is, the simpler rule is the better finding; it is reported, and the candidate is not
   approved.

**Production also needs:** the owners' written approval; a serving decision on where the switch point and the
`validated_as_measured` scope apply (`ml/validation_scope.py`); the event-analysis contract and labels, relocked if
any served value changes; and a point-in-time check of the serving path. Nothing here changes production.

## 7. Retrospective 2026 evidence (NOT validation)

This reproduces the audit's numbers exactly (`results/evaluation_2026_retrospective.json`; 208 events). 2026 was
examined repeatedly before this candidate existed, so these numbers cannot support approval.

| Snapshot | Blend | Served M5 v2 | In-event average | Raw EPA | Blend − M5 v2 (95% CI) | Events where the blend is better |
|---|---|---|---|---|---|---|
| first | 0.598 | 0.557 | −0.048 | 0.596 | +0.041 (0.028 to 0.055) | 135 / 208 |
| **midpoint** | **0.717** | 0.611 | 0.702 | 0.596 | **+0.105 (0.092 to 0.119)** | **194 / 208** |
| last | 0.749 | 0.631 | **0.844** | 0.596 | +0.118 (0.104 to 0.133) | 183 / 208 |

Read with care:
- **The advantage over the in-event average alone is small at the midpoint:** +0.015 (0.005 to 0.025), better in
  128 of 208 events.
- **At the last snapshot the in-event average is much better** (−0.095 for the blend). Late in qualification, the
  event's own results dominate any prior. The blend's equal weights suit the midpoint only. A snapshot-dependent
  weight would be a new candidate.
- **At the first snapshot** no team has an in-event average, so the blend equals raw EPA except in how ties and
  missing values fall.

## 8. Known limitations

- Raw points. When a team's EPA comes from an earlier season, its units differ from the in-event average (in 2026,
  36% of matches mix EPA seasons). Kept as audited; a normalized blend would be RANK-BLEND-v2.
- The in-event average is an alliance score, so it carries partners' contributions. It is not a per-robot estimate.
- Equal weights are a choice, not an estimate.
