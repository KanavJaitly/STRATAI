from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class EventSummary(BaseModel):
    """Minimal TBA event summary model.

    TBA's raw API calls this field "year", not "season" — verified against
    external documentation after the original field name ("season") turned
    out to not exist in TBA's real API at all, meaning this model would have
    raised a validation error on every real event payload. The alias accepts
    the real wire field while keeping the "season" attribute name used
    consistently everywhere else in this codebase (database columns, other
    models, etc).
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    name: str
    event_code: str | None = None
    season: int = Field(alias="year")
    start_date: date | None = None
    end_date: date | None = None


class MatchAllianceResult(BaseModel):
    """One alliance's roster and score within a single TBA match."""

    model_config = ConfigDict(populate_by_name=True)

    score: int | None = None
    team_keys: list[str] = Field(default_factory=list, alias="teams")


class MatchAlliances(BaseModel):
    """The red/blue alliance results nested under a TBA match's "alliances" key."""

    red: MatchAllianceResult = Field(default_factory=MatchAllianceResult)
    blue: MatchAllianceResult = Field(default_factory=MatchAllianceResult)


class Match(BaseModel):
    """Minimal TBA match metadata model.

    Two real defects were fixed here: TBA's raw field is "comp_level", not
    "competition_level", and match scores/team rosters are nested under an
    "alliances": {"red": {...}, "blue": {...}} object, not flat score_red/
    score_blue fields — this model previously had no way to know which teams
    played a match at all. "scheduled_time" maps to TBA's "time" field, which
    is a Unix epoch integer, not a string.
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    event_key: str
    competition_level: str | None = Field(default=None, alias="comp_level")
    set_number: int | None = None
    match_number: int | None = None
    scheduled_time: int | None = Field(default=None, alias="time")
    alliances: MatchAlliances = Field(default_factory=MatchAlliances)
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
