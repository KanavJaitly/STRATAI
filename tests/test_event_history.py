"""EventHistory and the prefetched Statbotics EPA give exactly the per-team reads' features (no leakage either way).

The qualification forecast reads an event's rows once (ml.features.assembler.EventHistory) and every team's EPA
candidates once (ml.ratings.provider.PrefetchedStatboticsEpa), then applies each match's own as_of in Python
(2026-11-16: ~3,400 queries per forecast became ~270). These tests reuse the leakage fixtures of
tests/test_ml_features_assembler.py: a future match, a late scouting submission, an EPA row at a not-yet-concluded
event, and same-event EPA. They rerun that module's leakage tests through the new path and compare both paths at
instants before, at, between and after every match.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import tests.test_ml_features_assembler as base
from database.connection import Database
from ml.features.assembler import EventHistory, build_match_feature_row
from ml.features.scale import ScaleLookup
from ml.ratings.provider import Unavailable, StatboticsPointInTimeEpa
from tests.test_ml_features_assembler import (  # noqa: F401  (pytest fixtures)
    _statbotics_reference_epa_source,
    database,
    requires_db,
)

_MATCHES = [base._QM1, base._QM2, base._QM3, base._QM4, base._QM_IRREGULAR]
_INSTANTS = [base._T0 - timedelta(hours=1), base._T0, base._T1, base._AS_OF, base._T3,
             base._T3 + timedelta(days=30), datetime(2026, 2, 1, tzinfo=timezone.utc),
             datetime(2026, 4, 2, tzinfo=timezone.utc)]


def _through_history(database: Database, match_key: str, as_of: datetime, **kwargs):
    history = EventHistory.read(database, base._EVENT_TARGET)
    provider = StatboticsPointInTimeEpa(database).prefetched(base._ALL_TEAMS)
    return build_match_feature_row(database, match_key, as_of, epa_provider=provider, history=history, **kwargs)


@requires_db
@pytest.mark.parametrize("match_key", _MATCHES)
def test_both_paths_give_identical_rows_at_every_instant(database: Database, match_key: str) -> None:
    scales = ScaleLookup(database)
    for as_of in _INSTANTS:
        plain = build_match_feature_row(database, match_key, as_of,
                                        epa_provider=StatboticsPointInTimeEpa(database), scale_lookup=scales)
        assert _through_history(database, match_key, as_of, scale_lookup=scales) == plain, (match_key, as_of)


@requires_db
@pytest.mark.parametrize("name", [
    "test_no_match_at_or_after_as_of_contributes_to_scoring",
    "test_defense_score_excludes_both_future_match_and_late_submission",
    "test_feeding_absent_for_a_team_with_only_defense_ratings",
    "test_team_with_zero_scouting_observations_is_missing_not_zero",
    "test_sentinel_collision_zero_defense_rating_is_a_real_value_not_absence",
    "test_epa_uses_prior_concluded_event_never_the_same_event",
    "test_epa_withheld_when_no_team_event_stats_row_exists_at_all",
    "test_epa_withheld_when_the_only_row_is_at_a_not_yet_concluded_event",
])
def test_the_leakage_tests_pass_through_the_history_path(database: Database, monkeypatch, name: str) -> None:
    monkeypatch.setattr(base, "build_match_feature_row", _through_history)
    getattr(base, name)(database)


@requires_db
def test_history_refuses_another_event(database: Database) -> None:
    history = EventHistory.read(database, base._EVENT_TARGET)
    with pytest.raises(ValueError):
        history.score_rows(base._TEAM_A, base._EVENT_CONCLUDED, base._AS_OF)


@requires_db
def test_prefetched_epa_refuses_a_team_it_did_not_read(database: Database) -> None:
    provider = StatboticsPointInTimeEpa(database).prefetched([base._TEAM_A])
    assert not isinstance(provider.point_in_time_epa(base._TEAM_A, base._EVENT_TARGET, base._AS_OF), Unavailable)
    with pytest.raises(ValueError):
        provider.point_in_time_epa(base._TEAM_B, base._EVENT_TARGET, base._AS_OF)


@requires_db
def test_the_strength_view_is_the_same_with_the_history(database: Database) -> None:
    # The event analysis (rankings) passes the history to every team's strength view too (2026-11-16).
    from ml.views.strength import build_team_strength

    history = EventHistory.read(database, base._EVENT_TARGET)
    for as_of in _INSTANTS:
        for team in base._ALL_TEAMS:
            plain = build_team_strength(database, team, base._EVENT_TARGET, as_of,
                                        epa_provider=StatboticsPointInTimeEpa(database))
            fast = build_team_strength(database, team, base._EVENT_TARGET, as_of, history=history,
                                       epa_provider=StatboticsPointInTimeEpa(database).prefetched(base._ALL_TEAMS))
            assert fast == plain, (team, as_of)
