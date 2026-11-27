"""The season scoring configuration the alliance optimizer foundation reads (audit 2026-11-26, workstream 7).

Everything season-specific is a value in a `SeasonScoringConfig`; the evaluator and the search contain none. No real
season's configuration exists yet. Each value has to come from that season's game manual and be approved before the
optimizer may run on it (docs/alliance_optimizer.md lists them). A configuration whose `approval.status` is not
`approved` is refused unless the caller passes `allow_unapproved=True`, which only tests and research may do.

**What a configuration states:**
- **components:** the scoring components robots contribute to (for example auto, teleop, endgame), each with an
  interaction rule:
  - `additive`: the alliance scores the sum of its robots' contributions;
  - `capped`: the sum, but no more than `cap` (a shared resource the alliance can exhaust);
  - `best_k`: only the `k` largest contributions count (only k robots can use the location or action at once).
- **bonuses:** a fixed `value` awarded when a component's alliance total reaches `threshold` (a ranking-point or
  bonus condition). With uncertainty, the expected bonus is value × P(total ≥ threshold) under a normal model.
- **roles:** alternative jobs a robot can do instead of scoring normally (for example defense), each with
  `max_per_alliance`. A robot in a role contributes its role-mode values (from its profile) instead of its normal ones;
  the evaluator assigns roles to maximise the objective.
- **alliance:** `active_robots` (who play a match), `roster_size` (picked robots, so roster_size − active_robots are
  backups), `lineup_choice` (whether the alliance chooses which robots play each match), and `short_handed`
  (what happens when fewer robots than `active_robots` are available: `plays_with_available` or `forfeits`).
- **approval:** `status` (`draft`, `approved`), who approved it and when, and the game-manual sections each value
  came from.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

RULE_KINDS = ("additive", "capped", "best_k")
SHORT_HANDED = ("plays_with_available", "forfeits")
APPROVAL_STATUSES = ("draft", "approved")


class ConfigError(ValueError):
    """A configuration that is malformed, or not approved for the use asked of it."""


@dataclass(frozen=True)
class ComponentRule:
    name: str
    kind: Literal["additive", "capped", "best_k"]
    cap: float | None = None
    k: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in RULE_KINDS:
            raise ConfigError(f"component {self.name!r}: unknown rule {self.kind!r}")
        if self.kind == "capped" and (self.cap is None or self.cap <= 0):
            raise ConfigError(f"component {self.name!r}: a capped rule needs a positive cap")
        if self.kind == "best_k" and (self.k is None or self.k < 1):
            raise ConfigError(f"component {self.name!r}: a best_k rule needs k >= 1")
        if self.kind != "capped" and self.cap is not None:
            raise ConfigError(f"component {self.name!r}: cap applies only to a capped rule")
        if self.kind != "best_k" and self.k is not None:
            raise ConfigError(f"component {self.name!r}: k applies only to a best_k rule")


@dataclass(frozen=True)
class Bonus:
    name: str
    component: str
    threshold: float
    value: float

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ConfigError(f"bonus {self.name!r}: a negative value is not a bonus")


@dataclass(frozen=True)
class Role:
    name: str
    max_per_alliance: int

    def __post_init__(self) -> None:
        if self.max_per_alliance < 1:
            raise ConfigError(f"role {self.name!r}: max_per_alliance must be at least 1")


@dataclass(frozen=True)
class AllianceShape:
    active_robots: int
    roster_size: int
    lineup_choice: bool
    short_handed: Literal["plays_with_available", "forfeits"]

    def __post_init__(self) -> None:
        if self.active_robots < 1 or self.roster_size < self.active_robots:
            raise ConfigError("the roster must hold at least the active robots")
        if self.short_handed not in SHORT_HANDED:
            raise ConfigError(f"unknown short_handed policy {self.short_handed!r}")


@dataclass(frozen=True)
class Approval:
    status: Literal["draft", "approved"]
    approved_by: str | None = None
    approved_on: str | None = None
    sources: Mapping[str, str] = field(default_factory=dict)  # value path -> game-manual section

    def __post_init__(self) -> None:
        if self.status not in APPROVAL_STATUSES:
            raise ConfigError(f"unknown approval status {self.status!r}")
        if self.status == "approved" and not (self.approved_by and self.approved_on):
            raise ConfigError("an approved configuration names who approved it and when")


@dataclass(frozen=True)
class SeasonScoringConfig:
    season: int
    version: str
    components: tuple[ComponentRule, ...]
    alliance: AllianceShape
    approval: Approval
    bonuses: tuple[Bonus, ...] = ()
    roles: tuple[Role, ...] = ()

    def __post_init__(self) -> None:
        names = [c.name for c in self.components]
        if not names:
            raise ConfigError("a configuration needs at least one component")
        if len(set(names)) != len(names):
            raise ConfigError("component names must be unique")
        for bonus in self.bonuses:
            if bonus.component not in names:
                raise ConfigError(f"bonus {bonus.name!r} names unknown component {bonus.component!r}")
        role_names = [r.name for r in self.roles]
        if len(set(role_names)) != len(role_names):
            raise ConfigError("role names must be unique")
        for c in self.components:
            if c.kind == "best_k" and c.k is not None and c.k > self.alliance.active_robots:
                raise ConfigError(f"component {c.name!r}: k exceeds the active robots")

    @property
    def component_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.components)

    def require_usable(self, *, allow_unapproved: bool = False) -> None:
        """Refuse a configuration that is not approved, unless the caller explicitly accepts that (tests, research)."""
        if self.approval.status != "approved" and not allow_unapproved:
            raise ConfigError(f"the {self.season} scoring configuration {self.version!r} is {self.approval.status}, "
                              "not approved: its values have not been checked against the game manual")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SeasonScoringConfig":
        """Build from the JSON shape docs/alliance_optimizer.md documents. Unknown keys are refused."""
        known = {"season", "version", "components", "alliance", "approval", "bonuses", "roles"}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown configuration keys: {sorted(unknown)}")
        try:
            return cls(
                season=int(data["season"]), version=str(data["version"]),
                components=tuple(ComponentRule(**c) for c in data["components"]),
                alliance=AllianceShape(**data["alliance"]),
                approval=Approval(**{**data["approval"], "sources": dict(data["approval"].get("sources", {}))}),
                bonuses=tuple(Bonus(**b) for b in data.get("bonuses", ())),
                roles=tuple(Role(**r) for r in data.get("roles", ())),
            )
        except (KeyError, TypeError) as exc:
            raise ConfigError(f"malformed configuration: {exc}") from None


__all__ = ["APPROVAL_STATUSES", "AllianceShape", "Approval", "Bonus", "ComponentRule", "ConfigError", "RULE_KINDS",
           "Role", "SHORT_HANDED", "SeasonScoringConfig"]
