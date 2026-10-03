"""The P5-M8/P5-M9 rules decided as P5-D13 (Kanav, 2026-10-03, before the DM1 dry run).

**Rule 1, similarity.**
- **Period-share vector:** each period's max points per scoring unit × that period's seconds, normalized to shares
  over (auto, teleop, endgame).
- **Similarity:** the cosine similarity of the two games' period-share vectors, plus the Jaccard overlap of their
  field-element types.
- **Reported:** both terms and their sum. There is no threshold.
- **"Most similar":** the largest sum; ties go to the more recent season.

**Rule 2, candidate archetypes.**
- **Mapping:** a human-authored action-type → function mapping (`ActionFunctionMap`), frozen (hashed) before the
  dry run.
- **Proposed:** only codebook functions whose action type occurs among the new spec's scoring actions. Each
  candidate is one codebook function, with its family and the actions behind it.

**Rule 3, expected scoring ranges.**
- **Source season:** the most similar catalog season that has breakdown ranges (P5-M7 adapters).
- **Per component:** that season's P10, median and P90.
  - auto, teleop and endgame are rescaled by the ratio of the two games' max points per unit in that period;
  - fouls are not a period, so they are not rescaled (ratio 1).
- **Labelled** `not_validated`.

**Rule 4, dominant component.**
- **Predicted:** components ordered by expected-range median; the first is dominant.
- **Actual** (scored later, P5-M9 (b)): the largest mean share in FRC competition weeks 1–3 of 2026 (TBA weeks
  0–2).

The κ gate and the reconciliation are in data.design_reference. Every human artifact is an input; none is generated
here.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, Field

from data.design_reference import Codebook, Coding
from data.game_spec import GameSpec
from ml.gameanalysis.analysis import Rules, value_table

VERSION = "P5-D13"
PERIODS = ("auto", "teleop", "endgame")
RANGE_COMPONENTS = ("auto", "teleop", "endgame", "fouls")
NOT_VALIDATED = "not_validated"


class ActionFunctionMap(BaseModel):
    """Human-authored before the reveal: scoring-action type -> codebook functions."""

    version: str = Field(min_length=1)
    authored_by: str = Field(min_length=1)
    codebook_sha256: str = Field(min_length=64, max_length=64)
    mapping: dict[str, list[str]] = Field(min_length=1)

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode("utf-8")).hexdigest()


def period_shares(spec: GameSpec) -> dict[str, float]:
    periods = value_table(spec)["periods"]
    raw = {p: periods[p]["max_points_per_unit"] * periods[p]["period_seconds"] if p in periods else 0.0
           for p in PERIODS}
    total = sum(raw.values())
    return {p: (raw[p] / total if total else 0.0) for p in PERIODS}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a[p] * b[p] for p in PERIODS)
    norm = math.sqrt(sum(a[p] ** 2 for p in PERIODS)) * math.sqrt(sum(b[p] ** 2 for p in PERIODS))
    return dot / norm if norm else 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def similarity(spec: GameSpec, catalog: list[GameSpec]) -> list[dict[str, Any]]:
    mine = period_shares(spec)
    types = {e.element_type for e in spec.field_elements}
    out = []
    for game in catalog:
        cosine = _cosine(mine, period_shares(game))
        jaccard = _jaccard(types, {e.element_type for e in game.field_elements})
        out.append({"season": game.season, "game": game.game_name, "cosine_period_shares": cosine,
                    "jaccard_field_element_types": jaccard, "similarity": cosine + jaccard})
    return sorted(out, key=lambda g: (-g["similarity"], -g["season"]))


def candidate_archetypes(spec: GameSpec, codebook: Codebook, action_map: ActionFunctionMap) -> list[dict[str, Any]]:
    if action_map.codebook_sha256 != codebook.sha256():
        raise ValueError("the action->function map was authored against a different codebook")
    unknown = {f for fs in action_map.mapping.values() for f in fs} - set(codebook.functions)
    if unknown:
        raise ValueError(f"the action->function map names functions outside the codebook: {sorted(unknown)}")
    actions: dict[str, list[str]] = {}
    for action in spec.scoring_actions:
        for function in action_map.mapping.get(action.action_type, []):
            actions.setdefault(function, []).append(action.action_id)
    return [{"archetype": f, "family": codebook.functions[f], "functions": [f], "from_actions": sorted(ids)}
            for f, ids in sorted(actions.items())]


def _max_points(spec: GameSpec) -> dict[str, float]:
    periods = value_table(spec)["periods"]
    return {p: periods[p]["max_points_per_unit"] for p in PERIODS if p in periods}


def expected_ranges(spec: GameSpec, catalog: list[GameSpec], ranges: dict[str, Any]) -> dict[str, Any]:
    with_ranges = {int(s) for s in ranges["seasons"]}
    ranked = [g for g in similarity(spec, catalog) if g["season"] in with_ranges]
    if not ranked:
        raise ValueError("no catalog season has breakdown ranges")
    source = ranked[0]["season"]
    source_spec = next(g for g in catalog if g.season == source)
    mine, theirs = _max_points(spec), _max_points(source_spec)
    out: dict[str, Any] = {"label": NOT_VALIDATED, "source_season": source, "components": {}}
    for component in RANGE_COMPONENTS:
        base = ranges["seasons"][str(source)][component]
        if component == "fouls":
            ratio: float | None = 1.0
        elif mine.get(component) is None or not theirs.get(component):
            ratio = None
        else:
            ratio = mine[component] / theirs[component]
        out["components"][component] = (
            {"ratio": None, "reason": "period absent from one of the games", "low": None, "median": None, "high": None}
            if ratio is None else
            {"ratio": ratio, "low": base["p10"] * ratio, "median": base["p50"] * ratio, "high": base["p90"] * ratio})
    return out


def dominant_components(expected: dict[str, Any]) -> list[str]:
    medians = {c: v["median"] for c, v in expected["components"].items() if v["median"] is not None}
    return sorted(medians, key=lambda c: (-medians[c], c))


def build_rules(catalog: list[GameSpec], codebook: Codebook, action_map: ActionFunctionMap,
                consensus: Coding) -> Rules:
    """The decided rule set, bound to the human-authored artifacts it needs."""
    cache: dict[str, Any] = {}

    def ranges_rule(spec: GameSpec, ranges: dict[str, Any]) -> dict[str, Any]:
        cache["expected"] = expected_ranges(spec, catalog, ranges)
        return cache["expected"]

    return Rules(
        version=VERSION,
        similarity=lambda spec, games: similarity(spec, games),
        candidate_archetypes=lambda spec, table: candidate_archetypes(spec, codebook, action_map),
        expected_ranges=ranges_rule,
        dominant_components=lambda spec, table: dominant_components(cache["expected"]),
        reconcile_codings=lambda first, second: consensus,
        notes={"action_function_map_sha256": action_map.sha256(), "codebook_sha256": codebook.sha256()},
    )
