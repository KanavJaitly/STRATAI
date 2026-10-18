"""P7-M6: alliance selection -- candidate profiles, and the pick list's real refusals and (synthetic) success path.

Real Postgres sentinel rows (namespace 9955), only on an isolated stratai_* database copy, with the reference
Statbotics EPA source. The success path uses a SYNTHETIC approved ruleset (tests/phase6_bracket_fixtures), synthetic
final ranks, stub playoff models, a stub ranking model and SYNTHETIC PX gate records in a temporary directory: it
proves the route's wiring, checks and serialization, and is no evidence about any real event, model or rule.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.dependencies import get_database, get_playoff_models, get_ranking_model
from data.config import Settings
from data.landing.raw_writer import RawPayloadRecord, RawPayloadWriter
from data.rankings import OBJECT_TYPE_EVENT_RANKING
from database.connection import Database, DatabaseConfig
from ml.playoffs import service
from ml.playoffs.px1 import OutsidePX1Domain
from ml.playoffs.selection import DraftState
from ml.playoffs.service import PlayoffModels, playoff_gate_records, playoff_gates
from tests.phase6_bracket_fixtures import ruleset
from tests.phase7_support import assert_declared_error, stub_served_model
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_* database copy")

_SEASON = 9955
_PRIOR, _EVENT, _EMPTY, _LATER = "9955zzzprior", "9955zzzevent", "9955zzzempty", "9955zzzlater"
_ODD = "9956zzzodd"  # a season-9955 event whose key names another season
_TEAMS = list(range(995501, 995513))  # 12 teams: 4 alliances of 3 under the synthetic ruleset
_PLAYOFF_ONLY = 995513  # in a playoff row only (one test)
_T0 = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)
CANDIDATES = "/events/{event_key}/alliance-selection/candidates"
PICK_LIST = "/events/{event_key}/alliance-selection/pick-list"


@pytest.fixture(autouse=True)
def _reference_epa_source(monkeypatch):
    monkeypatch.setenv("EPA_SOURCE", "statbotics")


def _cleanup(db: Database) -> None:
    with db.cursor() as c:
        for prefix in ("9955zzz%%", "9956zzz%%"):
            c.execute("DELETE FROM raw_source_payloads WHERE source = 'tba' AND source_object_id LIKE '" + prefix + "'")
            c.execute("DELETE FROM match_teams WHERE match_key LIKE '" + prefix + "'")
            c.execute("DELETE FROM matches WHERE event_key LIKE '" + prefix + "'")
            c.execute("DELETE FROM team_event_stats WHERE event_key LIKE '" + prefix + "'")
            c.execute("DELETE FROM events WHERE event_key LIKE '" + prefix + "'")
        c.execute("DELETE FROM teams WHERE team_number = ANY(%s)", (_TEAMS + [_PLAYOFF_ONLY],))
        c.execute("DELETE FROM season_rulesets WHERE season = %s", (_SEASON,))


@pytest.fixture
def database() -> Generator[Database, None, None]:
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))
    _cleanup(db)
    future = datetime.now(timezone.utc) + timedelta(days=3)
    with db.cursor() as c:
        c.execute("INSERT INTO events (event_key, season, name, end_date) VALUES (%s, %s, 'Prior', %s), "
                  "(%s, %s, 'Event', %s), (%s, %s, 'Empty', %s), (%s, %s, 'Later', %s), (%s, %s, 'Odd', %s)",
                  (_PRIOR, _SEASON, date(2026, 2, 20), _EVENT, _SEASON, date(2026, 3, 2), _EMPTY, _SEASON,
                   date(2026, 3, 2), _LATER, _SEASON, future.date(), _ODD, _SEASON, date(2026, 3, 2)))
        c.execute("INSERT INTO teams (team_number, name) VALUES " + ", ".join(["(%s, %s)"] * len(_TEAMS)),
                  [v for t in _TEAMS for v in (t, f"Team {t}")])
        c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                  "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', 1, %s, 50, 40)",
                  (f"{_PRIOR}_qm1", _PRIOR, _SEASON, datetime(2026, 2, 19, 10, tzinfo=timezone.utc)))
        for i, team in enumerate(_TEAMS):
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                      (f"{_PRIOR}_qm1", team, "red" if i % 2 else "blue"))
            c.execute("INSERT INTO team_event_stats (team_number, event_key, season, epa_total, epa_auto, epa_teleop, "
                      "epa_endgame, matches_played) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)",
                      (team, _PRIOR, _SEASON, 60 - 3 * i, 8.0, 40 - 3 * i, 12.0))
        for n in range(4):  # four played qualification matches, each with six of the twelve teams
            key, red, blue = f"{_EVENT}_qm{n + 1}", _TEAMS[(6 * n) % 12:][:3], _TEAMS[(6 * n + 3) % 12:][:3]
            c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                      "scheduled_time, score_red, score_blue) VALUES (%s, %s, %s, 'qualification', %s, %s, 60, 50)",
                      (key, _EVENT, _SEASON, n + 1, _T0 + timedelta(hours=n)))
            for color, teams in (("red", red), ("blue", blue)):
                for team in teams:
                    c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                              (key, team, color))
        c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                  "scheduled_time) VALUES (%s, %s, %s, 'qualification', 1, %s)", (f"{_LATER}_qm1", _LATER, _SEASON,
                                                                                  future))
        for team in _TEAMS[:6]:
            c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, %s)",
                      (f"{_LATER}_qm1", team, "red" if team in _TEAMS[:3] else "blue"))
    try:
        yield db
    finally:
        _cleanup(db)


def _land_final_ranks(db: Database, teams: list[int] | None = None) -> None:
    payload = {"rankings": [{"team_key": f"frc{t}", "rank": i + 1} for i, t in enumerate(teams or _TEAMS)]}
    RawPayloadWriter(db).write(RawPayloadRecord("tba", OBJECT_TYPE_EVENT_RANKING, _EVENT, payload))


def _approve_synthetic_ruleset(db: Database, data: dict | None = None) -> None:
    from data.rulesets import review_ruleset, save_ruleset_draft, submit_ruleset

    row = save_ruleset_draft(db, data or ruleset(_SEASON), created_by="synthetic author")
    submit_ruleset(db, row["id"])
    review_ruleset(db, row["id"], reviewer="synthetic reviewer", approve=True,
                   reviewer_qualification="synthetic test qualification", checklist={f"R{i}": True for i in range(1, 15)},
                   verified_sha256=row["ruleset_sha256"])


class _StubPX1:
    """A stand-in PX-1: P(red) from the two alliances' EPA totals and seeds. Synthetic."""

    def predict(self, row) -> float:
        red = sum(t.epa_total or 0.0 for t in row.red_teams)
        blue = sum(t.epa_total or 0.0 for t in row.blue_teams)
        return 1.0 / (1.0 + math.exp(-((red - blue) / 30.0 + 0.1 * (row.blue_seed - row.red_seed))))


def _stub_playoff_models() -> PlayoffModels:
    return PlayoffModels(_StubPX1(), lambda p: p, "1" * 64, "2" * 64)


def _write_gate_records(directory, *, passed=(True, True, True), shas=("1" * 64, "2" * 64)) -> None:
    """SYNTHETIC gate records: PX-1 names the PX-1 sha, PX-2 the calibrator sha (P6-M5 records both)."""
    bodies = ({"artifact_sha256": shas[0]}, {"artifact_sha256": shas[1]}, {})
    for (gate, name), ok, body in zip(service.PX_GATE_RECORDS, passed, bodies):
        (directory / name).write_text(json.dumps({"gate": gate, "passed": ok, **body}), encoding="utf-8")


@pytest.fixture
def gate_dir(tmp_path, monkeypatch):
    """The PX gate records are read from a temporary directory, never the real results directory."""
    monkeypatch.setattr(service, "PHASE6_RESULTS", tmp_path)
    return tmp_path


@pytest.fixture
def app(database, gate_dir):
    application = create_app(Settings())
    application.dependency_overrides[get_database] = lambda: database
    application.dependency_overrides[get_ranking_model] = lambda: stub_served_model(
        predict_rating=lambda f: (f.epa_total or 0.0))
    return application


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _empty_draft(seed: int = 1) -> dict:
    return {"seed": seed, "alliances": [[], [], [], []], "declined": [], "turns_taken": 0}


# --- candidates -----------------------------------------------------------------------------------------------------


def test_candidates_default_to_the_selection_moment_with_engine_labels(client):
    body = client.get(CANDIDATES.format(event_key=_EVENT)).json()
    assert body["as_of_source"] == "selection_moment"
    assert datetime.fromisoformat(body["as_of"]) == _T0 + timedelta(hours=3, minutes=1)  # latest qual + 1 minute
    assert [c["team_number"] for c in body["candidates"]] == _TEAMS
    first = body["candidates"][0]
    assert first["defense"]["value"] is None and first["defense"]["validation"]["status"] == "insufficient_data"
    assert first["synergy"]["validation"]["reasons"] == ["alliance incomplete"]
    assert first["scoring_epa"]["validation"]["status"] == "descriptive" and first["scoring_epa"]["value"] is not None
    assert body["epa"]["epa_source"] == "statbotics"


def test_reliability_carries_the_interim_caveat_in_its_reasons(client):
    body = client.get(CANDIDATES.format(event_key=_EVENT)).json()
    assert all(any(r.startswith("reliability_score_interim") for r in c["reliability"]["validation"]["reasons"])
               for c in body["candidates"])


def test_a_playoff_only_team_is_not_a_candidate(client, app, database):
    with database.cursor() as c:
        c.execute("INSERT INTO teams (team_number, name) VALUES (%s, 'Playoff only')", (_PLAYOFF_ONLY,))
        c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                  "scheduled_time) VALUES (%s, %s, %s, 'final', 1, %s)", (f"{_EVENT}_f1m1", _EVENT, _SEASON,
                                                                       _T0 + timedelta(hours=8)))
        c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                  (f"{_EVENT}_f1m1", _PLAYOFF_ONLY))
    body = client.get(CANDIDATES.format(event_key=_EVENT)).json()
    assert _PLAYOFF_ONLY not in [c["team_number"] for c in body["candidates"]]
    response = client.get(CANDIDATES.format(event_key=_EVENT),
                          params={"configuration": [_TEAMS[0], _TEAMS[1], _PLAYOFF_ONLY]})
    assert_declared_error(app.openapi(), response, "GET", CANDIDATES, code="team_not_found")


def test_candidates_without_an_epa_source_refuse(client, app):
    from api.dependencies import get_epa_source

    app.dependency_overrides[get_epa_source] = lambda: None
    response = client.get(CANDIDATES.format(event_key=_EVENT))
    assert_declared_error(app.openapi(), response, "GET", CANDIDATES, code="epa_source_not_loaded")


def test_a_configuration_adds_the_alliance_factors_for_its_members_only(client):
    config = _TEAMS[:3]
    body = client.get(CANDIDATES.format(event_key=_EVENT), params={"configuration": config}).json()
    by_team = {c["team_number"]: c for c in body["candidates"]}
    assert all(by_team[t]["synergy"]["validation"]["status"] == "not_validated_against_outcomes" for t in config)
    assert by_team[_TEAMS[5]]["synergy"]["validation"]["status"] == "insufficient_data"


def test_before_selection_the_default_is_now_and_never_the_future(client):
    body = client.get(CANDIDATES.format(event_key=_LATER)).json()
    assert body["as_of_source"] == "now"
    assert datetime.fromisoformat(body["as_of"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)


@pytest.mark.parametrize("params, event, code", [
    ({"configuration": _TEAMS[:2]}, _EVENT, "validation_error"),
    ({"configuration": [_TEAMS[0], _TEAMS[0], _TEAMS[1]]}, _EVENT, "validation_error"),
    ({"configuration": [_TEAMS[0], _TEAMS[1], 995599]}, _EVENT, "team_not_found"),
    ({}, "9955zzznosuch", "event_not_found"),
    ({}, _EMPTY, "selection_time_unavailable"),
    ({"as_of": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}, _EVENT, "invalid_as_of"),
])
def test_candidate_refusals_are_declared(client, app, params, event, code):
    response = client.get(CANDIDATES.format(event_key=event), params=params)
    assert_declared_error(app.openapi(), response, "GET", CANDIDATES, code=code)


# --- the PX gate reader ---------------------------------------------------------------------------------------------


def test_missing_records_are_not_passed(tmp_path):
    assert playoff_gates(tmp_path) == {"PX-1": False, "PX-2": False, "PX-4": False}


@pytest.mark.parametrize("text, passed", [
    ('{"passed": true}', True), ('{"passed": "true"}', False), ('{"passed": 1}', False), ('[true]', False),
    ('"passed"', False), ('{"passed": false}', False), ("not json", False), ('{}', False),
])
def test_only_a_json_object_with_passed_true_passes(tmp_path, text, passed):
    for _, name in service.PX_GATE_RECORDS:
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert set(playoff_gates(tmp_path).values()) == {passed}
    if passed:
        assert all(raw == text for _, raw in playoff_gate_records(tmp_path).values())


def test_the_real_results_directory_has_no_passed_px_gate():
    """The P6 PX gates are recorded as not run/passed today (P6-DM1 deferred); this pins that the service sees it."""
    assert not all(playoff_gates().values())


# --- the pick list: the refusals, in the R4 order --------------------------------------------------------------------


def test_today_the_pick_list_refuses_with_not_approved(client, app):
    """No approved ruleset exists for the season: the engine's own refusal, before anything else is consulted."""
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="not_approved")


def test_not_approved_comes_before_the_epa_source(client, app):
    from api.dependencies import get_epa_source

    app.dependency_overrides[get_epa_source] = lambda: None
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="not_approved")


@pytest.mark.parametrize("sql, code", [
    ("UPDATE season_rulesets SET ruleset_sha256 = repeat('0', 64) WHERE season = %s", "storage_integrity"),
    ("UPDATE season_rulesets SET ruleset_json = '{}'::jsonb WHERE season = %s", "storage_integrity"),
])
def test_a_tampered_approved_ruleset_is_storage_integrity(client, app, database, gate_dir, sql, code):
    _approve_synthetic_ruleset(database)
    with database.cursor() as c:
        c.execute(sql, (_SEASON,))
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code=code)


def test_an_event_key_of_another_season_is_wrong_season(client, app, database):
    _approve_synthetic_ruleset(database)
    response = client.post(PICK_LIST.format(event_key=_ODD), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="wrong_season")


def test_an_excluded_event_is_refused(client, app, database):
    data = ruleset(_SEASON)
    data["event_exclusions"] = [{"event_key": _EVENT, "reason": "synthetic_exclusion", "finding": "synthetic"}]
    _approve_synthetic_ruleset(database, data)
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="event_excluded")


def test_with_an_approved_ruleset_the_missing_px_gate_records_refuse(client, app, database):
    """No gate record exists in the (temporary) results directory, so the pick list stops at step 3."""
    _approve_synthetic_ruleset(database)
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="playoff_models_not_accepted")
    assert "PX-1" in error["message"] and "PX-4" in error["message"]


def test_one_failed_px_gate_refuses(client, app, database, gate_dir):
    _approve_synthetic_ruleset(database)
    _write_gate_records(gate_dir, passed=(True, True, False))
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="playoff_models_not_accepted")
    assert "PX-4" in error["message"] and "PX-1" not in error["message"]


def test_the_pick_list_refuses_an_unknown_event(client, app):
    response = client.post(PICK_LIST.format(event_key="9955zzznosuch"), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="event_not_found")


def test_a_team_on_two_alliances_is_a_validation_error(client, app):
    body = {**_empty_draft(), "alliances": [[_TEAMS[0]], [_TEAMS[0]], [], []]}
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=body)
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="validation_error")


def _ready(database, gate_dir, *, ranks: bool = True) -> None:
    _approve_synthetic_ruleset(database)
    _write_gate_records(gate_dir)
    if ranks:
        _land_final_ranks(database)


def test_before_qualification_ends_the_pick_list_refuses(client, app, database, gate_dir):
    _approve_synthetic_ruleset(database)
    _write_gate_records(gate_dir)
    response = client.post(PICK_LIST.format(event_key=_LATER), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="selection_time_unavailable")


def test_an_unplayed_qualification_match_means_qualification_is_not_finished(client, app, database, gate_dir):
    _ready(database, gate_dir)
    with database.cursor() as c:
        c.execute("INSERT INTO matches (match_key, event_key, season, competition_level, match_number, "
                  "scheduled_time) VALUES (%s, %s, %s, 'qualification', 9, %s)",
                  (f"{_EVENT}_qm9", _EVENT, _SEASON, _T0 + timedelta(minutes=30)))
        c.execute("INSERT INTO match_teams (match_key, team_number, alliance_color) VALUES (%s, %s, 'red')",
                  (f"{_EVENT}_qm9", _TEAMS[0]))
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="selection_time_unavailable")
    assert "1 match(es) unscored" in error["message"]


def test_after_the_gates_without_final_ranks_the_pick_list_refuses(client, app, database, gate_dir):
    _ready(database, gate_dir, ranks=False)
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="rankings_unavailable")


def test_ranks_fetched_before_qualification_ended_are_not_final(client, app, database, gate_dir):
    _ready(database, gate_dir)
    with database.cursor() as c:
        c.execute("UPDATE raw_source_payloads SET fetch_timestamp = %s WHERE source = 'tba' AND "
                  "source_object_type = %s AND source_object_id = %s", (_T0, OBJECT_TYPE_EVENT_RANKING, _EVENT))
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="rankings_unavailable")


def test_ranks_missing_a_qualification_team_are_not_final(client, app, database, gate_dir):
    _ready(database, gate_dir, ranks=False)
    _land_final_ranks(database, _TEAMS[:-1])
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="rankings_unavailable")


def test_after_the_gates_without_pinned_playoff_models_the_pick_list_refuses(client, app, database, gate_dir):
    _ready(database, gate_dir)
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="model_not_loaded")
    assert "PX-1" in error["message"]


@pytest.mark.parametrize("shas", [("3" * 64, "2" * 64), ("1" * 64, "3" * 64), ("", "")])
def test_gate_records_that_do_not_name_the_pinned_artifacts_refuse(client, app, database, gate_dir, shas):
    _ready(database, gate_dir)
    _write_gate_records(gate_dir, shas=shas)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="playoff_models_not_accepted")
    assert "do not identify" in error["message"]


def test_without_an_epa_source_after_the_gates_the_pick_list_refuses(client, app, database, gate_dir):
    from api.dependencies import get_epa_source

    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    app.dependency_overrides[get_epa_source] = lambda: None
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="epa_source_not_loaded")


def test_without_the_m5v2_ordering_model_the_pick_list_refuses(client, app, database, gate_dir):
    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    app.dependency_overrides[get_ranking_model] = lambda: None
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    error = assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="model_not_loaded")
    assert "ranking_xgb_v2" in error["message"]


@pytest.mark.parametrize("raise_, code", [
    (OutsidePX1Domain("synthetic: outside the 3-team domain"), "playoff_inputs_insufficient"),
    (ValueError("PX-1 input absent: synthetic"), "playoff_inputs_insufficient"),
])
def test_px1_refusals_are_typed(client, app, database, gate_dir, raise_, code):
    _ready(database, gate_dir)

    class _Refusing:
        def predict(self, row):
            raise raise_

    app.dependency_overrides[get_playoff_models] = lambda: PlayoffModels(_Refusing(), lambda p: p, "1" * 64, "2" * 64)
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code=code)


def _with_selection(**changes) -> dict:
    data = ruleset(_SEASON)
    data["selection"] = {**data["selection"], **changes}
    return data


@pytest.mark.parametrize("data, code", [
    (_with_selection(captain_rule=None, unresolved=[{"field": "captain_rule", "note": "synthetic",
                                                     "sources_checked": "synthetic"}]), "not_established"),
    (_with_selection(captain_may_accept_higher_alliance=False), "not_supported"),
    ({**ruleset(_SEASON), "alliance_counts": [{"min_teams": 13, "max_teams": None, "alliances": 4,
                                               "citation": "synthetic fixture"}]}, "not_covered"),
])
def test_the_engine_refuses_rules_it_cannot_represent(client, app, database, gate_dir, data, code):
    _approve_synthetic_ruleset(database, data)
    _write_gate_records(gate_dir)
    _land_final_ranks(database)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code=code)


@pytest.mark.parametrize("declined", [_TEAMS[-2:], [_TEAMS[6]]])
def test_too_many_declines_leave_the_draft_infeasible(client, app, database, gate_dir, declined):
    """Two declines run out during another seed's turn; one runs out on seed 1's own last turn (that was an
    AssertionError 500 before P7-D5)."""
    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json={**_empty_draft(), "declined": declined})
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="infeasible")


def test_a_declined_team_may_captain_where_the_rules_allow_it(client, app, database, gate_dir):
    """Seed 1 invites team 2, which declines; seed 1 picks team 3; team 2 then captains seed 2 (synthetic rules:
    declined_team_may_become_captain true). A real draft state, served."""
    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    draft = {"seed": 2, "alliances": [[_TEAMS[0], _TEAMS[2]], [_TEAMS[1]], [], []], "declined": [_TEAMS[1]],
             "turns_taken": 1}
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=draft)
    assert response.status_code == 200, response.text
    assert response.json()["ranked"][0]["configuration"][0] == _TEAMS[1]


def test_a_declined_captain_under_an_unestablished_rule_is_not_established(client, app, database, gate_dir):
    _approve_synthetic_ruleset(database, _with_selection(
        declined_team_may_become_captain=None,
        unresolved=[{"field": "declined_team_may_become_captain", "note": "synthetic", "sources_checked": "synthetic"}]))
    _write_gate_records(gate_dir)
    _land_final_ranks(database)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    draft = {"seed": 2, "alliances": [[_TEAMS[0], _TEAMS[2]], [_TEAMS[1]], [], []], "declined": [_TEAMS[1]],
             "turns_taken": 1}
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=draft)
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="not_established")


def test_ranks_fetched_before_the_last_result_was_seen_are_not_final(client, app, database, gate_dir):
    """The ranking predates the last qualification result payload (e.g. an event running late)."""
    _ready(database, gate_dir)
    with database.cursor() as c:
        c.execute("UPDATE raw_source_payloads SET fetch_timestamp = %s WHERE source = 'tba' AND "
                  "source_object_type = %s AND source_object_id = %s",
                  (_T0 + timedelta(hours=4), OBJECT_TYPE_EVENT_RANKING, _EVENT))
    RawPayloadWriter(database).write(RawPayloadRecord("tba", "match", f"{_EVENT}_qm4", {"key": f"{_EVENT}_qm4"}))
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft())
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="rankings_unavailable")


@pytest.mark.parametrize("draft", [
    {**_empty_draft(seed=2)},  # not seed 2's turn
    {**_empty_draft(), "alliances": [[], []]},  # the event has 4 alliances
    {**_empty_draft(), "alliances": [[995599], [], [], []]},  # an unknown team
    {**_empty_draft(), "declined": [995599]},  # an unknown declined team
    # a declined team picked later, which the synthetic rules forbid (declined_team_may_be_picked_later: false)
    {"seed": 2, "alliances": [[_TEAMS[0], _TEAMS[5]], [], [], []], "declined": [_TEAMS[5]], "turns_taken": 1},
    {**_empty_draft(), "alliances": [[_TEAMS[0]], [_TEAMS[1]], [_TEAMS[2]], [_TEAMS[3]]]},  # captains up front
    {**_empty_draft(), "alliances": [[_TEAMS[11]], [], [], []]},  # not the captain the captain rule gives
    {**_empty_draft(), "turns_taken": 99},  # more turns than the draft has
    {"seed": 2, "alliances": [[_TEAMS[0]], [], [], []], "turns_taken": 1},  # seed 1 took a turn but holds 1 team
    {"seed": 1, "alliances": [[_TEAMS[0], _TEAMS[5], _TEAMS[6]], [], [], []], "turns_taken": 0},  # picks, no turns
])
def test_inconsistent_draft_states_are_invalid_state(client, app, database, gate_dir, draft):
    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=draft)
    assert_declared_error(app.openapi(), response, "POST", PICK_LIST, code="invalid_state")


def test_event_rules_required_is_not_declared(app):
    from tests.phase7_support import declared_codes

    assert "event_rules_required" not in declared_codes(app.openapi(), "POST", PICK_LIST, 409)


# --- the pick list: the synthetic success path ------------------------------------------------------------------------


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_the_synthetic_success_path_serves_the_full_shape_without_raw_precision(client, app, database, gate_dir):
    _ready(database, gate_dir)
    app.dependency_overrides[get_playoff_models] = _stub_playoff_models
    response = client.post(PICK_LIST.format(event_key=_EVENT), json=_empty_draft(seed=1))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["probability_status"] == "validated_playoff_success" and body["seed"] == 1
    assert datetime.fromisoformat(body["as_of"]) == _T0 + timedelta(hours=3, minutes=1)
    ranked = body["ranked"]
    assert ranked and ranked[0]["configuration"][0] == _TEAMS[0]  # seed 1's captain: the top-ranked team
    assert len(ranked) == len(_TEAMS) - 1  # every available team, ranked
    assert all(r["win_event"]["display"] for r in ranked)
    scope = ranked[0]["win_event"]["validation"]
    assert scope["status"] == "validated_playoff_success" and scope["evidence"].endswith("p6_m5_px4.json")
    assert [r.split(":")[0] for r in scope["reasons"]] == ["px4_scope", "predicted_field_not_validated"]
    assert ranked[-1]["vs_next_label"] is None and ranked[-1]["vs_next_reach_finals_label"] is None
    assert ranked[-1]["vs_next_reason"].startswith("last_candidate")
    assert all(r["vs_next_label"] and r["vs_next_reach_finals_label"] for r in ranked[:-1])
    assert body["models"] == {"px1_sha256": "1" * 64, "px2_calibrator_sha256": "2" * 64,
                              "ranking_model_sha256": "stub"}
    from data.rulesets import SeasonRuleset

    assert body["provenance"] == {"ruleset_sha256": SeasonRuleset.model_validate(ruleset(_SEASON)).sha256(),
                                  "ruleset_variant": None, "ordering_policy": "ranking_xgb_v2"}
    assert len(body["alternatives"]) <= 5
    assert not set(_keys(body)) & {"p_win_event", "p_reach_finals", "margin_over_next", "difference"}
    out = os.environ.get("STRATAI_SYNTHETIC_EXAMPLES_DIR")
    if out:  # P7-M8 / P7-Q1: the pick list's synthetic success example comes from this test, labelled synthetic
        from api.examples import ApiExample
        from scripts.phase7_capture_examples import write_examples

        example = ApiExample(
            operation="POST /events/{event_key}/alliance-selection/pick-list", status=200, name="synthetic_success",
            kind="synthetic", summary="SYNTHETIC: a synthetic approved ruleset, synthetic ranks, stub PX models and "
                                      "synthetic gate records; no real event, model or rule",
            environment={"environment_name": "tests/test_phase7_alliance_selection_api.py",
                         "environment_of_record": False, "synthetic": True},
            request={"path_params": {"event_key": _EVENT}, "body": _empty_draft(seed=1)}, response=body)
        write_examples([example], Path(out))


def test_the_service_ranks_by_win_event_and_alternatives_are_distinct(database, gate_dir):
    _ready(database, gate_dir)
    from ml.ratings.provider import default_point_in_time_provider

    provider = default_point_in_time_provider(database, Settings())
    out = service.pick_list(database, _EVENT, 1, DraftState.empty(4), datetime.now(timezone.utc),
                            epa_provider=lambda: provider, m5v2_predict_rating=lambda f: f.epa_total or 0.0,
                            playoff_models=_stub_playoff_models())
    ranked = out.recommendation.ranked
    keys = [(-r.p_win_event, -r.p_reach_finals) for r in ranked]
    assert keys == sorted(keys)
    configurations = [tuple(sorted(f.alliances[0])) for f in out.recommendation.alternatives]
    assert len(set(configurations)) == len(configurations) <= 5
    assert tuple(sorted(ranked[0].configuration)) not in configurations


def test_a_missing_ruleset_table_means_not_approved():
    """Migration 0011 not applied: no ruleset was ever approved (psycopg's UndefinedTable, matched by name)."""
    from contextlib import contextmanager

    from data.rulesets import RulesetError

    class UndefinedTable(Exception):
        pass

    class _NoTable:
        @contextmanager
        def cursor(self):
            raise UndefinedTable("relation \"season_rulesets\" does not exist")
            yield

    with pytest.raises(RulesetError) as raised:
        service._approved_rules(_NoTable(), _SEASON, _EVENT)
    assert raised.value.code == "not_approved"
