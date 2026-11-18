"""Roles and permissions.

Five roles (2026-11-17; migration 0016 added strategy, drive and scout). An administrator holds every permission,
always; mentors are administrators. Every other role holds exactly its ROLE_GRANTS entry:
- base (Member): the events list and an event's page, read-only;
- scout: those, plus the scouting forms, their own assignments and submissions;
- drive (Drive team): those, plus match win probability, team pages and the drive team page with the strategy
  engine's match plan, read-only (match_plan_view; not the other strategy tools);
- strategy (Strategy team): event data, match strategy tools and reports, alliance selection including recording the
  live draft, every scouting report and assigning scouts.
New sign-ups are members; an administrator changes a role in Team > Members.

Grants are fixed in code, not configurable per team (migration 0015 dropped the stored role permissions), so no
administrator action can widen what a role sees. To add a role later: add its name to ROLES and ROLE_LABELS,
give it an entry in ROLE_GRANTS, and extend the role CHECK constraint on team_memberships in a migration.
"""

from __future__ import annotations

ADMIN, BASE, STRATEGY, DRIVE, SCOUT = "admin", "base", "strategy", "drive", "scout"
ROLES = (ADMIN, BASE, STRATEGY, DRIVE, SCOUT)  # the order of migration 0016's role CHECK
ROLE_LABELS = {ADMIN: "Administrator", BASE: "Member", STRATEGY: "Strategy team", DRIVE: "Drive team", SCOUT: "Scout"}

# Every permission, with what it opens. api/app.py gates each router on one of these; the /workspace routes check
# theirs directly.
ALL_PERMISSIONS: dict[str, str] = {
    "team_info": "Events, rosters and match schedules (the events list and an event's page)",
    "event_analysis": "Event analysis",
    "qualification_forecast": "Qualification forecasts",
    "season_explorer": "The historical season explorer",
    "match_predictions": "Match predictions: win probability, event rankings, alliance synergy",
    "team_analytics": "Team analytics: team metrics and team strength",
    "alliance_selection": "Alliance selection: candidates and pick lists, and the team's live draft board",
    "alliance_selection_record": "Recording live alliance-selection actions (picks, declines, corrections)",
    "strategy_tools": "Match strategy tools, pre-match reports and briefings",
    "match_plan_view": "The strategy engine's recommended plan for a scheduled match, read-only (the Drive team page)",
    "platform_inputs": "Game manuals, rulesets, capability profiles and readiness",
    "scouting_forms": "Scouting forms and one's own assignments and submissions",
    "scouting_submit": "Submitting scouting reports",
    "scouting_view": "Every scouting report of the team, and the team's scouting summary",
    "scouting_assign": "Assigning scouts to matches",
    "team_overview": "The team overview: team settings, member count",
    "team_management": "Members: see them, change a role, remove someone",
    "team_settings": "Team settings",
    "activity_log": "The team's activity log",
}

# What each role other than admin holds. Base is read-only: the events list (/) and an event's page (/events/:key).
_EVENT_DATA = {"team_info", "event_analysis", "qualification_forecast"}

ROLE_GRANTS: dict[str, frozenset[str]] = {
    BASE: frozenset(_EVENT_DATA),
    SCOUT: frozenset(_EVENT_DATA | {"scouting_forms", "scouting_submit"}),
    DRIVE: frozenset(_EVENT_DATA | {"match_predictions", "team_analytics", "match_plan_view"}),
    STRATEGY: frozenset(_EVENT_DATA | {"match_predictions", "team_analytics", "strategy_tools", "alliance_selection",
                                       "alliance_selection_record", "scouting_view", "scouting_assign"}),
}


def effective_permissions(role: str) -> frozenset[str]:
    """What a member of role holds. An unknown role holds nothing."""
    if role == ADMIN:
        return frozenset(ALL_PERMISSIONS)
    return ROLE_GRANTS.get(role, frozenset())
