"""Phase 11: a team's live alliance-selection draft record, as an append-only log, and its replay.

docs/P11-P19Phases.md §5; decisions in .agent/phase11/decisions/P11_Q1_Q4_DECISIONS_2026-11-04.md.

**The log is the record.** Nothing in it is ever updated or deleted. The current state is derived by replaying it
(`replay`), so the state at any earlier point is the replay of a prefix (`replay(entries[:k])`), and Phase 12 can
synchronize logs rather than snapshots. Each entry has a stable action id that the client or the local server
creates, a per-record sequence, an author and a time, and a `source` (`manual` or `imported`).

**Entry types:**
- `configure`: the record's setup, which holds the rules, the final qualification ranks, the selection pool, what
  is missing and where each part came from.
  - The latest `configure` governs. Configuration is state, not a draft event, so a new one re-validates every
    draft action.
- The draft actions, in real order:
  - `captain`: seed N's captain is now team C. This is a captain named when its seed's first turn comes, which
    covers promotion.
  - `pick`: seed N's captain invites T, and T accepts.
  - `decline`: T declines seed N's invitation.
  - `backup`: T is a backup robot (`seed` is optional), when the rules use backups.
- `undo`: removes the most recent effective draft action.
- `correct`: replaces an earlier effective draft action with another, or with nothing ("it did not happen"). Every
  later action is re-validated.
- `close` / `reopen`.

**One draft model.** The state is the P6 `DraftState`, the serpentine order is `ml.playoffs.selection.turn_order`,
and the pool and captain rules are `pickable_teams` and `highest_ranked_captain`: the same rules the P6-M6 draft
model and the P7-M6 state check apply. A captain is named when its seed's first turn comes, as the draft model names
it.

**Validation.**
- A draft action that the rules make impossible gets a `Violation` (code and message).
- A violation recorded with an `override_reason` is accepted as an override: the room did something the rules do
  not model.
- A violation that appears only later, after a correction or a new configuration, is flagged `invalid`. The action
  is still applied when that is structurally possible, because it is what the room did. Otherwise it is
  `not_applied`.
- Nothing is silently dropped.
- A check that cannot be made (no ranks, or a captain rule that is not established) is never failed and never
  guessed. It is noted as unchecked.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from data.rulesets import RulesetError
from ml.playoffs.selection import DraftState, highest_ranked_captain, pickable_teams, turn_order

CONFIGURE, PICK, DECLINE, CAPTAIN, BACKUP, UNDO, CORRECT, CLOSE, REOPEN = (
    "configure", "pick", "decline", "captain", "backup", "undo", "correct", "close", "reopen")
DRAFT_TYPES = (CAPTAIN, PICK, DECLINE, BACKUP)
ENTRY_TYPES = (CONFIGURE, *DRAFT_TYPES, UNDO, CORRECT, CLOSE, REOPEN)
SOURCES = ("manual", "imported")
RULES_SOURCES = ("approved_ruleset", "manual_entry")

ACCEPTED, OVERRIDDEN, INVALID, NOT_APPLIED = "accepted", "overridden", "invalid", "not_applied"
MAX_REASON = 500


class DraftLogError(ValueError):
    """A log entry that cannot be part of the record at all (an unknown type, a malformed payload, an undo or
    correction whose target is not an effective draft action). The service refuses it; replay reports it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


# --- setup -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftRules:
    """The selection rules the record checks against: an event's approved P6-M1 rules, or the values an
    administrator entered from the event when no approved ruleset covers it (`source: manual_entry`)."""

    n_alliances: int
    picks_per_alliance: int
    declined_team_may_be_picked_later: bool
    declined_team_may_become_captain: bool | None  # None: not established (P6-M1 `unresolved`)
    captain_may_accept_higher_alliance: bool
    backup_robots: bool
    captain_rule_established: bool  # the ruleset's captain_rule is highest_ranked_available (else unresolved)
    source: str
    ruleset_sha256: str | None = None
    ruleset_variant: str | None = None

    def __post_init__(self) -> None:
        if self.source not in RULES_SOURCES:
            raise DraftLogError("invalid_setup", f"unknown rules source {self.source!r}")
        for name in ("declined_team_may_be_picked_later", "captain_may_accept_higher_alliance", "backup_robots",
                     "captain_rule_established"):
            if not isinstance(getattr(self, name), bool):
                raise DraftLogError("invalid_setup", f"the rule {name} must be true or false")
        if self.declined_team_may_become_captain is not None and not isinstance(
                self.declined_team_may_become_captain, bool):
            raise DraftLogError("invalid_setup", "declined_team_may_become_captain is true, false or not established")
        for name in ("n_alliances", "picks_per_alliance"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                raise DraftLogError("invalid_setup", f"{name} must be a whole number")
        if not 2 <= self.n_alliances <= 16 or not 1 <= self.picks_per_alliance <= 4:
            raise DraftLogError("invalid_setup", "an event has 2-16 alliances and 1-4 picks per alliance")

    def order(self) -> list[int]:
        return turn_order(self.n_alliances, self.picks_per_alliance)

    def to_json(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DraftRules:
        try:
            return cls(**{name: data.get(name) for name in cls.__dataclass_fields__})
        except TypeError as exc:
            raise DraftLogError("invalid_setup", f"malformed rules: {exc}") from None


@dataclass(frozen=True)
class DraftSetup:
    """Everything a record checks against, fixed when it is configured so that replay is deterministic.

    `ranks` are the final qualification ranks (team -> rank), and are None when they are not available. `pool` is
    the selection pool (the qualification roster), and is None when it is not known. `missing` names each missing
    input. `provenance` says where each part came from (the ranking payload's fetch time, the ruleset sha256, and who
    entered manual rules)."""

    rules: DraftRules
    ranks: Mapping[int, int] | None
    pool: tuple[int, ...] | None
    missing: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def candidates(self) -> list[int]:
        """Every team that could take part, strongest seed first (rank order; unranked teams by number)."""
        teams = set(self.pool or ()) | set(self.ranks or ())
        return sorted(teams, key=self.rank_key)

    def rank_key(self, team: int) -> tuple[int, int]:
        return ((self.ranks or {}).get(team, 10 ** 6), team)

    def to_json(self) -> dict[str, Any]:
        return {"rules": self.rules.to_json(),
                "ranks": None if self.ranks is None else [[t, r] for t, r in sorted(self.ranks.items())],
                "pool": None if self.pool is None else list(self.pool), "missing": list(self.missing),
                "provenance": dict(self.provenance)}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> DraftSetup:
        if not isinstance(data, Mapping) or not isinstance(data.get("rules"), Mapping):
            raise DraftLogError("invalid_setup", "a configure entry carries a rules object")
        ranks = data.get("ranks")
        pool = data.get("pool")
        try:
            return cls(DraftRules.from_json(data["rules"]),
                       None if ranks is None else {int(t): int(r) for t, r in ranks},
                       None if pool is None else tuple(int(t) for t in pool),
                       tuple(str(m) for m in data.get("missing") or ()), dict(data.get("provenance") or {}))
        except (TypeError, ValueError) as exc:
            raise DraftLogError("invalid_setup", f"malformed setup: {exc}") from None


# --- entries ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftAction:
    """One draft action: a captain named, a pick, a decline or a backup."""

    type: str
    seed: int | None
    team: int

    @classmethod
    def from_payload(cls, type_: str, payload: Mapping[str, Any]) -> DraftAction:
        if type_ not in DRAFT_TYPES:
            raise DraftLogError("invalid_action", f"{type_!r} is not a draft action")
        team, seed = payload.get("team"), payload.get("seed")
        if isinstance(team, bool) or not isinstance(team, int) or team < 1:
            raise DraftLogError("invalid_action", "a draft action names a team number")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 1):
            raise DraftLogError("invalid_action", "a seed is a positive alliance number")
        if seed is None and type_ != BACKUP:
            raise DraftLogError("invalid_action", f"a {type_} names the alliance (seed) it belongs to")
        return cls(type_, seed, team)

    def payload(self) -> dict[str, Any]:
        return {"seed": self.seed, "team": self.team}

    def describe(self) -> str:
        if self.type == CAPTAIN:
            return f"Alliance {self.seed}'s captain is team {self.team}"
        if self.type == PICK:
            return f"Alliance {self.seed} picks team {self.team}"
        if self.type == DECLINE:
            return f"Team {self.team} declines alliance {self.seed}"
        return f"Team {self.team} is a backup" + (f" for alliance {self.seed}" if self.seed else "")


@dataclass(frozen=True)
class LogEntry:
    """One stored log entry (a draft_actions row)."""

    action_id: str
    seq: int
    type: str
    payload: Mapping[str, Any]
    override_reason: str | None = None
    author_label: str = ""
    author_user_id: int | None = None
    recorded_at: datetime | None = None
    source: str = "manual"
    mode: str = "online"


# --- replay -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveAction:
    """A draft action in effect after undos and corrections, with its validation outcome."""

    slot_action_id: str  # the entry that first recorded this position in the draft
    action_id: str  # the entry whose content is in effect (the original, or the latest correction)
    seq: int
    action: DraftAction
    status: str  # accepted | overridden | invalid | not_applied
    violation: Violation | None
    override_reason: str | None
    notes: tuple[str, ...]
    author_label: str
    recorded_at: datetime | None


@dataclass(frozen=True)
class HistoryItem:
    """One log entry as the history shows it: what it did and what superseded it."""

    entry: LogEntry
    summary: str
    superseded_by: str | None  # the undo/correct entry that removed or replaced it
    in_effect: bool


@dataclass
class _Core:
    alliances: list[list[int]]
    declined: dict[int, int]  # team -> the seed whose invitation it declined (the latest)
    backups: dict[int, int | None]
    picks_made: int = 0

    def draft_state(self) -> DraftState:
        return DraftState(tuple(tuple(a) for a in self.alliances), frozenset(self.declined), self.picks_made)

    def on_alliance(self) -> set[int]:
        return {t for a in self.alliances for t in a}


@dataclass(frozen=True)
class DraftView:
    """The record replayed: its setup, its status, the effective draft, and the history."""

    record_seq: int  # the last entry's sequence (0 for an empty log)
    setup: DraftSetup | None
    closed: bool
    effective: tuple[EffectiveAction, ...]
    history: tuple[HistoryItem, ...]
    alliances: tuple[tuple[int, ...], ...]
    declined: Mapping[int, int]
    backups: Mapping[int, int | None]
    picks_made: int

    @property
    def flagged(self) -> tuple[EffectiveAction, ...]:
        return tuple(a for a in self.effective if a.status in (INVALID, NOT_APPLIED))

    def draft_state(self) -> DraftState:
        return DraftState(self.alliances, frozenset(self.declined), self.picks_made)

    def order(self) -> list[int]:
        return [] if self.setup is None else self.setup.rules.order()

    @property
    def complete(self) -> bool:
        return self.setup is not None and self.picks_made >= len(self.order())

    def acting_seed(self) -> int | None:
        order = self.order()
        return order[self.picks_made] if self.picks_made < len(order) else None

    def round_number(self) -> int | None:
        if self.setup is None or self.complete:
            return None
        return self.picks_made // self.setup.rules.n_alliances + 1

    def turns_before(self, seed: int) -> int | None:
        """Other alliances' picks before `seed`'s next turn (0 when it is `seed`'s turn); None if none remains."""
        order = self.order()
        for index in range(self.picks_made, len(order)):
            if order[index] == seed:
                return index - self.picks_made
        return None

    def projected_captains(self) -> dict[int, int | None]:
        """For each seed without a captain: the team the captain rule names if every later turn named the next
        captain now. Projection only (labelled so wherever it is shown); None when it cannot be made."""
        if self.setup is None or not self.setup.ranks or not self.setup.rules.captain_rule_established:
            return {seed: None for seed, a in enumerate(self.alliances, 1) if not a}
        ranks = {t: r for t, r in self.setup.ranks.items()}
        alliances = [list(a) for a in self.alliances]
        out: dict[int, int | None] = {}
        for seed, alliance in enumerate(alliances, start=1):
            if alliance:
                continue
            try:
                captain = highest_ranked_captain(
                    DraftState(tuple(tuple(a) for a in alliances), frozenset(self.declined), self.picks_made), ranks,
                    declined_team_may_become_captain=self.setup.rules.declined_team_may_become_captain,
                    label="this event")
            except RulesetError:
                out[seed] = None
                continue
            out[seed] = captain
            alliances[seed - 1] = [captain]
        return out

    def expected_captain(self) -> tuple[int | None, Violation | None]:
        """The captain the rules name for the acting seed now, or why it cannot be named."""
        seed = self.acting_seed()
        if seed is None or self.setup is None or self.alliances[seed - 1]:
            return None, None
        return _expected_captain(self.setup, self.draft_state())

    def availability(self) -> tuple[list[int], dict[int, str]]:
        """(available teams in rank order, {unavailable team: reason}), under the record's rules."""
        unavailable: dict[int, str] = {}
        for alliance in self.alliances:
            for position, team in enumerate(alliance):
                unavailable[team] = "captain" if position == 0 else "picked"
        if self.setup is not None and not self.setup.rules.declined_team_may_be_picked_later:
            for team in self.declined:
                unavailable.setdefault(team, "declined")
        for team in self.backups:
            unavailable.setdefault(team, "backup")
        acting = self.acting_seed()
        if self.setup is not None and not self.setup.rules.captain_may_accept_higher_alliance and acting is not None:
            # A team the rules will make a lower alliance's captain cannot join the acting (higher) alliance.
            for seed, captain in self.projected_captains().items():
                if captain is not None and seed > acting:
                    unavailable.setdefault(captain, "projected_captain")
        candidates = [] if self.setup is None else self.setup.candidates()
        state = self.draft_state()
        rule = True if self.setup is None else self.setup.rules.declined_team_may_be_picked_later
        pickable = set(pickable_teams(state, candidates, declined_team_may_be_picked_later=rule))
        available = [t for t in candidates if t in pickable and t not in unavailable]
        return available, unavailable


def _expected_captain(setup: DraftSetup, state: DraftState) -> tuple[int | None, Violation | None]:
    if not setup.ranks:
        return None, Violation("captain_unchecked", "the final qualification ranks are not available, so the "
                                                    "captain cannot be checked")
    if not setup.rules.captain_rule_established:
        return None, Violation("captain_unchecked", "the event's captain rule is not established by its ruleset, "
                                                    "so the captain cannot be checked")
    try:
        return highest_ranked_captain(state, dict(setup.ranks),
                                      declined_team_may_become_captain=setup.rules.declined_team_may_become_captain,
                                      label="this event"), None
    except RulesetError as exc:
        code = "captain_rule_not_established" if exc.code == "not_established" else "no_eligible_captain"
        return None, Violation(code, str(exc))


def check_action(setup: DraftSetup, core: _Core, action: DraftAction) -> tuple[Violation | None, tuple[str, ...]]:
    """The first rule `action` breaks from `core` under `setup` (or None), plus notes on checks that could not be
    made. Pure: `core` is not changed."""
    rules = setup.rules
    order = rules.order()
    notes: list[str] = []
    in_pool = setup.pool is None or action.team in setup.pool or action.team in (setup.ranks or {})
    if setup.pool is None and not setup.ranks:
        notes.append("team_unchecked: the event's selection pool is not known")
    if action.seed is not None and action.seed > rules.n_alliances:
        return Violation("unknown_alliance", f"the event has {rules.n_alliances} alliances"), ()
    on_alliance = core.on_alliance()
    acting = order[core.picks_made] if core.picks_made < len(order) else None

    if action.type == BACKUP:
        if not rules.backup_robots:
            return Violation("backups_not_used", "the event's rules do not use backup robots"), ()
        if acting is not None:
            return Violation("draft_incomplete", "backup robots are recorded once every pick is made"), ()
        if action.team in on_alliance:
            return Violation("team_on_alliance", f"team {action.team} is already on an alliance"), ()
        if action.team in core.backups:
            return Violation("already_backup", f"team {action.team} is already a backup"), ()
        if not in_pool:
            return Violation("team_not_in_pool", f"team {action.team} is not in this event's selection pool"), ()
        return None, tuple(notes)

    if acting is None:
        return Violation("draft_complete", "every pick of the draft has been made"), ()
    if action.seed != acting:
        return Violation("wrong_turn", f"it is alliance {acting}'s turn, not alliance {action.seed}'s"), ()
    if action.team in on_alliance:
        return Violation("team_on_alliance", f"team {action.team} is already on an alliance"), ()
    if not in_pool:
        return Violation("team_not_in_pool", f"team {action.team} is not in this event's selection pool"), ()

    if action.type == CAPTAIN:
        if core.alliances[action.seed - 1]:
            return Violation("captain_already_named",
                             f"alliance {action.seed}'s captain is already team {core.alliances[action.seed - 1][0]}"), ()
        expected, problem = _expected_captain(setup, core.draft_state())
        if problem is not None and problem.code == "captain_unchecked":
            return None, (*notes, f"captain_unchecked: {problem.message}")
        if problem is not None:
            return problem, ()
        if expected != action.team:
            return Violation("wrong_captain", f"the captain rule names team {expected} as alliance {action.seed}'s "
                                              f"captain, not team {action.team}"), ()
        return None, tuple(notes)

    if not core.alliances[action.seed - 1]:
        return Violation("captain_not_named", f"alliance {action.seed}'s captain must be recorded first"), ()
    if action.team in core.declined and not rules.declined_team_may_be_picked_later:
        return Violation("team_declined", f"team {action.team} declined an invitation, and the event's rules do not "
                                          "let it be picked later"), ()
    if action.type == PICK:
        if len(core.alliances[action.seed - 1]) >= 1 + rules.picks_per_alliance:
            return Violation("alliance_full", f"alliance {action.seed} already has every pick"), ()
        if not rules.captain_may_accept_higher_alliance:
            view = _view_of(setup, core)
            later = {s: t for s, t in view.projected_captains().items() if s > action.seed and t is not None}
            if action.team in later.values():
                return Violation("captain_not_pickable", f"team {action.team} is projected to captain a lower "
                                                         "alliance, and the event's rules do not let a captain join a "
                                                         "higher alliance"), ()
    return None, tuple(notes)


def _structurally_applicable(setup: DraftSetup, core: _Core, action: DraftAction) -> bool:
    if action.seed is not None and not 1 <= action.seed <= setup.rules.n_alliances:
        return False
    if action.type == CAPTAIN:
        return action.team not in core.on_alliance() and not core.alliances[action.seed - 1]
    if action.type == PICK:
        return action.team not in core.on_alliance() and bool(core.alliances[action.seed - 1])
    if action.type == DECLINE:
        return action.team not in core.on_alliance()
    return action.team not in core.on_alliance() and action.team not in core.backups


def _apply(core: _Core, action: DraftAction) -> None:
    if action.type == CAPTAIN:
        core.alliances[action.seed - 1] = [action.team]
    elif action.type == PICK:
        core.alliances[action.seed - 1].append(action.team)
        core.picks_made += 1
    elif action.type == DECLINE:
        core.declined[action.team] = action.seed
    else:
        core.backups[action.team] = action.seed


def _view_of(setup: DraftSetup, core: _Core) -> DraftView:
    return DraftView(0, setup, False, (), (), tuple(tuple(a) for a in core.alliances), dict(core.declined),
                     dict(core.backups), core.picks_made)


def _target(payload: Mapping[str, Any]) -> str:
    target = payload.get("target_action_id")
    if not isinstance(target, str) or not target:
        raise DraftLogError("invalid_action", "an undo or correction names the action it applies to")
    return target


@dataclass
class _Slot:
    origin: LogEntry
    current: LogEntry
    action: DraftAction | None  # None: removed (undone, or corrected to "did not happen")


def replay(entries: Sequence[LogEntry], *, strict: bool = False) -> DraftView:
    """Replay a record's log, in sequence order. With strict=True, an entry that cannot be part of the record raises
    DraftLogError (the service's append check); otherwise it is shown in the history as having had no effect."""
    entries = sorted(entries, key=lambda e: e.seq)
    setup: DraftSetup | None = None
    closed = False
    slots: list[_Slot] = []
    by_current: dict[str, int] = {}
    superseded: dict[str, str] = {}
    no_effect: set[str] = set()
    summaries: dict[str, str] = {}
    last_configure: str | None = None

    def fail(entry: LogEntry, exc: DraftLogError) -> None:
        if strict:
            raise exc
        no_effect.add(entry.action_id)
        summaries[entry.action_id] = f"No effect: {exc.message}"

    for entry in entries:
        try:
            if entry.type not in ENTRY_TYPES:
                raise DraftLogError("invalid_action", f"unknown entry type {entry.type!r}")
            if entry.type == CONFIGURE:
                setup = DraftSetup.from_json(entry.payload)
                if last_configure is not None:  # the latest configuration governs; earlier ones are superseded
                    superseded[last_configure] = entry.action_id
                last_configure = entry.action_id
                summaries[entry.action_id] = "Record configured" + (
                    f" (missing: {', '.join(setup.missing)})" if setup.missing else "")
            elif entry.type == CLOSE:
                closed = True
                summaries[entry.action_id] = "Record closed"
            elif entry.type == REOPEN:
                closed = False
                summaries[entry.action_id] = "Record reopened"
            elif entry.type in DRAFT_TYPES:
                action = DraftAction.from_payload(entry.type, entry.payload)
                by_current[entry.action_id] = len(slots)
                slots.append(_Slot(entry, entry, action))
                summaries[entry.action_id] = action.describe()
            elif entry.type == UNDO:
                target = _target(entry.payload)
                live = [i for i, s in enumerate(slots) if s.action is not None]
                if not live or slots[live[-1]].current.action_id != target:
                    raise DraftLogError("not_last_action", "undo removes only the most recent action in effect")
                slot = slots[live[-1]]
                superseded[slot.current.action_id] = entry.action_id
                slot.action = None
                summaries[entry.action_id] = f"Undid: {summaries.get(target, target)}"
            else:  # CORRECT
                target = _target(entry.payload)
                index = by_current.get(target)
                if index is None or slots[index].action is None or slots[index].current.action_id != target:
                    raise DraftLogError("not_in_effect", "a correction replaces an action that is in effect")
                replacement = entry.payload.get("replacement")
                new = None if replacement is None else DraftAction.from_payload(
                    replacement.get("type") if isinstance(replacement, Mapping) else None,
                    replacement if isinstance(replacement, Mapping) else {})
                slot = slots[index]
                superseded[slot.current.action_id] = entry.action_id
                del by_current[target]
                slot.current, slot.action = entry, new
                by_current[entry.action_id] = index
                summaries[entry.action_id] = (f"Corrected '{summaries.get(target, target)}' to "
                                              + ("'it did not happen'" if new is None else f"'{new.describe()}'"))
        except DraftLogError as exc:
            fail(entry, exc)

    effective: list[EffectiveAction] = []
    core = _Core([[] for _ in range(setup.rules.n_alliances)] if setup else [], {}, {})
    for slot in slots:
        if slot.action is None:
            continue
        entry, action = slot.current, slot.action
        if setup is None:
            violation, notes = Violation("not_configured", "the record has no setup"), ()
        else:
            violation, notes = check_action(setup, core, action)
        override = entry.override_reason
        if violation is None:
            status = ACCEPTED
        elif override:
            status = OVERRIDDEN
        else:
            status = INVALID
        if setup is not None and _structurally_applicable(setup, core, action):
            _apply(core, action)
        else:
            status = NOT_APPLIED
        effective.append(EffectiveAction(slot.origin.action_id, entry.action_id, entry.seq, action, status, violation,
                                         override, notes, entry.author_label, entry.recorded_at))

    history = tuple(HistoryItem(e, summaries.get(e.action_id, e.type), superseded.get(e.action_id),
                                e.action_id not in superseded and e.action_id not in no_effect) for e in entries)
    return DraftView(entries[-1].seq if entries else 0, setup, closed, tuple(effective), history,
                     tuple(tuple(a) for a in core.alliances), dict(core.declined), dict(core.backups),
                     core.picks_made)


def check_append(entries: Sequence[LogEntry], new: LogEntry) -> tuple[DraftView, Violation | None]:
    """Replay `entries` plus `new` strictly. Returns the resulting view, and the violation `new` itself carries
    (for a draft action, or a correction's replacement) when it has no override. DraftLogError if `new` cannot be
    part of the record at all."""
    view = replay([*entries, new], strict=True)
    if new.type in DRAFT_TYPES or new.type == CORRECT:
        mine = next((a for a in view.effective if a.action_id == new.action_id), None)
        if mine is not None and mine.violation is not None and not new.override_reason:
            return view, mine.violation
        if mine is not None and mine.status == NOT_APPLIED:
            return view, mine.violation or Violation("not_applicable", "the action cannot apply to this state")
    return view, None


def view_json(view: DraftView, *, team_number: int | None = None) -> dict[str, Any]:
    """The board and history as the API serves them. Every team is labelled with its source: recorded (observed),
    or projected from the rules and ranks."""
    available, unavailable = view.availability()
    projected = view.projected_captains() if view.setup is not None else {}
    ranks = dict(view.setup.ranks or {}) if view.setup is not None else {}
    acting = view.acting_seed()
    expected, why = view.expected_captain()
    projected_seed = {c: s for s, c in projected.items() if c is not None}
    alliances = []
    for seed, alliance in enumerate(view.alliances, start=1):
        alliances.append({"seed": seed, "captain": alliance[0] if alliance else None, "picks": list(alliance[1:]),
                          "projected_captain": projected.get(seed) if not alliance else None})
    return {
        "record_seq": view.record_seq, "status": "closed" if view.closed else "open", "configured": view.setup is not None,
        "setup": None if view.setup is None else view.setup.to_json(),
        "alliances": alliances,
        "turn": None if acting is None else {
            "index": view.picks_made, "round": view.round_number(), "seed": acting,
            "captain_named": bool(view.alliances[acting - 1]), "expected_captain": expected,
            "expected_captain_reason": None if why is None else why.message},
        "complete": view.complete,
        "available": [{"team_number": t, "rank": ranks.get(t),
                       "projected_captain_of": next((s for s, c in projected.items() if c == t), None),
                       "declined_earlier": t in view.declined} for t in available],
        "unavailable": [{"team_number": t, "reason": r, "rank": ranks.get(t),
                         "seed": next((s for s, a in enumerate(view.alliances, 1) if t in a), None)
                         if r in ("captain", "picked") else view.declined.get(t) if r == "declined" else
                         view.backups.get(t) if r == "backup" else projected_seed.get(t)}
                        for t, r in sorted(unavailable.items(), key=lambda tr: (ranks.get(tr[0], 10 ** 6), tr[0]))],
        "declined": [{"team_number": t, "seed": s} for t, s in view.declined.items()],
        "backups": [{"team_number": t, "seed": s} for t, s in view.backups.items()],
        "flags": [{"action_id": a.action_id, "status": a.status, "code": a.violation.code if a.violation else None,
                   "message": a.violation.message if a.violation else None} for a in view.flagged],
        "effective": [{"action_id": a.action_id, "slot_action_id": a.slot_action_id, "seq": a.seq,
                       "type": a.action.type, "seed": a.action.seed, "team_number": a.action.team,
                       "status": a.status, "violation": None if a.violation is None else
                       {"code": a.violation.code, "message": a.violation.message},
                       "override_reason": a.override_reason, "notes": list(a.notes), "summary": a.action.describe(),
                       "recorded_by": a.author_label, "recorded_at": a.recorded_at} for a in view.effective],
        "history": [{"action_id": h.entry.action_id, "seq": h.entry.seq, "type": h.entry.type,
                     "summary": h.summary, "override_reason": h.entry.override_reason, "in_effect": h.in_effect,
                     "superseded_by": h.superseded_by, "recorded_by": h.entry.author_label,
                     "recorded_at": h.entry.recorded_at, "source": h.entry.source, "mode": h.entry.mode}
                    for h in view.history],
        "team_number": team_number,
    }


__all__ = [
    "ACCEPTED", "BACKUP", "CAPTAIN", "CLOSE", "CONFIGURE", "CORRECT", "DECLINE", "DRAFT_TYPES", "DraftAction",
    "DraftLogError", "DraftRules", "DraftSetup", "DraftView", "EffectiveAction", "ENTRY_TYPES", "INVALID", "LogEntry",
    "NOT_APPLIED", "OVERRIDDEN", "PICK", "REOPEN", "SOURCES", "UNDO", "Violation", "check_action", "check_append",
    "replay", "view_json",
]
