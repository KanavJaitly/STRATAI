from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class StagingTeam(BaseModel):
    """Canonical representation of an FRC team, independent of source.

    `name` is the team's commonly-used short name (TBA's "nickname"), not its
    long legal/school name -- that's what every dashboard, report, and coach
    actually calls a team day-to-day, so it's what the canonical model uses.
    """

    team_number: int
    name: str | None = None
    city: str | None = None
    state_province: str | None = None
    country: str | None = None
    rookie_year: int | None = None


class StagingEvent(BaseModel):
    """Canonical representation of a single FRC competition event."""

    event_key: str
    name: str
    season: int
    event_code: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    city: str | None = None
    state_province: str | None = None
    country: str | None = None


class StagingTeamEventStats(BaseModel):
    """Canonical representation of one team's performance at one event.

    Keyed by (team_number, event_key) so it joins directly against StagingTeam
    and StagingEvent regardless of source. Populated from Statbotics's EPA-based
    team-event metrics (see StatboticsTeamEventMetrics), which landed in the raw
    layer in Milestone 5; this is the first staging entity that does NOT derive
    from The Blue Alliance.

    `matches_played` is derived (wins + losses + ties) rather than sourced --
    Statbotics reports the win/loss/tie breakdown but no explicit game count,
    and the derived total is only meaningful when all three are present, so it
    is left None if any component is missing rather than silently undercounting.
    """

    team_number: int
    event_key: str
    season: int
    epa_total: float | None = None
    epa_auto: float | None = None
    epa_teleop: float | None = None
    epa_endgame: float | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    matches_played: int | None = None


class StagingMatch(BaseModel):
    """Canonical representation of a single FRC match, independent of source.

    Deliberately flattens TBA's nested alliances.{red,blue}.{score,teams}
    structure and strips source-specific team-key prefixes (e.g. "frc1114"
    becomes the plain int 1114): alliance nesting and key formatting are TBA
    implementation details, not StratAI domain concepts. Team numbers here
    are directly joinable with StagingTeam.team_number regardless of which
    source produced either record.

    `competition_level` uses a controlled vocabulary (qualification /
    quarterfinal / semifinal / final) rather than a source's raw abbreviation
    codes (TBA's "qm"/"qf"/"sf"/"f"). An unrecognized level from a future
    source is preserved as its own lowercased string rather than rejected --
    losing knowledge of *what kind* of match this was is worse than not
    having it fit the known vocabulary exactly.

    `winning_alliance` is one of "red", "blue", "tie", or None (not yet
    played) -- collapsing TBA's ambiguous empty-string convention (which
    conflates "not played" and "tie") into a single unambiguous enum.
    """

    match_key: str
    event_key: str
    season: int
    competition_level: str
    match_number: int | None = None
    set_number: int | None = None
    scheduled_time: datetime | None = None
    red_teams: list[int] = Field(default_factory=list)
    blue_teams: list[int] = Field(default_factory=list)
    red_score: int | None = None
    blue_score: int | None = None
    winning_alliance: str | None = None
