"""Phase 3 Milestone 11: quality checks over computed team_metrics.

Two halves, for two different questions.

The first is pure: every rule in data.metrics.quality triggered on its own,
against hand-built TeamMetrics objects, asserting the exact issue recorded.
Each fixture here is deliberately constructed to pass every pydantic validator
in data/metrics/schemas.py and every CHECK constraint in
0008_metrics_schema.sql -- if a rule could only be triggered by an object the
models refuse to build, that rule would be dead code, and proving otherwise is
the point of building them this way rather than with mocks.

The second is integration, against real Postgres: a seeded sentinel event run
through the real compute_event_team_metrics, asserting the issues land in
data_quality_issues and are queryable through the existing DataQualityRecorder,
and -- the load-bearing one -- that a low-confidence team's metrics row is
still in team_metrics afterwards. Warning means recorded and loaded. A rule
that discarded the metric would defeat the milestone.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from data.config import Settings
from data.metrics import quality as metrics_quality
from data.metrics.aggregation import MIN_OBSERVATIONS_FOR_SCORE
from data.metrics.compute import (
    ENTITY_TYPE_TEAM_METRICS,
    PIPELINE_NAME,
    compute_event_team_metrics,
    team_metrics_entity_key,
)
from data.metrics.quality import (
    OBJECT_TYPE_TEAM_METRICS,
    QUALITY_SOURCE,
    check_team_metrics,
    team_metrics_object_id,
)
from data.metrics.schemas import (
    MIN_MATCHES_FOR_STDDEV,
    DefenseFeedingProfile,
    ScoringProfile,
    TeamMetrics,
)
from data.staging.quality import (
    ISSUE_IMPLAUSIBLE_VALUE,
    ISSUE_INCONSISTENT_VALUES,
    ISSUE_LOW_SAMPLE_SIZE,
    LOW_AGREEMENT,
    LOW_SAMPLE_MATCHES,
    LOW_SAMPLE_OBSERVATIONS,
    SEVERITY_WARNING,
    DataQualityRecorder,
    check_entity,
)
from database.connection import Database, DatabaseConfig

_COMPUTED_AT = "2026-08-05T18:00:00Z"


# ===========================================================================
# Builders. Every default is a clean, high-confidence metric that trips
# nothing, so each test below changes exactly the fields its own rule is about
# and any extra issue is that change's fault, not the fixture's.
# ===========================================================================


def scoring(**overrides: Any) -> ScoringProfile:
    """A clean 8-match ScoringProfile: internally consistent, well above every threshold."""
    base: dict[str, Any] = {
        "matches_scheduled": 8, "matches_used": 8,
        "average_score": 50.0, "score_stddev": 5.0,
        "consistency_rating": 90.0, "reliability_score": 100.0,
        "good_day_count": 1, "average_day_count": 6, "bad_day_count": 1,
    }
    base.update(overrides)
    return ScoringProfile(**base)


def defense_feeding(**overrides: Any) -> DefenseFeedingProfile:
    """A clean DefenseFeedingProfile: both metrics well-sampled and in agreement."""
    base: dict[str, Any] = {
        "defense_score": 3.0, "defense_observation_count": 6,
        "defense_agreement": 0.8, "defense_insufficient_data": False,
        "feeding_score": 2.0, "feeding_observation_count": 5,
        "feeding_agreement": 0.9, "feeding_insufficient_data": False,
        "contributing_sources": ["human_scout"],
    }
    base.update(overrides)
    return DefenseFeedingProfile(**base)


def metrics(
    scoring_profile: ScoringProfile | None = None,
    defense_feeding_profile: DefenseFeedingProfile | None = None,
) -> TeamMetrics:
    return TeamMetrics(
        team_number=1114, event_key="9989zzzquality", season=9989, computed_at=_COMPUTED_AT,
        scoring=scoring_profile or scoring(),
        defense_feeding=defense_feeding_profile or defense_feeding(),
    )


def only(issues: list, field: str | None = None):
    """The single issue recorded, optionally narrowed to one field first."""
    candidates = [issue for issue in issues if field is None or issue.field == field]
    assert len(candidates) == 1, f"expected exactly one issue for {field!r}, got {candidates}"
    return candidates[0]


def fields(issues: list) -> list[str | None]:
    return sorted(issue.field for issue in issues)


# ===========================================================================
# The clean baseline. No database required.
# ===========================================================================


def test_a_high_confidence_metric_trips_nothing():
    assert check_team_metrics(metrics()) == []


def test_a_team_with_no_matches_at_all_is_not_flagged():
    """Zero matches is not a quality problem, it is an empty schedule.

    Every value field is already None, so nothing is being presented as
    confident and there is no false impression to correct -- and during a live
    event this is every team on the board before the first match is played.
    Flagging it would put the entire roster in data_quality_issues on day one.
    """
    empty = ScoringProfile(matches_scheduled=8, matches_used=0)
    unscouted = DefenseFeedingProfile(
        defense_score=None, defense_observation_count=0, defense_agreement=None,
        defense_insufficient_data=True, feeding_score=None, feeding_observation_count=0,
        feeding_agreement=None, feeding_insufficient_data=True, contributing_sources=[],
    )
    assert check_team_metrics(metrics(empty, unscouted)) == []


def test_an_unscouted_team_is_not_flagged_for_having_no_defense_or_feeding_score():
    """insufficient_data is the model reporting no score, not a low-confidence one.

    At a real event most teams have no observations at all, so flagging this
    would write two rows per team per computation and bury the genuine
    findings.
    """
    unscouted = DefenseFeedingProfile(
        defense_score=None, defense_observation_count=0, defense_agreement=None,
        defense_insufficient_data=True, feeding_score=None, feeding_observation_count=0,
        feeding_agreement=None, feeding_insufficient_data=True, contributing_sources=[],
    )
    assert check_team_metrics(metrics(scoring(), unscouted)) == []


# ===========================================================================
# Implausibility rules, each triggered individually.
# ===========================================================================


def test_reliability_score_that_disagrees_with_its_own_counts_is_flagged():
    # 5 of 10 matches recorded defines reliability as 50.0, not 90.0.
    issues = check_team_metrics(metrics(scoring(
        matches_scheduled=10, matches_used=5, reliability_score=90.0,
        good_day_count=1, average_day_count=3, bad_day_count=1,
    )))
    issue = only(issues)
    assert issue.field == "reliability_score"
    assert issue.issue_type == ISSUE_INCONSISTENT_VALUES
    assert issue.severity == SEVERITY_WARNING
    assert "50.0000" in issue.description


def test_perfect_reliability_from_a_tiny_sample_is_flagged():
    """The flagship rule: a maximal claim resting on a sample too small to mean it.

    This rule cannot be triggered in isolation, by construction -- it requires
    matches_used below LOW_SAMPLE_MATCHES, which is exactly the low-sample-size
    rule's own trigger, so both always fire together on the same row. That
    overlap is deliberate and is asserted here rather than worked around: the
    two answer different questions and are reached by different queries
    (field='reliability_score' asks whose reliability number is overclaiming;
    field='matches_used' asks whose statistics rest on too little data), so
    collapsing them would leave the first unanswerable.
    """
    issues = check_team_metrics(metrics(scoring(
        matches_scheduled=2, matches_used=2, reliability_score=100.0,
        good_day_count=0, average_day_count=2, bad_day_count=0,
    )))
    assert fields(issues) == ["matches_used", "reliability_score"]

    issue = only(issues, "reliability_score")
    assert issue.issue_type == ISSUE_IMPLAUSIBLE_VALUE
    assert issue.severity == SEVERITY_WARNING
    assert "perfect 100.0" in issue.description
    assert "2 recorded match(es)" in issue.description


def test_perfect_reliability_from_a_full_schedule_is_not_flagged():
    """The same 100.0, earned over a real schedule, is a genuine result."""
    assert check_team_metrics(metrics(scoring(
        matches_scheduled=12, matches_used=12, reliability_score=100.0,
        good_day_count=2, average_day_count=8, bad_day_count=2,
    ))) == []


def test_perfect_consistency_alongside_real_variance_is_flagged():
    issue = only(check_team_metrics(metrics(scoring(
        consistency_rating=100.0, score_stddev=5.0,
    ))))
    assert issue.field == "consistency_rating"
    assert issue.issue_type == ISSUE_INCONSISTENT_VALUES
    assert issue.severity == SEVERITY_WARNING


def test_imperfect_consistency_alongside_zero_variance_is_flagged():
    # Day counts kept all-average so the zero-variance day-count rule stays quiet
    # and this rule is genuinely the only one firing.
    issue = only(check_team_metrics(metrics(scoring(
        consistency_rating=80.0, score_stddev=0.0,
        good_day_count=0, average_day_count=8, bad_day_count=0,
    ))))
    assert issue.field == "consistency_rating"
    assert issue.issue_type == ISSUE_INCONSISTENT_VALUES


def test_a_good_or_bad_day_alongside_zero_variance_is_flagged():
    issues = check_team_metrics(metrics(scoring(
        score_stddev=0.0, consistency_rating=100.0,
        good_day_count=2, average_day_count=5, bad_day_count=1,
    )))
    assert fields(issues) == ["bad_day_count", "good_day_count"]
    for issue in issues:
        assert issue.issue_type == ISSUE_INCONSISTENT_VALUES
        assert issue.severity == SEVERITY_WARNING


def test_all_average_days_alongside_zero_variance_is_not_flagged():
    """Zero variance means every match must be average -- that is the correct state."""
    assert check_team_metrics(metrics(scoring(
        score_stddev=0.0, consistency_rating=100.0,
        good_day_count=0, average_day_count=8, bad_day_count=0,
    ))) == []


def test_all_average_days_alongside_real_variance_is_not_flagged():
    """The converse does not hold: scores can vary without any clearing a one-stddev cutoff."""
    assert check_team_metrics(metrics(scoring(
        score_stddev=5.0, consistency_rating=90.0,
        good_day_count=0, average_day_count=8, bad_day_count=0,
    ))) == []


def test_a_statistic_missing_despite_enough_matches_is_flagged():
    """The one rule that surfaces live upstream corruption rather than a bad writer.

    consistency_rating returns None above the threshold in exactly one case:
    its out-of-domain guard, which requires a negative score to have reached
    the match history. Today that None is indistinguishable from the ordinary
    "not enough matches yet" None.
    """
    issue = only(check_team_metrics(metrics(scoring(consistency_rating=None))))
    assert issue.field == "consistency_rating"
    assert issue.issue_type == ISSUE_IMPLAUSIBLE_VALUE
    assert issue.severity == SEVERITY_WARNING
    assert "negative score" in issue.description


def test_every_missing_statistic_is_named_separately():
    issues = check_team_metrics(metrics(scoring(
        matches_scheduled=8, matches_used=8, average_score=50.0,
        score_stddev=None, consistency_rating=None, reliability_score=None,
        good_day_count=None, average_day_count=None, bad_day_count=None,
    )))
    assert fields(issues) == [
        "average_day_count", "bad_day_count", "consistency_rating",
        "good_day_count", "reliability_score", "score_stddev",
    ]


def test_statistics_absent_below_the_threshold_are_not_flagged():
    """Below MIN_MATCHES_FOR_STDDEV the Nones are correct, not missing."""
    issues = check_team_metrics(metrics(scoring(
        matches_scheduled=8, matches_used=1, average_score=50.0,
        score_stddev=None, consistency_rating=None, reliability_score=None,
        good_day_count=None, average_day_count=None, bad_day_count=None,
    )))
    # Only the low-sample warning, nothing about the absent statistics.
    assert fields(issues) == ["matches_used"]
    assert only(issues).issue_type == ISSUE_LOW_SAMPLE_SIZE


def test_a_defense_score_below_the_aggregation_minimum_is_flagged():
    """MIN_OBSERVATIONS_FOR_SCORE lives only in the aggregator; the model and the
    CHECK constraint both permit a score from a single observation."""
    issues = check_team_metrics(metrics(
        scoring(), defense_feeding(defense_observation_count=1),
    ))
    # Both the policy-violation rule and the low-sample rule key off the count.
    assert fields(issues) == ["defense_observation_count", "defense_observation_count"]
    types = sorted(issue.issue_type for issue in issues)
    assert types == [ISSUE_INCONSISTENT_VALUES, ISSUE_LOW_SAMPLE_SIZE]
    policy = next(i for i in issues if i.issue_type == ISSUE_INCONSISTENT_VALUES)
    assert str(MIN_OBSERVATIONS_FOR_SCORE) in policy.description


def test_a_score_without_its_agreement_is_flagged():
    issue = only(check_team_metrics(metrics(
        scoring(), defense_feeding(defense_agreement=None),
    )))
    assert issue.field == "defense_agreement"
    assert issue.issue_type == ISSUE_INCONSISTENT_VALUES
    assert "no confidence signal" in issue.description


def test_an_agreement_without_a_score_is_flagged():
    issue = only(check_team_metrics(metrics(scoring(), defense_feeding(
        defense_score=None, defense_observation_count=0,
        defense_agreement=0.5, defense_insufficient_data=True,
    ))))
    assert issue.field == "defense_agreement"
    assert issue.issue_type == ISSUE_INCONSISTENT_VALUES


def test_feeding_is_judged_independently_of_defense():
    """The two aggregate separately, so their confidence can differ for one team."""
    issues = check_team_metrics(metrics(
        scoring(), defense_feeding(feeding_agreement=None),
    ))
    assert fields(issues) == ["feeding_agreement"]


# ===========================================================================
# Low-sample-size / low-confidence rules.
# ===========================================================================


def test_few_matches_is_flagged_as_low_sample_size():
    issue = only(check_team_metrics(metrics(scoring(
        matches_scheduled=8, matches_used=2, reliability_score=25.0,
        good_day_count=0, average_day_count=2, bad_day_count=0,
    ))))
    assert issue.field == "matches_used"
    assert issue.issue_type == ISSUE_LOW_SAMPLE_SIZE
    assert issue.severity == SEVERITY_WARNING


def test_matches_at_the_threshold_are_not_flagged():
    assert check_team_metrics(metrics(scoring(
        matches_scheduled=8, matches_used=LOW_SAMPLE_MATCHES, reliability_score=50.0,
        good_day_count=1, average_day_count=2, bad_day_count=1,
    ))) == []


def test_few_observations_behind_a_reported_score_is_flagged():
    issue = only(check_team_metrics(metrics(
        scoring(), defense_feeding(defense_observation_count=3),
    )))
    assert issue.field == "defense_observation_count"
    assert issue.issue_type == ISSUE_LOW_SAMPLE_SIZE


def test_observations_at_the_threshold_are_not_flagged():
    assert check_team_metrics(metrics(
        scoring(), defense_feeding(defense_observation_count=LOW_SAMPLE_OBSERVATIONS),
    )) == []


def test_low_agreement_is_flagged_even_with_plenty_of_observations():
    """The axis no count can express: many scouts, none of them agreeing."""
    issue = only(check_team_metrics(metrics(
        scoring(), defense_feeding(defense_observation_count=8, defense_agreement=0.2),
    )))
    assert issue.field == "defense_agreement"
    assert issue.issue_type == ISSUE_LOW_SAMPLE_SIZE
    assert issue.severity == SEVERITY_WARNING
    assert "rating tiers" in issue.description


def test_adjacent_tier_disagreement_is_not_flagged():
    """Ratings of 2,3,2,3 score 0.8 agreement -- normal scouting noise, not a finding."""
    assert check_team_metrics(metrics(
        scoring(), defense_feeding(defense_agreement=0.8),
    )) == []


def test_agreement_at_the_threshold_is_not_flagged():
    assert check_team_metrics(metrics(
        scoring(), defense_feeding(defense_agreement=LOW_AGREEMENT),
    )) == []


# ===========================================================================
# Severity policy and the data_quality_issues column convention.
# ===========================================================================


def test_no_rule_can_ever_produce_a_fatal_issue():
    """A metric is untrustworthy, not corrupt. Nothing here may keep it out of the table."""
    everything_wrong = check_team_metrics(metrics(
        scoring(
            matches_scheduled=10, matches_used=2, reliability_score=100.0,
            score_stddev=0.0, consistency_rating=50.0,
            good_day_count=1, average_day_count=0, bad_day_count=1,
        ),
        defense_feeding(defense_observation_count=1, defense_agreement=0.1),
    ))
    assert len(everything_wrong) > 1
    assert all(issue.severity == SEVERITY_WARNING for issue in everything_wrong)
    assert not any(issue.is_fatal for issue in everything_wrong)


def test_issues_carry_the_documented_column_convention():
    issue = only(check_team_metrics(metrics(scoring(consistency_rating=None))))
    assert issue.source == QUALITY_SOURCE == "metrics_compute"
    assert issue.object_type == OBJECT_TYPE_TEAM_METRICS == "team_metrics"
    assert issue.object_id == "1114_9989zzzquality"
    # A team_metrics row has no single originating payload -- its provenance is
    # many-to-one and lives in canonical_lineage, keyed by this same object_id.
    assert issue.raw_payload_id is None


def test_the_issue_object_id_matches_the_lineage_entity_key():
    """Pins the deliberate two-line duplication: compute.py imports this module,
    so importing team_metrics_entity_key back would be circular."""
    assert team_metrics_object_id(1114, "2024casj") == team_metrics_entity_key(1114, "2024casj")


def test_the_metrics_vocabulary_matches_the_pipeline_that_produces_it():
    """One word per entity across the raw rows, the runs, the issues, and the lineage."""
    assert OBJECT_TYPE_TEAM_METRICS == ENTITY_TYPE_TEAM_METRICS
    assert QUALITY_SOURCE == PIPELINE_NAME


def test_the_ingestion_dispatcher_still_refuses_a_team_metrics():
    """Kept separate on purpose: check_entity's closed set is what stops
    data.staging from ever needing to import data.metrics."""
    with pytest.raises(TypeError):
        check_entity(metrics(), source="tba")


def test_thresholds_are_the_documented_values():
    assert LOW_SAMPLE_MATCHES == 4
    assert LOW_SAMPLE_OBSERVATIONS == 4
    assert LOW_AGREEMENT == 0.5
    assert ISSUE_LOW_SAMPLE_SIZE == "low_sample_size"
    # The low-sample band sits strictly above the point where a score stops
    # being reported at all, so the two never mean the same thing.
    assert LOW_SAMPLE_OBSERVATIONS > MIN_OBSERVATIONS_FOR_SCORE
    assert LOW_SAMPLE_MATCHES > MIN_MATCHES_FOR_STDDEV


# ===========================================================================
# Integration: the real compute pipeline against real Postgres.
# ===========================================================================

# Sentinel namespace, distinct from every other module's (9990-9999 are taken).
_S_EVENT = "9989zzzquality"
_S_SEASON = 9989
_S_MATCHES = [f"{_S_EVENT}_qm{n}" for n in range(1, 6)]
_S_TEAM_CLEAN = 989101        # 5 played matches, no scouting -> nothing flagged
_S_TEAM_THIN = 989102         # 2 played matches -> low sample + perfect reliability
_S_TEAM_FEW_OBS = 989103      # 5 matches, 3 agreeing observations -> low sample only
_S_TEAM_DISAGREED = 989104    # 5 matches, 4 wildly split observations -> low agreement only
_S_TEAMS = [_S_TEAM_CLEAN, _S_TEAM_THIN, _S_TEAM_FEW_OBS, _S_TEAM_DISAGREED]

_RED_SCORES = [50, 60, 55, 70, 45]
_BLUE_SCORES = [30, 40, 35, 50, 25]


def _database_available() -> bool:
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(), reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        # Metric issues carry no raw_payload_id, so the raw-payload cascade
        # never reaches them -- but pipeline_run_id is ON DELETE CASCADE and
        # every one of them carries a real run id, so deleting this event's
        # runs reclaims them. Deleted explicitly first anyway, so this teardown
        # does not silently depend on that.
        cursor.execute(
            "DELETE FROM data_quality_issues WHERE object_id LIKE %s", (f"%{_S_EVENT}",),
        )
        cursor.execute("DELETE FROM scouting_observations WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM match_teams WHERE match_key LIKE %s", (f"{_S_EVENT}%",))
        cursor.execute("DELETE FROM matches WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM canonical_lineage WHERE entity_key LIKE %s", (f"%{_S_EVENT}",))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_S_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM pipeline_runs WHERE scope_key = %s", (_S_EVENT,))


def _observe(cursor: Any, match_key: str, team_number: int, scout: str, defense_rating: int) -> None:
    cursor.execute(
        """
        INSERT INTO scouting_observations (
            match_key, event_key, team_number, scout_identifier,
            defense_rating, source, submitted_at
        ) VALUES (%s, %s, %s, %s, %s, 'human_scout', NOW())
        """,
        (match_key, _S_EVENT, team_number, scout, defense_rating),
    )


@pytest.fixture
def database() -> Database:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO events (event_key, season, name) VALUES (%s, %s, %s)",
            (_S_EVENT, _S_SEASON, "Sentinel Metrics Quality Event"),
        )
        for team_number in _S_TEAMS:
            cursor.execute(
                "INSERT INTO teams (team_number, name) VALUES (%s, %s)",
                (team_number, f"Sentinel {team_number}"),
            )
        for index, match_key in enumerate(_S_MATCHES):
            cursor.execute(
                "INSERT INTO matches (match_key, event_key, season, competition_level, "
                "match_number, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s)",
                (match_key, _S_EVENT, _S_SEASON, index + 1, _RED_SCORES[index], _BLUE_SCORES[index]),
            )
            # The thin team plays only the first two matches; everyone else plays all five.
            for team_number in (_S_TEAM_CLEAN, _S_TEAM_FEW_OBS):
                cursor.execute(
                    "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                    (match_key, team_number),
                )
            cursor.execute(
                "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'blue')",
                (match_key, _S_TEAM_DISAGREED),
            )
            if index < 2:
                cursor.execute(
                    "INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                    (match_key, _S_TEAM_THIN),
                )

        # Three agreeing observations: count 3 (below the confidence threshold),
        # agreement ~0.81 (comfortably above it).
        for match_key, rating in zip(_S_MATCHES[:3], (3, 3, 4)):
            _observe(cursor, match_key, _S_TEAM_FEW_OBS, "scout_a", rating)
        # Four observations splitting 0/0/5/5: count 4 (at the threshold, not
        # flagged), agreement 0.0 -- the scouts do not agree at all.
        for match_key, rating in zip(_S_MATCHES[:4], (0, 0, 5, 5)):
            _observe(cursor, match_key, _S_TEAM_DISAGREED, "scout_b", rating)

    try:
        yield db
    finally:
        _cleanup(db)


def _issue_rows(database: Database, team_number: int) -> list[dict[str, Any]]:
    """This event's recorded issues for one team, read back the way a caller would."""
    return DataQualityRecorder(database).open_issues(
        object_type=OBJECT_TYPE_TEAM_METRICS,
        object_id=team_metrics_entity_key(team_number, _S_EVENT),
    )


def _team_metrics_row(database: Database, team_number: int) -> tuple | None:
    with database.cursor() as cursor:
        cursor.execute(
            "SELECT matches_used, matches_scheduled, reliability_score FROM team_metrics "
            "WHERE team_number = %s AND event_key = %s",
            (team_number, _S_EVENT),
        )
        return cursor.fetchone()


@requires_db
def test_a_low_sample_team_is_flagged_as_a_warning_and_still_loaded(database: Database) -> None:
    """The load-bearing severity-as-policy assertion for this milestone.

    A team with two matches is flagged twice and its metrics row is still in
    team_metrics afterwards, holding its real values. A rule that rejected it
    would leave the team with no metrics at all, which is strictly worse than
    a flagged one -- and would make the flag itself a data-loss bug.
    """
    compute_event_team_metrics(_S_EVENT, database=database)

    rows = _issue_rows(database, _S_TEAM_THIN)
    assert sorted(row["field"] for row in rows) == ["matches_used", "reliability_score"]
    assert {row["severity"] for row in rows} == {SEVERITY_WARNING}

    loaded = _team_metrics_row(database, _S_TEAM_THIN)
    assert loaded is not None, "a low-confidence metric must still be loaded, never rejected"
    assert loaded == (2, 2, 100.0)


@requires_db
def test_a_high_confidence_team_records_no_issues(database: Database) -> None:
    compute_event_team_metrics(_S_EVENT, database=database)

    assert _issue_rows(database, _S_TEAM_CLEAN) == []
    assert _team_metrics_row(database, _S_TEAM_CLEAN) is not None


@requires_db
def test_few_observations_are_flagged_through_the_real_aggregation(database: Database) -> None:
    """Three real observations, aggregated for real -- not a hand-built profile."""
    compute_event_team_metrics(_S_EVENT, database=database)

    row = only(_issue_rows(database, _S_TEAM_FEW_OBS))
    assert row["field"] == "defense_observation_count"
    assert row["issue_type"] == ISSUE_LOW_SAMPLE_SIZE
    assert row["severity"] == SEVERITY_WARNING


@requires_db
def test_disagreeing_scouts_are_flagged_even_at_an_adequate_count(database: Database) -> None:
    compute_event_team_metrics(_S_EVENT, database=database)

    row = only(_issue_rows(database, _S_TEAM_DISAGREED))
    assert row["field"] == "defense_agreement"
    assert row["issue_type"] == ISSUE_LOW_SAMPLE_SIZE
    # 0 and 5 ratings split evenly: maximal disagreement on the scale.
    assert "0.00" in row["description"]


@requires_db
def test_issues_are_queryable_from_data_quality_issues_by_the_documented_columns(
    database: Database,
) -> None:
    """The milestone's success criterion, asserted as raw SQL rather than through
    the recorder: a low-confidence metric is findable and distinguishable."""
    result = compute_event_team_metrics(_S_EVENT, database=database)

    with database.cursor() as cursor:
        cursor.execute(
            """
            SELECT object_id, field, issue_type, severity, source, raw_payload_id, pipeline_run_id
            FROM data_quality_issues
            WHERE object_type = %s AND object_id LIKE %s
            ORDER BY object_id, field
            """,
            (OBJECT_TYPE_TEAM_METRICS, f"%{_S_EVENT}"),
        )
        rows = cursor.fetchall()

    assert len(rows) == 4, rows
    assert [row[0] for row in rows] == [
        team_metrics_entity_key(_S_TEAM_THIN, _S_EVENT),
        team_metrics_entity_key(_S_TEAM_THIN, _S_EVENT),
        team_metrics_entity_key(_S_TEAM_FEW_OBS, _S_EVENT),
        team_metrics_entity_key(_S_TEAM_DISAGREED, _S_EVENT),
    ]
    assert all(row[3] == SEVERITY_WARNING for row in rows)
    assert all(row[4] == QUALITY_SOURCE for row in rows)
    assert all(row[5] is None for row in rows), "a computed row names no single raw payload"
    assert all(row[6] == result.run_id for row in rows)


@requires_db
def test_the_compute_run_records_its_quality_summary(database: Database) -> None:
    result = compute_event_team_metrics(_S_EVENT, database=database)
    assert len(result.issues) == 4

    with database.cursor() as cursor:
        cursor.execute("SELECT stage_counts FROM pipeline_runs WHERE id = %s", (result.run_id,))
        stage_counts = cursor.fetchone()[0]

    summary = stage_counts["quality_issues"]
    assert summary["total"] == 4
    assert summary["fatal"] == 0
    assert summary["by_severity"] == {SEVERITY_WARNING: 4}
    assert summary["by_type"] == {ISSUE_LOW_SAMPLE_SIZE: 3, ISSUE_IMPLAUSIBLE_VALUE: 1}


@requires_db
def test_every_rostered_team_is_loaded_regardless_of_its_findings(database: Database) -> None:
    """Four teams in, four rows out. Quality checks annotate; they never gate."""
    result = compute_event_team_metrics(_S_EVENT, database=database)
    assert result.teams_computed == len(_S_TEAMS)

    with database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM team_metrics WHERE event_key = %s", (_S_EVENT,))
        assert cursor.fetchone()[0] == len(_S_TEAMS)


@requires_db
def test_recomputing_records_the_findings_again(database: Database) -> None:
    """One row per detection, matching DataQualityRecorder's existing policy --
    it is what keeps "how long has this been thin" answerable."""
    compute_event_team_metrics(_S_EVENT, database=database)
    compute_event_team_metrics(_S_EVENT, database=database)

    assert len(_issue_rows(database, _S_TEAM_THIN)) == 4  # two findings, twice


@requires_db
def test_deleting_the_run_reclaims_its_metric_issues(database: Database) -> None:
    """Metric issues have no raw_payload_id, so the raw-payload cascade cannot
    reach them -- this pins that the pipeline_run_id cascade does, which is what
    every integration teardown in this repo already relies on."""
    result = compute_event_team_metrics(_S_EVENT, database=database)
    assert _issue_rows(database, _S_TEAM_THIN) != []

    with database.cursor() as cursor:
        cursor.execute("DELETE FROM pipeline_runs WHERE id = %s", (result.run_id,))

    assert _issue_rows(database, _S_TEAM_THIN) == []
