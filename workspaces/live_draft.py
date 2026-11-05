"""Phase 11: a team's live alliance-selection draft record: start it, record each real action, undo, correct, close and
reopen it, and read it (docs/phase11.md; decisions in .agent/phase11/decisions/).

**Storage.** Migration 0013 holds `draft_records` (one per team per event) and `draft_actions`, an append-only log.
The state is always `workspaces.draft_log.replay` of the log and is never stored.

**Permissions (P11-Q2, P11-Q4).**
- Reading a record needs `alliance_selection`.
- Changing one needs `alliance_selection_record` too. Administrators always hold it; other roles only if an
  administrator grants it.
- Writing also needs a verified workspace, as team scouting does.
- The workspace always comes from the caller's session, and every query filters on it, so another team's record
  reads as not found.

**Serialized appends.**
- Each change locks its record's row (`FOR UPDATE`), replays the log, checks the new entry against that state and
  appends it at the next sequence, all in one transaction.
- Two administrators recording at once are therefore serialized, and the second is re-validated against the
  first.
- The action id the client sends makes a retry idempotent: the same id with the same content returns the current
  state, and the same id with other content is refused.

**Attribution.** Every entry stores its author (a member of the workspace, by composite key), the server time, the
client's time if it sent one, and its source and mode. Every change is written to the activity log in the same
transaction.

**Setup.**
- When a record is started or refreshed, its setup is built from:
  - the event's final qualification ranks, under the same final-ranks rule as the pick list;
  - the qualification roster;
  - the approved P6-M1 rules for the event.
- When no approved ruleset covers the event, an administrator enters the rules from the event. They are stored as
  `manual_entry`, attributed, and never guessed.
- Whatever is missing is named in the setup. Recording still works, and checks that cannot be made are noted as
  unchecked.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from data.rankings import read_event_ranks
from data.rulesets import RulesetError
from database.connection import Database
from ml.features.roster import event_exists, list_teams_at_event
from ml.playoffs.service import approved_event_rules, qualification_roster, qualification_schedule, ranks_are_final
from workspaces import activity
from workspaces import draft_log as dl
from workspaces.errors import WorkspaceError, conflict, forbidden, invalid_input, not_found
from workspaces.management import require, require_verified
from workspaces.sessions import SessionContext

VIEW, RECORD = "alliance_selection", "alliance_selection_record"
CODE_UNAVAILABLE = "live_draft_unavailable"
MANUAL_RULE_FIELDS = ("n_alliances", "picks_per_alliance", "declined_team_may_be_picked_later",
                      "declined_team_may_become_captain", "captain_may_accept_higher_alliance", "backup_robots")


def _storage_missing() -> WorkspaceError:
    return conflict(CODE_UNAVAILABLE, "Live alliance selection needs database migration 0013 on this server. Ask "
                                      "whoever runs StratAI to apply the latest migrations.")


def _guard(function):
    """Turn a missing 0013 (UndefinedTable) into a clear refusal instead of a 500."""
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except psycopg.errors.UndefinedTable:
            raise _storage_missing() from None
    wrapped.__name__ = function.__name__
    wrapped.__doc__ = function.__doc__
    return wrapped


def _uuid(value: Any, what: str) -> str:
    if value is None:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise invalid_input(f"{what} must be a UUID.") from None


def _reason(value: Any, what: str = "The override reason") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > dl.MAX_REASON:
        raise invalid_input(f"{what} must be 1-{dl.MAX_REASON} characters.")
    return value.strip()


# --- setup ---------------------------------------------------------------------------------------------------------


def _manual_rules(values: Mapping[str, Any], actor: str) -> dl.DraftRules:
    unknown = set(values) - set(MANUAL_RULE_FIELDS)
    if unknown:
        raise invalid_input(f"Unknown rule fields: {sorted(unknown)}.")
    missing = [name for name in MANUAL_RULE_FIELDS if name not in values and name != "declined_team_may_become_captain"]
    if missing:
        raise invalid_input(f"Enter every rule from the event: {', '.join(missing)}.")
    try:
        return dl.DraftRules(**{name: values.get(name) for name in MANUAL_RULE_FIELDS},
                             captain_rule_established=True, source="manual_entry")
    except dl.DraftLogError as exc:
        raise invalid_input(exc.message) from None


def build_setup(database: Database, event_key: str, *, manual_rules: Mapping[str, Any] | None,
                actor: str) -> dl.DraftSetup:
    """The record's setup from the event's current data (see the module docstring). Raises `rules_required` when
    neither an approved ruleset nor manual rules give the event's rules."""
    missing: list[str] = []
    provenance: dict[str, Any] = {"configured_by": actor}
    roster = qualification_roster(database, event_key)
    if not roster:
        missing.append("roster_unavailable: no qualification match with a roster is stored for this event")
    latest, unplayed = qualification_schedule(database, event_key)
    landed = read_event_ranks(database, event_key)
    ranks: dict[int, int] | None = None
    if landed is None:
        missing.append("rankings_unavailable: no qualification ranking is stored for this event")
    else:
        candidate, fetched = landed
        provenance["ranking_fetched_at"] = fetched.isoformat() if isinstance(fetched, datetime) else str(fetched)
        if unplayed or not ranks_are_final(database, event_key, candidate, fetched, latest, roster):
            missing.append("rankings_not_final: the stored ranking predates the end of qualification or does not "
                           "cover the qualification roster")
        else:
            ranks = candidate
    team_count = len(roster) or (len(ranks) if ranks else 0)
    rules: dl.DraftRules | None = None
    try:
        event_rules = approved_event_rules(database, event_key)
        selection = event_rules.selection
        if not team_count:
            raise RulesetError("not_covered", "the event's team count is not known, so its alliance count is not")
        rules = dl.DraftRules(
            n_alliances=event_rules.alliances_for(team_count), picks_per_alliance=selection.picks_per_alliance,
            declined_team_may_be_picked_later=selection.declined_team_may_be_picked_later,
            declined_team_may_become_captain=selection.declined_team_may_become_captain,
            captain_may_accept_higher_alliance=selection.captain_may_accept_higher_alliance,
            backup_robots=selection.backup_robots,
            captain_rule_established=selection.captain_rule == "highest_ranked_available",
            source="approved_ruleset", ruleset_sha256=event_rules.season_ruleset.sha256(),
            ruleset_variant=event_rules.variant)
        provenance.update(ruleset_sha256=rules.ruleset_sha256, ruleset_variant=rules.ruleset_variant)
        if manual_rules:
            raise invalid_input("This event has an approved ruleset, so its rules are used; manual rules are only for "
                                "an event no approved ruleset covers.")
    except RulesetError as exc:
        missing.append(f"ruleset_unavailable: {exc.code}: {exc}")
        if not manual_rules:
            raise WorkspaceError(HTTPStatus.UNPROCESSABLE_ENTITY, "rules_required",
                                 f"No approved ruleset gives this event's rules ({exc.code}). Enter the alliance "
                                 "count, picks per alliance and the decline, captain and backup rules from the event.")
        rules = _manual_rules(manual_rules, actor)
        provenance["manual_rules_entered_by"] = actor
    return dl.DraftSetup(rules, ranks, tuple(roster) or None, tuple(missing), provenance)


# --- reads ---------------------------------------------------------------------------------------------------------

_RECORD_SQL = ("SELECT r.id, r.record_uid, r.event_key, r.created_at, COALESCE(m.display_name, u.full_name) "
               "FROM draft_records r JOIN team_memberships m ON m.workspace_id = r.workspace_id "
               "AND m.user_id = r.created_by_user_id JOIN users u ON u.id = r.created_by_user_id "
               "WHERE r.workspace_id = %s")
_ENTRIES_SQL = ("SELECT action_id, seq, action_type, payload, override_reason, author_label, author_user_id, "
                "recorded_at, source, mode FROM draft_actions WHERE workspace_id = %s AND record_id = %s ORDER BY seq")


def _record(cursor: Any, context: SessionContext, record_id: int, *, lock: bool = False) -> tuple:
    if lock:
        cursor.execute("SELECT id FROM draft_records WHERE workspace_id = %s AND id = %s FOR UPDATE",
                       (context.workspace_id, record_id))
    cursor.execute(_RECORD_SQL + " AND r.id = %s", (context.workspace_id, record_id))
    row = cursor.fetchone()
    if row is None:
        raise not_found("draft_not_found", "No live draft record with that id in this team's workspace.")
    return row


def _entries(cursor: Any, workspace_id: int, record_id: int) -> list[dl.LogEntry]:
    cursor.execute(_ENTRIES_SQL, (workspace_id, record_id))
    return [dl.LogEntry(str(a), seq, t, p or {}, o, label, uid, at, src, mode)
            for a, seq, t, p, o, label, uid, at, src, mode in cursor.fetchall()]


def _out(context: SessionContext, row: tuple, view: dl.DraftView) -> dict[str, Any]:
    record_id, record_uid, event_key, created_at, created_by = row
    return {"record_id": record_id, "record_uid": str(record_uid), "event_key": event_key, "created_at": created_at,
            "created_by": created_by, "can_record": context.can(RECORD) and context.verified,
            **dl.view_json(view, team_number=context.team_number)}


def load_view(database: Database, context: SessionContext, record_id: int) -> tuple[tuple, dl.DraftView]:
    """The record row and its replayed log (for the recommendations, which need the view itself)."""
    require(context, VIEW)
    with database.cursor() as cursor:
        row = _record(cursor, context, record_id)
        entries = _entries(cursor, context.workspace_id, record_id)
    return row, dl.replay(entries)


@_guard
def load_view_with_previous(database: Database, context: SessionContext,
                            record_id: int) -> tuple[tuple, tuple[dl.DraftView, dl.DraftView | None]]:
    """The record row, its replayed log, and the replay without its latest entry (the state the previous
    recommendation reflected, for the movement explanation)."""
    require(context, VIEW)
    with database.cursor() as cursor:
        row = _record(cursor, context, record_id)
        entries = _entries(cursor, context.workspace_id, record_id)
    return row, (dl.replay(entries), dl.replay(entries[:-1]) if len(entries) > 1 else None)


@_guard
def get_draft(database: Database, context: SessionContext, record_id: int) -> dict[str, Any]:
    row, view = load_view(database, context, record_id)
    return _out(context, row, view)


@_guard
def list_drafts(database: Database, context: SessionContext, *, event_key: str | None = None) -> list[dict[str, Any]]:
    require(context, VIEW)
    with database.cursor() as cursor:
        cursor.execute(_RECORD_SQL + " AND (%s::text IS NULL OR r.event_key = %s) ORDER BY r.created_at DESC",
                       (context.workspace_id, event_key, event_key))
        rows = cursor.fetchall()
        out = []
        for row in rows:
            view = dl.replay(_entries(cursor, context.workspace_id, row[0]))
            out.append({"record_id": row[0], "record_uid": str(row[1]), "event_key": row[2], "created_at": row[3],
                        "created_by": row[4], "record_seq": view.record_seq,
                        "status": "closed" if view.closed else "open", "picks_made": view.picks_made,
                        "complete": view.complete})
    return out


# --- writes --------------------------------------------------------------------------------------------------------


def _writer(context: SessionContext) -> None:
    require(context, VIEW)
    require(context, RECORD)
    require_verified(context, "Recording alliance selection")


def _insert(cursor: Any, context: SessionContext, record_id: int, entry: dl.LogEntry,
            client_recorded_at: datetime | None) -> None:
    try:
        _insert_row(cursor, context, record_id, entry, client_recorded_at)
    except psycopg.errors.UniqueViolation:  # the id is already used by an entry of another of the team's records
        raise conflict("action_id_conflict", "That action id is already used by a different action.") from None


def _insert_row(cursor: Any, context: SessionContext, record_id: int, entry: dl.LogEntry,
                client_recorded_at: datetime | None) -> None:
    cursor.execute(
        "INSERT INTO draft_actions (workspace_id, record_id, action_id, seq, action_type, payload, override_reason, "
        "author_user_id, author_label, client_recorded_at, source, mode) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (context.workspace_id, record_id, entry.action_id, entry.seq, entry.type, Jsonb(dict(entry.payload)),
         entry.override_reason, context.user_id, entry.author_label, client_recorded_at, entry.source, entry.mode))


def _log(cursor: Any, context: SessionContext, action: str, event_key: str, record_id: int, entry: dl.LogEntry,
         summary: str) -> None:
    details = {"event_key": event_key, "record_id": record_id, "seq": entry.seq, "type": entry.type,
               "action_id": entry.action_id, "summary": summary}
    if entry.override_reason:
        details["override_reason"] = entry.override_reason
    activity.record(cursor, workspace_id=context.workspace_id, actor_user_id=context.user_id,
                    actor_label=context.name, action=action, details=details)


@_guard
def start_draft(database: Database, context: SessionContext, *, event_key: str, record_uid: Any = None,
                action_id: Any = None, manual_rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Open the team's live draft record for an event it attends, configured from the event's current data."""
    _writer(context)
    if not isinstance(event_key, str) or not event_key or not event_exists(database, event_key):
        raise not_found("event_not_found", f"Event '{event_key}' is not known to StratAI.")
    if context.team_number not in list_teams_at_event(database, event_key):
        raise forbidden("team_not_at_event", f"Team {context.team_number} is not on this event's match roster, so "
                                             "it has no alliance selection to record there.")
    record_uid, action_id = _uuid(record_uid, "record_uid"), _uuid(action_id, "action_id")
    setup = build_setup(database, event_key, manual_rules=manual_rules, actor=context.name)
    with database.cursor() as cursor:
        cursor.execute("SELECT id FROM draft_records WHERE workspace_id = %s AND event_key = %s",
                       (context.workspace_id, event_key))
        existing = cursor.fetchone()
        if existing is not None:
            raise conflict("draft_exists", f"This team already has a live draft record for {event_key} "
                                           f"(record {existing[0]}). Open it instead.")
        try:
            cursor.execute("INSERT INTO draft_records (workspace_id, record_uid, event_key, created_by_user_id) "
                           "VALUES (%s, %s, %s, %s) RETURNING id", (context.workspace_id, record_uid, event_key,
                                                                    context.user_id))
        except psycopg.errors.UniqueViolation:  # another administrator started it a moment ago, or a reused uid
            raise conflict("draft_exists", f"This team already has a live draft record for {event_key}. "
                                           "Open it instead.") from None
        record_id = cursor.fetchone()[0]
        entry = dl.LogEntry(action_id, 1, dl.CONFIGURE, setup.to_json(), None, context.name, context.user_id)
        _insert(cursor, context, record_id, entry, None)
        _log(cursor, context, "draft_started", event_key, record_id, entry, "Live draft record started")
        row = _record(cursor, context, record_id)
        view = dl.replay(_entries(cursor, context.workspace_id, record_id))
    return _out(context, row, view)


def _append(database: Database, context: SessionContext, record_id: int, type_: str, payload: dict[str, Any], *,
            action_id: Any, override_reason: Any = None, client_recorded_at: datetime | None = None,
            source: str = "manual", activity_action: str) -> dict[str, Any]:
    """Lock, replay, check, append and log one entry (the serialized append the module docstring describes)."""
    _writer(context)
    action_id = _uuid(action_id, "action_id")
    override = _reason(override_reason)
    if source not in dl.SOURCES:
        raise invalid_input(f"source must be one of {dl.SOURCES}.")
    with database.cursor() as cursor:
        row = _record(cursor, context, record_id, lock=True)
        entries = _entries(cursor, context.workspace_id, record_id)
        previous = next((e for e in entries if e.action_id == action_id), None)
        if previous is not None:  # an idempotent retry, or a reused id
            if previous.type != type_ or dict(previous.payload) != payload or previous.override_reason != override:
                raise conflict("action_id_conflict", "That action id is already used by a different action.")
            return _out(context, row, dl.replay(entries))
        view = dl.replay(entries)
        if view.closed and type_ != dl.REOPEN:
            raise conflict("record_closed", "This live draft record is closed. Reopen it to record changes.")
        if type_ == dl.REOPEN and not view.closed:
            raise conflict("record_open", "This live draft record is already open.")
        entry = dl.LogEntry(action_id, (entries[-1].seq if entries else 0) + 1, type_, payload, override,
                            context.name, context.user_id, source=source)
        try:
            after, violation = dl.check_append(entries, entry)
        except dl.DraftLogError as exc:
            raise conflict(exc.code, exc.message) from None
        if violation is not None:
            raise conflict(violation.code, violation.message + ". If the room really did this, record it again "
                                                               "with an override reason.")
        _insert(cursor, context, record_id, entry, client_recorded_at)
        summary = next(h.summary for h in after.history if h.entry.action_id == action_id)
        _log(cursor, context, "draft_action_overridden" if override and activity_action == "draft_action_recorded"
             else activity_action, row[2], record_id, entry, summary)
        return _out(context, row, after)


@_guard
def record_action(database: Database, context: SessionContext, record_id: int, *, type_: str, seed: Any, team: Any,
                  action_id: Any = None, override_reason: Any = None, client_recorded_at: datetime | None = None,
                  source: str = "manual") -> dict[str, Any]:
    """Record one draft action as it happened: a captain named, a pick, a decline or a backup."""
    _writer(context)  # the permission is checked before anything about the request is
    try:
        action = dl.DraftAction.from_payload(type_, {"seed": seed, "team": team})
    except dl.DraftLogError as exc:
        raise invalid_input(exc.message) from None
    return _append(database, context, record_id, type_, action.payload(), action_id=action_id,
                   override_reason=override_reason, client_recorded_at=client_recorded_at, source=source,
                   activity_action="draft_action_recorded")


@_guard
def undo_last(database: Database, context: SessionContext, record_id: int, *, target_action_id: Any = None,
              action_id: Any = None) -> dict[str, Any]:
    """Remove the most recent action in effect. `target_action_id`, when given, must name it (so an undo sent from
    a stale screen cannot remove a different action)."""
    _writer(context)
    if target_action_id is None:
        _, view = load_view(database, context, record_id)
        if not view.effective:
            raise conflict("nothing_to_undo", "No action is in effect.")
        target_action_id = view.effective[-1].action_id
    return _append(database, context, record_id, dl.UNDO, {"target_action_id": _uuid(target_action_id, "target")},
                   action_id=action_id, activity_action="draft_action_undone")


@_guard
def correct_action(database: Database, context: SessionContext, record_id: int, *, target_action_id: Any,
                   replacement: Mapping[str, Any] | None, action_id: Any = None,
                   override_reason: Any = None) -> dict[str, Any]:
    """Replace an earlier action in effect with what really happened (or with nothing). Later actions are
    re-validated; one that becomes invalid is flagged, never silently dropped."""
    _writer(context)
    new = None
    if replacement is not None:
        if not isinstance(replacement, Mapping):
            raise invalid_input("A replacement is an action (type, seed, team) or null.")
        try:
            new = dl.DraftAction.from_payload(replacement.get("type"), replacement)
        except dl.DraftLogError as exc:
            raise invalid_input(exc.message) from None
    payload = {"target_action_id": _uuid(target_action_id, "target"),
               "replacement": None if new is None else {"type": new.type, **new.payload()}}
    return _append(database, context, record_id, dl.CORRECT, payload, action_id=action_id,
                   override_reason=override_reason, activity_action="draft_action_corrected")


@_guard
def close_draft(database: Database, context: SessionContext, record_id: int, *, action_id: Any = None) -> dict:
    _writer(context)
    return _append(database, context, record_id, dl.CLOSE, {}, action_id=action_id, activity_action="draft_closed")


@_guard
def reopen_draft(database: Database, context: SessionContext, record_id: int, *, action_id: Any = None) -> dict:
    _writer(context)
    return _append(database, context, record_id, dl.REOPEN, {}, action_id=action_id, activity_action="draft_reopened")


@_guard
def reconfigure_draft(database: Database, context: SessionContext, record_id: int, *, action_id: Any = None,
                      manual_rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Refresh the record's setup from the event's current data (e.g. once final ranks land). Every draft action is
    re-validated against the new setup."""
    _writer(context)
    with database.cursor() as cursor:
        event_key = _record(cursor, context, record_id)[2]
        current = dl.replay(_entries(cursor, context.workspace_id, record_id)).setup
    if manual_rules is None and current is not None and current.rules.source == "manual_entry":
        # Keep the rules an administrator entered: a refresh picks up ranks and roster, never drops the rules.
        manual_rules = {name: getattr(current.rules, name) for name in MANUAL_RULE_FIELDS}
    try:
        setup = build_setup(database, event_key, manual_rules=manual_rules, actor=context.name)
    except WorkspaceError as exc:
        if exc.code != "invalid_input" or current is None or current.rules.source != "manual_entry":
            raise
        # The event's season gained an approved ruleset since: it now governs, and the entered rules are dropped.
        setup = build_setup(database, event_key, manual_rules=None, actor=context.name)
    return _append(database, context, record_id, dl.CONFIGURE, setup.to_json(), action_id=action_id,
                   activity_action="draft_reconfigured")


__all__ = ["build_setup", "close_draft", "correct_action", "get_draft", "list_drafts", "load_view",
           "load_view_with_previous",
           "reconfigure_draft", "record_action", "reopen_draft", "start_draft", "undo_last"]
