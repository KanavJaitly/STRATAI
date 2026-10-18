"""P6-M11: the match strategy engine. The AI recommender and the coach scenario mode share one evaluation path.

- **Both paths go through `StrategyEngine.assess`.**
  - It calls the P6-M10 model's single entry point and applies the single display rule.
  - The recommender (`recommend`) and the coach path (`assess`, `compare`) differ only in where the strategy came
    from, and that is never passed in.
  - The engine never adds, adjusts, caches or rounds a probability itself (P6-DM2).
- **The recommender** searches the **entire** finite strategy space for the side being advised, exhaustively:
  - each robot is scoring (with any subset of components), defending one opponent, or feeding one ally;
  - auto and endgame are pursued or not.
  - Ties are broken deterministically: fewer changes from the baseline, then the canonical JSON.
- **Presentation (P6-Q10):**
  - the recommendation states that its odds are the maximum over N model estimates, not an unbiased probability;
  - differences within one display step are "indistinguishable at model resolution";
  - an AI strategy is never called superior.
- **Opponent:** the baseline, or a structured coach-entered strategy. There is no best-response search in Phase 6.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from ml.strategy.display import compare_odds, display_odds
from ml.strategy.outcome import ComponentOutcomeModel, MatchContext, OutcomeEvaluation
from ml.strategy.representation import SCORING_COMPONENTS, RobotPlan, Strategy

Side = Literal["red", "blue"]
MAX_ALTERNATIVES = 5
SELECTION_NOTE = ("The recommended strategy has the highest model estimate among {n} evaluated candidates. "
                  "A maximum over many model estimates is not an unbiased probability, strategy effects are unmeasured "
                  "(not_validated), and no strategy is claimed better than another within one display step.")


@dataclass(frozen=True)
class Assessment:
    """One strategy for one side, under the model: the same object for the AI and coach paths."""

    side: Side
    strategy: Strategy
    opponent_strategy: Strategy
    evaluation: OutcomeEvaluation
    p_ours: float | None
    display_ours: str | None

    def explanation(self) -> dict[str, object]:
        means = self.evaluation.component_means
        ours, theirs = (means.get("red"), means.get("blue")) if self.side == "red" else (means.get("blue"),
                                                                                       means.get("red"))
        return {
            "roles": {r.team_number: r.role for r in self.strategy.robots},
            "defensive_assignments": {r.team_number: r.defense_target for r in self.strategy.robots
                                      if r.defense_target is not None},
            "feeding_assignments": {r.team_number: r.feed_target for r in self.strategy.robots
                                    if r.feed_target is not None},
            "scoring_priorities": {r.team_number: list(r.components) for r in self.strategy.robots},
            "expected_component_means_normalized": {"ours": ours, "opponent": theirs},
            "validation_status": self.evaluation.validation_status,
            "reasons": list(self.evaluation.reasons),
        }


@dataclass(frozen=True)
class Recommendation:
    side: Side
    recommended: Assessment | None
    alternatives: tuple[Assessment, ...]
    candidates_evaluated: int
    selection_note: str
    unavailable_reason: str | None = None
    baseline: Assessment | None = None
    vs_baseline: dict[str, object] = field(default_factory=dict)


def _own_and_opponents(context: MatchContext, side: Side) -> tuple[list[int], list[int]]:
    red = [t.team_number for t in context.red_teams]
    blue = [t.team_number for t in context.blue_teams]
    return (red, blue) if side == "red" else (blue, red)


def robot_options(team_number: int, allies: Sequence[int], opponents: Sequence[int]) -> list[RobotPlan]:
    """Every plan the vocabulary allows for one robot, in a fixed order."""
    options: list[RobotPlan] = []
    for size in range(len(SCORING_COMPONENTS), -1, -1):
        for components in itertools.combinations(SCORING_COMPONENTS, size):
            options.append(RobotPlan(team_number=team_number, components=components))
    windows = ("auto", "endgame")
    subsets = [c for size in range(2, -1, -1) for c in itertools.combinations(windows, size)]
    for target in sorted(opponents):
        options.extend(RobotPlan(team_number=team_number, role="defense", components=c, defense_target=target)
                       for c in subsets)
    for target in sorted(a for a in allies if a != team_number):
        options.extend(RobotPlan(team_number=team_number, role="feeding", components=c, feed_target=target)
                       for c in subsets)
    return options


def candidate_strategies(own: Sequence[int], opponents: Sequence[int]) -> list[Strategy]:
    per_robot = [robot_options(t, own, opponents) for t in own]
    return [Strategy(robots=combo) for combo in itertools.product(*per_robot)]  # type: ignore[arg-type]


class StrategyEngine:
    def __init__(self, model: ComponentOutcomeModel) -> None:
        self.model = model

    def assess(self, context: MatchContext, side: Side, strategy: Strategy,
               opponent_strategy: Strategy | None = None) -> Assessment:
        """Evaluate one strategy for one side. The coach path, and the only evaluation path the recommender uses."""
        own, opponents = _own_and_opponents(context, side)
        opponent = opponent_strategy or Strategy.baseline(opponents)
        red, blue = (strategy, opponent) if side == "red" else (opponent, strategy)
        evaluation = self.model.evaluate(context, red, blue)
        p_ours = evaluation.p_red if side == "red" else evaluation.p_blue
        return Assessment(side, strategy, opponent, evaluation, p_ours, display_odds(p_ours))

    def recommend(self, context: MatchContext, side: Side, opponent_strategy: Strategy | None = None,
                  max_alternatives: int = MAX_ALTERNATIVES) -> Recommendation:
        """The AI path: exhaustive search over the side's strategy space, every candidate through `assess`."""
        own, opponents = _own_and_opponents(context, side)
        baseline = self.assess(context, side, Strategy.baseline(own), opponent_strategy)
        if baseline.p_ours is None:
            return Recommendation(side, None, (), 0, SELECTION_NOTE.format(n=0),
                                  unavailable_reason=",".join(baseline.evaluation.reasons), baseline=baseline)
        assessed = [self.assess(context, side, s, opponent_strategy) for s in candidate_strategies(own, opponents)]
        assessed.sort(key=lambda a: (-a.p_ours, a.strategy.changes_from_baseline(), a.strategy.canonical_json()))
        best, rest = assessed[0], assessed[1:1 + max_alternatives]
        return Recommendation(side, best, tuple(rest), len(assessed), SELECTION_NOTE.format(n=len(assessed)),
                              baseline=baseline, vs_baseline=compare_odds(best.p_ours, baseline.p_ours))

    def compare(self, context: MatchContext, side: Side, first: Strategy, second: Strategy,
                opponent_strategy: Strategy | None = None) -> dict[str, object]:
        """Two strategies (e.g. the AI's and a coach's) under the same model and inputs (P6-Q10)."""
        a = self.assess(context, side, first, opponent_strategy)
        b = self.assess(context, side, second, opponent_strategy)
        return {"first": {"display": a.display_ours, "validation_status": a.evaluation.validation_status,
                          "reasons": list(a.evaluation.reasons)},
                "second": {"display": b.display_ours, "validation_status": b.evaluation.validation_status,
                           "reasons": list(b.evaluation.reasons)},
                **compare_odds(a.p_ours, b.p_ours)}
