"""P7-M3 regression: the win-probability, ranking, synergy and qualification-forecast routes serve exactly what
they served before Phase 7 changed them (P7-M3 acceptance; R7: changes are additive only).

tests/fixtures/p7_m3_predictions_golden.json was captured from the routes *before* any P7-M3 change, with the
clock frozen, on the synthetic fixtures of tests/test_api_predictions.py (real registry-load-predict pipeline,
synthetic models; no result here is evidence about model quality). Every key the old responses had must still be
there with the same value; new keys are allowed (additive). Artifact sha256 values are excluded: they identify the
temporary registry, not what is served.

Regenerate only on purpose, and only before changing the routes: P7_M3_WRITE_GOLDEN=1 pytest <this file>.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tests.test_api_predictions import (  # noqa: F401  (fixtures)
    _MATCH_PLAYED,
    _MATCH_PLAYOFF,
    _S_EVENT,
    _TEAM_BLUE,
    _TEAM_EMPTY,
    _TEAM_RED,
    _statbotics_reference_epa_source,  # autouse there; imported so it applies here too
    client,
    database,
    registry_dir,
    requires_db,
)

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "p7_m3_predictions_golden.json"
FROZEN = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
_VOLATILE = {"model_sha256", "win_prob_model_sha256", "ranking_model_sha256"}

pytestmark = requires_db


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D102
        return FROZEN if tz is not None else FROZEN.replace(tzinfo=None)


@pytest.fixture
def frozen(monkeypatch):
    import api.routes.common as common
    import api.routes.predictions as predictions

    monkeypatch.setattr(predictions, "datetime", _FrozenDatetime)  # the deprecated ranking route's own now()
    monkeypatch.setattr(common, "datetime", _FrozenDatetime)       # parse_as_of's default now (P7-M3)


def _requests() -> list[tuple[str, str, str, dict[str, Any] | None]]:
    alliances = {"event_key": _S_EVENT, "red_team_numbers": _TEAM_RED, "blue_team_numbers": _TEAM_BLUE}
    return [
        ("match_qualification", "GET", f"/predictions/matches/{_MATCH_PLAYED}/win-probability", None),
        ("match_playoff", "GET", f"/predictions/matches/{_MATCH_PLAYOFF}/win-probability", None),
        ("adhoc_unspecified", "POST", "/predictions/win-probability", alliances),
        ("adhoc_qualification", "POST", "/predictions/win-probability", {**alliances, "match_context": "qualification"}),
        ("adhoc_playoff", "POST", "/predictions/win-probability", {**alliances, "match_context": "playoff"}),
        ("adhoc_epa_incomplete", "POST", "/predictions/win-probability",
         {**alliances, "blue_team_numbers": _TEAM_EMPTY, "match_context": "qualification"}),
        ("ranking", "GET", f"/predictions/events/{_S_EVENT}/ranking", None),
        ("synergy", "POST", "/predictions/alliance-synergy", {"event_key": _S_EVENT, "team_numbers": _TEAM_RED}),
        ("qualification_forecast", "GET",
         f"/events/{_S_EVENT}/qualification-forecast?as_of={FROZEN.isoformat().replace('+', '%2B')}", None),
    ]


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _capture(client) -> dict[str, Any]:
    out = {}
    for name, method, url, body in _requests():
        response = client.get(url) if method == "GET" else client.post(url, json=body)
        out[name] = {"status": response.status_code, "body": _strip(response.json())}
    return out


def _contained(old: Any, new: Any, path: str = "") -> list[str]:
    """Paths where `new` drops or changes something `old` had (new keys are allowed: additive)."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [path]
        return [p for key in old for p in (_contained(old[key], new[key], f"{path}/{key}") if key in new
                                           else [f"{path}/{key} (removed)"])]
    if isinstance(old, list):
        if not isinstance(new, list) or len(old) != len(new):
            return [path]
        return [p for i, (a, b) in enumerate(zip(old, new)) for p in _contained(a, b, f"{path}/{i}")]
    return [] if old == new else [f"{path}: {old!r} -> {new!r}"]


def test_served_values_are_unchanged_from_before_phase7(client, frozen):
    captured = _capture(client)
    # Every request is a success case: a refusal here means the fixture is wrong, never a baseline to keep.
    assert {name: r["status"] for name, r in captured.items() if r["status"] != 200} == {}
    if os.environ.get("P7_M3_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps({"frozen_now": FROZEN.isoformat(), "responses": captured}, indent=1,
                                     sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden written")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["responses"]
    assert set(golden) == set(captured)
    problems = {name: _contained(golden[name], captured[name]) for name in golden}
    assert not any(problems.values()), {k: v for k, v in problems.items() if v}
