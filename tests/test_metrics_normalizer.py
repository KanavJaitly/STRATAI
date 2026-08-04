"""Phase 3 Milestone 6: scouting observation normalization.

Mirrors tests/test_normalizer.py's style for the equivalent TBA normalizers:
valid-payload field checks, required-field/malformed-payload rejection,
determinism, non-mutation, and a dedicated "safety net" test proving a field
the hand-written validator doesn't fully check (submitted_at's exact date
format) still cannot reach ScoutingObservation's constructor as a raw
pydantic error.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from data.metrics.normalizer import (
    normalize_human_scout_observation,
    normalize_scouting_observation,
    scouting_observation_natural_key,
)
from data.metrics.schemas import ScoutingObservation
from data.metrics.validator import PayloadValidationError

VALID_PAYLOAD = {
    "match_key": "2026casj_qm1",
    "event_key": "2026casj",
    "team_number": 1114,
    "scout_identifier": "alice",
    "defense_rating": 3,
    "feeding_rating": 4,
    "notes": "Played strong defense in the endgame.",
    "submitted_at": "2026-08-04T18:30:00Z",
}


# --- valid payloads normalize correctly -------------------------------------

def test_valid_payload_normalizes_correctly():
    obs = normalize_human_scout_observation(VALID_PAYLOAD)
    assert isinstance(obs, ScoutingObservation)
    assert obs.match_key == "2026casj_qm1"
    assert obs.event_key == "2026casj"
    assert obs.team_number == 1114
    assert obs.scout_identifier == "alice"
    assert obs.defense_rating == 3
    assert obs.feeding_rating == 4
    assert obs.notes == "Played strong defense in the endgame."
    assert obs.source == "human_scout"
    assert obs.submitted_at.year == 2026
    assert obs.submitted_at.month == 8
    assert obs.submitted_at.day == 4


def test_defense_rating_only_normalizes_correctly():
    payload = dict(VALID_PAYLOAD, feeding_rating=None)
    obs = normalize_human_scout_observation(payload)
    assert obs.defense_rating == 3
    assert obs.feeding_rating is None


def test_feeding_rating_only_normalizes_correctly():
    payload = dict(VALID_PAYLOAD, defense_rating=None)
    obs = normalize_human_scout_observation(payload)
    assert obs.feeding_rating == 4
    assert obs.defense_rating is None


def test_missing_notes_normalizes_to_none():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "notes"}
    obs = normalize_human_scout_observation(payload)
    assert obs.notes is None


def test_source_is_always_human_scout_regardless_of_payload_content():
    # source is not read from the payload at all (it is the dispatch/registry
    # key, hardcoded by this specific normalizer) -- an extraneous "source" key
    # in the payload must be ignored, not accidentally override it.
    payload = dict(VALID_PAYLOAD, source="not_a_real_source")
    obs = normalize_human_scout_observation(payload)
    assert obs.source == "human_scout"


# --- required fields / invalid payload rejection ----------------------------

def test_missing_required_field_raises():
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_human_scout_observation({"match_key": "2026casj_qm1"})
    fields = {issue.field for issue in exc_info.value.issues}
    assert "event_key" in fields
    assert "team_number" in fields
    assert "scout_identifier" in fields
    assert "submitted_at" in fields
    assert "ratings" in fields


def test_malformed_payload_type_raises():
    with pytest.raises(PayloadValidationError):
        normalize_human_scout_observation("not a dict")


def test_event_key_match_key_mismatch_raises():
    payload = dict(VALID_PAYLOAD, event_key="2026different")
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_human_scout_observation(payload)
    assert any(issue.field == "event_key" for issue in exc_info.value.issues)


def test_rating_out_of_range_raises():
    payload = dict(VALID_PAYLOAD, defense_rating=9)
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_human_scout_observation(payload)
    assert any(issue.field == "defense_rating" for issue in exc_info.value.issues)


def test_neither_rating_present_raises():
    payload = dict(VALID_PAYLOAD, defense_rating=None, feeding_rating=None)
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_human_scout_observation(payload)
    assert any(issue.field == "ratings" for issue in exc_info.value.issues)


# --- the _build_or_raise safety net -----------------------------------------

def test_malformed_submitted_at_format_wraps_as_payload_validation_error():
    # Regression-shaped like test_normalize_tba_event_wraps_pydantic_errors_
    # as_payload_validation_error: Milestone 5's validator only checks
    # submitted_at is a non-empty string (not that it's a real, parseable
    # date), so a garbage string reaches ScoutingObservation's constructor
    # unguarded by the hand-written validator. _build_or_raise must still turn
    # pydantic's rejection into a structured PayloadValidationError, not let a
    # raw pydantic.ValidationError leak out.
    payload = dict(VALID_PAYLOAD, submitted_at="not-a-real-date")
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_human_scout_observation(payload)
    assert any(issue.field == "submitted_at" for issue in exc_info.value.issues)
    # And confirm it is genuinely a pydantic-driven rejection, not something
    # the hand-written validator already caught structurally.
    with pytest.raises(PydanticValidationError):
        ScoutingObservation(**{**payload, "source": "human_scout"})


# --- deterministic normalization --------------------------------------------

def test_normalization_is_deterministic():
    first = normalize_human_scout_observation(VALID_PAYLOAD)
    second = normalize_human_scout_observation(VALID_PAYLOAD)
    assert first == second


def test_normalization_does_not_mutate_input_payload():
    payload_copy = dict(VALID_PAYLOAD)
    normalize_human_scout_observation(VALID_PAYLOAD)
    assert VALID_PAYLOAD == payload_copy


# --- natural key -------------------------------------------------------

def test_natural_key_matches_expected_format():
    obs = normalize_human_scout_observation(VALID_PAYLOAD)
    assert scouting_observation_natural_key(obs) == "2026casj_qm1:1114:alice:human_scout"


def test_natural_key_is_deterministic():
    first = normalize_human_scout_observation(VALID_PAYLOAD)
    second = normalize_human_scout_observation(VALID_PAYLOAD)
    assert scouting_observation_natural_key(first) == scouting_observation_natural_key(second)


def test_natural_key_differs_for_different_scouts_on_same_match_and_team():
    obs_a = normalize_human_scout_observation(dict(VALID_PAYLOAD, scout_identifier="alice"))
    obs_b = normalize_human_scout_observation(dict(VALID_PAYLOAD, scout_identifier="bob"))
    assert scouting_observation_natural_key(obs_a) != scouting_observation_natural_key(obs_b)


def test_natural_key_does_not_collide_across_the_scout_identifier_source_boundary():
    # The human_scout normalizer always hardcodes source="human_scout", so it
    # cannot exercise this case -- construct ScoutingObservation directly.
    # Underscore-joining would collide here: scout_identifier="b_2"+source="c"
    # and scout_identifier="b"+source="2_c" both underscore-join to the
    # identical "..._b_2_c". Colon-joining keeps them distinct.
    common = dict(
        match_key="2026casj_qm1", event_key="2026casj", team_number=1114,
        defense_rating=3, submitted_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    obs_a = ScoutingObservation(**common, scout_identifier="b_2", source="c")
    obs_b = ScoutingObservation(**common, scout_identifier="b", source="2_c")
    key_a = scouting_observation_natural_key(obs_a)
    key_b = scouting_observation_natural_key(obs_b)
    assert key_a != key_b
    # And confirm underscore-joining really would have collided, so this test
    # is pinning a real fix, not a hypothetical one.
    underscore_joined_a = f"{obs_a.match_key}_{obs_a.team_number}_{obs_a.scout_identifier}_{obs_a.source}"
    underscore_joined_b = f"{obs_b.match_key}_{obs_b.team_number}_{obs_b.scout_identifier}_{obs_b.source}"
    assert underscore_joined_a == underscore_joined_b


# --- source dispatch / extensibility ----------------------------------------

def test_normalize_scouting_observation_dispatches_to_human_scout_normalizer():
    obs = normalize_scouting_observation("human_scout", VALID_PAYLOAD)
    assert obs == normalize_human_scout_observation(VALID_PAYLOAD)


def test_normalize_scouting_observation_unknown_source_raises_clear_error():
    with pytest.raises(ValueError, match="No scouting_observation normalizer registered for source 'scoutradioz'"):
        normalize_scouting_observation("scoutradioz", VALID_PAYLOAD)


def test_normalize_scouting_observation_completely_unknown_source_raises_clear_error():
    with pytest.raises(ValueError):
        normalize_scouting_observation("carrier_pigeon", VALID_PAYLOAD)
