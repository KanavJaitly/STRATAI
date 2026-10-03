"""P5-M8 structured game specification: a versioned schema, entered by a person from the game manual.

docs/P5Milestones.md, P5-M8 (frozen at P5-M0). A spec records the following, each with the manual sections it
came from:
- the match length per period;
- the scoring actions, with points by period;
- the endgame actions;
- the ranking-point rules;
- the field elements.

**No LLM parses the manual; no spec is generated.** A spec carries who entered it and when entry began, the start
of DM1's 5-day clock (P5-M9).

**The catalog** is a directory of spec files plus a manifest of their sha256s. `load_catalog` verifies every file
against the manifest, and `before_reveal` keeps only games from before a simulated reveal year (the DM1 leakage
rule).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "p5-game-spec-v1"
Period = Literal["auto", "teleop", "endgame"]
CATALOG_MANIFEST = "catalog_manifest.json"


class ScoringAction(BaseModel):
    action_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    period: Period
    points: float = Field(ge=0)
    unit: str = Field(min_length=1, description="what one scoring of the action is, e.g. 'game piece in the hub'")
    field_element_id: str | None = None
    manual_section: str = Field(min_length=1)


class RankingPointRule(BaseModel):
    rule_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    ranking_points: float = Field(gt=0)
    manual_section: str = Field(min_length=1)


class FieldElement(BaseModel):
    element_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    count: int = Field(ge=1)
    manual_section: str = Field(min_length=1)


class MatchLength(BaseModel):
    auto_seconds: int = Field(gt=0)
    teleop_seconds: int = Field(gt=0, description="including the endgame")
    endgame_seconds: int = Field(ge=0)

    @model_validator(mode="after")
    def _endgame_within_teleop(self) -> MatchLength:
        if self.endgame_seconds > self.teleop_seconds:
            raise ValueError("endgame_seconds exceeds teleop_seconds")
        return self


class SpecSource(BaseModel):
    manual_title: str = Field(min_length=1)
    manual_version: str = Field(min_length=1)
    entered_by: str = Field(min_length=1, description="the person who entered the spec from the manual")
    entry_started_at: datetime
    entry_completed_at: datetime
    llm_used: Literal[False] = False  # the core never lets an LLM parse the manual

    @model_validator(mode="after")
    def _ordered(self) -> SpecSource:
        if self.entry_started_at.tzinfo is None or self.entry_completed_at.tzinfo is None:
            raise ValueError("entry times must carry a timezone")
        if self.entry_completed_at < self.entry_started_at:
            raise ValueError("entry_completed_at precedes entry_started_at")
        return self


class GameSpec(BaseModel):
    schema_version: Literal["p5-game-spec-v1"] = SCHEMA_VERSION
    season: int = Field(ge=1992)
    game_name: str = Field(min_length=1)
    match_length: MatchLength
    scoring_actions: list[ScoringAction] = Field(min_length=1)
    ranking_point_rules: list[RankingPointRule]
    field_elements: list[FieldElement]
    source: SpecSource

    @model_validator(mode="after")
    def _consistent(self) -> GameSpec:
        ids = [a.action_id for a in self.scoring_actions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scoring action ids")
        elements = {e.element_id for e in self.field_elements}
        unknown = sorted({a.field_element_id for a in self.scoring_actions if a.field_element_id} - elements)
        if unknown:
            raise ValueError(f"scoring actions reference unknown field elements {unknown}")
        if any(a.period == "endgame" for a in self.scoring_actions) and self.match_length.endgame_seconds == 0:
            raise ValueError("endgame scoring actions but no endgame period")
        return self

    def sha256(self) -> str:
        return hashlib.sha256(canonical_spec_bytes(self)).hexdigest()


def canonical_spec_bytes(spec: GameSpec) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_spec(path: Path) -> GameSpec:
    return GameSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))


class CatalogIntegrityError(RuntimeError):
    """A catalog file is missing, unlisted, or does not match its manifest sha256."""


def write_catalog_manifest(directory: Path) -> dict[str, str]:
    """Record the sha256 of every spec file in the catalog directory (run once, after human entry)."""
    entries = {}
    for path in sorted(Path(directory).glob("*.json")):
        if path.name == CATALOG_MANIFEST:
            continue
        load_spec(path)  # validates
        entries[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (Path(directory) / CATALOG_MANIFEST).write_text(json.dumps(entries, indent=1, sort_keys=True) + "\n",
                                                   encoding="utf-8")
    return entries


def load_catalog(directory: Path) -> list[GameSpec]:
    """Every spec in the catalog, each verified against the manifest; seasons must be unique."""
    directory = Path(directory)
    manifest_path = directory / CATALOG_MANIFEST
    if not manifest_path.exists():
        raise CatalogIntegrityError(f"{directory} has no {CATALOG_MANIFEST}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = sorted(p.name for p in directory.glob("*.json") if p.name != CATALOG_MANIFEST)
    if files != sorted(manifest):
        raise CatalogIntegrityError(f"catalog files {files} do not match the manifest {sorted(manifest)}")
    specs = []
    for name in files:
        data = (directory / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest[name]:
            raise CatalogIntegrityError(f"{name} does not match its manifest sha256")
        specs.append(GameSpec.model_validate_json(data))
    seasons = [s.season for s in specs]
    if len(seasons) != len(set(seasons)):
        raise CatalogIntegrityError("two catalog specs share a season")
    return sorted(specs, key=lambda s: s.season)


def before_reveal(specs: list[GameSpec], reveal_season: int) -> list[GameSpec]:
    """DM1 leakage rule: only games from before the simulated reveal year."""
    return [s for s in specs if s.season < reveal_season]
