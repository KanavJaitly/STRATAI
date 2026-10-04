"""P5-M2: the live log's root is the frozen D18 snapshot, value for value (an integrity check, not L1).

Reads the real snapshot artifacts and an isolated database copy, read-only; skipped when either is absent.
Also checks the configuration and API refusals of the live provider.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ml.ratings.live_epa import EpaSourcePendingError, EpaSourceUnavailableError

SNAPSHOT = Path(os.environ.get("STATBOTICS_SNAPSHOT_DIR",
                               "C:/Dev/StratAI-artifacts/statbotics/statbotics_snapshot_20261001T220423Z"))
CHAIN = Path(os.environ.get("STRATAI_EPA_CHAIN",
                            "C:/Dev/StratAI-artifacts/ratings/epa-chain/chain_e77d9444c57a7b50.json"))


def _isolated() -> bool:
    from tests.test_live_epa import _isolated_db_name

    return _isolated_db_name() is not None


@pytest.mark.skipif(not (SNAPSHOT.exists() and CHAIN.exists() and _isolated()),
                    reason="needs the D18 artifacts and an isolated stratai_* database copy")
def test_root_records_equal_d18_values_and_anchors(tmp_path):
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.ratings.d18_source import load_d18_provider
    from ml.ratings.live_epa import week_one_and_season_end
    from ml.ratings.live_snapshots import SnapshotLog
    from ml.ratings.live_source import read_event_ends

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    d18, _ = load_d18_provider(database, SNAPSHOT, CHAIN)
    log = SnapshotLog.create_from_root(tmp_path / "log", SNAPSHOT)
    records = log.records(log.head())
    assert set(records) == set(d18.statbotics)
    assert all(records[key].value == value for key, value in d18.statbotics.items())
    unprocessed = sorted({k[1] for k, r in records.items() if not r.processed})
    assert unprocessed == ["2026isde1", "2026isde2", "2026isde3", "2026isde4"]
    assert sum(not r.processed for r in records.values()) == 140
    ends, seasons = read_event_ends(database)
    week_one, season_end = week_one_and_season_end(records, ends, seasons, {2024, 2025, 2026})
    assert week_one == d18.week_one_complete and season_end == d18.season_end


def test_pending_maps_to_its_own_code():
    from api.routes.common import CODE_EPA_SOURCE_INCOMPLETE, CODE_EPA_SOURCE_PENDING, epa_source_incomplete_error

    when = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert epa_source_incomplete_error(EpaSourcePendingError(1, "t", when, "e", "pending")).code \
        == CODE_EPA_SOURCE_PENDING
    assert epa_source_incomplete_error(EpaSourceUnavailableError(1, "t", when, "e", "unavailable")).code \
        == CODE_EPA_SOURCE_INCOMPLETE


def test_live_source_refuses_without_the_q1_policy(monkeypatch, tmp_path):
    from data.config import Settings
    from ml.ratings.provider import EpaSourceNotConfigured, default_point_in_time_provider

    monkeypatch.setenv("EPA_SOURCE", "p5_live_statbotics")
    monkeypatch.setenv("LIVE_EPA_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("STATBOTICS_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("STRATAI_EPA_CHAIN", str(tmp_path / "chain.json"))
    monkeypatch.delenv("LIVE_EPA_A1A2_POLICY", raising=False)
    with pytest.raises(EpaSourceNotConfigured, match="LIVE_EPA_A1A2_POLICY"):
        default_point_in_time_provider(None, Settings())  # type: ignore[arg-type]
