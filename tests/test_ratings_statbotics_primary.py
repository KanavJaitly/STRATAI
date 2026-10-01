"""D18's Statbotics-primary provider (ml.ratings.statbotics_primary), on synthetic facts.

Synthetic by design: these pin the frozen rules of .agent/phase4/D18_SOURCE_SPEC.md
§1-3 (selection, validity, availability, fallback scope), not any real-data result.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ml.ratings.provider import TeamEventEpa, TeamEventFacts, Unavailable
from ml.ratings.statbotics_primary import (
    FALLBACK_EVENT,
    RULE_A1_SEASON_END,
    RULE_A2_WEEK_ONE,
    VALUE_SOURCE_FALLBACK,
    VALUE_SOURCE_STATBOTICS,
    SilentFallbackError,
    StatboticsPrimaryEpa,
    StatboticsTeamEvent,
)

T0 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def day(n: int) -> datetime:
    return T0 + timedelta(days=n)


def row(total: float = 30.0, *, qual: int | None = 10, played: int | None = 12, season: int = 2026) -> StatboticsTeamEvent:
    part = None if total is None else total / 3
    return StatboticsTeamEvent(season, total, part, part, part, played, qual)


class _Fallback:
    source = "stratai"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def point_in_time_epa(self, team, target_event_key, as_of):
        self.calls.append((team, target_event_key))
        return TeamEventEpa(team, "2026isde2", 40.0, 10.0, 20.0, 10.0, "stratai", False, {"available_at": 1})

    def provenance(self):
        return {"source": "stratai", "chain_manifest": "chain_x.json"}


def provider(statbotics, facts, *, strict=True, fallback=None) -> StatboticsPrimaryEpa:
    return StatboticsPrimaryEpa(statbotics, facts, season_end={2025: day(-200), 2026: day(120)},
                                week_one_complete={2025: day(-500), 2026: day(7)},
                                fallback=fallback or _Fallback(), strict=strict)


def facts(*items: tuple[str, int, int]) -> list[TeamEventFacts]:
    return [TeamEventFacts(key, day(end), day(last)) for key, end, last in items]


def test_d13_order_and_a2_value_served_with_provenance():
    p = provider({(1, "2026a"): row(30), (1, "2026b"): row(50)},
                 {1: facts(("2026a", 10, 10), ("2026b", 20, 20))})
    found = p.point_in_time_epa(1, "2026c", day(30))
    assert isinstance(found, TeamEventEpa)
    assert (found.event_key, found.total, found.source) == ("2026b", 50, VALUE_SOURCE_STATBOTICS)
    assert found.provenance["rule"] == RULE_A2_WEEK_ONE and found.provenance["skipped"] == []


def test_a1_season_end_value_skipped_until_season_end_then_next_candidate():
    p = provider({(1, "2026a"): row(30), (1, "2026cmp"): row(70, qual=0)},
                 {1: facts(("2026a", 10, 10), ("2026cmp", 40, 40))})
    found = p.point_in_time_epa(1, "2026off", day(60))  # after the event, before T_end(2026)=day 120
    assert found.event_key == "2026a" and found.provenance["skipped"] == ["2026cmp"]
    assert p.diagnostics[f"skipped:{RULE_A1_SEASON_END}"] == 1
    after = p.point_in_time_epa(1, "2026off", day(121))
    assert after.event_key == "2026cmp" and after.provenance["rule"] == RULE_A1_SEASON_END


def test_missing_qual_count_is_treated_as_season_end():
    assert row(qual=None).rule == RULE_A1_SEASON_END and row(qual=0).rule == RULE_A1_SEASON_END


def test_a2_waits_for_week_one_statistics():
    p = provider({(1, "2026w1"): row(30)}, {1: facts(("2026w1", 3, 3))})
    early = p.point_in_time_epa(1, "2026w2", day(5))  # T_w1(2026) = day 7
    assert isinstance(early, Unavailable) and p.diagnostics["withheld:availability"] == 1
    assert p.point_in_time_epa(1, "2026w2", day(8)).event_key == "2026w1"


def test_availability_is_strict():
    p = provider({(1, "2026w1"): row(30)}, {1: facts(("2026w1", 3, 3))})
    assert isinstance(p.point_in_time_epa(1, "2026x", day(7)), Unavailable)  # available_at == as_of


@pytest.mark.parametrize("statbotics", [{}, {(1, "2026b"): row(played=0)}, {(1, "2026b"): row(total=None)}])
def test_missing_or_invalid_candidate_is_a_hard_error_not_an_older_event(statbotics):
    statbotics = {(1, "2026a"): row(30), **statbotics}
    f = {1: facts(("2026a", 10, 10), ("2026b", 20, 20))}
    with pytest.raises(SilentFallbackError):
        provider(statbotics, f).point_in_time_epa(1, "2026c", day(30))
    lenient = provider(statbotics, f, strict=False)
    assert isinstance(lenient.point_in_time_epa(1, "2026c", day(30)), Unavailable)
    assert lenient.hard_errors[0]["candidate"] == "2026b"


def test_fallback_only_for_the_fallback_event_and_labelled():
    fallback = _Fallback()
    p = provider({(1, "2026a"): row(30)}, {1: facts(("2026a", 10, 10))}, fallback=fallback)
    found = p.point_in_time_epa(1, FALLBACK_EVENT, day(130))
    assert found.source == VALUE_SOURCE_FALLBACK and found.provenance["fallback_provider"] == "stratai"
    assert p.point_in_time_epa(1, "2026other", day(130)).source == VALUE_SOURCE_STATBOTICS
    assert fallback.calls == [(1, FALLBACK_EVENT)]


def test_no_prior_event_is_withheld_legitimately():
    p = provider({}, {1: facts(("2026a", 10, 10))})
    assert isinstance(p.point_in_time_epa(1, "2026a", day(30)), Unavailable)  # the target itself is excluded
    assert p.diagnostics["withheld:no_prior_event"] == 1 and not p.hard_errors


def test_provenance_names_spec_fallback_and_counts():
    p = provider({(1, "2026a"): row(30)}, {1: facts(("2026a", 10, 10))})
    p.point_in_time_epa(1, "2026b", day(30))
    info = p.provenance()
    assert info["freeze_commit"] == "ec1b0af" and info["fallback_event"] == FALLBACK_EVENT
    assert info["lookup_diagnostics"] == {f"served:statbotics:{RULE_A2_WEEK_ONE}": 1}
