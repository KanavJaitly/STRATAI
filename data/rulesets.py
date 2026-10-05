"""P6-M1: per-season alliance-selection and playoff rulesets, entered by people from the game manuals.

docs/P6Milestones.md P6-M1 (frozen at P6-M0).
- **Human-entered:** a ruleset is entered by a person from the official manual, with a section citation for every
  rule. No LLM drafts or parses a manual (CLAUDE.md, P6-M1).
- **Draft → approval:** a ruleset becomes authoritative only when a named reviewer approves it: draft → submit →
  approve, or return with a note. Every version is kept.
- **Read, never hard-coded:** every later Phase 6 milestone reads the season's *approved* ruleset, and no rule
  exists only in code. `approved_ruleset` refuses an unapproved or unknown season.
- **Storage:** migration `0011_phase6_season_rulesets.sql`. Content is append-only (an edit is a new version), and
  only status and review metadata move forward. The structure mirrors Phase 5's game-spec workflow
  (`data/human_inputs.py`).

**The bracket is data.** Each bracket format lists its slots: the matches before the finals, keyed by TBA's
(`competition_level`, `set_number`). For each slot it gives:
- the round;
- where each side comes from: a seed, or the winner or loser of an earlier slot.

The finals are a best-of-N series between two slot sources. Nothing about a particular season's format is coded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from database.connection import Database

SCHEMA_VERSION = "p6-ruleset-v1"
STATUSES = ("draft", "awaiting_review", "approved", "superseded")


class RulesetError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SlotSource(_Frozen):
    kind: Literal["seed", "winner", "loser"]
    seed: int | None = Field(default=None, ge=1)
    slot: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> SlotSource:
        if (self.kind == "seed") != (self.seed is not None) or (self.kind != "seed") != (self.slot is not None):
            raise ValueError("a seed source names a seed; a winner/loser source names a slot")
        return self


class BracketSlot(_Frozen):
    slot: str = Field(min_length=1)
    competition_level: Literal["semifinal", "quarterfinal", "eighthfinal"]
    set_number: int = Field(ge=1)
    round: int = Field(ge=1)
    red: SlotSource
    blue: SlotSource
    citation: str = Field(min_length=1)


class FinalsSeries(_Frozen):
    competition_level: Literal["final"] = "final"
    set_number: int = Field(ge=1)
    round: int = Field(ge=1)
    wins_needed: int = Field(ge=1)
    red: SlotSource
    blue: SlotSource
    citation: str = Field(min_length=1)


class BracketFormat(_Frozen):
    alliances: int = Field(ge=2)
    slots: tuple[BracketSlot, ...] = Field(min_length=1)
    finals: FinalsSeries

    @model_validator(mode="after")
    def _graph(self) -> BracketFormat:
        names = [s.slot for s in self.slots]
        if len(set(names)) != len(names):
            raise ValueError("duplicate slot names")
        keys = [(s.competition_level, s.set_number) for s in self.slots]
        if len(set(keys)) != len(keys):
            raise ValueError("two slots share a TBA (competition_level, set_number)")
        order = {name: i for i, name in enumerate(names)}
        seeds_seen: list[int] = []
        uses: dict[tuple[str, str], int] = {}
        for i, slot in enumerate(self.slots):
            for source in (slot.red, slot.blue):
                if source.kind == "seed":
                    if source.seed > self.alliances:
                        raise ValueError(f"slot {slot.slot} uses seed {source.seed} > {self.alliances} alliances")
                    seeds_seen.append(source.seed)
                else:
                    if source.slot not in order or order[source.slot] >= i:
                        raise ValueError(f"slot {slot.slot} depends on {source.slot}, which is not an earlier slot")
                    uses[(source.kind, source.slot)] = uses.get((source.kind, source.slot), 0) + 1
        for source in (self.finals.red, self.finals.blue):
            if source.kind == "seed" or source.slot not in order:
                raise ValueError("the finals take their teams from earlier slots")
            uses[(source.kind, source.slot)] = uses.get((source.kind, source.slot), 0) + 1
        if sorted(seeds_seen) != list(range(1, self.alliances + 1)):
            raise ValueError("every seed must enter the bracket exactly once")
        if any(count > 1 for count in uses.values()):
            raise ValueError("a slot's winner or loser is routed to more than one place")
        return self

    def slot_by_tba(self) -> dict[tuple[str, int], BracketSlot]:
        return {(s.competition_level, s.set_number): s for s in self.slots}


class AllianceCountRule(_Frozen):
    min_teams: int = Field(ge=1)
    max_teams: int | None = Field(default=None, ge=1)
    alliances: int = Field(ge=2)
    citation: str = Field(min_length=1)


class SelectionRules(_Frozen):
    order: Literal["serpentine"]
    picks_per_alliance: int = Field(ge=1)
    captain_rule: Literal["highest_ranked_available"]
    captain_may_accept_higher_alliance: bool
    declined_team_may_be_picked_later: bool
    declined_team_may_become_captain: bool
    backup_robots: bool
    citation: str = Field(min_length=1)


class ManualReference(_Frozen):
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)


class SeasonRuleset(_Frozen):
    schema_version: Literal["p6-ruleset-v1"] = SCHEMA_VERSION
    season: int = Field(ge=1992)
    game_name: str = Field(min_length=1)
    manual: ManualReference
    alliance_counts: tuple[AllianceCountRule, ...] = Field(min_length=1)
    selection: SelectionRules
    brackets: tuple[BracketFormat, ...] = Field(min_length=1)
    tie_rule: str = Field(min_length=1, description="how a tied playoff match is resolved, with its citation")

    @model_validator(mode="after")
    def _consistent(self) -> SeasonRuleset:
        formats = {b.alliances for b in self.brackets}
        if len(formats) != len(self.brackets):
            raise ValueError("one bracket format per alliance count")
        missing = {r.alliances for r in self.alliance_counts} - formats
        if missing:
            raise ValueError(f"no bracket format for alliance counts {sorted(missing)}")
        return self

    def alliances_for(self, team_count: int) -> int:
        for rule in self.alliance_counts:
            if team_count >= rule.min_teams and (rule.max_teams is None or team_count <= rule.max_teams):
                return rule.alliances
        raise RulesetError("not_covered", f"no alliance-count rule covers {team_count} teams")

    def bracket(self, alliances: int) -> BracketFormat:
        for b in self.brackets:
            if b.alliances == alliances:
                return b
        raise RulesetError("not_covered", f"no bracket format for {alliances} alliances")

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode("utf-8")).hexdigest()


# --- storage (migration 0011): draft -> submit -> named-reviewer approval ----------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RulesetError("invalid_input", f"{field} must name a person")
    return value.strip()


def _rows(cursor) -> list[dict[str, Any]]:
    columns = [c.name for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def validate_ruleset(payload: dict[str, Any]) -> SeasonRuleset:
    try:
        return SeasonRuleset.model_validate(payload)
    except ValidationError as exc:
        raise RulesetError("invalid_input", "the ruleset does not satisfy the schema",
                           [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                            for e in exc.errors()]) from exc


def save_ruleset_draft(database: Database, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """A new immutable version in `draft`. The ruleset must satisfy the schema."""
    created_by = _name(created_by, "created_by")
    ruleset = validate_ruleset(payload)
    with database.cursor() as cursor:
        cursor.execute("SELECT coalesce(max(version), 0) + 1 FROM season_rulesets WHERE season = %s",
                       (ruleset.season,))
        version = cursor.fetchone()[0]
        cursor.execute("INSERT INTO season_rulesets (season, version, ruleset_json, ruleset_sha256, status, created_by) "
                       "VALUES (%s, %s, %s, %s, 'draft', %s) RETURNING *",
                       (ruleset.season, version, json.dumps(ruleset.model_dump(mode="json")), ruleset.sha256(),
                        created_by))
        return _rows(cursor)[0]


def _locked(cursor, ruleset_id: int) -> dict[str, Any]:
    cursor.execute("SELECT * FROM season_rulesets WHERE id = %s FOR UPDATE", (ruleset_id,))
    rows = _rows(cursor)
    if not rows:
        raise RulesetError("not_found", f"no ruleset version {ruleset_id}")
    return rows[0]


def submit_ruleset(database: Database, ruleset_id: int) -> dict[str, Any]:
    with database.cursor() as cursor:
        row = _locked(cursor, ruleset_id)
        if row["status"] != "draft":
            raise RulesetError("invalid_state", f"ruleset {ruleset_id} is {row['status']}, not draft")
        cursor.execute("UPDATE season_rulesets SET status = 'awaiting_review', submitted_at = %s WHERE id = %s "
                       "RETURNING *", (_now(), ruleset_id))
        return _rows(cursor)[0]


def review_ruleset(database: Database, ruleset_id: int, *, reviewer: str, approve: bool,
                   note: str = "") -> dict[str, Any]:
    """A named reviewer approves it, superseding the season's earlier approved version, or returns it with a note."""
    reviewer = _name(reviewer, "reviewer")
    with database.cursor() as cursor:
        row = _locked(cursor, ruleset_id)
        if row["status"] != "awaiting_review":
            raise RulesetError("invalid_state", f"ruleset {ruleset_id} is {row['status']}, not awaiting_review")
        if row["created_by"] == reviewer:
            raise RulesetError("invalid_input", "the reviewer must be a different person from the author")
        now = _now()
        if not approve:
            if not note.strip():
                raise RulesetError("invalid_input", "returning a ruleset needs a note")
            cursor.execute("UPDATE season_rulesets SET status = 'draft', reviewed_by = %s, reviewed_at = %s, "
                           "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, note, ruleset_id))
            return _rows(cursor)[0]
        cursor.execute("UPDATE season_rulesets SET status = 'superseded' WHERE season = %s AND status = 'approved'",
                       (row["season"],))
        cursor.execute("UPDATE season_rulesets SET status = 'approved', reviewed_by = %s, reviewed_at = %s, "
                       "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, note or None, ruleset_id))
        return _rows(cursor)[0]


def list_rulesets(database: Database, season: int | None = None) -> list[dict[str, Any]]:
    with database.cursor() as cursor:
        if season is None:
            cursor.execute("SELECT * FROM season_rulesets ORDER BY season, version")
        else:
            cursor.execute("SELECT * FROM season_rulesets WHERE season = %s ORDER BY version", (season,))
        return _rows(cursor)


def approved_ruleset(database: Database, season: int) -> SeasonRuleset:
    """The season's approved ruleset. Refuses an unapproved or unknown season: rules never fall back to code."""
    with database.cursor() as cursor:
        cursor.execute("SELECT ruleset_json, ruleset_sha256 FROM season_rulesets WHERE season = %s AND status = 'approved'",
                       (season,))
        row = cursor.fetchone()
    if row is None:
        raise RulesetError("not_approved", f"no approved {season} ruleset: it must be entered from the manual and "
                                           "approved by a named reviewer (P6-M1)")
    ruleset = SeasonRuleset.model_validate(row[0])
    if ruleset.sha256() != row[1]:
        raise RulesetError("storage_integrity", f"the approved {season} ruleset does not match its sha256")
    return ruleset


def approved_seasons(database: Database) -> list[int]:
    with database.cursor() as cursor:
        cursor.execute("SELECT season FROM season_rulesets WHERE status = 'approved' ORDER BY season")
        return [r[0] for r in cursor.fetchall()]
