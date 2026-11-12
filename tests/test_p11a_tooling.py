"""P11A tooling for the human steps (SYNTHETIC season 9911 only; nothing here is a real game or a real approval).

- the independent-reviewer rule on a scoring configuration;
- `check_draft` and the draft-config checker CLI (no approval needed; approves nothing);
- the GameSpec row-copy tool: export/import documents, guards, and the import's read-back check.

No test writes an approved row to any database: the import's SQL path runs against a fake connection. The one
database test only reads (an export from the isolated copy, which holds no approved spec).
"""

from __future__ import annotations

import json

import pytest

from ml.alliance.scoring_config import (
    ResolvedScoring,
    ScoringConfigError,
    SeasonScoringConfig,
    check_draft,
    require_approved,
    reviewer_is_independent,
)
from scripts import p11a_check_scoring_config as checker
from scripts import p11a_gamespec_copy as copy_tool
from tests.p11a_support import SEASON, approve, game_spec, scoring_config

# --- 3c: the reviewer must not be the person who entered the configuration ---------------------------------------


def _reviewed_by(reviewer: str, entered_by: str = "Ada Entry") -> SeasonScoringConfig:
    data = scoring_config(approved=False).model_dump(mode="json")
    data["source"]["entered_by"] = entered_by
    draft = SeasonScoringConfig.model_validate(data)
    return SeasonScoringConfig.model_validate({
        **draft.model_dump(mode="json"), "status": "approved",
        "review": {"reviewer": reviewer, "qualification": "synthetic test only", "reviewed_at": "2099-01-04T00:00:00Z",
                   "verified_sha256": draft.content_sha256()}})


@pytest.mark.parametrize("reviewer", ["Ada Entry", "ada entry", "  Ada   Entry ", "ADA ENTRY"])
def test_a_config_reviewed_by_its_own_entrant_is_refused(reviewer):
    config = _reviewed_by(reviewer)
    assert reviewer_is_independent(config) is False
    with pytest.raises(ScoringConfigError) as refused:
        require_approved(config, SEASON)
    assert refused.value.code == "scoring_config_not_approved" and "entered it" in refused.value.message
    with pytest.raises(ScoringConfigError):
        ResolvedScoring.resolve(config, game_spec())  # scoring goes through require_approved


def test_a_config_reviewed_by_someone_else_passes_and_a_draft_has_no_reviewer():
    assert reviewer_is_independent(_reviewed_by("Bea Review")) is True
    assert require_approved(_reviewed_by("Bea Review"), SEASON).status == "approved"
    assert reviewer_is_independent(scoring_config(approved=False)) is None


# --- 3b: check_draft and the checker CLI ----------------------------------------------------------------------------


def test_check_draft_validates_a_draft_without_approving_it():
    draft = scoring_config(approved=False)
    report = check_draft(draft, game_spec())
    assert report["valid_against_spec"] is True and report["problems"] == []
    assert report["status"] == "draft" and report["review"] is None
    assert report["content_sha256"] == draft.content_sha256()
    assert report["resolved_rules"]["endgame"]["cap_points"] == 20.0  # 2 x climb (10 points), from the GameSpec
    with pytest.raises(ScoringConfigError):  # a valid draft is still not usable for scoring
        require_approved(draft, SEASON)


def test_check_draft_lists_every_problem_not_only_the_first():
    data = scoring_config(approved=False, bonus=True).model_dump(mode="json")
    data["rules"][2]["cap_action_id"] = "teleop_piece"           # wrong period
    data["rules"][0]["bonuses"][0]["bonus_action_id"] = "nope"   # unknown action
    data["game_spec_sha256"] = "0" * 64                         # another GameSpec
    report = check_draft(SeasonScoringConfig.model_validate(data), game_spec())
    assert report["valid_against_spec"] is False and report["resolved_rules"] is None
    joined = " | ".join(report["problems"])
    assert "is not this GameSpec's sha256" in joined
    assert "GameSpec has no scoring action 'nope'" in joined and "teleop_piece is a teleop action, not endgame" in joined
    assert len(report["problems"]) == 3


def test_check_draft_reports_review_state_and_season_mismatch():
    report = check_draft(approve(scoring_config(approved=False)), game_spec())
    assert report["review"] == {"reviewer": "Synthetic Reviewer", "verified_sha256_matches_content": True,
                                "reviewer_independent_of_entered_by": True}
    other = check_draft(scoring_config(approved=False), game_spec(season=9912))
    assert any("the GameSpec is for 9912" in p for p in other["problems"])


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_the_checker_cli_prints_the_content_sha256_and_exit_codes(tmp_path, capsys):
    draft = scoring_config(approved=False)
    config = tmp_path / "config.json"
    config.write_text(draft.model_dump_json(), encoding="utf-8")
    spec = _write(tmp_path / "spec.json", game_spec().model_dump(mode="json"))
    assert checker.main(["--config", str(config), "--spec", str(spec)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["content_sha256"] == draft.content_sha256() and out["game_spec_approved"] is False

    export = _write(tmp_path / "export.json", copy_tool.build_export(_approved_row(), {"database": "stratai_test_x"}))
    assert checker.main(["--config", str(config), "--spec", str(export)]) == 0
    assert json.loads(capsys.readouterr().out)["game_spec_approved"] is True

    bad = _write(tmp_path / "bad.json", {**json.loads(config.read_text()), "game_spec_sha256": "1" * 64})
    assert checker.main(["--config", str(bad), "--spec", str(spec)]) == 1
    capsys.readouterr()
    assert checker.main(["--config", str(tmp_path / "missing.json"), "--spec", str(spec)]) == 2


# --- 3a: the GameSpec row-copy tool ---------------------------------------------------------------------------------


def _approved_row(**overrides):
    spec = game_spec()
    row = {"season": SEASON, "version": 3, "spec_json": json.dumps(spec.model_dump(mode="json")), "complete": True,
           "validation_errors": "[]", "spec_sha256": spec.sha256(), "manual_id": 7, "based_on_id": 2,
           "status": "approved", "created_by": "Ada Entry", "created_at": "2099-01-02T00:00:00+00:00",
           "entry_started_at": "2099-01-01T00:00:00+00:00", "submitted_at": "2099-01-02T01:00:00+00:00",
           "reviewed_by": "Bea Review", "reviewed_at": "2099-01-03T00:00:00+00:00", "review_note": None}
    return {**row, **overrides}


def test_export_documents_round_trip_and_refuse_unapproved_or_mismatched_rows():
    document = copy_tool.build_export(_approved_row(), {"database": "stratai_test_x"})
    assert copy_tool.check_export(json.loads(json.dumps(document))) == _approved_row()
    for row, code in ((_approved_row(status="awaiting_review"), "not_approved"),
                      (_approved_row(spec_sha256="0" * 64), "spec_sha256_mismatch")):
        with pytest.raises(copy_tool.CopyRefused) as refused:
            copy_tool.build_export(row, {})
        assert refused.value.code == code


def test_an_altered_or_foreign_export_file_is_refused():
    document = copy_tool.build_export(_approved_row(), {"database": "stratai_test_x"})
    altered = json.loads(json.dumps(document))
    altered["row"]["reviewed_by"] = "Someone Else"
    cases = [(altered, "altered_export"), ({**document, "kind": "other"}, "not_an_export"),
             ({**document, "row": {**document["row"], "extra": 1}}, "not_an_export")]
    for doc, code in cases:
        with pytest.raises(copy_tool.CopyRefused) as refused:
            copy_tool.check_export(doc)
        assert refused.value.code == code


class _FakeConnection:
    """Records statements; `existing` rows answer the conflict SELECT, `stored` answers INSERT ... RETURNING."""

    def __init__(self, existing=(), stored=None):
        self.existing, self.stored, self.statements = list(existing), stored, []

    def cursor(self):
        conn = self

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                conn.statements.append((sql, params))

            def fetchall(self):
                return [tuple(r[c] for c in copy_tool.COLUMNS) for r in conn.existing]

            def fetchone(self):
                return conn.stored

        return _Cursor()


def test_import_inserts_the_row_verbatim_except_the_source_foreign_keys():
    row = _approved_row()
    conn = _FakeConnection(stored=(41, row["spec_json"], row["spec_sha256"]))
    result = copy_tool.import_row(conn, row)
    assert result["status"] == "imported" and result["id"] == 41 and result["source_manual_id"] == 7
    sql, values = conn.statements[-1]
    assert sql.startswith("INSERT INTO game_spec_versions")
    inserted = dict(zip(copy_tool.COLUMNS, values))
    assert inserted["manual_id"] is None and inserted["based_on_id"] is None
    assert {k: v for k, v in inserted.items() if k not in ("manual_id", "based_on_id")} == \
        {k: v for k, v in row.items() if k not in ("manual_id", "based_on_id")}


def test_import_refuses_a_readback_that_differs():
    row = _approved_row()
    for stored in ((41, row["spec_json"] + " ", row["spec_sha256"]), (41, row["spec_json"], "0" * 64)):
        with pytest.raises(copy_tool.CopyRefused) as refused:
            copy_tool.import_row(_FakeConnection(stored=stored), row)
        assert refused.value.code == "readback_mismatch"


def test_import_is_idempotent_for_the_identical_row_and_refuses_any_other_clash():
    row = _approved_row()
    conn = _FakeConnection(existing=[row])
    assert copy_tool.import_row(conn, row)["status"] == "already_present"
    assert not any(s.startswith("INSERT") for s, _ in conn.statements)
    for clash in (_approved_row(version=1), _approved_row(status="draft", spec_sha256="x" * 64)):
        with pytest.raises(copy_tool.CopyRefused) as refused:
            copy_tool.import_row(_FakeConnection(existing=[clash]), row)
        assert refused.value.code == "target_conflict"


def _no_connection(*args, **kwargs):
    raise AssertionError("connected before the target check")


@pytest.mark.parametrize("name, command, code", [
    ("stratai", "export", "serving_database"), ("stratai", "import", "serving_database"),
    ("stratai", "verify", "serving_database"), ("stratai_test", "import", "not_a_test_database"),
    ("stratai_p5_replay_debug", "export", "not_a_test_database")])
def test_the_copy_tool_refuses_serving_and_non_test_databases_before_connecting(
        monkeypatch, tmp_path, capsys, name, command, code):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", f"postgresql://postgres@localhost:5432/{name}")
    monkeypatch.setattr(psycopg, "connect", _no_connection)
    export = _write(tmp_path / "export.json", copy_tool.build_export(_approved_row(), {"database": "stratai_test_x"}))
    argv = {"export": ["export", "--season", "2026", "--out", str(tmp_path / "out.json")],
            "import": ["import", "--file", str(export), "--confirm-database", name],
            "verify": ["verify", "--file", str(export)]}[command]
    assert copy_tool.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["code"] == code
    assert not (tmp_path / "out.json").exists()


def test_import_needs_the_confirmed_target_name(monkeypatch, tmp_path, capsys):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@localhost:5432/stratai_test_p11a")
    monkeypatch.setattr(psycopg, "connect", _no_connection)
    export = _write(tmp_path / "export.json", copy_tool.build_export(_approved_row(), {"database": "stratai_test_x"}))
    assert copy_tool.main(["import", "--file", str(export), "--confirm-database", "stratai_test_other"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "not_confirmed"


def test_the_target_guard_allows_the_bare_copy_only_when_asked():
    from database.target_guard import TargetRefused, check_target

    url = "postgresql://u@localhost:5432/{}"
    with pytest.raises(TargetRefused):
        check_target(url.format("stratai_test"))
    assert check_target(url.format("stratai_test"), allow_bare_test=True).dbname == "stratai_test"
    for refused_name, code in (("stratai", "serving_database"), ("stratai_testing", "not_a_test_database")):
        with pytest.raises(TargetRefused) as refused:
            check_target(url.format(refused_name), allow_bare_test=True)
        assert refused.value.code == code
    with pytest.raises(TargetRefused) as refused:
        check_target("postgresql://u@db.example.org:5432/stratai_test", allow_bare_test=True)
    assert refused.value.code == "remote_host"


def test_export_reads_the_isolated_copy_and_reports_no_approved_spec():
    """Database test (read-only): the isolated copy holds no approved GameSpec for any 2024-2026 season."""
    from tests.test_live_epa import _isolated_db_name

    if _isolated_db_name() is None:
        pytest.skip("needs an isolated stratai_test_* database copy")
    from data.config import Settings

    url = str(Settings().database_url)
    if not url.rsplit("/", 1)[-1].startswith("stratai_test_"):
        pytest.skip("needs a stratai_test_<suffix> copy")
    for season in (2024, 2025, 2026):
        with pytest.raises(copy_tool.CopyRefused) as refused:
            copy_tool.export_row(url, season)
        assert refused.value.code == "no_approved_spec"
