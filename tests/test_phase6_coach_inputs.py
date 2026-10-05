"""P6-M9 coach inputs: raw-first landing, validation, point-in-time loading. Isolated database only; synthetic
event keys (`t-p6-coach-*`), cleaned up before and after. Synthetic fixtures, not evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.strategy.coach_inputs import (COACH_SOURCE, CoachInputError, load_coach_observations,
                                      submit_coach_observation, submit_coach_strategy)
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_test database")

EVENT = "t-p6-coach-event"
T0 = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def database():
    db = Database(DatabaseConfig(Settings().database_url))

    def cleanup():
        with db.cursor() as c:
            c.execute("DELETE FROM raw_source_payloads WHERE source = %s AND payload_json->>'event_key' = %s",
                      (COACH_SOURCE, EVENT))

    cleanup()
    yield db
    cleanup()


def _raw_count(db) -> int:
    with db.cursor() as c:
        c.execute("SELECT count(*) FROM raw_source_payloads WHERE source = %s AND payload_json->>'event_key' = %s",
                  (COACH_SOURCE, EVENT))
        return c.fetchone()[0]


def test_strategy_lands_raw_first_and_provenance_stays_outside(database):
    record = submit_coach_strategy(database, {"event_key": EVENT, "author": "Coach A",
                                              "strategy": {"robots": [{"team_number": n} for n in (1, 2, 3)]}},
                                   now=T0)
    assert record.provenance.origin == "human_entered" and record.provenance.author == "Coach A"
    assert record.strategy.is_baseline() and _raw_count(database) == 1


def test_invalid_strategy_is_landed_but_refused(database):
    with pytest.raises(CoachInputError) as error:
        submit_coach_strategy(database, {"event_key": EVENT, "author": "Coach A",
                                         "strategy": {"robots": [{"team_number": 1, "role": "defense"}]}}, now=T0)
    assert error.value.problems and _raw_count(database) == 1


def test_observations_are_point_in_time_and_drop_free_text(database):
    base = {"event_key": EVENT, "team_number": 254, "kind": "component_unavailable", "component": "endgame",
            "observer": "Coach B"}
    submit_coach_observation(database, {**base, "observed_at": T0.isoformat(), "note": "climber bent, free text"})
    submit_coach_observation(database, {**base, "observed_at": (T0 + timedelta(hours=2)).isoformat()})
    with pytest.raises(CoachInputError):
        submit_coach_observation(database, {**base, "kind": "robot_unavailable", "observed_at": T0.isoformat()})
    before, invalid = load_coach_observations(database, EVENT, T0 + timedelta(hours=1))
    assert len(before) == 1 and invalid == 1
    assert not hasattr(before[0], "note")
    later, _ = load_coach_observations(database, EVENT, T0 + timedelta(hours=3))
    assert len(later) == 2
    nothing, _ = load_coach_observations(database, EVENT, T0)
    assert nothing == ()  # strictly before as_of
