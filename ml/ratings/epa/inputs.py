"""The engine's canonical inputs (docs/ratings/data_contract.md §3).

These are the only way data reaches the engine. They hold what STRATAI stores
(canonical tables plus the untouched raw TBA payload); a reader outside this
package builds them, and nothing here knows where they came from. Structural
typing is enforced here; semantic checks that produce exclusion codes live in
ml.ratings.epa.validation, because an excluded match is an observable outcome,
not a construction error.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CompLevel = Literal["qm", "ef", "qf", "sf", "f"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventInput(_Frozen):
    """One TBA event, before any filtering."""

    event_key: str
    event_type: int = Field(description="TBA event_type integer")
    week: int | None = Field(description="TBA week, unadjusted (spec §2.1 adjusts it)")
    district: str | None = Field(default=None, description="TBA district abbreviation")


class AllianceInput(_Frozen):
    """One alliance of one match, exactly as TBA reported it."""

    teams: tuple[int, ...]
    dq_teams: tuple[int, ...] = ()
    surrogate_teams: tuple[int, ...] = ()
    score: int | None = Field(description="None or negative = not played")
    breakdown: dict[str, Any] | None = Field(description="raw TBA alliance score_breakdown, untouched")


class MatchInput(_Frozen):
    """One TBA match, before any filtering."""

    match_key: str
    event_key: str
    comp_level: CompLevel
    set_number: int
    match_number: int
    time: int | None = Field(description="TBA scheduled time, epoch seconds")
    red: AllianceInput
    blue: AllianceInput

    @property
    def elim(self) -> bool:
        return self.comp_level != "qm"


class PriorTeamYear(_Frozen):
    """One earlier season's year-normalized EPA for one team (spec §4.5)."""

    season: int
    norm_epa: int | None = Field(
        description="the reference's integer norm_epa; None = the TeamYear exists but has no value"
    )


class PriorSeasonInput(_Frozen):
    """Explicit prior-season history. The engine never fills this in itself."""

    source: str = Field(min_length=1, description="where these values came from (provenance)")
    team_years: dict[int, tuple[PriorTeamYear, ...]]

    @model_validator(mode="after")
    def _one_value_per_team_season(self) -> PriorSeasonInput:
        for team, years in self.team_years.items():
            seasons = [y.season for y in years]
            if len(seasons) != len(set(seasons)):
                raise ValueError(f"team {team} has more than one PriorTeamYear for the same season")
        return self


class SeasonInput(_Frozen):
    """Everything one season's run consumes."""

    season: int
    events: tuple[EventInput, ...]
    matches: tuple[MatchInput, ...]
    prior: PriorSeasonInput | None = Field(
        default=None, description='None = "initialized without prior-season history"'
    )
    team_districts: dict[int, str] | None = Field(
        default=None,
        description="team -> TBA district abbreviation this season; needed only for the 2026 isr rule",
    )


def canonical_json(value: Any) -> str:
    """The one serialization every fingerprint and determinism check uses."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def canonical_season_payload(season_input: SeasonInput) -> dict[str, Any]:
    """SeasonInput as plain data with every collection in a fixed order.

    Events sort by event_key and matches by match_key, so two inputs that hold
    the same records in a different order have the same fingerprint.
    """
    payload = season_input.model_dump(mode="json")
    payload["events"] = sorted(payload["events"], key=lambda e: e["event_key"])
    payload["matches"] = sorted(payload["matches"], key=lambda m: m["match_key"])
    if payload["prior"] is not None:
        payload["prior"]["team_years"] = {
            team: sorted(years, key=lambda y: y["season"])
            for team, years in sorted(payload["prior"]["team_years"].items(), key=lambda kv: int(kv[0]))
        }
    return payload


def fingerprint(value: Any) -> str:
    """sha256 of canonical_json(value)."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def season_input_fingerprint(season_input: SeasonInput) -> str:
    """Order-independent sha256 of a SeasonInput."""
    return fingerprint(canonical_season_payload(season_input))
