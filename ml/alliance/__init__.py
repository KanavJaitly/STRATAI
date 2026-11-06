"""P11A: alliance-selection recommendation intelligence (docs/P11-RecommendationIntelligence.md, PROPOSED).

Modules:
- scoring_config: the season scoring configuration (B4), referencing the approved P5-M8 GameSpec;
- estimator: per-robot component estimates (A3);
- snapshot: the event snapshot (§14);
- planner: alliance value (B5) and the first/second-pick plan (B6, C, D, E);
- profile: the team profile (G2).

Every output is `not_validated`, and nothing here uses an LLM.
"""
