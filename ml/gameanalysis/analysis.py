"""P5-M8 game-rule analysis: the parts the frozen spec fully determines, plus explicit slots for the rest.

**Determined by the spec, and built here:**
- **The scoring-action value table:** a pure transform of a human-entered GameSpec.
- **Past-season scoring-component ranges:** per catalog season with breakdown data (2024–2026), from P5-M7's
  adapters. Only seasons before the reveal are allowed (the DM1 leakage rule). Labelled `descriptive`.
- **Historical design examples by codebook label:** see data.design_reference. Each is labelled
  `curated_reference_unverified`.

**Left open by the spec, and the reason for open decision Q3** (.agent/phase5/M08_DECISION_REQUIRED.md). P5-M8
says these rules are "fixed before the dry run" but does not say what they are:
- similarity to catalog games;
- candidate archetypes for a new game;
- expected scoring ranges for a new game;
- P5-M9's "predicted dominant scoring components";
- how two codings are reconciled into the served labels.

They are `Rules` slots with no implementation. `analyze` refuses (`RuleNotDecided`) until a decided, versioned
rule set is registered. Inventing them here would be new methodology.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from data.game_spec import GameSpec
from ml.features.score_components import COMPONENTS

DESCRIPTIVE = "descriptive"
NOT_VALIDATED = "not_validated"


class RuleNotDecided(RuntimeError):
    """A P5-M8/M9 rule the frozen spec leaves open (decision Q3) has not been decided and registered."""


def value_table(spec: GameSpec) -> dict[str, Any]:
    """Every scoring action with its points, grouped by period, and per-period summaries (descriptive)."""
    by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in spec.scoring_actions:
        by_period[action.period].append({"action_id": action.action_id, "name": action.name,
                                         "points": action.points, "unit": action.unit,
                                         "field_element_id": action.field_element_id,
                                         "manual_section": action.manual_section})
    seconds = {"auto": spec.match_length.auto_seconds,
               "teleop": spec.match_length.teleop_seconds - spec.match_length.endgame_seconds,
               "endgame": spec.match_length.endgame_seconds}
    summary = {period: {"actions": len(items), "max_points_per_unit": max(i["points"] for i in items),
                        "period_seconds": seconds[period]}
               for period, items in sorted(by_period.items())}
    return {"label": DESCRIPTIVE, "season": spec.season, "game": spec.game_name, "spec_sha256": spec.sha256(),
            "actions": {p: sorted(v, key=lambda i: (-i["points"], i["action_id"])) for p, v in sorted(by_period.items())},
            "periods": summary,
            "ranking_point_rules": [r.model_dump() for r in spec.ranking_point_rules]}


def component_ranges(rows: Sequence[Any], reveal_season: int) -> dict[str, Any]:
    """Past seasons' alliance points per component (quartiles and 10th/90th percentiles), seasons < reveal only."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    seasons = sorted({r.season for r in rows if r.season < reveal_season})
    for season in seasons:
        items = [r for r in rows if r.season == season]
        out[str(season)] = {}
        for component in COMPONENTS:
            values = np.array([getattr(r.parts, component) for r in items], dtype=float)
            out[str(season)][component] = {f"p{q}": float(np.quantile(values, q / 100)) for q in (10, 25, 50, 75, 90)}
            out[str(season)][component]["n"] = int(len(values))
    leaked = sorted({r.season for r in rows if r.season >= reveal_season})
    return {"label": DESCRIPTIVE, "reveal_season": reveal_season, "seasons": out,
            "excluded_seasons_at_or_after_reveal": leaked}


@dataclass
class Rules:
    """The Q3 rule set: each slot is a decided, versioned rule, or None (refused)."""

    version: str | None = None
    similarity: Callable[[GameSpec, list[GameSpec]], list[dict[str, Any]]] | None = None
    candidate_archetypes: Callable[[GameSpec, dict[str, Any]], list[dict[str, Any]]] | None = None
    expected_ranges: Callable[[GameSpec, dict[str, Any]], dict[str, Any]] | None = None
    dominant_components: Callable[[GameSpec, dict[str, Any]], list[str]] | None = None
    reconcile_codings: Callable[[Any, Any], Any] | None = None  # two Codings -> the served Coding
    notes: dict[str, str] = field(default_factory=dict)

    def require(self, name: str) -> Callable:
        rule = getattr(self, name)
        if rule is None or self.version is None:
            raise RuleNotDecided(f"rule '{name}' is open decision Q3 (.agent/phase5/M08_DECISION_REQUIRED.md)")
        return rule


def analyze(spec: GameSpec, catalog: list[GameSpec], ranges: dict[str, Any], rules: Rules) -> dict[str, Any]:
    """The P5-M8 analysis for one new game: the value table, then the four Q3-decided outputs."""
    if any(game.season >= spec.season for game in catalog):
        raise ValueError("the catalog must hold only games from before the analysed game (DM1 leakage rule)")
    table = value_table(spec)
    return {"value_table": table,
            "similarity": {"label": DESCRIPTIVE, "rule_version": rules.version,
                           "games": rules.require("similarity")(spec, catalog)},
            "candidate_archetypes": {"label": NOT_VALIDATED, "rule_version": rules.version,
                                     "archetypes": rules.require("candidate_archetypes")(spec, table)},
            "expected_scoring_ranges": {"label": NOT_VALIDATED, "rule_version": rules.version,
                                        "ranges": rules.require("expected_ranges")(spec, ranges)},
            "predicted_dominant_components": {"label": NOT_VALIDATED, "rule_version": rules.version,
                                              "components": rules.require("dominant_components")(spec, table)}}
