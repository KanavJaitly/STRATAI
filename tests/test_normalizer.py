from __future__ import annotations

import pytest

from data.staging.normalizer import (
    normalize_event,
    normalize_match,
    normalize_team,
    normalize_tba_event,
    normalize_tba_match,
    normalize_tba_team,
)
from data.staging.schemas import StagingEvent, StagingMatch, StagingTeam
from data.staging.validator import PayloadValidationError

VALID_EVENT_PAYLOAD = {
    "key": "2025casj", "name": "Sacramento Regional", "event_code": "casj", "year": 2025,
    "start_date": "2025-03-14", "end_date": "2025-03-16",
    "city": "Sacramento", "state_prov": "CA", "country": "USA",
}

VALID_MATCH_PAYLOAD = {
    "key": "2025casj_qm1", "event_key": "2025casj", "comp_level": "qm", "match_number": 1, "set_number": 1,
    "time": 1710439200,
    "alliances": {
        "red": {"score": 112, "teams": ["frc1114", "frc254", "frc604"]},
        "blue": {"score": 98, "teams": ["frc118", "frc330", "frc973"]},
    },
    "winning_alliance": "red",
}

VALID_TEAM_PAYLOAD = {
    "key": "frc1114", "team_number": 1114, "nickname": "Simbotics", "name": "Queen's University / Simbotics",
    "city": "St. Catharines", "state_prov": "ON", "country": "Canada", "rookie_year": 2003,
}


# --- valid payloads normalize correctly -------------------------------------

def test_valid_tba_event_payload_normalizes_correctly():
    event = normalize_tba_event(VALID_EVENT_PAYLOAD)
    assert isinstance(event, StagingEvent)
    assert event.event_key == "2025casj"
    assert event.name == "Sacramento Regional"
    assert event.season == 2025
    assert event.event_code == "casj"
    assert str(event.start_date) == "2025-03-14"
    assert str(event.end_date) == "2025-03-16"
    assert event.state_province == "CA"


def test_valid_tba_match_payload_normalizes_correctly():
    match = normalize_tba_match(VALID_MATCH_PAYLOAD)
    assert isinstance(match, StagingMatch)
    assert match.match_key == "2025casj_qm1"
    assert match.event_key == "2025casj"
    assert match.season == 2025
    assert match.competition_level == "qualification"
    assert match.red_teams == [1114, 254, 604]
    assert match.blue_teams == [118, 330, 973]
    assert match.red_score == 112
    assert match.blue_score == 98
    assert match.winning_alliance == "red"
    assert match.scheduled_time is not None


def test_valid_tba_team_payload_normalizes_correctly():
    team = normalize_tba_team(VALID_TEAM_PAYLOAD)
    assert isinstance(team, StagingTeam)
    assert team.team_number == 1114
    assert team.name == "Simbotics"  # nickname preferred over the long legal name
    assert team.state_province == "ON"
    assert team.country == "Canada"
    assert team.rookie_year == 2003


# --- required fields / invalid payload rejection ----------------------------

def test_normalize_tba_event_missing_required_field_raises():
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_event({"key": "2025casj"})
    assert any(issue.field == "name" for issue in exc_info.value.issues)
    assert any(issue.field == "year" for issue in exc_info.value.issues)


def test_normalize_tba_match_missing_required_field_raises():
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_match({"key": "2025casj_qm1"})
    assert any(issue.field == "event_key" for issue in exc_info.value.issues)


def test_normalize_tba_team_missing_required_field_raises():
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_team({"key": "frc1114"})
    assert any(issue.field == "team_number" for issue in exc_info.value.issues)


def test_normalize_tba_event_malformed_payload_type_raises():
    with pytest.raises(PayloadValidationError):
        normalize_tba_event("not a dict")


def test_normalize_tba_match_malformed_team_key_raises():
    payload = dict(VALID_MATCH_PAYLOAD, alliances={"red": {"teams": ["1114"]}, "blue": {"teams": []}})
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_match(payload)
    assert any("teams" in issue.field for issue in exc_info.value.issues)


# --- deterministic normalization --------------------------------------------

def test_normalization_is_deterministic():
    first = normalize_tba_match(VALID_MATCH_PAYLOAD)
    second = normalize_tba_match(VALID_MATCH_PAYLOAD)
    assert first == second


def test_normalization_does_not_mutate_input_payload():
    payload_copy = dict(VALID_MATCH_PAYLOAD)
    normalize_tba_match(VALID_MATCH_PAYLOAD)
    assert VALID_MATCH_PAYLOAD == payload_copy


# --- canonical field names (not TBA's raw naming) ---------------------------

def test_staging_match_uses_canonical_field_names_not_tba_names():
    field_names = set(StagingMatch.model_fields.keys())
    # Canonical vocabulary must be present...
    assert {"competition_level", "red_teams", "blue_teams", "red_score", "blue_score"}.issubset(field_names)
    # ...and TBA's raw naming must not have leaked into the canonical model.
    assert "comp_level" not in field_names
    assert "alliances" not in field_names
    assert "teams" not in field_names


def test_staging_team_uses_canonical_field_names_not_tba_names():
    field_names = set(StagingTeam.model_fields.keys())
    assert "name" in field_names
    assert "nickname" not in field_names  # StratAI's canonical field is just "name"


# --- source-specific normalization behavior ---------------------------------

def test_normalize_tba_match_maps_known_competition_levels():
    for raw, canonical in [("qm", "qualification"), ("qf", "quarterfinal"), ("sf", "semifinal"), ("f", "final")]:
        payload = dict(VALID_MATCH_PAYLOAD, comp_level=raw)
        assert normalize_tba_match(payload).competition_level == canonical


def test_normalize_tba_match_falls_back_gracefully_for_unrecognized_competition_level():
    payload = dict(VALID_MATCH_PAYLOAD, comp_level="exhibition")
    match = normalize_tba_match(payload)
    assert match.competition_level == "exhibition"  # preserved, not rejected


def test_normalize_tba_match_distinguishes_tie_from_not_yet_played():
    upcoming = {"key": "2025casj_qm5", "event_key": "2025casj"}
    assert normalize_tba_match(upcoming).winning_alliance is None

    tie_payload = dict(
        VALID_MATCH_PAYLOAD,
        alliances={"red": {"score": 100, "teams": ["frc1114"]}, "blue": {"score": 100, "teams": ["frc254"]}},
        winning_alliance="",
    )
    assert normalize_tba_match(tie_payload).winning_alliance == "tie"


# --- TBA's -1 unplayed-match sentinel ---------------------------------------
#
# TBA publishes a scheduled-but-unplayed match with score -1 on both alliances.
# Read verbatim, the two -1s compare equal and the match is recorded as a *tie
# that never happened*. Every not-yet-played match in a live event's schedule
# carries this, so these are the tests standing between the pipeline and a
# schedule's worth of fabricated ties.

def test_unplayed_match_normalizes_to_null_scores_and_no_winner():
    unplayed = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": -1, "team_keys": ["frc1114", "frc254", "frc604"]},
            "blue": {"score": -1, "team_keys": ["frc118", "frc330", "frc973"]},
        },
        winning_alliance="",
    )
    match = normalize_tba_match(unplayed)

    assert match.red_score is None
    assert match.blue_score is None
    # The whole point: NOT "tie". Two sentinels are equal to each other, which
    # is exactly why comparing them without resolving them first is unsafe.
    assert match.winning_alliance is None
    # Still a real, loadable record -- the schedule and roster are known.
    assert match.red_teams == [1114, 254, 604]
    assert match.blue_teams == [118, 330, 973]
    assert match.scheduled_time is not None


def test_half_sentinel_match_nulls_both_scores():
    # A match cannot be half-played. Storing NULL/30 would be uninterpretable
    # downstream, so the whole match is read as unplayed; the quality layer
    # records the anomaly as a warning rather than losing it silently.
    half = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": -1, "teams": ["frc1114"]},
            "blue": {"score": 30, "teams": ["frc254"]},
        },
        winning_alliance="",
    )
    match = normalize_tba_match(half)

    assert match.red_score is None
    assert match.blue_score is None
    assert match.winning_alliance is None


def test_genuine_scores_are_untouched_by_sentinel_handling():
    played = normalize_tba_match(VALID_MATCH_PAYLOAD)
    assert (played.red_score, played.blue_score, played.winning_alliance) == (112, 98, "red")

    # 0-0 is a real, legitimate result (both alliances no-showed or were DQ'd),
    # and must not be confused with "no result yet".
    scoreless = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": 0, "teams": ["frc1114"]},
            "blue": {"score": 0, "teams": ["frc254"]},
        },
        winning_alliance="",
    )
    match = normalize_tba_match(scoreless)
    assert (match.red_score, match.blue_score) == (0, 0)
    assert match.winning_alliance == "tie"  # a genuine 0-0 tie, unlike -1/-1


def test_a_missing_score_is_not_treated_as_the_unplayed_sentinel():
    # Distinct condition from -1, deliberately left as it was: an absent score
    # does not cause the other alliance's real score to be discarded.
    partial = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": 45, "teams": ["frc1114"]},
            "blue": {"teams": ["frc254"]},
        },
        winning_alliance="",
    )
    match = normalize_tba_match(partial)
    assert match.red_score == 45
    assert match.blue_score is None
    assert match.winning_alliance is None


# --- TBA's frc0 unassigned-roster placeholder ------------------------------
#
# The sibling of the -1 sentinel above, and the same principle applied to a
# different field: the raw payload's marker for "this is absent" becomes an
# actual absence at the point the payload is interpreted. -1 score -> NULL
# score; frc0 roster -> empty roster. What differs is where each was being
# caught -- -1 reached the quality layer, frc0 never got past structural
# validation.

def test_unassigned_roster_normalizes_to_an_empty_roster():
    # The exact shape of the real 2024mdsev_qm73 payload, which carries both
    # sentinels at once: unassigned rosters and unplayed scores.
    unassigned = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
            "blue": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
        },
        winning_alliance="",
    )
    match = normalize_tba_match(unassigned)

    # Empty, NOT [0, 0, 0]: team 0 does not exist, so a roster naming it would
    # both assert that some robot played and fail the match_teams foreign key.
    assert match.red_teams == []
    assert match.blue_teams == []
    # And the match itself still loads, as unplayed rather than as a tie.
    assert (match.red_score, match.blue_score, match.winning_alliance) == (None, None, None)
    assert match.match_key == VALID_MATCH_PAYLOAD["key"]
    assert match.season == 2025


def test_a_partially_assigned_roster_keeps_its_real_teams():
    # Not special-cased: the placeholders drop out and a short alliance is left,
    # which the quality layer flags as an implausible size (a warning -- the
    # match is still loadable and its scores still meaningful).
    partial = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": 80, "team_keys": ["frc1114", "frc0", "frc0"]},
            "blue": {"score": 70, "team_keys": ["frc254", "frc604", "frc973"]},
        },
        winning_alliance="red",
    )
    match = normalize_tba_match(partial)

    assert match.red_teams == [1114]
    assert match.blue_teams == [254, 604, 973]
    assert (match.red_score, match.blue_score, match.winning_alliance) == (80, 70, "red")


def test_a_real_roster_is_untouched_by_placeholder_handling():
    # The guard against over-reaching: nothing about an ordinary roster changes.
    match = normalize_tba_match(dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": 100, "team_keys": ["frc1114", "frc254", "frc604"]},
            "blue": {"score": 90, "team_keys": ["frc118", "frc330", "frc973"]},
        },
    ))
    assert match.red_teams == [1114, 254, 604]
    assert match.blue_teams == [118, 330, 973]


def test_normalize_tba_match_strips_team_key_prefix_and_derives_season():
    match = normalize_tba_match(VALID_MATCH_PAYLOAD)
    assert all(isinstance(t, int) for t in match.red_teams + match.blue_teams)
    assert match.season == 2025  # derived from the "2025casj" event_key prefix


def test_normalize_tba_team_prefers_nickname_over_legal_name():
    payload = dict(VALID_TEAM_PAYLOAD, nickname=None, name="Fallback Legal Name")
    assert normalize_tba_team(payload).name == "Fallback Legal Name"


# --- regressions found during the adversarial acceptance review ------------

def test_normalize_tba_match_collapses_offseason_b_team_to_parent_team_number():
    # Regression: "frc254b" (TBA's real offseason second-robot convention)
    # previously crashed parse_tba_team_number with a raw ValueError. It's
    # deliberately collapsed to the parent team's number (254), not rejected
    # and not given a separate identity.
    payload = dict(
        VALID_MATCH_PAYLOAD,
        alliances={
            "red": {"score": 100, "teams": ["frc254", "frc254b"]},
            "blue": {"score": 90, "teams": ["frc118"]},
        },
    )
    match = normalize_tba_match(payload)
    assert match.red_teams == [254, 254]  # both keys collapse to the same team_number


def test_normalize_tba_match_treats_epoch_zero_timestamp_as_unset():
    # Regression: a raw "time": 0 previously produced scheduled_time =
    # 1970-01-01 instead of None -- FRC didn't exist in 1970.
    payload = dict(VALID_MATCH_PAYLOAD, time=0)
    assert normalize_tba_match(payload).scheduled_time is None


def test_normalize_tba_event_wraps_pydantic_errors_as_payload_validation_error():
    # Regression: a field the hand-written validator doesn't explicitly check
    # (event_code) previously reached StagingEvent's constructor unguarded and
    # raised a raw pydantic.ValidationError instead of PayloadValidationError.
    payload = dict(VALID_EVENT_PAYLOAD, event_code=999)
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_event(payload)
    assert any(issue.field == "event_code" for issue in exc_info.value.issues)


def test_normalize_tba_team_wraps_pydantic_errors_as_payload_validation_error():
    payload = dict(VALID_TEAM_PAYLOAD, city=12345)
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_team(payload)
    assert any(issue.field == "city" for issue in exc_info.value.issues)


def test_normalize_tba_match_rejects_team_on_both_alliances():
    payload = dict(
        VALID_MATCH_PAYLOAD,
        alliances={"red": {"teams": ["frc1114"]}, "blue": {"teams": ["frc1114"]}},
    )
    with pytest.raises(PayloadValidationError) as exc_info:
        normalize_tba_match(payload)
    assert any(issue.field == "alliances" for issue in exc_info.value.issues)


# --- source dispatch / extensibility ----------------------------------------

def test_normalize_event_dispatches_to_tba_normalizer():
    event = normalize_event("tba", VALID_EVENT_PAYLOAD)
    assert event == normalize_tba_event(VALID_EVENT_PAYLOAD)


def test_normalize_match_unknown_source_raises_clear_error():
    with pytest.raises(ValueError, match="No match normalizer registered for source 'scoutradioz'"):
        normalize_match("scoutradioz", {})


def test_normalize_team_unknown_source_raises_clear_error():
    with pytest.raises(ValueError, match="No team normalizer registered for source 'scoutradioz'"):
        normalize_team("scoutradioz", {})
