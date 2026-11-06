"""P11A hardening: the response labels are enforced at runtime, and only a registered approved configuration plans.

- Each pinned label (`ml.alliance.contract`) rejects any other value and cannot be omitted.
- Undeclared fields are dropped, never served.
- The API route validates every response: a tampered service result becomes a 500 with no plan in the body.
- The offline CLI validates through the same types and writes nothing invalid.
- The registry (data/season_scoring) is the trust root: a snapshot cannot bring its own "approval".

Synthetic season 9911 and teams 1-24 only; no database (the session is replaced, the service is faked).
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ml.alliance.contract import AlliancePlanOut, P11APlanOut, P11AProfileOut, TeamProfileOut
from ml.alliance.planner import DraftPosition, PlanWithheld, build_plan
from ml.alliance.profile import team_profile
from ml.alliance.scoring_config import SeasonScoringConfig
from ml.alliance.snapshot import snapshot_filename
from tests.p11a_support import (
    SEASON,
    approve,
    scoring_config,
    snapshot,
    synthetic_registry,  # noqa: F401 (autouse fixture)
    write_registry,
)

PINS = [("validation_status", "validated"), ("interval_status", "calibrated"), ("thresholds_status", "approved"),
        ("objective", "probability_of_winning"), ("unit", "percent"), ("availability_model", "modelled")]


def _position(snap, team):
    return DraftPosition(team, 7, "captain", 1, (team,), 2, 0, tuple(t for t in snap.teams() if t != team), {})


@pytest.fixture(scope="module")
def plan_and_profile():
    import tests.p11a_support as support
    from ml.alliance import scoring_config as module
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        old = module.CONFIG_DIR
        module.CONFIG_DIR = Path(d)
        support.write_registry(Path(d))
        try:
            snap = snapshot(seed=31)
            plan = build_plan(snap, _position(snap, snap.teams()[0]))
            profile = team_profile(snap, snap.teams()[4], our_team=snap.teams()[0])
        finally:
            module.CONFIG_DIR = old
    return plan, profile


def test_real_outputs_satisfy_the_contract(plan_and_profile):
    plan, profile = plan_and_profile
    P11APlanOut.model_validate(plan)
    P11AProfileOut.model_validate(profile)


@pytest.mark.parametrize("field,value", PINS)
def test_each_pinned_plan_label_rejects_another_value_and_cannot_be_omitted(plan_and_profile, field, value):
    plan = copy.deepcopy(plan_and_profile[0])
    with pytest.raises(ValidationError):
        P11APlanOut.model_validate({**plan, field: value})
    with pytest.raises(ValidationError):
        P11APlanOut.model_validate({k: v for k, v in plan.items() if k != field})


def test_nested_pins_reject_validated_resolved_or_probability_values(plan_and_profile):
    plan = copy.deepcopy(plan_and_profile[0])
    for mutate in (
        lambda p: p["win_probability"].update(status="available"),
        lambda p: p["comparisons"][0].update(outcome="a_better"),
        lambda p: p["comparisons"][0].update(reason="threshold_met"),
        lambda p: p["cards"][0]["robot"]["components"]["auto"].update(kind="validated"),
        lambda p: p["fit_diagnostics"]["auto"]["collapse_screen"].update(status="authoritative"),
        lambda p: p["availability"].update(predicted=[1, 2]),
    ):
        tampered = copy.deepcopy(plan)
        mutate(tampered)
        with pytest.raises(ValidationError):
            P11APlanOut.model_validate(tampered)
    profile = copy.deepcopy(plan_and_profile[1])
    for field, value in (("validation_status", "validated"), ("thresholds_status", "approved")):
        with pytest.raises(ValidationError):
            P11AProfileOut.model_validate({**profile, field: value})
    tampered = copy.deepcopy(profile)
    tampered["estimates"]["validation_status"] = "validated"
    with pytest.raises(ValidationError):
        P11AProfileOut.model_validate(tampered)


def test_undeclared_fields_are_dropped_not_served(plan_and_profile):
    plan = copy.deepcopy(plan_and_profile[0])
    plan["win_probability_value"] = 0.71
    plan["cards"][0]["chance_of_winning"] = 0.6
    served = json.dumps(P11APlanOut.model_validate(plan).model_dump(mode="json"))
    assert "win_probability_value" not in served and "chance_of_winning" not in served


# --- the API route --------------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    from api import create_app
    from api import session as api_session
    from data.config import Settings

    member = SimpleNamespace(team_number=1, workspace_id=3, verified=True, can=lambda permission: True)
    monkeypatch.setattr(api_session, "current_session", lambda request: member)
    return TestClient(create_app(Settings(api_prefix="")), raise_server_exceptions=False)


def _envelope(plan):
    return {"record_id": 7, "record_seq": 7, "computed_at": "2099-03-03T16:00:00Z",
            "source": "p11a_expected_score_plan", "experimental": True, "relation_to_recommendations": "separate",
            "status": "current", "withheld": None, "timing_ms": {"total": 1.0}, "plan": plan}


def test_the_route_serves_a_valid_plan_and_refuses_a_tampered_one(client, monkeypatch, plan_and_profile):
    from workspaces import alliance_plan

    plan = copy.deepcopy(plan_and_profile[0])
    monkeypatch.setattr(alliance_plan, "plan_for_record", lambda *a, **k: _envelope(plan))
    good = client.get("/workspace/alliance-selection/drafts/7/plan")
    assert good.status_code == 200 and good.json()["plan"]["validation_status"] == "not_validated"
    for field, value in PINS:
        monkeypatch.setattr(alliance_plan, "plan_for_record", lambda *a, **k: _envelope({**plan, field: value}))
        bad = client.get("/workspace/alliance-selection/drafts/7/plan")
        assert bad.status_code == 500, field
        assert "plan" not in bad.json() and value not in bad.text
    envelope = _envelope(plan)
    envelope["experimental"] = False
    monkeypatch.setattr(alliance_plan, "plan_for_record", lambda *a, **k: envelope)
    assert client.get("/workspace/alliance-selection/drafts/7/plan").status_code == 500


def test_the_profile_route_refuses_an_estimate_marked_validated(client, monkeypatch, plan_and_profile):
    from workspaces import alliance_plan

    profile = copy.deepcopy(plan_and_profile[1])
    body = {**_envelope(None), "profile": profile}
    body.pop("plan")
    monkeypatch.setattr(alliance_plan, "profile_for_record", lambda *a, **k: body)
    assert client.get("/workspace/alliance-selection/drafts/7/teams/5/profile").status_code == 200
    tampered = copy.deepcopy(body)
    tampered["profile"]["estimates"]["validation_status"] = "validated"
    monkeypatch.setattr(alliance_plan, "profile_for_record", lambda *a, **k: tampered)
    assert client.get("/workspace/alliance-selection/drafts/7/teams/5/profile").status_code == 500


def test_the_envelopes_pin_source_and_experimental():
    for model in (AlliancePlanOut, TeamProfileOut):
        assert model.model_fields["experimental"].annotation.__args__ == (True,)
        assert model.model_fields["source"].annotation.__args__ == ("p11a_expected_score_plan",)


# --- the offline CLI --------------------------------------------------------------------------------------------------


def test_the_cli_validates_through_the_contract_and_writes_nothing_invalid(tmp_path, monkeypatch, plan_and_profile):
    import scripts.p11a_snapshot as cli
    from tests.test_phase11_draft_log import Log, setup

    snap = snapshot(seed=31)
    path = tmp_path / snapshot_filename(snap)
    snap.save(path)
    log = Log(setup())
    log.captain(1, 1)
    (tmp_path / "log.json").write_text(json.dumps([{"action_id": e.action_id, "seq": e.seq, "type": e.type,
                                                     "payload": dict(e.payload)} for e in log.entries]))
    tampered = {**plan_and_profile[0], "validation_status": "validated"}
    monkeypatch.setattr(cli, "build_plan", lambda *a, **k: tampered)
    out = tmp_path / "plan.json"
    with pytest.raises(ValidationError):
        cli.main(["plan", "--snapshot", str(path), "--log", str(tmp_path / "log.json"), "--team", "1",
                  "--out", str(out)])
    assert not out.exists()


# --- the trust root: data/season_scoring ------------------------------------------------------------------------------


def test_a_snapshot_cannot_bring_its_own_approval(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    snap = snapshot(seed=32)  # embeds a self-consistent "approved" configuration
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, _position(snap, snap.teams()[0]), scoring_dir=empty)
    assert refused.value.code == "scoring_config_not_registered"


def test_a_snapshot_whose_configuration_differs_from_the_registered_one_is_refused(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    write_registry(registry)
    snap = snapshot(seed=33)
    forged = scoring_config(approved=False).model_dump(mode="json")
    forged["review"] = None
    forged = approve(SeasonScoringConfig.model_validate({**forged, "fouls": "excluded"}))  # different, self-approved
    snap.scoring_config = forged.model_dump(mode="json")
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, _position(snap, snap.teams()[0]), scoring_dir=registry)
    assert refused.value.code == "scoring_config_not_registered"


def test_an_unapproved_registered_configuration_is_refused(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / f"{SEASON}.json").write_text(scoring_config(approved=False).model_dump_json())
    snap = snapshot(seed=34)
    with pytest.raises(PlanWithheld) as refused:
        build_plan(snap, _position(snap, snap.teams()[0]), scoring_dir=registry)
    assert refused.value.code == "scoring_config_not_approved"


def test_no_real_season_has_a_registered_configuration():
    from ml.alliance.scoring_config import find_config
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "data" / "season_scoring"
    assert sorted(p.name for p in real.glob("*.json")) == []
    for season in (2023, 2024, 2025, 2026, 2027):
        assert find_config(season, real) is None


# --- the database preflight (no connection is made for these) ---------------------------------------------------------


@pytest.mark.parametrize("name", ["stratai", "stratai_dev", "postgres", "stratai_prod"])
def test_the_preflight_refuses_anything_but_an_isolated_test_copy_before_connecting(name, monkeypatch):
    import psycopg

    from scripts.p11a_db_preflight import refuse_unless_isolated

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("connected"))
    with pytest.raises(SystemExit) as refused:
        refuse_unless_isolated(f"postgresql://localhost:5432/{name}")
    assert refused.value.code == 2


def test_the_preflight_accepts_an_isolated_copy():
    from scripts.p11a_db_preflight import refuse_unless_isolated

    assert refuse_unless_isolated("postgresql://u:secret@db:5433/stratai_test_p11a")["dbname"] == "stratai_test_p11a"
