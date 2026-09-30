"""The EPA reader: raw TBA payload -> engine inputs, cross-checks, and read-only DB access."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import psycopg
import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.ratings.epa.inputs import season_input_fingerprint
from ml.ratings.reader import (
    CANONICAL_ROSTER_MISMATCH,
    CANONICAL_SCORE_MISMATCH,
    CANONICAL_TIME_MISMATCH,
    DUPLICATE_CURRENT_PAYLOAD,
    PLACEHOLDER_TEAM_KEY,
    RAW_EVENT_INVALID,
    RAW_EVENT_MISSING,
    RAW_MATCH_EVENT_MISMATCH,
    RAW_MATCH_INVALID,
    RAW_MATCH_MISSING,
    UNPARSEABLE_TEAM_KEY,
    CanonicalMatch,
    ReaderIssue,
    assemble_season_input,
    event_input_from_payload,
    match_input_from_payload,
    read_season_input,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tba_match_2024casj_qm1.json").read_text())
QM1 = "2024casj_qm1"


def _canonical(**overrides) -> CanonicalMatch:
    base = dict(match_key=QM1, event_key="2024casj", scheduled_time=FIXTURE["time"], score_red=30, score_blue=27,
                red_roster=(253, 841, 8546), blue_roster=(5104, 6884, 6918))
    return CanonicalMatch(**{**base, **overrides})


def test_event_payload_conversion() -> None:
    converted = event_input_from_payload("2024casj", {"event_type": 0, "week": 0, "district": None})
    assert (converted.event_type, converted.week, converted.district) == (0, 0, None)  # type: ignore[union-attr]
    district = event_input_from_payload("2024mimil", {"event_type": 1, "week": 2, "district": {"abbreviation": "fim"}})
    assert district.district == "fim"  # type: ignore[union-attr]
    bad = event_input_from_payload("2024x", {"event_type": "0", "week": 1.5})
    assert isinstance(bad, ReaderIssue) and bad.code == RAW_EVENT_INVALID and bad.effect == "excluded"


def test_real_match_payload_converts_with_no_issues() -> None:
    match, issues = match_input_from_payload(_canonical(), FIXTURE)
    assert issues == []
    assert match is not None and match.comp_level == "qm" and match.time == FIXTURE["time"]
    assert match.red.teams == (841, 8546, 253)  # TBA order is kept
    assert match.red.score == 30 and match.red.breakdown == FIXTURE["score_breakdown"]["red"]
    assert match.blue.dq_teams == () and match.blue.surrogate_teams == ()


def test_disagreements_with_canonical_tables_are_noted_and_raw_is_used() -> None:
    match, issues = match_input_from_payload(
        _canonical(scheduled_time=1, score_red=31, blue_roster=(1, 2, 3)), FIXTURE
    )
    assert match is not None and match.time == FIXTURE["time"] and match.red.score == 30
    assert sorted(i.code for i in issues) == [CANONICAL_ROSTER_MISMATCH, CANONICAL_SCORE_MISMATCH, CANONICAL_TIME_MISMATCH]
    assert all(i.effect == "noted" for i in issues)


def test_unplayed_minus_one_matches_canonical_null() -> None:
    payload = copy.deepcopy(FIXTURE)
    payload["alliances"]["red"]["score"] = payload["alliances"]["blue"]["score"] = -1
    _, issues = match_input_from_payload(_canonical(score_red=None, score_blue=None), payload)
    assert issues == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda p: p.update(event_key="2024cada"), RAW_MATCH_EVENT_MISMATCH),
        (lambda p: p.update(comp_level="xx"), RAW_MATCH_INVALID),
        (lambda p: p.update(time="soon"), RAW_MATCH_INVALID),
        (lambda p: p["alliances"]["red"].update(team_keys=["frc254B", "frc1", "frc2"]), UNPARSEABLE_TEAM_KEY),
        (lambda p: p["alliances"]["red"].update(score=30.0), RAW_MATCH_INVALID),
        (lambda p: p.update(score_breakdown=[1]), RAW_MATCH_INVALID),
        (lambda p: p["alliances"].pop("blue"), RAW_MATCH_INVALID),
    ],
)
def test_payloads_that_cannot_be_built_are_excluded(mutate, code: str) -> None:
    payload = copy.deepcopy(FIXTURE)
    mutate(payload)
    match, issues = match_input_from_payload(_canonical(), payload)
    assert match is None
    assert [i.code for i in issues if i.effect == "excluded"] == [code]


def test_placeholder_team_key_is_noted_and_left_to_the_engine() -> None:
    payload = copy.deepcopy(FIXTURE)
    payload["alliances"]["red"]["team_keys"] = ["frc0", "frc0", "frc0"]
    match, issues = match_input_from_payload(_canonical(red_roster=()), payload)
    assert match is not None and match.red.teams == (0, 0, 0)  # the engine filters it as invalid_alliance
    assert {i.code for i in issues} == {PLACEHOLDER_TEAM_KEY, CANONICAL_ROSTER_MISMATCH}


def _rows():
    events = [("2024casj", 1, {"event_type": 0, "week": 0, "district": None}),
              ("2024nope", None, None),
              ("2024dup", 2, {"event_type": 0, "week": 1, "district": None}),
              ("2024dup", 3, {"event_type": 0, "week": 1, "district": None})]
    other = copy.deepcopy(FIXTURE)
    other["key"] = "2024casj_qm2"
    matches = [(QM1, "2024casj", FIXTURE["time"], 30, 27, 10, FIXTURE),
               ("2024casj_qm2", "2024casj", FIXTURE["time"], 30, 27, 11, other),
               ("2024casj_qm3", "2024casj", FIXTURE["time"], 30, 27, None, None),
               ("2024nope_qm1", "2024nope", FIXTURE["time"], 30, 27, 12, FIXTURE)]
    rosters = [(k, c, t) for k in (QM1, "2024casj_qm2") for c, ts in (("red", (841, 8546, 253)),
                                                                          ("blue", (6884, 5104, 6918))) for t in ts]
    return events, matches, rosters


def test_assembly_excludes_what_it_cannot_read_and_says_so() -> None:
    events, matches, rosters = _rows()
    result = assemble_season_input(2024, events, matches, rosters)
    assert [e.event_key for e in result.season_input.events] == ["2024casj"]
    assert [m.match_key for m in result.season_input.matches] == [QM1, "2024casj_qm2"]
    got = {(i.code, i.event_key, i.match_key) for i in result.issues}
    assert got == {
        (RAW_EVENT_MISSING, "2024nope", None),
        (DUPLICATE_CURRENT_PAYLOAD, "2024dup", None),
        (RAW_MATCH_MISSING, "2024casj", "2024casj_qm3"),
        (RAW_EVENT_MISSING, "2024nope", "2024nope_qm1"),
    }
    assert result.canonical_events == 3 and result.canonical_matches == 4
    assert result.snapshot["raw_payloads_read"] == 3 and result.snapshot["max_raw_payload_id"] == 11


def test_assembly_does_not_depend_on_row_order() -> None:
    events, matches, rosters = _rows()
    first = assemble_season_input(2024, events, matches, rosters)
    rng = random.Random(1)
    for rows in (events, matches, rosters):
        rng.shuffle(rows)
    second = assemble_season_input(2024, events, matches, rosters)
    assert season_input_fingerprint(first.season_input) == season_input_fingerprint(second.season_input)
    assert first.issues == second.issues and first.snapshot == second.snapshot


# --- against the real database, read-only ------------------------------------------


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _database_available(), reason="Requires a reachable PostgreSQL database")


def _row_counts(database: Database) -> tuple:
    with database.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM raw_source_payloads), (SELECT count(*) FROM matches), "
                    "(SELECT count(*) FROM events), (SELECT count(*) FROM match_teams), "
                    "(SELECT max(id) FROM raw_source_payloads)")
        return cur.fetchone()


@requires_db
def test_reads_a_real_event_read_only_and_repeatably() -> None:
    database = Database(DatabaseConfig(Settings().database_url))
    before = _row_counts(database)
    first = read_season_input(database, 2024, event_keys=["2024casj"])
    second = read_season_input(database, 2024, event_keys=["2024casj"])
    assert _row_counts(database) == before
    if not first.season_input.matches:
        pytest.skip("2024casj is not synced in this database")
    assert season_input_fingerprint(first.season_input) == season_input_fingerprint(second.season_input)
    assert first.issues == ()
    qm1 = next(m for m in first.season_input.matches if m.match_key == QM1)
    assert qm1.red.breakdown == FIXTURE["score_breakdown"]["red"]
    assert qm1.time == FIXTURE["time"]
