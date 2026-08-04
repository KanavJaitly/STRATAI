"""Phase 3 Milestone 5: raw human-scout observation payload validation.

Mirrors tests/test_staging_validator.py's style for the equivalent TBA/Statbotics
validators: `assert validate_x(payload) == []` for a valid payload, `assert
any(issue.field == "..." for issue in issues)` for each rejection. This module
does not re-test ValidationIssue/PayloadValidationError's own basic structure --
that is already covered by test_staging_validator.py, and data.metrics.validator
reuses those classes directly rather than redefining them (asserted below).
"""

from __future__ import annotations

import data.staging.validator as staging_validator
from data.metrics.validator import (
    PayloadValidationError,
    ValidationIssue,
    validate_human_scout_observation_payload,
    validate_scouting_observation,
)

import pytest


def _valid_payload(**overrides) -> dict:
    payload = {
        "match_key": "2026casj_qm1",
        "event_key": "2026casj",
        "team_number": 1114,
        "scout_identifier": "alice",
        "defense_rating": 3,
        "feeding_rating": 4,
        "notes": "Played strong defense in the endgame.",
        "submitted_at": "2026-08-04T18:30:00Z",
    }
    payload.update(overrides)
    return payload


# --- reuse, not redefinition -------------------------------------------------

def test_reuses_staging_validation_issue_and_error_classes_as_is():
    # Milestone 5's brief is explicit: reuse ValidationIssue/PayloadValidationError
    # as-is. Identity (not just equal shape) proves this module imports rather
    # than parallels them.
    assert ValidationIssue is staging_validator.ValidationIssue
    assert PayloadValidationError is staging_validator.PayloadValidationError


# --- valid payloads -----------------------------------------------------

def test_validate_human_scout_observation_payload_accepts_valid_payload():
    assert validate_human_scout_observation_payload(_valid_payload()) == []


def test_accepts_defense_rating_only():
    payload = _valid_payload(feeding_rating=None)
    assert validate_human_scout_observation_payload(payload) == []


def test_accepts_feeding_rating_only():
    payload = _valid_payload(defense_rating=None)
    assert validate_human_scout_observation_payload(payload) == []


def test_accepts_boundary_rating_values():
    # 0 and 5 are both real, meaningful ratings (per MIN_RATING/MAX_RATING),
    # not sentinel/missing-data values -- must not be rejected as "falsy".
    assert validate_human_scout_observation_payload(_valid_payload(defense_rating=0, feeding_rating=5)) == []


def test_accepts_payload_with_no_notes():
    payload = _valid_payload()
    del payload["notes"]
    assert validate_human_scout_observation_payload(payload) == []


def test_extra_unknown_fields_are_ignored():
    payload = _valid_payload(source="human_scout", something_unexpected=True)
    assert validate_human_scout_observation_payload(payload) == []


# --- non-dict payload -----------------------------------------------------

def test_rejects_non_dict_payload():
    issues = validate_human_scout_observation_payload(["not", "a", "dict"])
    assert len(issues) == 1
    assert issues[0].entity_type == "scouting_observation"
    assert issues[0].field == "<payload>"


# --- required fields, individually missing ----------------------------------

def test_rejects_missing_match_key():
    payload = _valid_payload()
    del payload["match_key"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "match_key" for issue in issues)


def test_rejects_missing_event_key():
    payload = _valid_payload()
    del payload["event_key"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "event_key" for issue in issues)


def test_rejects_missing_submitted_at():
    payload = _valid_payload()
    del payload["submitted_at"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "submitted_at" for issue in issues)


def test_rejects_missing_team_number():
    payload = _valid_payload()
    del payload["team_number"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "team_number" for issue in issues)


def test_rejects_missing_scout_identifier():
    payload = _valid_payload()
    del payload["scout_identifier"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "scout_identifier" for issue in issues)


def test_rejects_missing_both_ratings():
    payload = _valid_payload(defense_rating=None, feeding_rating=None)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "ratings" for issue in issues)


def test_rejects_payload_with_neither_rating_key_present_at_all():
    payload = _valid_payload()
    del payload["defense_rating"]
    del payload["feeding_rating"]
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "ratings" for issue in issues)


# --- malformed match_key -----------------------------------------------

@pytest.mark.parametrize("malformed", ["", None, 12345, ["2026casj_qm1"]])
def test_rejects_malformed_match_key(malformed):
    payload = _valid_payload(match_key=malformed)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "match_key" for issue in issues)


# --- malformed event_key / event_key-match_key consistency -----------------

@pytest.mark.parametrize("malformed", ["", None, 12345, ["2026casj"]])
def test_rejects_malformed_event_key(malformed):
    payload = _valid_payload(event_key=malformed)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "event_key" for issue in issues)


def test_rejects_event_key_that_match_key_does_not_belong_to():
    # match_key "2026casj_qm1" belongs to event "2026casj", not "2026different"
    # -- mirrors validate_tba_match_payload's identical consistency check.
    payload = _valid_payload(match_key="2026casj_qm1", event_key="2026different")
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "event_key" for issue in issues)


def test_does_not_double_report_when_match_key_itself_is_already_malformed():
    # A malformed match_key must not also trigger a confusing "doesn't belong
    # to event_key" issue on top of the match_key rejection itself.
    payload = _valid_payload(match_key="", event_key="2026casj")
    issues = validate_human_scout_observation_payload(payload)
    event_key_issues = [issue for issue in issues if issue.field == "event_key"]
    assert event_key_issues == []


# --- malformed submitted_at -------------------------------------------------

@pytest.mark.parametrize("malformed", ["", None, 12345, ["2026-08-04T18:30:00Z"]])
def test_rejects_malformed_submitted_at(malformed):
    payload = _valid_payload(submitted_at=malformed)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "submitted_at" for issue in issues)


# --- malformed team_number ------------------------------------------------

@pytest.mark.parametrize("malformed", [0, -5, "1114", 11.5, True, False])
def test_rejects_malformed_team_number(malformed):
    payload = _valid_payload(team_number=malformed)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "team_number" for issue in issues)


# --- malformed scout_identifier -------------------------------------------

@pytest.mark.parametrize("malformed", ["", None, 42])
def test_rejects_malformed_scout_identifier(malformed):
    payload = _valid_payload(scout_identifier=malformed)
    issues = validate_human_scout_observation_payload(payload)
    assert any(issue.field == "scout_identifier" for issue in issues)


# --- each rating out of range ---------------------------------------------

@pytest.mark.parametrize("bad_value", [-1, 6, 100, "3", 2.5, True, False])
def test_rejects_defense_rating_out_of_range(bad_value):
    issues = validate_human_scout_observation_payload(_valid_payload(defense_rating=bad_value))
    assert any(issue.field == "defense_rating" for issue in issues)


@pytest.mark.parametrize("bad_value", [-1, 6, 100, "3", 2.5, True, False])
def test_rejects_feeding_rating_out_of_range(bad_value):
    issues = validate_human_scout_observation_payload(_valid_payload(feeding_rating=bad_value))
    assert any(issue.field == "feeding_rating" for issue in issues)


def test_rejects_integral_valued_float_rating():
    # 3.0 is not 3 -- float and int are distinct types even when the float
    # carries no fractional part, matching the same strictness the TBA
    # validator already applies to its own integer fields (e.g. match_number).
    issues = validate_human_scout_observation_payload(_valid_payload(defense_rating=3.0))
    assert any(issue.field == "defense_rating" for issue in issues)


# --- notes type check -----------------------------------------------------

def test_rejects_non_string_notes():
    issues = validate_human_scout_observation_payload(_valid_payload(notes=12345))
    assert any(issue.field == "notes" for issue in issues)


def test_accepts_null_notes():
    assert validate_human_scout_observation_payload(_valid_payload(notes=None)) == []


# --- source dispatch -------------------------------------------------------

def test_validate_scouting_observation_dispatches_to_human_scout_validator():
    assert validate_scouting_observation("human_scout", _valid_payload()) == []
    issues = validate_scouting_observation("human_scout", _valid_payload(team_number=-1))
    assert any(issue.field == "team_number" for issue in issues)


def test_validate_scouting_observation_unknown_source_raises_value_error():
    with pytest.raises(ValueError, match="scoutradioz"):
        validate_scouting_observation("scoutradioz", _valid_payload())


def test_validate_scouting_observation_completely_unknown_source_raises_value_error():
    with pytest.raises(ValueError):
        validate_scouting_observation("carrier_pigeon", _valid_payload())
