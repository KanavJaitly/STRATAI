"""P10-M2: the read-snapshot fix (`database.connection.read_snapshot`, used by `build_team_features`).

The race it fixes was found by the P10-M2 simulated event:
1. a team's scores and its auto points were read in separate statements, each on its own connection;
2. a sync committing between them made the counts disagree;
3. `TeamFeatures` then failed its own invariant (`auto_points_matches_used` > `matches_used`), and the request
   answered 500.

The race is reproduced **deterministically**. A hook placed exactly between the two reads commits a new completed
match through a separate connection. No sleeps or timing are involved. The same interleaving is run:
- without the snapshot (the pre-fix behaviour), where it must fail;
- with it, where the feature vector is one consistent version.

Everything runs on a **disposable** database (`stratai_test_p10snap_<pid>`), created empty from the isolated
`stratai_test` connection, migrated, seeded with synthetic rows only, and dropped at the end. The test-database
guard allows that name; it is not weakened.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import psycopg
import pytest
from psycopg import sql
from pydantic import ValidationError

from data.config import Settings
from database.connection import Database, DatabaseConfig, SnapshotDatabase, read_snapshot
from database.readonly import ReadOnlySessionDatabase
from ml.features import assembler
from ml.features.assembler import build_team_features
from ml.ratings.provider import StatboticsPointInTimeEpa
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs the isolated stratai_test database")

EVENT, SEASON, TEAM = "2099p10snap", 2099, 990101
OTHERS = [990102, 990103, 990104, 990105, 990106]
T0 = datetime(2099, 3, 1, 9, tzinfo=timezone.utc)
AS_OF = datetime(2099, 3, 2, 9, tzinfo=timezone.utc)  # after every seeded and inserted match


def _with_db(url: str, name: str) -> str:
    return url.rsplit("/", 1)[0] + "/" + name


@pytest.fixture(scope="module")
def snapdb() -> Generator[Database, None, None]:
    """A disposable, migrated database with one synthetic event: 4 completed matches for TEAM."""
    from database.migrate import run_migrations

    source = str(Settings().database_url)
    name = f"stratai_test_p10snap_{os.getpid()}"
    url = _with_db(source, name)
    with psycopg.connect(source, autocommit=True) as admin:  # the guard allows this; CREATE DATABASE works from it
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        run_migrations(Settings(database_url=url))
        database = Database(DatabaseConfig(url))
        with database.cursor() as c:
            c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'P10 snapshot', %s)",
                      (EVENT, SEASON, (T0 + timedelta(days=2)).date()))
            c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * 6),
                      [v for t in [TEAM, *OTHERS] for v in (t, f"Synthetic {t}")])
        for i in range(1, 5):
            insert_completed_match(url, i)
        yield database
    finally:
        with psycopg.connect(source, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def insert_completed_match(url: str, number: int) -> None:
    """One completed qualification match with TEAM on red, its canonical rows and its raw TBA payload, committed by
    its own connection (what a sync commit does)."""
    key = f"{EVENT}_qm{number}"
    with psycopg.connect(url) as conn:
        conn.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                     "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, %s, %s)",
                     (key, EVENT, SEASON, number, T0 + timedelta(minutes=10 * number), 40 + number, 30))
        for team, colour in zip([TEAM, *OTHERS], ["red"] * 3 + ["blue"] * 3):
            conn.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                         (key, team, colour))
        conn.execute("INSERT INTO raw_source_payloads (source, source_object_type, source_object_id, event_key, "
                     "match_key, payload_json, payload_checksum) VALUES ('tba', 'match', %s, %s, %s, %s, %s)",
                     (key, EVENT, key, psycopg.types.json.Jsonb({"score_breakdown": {"red": {"autoPoints": 10},
                                                                                     "blue": {"autoPoints": 5}}}),
                      f"p10snap-{key}"))


@pytest.fixture
def fixed_auto_points(monkeypatch):
    """Auto points of any present breakdown are 10 (the season adapter is not under test here), so every completed
    match contributes to both counts and they must be equal in a consistent read."""
    monkeypatch.setattr(assembler, "auto_points", lambda season, breakdown: 10.0)


def features(database: Database):
    return build_team_features(database, TEAM, EVENT, AS_OF, epa_provider=StatboticsPointInTimeEpa(database))


def _remove_matches_from(url: str, first: int) -> None:
    with psycopg.connect(url) as conn:
        keys = [f"{EVENT}_qm{n}" for n in range(first, 200)]
        conn.execute("DELETE FROM raw_source_payloads WHERE source_object_id = ANY(%s)", (keys,))
        conn.execute("DELETE FROM match_teams WHERE match_key = ANY(%s)", (keys,))
        conn.execute("DELETE FROM matches WHERE match_key = ANY(%s)", (keys,))


@pytest.fixture
def url(snapdb) -> Generator[str, None, None]:
    yield snapdb._config.database_url
    _remove_matches_from(snapdb._config.database_url, 5)  # every test starts from the 4 seeded matches


def _commit_between_the_two_reads(monkeypatch, url: str, number: int) -> list[int]:
    """The deterministic barrier: after the scores are read and before the auto points are, a new completed match
    is committed by another connection."""
    original = assembler._point_in_time_scores
    fired: list[int] = []

    def scores_then_commit(*args, **kwargs):
        result = original(*args, **kwargs)
        if not fired:
            insert_completed_match(url, number)
            fired.append(number)
        return result

    monkeypatch.setattr(assembler, "_point_in_time_scores", scores_then_commit)
    return fired


@contextmanager
def _no_snapshot(database):  # the pre-fix behaviour: every statement on its own connection
    yield database


# --- the race, reproduced and fixed --------------------------------------------------------------------------------


def test_without_the_snapshot_a_commit_between_the_reads_breaks_the_feature_invariant(snapdb, url, monkeypatch,
                                                                                         fixed_auto_points):
    """This is the original bug, reproduced deterministically: the test fails against the pre-fix implementation."""
    monkeypatch.setattr(assembler, "read_snapshot", _no_snapshot)
    fired = _commit_between_the_two_reads(monkeypatch, url, 5)
    with pytest.raises(ValidationError, match="auto_points_matches_used"):
        features(snapdb)
    assert fired == [5]  # the interleaving really happened


def test_with_the_snapshot_the_same_interleaving_gives_one_consistent_version(snapdb, url, monkeypatch,
                                                                             fixed_auto_points):
    fired = _commit_between_the_two_reads(monkeypatch, url, 5)
    during = features(snapdb)
    assert fired == [5]
    # every count and value comes from the state before the commit (4 matches), none from after (5)
    assert (during.matches_used, during.matches_considered, during.auto_points_matches_used) == (4, 4, 4)
    assert during.average_score == pytest.approx((41 + 42 + 43 + 44) / 4)
    monkeypatch.undo()
    monkeypatch.setattr(assembler, "auto_points", lambda season, breakdown: 10.0)
    after = features(snapdb)  # a later read sees the commit, consistently
    assert (after.matches_used, after.matches_considered, after.auto_points_matches_used) == (5, 5, 5)


def test_normal_reads_are_unchanged_by_the_snapshot(snapdb, url, monkeypatch, fixed_auto_points):
    """Values, types, order and absences are the same with and without the snapshot when nothing is committing."""
    with_snapshot = features(snapdb).model_dump()
    monkeypatch.setattr(assembler, "read_snapshot", _no_snapshot)
    without = features(snapdb).model_dump()
    assert with_snapshot == without
    assert with_snapshot["defense_score"] is None and with_snapshot["defense_score_present"] is False
    assert with_snapshot["epa_total_present"] is False  # no EPA rows: an absence, never a 0


# --- the snapshot itself --------------------------------------------------------------------------------------------


def _count(database) -> int:
    with database.cursor() as c:
        c.execute("SELECT count(*) FROM matches WHERE event_key = %s", (EVENT,))
        return c.fetchone()[0]


def test_a_snapshot_sees_one_state_while_another_connection_commits(snapdb, url):
    with read_snapshot(snapdb) as snapshot:
        assert isinstance(snapshot, SnapshotDatabase)
        before = _count(snapshot)
        insert_completed_match(url, 6)  # committed by another connection, while the snapshot is open
        assert _count(snapshot) == before  # repeatable read: the commit is invisible inside the snapshot
        assert _count(snapdb) == before + 1  # a plain read sees it
    with read_snapshot(snapdb) as later:
        assert _count(later) == before + 1


def test_a_writer_is_never_blocked_by_an_open_snapshot(snapdb, url):
    with read_snapshot(snapdb) as snapshot:
        _count(snapshot)  # the snapshot holds its read locks now
        with psycopg.connect(url) as writer:
            writer.execute("SET lock_timeout = '2s'")  # a blocked write would fail here instead of waiting
            writer.execute("UPDATE matches SET score_blue = score_blue WHERE event_key = %s", (EVENT,))
            writer.commit()


def test_a_snapshot_is_read_only(snapdb, url):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with read_snapshot(snapdb) as snapshot:
            with snapshot.cursor() as c:
                c.execute("DELETE FROM matches WHERE event_key = %s", (EVENT,))
    assert _count(snapdb) == 4


def _sessions(url: str) -> list[tuple[str, str]]:
    with psycopg.connect(url, autocommit=True) as probe:
        return probe.execute("SELECT state, coalesce(left(query, 60), '') FROM pg_stat_activity "
                             "WHERE datname = current_database() AND pid <> pg_backend_pid()").fetchall()


def test_an_error_inside_a_snapshot_leaks_no_connection_or_open_transaction(snapdb, url):
    held: list[SnapshotDatabase] = []
    with pytest.raises(RuntimeError):
        with read_snapshot(snapdb) as snapshot:
            held.append(snapshot)
            _count(snapshot)
            raise RuntimeError("boom")
    assert held[0]._conn.closed
    with pytest.raises(psycopg.errors.UndefinedTable):
        with read_snapshot(snapdb) as snapshot:
            held.append(snapshot)
            with snapshot.cursor() as c:
                c.execute("SELECT * FROM no_such_table")
    assert held[1]._conn.closed
    assert _sessions(url) == []  # no idle-in-transaction session, no connection left behind


def test_a_snapshot_is_reused_and_other_databases_pass_through(snapdb, url):
    with read_snapshot(snapdb) as outer:
        with read_snapshot(outer) as inner:
            assert inner is outer  # a nested build reuses the same snapshot: still one version
    session = ReadOnlySessionDatabase(snapdb._config)
    try:
        with read_snapshot(session) as passed:
            assert passed is session  # a batch job's read-only session manages its own connection
    finally:
        session.close()


# --- concurrent readers and a committing writer --------------------------------------------------------------------


def test_concurrent_feature_reads_during_a_stream_of_commits_are_always_one_version(snapdb, url, fixed_auto_points):
    """Readers build features continuously while a writer commits 25 matches, one transaction each. Every vector
    must be internally consistent, and its count must be one the database actually passed through. The writer
    never waits for a reader."""
    start, done = threading.Barrier(5), threading.Event()
    seen: list[tuple[int, int, int]] = []
    errors: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        start.wait()
        while not done.is_set():
            try:
                f = features(snapdb)
            except Exception as exc:  # any invariant failure or crash is a finding
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}"[:200])
                return
            with lock:
                seen.append((f.matches_used, f.matches_considered, f.auto_points_matches_used))

    def writer() -> None:
        start.wait()
        try:
            for number in range(10, 35):
                insert_completed_match(url, number)
        finally:
            done.set()

    threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    assert not any(thread.is_alive() for thread in threads), "a reader or the writer hung"
    assert errors == []
    assert seen, "no reader completed a build"
    assert all(used == considered == auto for used, considered, auto in seen)  # one version per vector
    assert {used for used, _, _ in seen} <= set(range(4, 30))  # 4 seeded + up to 25 committed
    assert features(snapdb).matches_used == 29


# --- review P10-R1: one response is one version, and nothing inside can end the snapshot -----------------------------


def _strength(database, build=None):
    from ml.views.strength import build_team_strength

    build = build or build_team_strength
    return build(database, TEAM, EVENT, AS_OF, epa_provider=StatboticsPointInTimeEpa(database))


def _commit_after_the_features_are_built(monkeypatch, url: str, number: int) -> list[int]:
    """The deterministic barrier for the view: the view's own later reads (day counts, season auto points) run
    after a commit that the feature build did not see."""
    from ml.views import strength

    original = strength.build_team_features
    fired: list[int] = []

    def features_then_commit(*args, **kwargs):
        result = original(*args, **kwargs)
        if not fired:
            insert_completed_match(url, number)
            fired.append(number)
        return result

    monkeypatch.setattr(strength, "build_team_features", features_then_commit)
    return fired


def _day_total(view) -> float:
    s = view.scoring
    return s.good_day_count.value + s.average_day_count.value + s.bad_day_count.value


def test_without_one_snapshot_the_strength_view_mixes_two_versions(snapdb, url, monkeypatch, fixed_auto_points):
    """Review P10-R1: before `consistent_reads`, the view re-read the scores outside the feature snapshot."""
    from ml.views.strength import build_team_strength

    fired = _commit_after_the_features_are_built(monkeypatch, url, 5)
    view = _strength(snapdb, build_team_strength.__wrapped__)  # the undecorated view: the pre-fix behaviour
    assert fired == [5]
    assert view.scoring.average_score.n == 4 and _day_total(view) == 5  # two versions in one response


def test_with_one_snapshot_the_strength_view_is_one_version(snapdb, url, monkeypatch, fixed_auto_points):
    fired = _commit_after_the_features_are_built(monkeypatch, url, 5)
    view = _strength(snapdb)
    assert fired == [5]
    assert view.scoring.average_score.n == 4 and _day_total(view) == 4
    [this_event] = [e for e in view.auto_points.season_by_event if e.event_key == EVENT]
    assert this_event.average_auto_points.n == view.auto_points.this_event.n == 4


def test_a_commit_or_rollback_by_code_inside_a_snapshot_cannot_end_it(snapdb, url):
    """Some readers end their read transaction explicitly (`conn.rollback()`). Inside a snapshot that would silently
    start a new version; the held connection ignores it."""
    with read_snapshot(snapdb) as snapshot:
        before = _count(snapshot)
        with snapshot.connection() as conn:
            conn.rollback()
            conn.commit()
        insert_completed_match(url, 7)
        assert _count(snapshot) == before
