"""Regression tests for landing the untouched response body.

The pipeline used to land `model_dump(mode="json", by_alias=True)` -- a projection
through the client models -- so any field a model did not declare was dropped before
landing and was invisible to the landing checksum too. Connectors now return
`SourceResponse(raw, parsed)` and the pipeline lands `raw`.

Two things are guarded here, and the second is the dangerous one:

  1. Undeclared fields survive into landing, and a change confined to one is
     detected as a new payload version (previously it was not).
  2. A raw TBA match payload yields a full 3-team roster. TBA's real roster field
     is `team_keys`; the old projection renamed it to the model's alias `teams`,
     and staging read only that name. Reading a raw body with the old code gave an
     empty roster with a real score, and it failed *silently* -- the quality layer
     deliberately does not flag an empty alliance (an unplayed playoff match has
     none), so every match_teams row would have been pruned while the run reported
     success. This is the permanent guard against that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from data.clients.schemas import Match
from data.clients.source_connector import SourceResponse
from data.landing.raw_writer import compute_payload_checksum
from data.staging import (
    normalize_match,
    tba_alliance_team_keys,
    validate_match,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tba_match_2024casj_qm1.json"


@pytest.fixture(scope="module")
def real_match() -> dict[str, Any]:
    """A genuinely captured TBA match payload (2024casj_qm1), untouched."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ===========================================================================
# The roster trap: TBA sends `team_keys`, not `teams`.
# ===========================================================================


def test_real_tba_payload_uses_team_keys_not_teams(real_match):
    # Pins the premise the rest of this file rests on. If TBA ever renames the
    # field, this fails first and explains why everything else does.
    red = real_match["alliances"]["red"]
    assert "team_keys" in red
    assert "teams" not in red
    assert len(red["team_keys"]) == 3


def test_raw_match_payload_yields_a_full_roster(real_match):
    """THE regression test: a raw payload must not normalize to an empty roster."""
    match = normalize_match("tba", real_match)

    assert match.match_key == "2024casj_qm1"
    assert len(match.red_teams) == 3, "raw payload produced an incomplete red alliance"
    assert len(match.blue_teams) == 3, "raw payload produced an incomplete blue alliance"
    assert match.red_teams == [841, 8546, 253]
    # A scored match with an empty roster is the exact silent failure this guards.
    assert match.red_score is not None
    assert match.red_teams != []


def test_raw_match_payload_validates_cleanly(real_match):
    assert validate_match("tba", real_match) == []


def test_projection_shaped_payloads_still_work(real_match):
    """Payloads landed before this change used the alias `teams`; they must still load.

    The landing layer never rewrites history, so both shapes are present in
    raw_source_payloads permanently. The legacy shape is built by hand here
    (renaming `team_keys` to `teams` in a deep copy of the real payload)
    rather than via `Match.model_dump(by_alias=True)`: that alias was itself
    the bug this file guards against (see MatchAllianceResult's docstring in
    data/clients/schemas.py) and, now corrected, no longer produces the
    legacy shape at all.
    """
    projected = json.loads(json.dumps(real_match))
    for color in ("red", "blue"):
        alliance = projected["alliances"][color]
        alliance["teams"] = alliance.pop("team_keys")
    assert "teams" in projected["alliances"]["red"]          # the old shape
    assert "team_keys" not in projected["alliances"]["red"]

    match = normalize_match("tba", projected)
    assert match.red_teams == [841, 8546, 253]
    assert validate_match("tba", projected) == []


def test_alliance_helper_prefers_team_keys_but_accepts_teams():
    assert tba_alliance_team_keys({"team_keys": ["frc1114"]}) == ["frc1114"]
    assert tba_alliance_team_keys({"teams": ["frc254"]}) == ["frc254"]
    # team_keys wins when a payload somehow carries both.
    assert tba_alliance_team_keys({"team_keys": ["frc1"], "teams": ["frc2"]}) == ["frc1"]
    assert tba_alliance_team_keys({}) == []
    assert tba_alliance_team_keys(None) == []
    # Non-list values are passed through so each caller's own type check applies.
    assert tba_alliance_team_keys({"team_keys": "nonsense"}) == "nonsense"


def test_empty_roster_still_normalizes_to_an_empty_alliance(real_match):
    # An unplayed playoff match legitimately has no roster; that must stay valid
    # rather than being confused with the failure above.
    upcoming = {**real_match, "alliances": {"red": {"score": None, "team_keys": []},
                                            "blue": {"score": None, "team_keys": []}}}
    match = normalize_match("tba", upcoming)
    assert match.red_teams == []
    assert match.blue_teams == []


# ===========================================================================
# Undeclared fields survive, and change detection now sees them.
# ===========================================================================


def test_undeclared_fields_are_dropped_by_the_projection_but_kept_in_raw(real_match):
    """Documents exactly what the old approach lost."""
    projected = Match.model_validate(real_match).model_dump(mode="json", by_alias=True)

    # score_breakdown is the per-match scoring detail Phase 3 metrics need.
    assert real_match["score_breakdown"] is not None
    assert "score_breakdown" not in projected

    dropped = set(real_match) - set(projected)
    assert {"score_breakdown", "videos", "actual_time", "predicted_time"} <= dropped
    # And the raw body is substantially larger than what used to be stored.
    assert len(json.dumps(real_match)) > 3 * len(json.dumps(projected))


def test_change_confined_to_an_undeclared_field_changes_the_checksum(real_match):
    """The half of the bug that silently broke change detection.

    Two payloads differing only in an undeclared field checksummed identically
    under the projection, so the landing layer treated a genuine update as a
    duplicate and never landed a new version.
    """
    changed = json.loads(json.dumps(real_match))
    changed["score_breakdown"]["red"]["totalPoints"] = 99999

    # Landing raw: the change is visible.
    assert compute_payload_checksum(real_match) != compute_payload_checksum(changed)

    # Landing the projection: the change is invisible -- identical checksums.
    project = lambda payload: Match.model_validate(payload).model_dump(mode="json", by_alias=True)
    assert compute_payload_checksum(project(real_match)) == compute_payload_checksum(project(changed))


def test_checksum_algorithm_is_unchanged_and_still_order_independent(real_match):
    # Only the checksum's *input* changed with this work, never the algorithm --
    # idempotence depends on it staying deterministic and key-order independent.
    reordered = json.loads(json.dumps(real_match))
    reordered = dict(reversed(list(reordered.items())))
    assert compute_payload_checksum(real_match) == compute_payload_checksum(reordered)


# ===========================================================================
# The SourceResponse envelope.
# ===========================================================================


def test_source_response_keeps_raw_and_parsed_distinct(real_match):
    response = SourceResponse(real_match, Match.model_validate(real_match))

    # raw is the wire body, byte-for-byte in content.
    assert response.raw is real_match
    assert "score_breakdown" in response.raw
    assert response.raw["alliances"]["red"]["team_keys"] == ["frc841", "frc8546", "frc253"]

    # parsed is the typed view, with the model's own field names.
    assert response.parsed.key == "2024casj_qm1"
    assert response.parsed.alliances.red.team_keys == ["frc841", "frc8546", "frc253"]
    assert response.parsed.competition_level == "qm"   # model name for comp_level
