"""P7-M5 (P7-Q11, R19): measure the recommend endpoint's cost against its pre-registered budget.

    python -m scripts.phase7_m5_recommend_latency [--runs 5] [--registry DIR --version-tag TAG] [--record]

The budget was pre-registered before any measurement: 10 seconds per recommend request (one interactive Phase 8
request). The cost is the engine's exhaustive search (21,952 candidates for one side, every one through
StrategyEngine.assess); it does not depend on the model's coefficients, so a synthetic P6-M10 model measures it
faithfully. With --registry and --version-tag the registered model of record is measured instead.

Prints the measurement as JSON. --record writes it write-once to .agent/phase7/results/ through
scripts.phase5_records (which refuses an uncommitted tree, so the recorded commit is the code that ran).
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

BUDGET_SECONDS = 10.0  # pre-registered (docs/P7Milestones.md P7-M5 (e); .agent/phase7/P7_M0_DECISIONS.md R19)
RECORD_NAME = "p7_m5_recommend_latency.json"


def _model(registry: str | None, version_tag: str | None):
    from ml.strategy.outcome import SERVED_BASELINE_STATUS, ComponentOutcomeModel, load_registered_strategy_model

    if registry and version_tag:
        return load_registered_strategy_model(Path(registry), version_tag=version_tag), "registered"
    beta = {"auto": 0.9, "teleop": 0.8, "endgame": 0.7}
    sigma = [[0.10, 0.02, 0.0, 0.0], [0.02, 0.50, 0.05, 0.0], [0.0, 0.05, 0.08, 0.0], [0.0, 0.0, 0.0, 0.06]]
    model = ComponentOutcomeModel(beta, sigma, fit_info={}, spec_sha256="0" * 64)
    return model.with_status(version_tag="synthetic", baseline_status=SERVED_BASELINE_STATUS), "synthetic"


def _context(observations: int = 0):
    """Six synthetic teams, plus `observations` coach observations about teams outside the match (every observation
    at an event enters the context, and the engine scans all of them for every candidate)."""
    from datetime import datetime, timezone

    from ml.features.assembler import TeamFeatures
    from ml.strategy.outcome import MatchContext
    from ml.strategy.representation import CoachObservation

    def team(number: int, auto: float, teleop: float, endgame: float) -> TeamFeatures:
        """EPA components and causal scales present; every other feature absent (the engine reads only these)."""
        return TeamFeatures(
            team_number=number, epa_total=auto + teleop + endgame, epa_total_present=True,
            epa_auto=auto, epa_auto_present=True, epa_teleop=teleop, epa_teleop_present=True,
            epa_endgame=endgame, epa_endgame_present=True,
            average_score_present=False, score_stddev_present=False, consistency_rating_present=False,
            reliability_score_present=False, matches_considered=0, matches_used=0,
            average_auto_points_present=False, auto_points_matches_used=0,
            defense_score_present=False, defense_agreement_present=False, defense_observation_count=0,
            feeding_score_present=False, feeding_agreement_present=False, feeding_observation_count=0,
            score_scale=20.0, score_scale_present=True, epa_scale=10.0, epa_scale_present=True,
            epa_value_source="statbotics", epa_source_event_key="synthetic", epa_withheld_reason=None)

    red = tuple(team(n, 5 + i, 20 + 2 * i, 5.0) for i, n in enumerate((1, 2, 3)))
    blue = tuple(team(n, 6 + i, 21 + 2 * i, 4.0) for i, n in enumerate((4, 5, 6)))
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    notes = tuple(CoachObservation(event_key="synthetic", team_number=100 + i, kind="robot_unavailable",
                                   observed_at=when, observer="latency") for i in range(observations))
    return MatchContext(red, blue, observations=notes)


def measure(runs: int, registry: str | None = None, version_tag: str | None = None, observations: int = 0) -> dict:
    from ml.strategy.engine import StrategyEngine

    model, kind = _model(registry, version_tag)
    engine, context = StrategyEngine(model), _context(observations)
    seconds, evaluated = [], 0
    for _ in range(runs):
        start = time.perf_counter()
        result = engine.recommend(context, "red")
        seconds.append(time.perf_counter() - start)
        evaluated = result.candidates_evaluated
    worst = max(seconds)
    return {"budget_seconds": BUDGET_SECONDS, "runs": runs, "candidates_evaluated": evaluated,
            "seconds": [round(s, 3) for s in seconds], "median_seconds": round(statistics.median(seconds), 3),
            "max_seconds": round(worst, 3), "within_budget": worst <= BUDGET_SECONDS, "model": kind,
            "coach_observations_in_context": observations,
            "environment": {"machine": platform.node(), "python": platform.python_version(),
                            "processor": platform.processor() or platform.machine(),
                            "is_environment_of_record": False if kind == "synthetic" else None},
            "scope": "engine recommend only (the endpoint's dominant cost); HTTP, database feature building, the "
                     "EPA provider and the observation load are excluded"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--registry")
    parser.add_argument("--version-tag")
    parser.add_argument("--observations", type=int, default=0)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args(argv)
    result = measure(args.runs, args.registry, args.version_tag, args.observations)
    print(json.dumps(result, indent=1))
    if args.record:
        from scripts.phase5_records import write_once

        print(write_once(RECORD_NAME, result, results_dir=Path(".agent/phase7/results")))
    return 0 if result["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
