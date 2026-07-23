from __future__ import annotations

import pytest

from data.staging.validator import (
    PayloadValidationError,
    ValidationIssue,
    validate_event,
    validate_match,
    validate_team,
    validate_tba_event_payload,
    validate_tba_match_payload,
    validate_tba_team_payload,
)


# --- ValidationIssue / PayloadValidationError structure --------------------

def test_validation_issue_identifies_entity_field_and_reason():
    issue = ValidationIssue(entity_type="event", field="year", message="Missing required field", source_object_id="2025casj")
    assert issue.entity_type == "event"
    assert issue.field == "year"
    assert "Missing" in issue.message
    assert issue.source_object_id == "2025casj"


def test_payload_validation_error_message_contains_issue_details():
    issues = [ValidationIssue("event", "year", "Missing or non-integer required field 'year'", "2025casj")]
    error = PayloadValidationError(issues)
    assert "event.year" in str(error)
    assert "Missing or non-integer" in str(error)
    assert error.issues == issues


# --- event validation -------------------------------------------------------

def test_validate_tba_event_payload_accepts_valid_payload():
    payload = {
        "key": "2025casj", "name": "Sacramento Regional", "event_code": "casj", "year": 2025,
        "start_date": "2025-03-14", "end_date": "2025-03-16",
    }
    assert validate_tba_event_payload(payload) == []


def test_validate_tba_event_payload_rejects_missing_key():
    issues = validate_tba_event_payload({"name": "Sacramento", "year": 2025})
    assert any(issue.field == "key" for issue in issues)


def test_validate_tba_event_payload_rejects_missing_year():
    issues = validate_tba_event_payload({"key": "2025casj", "name": "Sacramento"})
    assert any(issue.field == "year" for issue in issues)


def test_validate_tba_event_payload_rejects_non_integer_year():
    issues = validate_tba_event_payload({"key": "2025casj", "name": "Sacramento", "year": "2025"})
    assert any(issue.field == "year" for issue in issues)


def test_validate_tba_event_payload_rejects_invalid_date_format():
    issues = validate_tba_event_payload({"key": "2025casj", "name": "Sacramento", "year": 2025, "start_date": "March 14"})
    assert any(issue.field == "start_date" for issue in issues)


def test_validate_tba_event_payload_rejects_non_dashed_iso_date_variants():
    # Regression: Python 3.11+'s date.fromisoformat() accepts "20250314" and
    # ISO week-date strings like "2025-W11-5", but pydantic's own date field
    # does not -- the validator must not be more permissive than the model it
    # gates, or it can report "valid" for a payload that then fails anyway.
    for malformed in ("20250314", "2025-W11-5"):
        issues = validate_tba_event_payload({"key": "2025casj", "name": "Sacramento", "year": 2025, "start_date": malformed})
        assert any(issue.field == "start_date" for issue in issues), f"{malformed!r} should have been rejected"


def test_validate_tba_event_payload_rejects_non_dict_payload():
    issues = validate_tba_event_payload(["not", "a", "dict"])
    assert len(issues) == 1
    assert issues[0].entity_type == "event"


# --- match validation ---------------------------------------------------

def test_validate_tba_match_payload_accepts_valid_payload():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj", "comp_level": "qm", "match_number": 1, "time": 1710439200,
        "alliances": {"red": {"score": 100, "teams": ["frc1114"]}, "blue": {"score": 90, "teams": ["frc254"]}},
    }
    assert validate_tba_match_payload(payload) == []


def test_validate_tba_match_payload_accepts_upcoming_match_with_no_alliances():
    assert validate_tba_match_payload({"key": "2025casj_qm5", "event_key": "2025casj"}) == []


def test_validate_tba_match_payload_rejects_missing_event_key():
    issues = validate_tba_match_payload({"key": "2025casj_qm1"})
    assert any(issue.field == "event_key" for issue in issues)


def test_validate_tba_match_payload_rejects_malformed_event_key():
    issues = validate_tba_match_payload({"key": "2025casj_qm1", "event_key": "not-a-real-key"})
    assert any(issue.field == "event_key" for issue in issues)


def test_validate_tba_match_payload_rejects_negative_timestamp():
    issues = validate_tba_match_payload({"key": "2025casj_qm1", "event_key": "2025casj", "time": -5})
    assert any(issue.field == "time" for issue in issues)


def test_validate_tba_match_payload_accepts_offseason_b_team_key():
    # Regression: TBA's real "B team" convention for offseason second robots
    # (e.g. "frc254b") was previously rejected as malformed.
    payload = {
        "key": "2025off_qm1", "event_key": "2025off",
        "alliances": {"red": {"teams": ["frc254", "frc254b"]}, "blue": {"teams": []}},
    }
    assert validate_tba_match_payload(payload) == []


def test_validate_tba_team_payload_accepts_offseason_b_team_key():
    assert validate_tba_team_payload({"key": "frc254b", "team_number": 254}) == []


def test_validate_tba_match_payload_rejects_invalid_winning_alliance_value():
    payload = {"key": "2025casj_qm1", "event_key": "2025casj", "winning_alliance": 12345}
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "winning_alliance" for issue in issues)


def test_validate_tba_match_payload_rejects_duplicate_team_in_same_alliance():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {"red": {"teams": ["frc1114", "frc1114", "frc604"]}, "blue": {"teams": []}},
    }
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "alliances.red.teams" for issue in issues)


def test_validate_tba_match_payload_rejects_team_on_both_alliances():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {"red": {"teams": ["frc1114"]}, "blue": {"teams": ["frc1114"]}},
    }
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "alliances" for issue in issues)


def test_validate_tba_match_payload_rejects_match_key_not_matching_event_key():
    # A match attributed to an event it doesn't actually belong to -- a real
    # data-integrity failure mode, not just a formatting nitpick.
    payload = {"key": "2025casj_qm1", "event_key": "2025txhou"}
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "event_key" for issue in issues)


def test_validate_tba_match_payload_rejects_malformed_team_key():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {"red": {"teams": ["1114"]}, "blue": {"teams": []}},  # missing "frc" prefix
    }
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "alliances.red.teams" for issue in issues)


def test_validate_tba_match_payload_rejects_non_integer_score():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {"red": {"score": "high", "teams": []}, "blue": {"teams": []}},
    }
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "alliances.red.score" for issue in issues)


# --- team validation ------------------------------------------------------

def test_validate_tba_team_payload_accepts_valid_payload():
    payload = {"key": "frc1114", "team_number": 1114, "nickname": "Simbotics", "rookie_year": 2003}
    assert validate_tba_team_payload(payload) == []


def test_validate_tba_team_payload_rejects_missing_team_number():
    issues = validate_tba_team_payload({"key": "frc1114"})
    assert any(issue.field == "team_number" for issue in issues)


def test_validate_tba_team_payload_rejects_malformed_key():
    issues = validate_tba_team_payload({"key": "1114", "team_number": 1114})
    assert any(issue.field == "key" for issue in issues)


def test_validate_tba_team_payload_rejects_non_integer_rookie_year():
    issues = validate_tba_team_payload({"key": "frc1114", "team_number": 1114, "rookie_year": "2003"})
    assert any(issue.field == "rookie_year" for issue in issues)


# --- source dispatch -------------------------------------------------------

def test_validate_event_dispatches_to_tba_validator():
    assert validate_event("tba", {"key": "2025casj", "name": "Sacramento", "year": 2025}) == []


def test_validate_event_unknown_source_raises():
    with pytest.raises(ValueError, match="No event validator registered for source 'scoutradioz'"):
        validate_event("scoutradioz", {})


def test_validate_match_unknown_source_raises():
    with pytest.raises(ValueError, match="No match validator registered"):
        validate_match("scoutradioz", {})


def test_validate_team_unknown_source_raises():
    with pytest.raises(ValueError, match="No team validator registered"):
        validate_team("scoutradioz", {})
