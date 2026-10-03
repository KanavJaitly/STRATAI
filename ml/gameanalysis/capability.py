"""P5-M9 team capability intake and the human-authored capability→archetype feasibility rubric.

docs/P5Milestones.md, P5-M9 (frozen at P5-M0).

**Intake.** A form covering budget, manufacturing, programming and mentor resources. It is stored raw first,
through the Phase 2 landing writer (source `capability_intake`), before it is validated.

**The rubric** is deterministic and **human-authored**. The curated design dataset has no resource, cost or
complexity data, so the rubric is not derived from it. Each archetype lists:
- the capabilities it requires (minimum levels and budget);
- a tier, the realism ceiling;
- its achievable features.

**Evaluation:**
- an archetype is feasible when every requirement is met;
- the realistic ceiling is the highest feasible tier;
- the recommended archetype is the feasible candidate (from P5-M8) with the rubric's highest priority;
- the explanation lists every requirement met and unmet.

There is no LLM. Every output is labelled `heuristic_not_validated_against_outcomes`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

HEURISTIC = "heuristic_not_validated_against_outcomes"
Level = Literal[0, 1, 2, 3]  # 0 none, 1 basic, 2 intermediate, 3 advanced
CAPABILITIES = ("manufacturing", "programming", "mentoring")
INTAKE_SOURCE, INTAKE_OBJECT_TYPE = "capability_intake", "team_profile"


class CapabilityIntake(BaseModel):
    profile_id: str = Field(min_length=1)
    team_number: int | None = Field(default=None, ge=1)
    budget_usd: float = Field(ge=0)
    manufacturing: Level
    programming: Level
    mentoring: Level
    notes: str = ""
    submitted_at: datetime


class ArchetypeRule(BaseModel):
    archetype: str = Field(min_length=1)
    tier: int = Field(ge=1, description="realism ceiling: higher means more demanding")
    priority: int = Field(description="lower is preferred among feasible candidates")
    min_budget_usd: float = Field(ge=0)
    min_levels: dict[str, int]
    achievable_features: list[str]

    @model_validator(mode="after")
    def _known(self) -> ArchetypeRule:
        unknown = set(self.min_levels) - set(CAPABILITIES)
        if unknown:
            raise ValueError(f"unknown capabilities {sorted(unknown)}")
        return self


class Rubric(BaseModel):
    version: str = Field(min_length=1)
    authored_by: str = Field(min_length=1, description="a person; the rubric is human-authored")
    season: int
    archetypes: list[ArchetypeRule] = Field(min_length=1)

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def land_intake(writer, payload: dict) -> CapabilityIntake:
    """Raw first: land the untouched form payload, then validate it (a bad form stays recorded)."""
    from data.landing.raw_writer import RawPayloadRecord

    writer.write(RawPayloadRecord(INTAKE_SOURCE, INTAKE_OBJECT_TYPE, str(payload.get("profile_id")), payload))
    return CapabilityIntake.model_validate(payload)


def _requirements(profile: CapabilityIntake, rule: ArchetypeRule) -> tuple[list[str], list[str]]:
    met, unmet = [], []
    budget = f"budget >= {rule.min_budget_usd:g} (have {profile.budget_usd:g})"
    (met if profile.budget_usd >= rule.min_budget_usd else unmet).append(budget)
    for capability, level in sorted(rule.min_levels.items()):
        have = getattr(profile, capability)
        (met if have >= level else unmet).append(f"{capability} >= {level} (have {have})")
    return met, unmet


def recommend(profile: CapabilityIntake, rubric: Rubric, candidate_archetypes: list[str]) -> dict:
    """Deterministic rubric application (see the module docstring)."""
    evaluated = []
    for rule in sorted(rubric.archetypes, key=lambda r: (r.priority, r.archetype)):
        met, unmet = _requirements(profile, rule)
        evaluated.append({"archetype": rule.archetype, "tier": rule.tier, "priority": rule.priority,
                          "feasible": not unmet, "candidate": rule.archetype in candidate_archetypes,
                          "requirements_met": met, "requirements_unmet": unmet,
                          "achievable_features": rule.achievable_features if not unmet else []})
    feasible = [e for e in evaluated if e["feasible"]]
    chosen = next((e for e in feasible if e["candidate"]), None)
    return {"label": HEURISTIC, "profile_id": profile.profile_id, "rubric_version": rubric.version,
            "rubric_sha256": rubric.sha256(),
            "realistic_ceiling_tier": max((e["tier"] for e in feasible), default=None),
            "recommended_archetype": None if chosen is None else chosen["archetype"],
            "achievable_features": [] if chosen is None else chosen["achievable_features"],
            "explanation": evaluated}
