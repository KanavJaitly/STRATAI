"""P6-M1: per-season alliance-selection and playoff rulesets, entered by people from the game manuals.

docs/P6Milestones.md P6-M1 (frozen at P6-M0).
- **Sources and roles are kept apart:**
  - the authoritative sources: FIRST Game Manuals, Team Updates and event/division pages, plus TBA only where the
    ruleset requires the TBA mapping;
  - Claude's cited research draft (`.agent/phase6/rulesets_research/`);
  - the submitted ruleset (stored here);
  - the human review.
- **Review control (Kanav, 2026-10-07; `.agent/phase6/decisions/P6_M1_REVIEW_CONTROL.md`).** P6-M1 requires a
  named, qualified human FRC-domain reviewer who independently verifies the submitted ruleset against the
  authoritative FIRST sources and completes R1–R15. R1–R14 are attested before approval. R15, the approval record, is written by the approval itself (`scripts/phase6_rulesets.py`) and committed afterwards, so it is never attested in advance.
  - "Independently" means against the sources, never by accepting the author's transcription or the research
    draft.
  - The reviewer may also be the ruleset's author when the reviewer satisfies the qualification requirement.
  - This replaces the earlier "a different person from the author" control.
  - No LLM is in the runtime path (CLAUDE.md).
- **Draft → approval:** a ruleset becomes authoritative only when a qualified named reviewer approves it: draft →
  submit → approve, or return with a note. Every version is kept.
  - **Approval refuses unless** all of these hold: a reviewer name; the reviewer's FRC-domain qualification; R1–R14
    all completed (R15 is the record the approval writes); the full sha256 the reviewer verified equals the stored one; the stored content still validates
    and still hashes to it.
  - **Recording:** the qualification, the checklist result and the verified sha256 are stored as a JSON document in
    `review_note`.
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

**Per-event selection variants (schema v2, Kanav's P1 decision, 2026-10-05).** One season can use more than one
alliance-selection structure. For example, standard events use 2 picks and backups, while FIRST Championship
divisions use 3 picks and no backups (2024 §12.2, 2025 and 2026 §13.2).
- **`selection`** is the season default.
- **`selection_variants`** each carry a complete `SelectionRules` and an explicit list of the event keys they apply
  to. Every listed event carries its own FIRST provenance: rule, document, version, Team Update (or an explicit
  null), section, and a FIRST URL.
  - Nothing is inferred: membership is never derived from `events.event_type` or from the data.
  - An event appears in at most one variant.
- **Precedence**, which is deterministic and never implicit:
  1. the explicit event-level variant listing the event;
  2. the season default.
- **`event_exclusions`** list events the ruleset cannot represent faithfully. Each has a reason code and the finding.
  Two kinds:
  - recorded behaviour no FIRST document explains, e.g. a backup that plays before T604/T608 allow it;
  - a FIRST rule the schema cannot express, e.g. small-event byes (§10.6.6) that TBA records as placeholder
    alliances.
  - An excluded event has no rules: `for_event` refuses it, so consumers exclude and count it and never
    approximate it.
- **Unresolved rules (schema v3, D-PX1-4/5, Kanav 2026-10-06).** `captain_rule` and
  `declined_team_may_become_captain` may be `null`, meaning not established by an authoritative FIRST source.
  - A `null` needs an `unresolved` entry (note and sources checked); an `unresolved` entry needs a `null`.
  - Consumers never substitute a value. They raise `RulesetError("not_established")` only where the value would
    actually decide an outcome.
- **Consumers must use `for_event`.** Selection consumers read one event's rules through `SeasonRuleset.for_event`,
  which returns an `EventRules`. `ml.playoffs.selection` refuses a bare `SeasonRuleset`, so the season default can
  never be applied to an event by accident.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from database.connection import Database

SCHEMA_VERSION = "p6-ruleset-v3"
# Provenance URLs must point at FIRST itself: the official manuals, Team Updates and event pages (P6-M1 research
# rule, 2026-10-05: FIRST is the only authoritative source for the rules).
FIRST_SOURCE_HOSTS = ("firstinspires.org", "firstfrc.blob.core.windows.net")
EVENT_KEY_PATTERN = re.compile(r"^(\d{4})[a-z0-9]+$")
REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NonEmpty = Annotated[str, Field(min_length=1)]
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


NULLABLE_SELECTION_FIELDS = ("captain_rule", "declined_team_may_become_captain")


class UnresolvedRule(_Frozen):
    """Why a nullable selection field is null: the rule is not established by an authoritative FIRST source
    (D-PX1-4/5, Kanav 2026-10-06). A null is never read as true, false or a default."""

    field: Literal["captain_rule", "declined_team_may_become_captain"]
    note: NonEmpty  # what is and is not established
    sources_checked: NonEmpty  # the official sources searched


class SelectionRules(_Frozen):
    order: Literal["serpentine"]
    picks_per_alliance: int = Field(ge=1)
    captain_rule: Literal["highest_ranked_available"] | None  # null = not established (needs an `unresolved` entry)
    captain_may_accept_higher_alliance: bool
    declined_team_may_be_picked_later: bool
    declined_team_may_become_captain: bool | None  # null = not established (needs an `unresolved` entry)
    backup_robots: bool
    unresolved: tuple[UnresolvedRule, ...]  # required; [] when every rule is established
    citation: str = Field(min_length=1)

    @model_validator(mode="after")
    def _nulls_are_explained(self) -> SelectionRules:
        explained = [u.field for u in self.unresolved]
        if len(set(explained)) != len(explained):
            raise ValueError("a field is listed in `unresolved` at most once")
        nulls = {f for f in NULLABLE_SELECTION_FIELDS if getattr(self, f) is None}
        if nulls != set(explained):
            raise ValueError(f"null fields {sorted(nulls)} must be exactly the fields explained in `unresolved` "
                             f"{sorted(explained)}")
        return self


class ManualReference(_Frozen):
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)


def _event_key(value: str) -> str:
    if not isinstance(value, str) or not EVENT_KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{value!r} is not a TBA event key (e.g. 2025arc)")
    return value


class VariantEvent(_Frozen):
    """One event placed in a non-default selection variant, with the FIRST provenance that puts it there."""

    event_key: str
    rule: NonEmpty  # the relevant FIRST rule, e.g. "FIRST Championship division: 4-ROBOT ALLIANCES"
    document: NonEmpty  # the source document
    version: NonEmpty  # the source document's version
    team_update: NonEmpty | None  # required key: the Team Update that applies, or null when none does
    section: NonEmpty  # the section or rule citation
    url: NonEmpty  # the FIRST URL

    _key = field_validator("event_key")(_event_key)

    @field_validator("url")
    @classmethod
    def _first_url(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in FIRST_SOURCE_HOSTS):
            raise ValueError(f"the source URL must be an https URL on a FIRST host {FIRST_SOURCE_HOSTS}")
        return value


class SelectionVariant(_Frozen):
    """A complete alternative `SelectionRules` for the explicitly listed events only."""

    name: NonEmpty
    selection: SelectionRules
    events: tuple[VariantEvent, ...] = Field(min_length=1)


class EventExclusion(_Frozen):
    """An event the ruleset cannot represent faithfully: excluded and counted, never approximated.

    Either its recorded behaviour is unexplained by any FIRST document, or a FIRST rule it follows is not
    expressible in this schema."""

    event_key: str
    reason: str  # a machine-readable code, e.g. "backup_before_first_match"
    finding: NonEmpty  # what was found, and why the FIRST documents do not resolve it

    _key = field_validator("event_key")(_event_key)

    @field_validator("reason")
    @classmethod
    def _code(cls, value: str) -> str:
        if not REASON_CODE_PATTERN.fullmatch(value):
            raise ValueError("the reason must be a lower_snake_case code")
        return value


class SeasonRuleset(_Frozen):
    schema_version: Literal["p6-ruleset-v3"] = SCHEMA_VERSION
    season: int = Field(ge=1992)
    game_name: str = Field(min_length=1)
    manual: ManualReference
    alliance_counts: tuple[AllianceCountRule, ...] = Field(min_length=1)
    selection: SelectionRules  # the season default
    selection_variants: tuple[SelectionVariant, ...]  # required; [] when every event uses the default
    event_exclusions: tuple[EventExclusion, ...]  # required; [] when there are none
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
        self._check_events()
        return self

    def _check_events(self) -> None:
        names = [v.name for v in self.selection_variants]
        if len(set(names)) != len(names):
            raise ValueError("duplicate selection variant names")
        default = self.selection.model_dump(exclude={"citation"})
        placed: dict[str, str] = {}
        for variant in self.selection_variants:
            if variant.selection.model_dump(exclude={"citation"}) == default:
                raise ValueError(f"variant {variant.name!r} has the season default's rules: it overrides nothing")
            for event in variant.events:
                if event.event_key in placed:
                    raise ValueError(f"{event.event_key} is listed in variants {placed[event.event_key]!r} and "
                                     f"{variant.name!r}: an event has at most one variant")
                placed[event.event_key] = variant.name
        excluded = [e.event_key for e in self.event_exclusions]
        if len(set(excluded)) != len(excluded):
            raise ValueError("an event is excluded at most once")
        for key in [*placed, *excluded]:
            if not key.startswith(str(self.season)):
                raise ValueError(f"{key} is not a {self.season} event")

    def exclusion(self, event_key: str) -> EventExclusion | None:
        return next((e for e in self.event_exclusions if e.event_key == event_key), None)

    def for_event(self, event_key: str) -> EventRules:
        """One event's rules. Precedence: (1) the explicit variant listing the event, (2) the season default.

        Refuses an event of another season, and an excluded event (which has no rules to apply)."""
        _event_key(event_key)
        if not event_key.startswith(str(self.season)):
            raise RulesetError("wrong_season", f"{event_key} is not covered by the {self.season} ruleset")
        excluded = self.exclusion(event_key)
        if excluded is not None:
            raise RulesetError("event_excluded", f"{event_key} is excluded ({excluded.reason}): {excluded.finding}",
                               {"reason": excluded.reason})
        for variant in self.selection_variants:
            if any(e.event_key == event_key for e in variant.events):
                return EventRules(self, event_key, variant.name, variant.selection)
        return EventRules(self, event_key, None, self.selection)

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


@dataclass(frozen=True)
class EventRules:
    """One event's resolved rules (`SeasonRuleset.for_event`): what every selection consumer reads.

    `variant` is the name of the variant that applies, or None for the season default. The roster rule and the
    brackets are season-level."""

    season_ruleset: SeasonRuleset
    event_key: str
    variant: str | None
    selection: SelectionRules

    def alliances_for(self, team_count: int) -> int:
        return self.season_ruleset.alliances_for(team_count)

    def bracket(self, alliances: int) -> BracketFormat:
        return self.season_ruleset.bracket(alliances)


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


# P6_M1_HUMAN_INPUT_GUIDE.md §5. Attested before approval: R1-R14. R15 (the approval record with its hash) is
# produced by the approval command and committed after it, so it is not part of the pre-approval attestation.
REVIEW_CHECKLIST = tuple(f"R{i}" for i in range(1, 15))
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _approval_record(row: dict[str, Any], *, reviewer_qualification: str, checklist: Any, verified_sha256: str,
                     note: str) -> str:
    """The review conditions an approval needs (review control of 2026-10-07). Returns the `review_note` JSON."""
    if not isinstance(reviewer_qualification, str) or not reviewer_qualification.strip():
        raise RulesetError("invalid_input", "approval needs the reviewer's FRC-domain qualification")
    if not isinstance(checklist, dict):
        raise RulesetError("review_incomplete", "approval needs the R1-R14 checklist result")
    unknown = sorted(set(checklist) - set(REVIEW_CHECKLIST))
    incomplete = [item for item in REVIEW_CHECKLIST if checklist.get(item) is not True]
    if unknown or incomplete:
        raise RulesetError("review_incomplete", "every checklist item R1-R14 must be completed (true)",
                           {"incomplete": incomplete, "unknown": unknown})
    sha_ok = isinstance(verified_sha256, str) and SHA256_PATTERN.fullmatch(verified_sha256)
    if not sha_ok or verified_sha256 != row["ruleset_sha256"]:
        raise RulesetError("hash_mismatch", "the full sha256 the reviewer verified does not equal the stored "
                                            f"ruleset's {row['ruleset_sha256']}")
    try:
        stored = SeasonRuleset.model_validate(row["ruleset_json"])
    except ValidationError as exc:  # e.g. an unresolved marker in content stored outside save_ruleset_draft
        raise RulesetError("invalid_stored_ruleset", "the stored ruleset does not satisfy the schema",
                           [".".join(str(p) for p in e["loc"]) for e in exc.errors()]) from exc
    if stored.sha256() != row["ruleset_sha256"]:
        raise RulesetError("hash_mismatch", "the stored ruleset content does not hash to its stored sha256")
    return json.dumps({"reviewer_qualification": reviewer_qualification.strip(),
                       "checklist": {item: True for item in REVIEW_CHECKLIST},
                       "verified_sha256": verified_sha256, "note": note or None}, sort_keys=True)


def review_ruleset(database: Database, ruleset_id: int, *, reviewer: str, approve: bool, note: str = "",
                   reviewer_qualification: str = "", checklist: Any = None,
                   verified_sha256: str = "") -> dict[str, Any]:
    """A named, qualified FRC-domain reviewer approves it (superseding the season's earlier approved version), or
    returns it with a note.

    Approval refuses unless every review condition holds (module docstring). The reviewer may be the author."""
    reviewer = _name(reviewer, "reviewer")
    with database.cursor() as cursor:
        row = _locked(cursor, ruleset_id)
        if row["status"] != "awaiting_review":
            raise RulesetError("invalid_state", f"ruleset {ruleset_id} is {row['status']}, not awaiting_review")
        now = _now()
        if not approve:
            if not note.strip():
                raise RulesetError("invalid_input", "returning a ruleset needs a note")
            cursor.execute("UPDATE season_rulesets SET status = 'draft', reviewed_by = %s, reviewed_at = %s, "
                           "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, note, ruleset_id))
            return _rows(cursor)[0]
        record = _approval_record(row, reviewer_qualification=reviewer_qualification, checklist=checklist,
                                  verified_sha256=verified_sha256, note=note)
        cursor.execute("UPDATE season_rulesets SET status = 'superseded' WHERE season = %s AND status = 'approved'",
                       (row["season"],))
        cursor.execute("UPDATE season_rulesets SET status = 'approved', reviewed_by = %s, reviewed_at = %s, "
                       "review_note = %s WHERE id = %s RETURNING *", (reviewer, now, record, ruleset_id))
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
                                           "approved by a named, qualified FRC-domain reviewer (P6-M1)")
    ruleset = SeasonRuleset.model_validate(row[0])
    if ruleset.sha256() != row[1]:
        raise RulesetError("storage_integrity", f"the approved {season} ruleset does not match its sha256")
    return ruleset


def approved_seasons(database: Database) -> list[int]:
    with database.cursor() as cursor:
        cursor.execute("SELECT season FROM season_rulesets WHERE status = 'approved' ORDER BY season")
        return [r[0] for r in cursor.fetchall()]
