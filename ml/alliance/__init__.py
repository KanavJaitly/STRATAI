"""Per-robot component estimates (P11A A3), used by the live draft's fallback rule P11-FB2.

Only `estimator` is here: it is an unchanged copy of `ml/alliance/estimator.py` from `p11a/recommendation-intelligence`
(version `p11a-a3-v1`), taken for P11-FB2 (decision `.agent/phase11/decisions/P11_FB2_DECISION_2026-11-14.md`). The
rest of P11A (scoring configurations, snapshot, planner, profile) is not on this branch, and P11A stays disabled.

Every estimate is `not_validated`, and nothing here uses an LLM.
"""
