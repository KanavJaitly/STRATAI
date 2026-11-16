"""Roles and permissions.

Two roles. An administrator holds every permission, always. A base member holds exactly ROLE_GRANTS[BASE]: read-only
access to the events list and an event's page (the routes those two pages call), and nothing else.

Grants are fixed in code, not configurable per team (migration 0015 dropped the stored role permissions), so no
administrator action can widen what a base member sees. To add a role later: add its name to ROLES and ROLE_LABELS,
give it an entry in ROLE_GRANTS, and extend the role CHECK constraint on team_memberships in a migration.
"""

from __future__ import annotations

ADMIN, BASE = "admin", "base"
ROLES = (ADMIN, BASE)
ROLE_LABELS = {ADMIN: "Administrator", BASE: "Member"}

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
ROLE_GRANTS: dict[str, frozenset[str]] = {
    BASE: frozenset({"team_info", "event_analysis", "qualification_forecast"}),
}


def effective_permissions(role: str) -> frozenset[str]:
    """What a member of role holds. An unknown role holds nothing."""
    if role == ADMIN:
        return frozenset(ALL_PERMISSIONS)
    return ROLE_GRANTS.get(role, frozenset())
