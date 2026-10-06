"""P6-M1 storage and review workflow, and the playoff-track runner's refusal without approved rulesets.

Isolated database only. Synthetic season 9997, cleaned before and after. SYNTHETIC rulesets: test fixtures, never
approved as real rules and not evidence.
"""

from __future__ import annotations

import copy

import pytest

from data.config import Settings
from data.rulesets import (RulesetError, approved_ruleset, list_rulesets, review_ruleset, save_ruleset_draft,
                           submit_ruleset)
from database.connection import Database, DatabaseConfig
from tests.phase6_bracket_fixtures import ruleset
from tests.test_live_epa import _isolated_db_name

pytestmark = pytest.mark.skipif(_isolated_db_name() is None, reason="needs an isolated stratai_test database")

SEASON = 9997


@pytest.fixture
def database():
    from database.migrate import run_migrations

    settings = Settings()
    run_migrations(settings)
    db = Database(DatabaseConfig(settings.database_url))

    def cleanup():
        with db.cursor() as c:
            c.execute("DELETE FROM season_rulesets WHERE season = %s", (SEASON,))

    cleanup()
    yield db
    cleanup()


def test_review_lifecycle_needs_a_different_named_reviewer(database):
    row = save_ruleset_draft(database, ruleset(SEASON), created_by="Author A")
    with pytest.raises(RulesetError) as unapproved:
        approved_ruleset(database, SEASON)
    assert unapproved.value.code == "not_approved"
    submit_ruleset(database, row["id"])
    with pytest.raises(RulesetError):
        review_ruleset(database, row["id"], reviewer="Author A", approve=True)  # the author cannot approve
    with pytest.raises(RulesetError):
        review_ruleset(database, row["id"], reviewer="Reviewer B", approve=False)  # returning needs a note
    review_ruleset(database, row["id"], reviewer="Reviewer B", approve=True)
    assert approved_ruleset(database, SEASON).sha256() == row["ruleset_sha256"]


def test_a_new_approval_supersedes_and_versions_are_kept(database):
    first = save_ruleset_draft(database, ruleset(SEASON), created_by="Author A")
    submit_ruleset(database, first["id"])
    review_ruleset(database, first["id"], reviewer="Reviewer B", approve=True)
    changed = copy.deepcopy(ruleset(SEASON))
    changed["tie_rule"] = "synthetic fixture: a different tie rule"
    second = save_ruleset_draft(database, changed, created_by="Author A")
    submit_ruleset(database, second["id"])
    review_ruleset(database, second["id"], reviewer="Reviewer B", approve=True)
    statuses = [(r["version"], r["status"]) for r in list_rulesets(database, SEASON)]
    assert statuses == [(1, "superseded"), (2, "approved")]
    assert approved_ruleset(database, SEASON).tie_rule.endswith("different tie rule")


def test_an_invalid_ruleset_is_refused(database):
    broken = ruleset(SEASON)
    broken["brackets"] = broken["brackets"][:1]  # the 4-alliance rule has no bracket format
    with pytest.raises(RulesetError) as error:
        save_ruleset_draft(database, broken, created_by="Author A")
    assert error.value.code == "invalid_input" and error.value.details


def test_runner_refuses_without_approved_rulesets(database):
    from scripts.phase6_playoff_track import Blocked, require_rulesets

    with pytest.raises(Blocked) as blocked:
        require_rulesets(database)
    assert blocked.value.code == 2


def test_m1_reproduction_path_runs_on_real_events_with_injected_rulesets(database):
    """Smoke test of the data path only: SYNTHETIC rulesets, two events per season, nothing recorded."""
    from data.rulesets import SeasonRuleset
    from scripts.phase6_playoff_track import run_m1

    synthetic = {s: SeasonRuleset.model_validate(ruleset(s)) for s in (2024, 2025, 2026)}
    result = run_m1(database, synthetic, limit=2)
    assert set(result["seasons"]) == {2024, 2025, 2026}
    assert all(s["events"] == 2 for s in result["seasons"].values())


def test_m1_counts_ruleset_exclusions_and_records_the_variant_applied(database):
    """Schema v2: an excluded event is excluded and counted under its reason, never evaluated, and an evaluated
    event records which selection variant governed it. SYNTHETIC rulesets on real event keys; nothing recorded."""
    from data.rulesets import SeasonRuleset
    from ml.playoffs.data import read_event_playoffs
    from scripts.phase6_playoff_track import run_m1
    from tests.phase6_bracket_fixtures import with_three_pick_variant

    limit = 8
    seeded = [e.event_key for e in read_event_playoffs(database, 2024)[:limit]
              if e.alliances and not e.division_champion]
    assert len(seeded) >= 2
    excluded_key, variant_key = seeded[0], seeded[1]
    data_2024 = with_three_pick_variant(ruleset(2024), [variant_key])
    data_2024["event_exclusions"] = [{"event_key": excluded_key, "reason": "synthetic_reason",
                                      "finding": "synthetic test exclusion"}]
    synthetic = {2024: SeasonRuleset.model_validate(data_2024),
                 2025: SeasonRuleset.model_validate(ruleset(2025)), 2026: SeasonRuleset.model_validate(ruleset(2026))}
    result = run_m1(database, synthetic, limit=limit)
    season = result["seasons"][2024]
    assert result["events"][excluded_key]["status"] == "excluded:ruleset_exclusion:synthetic_reason"
    assert season["counts"]["ruleset_exclusion:synthetic_reason"] == 1
    assert season["selection_variants"].get("three_picks") == 1
    if "selection_variant" in result["events"][variant_key]:  # reached the bracket (the roster rule covered it)
        assert result["events"][variant_key]["selection_variant"] == "three_picks"


def test_captain_rule_respects_serpentine_timing():
    """Round-2 picks happen after later seeds choose captains: a better-ranked team picked in round 2 should have
    been the next captain, so that is a violation."""
    from types import SimpleNamespace

    from data.alliances import Alliance
    from data.rulesets import SeasonRuleset
    from scripts.phase6_playoff_track import _captain_rule_violations

    rules = SeasonRuleset.model_validate(ruleset()).for_event("2099synth")
    ranks = {101: 1, 102: 2, 103: 3, 104: 4, 105: 5, 106: 6}
    ok = SimpleNamespace(event_key="e", alliances=[Alliance(1, 1, None, 101, (101, 102, 106), None, ()),
                                                   Alliance(2, 2, None, 103, (103, 104, 105), None, ())])
    assert _captain_rule_violations(ok, ranks, rules) == ([], {})
    # seed 2's captain is 104 although 103 was still available (103 only joined seed 1 in round 2)
    late = SimpleNamespace(event_key="e", alliances=[Alliance(1, 1, None, 101, (101, 102, 103), None, ()),
                                                     Alliance(2, 2, None, 104, (104, 105, 106), None, ())])
    assert len(_captain_rule_violations(late, ranks, rules)[0]) == 1


def _leaves(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, value


def test_fresh_template_supplies_no_rule_values():
    """Template safety (2026-10-05): every value is a blank placeholder; nothing is software-supplied."""
    from scripts.phase6_rulesets import SKELETON

    leaves = dict(_leaves(SKELETON))
    assert leaves and all(v == "" for v in leaves.values()), {k: v for k, v in leaves.items() if v != ""}
    for name in ("captain_may_accept_higher_alliance", "declined_team_may_be_picked_later",
                 "declined_team_may_become_captain", "backup_robots"):
        assert SKELETON["selection"][name] == ""


def test_fresh_template_fails_validation_on_every_rule_value():
    import pytest
    from pydantic import ValidationError

    from data.rulesets import SeasonRuleset
    from scripts.phase6_rulesets import SKELETON

    with pytest.raises(ValidationError) as error:
        SeasonRuleset.model_validate(SKELETON)
    failed = {".".join(str(p) for p in e["loc"]) for e in error.value.errors()}
    for name in ("captain_may_accept_higher_alliance", "declined_team_may_be_picked_later",
                 "declined_team_may_become_captain", "backup_robots", "order", "captain_rule",
                 "picks_per_alliance", "citation"):
        assert f"selection.{name}" in failed, name
    assert "alliance_counts.0.max_teams" in failed and "tie_rule" in failed and "season" in failed


def test_a_blank_boolean_alone_fails_validation():
    """Filling everything except one rule boolean still fails: a blank is never read as true or false."""
    import pytest
    from pydantic import ValidationError

    from data.rulesets import SeasonRuleset

    for name in ("captain_may_accept_higher_alliance", "declined_team_may_be_picked_later",
                 "declined_team_may_become_captain", "backup_robots"):
        data = ruleset()
        data["selection"][name] = ""
        with pytest.raises(ValidationError):
            SeasonRuleset.model_validate(data)
        del data["selection"][name]
        with pytest.raises(ValidationError):
            SeasonRuleset.model_validate(data)
