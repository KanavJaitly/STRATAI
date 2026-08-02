from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from data.clients.schemas import EventSummary, Match, StatboticsTeamEventMetrics, TeamInfo
from data.clients.source_connector import SourceResponse
from data.config import Settings
from data.lineage import LineageEntry, LineageStore, entity_key_of
from data.orchestrator import sync_event
from data.staging import (
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
    normalize_match,
)
from data.staging.quality import (
    _roster_numbers,
    ISSUE_EXTRACTION_FAILURE,
    ISSUE_IMPLAUSIBLE_VALUE,
    ISSUE_INCONSISTENT_VALUES,
    ISSUE_MISSING_REFERENCE,
    ISSUE_OUT_OF_RANGE,
    ISSUE_VALIDATION_FAILURE,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    DataQualityRecorder,
    QualityContext,
    QualityIssue,
    check_entity,
    issues_from_extraction_errors,
    issues_from_validation_error,
    summarize,
)
from data.staging.validator import PayloadValidationError, ValidationIssue
from database.connection import Database, DatabaseConfig

# ---------------------------------------------------------------------------
# Sentinel fixtures, namespaced away from both real data and M8's fixtures.
# ---------------------------------------------------------------------------

# The event key's season prefix must agree with the payload's year: the staging
# layer derives a match's season from its event key, so a "9997" sentinel would
# make every match implausible-by-construction and there would be no way to
# assert that a healthy event produces a silent quality log. The "zzzqual"
# suffix is not a real TBA event code, and all teardown is scoped to this exact
# key. Team numbers stay far above the real range (see the note in
# test_a_clean_event_records_no_issues).
S_EVENT = "2025zzzqual"
S_TEAMS = [997001, 997002, 997003, 997004, 997005, 997006]
S_TEAM_KEYS = [f"frc{number}" for number in S_TEAMS]
S_MATCH = f"{S_EVENT}_qm1"

FULL_CONTEXT = QualityContext(
    known_team_numbers=frozenset(S_TEAMS), known_event_keys=frozenset({S_EVENT}),
)


def staging_team(**overrides: Any) -> StagingTeam:
    return StagingTeam(**{"team_number": 1114, "name": "Simbotics", "rookie_year": 2003, **overrides})


def staging_event(**overrides: Any) -> StagingEvent:
    return StagingEvent(**{
        "event_key": S_EVENT, "name": "Quality Sentinel", "season": 2025,
        "start_date": "2025-03-14", "end_date": "2025-03-16", **overrides,
    })


def staging_match(**overrides: Any) -> StagingMatch:
    return StagingMatch(**{
        "match_key": S_MATCH, "event_key": S_EVENT, "season": 2025,
        "competition_level": "qualification", "match_number": 1,
        "red_teams": S_TEAMS[:3], "blue_teams": S_TEAMS[3:],
        "red_score": 100, "blue_score": 90, "winning_alliance": "red", **overrides,
    })


def raw_match_payload(*, red_score: Any, blue_score: Any, **overrides: Any) -> dict[str, Any]:
    """A raw TBA match payload, for the checks that must read pre-normalization state."""
    return {
        "key": S_MATCH, "event_key": S_EVENT, "comp_level": "qm", "match_number": 1,
        "alliances": {
            "red": {"score": red_score, "team_keys": S_TEAM_KEYS[:3]},
            "blue": {"score": blue_score, "team_keys": S_TEAM_KEYS[3:]},
        },
        **overrides,
    }


def staging_stats(**overrides: Any) -> StagingTeamEventStats:
    return StagingTeamEventStats(**{
        "team_number": S_TEAMS[0], "event_key": S_EVENT, "season": 2025,
        "epa_total": 50.0, "wins": 8, "losses": 2, "ties": 0, "matches_played": 10, **overrides,
    })


def only(issues: list[QualityIssue], field: str | None = None) -> QualityIssue:
    """Return the single issue (optionally for one field), asserting there is exactly one."""
    candidates = issues if field is None else [issue for issue in issues if issue.field == field]
    assert len(candidates) == 1, f"expected exactly one issue{f' for {field}' if field else ''}, got {candidates}"
    return candidates[0]


# ===========================================================================
# Entity checks: no database.
# ===========================================================================


def test_nonpositive_team_number_is_fatal():
    issue = only(check_entity(staging_team(team_number=0), source="tba"), "team_number")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, True)
    assert issue.object_type == "team"
    assert issue.object_id == "0"


def test_implausibly_high_team_number_is_only_a_warning():
    # Deliberate: a plausibility ceiling that discarded data would be worse than
    # no ceiling. This is also why the M8 sentinel fixtures (998001+) still load.
    issue = only(check_entity(staging_team(team_number=998001), source="tba"), "team_number")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, False)


def test_implausible_rookie_year_is_a_warning():
    issue = only(check_entity(staging_team(rookie_year=1850), source="tba"), "rookie_year")
    assert (issue.severity, issue.is_fatal) == (SEVERITY_WARNING, False)


def test_clean_team_produces_no_issues():
    assert check_entity(staging_team(), source="tba") == []


def test_event_ending_before_it_starts_is_fatal():
    issue = only(check_entity(staging_event(end_date="2025-03-01"), source="tba"), "end_date")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_ERROR, True)


def test_implausible_season_is_only_a_warning():
    issue = only(check_entity(staging_event(season=1776), source="tba"), "season")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, False)
    assert "1776" in issue.description


def test_negative_alliance_score_is_fatal():
    issue = only(check_entity(staging_match(red_score=-5), source="tba", context=FULL_CONTEXT), "red_score")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, True)


def test_implausibly_high_alliance_score_is_only_a_warning():
    issues = check_entity(staging_match(red_score=5000), source="tba", context=FULL_CONTEXT)
    issue = only(issues, "red_score")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, False)


def test_declared_winner_that_was_outscored_is_a_warning():
    issue = only(
        check_entity(staging_match(winning_alliance="red", red_score=80, blue_score=90),
                    source="tba", context=FULL_CONTEXT),
        "winning_alliance",
    )
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING, False)


def test_declared_winner_of_a_tied_match_is_not_flagged():
    # Playoff tiebreakers legitimately advance an alliance from a tied match.
    match = staging_match(winning_alliance="red", red_score=90, blue_score=90)
    assert check_entity(match, source="tba", context=FULL_CONTEXT) == []


def test_partially_filled_alliance_is_a_warning_but_an_empty_one_is_not():
    partial = check_entity(staging_match(red_teams=S_TEAMS[:2]), source="tba", context=FULL_CONTEXT)
    issue = only(partial, "red_teams")
    assert (issue.issue_type, issue.severity) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING)

    # An unplayed playoff match has no roster yet -- a normal state, not a defect.
    empty = check_entity(staging_match(red_teams=[], blue_teams=[]), source="tba", context=FULL_CONTEXT)
    assert empty == []


def test_unplayed_match_is_valid_and_is_not_flagged_at_all():
    # TBA's -1 sentinel is resolved to NULL scores by the normalizer, so what
    # reaches this layer is simply a match with no result yet -- a normal state
    # (and the state of most of a live event's schedule), not a defect. It must
    # produce no issue of any severity, or a live sync would log a finding for
    # every unplayed match on the board.
    unplayed_raw = raw_match_payload(red_score=-1, blue_score=-1, winning_alliance="")
    match = staging_match(red_score=None, blue_score=None, winning_alliance=None)
    assert check_entity(match, source="tba", context=FULL_CONTEXT, raw_payload=unplayed_raw) == []


def test_one_sided_unplayed_sentinel_is_a_warning_not_a_rejection():
    # A match cannot be half-played. The normalizer reads the whole match as
    # unplayed (both scores NULL); the anomaly is recorded here rather than
    # vanishing. A warning, not an error: the row is still a real scheduled
    # match, and "unplayed" vs "the other alliance scored zero" is an
    # interpretation, not a certainty.
    half_raw = raw_match_payload(red_score=-1, blue_score=30, winning_alliance="")
    match = staging_match(red_score=None, blue_score=None, winning_alliance=None)

    issue = only(check_entity(match, source="tba", context=FULL_CONTEXT, raw_payload=half_raw), "red_score")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING, False)
    assert "30" in issue.description


def test_the_negative_score_rejection_still_catches_genuine_corruption():
    # The sentinel is handled upstream precisely so this rule can stay fatal.
    # -1 is TBA saying "no result yet"; -5 is a score that cannot exist.
    issue = only(check_entity(staging_match(red_score=-5), source="tba", context=FULL_CONTEXT), "red_score")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, True)


def test_an_unassigned_roster_reaches_this_layer_as_an_empty_one_and_is_not_flagged():
    # frc0 is dropped by the normalizer, so what arrives here is a match with no
    # roster -- already a legitimate state under the rule above. Asserted end to
    # end from the raw payload so the two layers are pinned together: nothing
    # about the frc0 fix may start producing a finding for an ordinary unplayed
    # match, of which a live event's board is mostly made.
    unassigned_raw = raw_match_payload(
        red_score=-1, blue_score=-1, winning_alliance="",
        alliances={
            "red": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
            "blue": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
        },
    )
    match = normalize_match("tba", unassigned_raw)
    assert (match.red_teams, match.blue_teams) == ([], [])
    assert check_entity(match, source="tba", context=FULL_CONTEXT, raw_payload=unassigned_raw) == []


def test_a_partially_assigned_roster_still_trips_the_alliance_size_warning():
    # No new rule was written for the partial case: dropping the placeholders
    # leaves a short alliance, which the existing plausibility rule already
    # answers -- a warning, so the match still loads.
    partial_raw = raw_match_payload(
        red_score=80, blue_score=70, winning_alliance="red",
        alliances={
            "red": {"score": 80, "team_keys": [S_TEAM_KEYS[0], "frc0", "frc0"]},
            "blue": {"score": 70, "team_keys": S_TEAM_KEYS[3:]},
        },
    )
    match = normalize_match("tba", partial_raw)
    assert match.red_teams == [S_TEAMS[0]]

    issue = only(check_entity(match, source="tba", context=FULL_CONTEXT, raw_payload=partial_raw), "red_teams")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, False)


def test_the_referential_context_never_looks_up_team_zero():
    # Team 0 has no teams row and never will. Left in the referenced set it
    # would send a lookup whose answer no check consults -- and, had frc0 been
    # kept on the roster instead of dropped, would have turned this fix into a
    # missing_reference rejection rather than a load.
    unassigned_raw = raw_match_payload(
        red_score=-1, blue_score=-1,
        alliances={
            "red": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
            "blue": {"score": -1, "team_keys": S_TEAM_KEYS[3:]},
        },
    )
    assert _roster_numbers(unassigned_raw) == set(S_TEAMS[3:])


def test_without_a_raw_payload_the_sentinel_check_is_skipped():
    # Same contract as `context`: a fact the caller did not supply is never
    # guessed at. check_entity stays callable with the entity alone.
    match = staging_match(red_score=None, blue_score=None, winning_alliance=None)
    assert check_entity(match, source="tba", context=FULL_CONTEXT) == []


def test_roster_team_that_will_not_exist_is_fatal():
    issue = only(
        check_entity(staging_match(blue_teams=[S_TEAMS[3], S_TEAMS[4], 555555]),
                    source="tba", context=FULL_CONTEXT),
        "blue_teams",
    )
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_MISSING_REFERENCE, SEVERITY_ERROR, True)
    assert "555555" in issue.description


def test_unknown_event_reference_is_fatal():
    match = staging_match(match_key="2025other_qm1", event_key="2025other")
    issue = only(check_entity(match, source="tba", context=FULL_CONTEXT), "event_key")
    assert (issue.issue_type, issue.is_fatal) == (ISSUE_MISSING_REFERENCE, True)


def test_without_context_referential_checks_are_skipped():
    # No context must never produce a false 'missing reference' rejection.
    match = staging_match(blue_teams=[555555, 555556, 555557], event_key=S_EVENT)
    assert check_entity(match, source="tba", context=None) == []


def test_absurdly_distant_scheduled_time_is_a_warning():
    far_future = datetime.now(timezone.utc) + timedelta(days=1000)
    issue = only(
        check_entity(staging_match(scheduled_time=far_future), source="tba", context=FULL_CONTEXT),
        "scheduled_time",
    )
    assert (issue.issue_type, issue.severity) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING)


def test_negative_match_record_is_fatal():
    issue = only(check_entity(staging_stats(wins=-1, matches_played=None), source="statbotics",
                              context=FULL_CONTEXT), "wins")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, True)


def test_matches_played_contradicting_its_own_breakdown_is_fatal():
    issue = only(
        check_entity(staging_stats(wins=8, losses=2, ties=0, matches_played=99),
                    source="statbotics", context=FULL_CONTEXT),
        "matches_played",
    )
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_ERROR, True)
    assert issue.object_id == f"{S_TEAMS[0]}_{S_EVENT}"


def test_far_negative_epa_is_only_a_warning():
    issue = only(check_entity(staging_stats(epa_total=-500.0), source="statbotics",
                              context=FULL_CONTEXT), "epa_total")
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, False)


def test_stats_referencing_unknown_team_and_event_are_fatal():
    stats = staging_stats(team_number=555555, event_key="2025other")
    issues = check_entity(stats, source="statbotics", context=FULL_CONTEXT)
    assert {issue.field for issue in issues} == {"team_number", "event_key"}
    assert all(issue.issue_type == ISSUE_MISSING_REFERENCE and issue.is_fatal for issue in issues)


def test_check_entity_rejects_an_unsupported_type():
    with pytest.raises(TypeError, match="No quality checks defined"):
        check_entity({"not": "an entity"}, source="tba")


# ===========================================================================
# Issue construction from the existing failure paths.
# ===========================================================================


def test_validation_error_becomes_one_fatal_issue_per_underlying_problem():
    error = PayloadValidationError([
        ValidationIssue("match", "event_key", "Missing or empty required field 'event_key'", S_MATCH),
        ValidationIssue("match", "alliances.red.teams", "A team cannot appear twice", S_MATCH),
    ])
    issues = issues_from_validation_error(
        error, source="tba", object_type="match", object_id=S_MATCH, raw_payload_id=42,
    )

    assert [issue.field for issue in issues] == ["event_key", "alliances.red.teams"]
    assert all(issue.issue_type == ISSUE_VALIDATION_FAILURE for issue in issues)
    assert all(issue.is_fatal and issue.raw_payload_id == 42 for issue in issues)


def test_extraction_errors_become_warnings():
    issues = issues_from_extraction_errors(["Statbotics unavailable for 997001"], event_key=S_EVENT)
    issue = only(issues)
    assert (issue.issue_type, issue.severity, issue.is_fatal) == (ISSUE_EXTRACTION_FAILURE, SEVERITY_WARNING, False)
    assert (issue.object_type, issue.object_id) == ("extraction", S_EVENT)


def test_summarize_reports_totals_and_spreads():
    issues = [
        QualityIssue("tba", "match", "m1", ISSUE_OUT_OF_RANGE, SEVERITY_ERROR, "bad"),
        QualityIssue("tba", "match", "m2", ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "odd"),
        QualityIssue("tba", "team", "t1", ISSUE_IMPLAUSIBLE_VALUE, SEVERITY_WARNING, "odd"),
    ]
    assert summarize(issues) == {
        "total": 3, "fatal": 1,
        "by_severity": {SEVERITY_ERROR: 1, SEVERITY_WARNING: 2},
        "by_type": {ISSUE_OUT_OF_RANGE: 1, ISSUE_IMPLAUSIBLE_VALUE: 2},
    }
    assert summarize([]) == {"total": 0, "fatal": 0, "by_severity": {}, "by_type": {}}


# ===========================================================================
# Lineage keys: no database.
# ===========================================================================


def test_entity_keys_match_the_canonical_natural_keys():
    assert entity_key_of(staging_team(team_number=1114)) == "1114"
    assert entity_key_of(staging_event()) == S_EVENT
    assert entity_key_of(staging_match()) == S_MATCH
    assert entity_key_of(staging_stats()) == f"{S_TEAMS[0]}_{S_EVENT}"


def test_entity_key_of_rejects_an_unsupported_type():
    with pytest.raises(TypeError, match="No lineage key defined"):
        entity_key_of(object())


# ===========================================================================
# Integration: real data_quality_issues / canonical_lineage behaviour.
# Auto-skips when no PostgreSQL is reachable via the configured DATABASE_URL.
# ===========================================================================


def raw_event() -> dict[str, Any]:
    return {
        "key": S_EVENT, "name": "Quality Sentinel Regional", "event_code": "zzzqual",
        "year": 2025, "start_date": "2025-03-14", "end_date": "2025-03-16",
        "city": "San Jose", "state_prov": "CA", "country": "USA",
    }


def raw_teams() -> list[dict[str, Any]]:
    return [
        {"key": f"frc{number}", "team_number": number, "nickname": f"Sentinel {number}",
         "rookie_year": 2001}
        for number in S_TEAMS
    ]


def raw_match(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": S_MATCH, "event_key": S_EVENT, "comp_level": "qm",
        "set_number": 1, "match_number": 1, "time": 1700000000,
        "alliances": {
            "red": {"score": 100, "team_keys": S_TEAM_KEYS[:3]},
            "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
        },
        "winning_alliance": "red",
    }
    payload.update(overrides)
    return payload


class FakeTBAClient:
    def __init__(
        self,
        *,
        matches: list[dict[str, Any]] | None = None,
        teams: list[dict[str, Any]] | None = None,
        team_info_fails: bool = False,
    ) -> None:
        self.matches = matches if matches is not None else [raw_match()]
        self.teams = teams if teams is not None else raw_teams()
        self.team_info_fails = team_info_fails

    def fetch_event(self, event_key: str) -> SourceResponse[EventSummary]:
        payload = raw_event()
        return SourceResponse(payload, EventSummary.model_validate(payload))

    def fetch_event_matches(self, event_key: str) -> list[SourceResponse[Match]]:
        return [SourceResponse(p, Match.model_validate(p)) for p in self.matches]

    def fetch_event_teams(self, event_key: str) -> list[SourceResponse[TeamInfo]]:
        return [SourceResponse(p, TeamInfo.model_validate(p)) for p in self.teams]

    def fetch_team_info(self, team_number: int) -> SourceResponse[TeamInfo]:
        if self.team_info_fails:
            raise RuntimeError(f"simulated TBA outage for team {team_number}")
        payload = {"key": f"frc{team_number}", "team_number": team_number}
        return SourceResponse(payload, TeamInfo.model_validate(payload))


class FakeStatboticsClient:
    def fetch_team_event_metrics(
        self, team_number: int, event_key: str
    ) -> SourceResponse[StatboticsTeamEventMetrics]:
        # Statbotics's real nested response shape, so this integration path
        # proves a genuine payload reaches team_event_stats.
        payload = {
            "team": team_number, "year": 2025, "event": event_key,
            "epa": {
                "total_points": 50.0,
                "breakdown": {"auto_points": 10.0, "teleop_points": 30.0, "endgame_points": 10.0},
            },
            "record": {"total": {"wins": 8, "losses": 2, "ties": 0, "count": 10}},
        }
        return SourceResponse(payload, StatboticsTeamEventMetrics.model_validate(payload))


def _database_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{S_EVENT}%",))
        cursor.execute("DELETE FROM team_event_stats WHERE event_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (S_EVENT,))
        # Raw payload deletes cascade to both data_quality_issues and
        # canonical_lineage; the explicit deletes afterwards catch issue rows
        # with no raw payload (extraction failures) and any stragglers.
        cursor.execute("DELETE FROM raw_source_payloads WHERE source_object_id LIKE %s", (f"%{S_EVENT}%",))
        cursor.execute("DELETE FROM raw_source_payloads WHERE source_object_id = ANY(%s::text[])", (S_TEAM_KEYS,))
        cursor.execute("DELETE FROM canonical_lineage WHERE entity_key LIKE %s", (f"%{S_EVENT}%",))
        cursor.execute(
            "DELETE FROM canonical_lineage WHERE entity_key = ANY(%s::text[])",
            ([str(number) for number in S_TEAMS],),
        )
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (S_EVENT,))
        cursor.execute("DELETE FROM source_watermarks WHERE scope_key = %s", (S_EVENT,))


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    try:
        yield db
    finally:
        _cleanup(db)


def _run(database: Database, **kwargs: Any):
    kwargs.setdefault("tba", FakeTBAClient())
    kwargs.setdefault("statbotics", FakeStatboticsClient())
    return sync_event(S_EVENT, database=database, **kwargs)


def _belongs_to_sentinel_event(object_id: str | None) -> bool:
    """Is this issue about one of this module's sentinel objects?

    data_quality_issues is a shared, append-only table: a developer who has synced a real
    event (which the quickstart tells them to do) leaves genuine issue rows behind, and
    earlier milestones' sentinel data can too. Filtering by object_type alone would pick
    those up, so every assertion here is scoped to this module's own object ids --
    the event key itself, anything derived from it (match keys, "<team>_<event>"), and
    the sentinel team numbers.
    """
    if object_id is None:
        return False
    return object_id == S_EVENT or S_EVENT in object_id or object_id in {str(n) for n in S_TEAMS}


def _issues(database: Database, **filters: Any) -> list[dict[str, Any]]:
    """Unresolved issues for this module's sentinel event only."""
    rows = DataQualityRecorder(database).open_issues(**filters)
    return [row for row in rows if _belongs_to_sentinel_event(row["object_id"])]


def _issue_for(database: Database, object_type: str, field: str) -> dict[str, Any]:
    """The single recorded issue for one object type and field."""
    rows = [row for row in _issues(database, object_type=object_type) if row["field"] == field]
    assert len(rows) == 1, f"expected one {object_type}.{field} issue, got {rows}"
    return rows[0]


def _scalar(database: Database, sql: str, params: tuple = ()) -> Any:
    with database.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return None if row is None else row[0]


@requires_db
def test_a_clean_event_records_no_issues(database):
    result = _run(database)

    assert result.loaded == {"teams": 6, "events": 1, "matches": 1, "team_event_stats": 6}
    assert result.fatal_issues == []
    for object_type in ("match", "event", "team_event", "extraction"):
        assert _issues(database, object_type=object_type) == [], object_type

    # The only findings are the team-number ceiling warnings the six-digit
    # sentinel numbers deliberately trip -- warnings, so they are recorded
    # without keeping a single team out of the canonical tables.
    team_issues = _issues(database, object_type="team")
    assert len(team_issues) == 6
    assert all(row["severity"] == SEVERITY_WARNING and row["field"] == "team_number" for row in team_issues)
    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (S_TEAMS,)) == 6


@requires_db
def test_invalid_payload_records_issues_referencing_the_offending_raw_row(database):
    # A team twice on one alliance: structurally valid to the client model,
    # rejected by the staging validator.
    bad = raw_match()
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    result = _run(database, tba=FakeTBAClient(matches=[bad]))

    issues = _issues(database, object_type="match")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["issue_type"] == ISSUE_VALIDATION_FAILURE
    assert issue["severity"] == SEVERITY_ERROR
    assert (issue["source"], issue["object_id"]) == ("tba", S_MATCH)
    assert issue["field"] == "alliances.red.teams"
    assert "cannot appear twice" in issue["description"]
    assert issue["pipeline_run_id"] == result.run_id
    assert issue["detected_at"] is not None

    # The raw_payload_id points at the actual landed row for that match.
    landed_id = _scalar(
        database,
        "SELECT id FROM raw_source_payloads WHERE source_object_id = %s AND is_current",
        (S_MATCH,),
    )
    assert issue["raw_payload_id"] == landed_id

    # Rejected before serving.
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 0


@requires_db
def test_fatal_quality_issue_keeps_the_record_out_of_the_canonical_tables(database):
    # A negative score passes every structural check and only fails on quality:
    # this is the path that exists solely because of Milestone 9.
    negative = raw_match(alliances={
        "red": {"score": -5, "team_keys": S_TEAM_KEYS[:3]},
        "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
    })
    result = _run(database, tba=FakeTBAClient(matches=[negative]))

    issue = _issue_for(database, "match", "red_score")
    assert (issue["issue_type"], issue["severity"]) == (ISSUE_OUT_OF_RANGE, SEVERITY_ERROR)
    assert issue["pipeline_run_id"] == result.run_id
    # The same payload also trips a winning_alliance warning (red "won" with -5
    # against 90); one fatal finding is enough to reject it.
    assert _issue_for(database, "match", "winning_alliance")["severity"] == SEVERITY_WARNING

    assert result.loaded["matches"] == 0
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 0
    assert _scalar(database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (S_MATCH,)) == 0
    # And no lineage was claimed for a row that was never written.
    assert LineageStore(database).trace("match", S_MATCH) == []
    # Teams and the event still loaded: one bad match does not block the event.
    assert result.loaded["teams"] == 6
    # The watermark held short of the rejection, so it will be retried.
    assert _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks WHERE source = 'tba' AND object_type = 'match' AND scope_key = %s",
        (S_EVENT,),
    ) is None


@requires_db
def test_missing_reference_is_rejected_cleanly_instead_of_crashing_the_load(database):
    # TBA's team list omits 997006 and the roster backfill fails, so the match
    # references a team no teams row will contain. Without the referential
    # check this is a foreign-key violation that aborts the whole load.
    tba = FakeTBAClient(teams=raw_teams()[:5], team_info_fails=True)
    result = _run(database, tba=tba)

    reference_issues = [i for i in _issues(database, object_type="match")
                       if i["issue_type"] == ISSUE_MISSING_REFERENCE]
    assert len(reference_issues) == 1
    assert reference_issues[0]["field"] == "blue_teams"
    assert "997006" in reference_issues[0]["description"]
    assert reference_issues[0]["severity"] == SEVERITY_ERROR

    # The failed backfill is recorded too, as a warning.
    extraction_issues = _issues(database, object_type="extraction")
    assert len(extraction_issues) == 1
    assert extraction_issues[0]["issue_type"] == ISSUE_EXTRACTION_FAILURE
    assert extraction_issues[0]["severity"] == SEVERITY_WARNING
    assert extraction_issues[0]["raw_payload_id"] is None

    # The event's other data still loaded; only the unloadable match was dropped.
    assert result.loaded == {"teams": 5, "events": 1, "matches": 0, "team_event_stats": 5}
    assert _scalar(database, "SELECT COUNT(*) FROM matches WHERE event_key = %s", (S_EVENT,)) == 0


@requires_db
def test_warning_is_recorded_but_the_record_still_loads(database):
    # A declared winner who was outscored: suspicious, not disqualifying.
    inconsistent = raw_match(alliances={
        "red": {"score": 80, "team_keys": S_TEAM_KEYS[:3]},
        "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
    }, winning_alliance="red")
    result = _run(database, tba=FakeTBAClient(matches=[inconsistent]))

    issue = _issue_for(database, "match", "winning_alliance")
    assert (issue["issue_type"], issue["severity"]) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING)
    assert len(_issues(database, object_type="match")) == 1  # nothing else flagged

    assert result.skipped == []
    assert result.loaded["matches"] == 1
    assert _scalar(database, "SELECT score_red FROM matches WHERE match_key = %s", (S_MATCH,)) == 80


@requires_db
def test_canonical_rows_trace_back_to_their_raw_payloads(database):
    result = _run(database)
    store = LineageStore(database)

    assert result.lineage_recorded == 14  # 1 event + 6 teams + 1 match + 6 team_event

    # Every entity type is traceable, keyed on its canonical natural key.
    for entity_type, entity_key, source in (
        ("event", S_EVENT, "tba"),
        ("team", str(S_TEAMS[0]), "tba"),
        ("match", S_MATCH, "tba"),
        ("team_event", f"{S_TEAMS[0]}_{S_EVENT}", "statbotics"),
    ):
        record = store.latest(entity_type, entity_key)
        assert record is not None, f"no lineage for {entity_type} {entity_key}"
        assert record.source == source
        assert record.pipeline_run_id == result.run_id

    # And the trace resolves to the actual raw payload the row was built from.
    traced = store.trace_to_payload("match", S_MATCH)
    assert traced is not None
    raw_id, payload = traced
    assert payload["key"] == S_MATCH
    assert payload["alliances"]["red"]["team_keys"] == S_TEAM_KEYS[:3]
    assert raw_id == _scalar(
        database,
        "SELECT id FROM raw_source_payloads WHERE source_object_id = %s AND is_current",
        (S_MATCH,),
    )
    # The traced payload is the landing row itself, not a copy.
    assert payload == _scalar(
        database, "SELECT payload_json FROM raw_source_payloads WHERE id = %s", (raw_id,)
    )


@requires_db
def test_lineage_keeps_the_history_of_every_payload_version(database):
    _run(database)
    corrected = raw_match(alliances={
        "red": {"score": 111, "team_keys": S_TEAM_KEYS[:3]},
        "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
    })
    second = _run(database, tba=FakeTBAClient(matches=[corrected]))

    store = LineageStore(database)
    history = store.trace("match", S_MATCH)
    assert len(history) == 2  # both payload versions retained
    assert history[0].raw_payload_id < history[1].raw_payload_id  # oldest first
    assert history[1].pipeline_run_id == second.run_id

    # The current provenance is the corrected payload.
    raw_id, payload = store.trace_to_payload("match", S_MATCH)
    assert raw_id == history[1].raw_payload_id
    assert payload["alliances"]["red"]["score"] == 111
    assert _scalar(database, "SELECT score_red FROM matches WHERE match_key = %s", (S_MATCH,)) == 111


@requires_db
def test_lineage_recording_is_idempotent(database):
    _run(database)
    store = LineageStore(database)
    existing = store.latest("match", S_MATCH)
    assert existing is not None

    # Re-recording the same (entity, payload) pair adds nothing and keeps the
    # run that first promoted it.
    store.record([LineageEntry("match", S_MATCH, existing.raw_payload_id, "tba")], pipeline_run_id=None)

    history = store.trace("match", S_MATCH)
    assert len(history) == 1
    assert history[0].pipeline_run_id == existing.pipeline_run_id


@requires_db
def test_a_persistently_bad_payload_is_re_detected_on_every_run(database):
    bad = raw_match()
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]

    first = _run(database, tba=FakeTBAClient(matches=[bad]))
    second = _run(database, tba=FakeTBAClient(matches=[bad]))

    # One row per detection: the watermark deliberately holds short of the bad
    # payload, so it is re-read and re-reported, and "how long has this been
    # broken" stays answerable.
    detections = _issues(database, object_type="match")
    assert len(detections) == 2
    assert {row["pipeline_run_id"] for row in detections} == {first.run_id, second.run_id}
    assert len({row["raw_payload_id"] for row in detections}) == 1  # same offending payload


@requires_db
def test_an_unplayed_match_loads_as_unplayed_and_never_pins_the_watermark(database):
    """The whole -1 sentinel cluster, end to end.

    Before the fix this match was rejected as a "negative score", its raw
    payload pinned the watermark one id below itself forever, and every re-sync
    logged the same two out_of_range errors again. It also normalized to a
    fabricated "tie", which only stayed out of the database because the
    rejection happened first.
    """
    unplayed_key = f"{S_EVENT}_qm2"
    unplayed = raw_match(
        key=unplayed_key, match_number=2,
        # Exactly TBA's unplayed shape, as observed in the real 2024gagwi
        # payloads: -1 on both alliances, empty winner, no result timestamps.
        alliances={
            "red": {"score": -1, "team_keys": S_TEAM_KEYS[:3]},
            "blue": {"score": -1, "team_keys": S_TEAM_KEYS[3:]},
        },
        winning_alliance="", actual_time=None, score_breakdown=None,
    )
    first = _run(database, tba=FakeTBAClient(matches=[raw_match(), unplayed]))

    # Loaded, not rejected -- and as unplayed, not as a tie.
    assert first.loaded["matches"] == 2
    assert first.fatal_issues == []
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT score_red, score_blue, winning_alliance FROM matches WHERE match_key = %s",
            (unplayed_key,),
        )
        assert cursor.fetchone() == (None, None, None)

    # A scheduled match still carries its real roster.
    assert _scalar(
        database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (unplayed_key,),
    ) == 6

    # Valid, so not flagged at all: a live sync must not log a finding for
    # every not-yet-played match on the schedule.
    assert _issues(database, object_type="match") == []

    # The watermark reached the newest match payload instead of stopping below
    # the unplayed one -- the payload is permanently valid, so there is nothing
    # to retry.
    watermark = _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks "
        "WHERE source = 'tba' AND object_type = 'match' AND scope_key = %s",
        (S_EVENT,),
    )
    newest_match_payload = _scalar(
        database,
        "SELECT MAX(id) FROM raw_source_payloads "
        "WHERE source_object_type = 'match' AND source_object_id LIKE %s",
        (f"{S_EVENT}%",),
    )
    assert int(watermark) == newest_match_payload

    # Re-syncing is a true no-op: nothing re-landed, nothing re-loaded, and --
    # unlike a permanently-invalid payload -- no issue re-recorded.
    second = _run(database, tba=FakeTBAClient(matches=[raw_match(), unplayed]))
    assert second.landed["tba.match"] == 0
    assert second.loaded["matches"] == 0
    assert _issues(database, object_type="match") == []


@requires_db
def test_an_unassigned_roster_loads_as_unplayed_and_never_pins_the_watermark(database):
    """The whole frc0 sentinel cluster, end to end.

    The sibling of the -1 test above, and the same symptom reached by a
    different route: before this fix the payload was rejected by *structural
    validation* (three frc0s read as the same team three times, and again on the
    opposing alliance), so it never reached the quality layer at all. It could
    never become valid -- TBA is not going to reissue a completed event's
    schedule -- so the watermark held one id below it forever and every re-sync
    re-logged the same three validation_failure errors plus a failed backfill of
    team frc0.
    """
    unassigned_key = f"{S_EVENT}_qm2"
    unassigned = raw_match(
        key=unassigned_key, match_number=2,
        # Exactly the shape of the real 2024mdsev_qm73/_qm74 payloads: both
        # sentinels at once, unassigned rosters and unplayed scores.
        alliances={
            "red": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
            "blue": {"score": -1, "team_keys": ["frc0", "frc0", "frc0"]},
        },
        winning_alliance="", actual_time=None, score_breakdown=None,
    )
    tba = FakeTBAClient(matches=[raw_match(), unassigned])
    first = _run(database, tba=tba)

    # Loaded, not rejected -- and as unplayed, not as a tie.
    assert first.loaded["matches"] == 2
    assert first.fatal_issues == []
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT score_red, score_blue, winning_alliance FROM matches WHERE match_key = %s",
            (unassigned_key,),
        )
        assert cursor.fetchone() == (None, None, None)

    # The roster is absent, not a placeholder: no match_teams rows at all, and
    # team 0 nowhere in the canonical tables.
    assert _scalar(
        database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (unassigned_key,),
    ) == 0
    assert _scalar(database, "SELECT COUNT(*) FROM teams WHERE team_number = 0") == 0
    # The played match in the same batch still carries its full real roster.
    assert _scalar(
        database, "SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (S_MATCH,),
    ) == 6

    # Valid, so not flagged at all -- and frc0 was never looked up, so no
    # extraction_failure warning for a team that cannot exist.
    assert _issues(database, object_type="match") == []
    assert _issues(database, object_type="extraction") == []

    # The watermark reached the newest match payload instead of stopping below
    # the unassigned one.
    watermark = _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks "
        "WHERE source = 'tba' AND object_type = 'match' AND scope_key = %s",
        (S_EVENT,),
    )
    newest_match_payload = _scalar(
        database,
        "SELECT MAX(id) FROM raw_source_payloads "
        "WHERE source_object_type = 'match' AND source_object_id LIKE %s",
        (f"{S_EVENT}%",),
    )
    assert int(watermark) == newest_match_payload

    # Re-syncing is a true no-op: nothing re-landed, nothing re-loaded, and no
    # issue re-recorded on either the match or the extraction path.
    second = _run(database, tba=FakeTBAClient(matches=[raw_match(), unassigned]))
    assert second.landed["tba.match"] == 0
    assert second.loaded["matches"] == 0
    assert _issues(database, object_type="match") == []
    assert _issues(database, object_type="extraction") == []


@requires_db
def test_a_genuine_duplicate_roster_is_still_rejected_and_still_pins_the_watermark(database):
    """The other half of the frc0 fix: real corruption must be unaffected.

    A real team entered three times is not a placeholder, and treating it as one
    would load a match asserting one robot occupied three stations. This pins
    the behaviour the fix deliberately did not change -- including that such a
    payload still holds the watermark short of itself, which is the correct
    response to a record that might yet be corrected at source.
    """
    corrupt_key = f"{S_EVENT}_qm2"
    corrupt = raw_match(
        key=corrupt_key, match_number=2,
        alliances={
            # Real team, three times -- corruption, not an unassigned roster.
            "red": {"score": 100, "team_keys": [S_TEAM_KEYS[0]] * 3},
            "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
        },
    )
    result = _run(database, tba=FakeTBAClient(matches=[raw_match(), corrupt]))

    rejections = [row for row in _issues(database, object_type="match")
                  if row["object_id"] == corrupt_key]
    assert rejections, "a real duplicate roster must still be rejected"
    assert {row["issue_type"] for row in rejections} == {ISSUE_VALIDATION_FAILURE}
    assert {row["severity"] for row in rejections} == {SEVERITY_ERROR}
    assert any("cannot appear twice" in row["description"] for row in rejections)

    # Never reached the canonical tables; the healthy match in the same batch did.
    assert _scalar(
        database, "SELECT COUNT(*) FROM matches WHERE match_key = %s", (corrupt_key,),
    ) == 0
    assert result.loaded["matches"] == 1

    # And the watermark still holds short of it, so a corrected payload would be
    # picked up on a later run.
    watermark = _scalar(
        database,
        "SELECT watermark_value FROM source_watermarks "
        "WHERE source = 'tba' AND object_type = 'match' AND scope_key = %s",
        (S_EVENT,),
    )
    corrupt_payload_id = _scalar(
        database,
        "SELECT id FROM raw_source_payloads WHERE source_object_id = %s AND is_current",
        (corrupt_key,),
    )
    assert int(watermark) < corrupt_payload_id


@requires_db
def test_a_half_played_match_is_warned_about_but_still_loads(database):
    # One alliance sentinel, one real score. Incoherent, so the match is read
    # as unplayed rather than stored as an uninterpretable NULL/90 row -- but
    # the anomaly is recorded instead of vanishing.
    half = raw_match(alliances={
        "red": {"score": -1, "team_keys": S_TEAM_KEYS[:3]},
        "blue": {"score": 90, "team_keys": S_TEAM_KEYS[3:]},
    }, winning_alliance="")
    result = _run(database, tba=FakeTBAClient(matches=[half]))

    issue = _issue_for(database, "match", "red_score")
    assert (issue["issue_type"], issue["severity"]) == (ISSUE_INCONSISTENT_VALUES, SEVERITY_WARNING)
    assert issue["pipeline_run_id"] == result.run_id

    # Warning, not rejection: the record still loads, with both scores NULL.
    assert result.loaded["matches"] == 1
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT score_red, score_blue, winning_alliance FROM matches WHERE match_key = %s",
            (S_MATCH,),
        )
        assert cursor.fetchone() == (None, None, None)


@requires_db
def test_run_summary_records_the_quality_and_lineage_counts(database):
    bad = raw_match()
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    result = _run(database, tba=FakeTBAClient(matches=[bad]))

    stage_counts = _scalar(database, "SELECT stage_counts FROM pipeline_runs WHERE id = %s", (result.run_id,))
    assert stage_counts["quality_issues"]["fatal"] == 1
    assert stage_counts["quality_issues"]["by_type"][ISSUE_VALIDATION_FAILURE] == 1
    assert stage_counts["lineage_recorded"] == 13  # everything except the rejected match
    assert _scalar(database, "SELECT status FROM pipeline_runs WHERE id = %s", (result.run_id,)) == "succeeded"


@requires_db
def test_issues_and_lineage_are_cleaned_up_with_their_run_and_payload(database):
    # The ON DELETE CASCADE from 0007 is what lets any caller (including earlier
    # milestones' test teardown) delete a run or a raw payload without hitting a
    # foreign-key violation.
    bad = raw_match()
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    result = _run(database, tba=FakeTBAClient(matches=[bad]))
    assert _issues(database, object_type="match")

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM pipeline_runs WHERE id = %s", (result.run_id,))

    assert _issues(database, object_type="match") == []
    # Lineage survives a deleted run (the provenance is still true) but loses
    # the run reference.
    surviving = LineageStore(database).latest("team", str(S_TEAMS[0]))
    assert surviving is not None
    assert surviving.pipeline_run_id is None

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM raw_source_payloads WHERE id = %s", (surviving.raw_payload_id,))
    assert LineageStore(database).latest("team", str(S_TEAMS[0])) is None


@requires_db
def test_open_issues_filters_by_object_and_severity(database):
    bad = raw_match()
    bad["alliances"]["red"]["team_keys"] = [S_TEAM_KEYS[0], S_TEAM_KEYS[0], S_TEAM_KEYS[2]]
    _run(database, tba=FakeTBAClient(matches=[bad], teams=raw_teams()[:5], team_info_fails=True))

    assert all(row["severity"] == SEVERITY_ERROR for row in _issues(database, severity=SEVERITY_ERROR))
    assert all(row["object_type"] == "extraction" for row in _issues(database, object_type="extraction"))
    assert _issues(database, object_id="no-such-object") == []
