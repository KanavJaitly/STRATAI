"""A team's private scouting: match assignments, scouting reports, and the team's own defense/feeding summary.

**Private to the team.** Reports live in workspace_scouting_reports, never in the shared scouting_observations
table: that table feeds the team_metrics every other team can read, so one team's scouting stored there would reach
its rivals. Every query here filters on the caller's workspace.

**The same rules as the shared scouting path.** A report is validated by the project's own scouting normalizer
(data.metrics.normalizer.normalize_human_scout_observation: rating scale, match/event consistency, at least one
rating), its match must exist and its team must be on that match's roster. The team's summary is built by
data.metrics.aggregation.aggregate_defense_feeding over the team's own reports, unchanged: defense and feeding
come only from what scouts directly recorded (CLAUDE.md's first critical constraint), and below the
two-observation minimum a value is reported as insufficient, never invented.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg

from data.metrics.aggregation import aggregate_defense_feeding
from data.metrics.normalizer import normalize_human_scout_observation
from data.metrics.schemas import ScoutingObservation
from data.metrics.validator import PayloadValidationError
from database.connection import Database
from workspaces import activity
from workspaces.errors import conflict, forbidden, invalid_input, not_found
from workspaces.management import require, require_verified
from workspaces.sessions import SessionContext

MAX_NOTES = 2000


def _match(cursor: Any, match_key: Any) -> tuple:
    if not isinstance(match_key, str) or not match_key:
        raise invalid_input("Choose a match.")
    cursor.execute("SELECT match_key, event_key FROM matches WHERE match_key = %s", (match_key,))
    row = cursor.fetchone()
    if row is None:
        raise not_found("match_not_found", f"Match '{match_key}' is not known to StratAI.")
    return row


def _require_rostered(cursor: Any, match_key: str, team_number: Any) -> int:
    if isinstance(team_number, bool) or not isinstance(team_number, int):
        raise invalid_input("Choose a team.")
    cursor.execute("SELECT 1 FROM match_teams WHERE match_key = %s AND team_number = %s", (match_key, team_number))
    if cursor.fetchone() is None:
        raise invalid_input(f"Team {team_number} does not play in match {match_key}.")
    return team_number


# --- assignments ----------------------------------------------------------------------------------------------

_ASSIGNMENT_SQL = """
SELECT a.id, a.event_key, a.match_key, m.competition_level, m.set_number, m.match_number, m.scheduled_time,
       a.team_number, mt.alliance_color, a.assigned_user_id, COALESCE(am.display_name, u.full_name), a.status,
       a.created_at, EXISTS (SELECT 1 FROM workspace_scouting_reports r WHERE r.workspace_id = a.workspace_id
                             AND r.assignment_id = a.id)
FROM scouting_assignments a
JOIN matches m ON m.match_key = a.match_key
LEFT JOIN match_teams mt ON mt.match_key = a.match_key AND mt.team_number = a.team_number
JOIN team_memberships am ON am.workspace_id = a.workspace_id AND am.user_id = a.assigned_user_id
JOIN users u ON u.id = a.assigned_user_id
WHERE a.workspace_id = %(workspace)s
  AND (%(user)s::bigint IS NULL OR a.assigned_user_id = %(user)s)
  AND (%(event)s::text IS NULL OR a.event_key = %(event)s)
  AND (%(closed)s OR a.status = 'assigned')
ORDER BY m.scheduled_time NULLS LAST, a.match_key, a.team_number, a.id
"""


def _assignment(row: tuple) -> dict[str, Any]:
    (aid, event_key, match_key, level, set_number, match_number, scheduled, team, color, user_id, name, status,
     created, reported) = row
    return {"assignment_id": aid, "event_key": event_key, "match_key": match_key, "competition_level": level,
            "set_number": set_number, "match_number": match_number, "scheduled_time": scheduled,
            "team_number": team, "alliance_color": color, "assigned_user_id": user_id, "assigned_to": name,
            "status": status, "created_at": created, "report_submitted": reported}


def list_scouts(database: Database, context: SessionContext) -> list[dict[str, Any]]:
    """The active members an assignment can name: id, name and role only (no emails, no account details), so the
    strategy role can assign scouts without holding Team Management."""
    require(context, "scouting_assign")
    with database.cursor() as cursor:
        cursor.execute("SELECT m.id, COALESCE(m.display_name, u.full_name), m.role FROM team_memberships m "
                       "JOIN users u ON u.id = m.user_id WHERE m.workspace_id = %s AND m.status = 'active' "
                       "ORDER BY 2, m.id", (context.workspace_id,))
        return [{"membership_id": mid, "name": name, "role": role} for mid, name, role in cursor.fetchall()]


def list_assignments(database: Database, context: SessionContext, *, mine: bool, event_key: str | None = None,
                     include_closed: bool = False) -> list[dict[str, Any]]:
    """One's own assignments (scouting_forms), or the whole team's (scouting_assign or scouting_view)."""
    if mine:
        require(context, "scouting_forms")
    elif not (context.can("scouting_assign") or context.can("scouting_view")):
        require(context, "scouting_assign")
    with database.cursor() as cursor:
        cursor.execute(_ASSIGNMENT_SQL, {"workspace": context.workspace_id, "user": context.user_id if mine else None,
                                         "event": event_key, "closed": include_closed})
        return [_assignment(row) for row in cursor.fetchall()]


def create_assignment(database: Database, context: SessionContext, *, match_key: str, team_number: int,
                      membership_id: int) -> dict[str, Any]:
    """Assign one of the team's active members to scout one team in one match."""
    require(context, "scouting_assign")
    require_verified(context, "Scouting")
    with database.cursor() as cursor:
        match_key, event_key = _match(cursor, match_key)
        team_number = _require_rostered(cursor, match_key, team_number)
        cursor.execute("SELECT m.user_id, COALESCE(m.display_name, u.full_name) FROM team_memberships m "
                       "JOIN users u ON u.id = m.user_id WHERE m.id = %s AND m.workspace_id = %s "
                       "AND m.status = 'active'", (membership_id, context.workspace_id))
        member = cursor.fetchone()
        if member is None:
            raise not_found("member_not_found", "No active member with that id in this team's workspace.")
        user_id, name = member
        try:
            cursor.execute(
                "INSERT INTO scouting_assignments (workspace_id, event_key, match_key, team_number, assigned_user_id, "
                "created_by_user_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (context.workspace_id, event_key, match_key, team_number, user_id, context.user_id))
        except psycopg.errors.UniqueViolation:
            raise conflict("assignment_exists", f"{name} is already assigned to team {team_number} in {match_key}.")
        assignment_id = cursor.fetchone()[0]
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="scouting_assignment_created", target_user_id=user_id,
                        target_label=name, details={"match_key": match_key, "team_number": team_number})
        cursor.execute(_ASSIGNMENT_SQL + "", {"workspace": context.workspace_id, "user": user_id,
                                              "event": event_key, "closed": True})
        return next(_assignment(row) for row in cursor.fetchall() if row[0] == assignment_id)


def cancel_assignment(database: Database, context: SessionContext, assignment_id: int) -> None:
    require(context, "scouting_assign")
    with database.cursor() as cursor:
        cursor.execute("UPDATE scouting_assignments SET status = 'cancelled' WHERE id = %s AND workspace_id = %s "
                       "AND status = 'assigned' RETURNING assigned_user_id, match_key, team_number",
                       (assignment_id, context.workspace_id))
        row = cursor.fetchone()
        if row is None:
            raise not_found("assignment_not_found", "No open assignment with that id in this team's workspace.")
        activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                        actor_label=context.name, action="scouting_assignment_cancelled", target_user_id=row[0],
                        details={"match_key": row[1], "team_number": row[2]})


# --- reports --------------------------------------------------------------------------------------------------


def submit_report(database: Database, context: SessionContext, *, match_key: str, team_number: int,
                  defense_rating: int | None, feeding_rating: int | None, notes: str | None,
                  assignment_id: int | None = None) -> dict[str, Any]:
    """Record one scouting report by the signed-in member, private to the team."""
    require(context, "scouting_submit")
    require_verified(context, "Scouting")
    if notes is not None and (not isinstance(notes, str) or len(notes) > MAX_NOTES):
        raise invalid_input(f"Notes must be text of at most {MAX_NOTES} characters.")
    notes = notes.strip() or None if notes else None
    submitted_at = datetime.now(timezone.utc)
    with database.cursor() as cursor:
        match_key, event_key = _match(cursor, match_key)
        team_number = _require_rostered(cursor, match_key, team_number)
        try:
            normalize_human_scout_observation({
                "match_key": match_key, "event_key": event_key, "team_number": team_number,
                "scout_identifier": f"member-{context.user_id}", "submitted_at": submitted_at.isoformat(),
                "defense_rating": defense_rating, "feeding_rating": feeding_rating, "notes": notes})
        except PayloadValidationError as exc:
            raise invalid_input("; ".join(issue.message for issue in exc.issues) or "The report is not valid.")
        if assignment_id is not None:
            cursor.execute("SELECT match_key, team_number, assigned_user_id, status FROM scouting_assignments "
                           "WHERE id = %s AND workspace_id = %s FOR UPDATE", (assignment_id, context.workspace_id))
            assignment = cursor.fetchone()
            if assignment is None:
                raise not_found("assignment_not_found", "No assignment with that id in this team's workspace.")
            if assignment[2] != context.user_id:
                raise forbidden("not_your_assignment", "That assignment belongs to another scout.")
            if (assignment[0], assignment[1]) != (match_key, team_number):
                raise invalid_input("The report's match and team must match its assignment.")
            if assignment[3] == "cancelled":
                raise conflict("assignment_cancelled", "That assignment was cancelled.")
            cursor.execute("UPDATE scouting_assignments SET status = 'completed' WHERE id = %s", (assignment_id,))
        cursor.execute(
            "INSERT INTO workspace_scouting_reports (workspace_id, user_id, event_key, match_key, team_number, "
            "defense_rating, feeding_rating, notes, assignment_id, submitted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (context.workspace_id, context.user_id, event_key, match_key, team_number, defense_rating,
             feeding_rating, notes, assignment_id, submitted_at))
        report_id = cursor.fetchone()[0]
    return {"report_id": report_id, "event_key": event_key, "match_key": match_key, "team_number": team_number,
            "defense_rating": defense_rating, "feeding_rating": feeding_rating, "notes": notes,
            "assignment_id": assignment_id, "submitted_at": submitted_at, "scout": context.name}


def list_reports(database: Database, context: SessionContext, *, mine: bool, event_key: str | None = None,
                 team_number: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """One's own reports (scouting_forms), or all of the team's (scouting_view)."""
    require(context, "scouting_forms" if mine else "scouting_view")
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT r.id, r.event_key, r.match_key, r.team_number, r.defense_rating, r.feeding_rating, r.notes, "
            "r.assignment_id, r.submitted_at, COALESCE(m.display_name, u.full_name) FROM workspace_scouting_reports r "
            "JOIN team_memberships m ON m.workspace_id = r.workspace_id AND m.user_id = r.user_id "
            "JOIN users u ON u.id = r.user_id WHERE r.workspace_id = %s AND (%s::bigint IS NULL OR r.user_id = %s) "
            "AND (%s::text IS NULL OR r.event_key = %s) AND (%s::int IS NULL OR r.team_number = %s) "
            "ORDER BY r.submitted_at DESC, r.id DESC LIMIT %s",
            (context.workspace_id, context.user_id if mine else None, context.user_id if mine else None,
             event_key, event_key, team_number, team_number, max(1, min(limit, 1000))))
        return [{"report_id": rid, "event_key": ek, "match_key": mk, "team_number": team, "defense_rating": d,
                 "feeding_rating": f, "notes": notes, "assignment_id": aid, "submitted_at": at, "scout": scout}
                for rid, ek, mk, team, d, f, notes, aid, at, scout in cursor.fetchall()]


def scouting_summary(database: Database, context: SessionContext, *, event_key: str) -> dict[str, Any]:
    """The team's own defense/feeding profile of every team it scouted at one event."""
    require(context, "scouting_view")
    with database.cursor() as cursor:
        cursor.execute("SELECT 1 FROM events WHERE event_key = %s", (event_key,))
        if cursor.fetchone() is None:
            raise not_found("event_not_found", f"Event '{event_key}' is not known to StratAI.")
        cursor.execute(
            "SELECT match_key, team_number, user_id, defense_rating, feeding_rating, notes, submitted_at "
            "FROM workspace_scouting_reports WHERE workspace_id = %s AND event_key = %s ORDER BY team_number, id",
            (context.workspace_id, event_key))
        rows = cursor.fetchall()
    by_team: dict[int, list[ScoutingObservation]] = {}
    for match_key, team, user_id, defense, feeding, notes, submitted_at in rows:
        by_team.setdefault(team, []).append(ScoutingObservation(
            match_key=match_key, event_key=event_key, team_number=team, scout_identifier=f"member-{user_id}",
            defense_rating=defense, feeding_rating=feeding, notes=notes, source="workspace", submitted_at=submitted_at))
    teams = []
    for team, observations in sorted(by_team.items()):
        profile = aggregate_defense_feeding(observations)
        teams.append({"team_number": team, "reports": len(observations),
                      "scouts": len({o.scout_identifier for o in observations}),
                      "profile": profile.model_dump(mode="json")})
    return {"event_key": event_key, "teams": teams, "source": "this team's own scouting reports only",
            "method": "data.metrics.aggregation.aggregate_defense_feeding (median score, agreement; "
                      "insufficient below the two-observation minimum)"}
