from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class EventSummary(BaseModel):
    """Minimal TBA event summary model."""

    key: str
    name: str
    event_code: str | None = None
    season: int
    start_date: date | None = None
    end_date: date | None = None


class Match(BaseModel):
    """Minimal TBA match metadata model."""

    key: str
    event_key: str
    competition_level: str | None = None
    set_number: int | None = None
    match_number: int | None = None
    scheduled_time: str | None = None
    score_red: int | None = None
    score_blue: int | None = None
    winning_alliance: str | None = None


class TeamInfo(BaseModel):
    """Minimal TBA team profile model."""

    key: str
    team_number: int
    nickname: str | None = None
    city: str | None = None
    state_prov: str | None = None
    country: str | None = None
    rookie_year: int | None = None
    website: str | None = None
    school_name: str | None = None
    motto: str | None = None
