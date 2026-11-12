"""P11A §14: the database snapshot builder's cutoff rules, with a scripted read-only fake database (no PostgreSQL).

This checks the builder's own logic, given rows like the database returns:
- a match scheduled before `as_of` but whose result was posted after it is left out;
- a ranking fetched after `as_of` is left out;
- a scouting summary computed after `as_of` is left out;
- every exclusion is recorded.

It does not check the SQL against a real schema: tests/test_p11a_db.py does that on an isolated copy. Synthetic
event 9911syn and teams 1-12 only.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ml.alliance import snapshot as snap_module
from ml.alliance.snapshot import build_event_snapshot, result_known_at

T0 = datetime(2099, 3, 1, 9, 0, tzinfo=timezone.utc)
AS_OF = T0 + timedelta(hours=3)


def _matches():
    """Twelve qualification matches, 15 minutes apart. Match 12 is scheduled before AS_OF but posted after it."""
    rows = []
    for n in range(1, 13):
        scheduled = T0 + timedelta(minutes=15 * (n - 1))
        posted = scheduled + timedelta(minutes=8)
        if n == 12:
            posted = AS_OF + timedelta(minutes=20)  # delayed
        rows.append((f"9911syn_qm{n}", scheduled, {"red": {"n": n}, "blue": {"n": n}}, 100 + n,
                     T0 + timedelta(days=30), str(int(posted.timestamp())), None,
                     None))  # alliances (DQ/surrogate keys; spec A3.6, 2026-11-11): none here
    return [r for r in rows if r[1] < AS_OF]


class FakeCursor:
    def __init__(self, ranking_fetch: datetime, scouting_at: datetime):
        self.ranking_fetch, self.scouting_at, self._rows = ranking_fetch, scouting_at, []

    def execute(self, sql: str, params=()):
        if sql == snap_module._EVENT_SQL:
            self._rows = [(9911, date(2099, 3, 1), date(2099, 3, 2))]
        elif sql == snap_module._PRIOR_EVENTS_SQL:
            self._rows = []
        elif sql == snap_module._QUAL_SQL:
            assert params[1] == AS_OF
            self._rows = _matches()
        elif sql == snap_module._TEAMS_SQL:
            self._rows = [(key, color, (n * 3 + i + (0 if color == "red" else 6)) % 12 + 1)
                          for n, key in enumerate(params[0]) for color in ("red", "blue") for i in range(3)]
        elif "FROM team_metrics" in sql:
            # the builder selects agreement and sufficiency too (spec A7, 2026-11-11): 10 columns
            self._rows = [(1, 3.0, 4, None, 0, self.scouting_at, 0.5, None, False, True),
                          (2, 2.0, 3, 1.0, 2, T0, 0.0, 0.0, False, False)]
        else:
            raise AssertionError(f"unexpected SQL: {sql[:60]}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeDatabase:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @contextmanager
    def cursor(self):
        yield FakeCursor(**self.kwargs)


@pytest.fixture(autouse=True)
def _helpers(monkeypatch):
    import data.human_inputs
    import data.rankings
    import ml.features.score_components
    import ml.playoffs.service

    parts = lambda season, b: SimpleNamespace(auto=10.0 + b["n"], teleop=20.0, endgame=5.0, fouls=1.0,  # noqa: E731
                                              total=36.0 + b["n"])
    monkeypatch.setattr(ml.features.score_components, "score_components", parts)
    monkeypatch.setattr(data.human_inputs, "approved_spec", lambda database, season: None)
    monkeypatch.setattr(ml.playoffs.service, "qualification_roster", lambda database, key: list(range(1, 13)))


def _build(monkeypatch, ranking_fetch, scouting_at):
    import data.rankings

    monkeypatch.setattr(data.rankings, "read_event_ranks",
                        lambda database, key: ({t: t for t in range(1, 13)}, ranking_fetch))
    return build_event_snapshot(FakeDatabase(ranking_fetch=ranking_fetch, scouting_at=scouting_at), "9911syn", AS_OF)


def test_a_delayed_match_posted_after_as_of_is_left_out_and_recorded(monkeypatch):
    snap = _build(monkeypatch, T0, T0)
    keys = {r.match_key for r in snap.qual_rows}
    assert "9911syn_qm12" not in keys and len(keys) == 11
    assert any(e.get("match_key") == "9911syn_qm12" and e["reason"] == "result_posted_after_as_of"
               for e in snap.exclusions)
    snap.validate()


def test_a_ranking_fetched_after_as_of_is_left_out(monkeypatch):
    late = _build(monkeypatch, AS_OF + timedelta(hours=1), T0)
    assert late.ranks is None and any(e.get("what") == "ranks" for e in late.exclusions)
    early = _build(monkeypatch, AS_OF - timedelta(minutes=1), T0)
    assert early.ranks is not None and not any(e.get("what") == "ranks" for e in early.exclusions)


def test_scouting_computed_after_as_of_is_left_out(monkeypatch):
    snap = _build(monkeypatch, T0, AS_OF + timedelta(minutes=5))
    assert 1 not in snap.scouting and 2 in snap.scouting  # team 1's summary was computed after as_of
    assert snap.scouting[2]["computed_at"] == T0.isoformat()
    assert any(e.get("what") == "scouting" and e["team_number"] == 1 for e in snap.exclusions)


def test_the_result_time_prefers_posted_then_actual_then_scheduled():
    scheduled = T0
    assert result_known_at(scheduled, str(int((T0 + timedelta(minutes=9)).timestamp())), None) == T0 + timedelta(
        minutes=9)
    assert result_known_at(scheduled, None, int((T0 + timedelta(minutes=4)).timestamp())) == T0 + timedelta(minutes=4)
    assert result_known_at(scheduled, "null", "bad") == T0
    assert result_known_at(scheduled.replace(tzinfo=None), None, None) == T0


def test_a6_dq_affected_matches_are_left_out_and_surrogates_kept_and_recorded(monkeypatch):
    """Spec A3.6: the labelled-dataset rules (ml.dataset.builder). Match 3 had a disqualified team: it is excluded
    and recorded. Match 4 had a surrogate: it stays, and the appearance is recorded in the provenance."""
    original = _matches

    def with_flags():
        rows = [list(r) for r in original()]
        rows[2][7] = {"red": {"dq_team_keys": ["frc5"], "surrogate_team_keys": []},
                      "blue": {"dq_team_keys": [], "surrogate_team_keys": []}}
        rows[3][7] = {"red": {"dq_team_keys": [], "surrogate_team_keys": []},
                      "blue": {"dq_team_keys": [], "surrogate_team_keys": ["frc7"]}}
        return [tuple(r) for r in rows]

    monkeypatch.setitem(globals(), "_matches", with_flags)
    snap = _build(monkeypatch, T0, T0)
    keys = {r.match_key for r in snap.qual_rows}
    assert "9911syn_qm3" not in keys and "9911syn_qm4" in keys
    assert {"match_key": "9911syn_qm3", "reason": "dq_affected: disqualified [5]"} in snap.exclusions
    assert snap.provenance["surrogate_appearances"] == [{"match_key": "9911syn_qm4", "color": "blue",
                                                         "team_number": 7}]


def test_a_snapshot_without_surrogates_has_no_surrogate_key(monkeypatch):
    snap = _build(monkeypatch, T0, T0)
    assert "surrogate_appearances" not in snap.provenance  # unchanged content and id for events without surrogates
