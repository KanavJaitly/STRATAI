"""P6-M9: the strategy representation shared by the AI recommender and coach scenarios, and coach observations.

**One type for both paths.** `Strategy` is what the optimizer outputs and what a coach enters. It has **no field
recording who proposed it**, and extra fields are forbidden, so no evaluation input can carry a source. Who proposed
a strategy, and when, lives beside it in `StrategyProvenance`, which the outcome model never receives (P6-DM2).

**Vocabulary (P6-A8): score-component level.**
- Each robot has a teleop **role**: `scoring`, `defense` (with an opponent target) or `feeding` (with an ally
  target).
- Each robot also has the **score components it pursues** (its scoring priorities): a subset of auto, teleop and
  endgame, the components of the P5-M7 adapters.
- Teleop scoring requires the `scoring` role: a defender or feeder spends teleop on that role. Auto and endgame are
  separate time windows, so any robot may pursue them.
- Game-spec-level actions are used only when an approved P5-M8 spec exists; no such spec exists yet, so this module
  carries only the component-level vocabulary.

**Coach observations (P6-A9)** are structured, timestamped, attributed measured inputs, for example a mechanism
unavailable today. They apply identically to both paths, through the match context. Free text never enters a model:
`CoachObservation` has no free-text field, and the loader drops any notes from the raw submission.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VOCABULARY_VERSION = "p6-strategy-v1"
SCORING_COMPONENTS: tuple[str, ...] = ("auto", "teleop", "endgame")
ROLES: tuple[str, ...] = ("scoring", "defense", "feeding")
OBSERVATION_KINDS: tuple[str, ...] = ("component_unavailable", "robot_unavailable")

Component = Literal["auto", "teleop", "endgame"]
Role = Literal["scoring", "defense", "feeding"]


class StrategyError(ValueError):
    """A strategy or observation that does not satisfy the representation's rules."""


class RobotPlan(BaseModel):
    """One robot's assignment: its teleop role, its target (defense or feeding) and the components it pursues."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    team_number: int = Field(gt=0)
    role: Role = "scoring"
    components: tuple[Component, ...] = SCORING_COMPONENTS
    defense_target: int | None = Field(default=None, gt=0)
    feed_target: int | None = Field(default=None, gt=0)

    @field_validator("components")
    @classmethod
    def _canonical_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("a component is listed twice")
        return tuple(c for c in SCORING_COMPONENTS if c in value)

    @model_validator(mode="after")
    def _consistent(self) -> RobotPlan:
        if "teleop" in self.components and self.role != "scoring":
            raise ValueError("teleop scoring needs the scoring role: a defender or feeder spends teleop on its role")
        if (self.role == "defense") != (self.defense_target is not None):
            raise ValueError("defense_target is required for the defense role, and only for it")
        if (self.role == "feeding") != (self.feed_target is not None):
            raise ValueError("feed_target is required for the feeding role, and only for it")
        if self.feed_target == self.team_number:
            raise ValueError("a robot cannot feed itself")
        return self


class Strategy(BaseModel):
    """One alliance's strategy. No field records its origin (P6-DM2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vocabulary: Literal["p6-strategy-v1"] = VOCABULARY_VERSION
    robots: tuple[RobotPlan, RobotPlan, RobotPlan]

    @model_validator(mode="after")
    def _consistent(self) -> Strategy:
        teams = [r.team_number for r in self.robots]
        if len(set(teams)) != 3:
            raise ValueError("a strategy assigns three distinct robots")
        for robot in self.robots:
            if robot.feed_target is not None and robot.feed_target not in teams:
                raise ValueError(f"team {robot.team_number} feeds {robot.feed_target}, which is not an ally")
            if robot.defense_target is not None and robot.defense_target in teams:
                raise ValueError(f"team {robot.team_number} defends {robot.defense_target}, which is an ally")
        return self

    @classmethod
    def baseline(cls, teams: tuple[int, int, int] | list[int]) -> Strategy:
        """"No strategy specified": every robot scores every component, as history played it."""
        return cls(robots=tuple(RobotPlan(team_number=t) for t in teams))  # type: ignore[arg-type]

    def team_numbers(self) -> tuple[int, ...]:
        return tuple(r.team_number for r in self.robots)

    def plan_for(self, team_number: int) -> RobotPlan:
        for robot in self.robots:
            if robot.team_number == team_number:
                return robot
        raise StrategyError(f"team {team_number} is not in this strategy")

    def is_baseline(self) -> bool:
        return all(r.role == "scoring" and r.components == SCORING_COMPONENTS for r in self.robots)

    def canonical(self) -> Strategy:
        """The same strategy with robots in team-number order (robot order carries no meaning)."""
        return Strategy(robots=tuple(sorted(self.robots, key=lambda r: r.team_number)))  # type: ignore[arg-type]

    def canonical_json(self) -> str:
        return json.dumps(self.canonical().model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def changes_from_baseline(self) -> int:
        """How many (robot, component/role) assignments differ from the baseline; used only to order ties."""
        changes = 0
        for robot in self.robots:
            changes += robot.role != "scoring"
            changes += len(set(SCORING_COMPONENTS) - set(robot.components))
        return changes


class StrategyProvenance(BaseModel):
    """Who proposed a strategy and when. Stored beside a strategy, never passed to the outcome model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: Literal["optimizer_output", "human_entered"]
    author: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def _aware(self) -> StrategyProvenance:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must carry a timezone")
        return self


class StrategyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: Strategy
    provenance: StrategyProvenance
    event_key: str = Field(min_length=1)
    match_key: str | None = None


class CoachObservation(BaseModel):
    """A structured, timestamped, attributed measured input (P6-A9). No free text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_key: str = Field(min_length=1)
    team_number: int = Field(gt=0)
    kind: Literal["component_unavailable", "robot_unavailable"]
    component: Component | None = None
    observed_at: datetime
    observer: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> CoachObservation:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must carry a timezone")
        if (self.kind == "component_unavailable") != (self.component is not None):
            raise ValueError("component is required for component_unavailable, and only for it")
        return self

    def sort_key(self) -> tuple:
        return (self.observed_at, self.team_number, self.kind, self.component or "", self.observer)

    def disables(self, team_number: int, component: str) -> bool:
        if self.team_number != team_number:
            return False
        return self.kind == "robot_unavailable" or self.component == component
