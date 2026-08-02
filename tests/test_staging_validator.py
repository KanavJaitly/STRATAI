from __future__ import annotations

import pytest

from data.staging.validator import (
    TBA_UNASSIGNED_TEAM_KEY,
    PayloadValidationError,
    ValidationIssue,
    is_unassigned_team_key,
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


# --- TBA's frc0 unassigned-roster placeholder ------------------------------
#
# TBA publishes a roster that has not been assigned yet as ["frc0","frc0","frc0"]
# on both alliances (real: 2024mdsev_qm73/_qm74). To the two rules above that is
# indistinguishable from the same team entered three times and then again on the
# opposing alliance, so those matches were rejected outright and their payloads
# pinned the event's watermark forever. frc0 is a placeholder, not a team.
#
# The rules themselves must not weaken: these tests exist as much to pin what
# still gets rejected as to pin what now passes.

def test_is_unassigned_team_key_matches_only_the_placeholder():
    assert is_unassigned_team_key(TBA_UNASSIGNED_TEAM_KEY)
    assert is_unassigned_team_key("frc0")
    # A real team, a differently-spelled zero, and non-strings are all not it.
    assert not is_unassigned_team_key("frc1114")
    assert not is_unassigned_team_key("frc00")
    assert not is_unassigned_team_key("frc0b")
    assert not is_unassigned_team_key(0)
    assert not is_unassigned_team_key(None)


def test_validate_tba_match_payload_accepts_an_unassigned_roster_on_both_alliances():
    # The exact shape of the real 2024mdsev_qm73 payload.
    payload = {
        "key": "2024mdsev_qm73", "event_key": "2024mdsev",
        "alliances": {
            "red": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
            "blue": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
        },
        "winning_alliance": "",
    }
    assert validate_tba_match_payload(payload) == []


def test_validate_tba_match_payload_still_rejects_a_real_duplicate_beside_the_placeholder():
    # The placeholder is excluded from the identity comparison; the real team
    # entered twice is still corruption and must still be caught.
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {"red": {"teams": ["frc1114", "frc1114", "frc0"]}, "blue": {"teams": []}},
    }
    issues = validate_tba_match_payload(payload)
    assert any(issue.field == "alliances.red.teams" for issue in issues)
    # Reported against the real team, without the placeholder muddying it.
    assert "frc0" not in issues[0].message


def test_validate_tba_match_payload_still_rejects_a_real_team_on_both_alliances_beside_the_placeholder():
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {
            "red": {"teams": ["frc1114", "frc0", "frc0"]},
            "blue": {"teams": ["frc1114", "frc0", "frc0"]},
        },
    }
    issues = validate_tba_match_payload(payload)
    overlap = [issue for issue in issues if issue.field == "alliances"]
    assert len(overlap) == 1
    # frc0 on both alliances is not an overlap; frc1114 on both alliances is.
    assert "frc1114" in overlap[0].message
    assert "frc0" not in overlap[0].message


def test_validate_tba_match_payload_accepts_a_partially_assigned_roster():
    # Structurally fine -- an under-filled alliance is a plausibility question,
    # which the quality layer answers with a warning, not a rejection.
    payload = {
        "key": "2025casj_qm1", "event_key": "2025casj",
        "alliances": {
            "red": {"teams": ["frc1114", "frc0", "frc0"]},
            "blue": {"teams": ["frc254", "frc604", "frc973"]},
        },
    }
    assert validate_tba_match_payload(payload) == []


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
