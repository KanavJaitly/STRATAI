"""Research candidates from the 2026-11-26 audit (workstreams 1 and 2). NOT served, NOT validated.

- win_prob_norm_epa: WP-NORM-EPA-v1, a scale-normalized EPA logistic for match win probability;
- ranking_blend: RANK-BLEND-v1, prior EPA blended with the in-event average, for event rankings.

Their frozen specs are in .agent/model_candidates/. Their 2026 numbers are retrospective evidence only: 2026 was
examined repeatedly before these candidates existed. Each can be approved only by its pre-registered evaluation on 2027
data (scripts/evaluate_model_candidates.py refuses 2027 unless that run is explicitly requested). Nothing in the API,
the registry pins or the live draft imports this package.
"""
