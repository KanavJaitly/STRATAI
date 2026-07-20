from __future__ import annotations

from datetime import date

from pydantic import BaseModel


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


class StatboticsMatchStats(BaseModel):
    """Minimal Statbotics EPA-based match statistics model."""

    key: str
    event: str
    predicted_winner: str | None = None
    red_win_prob: float | None = None
    red_score_pred: float | None = None
    blue_score_pred: float | None = None


class StatboticsTeamEventMetrics(BaseModel):
    """Minimal Statbotics EPA-based team-event performance metrics model.

    Field names intentionally mirror the team_event_stats table columns from
    the database schema, since this is the data those columns exist to hold
    once a later staging milestone starts populating them.
    """

    team: int
    event: str
    epa_total: float | None = None
    epa_auto: float | None = None
    epa_teleop: float | None = None
    epa_endgame: float | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
