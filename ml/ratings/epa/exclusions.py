"""Exclusion codes and the run's exclusion report (data contract §4-§5).

Four kinds of outcome, kept apart because they mean different things:

* run rejection -- the input is unusable as a whole; RunRejected is raised and
  nothing is computed.
* filter -- the reference excludes this too, so it is not a divergence.
* reject -- a STRATAI refusal the reference would not make (it would zero-fill
  or synthesize instead); counted as a definite Level A divergence.
* skip -- predicted and recorded, but the rating update is not applied, the
  reference's own rule (models/template.py:77-90).

Possible divergences are cases where STRATAI's result is correct by the
specification but the reference's published value may differ for reasons
outside the match's own data (tie ordering, the reference's shared
empty-breakdown state; spec §11). They are counted, never hidden.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# Run rejections
UNSUPPORTED_SEASON = "unsupported_season"
DUPLICATE_MATCH_KEY = "duplicate_match_key"
DUPLICATE_EVENT_KEY = "duplicate_event_key"
UNKNOWN_EVENT = "unknown_event"
EVENT_SEASON_MISMATCH = "event_season_mismatch"
PRIOR_NOT_BEFORE_SEASON = "prior_not_before_season"
TEAM_DISTRICTS_REQUIRED = "team_districts_required"
NO_WEEK_ONE_DATA = "no_week_one_data"

RUN_REJECTION_CODES: tuple[str, ...] = (
    UNSUPPORTED_SEASON, DUPLICATE_MATCH_KEY, DUPLICATE_EVENT_KEY, UNKNOWN_EVENT,
    EVENT_SEASON_MISMATCH, PRIOR_NOT_BEFORE_SEASON, TEAM_DISTRICTS_REQUIRED, NO_WEEK_ONE_DATA,
)

# Filters (the reference excludes these too)
EVENT_BLACKLISTED = "event_blacklisted"
EVENT_TYPE_EXCLUDED = "event_type_excluded"
EVENT_WEEK_MISSING = "event_week_missing"
INVALID_ALLIANCE = "invalid_alliance"

# Rejections (definite divergences)
MISSING_TIME = "missing_time"
MISSING_BREAKDOWN = "missing_breakdown"
MALFORMED_BREAKDOWN = "malformed_breakdown"

# Match statuses that are neither filtered nor rejected
UPCOMING = "upcoming"
ZERO_SCORE = "zero_score"
SKIP_PLACEHOLDER = "skip_placeholder"
SKIP_ELIM_ALL_DQ = "skip_elim_all_dq"
SKIP_ALL_FOULS = "skip_all_fouls"
UPDATED = "updated"

# Possible divergences
TIE_ORDER = "tie_order"
SHARED_EMPTY_BREAKDOWN = "shared_empty_breakdown"

MATCH_CODES: tuple[str, ...] = (
    EVENT_BLACKLISTED, EVENT_TYPE_EXCLUDED, EVENT_WEEK_MISSING, INVALID_ALLIANCE,
    MISSING_TIME, UPCOMING, MISSING_BREAKDOWN, MALFORMED_BREAKDOWN, ZERO_SCORE,
    SKIP_PLACEHOLDER, SKIP_ELIM_ALL_DQ, SKIP_ALL_FOULS,
)
DEFINITE_DIVERGENCE_CODES: tuple[str, ...] = (MISSING_TIME, MISSING_BREAKDOWN, MALFORMED_BREAKDOWN)
POSSIBLE_DIVERGENCE_CODES: tuple[str, ...] = (TIE_ORDER, SHARED_EMPTY_BREAKDOWN)


class RunRejected(ValueError):
    """The SeasonInput cannot be run at all. Nothing partial is returned."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ExclusionEntry:
    code: str
    event_key: str
    match_key: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "event_key": self.event_key, "match_key": self.match_key, "detail": self.detail}


@dataclass(frozen=True)
class TieGroup:
    """Retained matches sharing one scheduled time, in the order processed."""

    time: int
    match_keys: tuple[str, ...]
    order_sensitive: bool  # some team plays in two of them, so order changes ratings

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "match_keys": list(self.match_keys), "order_sensitive": self.order_sensitive}


@dataclass
class ExclusionCollector:
    """Accumulates entries while a season is prepared and run."""

    entries: list[ExclusionEntry] = field(default_factory=list)
    ties: list[TieGroup] = field(default_factory=list)
    shared_empty_alliances: int = 0

    def add(self, code: str, event_key: str, match_key: str | None, detail: str) -> None:
        self.entries.append(ExclusionEntry(code, event_key, match_key, detail))

    def report(self) -> ExclusionReport:
        counts = Counter(entry.code for entry in self.entries)
        entries = tuple(sorted(self.entries, key=lambda e: (e.code, e.match_key or "", e.event_key, e.detail)))
        possible = {
            TIE_ORDER: sum(1 for tie in self.ties if tie.order_sensitive),
            SHARED_EMPTY_BREAKDOWN: self.shared_empty_alliances,
        }
        return ExclusionReport(
            counts={code: counts.get(code, 0) for code in MATCH_CODES},
            entries=entries,
            ties=tuple(self.ties),
            divergences={code: counts.get(code, 0) for code in DEFINITE_DIVERGENCE_CODES},
            possible_divergences=possible,
        )


@dataclass(frozen=True)
class ExclusionReport:
    counts: dict[str, int]
    entries: tuple[ExclusionEntry, ...]
    ties: tuple[TieGroup, ...]
    divergences: dict[str, int]
    possible_divergences: dict[str, int]

    @property
    def has_divergences(self) -> bool:
        return any(self.divergences.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "entries": [e.to_dict() for e in self.entries],
            "ties": [t.to_dict() for t in self.ties],
            "divergences": dict(self.divergences),
            "possible_divergences": dict(self.possible_divergences),
        }
