"""SYNTHETIC ruleset and bracket fixtures for Phase 6 tests.

These are test fixtures, not rulesets entered from any game manual. They are not evidence, and they are never
stored as approved rulesets. Real rulesets come only from people, through P6-M1's reviewed workflow.
"""

from __future__ import annotations

from typing import Any


def _seed(n: int) -> dict[str, Any]:
    return {"kind": "seed", "seed": n}


def _w(slot: str) -> dict[str, Any]:
    return {"kind": "winner", "slot": slot}


def _l(slot: str) -> dict[str, Any]:
    return {"kind": "loser", "slot": slot}


def _slot(name: str, set_number: int, round_: int, red: dict, blue: dict) -> dict[str, Any]:
    return {"slot": name, "competition_level": "semifinal", "set_number": set_number, "round": round_,
            "red": red, "blue": blue, "citation": "synthetic fixture"}


def double_elimination_8() -> dict[str, Any]:
    """A synthetic 8-alliance double-elimination graph: 13 slots, then a best-of-3 final."""
    slots = [
        _slot("M1", 1, 1, _seed(1), _seed(8)), _slot("M2", 2, 1, _seed(4), _seed(5)),
        _slot("M3", 3, 1, _seed(2), _seed(7)), _slot("M4", 4, 1, _seed(3), _seed(6)),
        _slot("M5", 5, 2, _l("M1"), _l("M2")), _slot("M6", 6, 2, _l("M3"), _l("M4")),
        _slot("M7", 7, 2, _w("M1"), _w("M2")), _slot("M8", 8, 2, _w("M3"), _w("M4")),
        _slot("M9", 9, 3, _l("M7"), _w("M6")), _slot("M10", 10, 3, _l("M8"), _w("M5")),
        _slot("M11", 11, 4, _w("M7"), _w("M8")), _slot("M12", 12, 4, _w("M10"), _w("M9")),
        _slot("M13", 13, 5, _l("M11"), _w("M12")),
    ]
    finals = {"competition_level": "final", "set_number": 1, "round": 6, "wins_needed": 2,
              "red": _w("M11"), "blue": _w("M13"), "citation": "synthetic fixture"}
    return {"alliances": 8, "slots": slots, "finals": finals}


def single_elimination_4() -> dict[str, Any]:
    slots = [_slot("S1", 1, 1, _seed(1), _seed(4)), _slot("S2", 2, 1, _seed(2), _seed(3))]
    finals = {"competition_level": "final", "set_number": 1, "round": 2, "wins_needed": 2,
              "red": _w("S1"), "blue": _w("S2"), "citation": "synthetic fixture"}
    return {"alliances": 4, "slots": slots, "finals": finals}


def ruleset(season: int = 2099) -> dict[str, Any]:
    return {
        "season": season, "game_name": "Synthetic Game", "manual": {"title": "Synthetic Manual", "version": "0"},
        "alliance_counts": [{"min_teams": 1, "max_teams": 23, "alliances": 4, "citation": "synthetic fixture"},
                            {"min_teams": 24, "max_teams": None, "alliances": 8, "citation": "synthetic fixture"}],
        "selection": {"order": "serpentine", "picks_per_alliance": 2, "captain_rule": "highest_ranked_available",
                      "captain_may_accept_higher_alliance": True, "declined_team_may_be_picked_later": False,
                      "declined_team_may_become_captain": True, "backup_robots": True,
                      "citation": "synthetic fixture"},
        "brackets": [double_elimination_8(), single_elimination_4()],
        "tie_rule": "synthetic fixture: replay",
    }
