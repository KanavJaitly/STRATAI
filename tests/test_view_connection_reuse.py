"""The heavy views read through one snapshot (one connection), not a connection per read.

2026-11-16: the qualification forecast opened about 940 connections for one district event (it lacked
consistent_reads, and the Statbotics EPA source read through the app's own Database), which took the hosted API past
the web app's 30 s limit. Needs no database.
"""

from __future__ import annotations

from database.connection import Database, DatabaseConfig
from ml.ratings.provider import StatboticsPointInTimeEpa
from ml.views import event_analysis, pre_match_report, qualification_forecast, strength


def test_the_heavy_views_each_read_one_snapshot():
    # consistent_reads wraps with functools.wraps, which sets __wrapped__.
    for view in (qualification_forecast.forecast_event_qualification, event_analysis.analyze_event,
                 strength.build_team_strength, pre_match_report.pre_match_inputs):
        assert hasattr(view, "__wrapped__"), view.__name__


def test_the_statbotics_epa_source_can_read_through_a_callers_snapshot():
    app_db, snapshot = Database(DatabaseConfig("postgresql://x/a")), Database(DatabaseConfig("postgresql://x/b"))
    provider = StatboticsPointInTimeEpa(app_db)
    bound = provider.reading_through(snapshot)
    assert bound is not provider and bound._database is snapshot and provider._database is app_db
