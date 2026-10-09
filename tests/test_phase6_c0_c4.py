"""C0 (2027 P6-M1 check) and C4 (PX-1b harness pointers), approved 2026-10-08 (D9 v1 Part C).

Pure and SYNTHETIC: no database, no real 2027 data (none exists), not evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.alliances import Alliance
from data.rulesets import SeasonRuleset
from ml.playoffs.data import EventPlayoffs, RawPlayoffMatch
from tests.phase6_bracket_fixtures import ruleset

T = datetime(2027, 3, 6, 12, tzinfo=timezone.utc)
KEY = "2027synth"


def _alliance(seed: int) -> Alliance:
    picks = (100 * seed + 1, 100 * seed + 2, 100 * seed + 3)
    return Alliance(seed=seed, position=seed, name=f"Alliance {seed}", captain=picks[0], picks=picks, backup=None,
                    declines=())


def _team(seed: int) -> tuple[int, ...]:
    return (100 * seed + 1, 100 * seed + 2, 100 * seed + 3)


def synthetic_2027_event(*, last_qualification: datetime = T - timedelta(hours=2)) -> EventPlayoffs:
    """A 4-alliance, single-elimination SYNTHETIC event: seed 1 beats 4, 3 beats 2, then 1 beats 3 two-one."""
    def match(key, level, set_number, number, red, blue, winner, minutes):
        return RawPlayoffMatch(f"{KEY}_{key}", level, set_number, number, T + timedelta(minutes=minutes), winner,
                               _team(red), _team(blue))
    matches = (match("sf1m1", "semifinal", 1, 1, 1, 4, "red", 0), match("sf2m1", "semifinal", 2, 1, 2, 3, "blue", 10),
               match("f1m1", "final", 1, 1, 1, 3, "blue", 20), match("f1m2", "final", 1, 2, 1, 3, "red", 30),
               match("f1m3", "final", 1, 3, 1, 3, "red", 40))
    return EventPlayoffs(KEY, 2027, tuple(_alliance(s) for s in range(1, 5)), matches, last_qualification, 20)


# --- C0 -------------------------------------------------------------------------------------------------------


def test_c0_runs_the_frozen_m1_check_on_2027_only(monkeypatch):
    import data.rankings
    import ml.playoffs.data
    from scripts.phase6_playoff_track import run_m1

    def events(database, season):
        assert season == 2027, "C0 must read 2027 events only"
        return [synthetic_2027_event()]
    monkeypatch.setattr(ml.playoffs.data, "read_event_playoffs", events)
    ranks = {t: i for i, t in enumerate([101, 201, 301, 401, 102, 202, 302, 402, 103, 203, 303, 403], start=1)}
    monkeypatch.setattr(data.rankings, "read_final_ranks_for_season", lambda database, season: {KEY: ranks})
    result = run_m1(None, {2027: SeasonRuleset.model_validate(ruleset(2027))}, seasons=(2027,))
    assert list(result["seasons"]) == [2027]
    info = result["events"][KEY]
    assert info["status"] == "reproduced" and (info["winner_seed"], info["finalist_seed"]) == (1, 3)
    assert result["seasons"][2027]["selection_rule_violations"] == 0 and result["escalate"] is False


def test_c0_refuses_without_an_approved_2027_ruleset(monkeypatch):
    import data.rulesets
    from scripts.phase6_playoff_track import Blocked, require_rulesets

    monkeypatch.setattr(data.rulesets, "approved_seasons", lambda database: [2024, 2025, 2026])
    with pytest.raises(Blocked) as blocked:
        require_rulesets(None, (2027,))
    assert blocked.value.code == 2


def test_c0_refuses_without_2027_playoff_data(monkeypatch):
    import scripts.phase6_px1b as px1b_harness
    from scripts.phase6_playoff_track import Blocked, run_m1_2027

    monkeypatch.setattr(px1b_harness, "_playoff_matches", lambda database, season: 0)
    with pytest.raises(Blocked):
        run_m1_2027(None, {2027: SeasonRuleset.model_validate(ruleset(2027))})


def test_c0_has_its_own_record_and_needs_the_2027_ruleset():
    from scripts.phase6_playoff_track import RUN_SEASONS, RUNS

    assert RUNS["m1-2027"][0] == "p6_m1_ruleset_check_2027.json"
    assert RUNS["m1"][0] == "p6_m1_ruleset_check.json"  # the 2024-2026 record is untouched
    assert RUN_SEASONS["m1-2027"] == (2027,) and "m1" not in RUN_SEASONS
