"""Roles and permissions.

Three roles. An administrator holds every permission, always; the strategy (drive team) and scouter roles hold a
per-workspace, administrator-configurable subset of CONFIGURABLE_PERMISSIONS, starting from DEFAULT_GRANTS.

The administrative permissions (ADMIN_ONLY_PERMISSIONS) cannot be granted to any other role: they are not in
CONFIGURABLE_PERMISSIONS, configure_role refuses them, and the database's CHECK constraint on
workspace_role_permissions cannot store them. That is what stops an ordinary member, or a mistaken configuration,
from handing out team management or the right to change permissions.
"""

from __future__ import annotations

from typing import Mapping

ADMIN, STRATEGY, SCOUTER = "admin", "strategy", "scouter"
ROLES = (ADMIN, STRATEGY, SCOUTER)
CONFIGURABLE_ROLES = (STRATEGY, SCOUTER)
ROLE_LABELS = {ADMIN: "Administrator", STRATEGY: "Drive team / strategy", SCOUTER: "Scouter"}

# Configurable permissions, with what each one opens. The keys must match the CHECK constraint on
# workspace_role_permissions in the latest migration that defines it (0012, redefined by 0013;
# tests/test_workspaces_units.py checks they do).
CONFIGURABLE_PERMISSIONS: dict[str, str] = {
    "team_info": "Event, team and match information (event lists, rosters, schedules, historical seasons)",
    "match_predictions": "Match predictions: win probability, event rankings, alliance synergy",
    "team_analytics": "Team analytics: team metrics and team strength",
    "event_analysis": "Event analysis",
    "qualification_forecast": "Qualification forecasts",
    "alliance_selection": "Alliance selection: candidates and pick lists, and the team's live draft board",
    # Phase 11 (P11-Q2): administrators always hold it; granting it to a role delegates the recording.
    "alliance_selection_record": "Recording live alliance-selection actions (picks, declines, corrections)",
    "strategy_tools": "Match strategy tools, pre-match reports and briefings",
    "scouting_forms": "Scouting forms and one's own assignments and submissions",
    "scouting_submit": "Submitting scouting reports",
    "scouting_view": "Every scouting report of the team, and the team's scouting summary",
    "scouting_assign": "Assigning scouts to matches",
}
ADMIN_ONLY_PERMISSIONS: dict[str, str] = {
    "team_management": "Team Management: members, invitations, roles, suspension and removal",
    "manage_permissions": "Changing what each role may do",
    "team_settings": "Team settings",
    "activity_log": "The team's activity log",
}
ALL_PERMISSIONS = {**CONFIGURABLE_PERMISSIONS, **ADMIN_ONLY_PERMISSIONS}

DEFAULT_GRANTS: dict[str, frozenset[str]] = {
    STRATEGY: frozenset({"team_info", "match_predictions", "team_analytics", "event_analysis",
                         "qualification_forecast", "alliance_selection", "strategy_tools", "scouting_forms",
                         "scouting_view", "scouting_assign"}),
    SCOUTER: frozenset({"team_info", "scouting_forms", "scouting_submit"}),
}


def default_role_grants() -> dict[str, dict[str, bool]]:
    """Every configurable permission for each configurable role, granted or not, as a new workspace starts."""
    return {role: {permission: permission in DEFAULT_GRANTS[role] for permission in CONFIGURABLE_PERMISSIONS}
            for role in CONFIGURABLE_ROLES}


def effective_permissions(role: str, grants: Mapping[str, bool]) -> frozenset[str]:
    """What a member of role holds, given the workspace's stored grants for that role.

    A permission with no stored row falls back to its default, so a permission added in a later release reaches
    existing workspaces with its documented default instead of silently off."""
    if role == ADMIN:
        return frozenset(ALL_PERMISSIONS)
    if role not in CONFIGURABLE_ROLES:
        return frozenset()
    return frozenset(permission for permission in CONFIGURABLE_PERMISSIONS
                     if grants.get(permission, permission in DEFAULT_GRANTS[role]))
