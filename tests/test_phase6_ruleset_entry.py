"""The prepared P6-M1 v2 rulesets encode Kanav's human decisions of 2026-10-08 (HD-1..HD-4) and nothing else.

Reads `.agent/phase6/rulesets_entry/resolved/` (v1, identical to the stored serving rows ids 1-3) and `resolved_v2/`.
Pure: no database. See `.agent/phase6/decisions/P6_M1_HUMAN_DECISIONS_2026-10-08.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.rulesets import SeasonRuleset
from ml.playoffs.selection import DraftState, best_available, run_draft

ENTRY = Path(__file__).resolve().parents[1] / ".agent" / "phase6" / "rulesets_entry"
SEASONS = (2024, 2025, 2026)
# The only fields the 2026-10-08 decisions may change from v1 (selection = default and the Championship variant).
ALLOWED = {"declined_team_may_become_captain", "unresolved", "citation"}


def _load(folder: str, season: int) -> dict:
    return json.loads((ENTRY / folder / f"ruleset_{season}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("season", SEASONS)
def test_v2_validates_and_encodes_hd1(season):
    data = _load("resolved_v2", season)
    assert "HUMAN_DECISION(" not in json.dumps(data)  # the entry-form marker form; the record path may appear
    rules = SeasonRuleset.model_validate(data)
    for selection in [rules.selection] + [v.selection for v in rules.selection_variants]:
        assert selection.declined_team_may_become_captain is True  # HD-1: may still become captain
        assert selection.declined_team_may_be_picked_later is False  # ... but can never be picked (T602/T606)
        assert "declined_team_may_become_captain" not in {u.field for u in selection.unresolved}
        assert "HD-1" in selection.citation


def test_captain_rules_after_hd2_and_hd3():
    r2024, r2025, r2026 = (SeasonRuleset.model_validate(_load("resolved_v2", s)) for s in SEASONS)
    assert r2024.selection.captain_rule == "highest_ranked_available"
    for selection in [r2025.selection] + [v.selection for v in r2025.selection_variants]:
        assert selection.captain_rule is None  # HD-2 does not establish the replacement-captain rule
        note = next(u.note for u in selection.unresolved if u.field == "captain_rule")
        assert "HD-2" in note and "stays null" in note
    for selection in [r2026.selection] + [v.selection for v in r2026.selection_variants]:
        assert selection.captain_rule == "highest_ranked_available" and "HD-3" in selection.citation


def test_2024_tie_rule_keeps_both_official_wordings_and_records_hd4():
    tie = _load("resolved_v2", 2024)["tie_rule"]
    assert "ALLIANCE STAGE points" in tie and "ALLIANCE PARK, ONSTAGE, and NOTE in TRAP STAGE points" in tie
    assert "HD-4" in tie


@pytest.mark.parametrize("season", SEASONS)
def test_v2_changes_nothing_but_the_decided_fields(season):
    v1, v2 = _load("resolved", season), _load("resolved_v2", season)
    for key in v1:
        if key in ("selection", "selection_variants", "tie_rule"):
            continue
        assert v1[key] == v2[key], key  # brackets, exclusions, roster rule, manual: untouched
    if season != 2024:
        assert v1["tie_rule"] == v2["tie_rule"]
    pairs = [(v1["selection"], v2["selection"])] + [
        (a["selection"], b["selection"]) for a, b in zip(v1["selection_variants"], v2["selection_variants"])]
    for old, new in pairs:
        assert {k for k in old if old[k] != new[k]} <= ALLOWED
    for a, b in zip(v1["selection_variants"], v2["selection_variants"]):
        assert a["name"] == b["name"] and a["events"] == b["events"]


def test_hd1_and_hd2_hold_in_the_draft_model():
    """A decliner can become captain but is never picked, and no captain is ever offered a higher-ranked team."""
    rules = SeasonRuleset.model_validate(_load("resolved_v2", 2026)).for_event("2026synthetic")
    teams = list(range(101, 114))  # 13 teams, 4 alliances x 3 = 12 slots
    ranks = {t: i for i, t in enumerate(teams, start=1)}
    declined = frozenset({105})  # declined an invitation before its captain turn
    ordering = list(reversed(teams))  # picks deliberately disagree with rank
    state = DraftState(((), (), (), ()), declined)
    seen: list[tuple[int, set[int]]] = []

    def chooser(current, seed, options):
        captain = current.alliances[seed - 1][0]
        seen.append((captain, set(options)))
        return best_available(ordering)(current, seed, options)

    final = run_draft(state, rules, ranks, chooser)
    captains = [a[0] for a in final.alliances]
    picks = {t for a in final.alliances for t in a[1:]}
    assert 105 not in picks  # never picked after declining
    for captain, options in seen:
        assert all(ranks[t] > ranks[captain] for t in options)  # never asks a higher-ranked team
    assert captains == sorted(captains, key=ranks.get)  # captains in rank order of availability
