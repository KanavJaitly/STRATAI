"""STRATAI's point-in-time EPA provider: decision D13 plus STRATAI availability.

The database-backed tests reuse test_epa_source_selection's sentinel world
(Championship division -> Einstein, DCMP division -> finals, simultaneous
events, a registered no-show) and require that the STRATAI provider selects
exactly the source event the Statbotics reference SQL selects, for every
appearance. The availability tests then show the one intended difference:
STRATAI removes a candidate whose value was not knowable at as_of.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ml.ratings import provider as pv
from ml.ratings.provider import (
    EPA_WITHHELD_NO_PRIOR_EVENT,
    EpaSourceNotConfigured,
    StaleEpaArtifacts,
    StatboticsPointInTimeEpa,
    StrataiPointInTimeEpa,
    StrataiTeamEventValue,
    TeamEventEpa,
    TeamEventFacts,
    default_point_in_time_provider,
    read_team_event_facts,
)
from test_epa_source_selection import EVENTS, NEXT_AS_OF, T_CHAMPS, TEAMS, at, world  # noqa: F401

UTC = timezone.utc


def _t(day: int, hour: int = 12) -> datetime:
    return datetime(2025, 3, day, hour, tzinfo=UTC)


def _value(total: float, available: datetime, season_end: bool = False) -> StrataiTeamEventValue:
    return StrataiTeamEventValue(total, 1.0, 2.0, 3.0, int(available.timestamp()), season_end)


# --- pure selection (no database) ------------------------------------------------


def _provider(values, facts) -> StrataiPointInTimeEpa:
    return StrataiPointInTimeEpa(values=values, facts=facts, provenance_info={})


def test_d13_order_latest_end_then_latest_match_then_event_key() -> None:
    facts = {1: [
        TeamEventFacts("2025old", _t(1, 0), _t(1, 18)),
        TeamEventFacts("2025div", _t(10, 0), _t(10, 9)),
        TeamEventFacts("2025ein", _t(10, 0), _t(10, 15)),
        TeamEventFacts("2025b", _t(5, 0), _t(5, 12)),
        TeamEventFacts("2025a", _t(5, 0), _t(5, 12)),
    ]}
    values = {(1, k.event_key): _value(i, _t(1, 0)) for i, k in enumerate(facts[1])}
    p = _provider(values, facts)
    assert p.point_in_time_epa(1, "2025next", _t(20)).event_key == "2025ein"  # same end date: later match wins
    assert p.point_in_time_epa(1, "2025ein", _t(10, 15)).event_key == "2025div"  # target excluded; division done
    assert p.point_in_time_epa(1, "2025div", _t(10, 9)).event_key == "2025a"  # div/ein unfinished; a < b by key
    found = p.point_in_time_epa(1, "2025next", _t(1, 12))  # nothing has ended yet
    assert not isinstance(found, TeamEventEpa) and found.reason == EPA_WITHHELD_NO_PRIOR_EVENT


def test_team_event_without_a_completed_match_or_end_date_is_never_a_candidate() -> None:
    facts = {1: [TeamEventFacts("2025noshow", _t(9, 0), None), TeamEventFacts("2025undated", None, _t(8)),
                 TeamEventFacts("2025real", _t(3, 0), _t(3))]}
    values = {(1, f.event_key): _value(10, _t(1, 0)) for f in facts[1]}
    assert _provider(values, facts).point_in_time_epa(1, "x", _t(20)).event_key == "2025real"


def test_missing_stratai_value_falls_back_like_a_missing_row() -> None:
    facts = {1: [TeamEventFacts("2025late", _t(9, 0), _t(9)), TeamEventFacts("2025early", _t(3, 0), _t(3))]}
    values = {(1, "2025early"): _value(10, _t(3))}
    assert _provider(values, facts).point_in_time_epa(1, "x", _t(20)).event_key == "2025early"


def test_unavailable_values_are_skipped_and_counted() -> None:
    facts = {1: [TeamEventFacts("2025late", _t(9, 0), _t(9)), TeamEventFacts("2025early", _t(3, 0), _t(3))]}
    values = {(1, "2025late"): _value(50, _t(30), season_end=True), (1, "2025early"): _value(10, _t(3))}
    p = _provider(values, facts)
    found = p.point_in_time_epa(1, "x", _t(20))
    assert found.event_key == "2025early" and found.total == 10  # the season-end value is not served in-season
    assert p.diagnostics["season_end"] == 1 and p.diagnostics["served"] == 1
    assert p.point_in_time_epa(1, "x", _t(31)).event_key == "2025late"  # after the season it is past information
    values[(1, "2025late")] = _value(50, _t(25))
    p = _provider(values, facts)
    assert p.point_in_time_epa(1, "x", _t(20)).event_key == "2025early"
    assert p.diagnostics["week_one_statistics"] == 1
    # strictly before: available exactly at as_of is not yet available
    assert p.point_in_time_epa(1, "x", _t(25)).event_key == "2025early"


def test_default_provider_is_explicit(monkeypatch) -> None:
    class S:
        epa_source = "stratai"
        stratai_epa_chain = None

    with pytest.raises(EpaSourceNotConfigured):
        default_point_in_time_provider(object(), S())  # type: ignore[arg-type]
    S.epa_source = "statbotics"
    assert isinstance(default_point_in_time_provider(object(), S()), StatboticsPointInTimeEpa)  # type: ignore[arg-type]


# --- chain artifacts --------------------------------------------------------------


def _write_chain(tmp_path: Path) -> Path:
    directory = tmp_path / "epa_2025_x"
    directory.mkdir()
    team_events = [{"team": 1, "event_key": "2025a", "epa": 12.5, "available_at": 100, "epa_is_season_end": False,
                    "components": {"auto_epa": 1.0, "teleop_epa": 2.0, "endgame_epa": 3.0}}]
    raw = json.dumps(team_events).encode()
    (directory / "team_events.json").write_bytes(raw)
    (directory / "manifest.json").write_text(json.dumps({
        "results_fingerprint": "f" * 64, "files": {"team_events.json": hashlib.sha256(raw).hexdigest()},
        "data_snapshot": {"raw_payload_ids_sha256": "s" * 64}}))
    chain = tmp_path / "chain_x.json"
    chain.write_text(json.dumps({"chain": [{"season": 2025, "directory": directory.name, "results_fingerprint": "f" * 64,
                                            "input_fingerprint": "i", "prior_source": "p"}]}))
    return chain


def test_chain_artifacts_load_and_are_integrity_checked(tmp_path, monkeypatch) -> None:
    chain = _write_chain(tmp_path)
    monkeypatch.setattr(pv, "read_team_event_facts", lambda database: {})
    loaded = StrataiPointInTimeEpa.from_chain_manifest(object(), chain, verify_snapshot=False)  # type: ignore[arg-type]
    assert loaded.values[(1, "2025a")].total == 12.5
    assert loaded.provenance()["seasons"][0]["prior_source"] == "p"
    (tmp_path / "epa_2025_x" / "team_events.json").write_text("[]")  # tampered
    with pytest.raises(StaleEpaArtifacts, match="digest"):
        StrataiPointInTimeEpa.from_chain_manifest(object(), chain, verify_snapshot=False)  # type: ignore[arg-type]


def test_stale_artifacts_are_refused(tmp_path, monkeypatch) -> None:
    chain = _write_chain(tmp_path)
    monkeypatch.setattr(pv, "read_team_event_facts", lambda database: {})

    class Read:
        snapshot = {"raw_payload_ids_sha256": "different" + "0" * 55}

    import ml.ratings.reader as reader

    monkeypatch.setattr(reader, "read_season_input", lambda database, season: Read())
    with pytest.raises(StaleEpaArtifacts, match="changed since the EPA replay"):
        StrataiPointInTimeEpa.from_chain_manifest(object(), chain)  # type: ignore[arg-type]


# --- parity with the Statbotics reference SQL on the sentinel world -----------------


def _stratai_over_world(db, *, season_end: set[str] = frozenset()) -> StrataiPointInTimeEpa:
    values = {}
    for key, (_season, _end, matches) in EVENTS.items():
        for team in {t for t, _ in matches}:
            last = max(when for t, when in matches if t == team)
            available = last + timedelta(days=3650) if key in season_end else last
            values[(team, key)] = _value(40.0, available, key in season_end)
    return StrataiPointInTimeEpa(values, read_team_event_facts(db, teams=list(TEAMS)), {})


def _appearances():
    for key, (_season, _end, matches) in EVENTS.items():
        for team, when in matches:
            yield team, key, when
    for team, as_of in NEXT_AS_OF.items():
        yield team, "9962zzznext", as_of


def test_stratai_selects_exactly_what_the_reference_sql_selects(world):  # noqa: F811
    stratai = _stratai_over_world(world)
    statbotics = StatboticsPointInTimeEpa(world)
    checked = 0
    for team, target, as_of in _appearances():
        a, b = stratai.point_in_time_epa(team, target, as_of), statbotics.point_in_time_epa(team, target, as_of)
        assert type(a) is type(b), (team, target, as_of)
        if isinstance(a, TeamEventEpa):
            assert a.event_key == b.event_key, (team, target, as_of)  # type: ignore[union-attr]
        checked += 1
    assert checked == sum(len(m) for _, _, m in EVENTS.values()) + len(NEXT_AS_OF)


def test_a_season_end_value_is_withheld_where_the_reference_would_serve_it(world):  # noqa: F811
    stratai = _stratai_over_world(world, season_end={"9961zzzcmptx"})
    found = stratai.point_in_time_epa(T_CHAMPS, "9962zzznext", NEXT_AS_OF[T_CHAMPS])
    reference = StatboticsPointInTimeEpa(world).point_in_time_epa(T_CHAMPS, "9962zzznext", NEXT_AS_OF[T_CHAMPS])
    assert reference.event_key == "9961zzzcmptx"  # type: ignore[union-attr]
    assert found.event_key == "9961zzzcur"  # type: ignore[union-attr]  # the next D13 candidate
    assert stratai.diagnostics["season_end"] == 1
