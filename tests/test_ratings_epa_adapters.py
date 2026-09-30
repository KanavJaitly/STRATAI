"""2024-2026 breakdown adapters, including the 2025 shared-breakdown decision.

Hand-computed from each adapter's formulas in spec §6; the 2024 case uses the
real TBA payload for 2024casj qm1 already in tests/fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml.ratings.epa import exclusions as ex
from ml.ratings.epa.adapters import (
    REQUIRED_FIELDS,
    BreakdownRejection,
    CleanedAlliance,
    actual_vector,
    clean_alliance,
    empty_alliance,
    post_clean,
)
from ml.ratings.epa.constants import TIEBREAKER
from ml.ratings.epa.validation import prepare_season
from ml.ratings.epa.year_stats import compute_year_stats
from ml.ratings.epa.inputs import SeasonInput
from ratings_epa_support import alliance, bd2024, bd2025, bd2026, event, match, score2025

FIXTURE = Path(__file__).parent / "fixtures" / "tba_match_2024casj_qm1.json"


def _clean(season: int, score: int, bd: dict | None) -> CleanedAlliance:
    result = clean_alliance(season, score, bd)
    assert isinstance(result, CleanedAlliance), result
    return result


def test_2024_real_payload_2024casj_qm1() -> None:
    payload = json.loads(FIXTURE.read_text())
    red = _clean(2024, payload["alliances"]["red"]["score"], payload["score_breakdown"]["red"])
    blue = _clean(2024, payload["alliances"]["blue"]["score"], payload["score_breakdown"]["blue"])
    # red: leave 4; teleop speaker 11 -> 22; park 1 + on stage 3 = 4; 4 + 22 + 4 = 30, no fouls
    assert red.score == 30 and red.foul == 0
    assert red.values == (30, 4, 22, 4, False, False, None, 0, 4, 0, 22, 22, 0, 1, 3, 0, 0, 0)
    assert red.teleop_residual == 0
    # blue: leave 2 + 1 auto speaker (5) = 7; teleop speaker 8 -> 16; park 1 + on stage 3 = 4
    assert blue.values == (27, 7, 16, 4, False, False, None, 0, 2, 5, 16, 21, 0, 1, 3, 0, 0, 0)


def test_2024_amplified_notes_and_fouls() -> None:
    bd = bd2024(teleop_speaker=4, amplified=2, teleop_amp=3, foul=5, adjust=-2, coop=True, melody=True)
    # teleop = 3 amp + 2*(4+2) + 3*2 = 3 + 12 + 6 = 21; foul = 5 + (-2) = 3; score = 21 + 3 = 24
    a = _clean(2024, 24, bd)
    assert a.foul == 3 and a.no_foul == 21
    assert a.values[1:8] == (0, 21, 0, True, False, None, 1)
    assert a.values[8 + 3] == 12 + 6  # speaker points: 0 auto + 18 teleop
    assert a.values[8 + 4] == 2  # amplified notes is a count


def test_residual_is_added_to_teleop() -> None:
    bd = bd2024(leave=2, teleop_speaker=5)  # components sum to 2 + 10 = 12
    a = _clean(2024, 15, bd)  # TBA says 15 (e.g. a points category the adapter does not read)
    assert a.teleop_residual == 3
    assert a.values[:4] == (15, 2, 13, 0)  # teleop 10 + 3


def test_2025_coral_levels_algae_and_trough() -> None:
    bd = bd2025(mobility=6, auto_coral_points=21, teleop_coral_points=30, auto_rows=(2, 1, 0, 1),
                teleop_rows=(5, 3, 2, 4), processor=3, net=2, barge=12)
    a = _clean(2025, score2025(bd), bd)
    # auto = 6 + 21; teleop = 30 + 6*3 + 4*2 = 56; endgame = barge 12
    assert a.values[:4] == (27 + 56 + 12, 27, 56, 12)
    # L1 = auto trough 1 + teleop trough 4 (trough NOT reduced by auto, as the reference does)
    # L2 = 0 + (2 - 0); L3 = 1 + (3 - 1); L4 = 2 + (5 - 2)
    assert a.values[8:] == (21, 30, 5, 2, 3, 5, 3, 18, 8, 12)


def test_2026_hub_tower_and_tiebreaker() -> None:
    bd = bd2026(auto_fuel=10, transition=4, shifts=(1, 2, 3, 4), endgame_fuel=5, auto_tower=15,
                endgame_tower=20, energized=True, foul=3)
    a = _clean(2026, 10 + 4 + 10 + 5 + 15 + 20 + 3, bd)
    # auto 10+15, teleop 4+1+2+3+4, endgame 5+20; tiebreaker = no-foul points
    assert a.values[:8] == (64, 25, 14, 25, True, False, False, 64)
    assert a.values[8:] == (10, 15, 4, 3, 7, 5, 20, None, None, None)


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_every_required_field_is_enforced(season: int) -> None:
    builders = {2024: bd2024, 2025: bd2025, 2026: bd2026}
    for spec in REQUIRED_FIELDS[season]:
        bd = json.loads(json.dumps(builders[season]()))
        node = bd
        for part in spec.path[:-1]:
            node = node[part]
        del node[spec.path[-1]]
        result = clean_alliance(season, 50, bd)
        assert isinstance(result, BreakdownRejection)
        assert result.code == ex.MALFORMED_BREAKDOWN
        assert ".".join(spec.path) in result.detail


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("foulPoints", True, "foulPoints is bool, expected int"),
        ("foulPoints", "3", "foulPoints is str, expected int"),
        ("autoLeavePoints", 2.0, "autoLeavePoints is float, expected int"),
        ("melodyBonusAchieved", 1, "melodyBonusAchieved is int, expected bool"),
        ("adjustPoints", None, "adjustPoints is NoneType, expected int"),
    ],
)
def test_wrong_types_are_rejected_not_coerced(field: str, value: object, message: str) -> None:
    bd = {**bd2024(), field: value}
    result = clean_alliance(2024, 50, bd)
    assert isinstance(result, BreakdownRejection) and result.detail == message


def test_nested_object_missing_or_wrong_type() -> None:
    bd = bd2026()
    del bd["hubScore"]
    assert clean_alliance(2026, 50, bd) == BreakdownRejection(ex.MALFORMED_BREAKDOWN, "hubScore missing")
    bd = {**bd2026(), "hubScore": [1, 2]}
    assert clean_alliance(2026, 50, bd) == BreakdownRejection(ex.MALFORMED_BREAKDOWN, "hubScore is list, expected object")


def test_overwritten_2025_field_is_not_required() -> None:
    bd = bd2025(processor=1)
    del bd["coopertitionCriteriaMet"]
    assert isinstance(clean_alliance(2025, score2025(bd), bd), CleanedAlliance)


def test_missing_breakdown_on_a_scored_alliance_is_rejected() -> None:
    assert clean_alliance(2024, 12, None) == BreakdownRejection(ex.MISSING_BREAKDOWN, "score 12 with no score_breakdown")


def test_zero_score_is_the_empty_breakdown_whatever_tba_sent() -> None:
    for bd in (None, bd2024(leave=4), {"garbage": True}):
        a = clean_alliance(2024, 0, bd)
        assert a == empty_alliance(0)
    empty = empty_alliance(0)
    # components unknown (None, excluded from means); rp False (counted as 0), exactly the reference's dict
    assert empty.values == (None, None, None, None, False, False, False) + (None,) * 11
    assert empty.foul is None and empty.empty


def test_actual_vector_is_float32_with_none_as_zero() -> None:
    vec = actual_vector(_clean(2024, 24, bd2024(teleop_speaker=12, melody=True)))
    assert vec.dtype == np.float32
    assert vec.tolist()[:8] == [24.0, 0.0, 24.0, 0.0, 1.0, 0.0, 0.0, 0.0]  # rp_3 None -> 0
    assert actual_vector(empty_alliance(0)).tolist() == [0.0] * 18


# --- 2025 tiebreaker / shared empty breakdown (spec §11 decision) ------------


def test_2025_tiebreaker_is_recomputed_from_both_alliances() -> None:
    def alliance_with(processor: int) -> CleanedAlliance:
        bd = {**bd2025(processor=processor), "coopertitionCriteriaMet": True}  # API value is ignored
        return _clean(2025, score2025(bd), bd)

    both = post_clean(2025, alliance_with(2), alliance_with(3))
    assert [a.values[TIEBREAKER] for a in both] == [1, 1]
    one_short = post_clean(2025, alliance_with(1), alliance_with(5))
    assert [a.values[TIEBREAKER] for a in one_short] == [0, 0]


def test_2025_empty_alliance_gets_tiebreaker_zero_on_both_sides() -> None:
    """Decision (a): reproduced. The empty alliance's processor-algae count is
    unknown (None -> 0), so coopertition is impossible and both alliances get 0."""
    red, blue = post_clean(2025, empty_alliance(0), _clean(2025, 30, bd2025(processor=5)))
    assert red.values[TIEBREAKER] == 0 and blue.values[TIEBREAKER] == 0
    assert red.values[8 + 6] is None  # processor algae itself stays unknown


def test_empty_breakdowns_never_share_state() -> None:
    """Decision (b): the reference's single module-level empty dict carries writes
    from earlier matches and seasons in the same process. STRATAI's empty value
    is fresh and immutable, so a 2025 write cannot reach a later empty alliance."""
    red_2025, _ = post_clean(2025, empty_alliance(0), empty_alliance(0))
    assert red_2025.values[TIEBREAKER] == 0
    fresh = empty_alliance(0)
    assert fresh.values[TIEBREAKER] is None
    with pytest.raises(AttributeError):
        red_2025.values = ()  # type: ignore[misc]
    # post_clean for 2024/2026 leaves the tiebreaker alone
    red_2026, _ = post_clean(2026, empty_alliance(0), empty_alliance(0))
    assert red_2026.values[TIEBREAKER] is None


def _two_match_season(season: int, builder, zero_on_red: bool) -> SeasonInput:
    key = f"{season}wk1"
    a = alliance(season, (1, 2, 3), builder(), score=0) if zero_on_red else None
    m1 = match(f"{key}_qm1", key, 100, a or alliance(season, (1, 2, 3), _nonzero(season)),
               alliance(season, (4, 5, 6), _nonzero(season)))
    m2 = match(f"{key}_qm2", key, 200, alliance(season, (1, 5, 3), _nonzero(season)),
               alliance(season, (4, 2, 6), _nonzero(season, bump=1)))
    return SeasonInput(season=season, events=(event(key),), matches=(m1, m2))


def _nonzero(season: int, bump: int = 0) -> dict:
    return {2024: lambda: bd2024(teleop_speaker=5 + bump), 2025: lambda: bd2025(processor=3 + bump, net=2),
            2026: lambda: bd2026(auto_fuel=7 + bump)}[season]()


def test_2026_statistics_do_not_inherit_a_2025_tiebreaker_write() -> None:
    """Run 2025 then 2026 in one process, both with a zero-score alliance. In the
    reference the 2026 empty alliance would hold tiebreaker 0 left by 2025 and so
    enter 2026's tiebreaker mean; here it is None and is excluded."""
    prepared_2025 = prepare_season(_two_match_season(2025, bd2025, zero_on_red=True))
    assert prepared_2025.stream[0].red.values[TIEBREAKER] == 0  # type: ignore[union-attr]
    prepared_2026 = prepare_season(_two_match_season(2026, bd2026, zero_on_red=True))
    empty = prepared_2026.stream[0].red
    assert empty is not None and empty.empty and empty.values[TIEBREAKER] is None
    stats = compute_year_stats(2026, prepared_2026.stream)
    # three non-empty alliances with tiebreaker (no-foul) 7, 7, 8; the empty one is excluded
    assert stats.tiebreaker_mean == 7.33  # r(22 / 3, 2)
    # every empty alliance is counted as a possible divergence
    assert prepared_2026.collector.report().possible_divergences[ex.SHARED_EMPTY_BREAKDOWN] == 1
