"""P6-M9: coach-entered strategies and observations, stored raw-first and validated against the vocabulary.

**Raw first (the Phase 2/3/5 convention).**
- Every submission is landed untouched in `raw_source_payloads` (source `coach_input`) before validation.
- A submission that fails validation stays recorded and is never applied.
- Each submission is its own object, keyed by the sha256 of its canonical payload, so nothing supersedes anything.

**Provenance travels beside the strategy, never inside it.** The author and time a coach supplies become a
`StrategyProvenance`; the `Strategy` itself has no origin field.

**Point in time.** Observations are usable only for predictions strictly after their `observed_at`. Notes or any
other free text in a raw submission are kept in the raw layer only and never reach a model (P6-A9).

This module is a service function, not an HTTP route: Phase 6 exposes no endpoints (P6-A1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from database.connection import Database
from ml.strategy.representation import CoachObservation, Strategy, StrategyProvenance, StrategyRecord

COACH_SOURCE = "coach_input"
STRATEGY_OBJECT_TYPE = "strategy"
OBSERVATION_OBJECT_TYPE = "observation"
_OBSERVATION_FIELDS = ("event_key", "team_number", "kind", "component", "observed_at", "observer")


class CoachInputError(ValueError):
    """A coach submission that does not satisfy the representation. It stays landed in the raw layer."""

    def __init__(self, message: str, problems: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


def _object_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _land(database: Database, object_type: str, payload: dict[str, Any]) -> None:
    RawPayloadWriter(database).write(RawPayloadRecord(COACH_SOURCE, object_type, _object_id(payload), payload))


def _problems(exc: ValidationError) -> list[dict[str, str]]:
    return [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]


def submit_coach_strategy(database: Database, payload: dict[str, Any], *,
                          now: datetime | None = None) -> StrategyRecord:
    """Land a coach's strategy raw, then validate it.

    `payload` = {"event_key", "match_key" (optional), "author", "strategy": {...}}.
    """
    if not isinstance(payload, dict):
        raise CoachInputError("a coach strategy submission must be an object")
    received = (now or datetime.now(timezone.utc)).isoformat()
    _land(database, STRATEGY_OBJECT_TYPE, {**payload, "received_at": received})
    try:
        strategy = Strategy.model_validate(payload.get("strategy"))
        provenance = StrategyProvenance(origin="human_entered", author=payload.get("author") or "",
                                        created_at=datetime.fromisoformat(received))
        return StrategyRecord(strategy=strategy, provenance=provenance, event_key=payload.get("event_key") or "",
                              match_key=payload.get("match_key"))
    except ValidationError as exc:
        raise CoachInputError("the coach strategy does not satisfy the strategy vocabulary", _problems(exc)) from exc


def submit_coach_observation(database: Database, payload: dict[str, Any]) -> CoachObservation:
    """Land a coach observation raw, then validate it. Any free text stays in the raw layer only."""
    if not isinstance(payload, dict):
        raise CoachInputError("a coach observation must be an object")
    _land(database, OBSERVATION_OBJECT_TYPE, payload)
    try:
        return CoachObservation.model_validate({k: payload.get(k) for k in _OBSERVATION_FIELDS})
    except ValidationError as exc:
        raise CoachInputError("the coach observation does not satisfy the schema", _problems(exc)) from exc


def load_coach_observations(database: Database, event_key: str, as_of: datetime) -> tuple[
        tuple[CoachObservation, ...], int]:
    """Valid observations for the event with observed_at strictly before as_of, in a deterministic order, plus
    the number of landed submissions that failed validation (reported, never applied)."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must carry a timezone")
    with database.cursor() as cursor:
        cursor.execute("SELECT payload_json FROM raw_source_payloads WHERE source = %s AND source_object_type = %s "
                       "AND payload_json->>'event_key' = %s ORDER BY id",
                       (COACH_SOURCE, OBSERVATION_OBJECT_TYPE, event_key))
        payloads = [row[0] for row in cursor.fetchall()]
    valid, invalid = [], 0
    for payload in payloads:
        try:
            observation = CoachObservation.model_validate({k: payload.get(k) for k in _OBSERVATION_FIELDS})
        except ValidationError:
            invalid += 1
            continue
        if observation.observed_at < as_of:
            valid.append(observation)
    return tuple(sorted(set(valid), key=CoachObservation.sort_key)), invalid
