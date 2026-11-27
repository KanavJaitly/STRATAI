"""Where a served model's validation label may be claimed (audit 2026-11-26, workstream 3; ml/validation_scope.py).

Pure rules first, then the routes on real 2025 (a training season of the served D18 models) and 2026 (the
retrospective evaluation season) events from the isolated database copy. The route tests need the registered D18
artifacts and the D18 EPA source (scripts/local_test_env.PINS) and skip without them.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.contract import (
    REASON_EPA_INCOMPLETE,
    REASON_PLAYOFF_SCOPE,
    STATUS_NOT_VALIDATED,
    STATUS_VALIDATED_QUALIFICATION,
    ServedModelInfo,
    calibrated_win_probability,
    m6m7_unvalidated_reason,
)
from ml.validation_scope import (
    QUALIFIER_RETROSPECTIVE_EVIDENCE,
    REASON_OUTSIDE_MEASURED_WINDOW,
    REASON_TRAINING_SEASON,
    evidence_qualifier,
    in_measured_window,
    is_training_season,
    season_of_event,
)
from ml.views.event_analysis import (
    NOT_VALIDATED,
    POLICY_M5V2,
    POLICY_RAW_EPA,
    VALIDATED_AS_MEASURED,
    VALIDATED_RAW_EPA,
    ordering_validation,
)

T0 = datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc)
SWITCH, LAST = T0, T0 + timedelta(hours=6)


class _Team:
    def __init__(self, epa: bool) -> None:
        self.epa_total_present = epa


FULL = [_Team(True)] * 3


# --- the pure rules ----------------------------------------------------------------------------------------------


def test_seasons():
    assert season_of_event("2025miket") == 2025 and season_of_event("bad") is None
    assert is_training_season(2024) and is_training_season(2025)
    assert not is_training_season(2026) and not is_training_season(2027) and not is_training_season(None)
    assert evidence_qualifier(2025) is None
    assert evidence_qualifier(2026) == evidence_qualifier(2027) == QUALIFIER_RETROSPECTIVE_EVIDENCE


def test_a_training_season_win_probability_is_never_validated():
    assert m6m7_unvalidated_reason("qualification", FULL, FULL, 2025) == REASON_TRAINING_SEASON
    assert m6m7_unvalidated_reason("qualification", FULL, FULL, 2024) == REASON_TRAINING_SEASON
    assert m6m7_unvalidated_reason("qualification", FULL, FULL, 2026) is None
    assert m6m7_unvalidated_reason("qualification", FULL, FULL, 2027) is None
    # The earlier reasons still come first: a 2025 playoff match is playoff_scope, an EPA gap is epa_incomplete.
    assert m6m7_unvalidated_reason("playoff", FULL, FULL, 2025) == REASON_PLAYOFF_SCOPE
    assert m6m7_unvalidated_reason("qualification", FULL, [_Team(False)] * 3, 2025) == REASON_EPA_INCOMPLETE


def _model() -> ServedModelInfo:
    return ServedModelInfo(model_type="win_prob_xgb_calibrated", model_version="1", model_version_tag="d18",
                           model_sha256="c" * 64, training_dataset_hash="a" * 64, provenance={})


def test_validated_values_carry_the_retrospective_qualifier_and_training_values_are_unvalidated():
    validated = calibrated_win_probability(0.65, None, _model(), 2026)
    assert validated.validation.status == STATUS_VALIDATED_QUALIFICATION
    assert QUALIFIER_RETROSPECTIVE_EVIDENCE in validated.validation.reasons
    in_sample = calibrated_win_probability(0.65, REASON_TRAINING_SEASON, _model(), 2025)
    assert in_sample.validation.status == STATUS_NOT_VALIDATED and in_sample.validated_value is None
    assert in_sample.unvalidated_value == 0.65 and in_sample.unvalidated_reason == REASON_TRAINING_SEASON


def test_the_measured_window_is_after_the_switch_and_through_the_last_qualification_match():
    assert not in_measured_window(SWITCH, SWITCH, LAST)  # at the switch: not yet passed
    assert in_measured_window(SWITCH + timedelta(minutes=1), SWITCH, LAST)
    assert in_measured_window(LAST, SWITCH, LAST)
    assert not in_measured_window(LAST + timedelta(minutes=1), SWITCH, LAST)  # selection, playoffs, later
    assert not in_measured_window(LAST, None, LAST) and not in_measured_window(LAST, SWITCH, None)


def test_validated_as_measured_only_where_it_was_measured():
    inside = SWITCH + timedelta(hours=1)
    assert ordering_validation(POLICY_M5V2, "2026mose", inside, SWITCH, LAST) == (VALIDATED_AS_MEASURED, None)
    assert ordering_validation(POLICY_M5V2, "2027abcd", inside, SWITCH, LAST) == (VALIDATED_AS_MEASURED, None)
    assert ordering_validation(POLICY_M5V2, "2025miket", inside, SWITCH, LAST) == (NOT_VALIDATED, REASON_TRAINING_SEASON)
    after = LAST + timedelta(minutes=1)  # the selection moment and later
    assert ordering_validation(POLICY_M5V2, "2026mose", after, SWITCH, LAST) == (NOT_VALIDATED,
                                                                                REASON_OUTSIDE_MEASURED_WINDOW)
    assert ordering_validation(POLICY_RAW_EPA, "2025miket", after, None, LAST) == (VALIDATED_RAW_EPA, None)


# --- the routes, on real events (isolated database copy, D18 configuration) ----------------------------------------

ARTIFACTS = Path("C:/Dev/StratAI-artifacts")


@pytest.fixture(scope="module")
def client():
    from tests.test_live_epa import _isolated_db_name

    if _isolated_db_name() is None or not (ARTIFACTS / "ml_registry").exists():
        pytest.skip("needs an isolated stratai_* database copy and the registered D18 artifacts")
    from scripts.local_test_env import PINS

    saved = {k: os.environ.get(k) for k in [*PINS, "ACCESS_POLICY"]}
    os.environ.update({k: v for k, v in PINS.items() if k != "DATABASE_URL"})
    os.environ["ACCESS_POLICY"] = "open"
    try:
        from fastapi.testclient import TestClient

        from api import create_app
        from data.config import Settings

        yield TestClient(create_app(Settings()))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _event_with_quals(client, season: int) -> str | None:
    events = client.get("/events", params={"season": season})
    if events.status_code != 200:
        return None
    for event in events.json()["events"]:
        matches = client.get(f"/events/{event['event_key']}/matches").json().get("matches", [])
        if sum(m["competition_level"] == "qualification" and m["result"] is not None for m in matches) < 40:
            continue
        # D18 refuses "as of now" where a team's latest prior event has no valid row (docs/ml_models.md section 9,
        # limitation 5: the 2026 Israeli events); such an event cannot show a label at all, so pick another.
        if client.get(f"/events/{event['event_key']}/analysis").status_code == 200:
            return event["event_key"]
    return None


def test_a_training_season_event_is_labelled_in_sample_on_every_model_route(client):
    event = _event_with_quals(client, 2025)
    if event is None:
        pytest.skip("no 2025 event with qualification results in this copy")
    analysis = client.get(f"/events/{event}/analysis").json()
    assert analysis["ordering"]["model"] == POLICY_M5V2  # after qualification: the switch has passed
    assert analysis["ordering"]["validation_status"] == NOT_VALIDATED
    assert analysis["ordering"]["evidence"].startswith(REASON_TRAINING_SEASON)
    forecast = client.get(f"/events/{event}/qualification-forecast").json()
    assert all(m["validation_status"] == STATUS_NOT_VALIDATED for m in forecast["matches"])
    assert {m["not_validated_reason"] for m in forecast["matches"]} <= {REASON_TRAINING_SEASON, REASON_EPA_INCOMPLETE}
    assert all(t["record_validation_status"] == STATUS_NOT_VALIDATED for t in forecast["teams"])
    qual = next(m for m in client.get(f"/events/{event}/matches").json()["matches"]
                if m["competition_level"] == "qualification")
    win = client.get(f"/predictions/matches/{qual['match_key']}/win-probability").json()
    assert win["validation_status"] == STATUS_NOT_VALIDATED
    assert win["not_validated_reason"] in (REASON_TRAINING_SEASON, REASON_EPA_INCOMPLETE)


def test_a_2026_event_is_validated_as_measured_only_during_qualification(client):
    event = _event_with_quals(client, 2026)
    if event is None:
        pytest.skip("no 2026 event with qualification results in this copy")
    after = client.get(f"/events/{event}/analysis").json()  # now: long after qualification
    assert after["ordering"]["validation_status"] == NOT_VALIDATED
    assert after["ordering"]["evidence"].startswith(REASON_OUTSIDE_MEASURED_WINDOW)
    quals = sorted((m for m in client.get(f"/events/{event}/matches").json()["matches"]
                    if m["competition_level"] == "qualification"), key=lambda m: m["scheduled_time"])
    last = datetime.fromisoformat(quals[-1]["scheduled_time"])
    during = client.get(f"/events/{event}/analysis", params={"as_of": last.isoformat()}).json()
    if during["ordering"]["switch_point_passed"]:
        assert during["ordering"]["validation_status"] == VALIDATED_AS_MEASURED
