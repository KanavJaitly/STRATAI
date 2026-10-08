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


QUALIFICATION = "synthetic test qualification: FRC strategy reviewer"
CHECKLIST = {f"R{i}": True for i in range(1, 16)}


def _approve(database, row, reviewer="Reviewer B", **overrides):
    """Approve with every review condition satisfied, unless a test overrides one."""
    kwargs = {"reviewer_qualification": QUALIFICATION, "checklist": dict(CHECKLIST),
              "verified_sha256": row["ruleset_sha256"]}
    kwargs.update(overrides)
    return review_ruleset(database, row["id"], reviewer=reviewer, approve=True, **kwargs)


def _submitted(database, data=None, author="Author A"):
    row = save_ruleset_draft(database, data or ruleset(SEASON), created_by=author)
    submit_ruleset(database, row["id"])
    return row


def test_review_lifecycle_with_a_qualified_reviewer(database):
    row = save_ruleset_draft(database, ruleset(SEASON), created_by="Author A")
    with pytest.raises(RulesetError) as unapproved:
        approved_ruleset(database, SEASON)
    assert unapproved.value.code == "not_approved"
    with pytest.raises(RulesetError) as not_submitted:
        _approve(database, row)  # a draft cannot be approved before submission
    assert not_submitted.value.code == "invalid_state"
    submit_ruleset(database, row["id"])
    with pytest.raises(RulesetError):
        review_ruleset(database, row["id"], reviewer="Reviewer B", approve=False)  # returning needs a note
    approved = _approve(database, row)
    assert approved["status"] == "approved" and approved["reviewed_by"] == "Reviewer B"
    assert approved_ruleset(database, SEASON).sha256() == row["ruleset_sha256"]


def test_a_returned_ruleset_goes_back_to_draft(database):
    row = _submitted(database)
    returned = review_ruleset(database, row["id"], reviewer="Reviewer B", approve=False, note="fix the tie rule")
    assert returned["status"] == "draft" and returned["review_note"] == "fix the tie rule"
    with pytest.raises(RulesetError):
        approved_ruleset(database, SEASON)


def test_a_qualified_reviewer_who_is_not_the_author_may_approve(database):
    assert _approve(database, _submitted(database), reviewer="Reviewer B")["status"] == "approved"


def test_a_qualified_reviewer_who_is_the_author_may_approve(database):
    """Review control of 2026-10-07: matching author and reviewer names are no longer refused."""
    approved = _approve(database, _submitted(database, author="Same Person"), reviewer="Same Person")
    assert approved["status"] == "approved" and approved["created_by"] == approved["reviewed_by"]


def test_the_approval_records_qualification_checklist_and_hash(database):
    import json

    row = _submitted(database)
    record = json.loads(_approve(database, row)["review_note"])
    assert record == {"reviewer_qualification": QUALIFICATION, "checklist": CHECKLIST,
                      "verified_sha256": row["ruleset_sha256"], "note": None}


@pytest.mark.parametrize("reviewer", ["", "   "])
def test_approval_needs_a_reviewer_identity(database, reviewer):
    row = _submitted(database)
    with pytest.raises(RulesetError) as refused:
        _approve(database, row, reviewer=reviewer)
    assert refused.value.code == "invalid_input"
    assert list_rulesets(database, SEASON)[0]["status"] == "awaiting_review"


@pytest.mark.parametrize("qualification", ["", "   ", None])
def test_approval_needs_the_reviewer_qualification(database, qualification):
    row = _submitted(database)
    with pytest.raises(RulesetError) as refused:
        _approve(database, row, reviewer_qualification=qualification)
    assert refused.value.code == "invalid_input"
    assert list_rulesets(database, SEASON)[0]["status"] == "awaiting_review"


@pytest.mark.parametrize("change", ["missing_R7", "R15_false", "none", "extra_item", "string_true"])
def test_approval_needs_every_checklist_item_completed(database, change):
    row = _submitted(database)
    checklist = dict(CHECKLIST)
    if change == "missing_R7":
        del checklist["R7"]
    elif change == "R15_false":
        checklist["R15"] = False
    elif change == "none":
        checklist = None
    elif change == "extra_item":
        checklist["R16"] = True
    else:
        checklist["R3"] = "true"
    with pytest.raises(RulesetError) as refused:
        _approve(database, row, checklist=checklist)
    assert refused.value.code == "review_incomplete"
    assert list_rulesets(database, SEASON)[0]["status"] == "awaiting_review"


@pytest.mark.parametrize("sha", ["", "0" * 64, "short", "ABC"])
def test_approval_needs_the_stored_full_sha256(database, sha):
    row = _submitted(database)
    with pytest.raises(RulesetError) as refused:
        _approve(database, row, verified_sha256=sha)
    assert refused.value.code == "hash_mismatch"
    assert list_rulesets(database, SEASON)[0]["status"] == "awaiting_review"


def test_approval_refuses_stored_content_that_no_longer_matches_its_hash(database):
    row = _submitted(database)
    with database.cursor() as c:  # simulate tampering after submission (isolated database only)
        c.execute("UPDATE season_rulesets SET ruleset_json = jsonb_set(ruleset_json, '{tie_rule}', '\"tampered\"') "
                  "WHERE id = %s", (row["id"],))
    with pytest.raises(RulesetError) as refused:
        _approve(database, row)
    assert refused.value.code == "hash_mismatch"


def test_approval_refuses_stored_content_with_an_unresolved_marker(database):
    import hashlib
    import json

    data = ruleset(SEASON)
    data["selection"]["captain_rule"] = "HUMAN_DECISION(2026_CAPTAIN_RULE): unresolved"
    sha = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    with database.cursor() as c:  # bypasses save_ruleset_draft's validation on purpose (isolated database only)
        c.execute("INSERT INTO season_rulesets (season, version, ruleset_json, ruleset_sha256, status, created_by, "
                  "submitted_at) VALUES (%s, 1, %s, %s, 'awaiting_review', 'Author A', now()) RETURNING id",
                  (SEASON, json.dumps(data), sha))
        row = {"id": c.fetchone()[0], "ruleset_sha256": sha}
    with pytest.raises(RulesetError) as refused:
        _approve(database, row)
    assert refused.value.code == "invalid_stored_ruleset"
    with pytest.raises(RulesetError):
        save_ruleset_draft(database, data, created_by="Author A")  # and it can never be drafted


def test_the_runner_gate_accepts_only_an_approved_hash_matching_ruleset(database, monkeypatch):
    from scripts import phase6_playoff_track
    from scripts.phase6_playoff_track import Blocked, require_rulesets

    monkeypatch.setattr(phase6_playoff_track, "SEASONS", (SEASON,))
    row = _submitted(database)
    with pytest.raises(Blocked):
        require_rulesets(database)  # awaiting review: refused
    _approve(database, row)
    assert require_rulesets(database)[SEASON].sha256() == row["ruleset_sha256"]  # approved and matching: accepted
    with database.cursor() as c:
        c.execute("UPDATE season_rulesets SET ruleset_json = jsonb_set(ruleset_json, '{tie_rule}', '\"tampered\"') "
                  "WHERE id = %s", (row["id"],))
    with pytest.raises(RulesetError) as integrity:
        require_rulesets(database)  # approved but no longer matching its hash: refused
    assert integrity.value.code == "storage_integrity"


def test_cli_approval_writes_the_approval_record(database, tmp_path):
    import json

    from scripts.phase6_rulesets import main

    row = _submitted(database, author="Same Person")
    checklist = tmp_path / "review.json"
    checklist.write_text(json.dumps(CHECKLIST), encoding="utf-8")
    base = ["review", "--id", str(row["id"]), "--reviewer", "Same Person", "--approve", "--record-dir", str(tmp_path)]
    assert main(base + ["--checklist", str(checklist), "--sha256", row["ruleset_sha256"]]) == 1  # no qualification
    assert main(base + ["--qualification", QUALIFICATION, "--sha256", row["ruleset_sha256"]]) == 1  # no checklist
    assert main(base + ["--qualification", QUALIFICATION, "--checklist", str(checklist), "--sha256",
                        row["ruleset_sha256"]]) == 0
    record = json.loads((tmp_path / f"P6_M1_APPROVAL_{SEASON}_v1.json").read_text(encoding="utf-8"))
    assert record["reviewer_name"] == "Same Person" and record["reviewer_qualification"] == QUALIFICATION
    assert record["checklist_result"] == CHECKLIST and record["approved_ruleset_sha256"] == row["ruleset_sha256"]
    assert record["status"] == "approved" and record["review_date"]


def test_a_new_approval_supersedes_and_versions_are_kept(database):
    first = save_ruleset_draft(database, ruleset(SEASON), created_by="Author A")
    submit_ruleset(database, first["id"])
    _approve(database, first)
    changed = copy.deepcopy(ruleset(SEASON))
    changed["tie_rule"] = "synthetic fixture: a different tie rule"
    second = save_ruleset_draft(database, changed, created_by="Author A")
    submit_ruleset(database, second["id"])
    _approve(database, second)
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


def test_m8_future_playoff_sentinel_changes_no_selection_moment_input_and_is_removed(database):
    """The frozen P6-M8 leakage sentinel: a far-future playoff result (with scouting rows) inserted into the isolated
    copy must not change any selection-moment feature, and must be gone afterwards."""
    from ml.features.assembler import build_team_features
    from ml.playoffs.data import read_event_playoffs
    from ml.features.scale import ScaleLookup
    from ml.ratings.d18_source import load_d18_provider
    from scripts.phase6_playoff_track import CHAIN, SNAPSHOT, future_playoff_sentinel

    provider, _ = load_d18_provider(database, SNAPSHOT, CHAIN)  # the EPA source M8 uses
    scales = ScaleLookup(database)
    event = next(e for e in read_event_playoffs(database, 2026)
                 if e.alliances and not e.division_champion and e.latest_qualification is not None)
    red, blue = event.alliances[0].picks[:3], event.alliances[1].picks[:3]
    as_of = event.selection_as_of()

    def features():
        return [build_team_features(database, t, event.event_key, as_of, epa_provider=provider,
                                    scale_lookup=scales).model_dump() for t in (*red, *blue)]

    before = features()
    with future_playoff_sentinel(database, event.event_key, event.season, red, blue) as key:
        with database.cursor() as c:
            c.execute("SELECT count(*) FROM match_teams WHERE match_key = %s", (key,))
            assert c.fetchone()[0] == 6
        assert features() == before
    with database.cursor() as c:
        c.execute("SELECT (SELECT count(*) FROM matches WHERE match_key = %s) + "
                  "(SELECT count(*) FROM match_teams WHERE match_key = %s) + "
                  "(SELECT count(*) FROM scouting_observations WHERE source = 'p6m8_sentinel')", (key, key))
        assert c.fetchone()[0] == 0


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
