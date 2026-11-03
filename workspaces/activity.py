"""The team activity log: who did what to whom, and when (activity_logs).

Every entry is written inside the same transaction as the change it records, so a change and its log entry are
committed together or not at all. Entries are never updated or deleted by the application.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

# The vocabulary of recorded actions, with the label the Activity Log shows for each.
ACTIONS: dict[str, str] = {
    "workspace_registered": "Team workspace registered",
    "workspace_verified": "Team ownership verified",
    "workspace_rejected": "Team registration rejected",
    "initial_admin_created": "First administrator created",
    "account_created": "Account created",
    "member_invited": "Member invited",
    "invitation_resent": "Invitation resent",
    "invitation_revoked": "Invitation revoked",
    "invitation_accepted": "Invitation accepted",
    "role_changed": "Role changed",
    "member_updated": "Member details edited",
    "member_suspended": "Account suspended",
    "member_reactivated": "Account reactivated",
    "member_removed": "Member removed",
    "password_reset_issued": "Password reset link issued",
    "password_reset_completed": "Password reset",
    "password_changed": "Password changed",
    "permissions_changed": "Role permissions changed",
    "settings_changed": "Team settings changed",
    "scouting_assignment_created": "Scouting assignment created",
    "scouting_assignment_cancelled": "Scouting assignment cancelled",
}


def record(cursor: Any, *, workspace_id: int, actor_user_id: int | None, actor_label: str, action: str,
           target_user_id: int | None = None, target_label: str | None = None,
           details: dict[str, Any] | None = None) -> None:
    """Append one entry. cursor must belong to the transaction that makes the change being recorded."""
    if action not in ACTIONS:
        raise ValueError(f"unknown activity action {action!r}")
    cursor.execute(
        "INSERT INTO activity_logs (workspace_id, actor_user_id, actor_label, action, target_user_id, target_label, "
        "details) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (workspace_id, actor_user_id, actor_label, action, target_user_id, target_label, Jsonb(details or {})))
