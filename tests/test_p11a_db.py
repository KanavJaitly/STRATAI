"""P11A on an isolated PostgreSQL copy (docs/p11a_verification.md). NOT RUN on the build machine (no PostgreSQL).

    export DATABASE_URL=postgresql://.../stratai_test_p11a      # an isolated copy (tests/db_guard.py enforces it)
    python -m scripts.p11a_db_preflight                          # must print "ready"
    pytest tests/test_p11a_db.py -k real_data                    # read-only real-data tests (seconds to minutes)
    pytest tests/test_p11a_db.py -k api                          # API tests (sentinel rows in the copy only)

**Part A, real data, read-only.**
- Every read runs in one READ ONLY transaction (`read_snapshot`). A test proves the export connection cannot write.
- The event is `P11A_DB_EVENT`, or the 2024-2026 event with the most played qualification matches that have a landed
  breakdown. 2027 is never read.
- Tests:
  - snapshot export and integrity;
  - the historical cutoff (no row, ranking or scouting summary after `as_of`);
  - real-event plan generation:
    - with **no** registered configuration (the real state), the plan is withheld;
    - with a **synthetic, test-only** GameSpec and configuration for the event's season, in a temporary registry
      (never data/season_scoring), the estimator and planner run on the real alliance rows within the P11-Q3
      budget. That output is not a real plan: its scoring rules are made up.

**Part B, the authenticated API.** It reuses Phase 11's sentinel event, teams and workspace fixtures
(tests/test_phase11_live_draft_api.py), which write only to the isolated copy and clean up after themselves.
- Tests:
  - authentication and permissions;
  - workspace isolation;
  - the snapshot folder;
  - a current plan and profile through HTTP.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_test_* database copy")

REAL_SEASONS = (2024, 2025, 2026)  # never 2027 (the holdout)


# --- part A: real data, read-only -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def readonly():
    from data.config import Settings
    from database.connection import Database, DatabaseConfig, read_snapshot

    with read_snapshot(Database(DatabaseConfig(Settings().database_url))) as database:
        yield database


@pytest.fixture(scope="module")
def real_event(readonly):
    chosen = os.environ.get("P11A_DB_EVENT")
    with readonly.cursor() as c:
        if chosen:
            c.execute("SELECT event_key, season FROM events WHERE event_key = %s", (chosen,))
        else:
            c.execute(
                "SELECT m.event_key, m.season FROM matches m WHERE m.season = ANY(%s) AND m.competition_level = "
                "'qualification' AND m.score_red IS NOT NULL AND m.scheduled_time IS NOT NULL AND EXISTS (SELECT 1 "
                "FROM raw_source_payloads p WHERE p.source = 'tba' AND p.source_object_type = 'match' AND "
                "p.is_current AND p.source_object_id = m.match_key) GROUP BY m.event_key, m.season "
                "ORDER BY count(*) DESC, m.event_key LIMIT 1", (list(REAL_SEASONS),))
        row = c.fetchone()
        if row is None:
            pytest.skip("no real 2024-2026 event with landed breakdowns (not a real-data copy)")
        event_key, season = row
        assert season in REAL_SEASONS, "the 2027 holdout must not be used"
        c.execute("SELECT scheduled_time FROM matches WHERE event_key = %s AND competition_level = 'qualification' "
                  "AND scheduled_time IS NOT NULL ORDER BY scheduled_time", (event_key,))
        times = [r[0] for r in c.fetchall()]
    return event_key, season, times


def _mid(times):
    return times[len(times) // 2] + timedelta(minutes=1)


def test_real_data_export_connection_is_read_only(readonly):
    import psycopg

    with readonly.cursor() as c:
        c.execute("SELECT current_setting('transaction_read_only')")
        assert c.fetchone()[0] == "on"
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("CREATE TEMP TABLE p11a_should_fail (x int)")


def test_real_data_snapshot_export_and_integrity(readonly, real_event, tmp_path):
    from ml.alliance.snapshot import EventSnapshot, SnapshotError, build_event_snapshot, snapshot_filename

    event_key, season, times = real_event
    as_of = times[-1] + timedelta(hours=1)
    started = time.monotonic()
    snap = build_event_snapshot(readonly, event_key, as_of)
    elapsed = time.monotonic() - started
    snap.validate()
    assert snap.season == season and snap.qual_rows and len(snap.teams()) >= 12
    assert snap.scoring_config is None  # no season is configured (data/season_scoring is empty)
    path = tmp_path / snapshot_filename(snap)
    assert EventSnapshot.load(Path(path)) if snap.save(path) else False
    text = path.read_text()
    path.write_text(text.replace('"auto": ', '"auto": 1', 1))
    with pytest.raises(SnapshotError):
        EventSnapshot.load(path)
    print(f"{event_key}: {len(snap.qual_rows)} rows, {len(snap.exclusions)} exclusions, built in {elapsed:.1f} s")


def test_real_data_historical_cutoff(readonly, real_event):
    from ml.alliance.snapshot import build_event_snapshot

    event_key, _, times = real_event
    as_of = _mid(times)
    snap = build_event_snapshot(readonly, event_key, as_of)
    snap.validate()  # no row at or after as_of; every prior's event ended before this event started
    assert all(datetime.fromisoformat(r.time) < as_of for r in snap.qual_rows)
    full = build_event_snapshot(readonly, event_key, times[-1] + timedelta(hours=1))
    assert len(snap.qual_rows) < len(full.qual_rows)
    assert all(p["end_date"] < snap.start_date for p in snap.priors.values())


def test_real_data_rankings_and_scouting_after_as_of_are_left_out(readonly, real_event):
    from data.rankings import read_event_ranks
    from ml.alliance.snapshot import build_event_snapshot

    event_key, _, times = real_event
    as_of = _mid(times)
    snap = build_event_snapshot(readonly, event_key, as_of)
    landed = read_event_ranks(readonly, event_key)
    if landed is not None and landed[1] > as_of:
        assert snap.ranks is None and any(e.get("what") == "ranks" for e in snap.exclusions)
    for team, entry in snap.scouting.items():
        assert datetime.fromisoformat(entry["computed_at"]) <= as_of, team


def test_real_data_plan_is_withheld_without_a_registered_configuration(readonly, real_event):
    from ml.alliance.planner import DraftPosition, PlanWithheld, build_plan
    from ml.alliance.snapshot import build_event_snapshot

    event_key, _, times = real_event
    snap = build_event_snapshot(readonly, event_key, times[-1] + timedelta(hours=1))
    us = snap.teams()[0]
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, DraftPosition(us, 1, "captain", 1, (us,), 2, 0, tuple(snap.teams()[1:]), {}))
    assert refused.value.code == "scoring_config_not_approved"


def test_real_data_plan_mechanics_with_a_synthetic_test_only_configuration(readonly, real_event, tmp_path):
    """The made-up scoring rules (tests/p11a_support.py) are registered in a temporary folder for the event's season.
    The output is not a real plan. It checks that the estimator and planner run on real rows, and how fast."""
    from ml.alliance.contract import P11APlanOut
    from ml.alliance.planner import DraftPosition, PlanWithheld, build_plan
    from ml.alliance.snapshot import build_event_snapshot
    from tests.p11a_support import game_spec, scoring_config, write_registry

    event_key, season, times = real_event
    snap = build_event_snapshot(readonly, event_key, times[-1] + timedelta(hours=1))
    snap.scoring_config = scoring_config(season=season).model_dump(mode="json")
    snap.game_spec = game_spec(season).model_dump(mode="json")
    write_registry(tmp_path, season)
    us = snap.teams()[0]
    started = time.monotonic()
    try:
        plan = build_plan(snap, DraftPosition(us, 1, "captain", 1, (us,), 2, 0, tuple(snap.teams()[1:]), {}),
                          scoring_dir=tmp_path)
    except PlanWithheld as exc:  # a real event may genuinely be unfit (reported, not hidden)
        pytest.fail(f"withheld on real rows: {exc.code}: {exc.message}")
    elapsed = time.monotonic() - started
    P11APlanOut.model_validate(plan)
    assert plan["cards"] and elapsed < 2.0, elapsed  # P11-Q3 budget for the plan computation itself


# --- part B: the authenticated API (sentinel rows in the isolated copy) ------------------------------------------------

from tests.test_phase11_live_draft_api import (  # noqa: E402
    BASE,
    EVENT,
    TEAM_A,
    TEAM_B,
    TEAMS,
    _environment,  # noqa: F401 (autouse fixture)
    canonical,  # noqa: F401 (fixture)
    start,
    team,  # noqa: F401 (fixture)
)
from tests.test_workspaces_api import code, make_app, workspace  # noqa: E402


def test_api_plan_and_profile_need_a_session_and_the_permission(team):
    from fastapi.testclient import TestClient

    app, admin, _, scouter = team
    record = start(admin).json()["record_id"]
    anonymous = TestClient(app)
    assert anonymous.get(f"{BASE}/{record}/plan").status_code == 401
    refused = scouter.get(f"{BASE}/{record}/plan")
    assert refused.status_code == 403 and code(refused) == "permission_denied"
    assert scouter.get(f"{BASE}/{record}/teams/{TEAM_A}/profile").status_code == 403


def test_api_another_workspace_cannot_read_the_plan(team):
    app, admin, _, _ = team
    record = start(admin).json()["record_id"]
    other = workspace(app, TEAM_B, "bea")
    for path in (f"{BASE}/{record}/plan", f"{BASE}/{record}/teams/{TEAM_A}/profile"):
        response = other.get(path)
        assert response.status_code == 404 and code(response) == "draft_not_found"


def test_api_plan_is_withheld_without_a_snapshot_folder(team):
    _, admin, strategy, _ = team
    record = start(admin).json()["record_id"]
    body = strategy.get(f"{BASE}/{record}/plan").json()
    assert body["status"] == "withheld" and body["withheld"]["code"] == "snapshot_unavailable"
    assert body["experimental"] is True and body["plan"] is None


def test_api_plan_and_profile_are_served_from_a_snapshot(monkeypatch, tmp_path):
    """A synthetic snapshot for the sentinel event and a synthetic, test-only registry for its sentinel season."""
    from ml.alliance import scoring_config as scoring_module
    from ml.alliance.snapshot import snapshot_filename
    from tests.p11a_support import snapshot, truths, write_registry
    from tests.test_phase11_live_draft_api import RULES, SEASON as SENTINEL_SEASON
    from workspaces import alliance_plan

    alliance_plan.clear_cache()
    truth = dict(zip(TEAMS, truths(len(TEAMS), 3).values()))
    snap = snapshot(truth=truth, season=SENTINEL_SEASON, event_key=EVENT)
    folder, registry = tmp_path / "snapshots", tmp_path / "registry"
    folder.mkdir()
    registry.mkdir()
    snap.save(folder / snapshot_filename(snap))
    write_registry(registry, SENTINEL_SEASON)
    monkeypatch.setattr(scoring_module, "CONFIG_DIR", registry)
    app = make_app(monkeypatch, P11A_SNAPSHOT_DIR=str(folder))
    admin = workspace(app, TEAM_A, "ada")
    record = admin.post(BASE, json={"event_key": EVENT, "manual_rules": RULES}).json()["record_id"]
    admin.post(f"{BASE}/{record}/actions", json={"type": "captain", "seed": 1, "team_number": TEAM_A})
    plan = admin.get(f"{BASE}/{record}/plan")
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["status"] == "current", body["withheld"]
    assert body["plan"]["validation_status"] == "not_validated" and body["plan"]["cards"]
    profile = admin.get(f"{BASE}/{record}/teams/{TEAMS[3]}/profile").json()
    assert profile["status"] == "current" and profile["profile"]["estimates"]["validation_status"] == "not_validated"
