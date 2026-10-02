"""The production D18 loader (ml.ratings.d18_source) equals the evaluation's own loader.

scripts/run_phase4_d18.load_source built the EPA source every D18 result was computed
on and stays byte-identical as that record; ml.ratings.d18_source.load_d18_provider is
the production copy. On the real verified snapshot, both must yield identical provider
state and identical answers. Runs only with a reachable database and the D18 artifacts
configured (STATBOTICS_SNAPSHOT_DIR, STRATAI_EPA_CHAIN); otherwise skipped, never passed.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import psycopg
import pytest

from data.config import Settings


def _configured() -> tuple[Path, Path] | None:
    snapshot, chain = os.environ.get("STATBOTICS_SNAPSHOT_DIR"), os.environ.get("STRATAI_EPA_CHAIN")
    if not snapshot or not chain or not Path(snapshot, "manifest.json").exists() or not Path(chain).exists():
        return None
    try:
        with psycopg.connect(str(Settings().database_url), connect_timeout=3):
            return Path(snapshot), Path(chain)
    except Exception:
        return None


ARTIFACTS = _configured()
pytestmark = pytest.mark.skipif(ARTIFACTS is None, reason="needs the database and the D18 snapshot/chain "
                                                          "(STATBOTICS_SNAPSHOT_DIR, STRATAI_EPA_CHAIN)")


@pytest.fixture(scope="module")
def providers():
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from ml.ratings.d18_source import load_d18_provider
    from scripts.run_phase4_d18 import load_source

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    snapshot, chain = ARTIFACTS
    evaluated, evaluated_s1 = load_source(database, snapshot, chain, strict=True)
    production, integrity = load_d18_provider(database, snapshot, chain, strict=True)
    return database, evaluated, evaluated_s1, production, integrity


def test_provider_state_is_identical(providers):
    _, evaluated, evaluated_s1, production, integrity = providers
    assert production.statbotics == evaluated.statbotics
    assert production.facts == evaluated.facts
    assert production.season_end == evaluated.season_end
    assert production.week_one_complete == evaluated.week_one_complete
    assert production.provenance_info == evaluated.provenance_info
    assert production.fallback.values == evaluated.fallback.values
    assert integrity["ok"] and integrity["team_event_stats_sha256"] == evaluated_s1["team_event_stats_sha256"]


def test_lookups_are_identical_including_every_fallback_appearance(providers):
    from scripts.run_phase4_d18 import APPEARANCES_SQL

    database, evaluated, _, production, _ = providers
    with database.cursor() as cursor:
        cursor.execute(APPEARANCES_SQL, {"seasons": [2024, 2025, 2026]})
        appearances = cursor.fetchall()
    sample = random.Random(20261002).sample(appearances, 5000)
    sample += [a for a in appearances if a[2] == "2026iscmp"]
    for _, team, target, as_of in sample:
        assert production.point_in_time_epa(team, target, as_of) == evaluated.point_in_time_epa(team, target, as_of)
    assert sum(a[2] == "2026iscmp" for a in sample) == 450
