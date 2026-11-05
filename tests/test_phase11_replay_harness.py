"""Phase 11: the replay harness's own logic (scripts/phase11_replay.py), on synthetic alliances with the setup, engine
and ordering faked. No database. Synthetic only: nothing here is evidence about any real event; the real-data replay
is the script's run on an isolated copy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.alliances import Alliance
from ml.playoffs.service import PlayoffModelsNotAccepted
from scripts import phase11_replay as harness
from tests.test_phase11_draft_log import setup
from workspaces import draft_recommendations as rec


def alliances(n: int = 4, picks: int = 2, declines: tuple[int, ...] = ()) -> list[Alliance]:
    """A real-looking final field: serpentine best-ranked-available, teams ranked by number, captains promoted."""
    teams = list(range(1, 3 * n + 4))
    out = [[] for _ in range(n)]
    pool = [t for t in teams if t not in declines]
    for index, seed in enumerate(harness.dl.turn_order(n, picks)):
        if not out[seed - 1]:
            out[seed - 1].append(min(t for t in teams if t not in {x for a in out for x in a}))
            pool = [t for t in pool if t != out[seed - 1][0]]
        out[seed - 1].append(pool.pop(0))
    return [Alliance(s, s, f"Alliance {s}", a[0], tuple(a), None, declines if s == 1 else ())
            for s, a in enumerate(out, start=1)]


@pytest.fixture
def faked(monkeypatch):
    s = setup(n_teams=15, n_alliances=4, picks_per_alliance=2)
    monkeypatch.setattr(harness, "_setup", lambda database, event_key: s)
    monkeypatch.setattr(rec, "engine_pick_list", lambda *a, **k: (_ for _ in ()).throw(
        PlayoffModelsNotAccepted("PX gates not passed")))
    monkeypatch.setattr(rec, "event_ordering", lambda *a, **k: rec.Ordering(
        tuple(range(15, 0, -1)), "raw_epa", "validated", {}, datetime(2030, 1, 1, tzinfo=timezone.utc),
        "selection_moment", ()))
    return s


def test_reconstruct_follows_the_serpentine_order_and_names_captains_at_their_first_turn(faked):
    actions, notes = harness.reconstruct(alliances(), faked.rules)
    assert actions[:2] == [("captain", 1, 1), ("pick", 1, 2)]
    assert ("captain", 2, 3) in actions  # team 2 was picked, so 3 was promoted
    assert [a for a in actions if a[0] == "pick"][4][1] == 4  # round 2 starts with the last seed
    assert notes == []


def test_a_clean_replay_passes_every_check(faked):
    result = harness.replay_event(None, "2030test", alliances(), epa_source=object(), ranking=None,
                                  playoff_models=None)
    assert result["passed"], result["problems"]
    assert result["overridden"] == []
    sources = result["recommendation_sources"]
    assert sources["fallback_p11_fb1"] > 0
    # A later captain is "not selecting" until the team projected ahead of it is picked (e.g. 3 before 2 is taken).
    assert set(sources) <= {"fallback_p11_fb1", "withheld:no_remaining_turn", "withheld:team_not_selecting"}
    assert result["recommend_seconds"]["count"] > 0


def test_declines_are_recorded_and_documented_as_unreconstructible(faked):
    field = alliances(declines=(5,))
    actions, notes = harness.reconstruct(field, faked.rules)
    assert ("decline", 1, 5) in actions and "timing and inviter not recorded" in notes[0]
    result = harness.replay_event(None, "2030test", field, epa_source=object(), ranking=None, playoff_models=None)
    assert result["passed"], result["problems"]


def test_a_fact_the_rules_refuse_is_counted_as_an_override_not_hidden(faked):
    field = alliances()
    wrong = field[1]
    field[1] = Alliance(2, 2, "Alliance 2", 9, (9,) + wrong.picks[1:], None, ())  # not the captain the rules name
    result = harness.replay_event(None, "2030test", field, epa_source=object(), ranking=None, playoff_models=None)
    assert any(o["code"] == "wrong_captain" for o in result["overridden"])


def test_the_budget_is_capped_at_the_verification_limit():
    with pytest.raises(SystemExit):
        harness.main(["--budget-minutes", "60"])
