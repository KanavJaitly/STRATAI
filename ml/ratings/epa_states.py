"""EPA source states: why a particular EPA value was, or was not, served.

The vocabulary of `.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md` §5 (decision P5-D2),
shared by the feature assembler, the Phase 5 views and the live provider:

    current                  a valid, processed Statbotics value from a healthy snapshot
    stale                    a valid processed Statbotics value served from the last good
                             snapshot while refreshes of other events are failing
    pending                  the D13 candidate ended < 72 h ago and is not processed:
                             refused, never replaced by an older event
    fallback_stratai         unprocessed by Statbotics >= 72 h after the event ended:
                             STRATAI's independent EPA, labelled "STRATAI EPA"
    unavailable              no servable value from either source: refused
    withheld_no_prior_event  no D13 candidate exists: EPA absent (legitimate)

Only `current`, `stale` and `fallback_stratai` accompany a served value. A provider
that knows a value's state records it in TeamEventEpa.provenance["epa_source_state"];
the frozen D18 provider predates the vocabulary, so its states are derived from the
value's source (its fixed snapshot is the live snapshot log's root).
"""

from __future__ import annotations

from typing import Any

CURRENT = "current"
STALE = "stale"
PENDING = "pending"
FALLBACK_STRATAI = "fallback_stratai"
UNAVAILABLE = "unavailable"
WITHHELD_NO_PRIOR_EVENT = "withheld_no_prior_event"

SERVED_STATES = frozenset({CURRENT, STALE, FALLBACK_STRATAI})
REFUSED_STATES = frozenset({PENDING, UNAVAILABLE})
ALL_STATES = SERVED_STATES | REFUSED_STATES | {WITHHELD_NO_PRIOR_EVENT}

STRATAI_FALLBACK_SOURCE = "stratai_fallback"  # ml.ratings.statbotics_primary.VALUE_SOURCE_FALLBACK


def served_state(source: str, provenance: dict[str, Any]) -> str:
    """The state of a served value: the provider's own, else derived from its source."""
    state = provenance.get("epa_source_state")
    if state is not None:
        if state not in SERVED_STATES:
            raise ValueError(f"a served EPA value cannot have state {state!r}")
        return state
    return FALLBACK_STRATAI if source == STRATAI_FALLBACK_SOURCE else CURRENT
