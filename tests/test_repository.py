from __future__ import annotations

import pytest

from data.config import Settings
from data.serving.repository import CanonicalRepository
from data.staging import (
    PayloadValidationError,
    StagingEvent,
    StagingMatch,
    StagingTeam,
    StagingTeamEventStats,
    normalize_team_event_stats,
)
from database.connection import Database, DatabaseConfig

# ---------------------------------------------------------------------------
# Sample staging entities shared across unit and integration tests.
# ---------------------------------------------------------------------------

SAMPLE_TEAMS = [
    StagingTeam(team_number=1114, name="Simbotics", city="St. Catharines",
                state_province="Ontario", country="Canada", rookie_year=2003),
    StagingTeam(team_number=254, name="The Cheesy Poofs", city="San Jose",
                state_province="CA", country="USA", rookie_year=1999),
    StagingTeam(team_number=604, name="Quixilver"),
    StagingTeam(team_number=118, name="Robonauts"),
    StagingTeam(team_number=330, name="Beach Bots"),
    StagingTeam(team_number=973, name="Greybots"),
]

SAMPLE_EVENT = StagingEvent(
    event_key="2024casj", name="Silicon Valley Regional", season=2024,
    event_code="casj", city="San Jose", state_province="CA", country="USA",
)

SAMPLE_MATCH = StagingMatch(
    match_key="2024casj_qm1", event_key="2024casj", season=2024,
    competition_level="qualification", match_number=1,
    red_teams=[1114, 254, 604], blue_teams=[118, 330, 973],
    red_score=100, blue_score=90, winning_alliance="red",
)

SAMPLE_STATS = StagingTeamEventStats(
    team_number=1114, event_key="2024casj", season=2024,
    epa_total=55.5, epa_auto=15.0, epa_teleop=30.0, epa_endgame=10.5,
    wins=8, losses=2, ties=0, matches_played=10,
)


# ===========================================================================
# Unit tests: verify the generated SQL / upsert behaviour with no database.
# ===========================================================================

class RecordingCursor:
    def __init__(self, sink: list[tuple[str, tuple | None]]) -> None:
        self.sink = sink

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.sink.append((query, params))

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


class RecordingConnection:
    def __init__(self, sink: list[tuple[str, tuple | None]]) -> None:
        self.sink = sink
        self.commits = 0

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.sink)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


def _recording_repo(monkeypatch) -> tuple[CanonicalRepository, list[tuple[str, tuple | None]]]:
    sink: list[tuple[str, tuple | None]] = []
    monkeypatch.setattr(
        "database.connection.psycopg.connect",
        lambda *_a, **_kw: RecordingConnection(sink),
    )
    repo = CanonicalRepository(Database(DatabaseConfig("postgresql://u:p@localhost:5432/db")))
    return repo, sink


def _find(sink, needle: str) -> tuple[str, tuple | None]:
    for query, params in sink:
        if needle in query:
            return query, params
    raise AssertionError(f"No executed statement containing {needle!r}")


def test_load_team_upserts_on_team_number(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    repo.load_team(SAMPLE_TEAMS[0])

    query, params = _find(sink, "INSERT INTO teams")
    assert "ON CONFLICT (team_number) DO UPDATE" in query
    assert params == (1114, "Simbotics", "St. Catharines", "Ontario", "Canada", 2003)


def test_load_event_maps_state_province_to_state_prov(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    repo.load_event(SAMPLE_EVENT)

    query, params = _find(sink, "INSERT INTO events")
    assert "ON CONFLICT (event_key) DO UPDATE" in query
    # params order: event_key, season, name, event_code, start_date, end_date, city, state_prov, country
    assert params[0] == "2024casj"
    assert params[7] == "CA"  # staging.state_province -> column state_prov


def test_load_match_upserts_match_and_synthesizes_junction_rows(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    repo.load_match(SAMPLE_MATCH)

    match_query, match_params = _find(sink, "INSERT INTO matches")
    assert "ON CONFLICT (match_key) DO UPDATE" in match_query
    # red_score -> score_red (position 7), blue_score -> score_blue (position 8)
    assert match_params[0] == "2024casj_qm1"
    assert match_params[7] == 100
    assert match_params[8] == 90

    junction = [(q, p) for q, p in sink if "INSERT INTO match_teams" in q]
    assert len(junction) == 6
    assert all("ON CONFLICT (match_key, team_number) DO UPDATE" in q for q, _ in junction)

    # Roster mapping: red teams stations 1-3, blue teams stations 1-3.
    rows = [p for _, p in junction]
    assert (("2024casj_qm1", 1114, "red", 1)) in rows
    assert (("2024casj_qm1", 604, "red", 3)) in rows
    assert (("2024casj_qm1", 118, "blue", 1)) in rows
    assert (("2024casj_qm1", 973, "blue", 3)) in rows

    prune_query, prune_params = _find(sink, "DELETE FROM match_teams")
    assert prune_params == ("2024casj_qm1", [1114, 254, 604, 118, 330, 973])


def test_load_match_prune_handles_empty_roster(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    repo.load_match(StagingMatch(
        match_key="2024casj_qm2", event_key="2024casj", season=2024,
        competition_level="qualification", match_number=2,
    ))

    assert not any("INSERT INTO match_teams" in q for q, _ in sink)
    _, prune_params = _find(sink, "DELETE FROM match_teams")
    assert prune_params == ("2024casj_qm2", [])


def test_load_team_event_stats_upserts_on_composite_key(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    repo.load_team_event_stat(SAMPLE_STATS)

    query, params = _find(sink, "INSERT INTO team_event_stats")
    assert "ON CONFLICT (team_number, event_key) DO UPDATE" in query
    assert params[0] == 1114
    assert params[1] == "2024casj"
    assert params[10] == 10  # matches_played


def test_load_all_respects_foreign_key_ordering(monkeypatch):
    repo, sink = _recording_repo(monkeypatch)
    counts = repo.load_all(
        teams=SAMPLE_TEAMS, events=[SAMPLE_EVENT],
        matches=[SAMPLE_MATCH], team_event_stats=[SAMPLE_STATS],
    )

    assert counts == {"teams": 6, "events": 1, "matches": 1, "team_event_stats": 1}

    order = [q for q, _ in sink]
    first_team = next(i for i, q in enumerate(order) if "INSERT INTO teams" in q)
    first_event = next(i for i, q in enumerate(order) if "INSERT INTO events" in q)
    first_match = next(i for i, q in enumerate(order) if "INSERT INTO matches" in q)
    first_stats = next(i for i, q in enumerate(order) if "INSERT INTO team_event_stats" in q)
    assert first_team < first_match
    assert first_event < first_match
    assert first_team < first_stats
    assert first_event < first_stats


def test_load_batch_stops_after_failure_and_preserves_earlier_records(monkeypatch, caplog):
    sink: list[tuple[str, tuple | None]] = []

    class RaisingCursor(RecordingCursor):
        def execute(self, query: str, params: tuple | None = None) -> None:
            super().execute(query, params)
            if params and params[0] == 254:
                raise RuntimeError("simulated upsert failure")

    class RaisingConnection(RecordingConnection):
        def cursor(self) -> RecordingCursor:
            return RaisingCursor(self.sink)

    monkeypatch.setattr("database.connection.psycopg.connect", lambda *_a, **_kw: RaisingConnection(sink))
    repo = CanonicalRepository(Database(DatabaseConfig("postgresql://u:p@localhost:5432/db")))

    with caplog.at_level("ERROR", logger="data.serving.repository"):
        with pytest.raises(RuntimeError, match="simulated upsert failure"):
            repo.load_teams(SAMPLE_TEAMS)  # team 1114 ok, team 254 raises, rest never attempted

    inserted_team_numbers = [p[0] for q, p in sink if "INSERT INTO teams" in q]
    assert inserted_team_numbers == [1114, 254]  # 604 and onward never attempted
    assert "load_team stopped after 1 record" in caplog.text
    assert "254" in caplog.text


# ===========================================================================
# Statbotics -> StagingTeamEventStats normalization (the M7 stats source).
# ===========================================================================

def test_normalize_statbotics_team_event_stats_derives_matches_played():
    # No sourced count in this payload, so the W/L/T fallback is used.
    stats = normalize_team_event_stats("statbotics", {
        "team": 1114, "event": "2024casj",
        "epa_total": 55.5, "epa_auto": 15.0, "epa_teleop": 30.0, "epa_endgame": 10.5,
        "wins": 8, "losses": 2, "ties": 1,
    })
    assert isinstance(stats, StagingTeamEventStats)
    assert stats.team_number == 1114
    assert stats.season == 2024  # derived from the event key
    assert stats.matches_played == 11  # 8 + 2 + 1


def test_normalize_statbotics_prefers_the_sourced_match_count():
    # Statbotics does report a played-match count; prefer it over the derived sum.
    # The two disagree here only to prove which one wins.
    stats = normalize_team_event_stats("statbotics", {
        "team": 1114, "event": "2024casj", "epa_total": 55.5,
        "wins": 8, "losses": 2, "ties": 1, "count": 12,
    })
    assert stats.matches_played == 12


def test_normalize_statbotics_reads_the_real_nested_payload_shape():
    # Statbotics's actual /team_event response nests EPA under epa/epa.breakdown
    # and the record under record.total. The whole chain -- flattening model,
    # normalizer, staging entity -- must survive that shape.
    stats = normalize_team_event_stats("statbotics", {
        "team": 254, "year": 2024, "event": "2024casj", "team_name": "The Cheesy Poofs",
        "epa": {
            "total_points": 61.42,
            "breakdown": {"auto_points": 18.31, "teleop_points": 34.07, "endgame_points": 9.04},
            "stats": {"mean": 58.44},
        },
        "record": {
            "qual": {"wins": 9, "losses": 3, "ties": 0, "count": 12},
            "total": {"wins": 13, "losses": 5, "ties": 0, "count": 18},
        },
    })

    assert isinstance(stats, StagingTeamEventStats)
    assert (stats.team_number, stats.event_key, stats.season) == (254, "2024casj", 2024)
    assert stats.epa_total == 61.42
    assert (stats.epa_auto, stats.epa_teleop, stats.epa_endgame) == (18.31, 34.07, 9.04)
    assert (stats.wins, stats.losses, stats.ties) == (13, 5, 0)  # total, not qual
    assert stats.matches_played == 18


def test_normalize_statbotics_team_event_stats_omits_matches_played_when_incomplete():
    stats = normalize_team_event_stats("statbotics", {
        "team": 254, "event": "2024casj", "epa_total": 60.0, "wins": 8,
    })
    assert stats.matches_played is None


def test_normalize_statbotics_team_event_stats_rejects_malformed_event_key():
    with pytest.raises(PayloadValidationError):
        normalize_team_event_stats("statbotics", {"team": 1114, "event": "casj"})


def test_normalize_team_event_stats_unregistered_source_raises():
    with pytest.raises(ValueError, match="No team_event_stats normalizer"):
        normalize_team_event_stats("nope", {"team": 1114, "event": "2024casj"})


# ===========================================================================
# Integration tests: real upsert/idempotence/constraint behaviour.
# Auto-skips when no PostgreSQL is reachable via the configured DATABASE_URL.
# ===========================================================================

# Sentinel keys namespaced so integration runs never touch real competition data.
_S_EVENT = "9999zzztest"
_S_TEAMS = [990001, 990002, 990003, 990004, 990005, 990006]
_S_MATCH = "9999zzztest_qm1"


def _database_available() -> bool:
    try:
        import psycopg

        settings = Settings()
        with psycopg.connect(str(settings.database_url), connect_timeout=3):
            return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="Requires a reachable PostgreSQL database via DATABASE_URL",
)


def _integration_teams() -> list[StagingTeam]:
    return [StagingTeam(team_number=n, name=f"Sentinel {n}") for n in _S_TEAMS]


def _integration_event() -> StagingEvent:
    return StagingEvent(event_key=_S_EVENT, name="Sentinel Event", season=9999)


def _integration_match(**overrides) -> StagingMatch:
    base = dict(
        match_key=_S_MATCH, event_key=_S_EVENT, season=9999,
        competition_level="qualification", match_number=1,
        red_teams=_S_TEAMS[:3], blue_teams=_S_TEAMS[3:],
        red_score=100, blue_score=90, winning_alliance="red",
    )
    base.update(overrides)
    return StagingMatch(**base)


def _cleanup(database: Database) -> None:
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM match_teams WHERE match_key = %s", (_S_MATCH,))
        cursor.execute("DELETE FROM team_event_stats WHERE event_key = %s", (_S_EVENT,))
        cursor.execute("DELETE FROM matches WHERE match_key = %s", (_S_MATCH,))
        cursor.execute("DELETE FROM teams WHERE team_number = ANY(%s::int[])", (_S_TEAMS,))
        cursor.execute("DELETE FROM events WHERE event_key = %s", (_S_EVENT,))


@pytest.fixture
def repo() -> CanonicalRepository:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    database = Database(DatabaseConfig(settings.database_url))
    _cleanup(database)
    try:
        yield CanonicalRepository(database)
    finally:
        _cleanup(database)


@requires_db
def test_load_all_persists_canonical_state(repo):
    repo.load_all(
        teams=_integration_teams(), events=[_integration_event()],
        matches=[_integration_match()],
        team_event_stats=[StagingTeamEventStats(
            team_number=990001, event_key=_S_EVENT, season=9999,
            epa_total=50.0, wins=8, losses=2, ties=0, matches_played=10,
        )],
    )

    with repo.database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (_S_TEAMS,))
        assert cursor.fetchone()[0] == 6
        cursor.execute("SELECT winning_alliance FROM matches WHERE match_key = %s", (_S_MATCH,))
        assert cursor.fetchone()[0] == "red"
        cursor.execute("SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (_S_MATCH,))
        assert cursor.fetchone()[0] == 6
        cursor.execute(
            "SELECT alliance_color, station_position FROM match_teams "
            "WHERE match_key = %s AND team_number = %s",
            (_S_MATCH, 990001),
        )
        assert cursor.fetchone() == ("red", 1)
        cursor.execute(
            "SELECT matches_played FROM team_event_stats WHERE team_number = %s AND event_key = %s",
            (990001, _S_EVENT),
        )
        assert cursor.fetchone()[0] == 10


@requires_db
def test_repeated_load_is_idempotent_and_reflects_updates(repo):
    teams = _integration_teams()
    repo.load_all(teams=teams, events=[_integration_event()], matches=[_integration_match()])

    # Re-load with a changed team name and a corrected match score.
    teams[0] = StagingTeam(team_number=990001, name="Renamed Sentinel")
    repo.load_all(teams=teams, events=[_integration_event()],
                  matches=[_integration_match(red_score=111)])

    with repo.database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM teams WHERE team_number = ANY(%s::int[])", (_S_TEAMS,))
        assert cursor.fetchone()[0] == 6  # no duplicates
        cursor.execute("SELECT COUNT(*) FROM match_teams WHERE match_key = %s", (_S_MATCH,))
        assert cursor.fetchone()[0] == 6  # junction not duplicated
        cursor.execute("SELECT name FROM teams WHERE team_number = %s", (990001,))
        assert cursor.fetchone()[0] == "Renamed Sentinel"  # update reflected
        cursor.execute("SELECT score_red FROM matches WHERE match_key = %s", (_S_MATCH,))
        assert cursor.fetchone()[0] == 111  # update reflected


@requires_db
def test_match_with_unknown_event_key_violates_foreign_key(repo):
    import psycopg

    repo.load_teams(_integration_teams())  # teams present, event deliberately absent
    with pytest.raises(psycopg.errors.IntegrityError):
        repo.load_match(_integration_match(event_key="9999nonexistent"))


@requires_db
def test_match_with_unknown_team_number_violates_foreign_key(repo):
    import psycopg

    repo.load_events([_integration_event()])
    repo.load_teams(_integration_teams()[:5])  # only 5 of 6 rostered teams exist
    with pytest.raises(psycopg.errors.IntegrityError):
        repo.load_match(_integration_match())  # references missing team 990006


@requires_db
def test_team_event_stats_with_unknown_team_violates_foreign_key(repo):
    import psycopg

    repo.load_events([_integration_event()])  # event exists, team does not
    with pytest.raises(psycopg.errors.IntegrityError):
        repo.load_team_event_stat(StagingTeamEventStats(
            team_number=990001, event_key=_S_EVENT, season=9999,
        ))
