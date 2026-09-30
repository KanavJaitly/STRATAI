"""The EPA replay runner: execution report, verification, write-once artifacts."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ml.ratings.epa import run_season
from ml.ratings.epa.inputs import SeasonInput, season_input_fingerprint
from ml.ratings.reader import ReaderIssue, ReadResult
from ml.ratings.runner import (
    WEEK_ONE_NOTE,
    SeasonReplay,
    artifact_files,
    build_execution_report,
    render_execution_report,
    verify_resume,
    write_artifacts,
)
from ratings_epa_support import random_season
from test_ratings_reader import requires_db


def _replay(season: int = 2024) -> SeasonReplay:
    season_input = random_season(season, seed=season)
    read = ReadResult(season_input=season_input,
                      issues=(ReaderIssue("placeholder_team_key", "noted", f"{season}ev0", f"{season}ev0_qm1", "x"),),
                      snapshot={"raw_payloads_read": 1, "max_raw_payload_id": 1, "raw_payload_ids_sha256": "0",
                                "canonical_rows": {}},
                      canonical_events=len(season_input.events), canonical_matches=len(season_input.matches))
    result = run_season(season_input, created_at="t", data_snapshot=read.snapshot)
    verification = {"performed": True,
                    "determinism": {"reread_input_identical": True, "reread_issues_identical": True,
                                    "rerun_results_fingerprint_identical": True, "ok": True},
                    "resume": verify_resume(season_input, result)}
    report = build_execution_report(read, season_input, result, verification)
    return SeasonReplay(season, read, season_input, result, report)


def test_resume_verification_passes_and_includes_the_week_two_boundary() -> None:
    replay = _replay()
    resume = replay.report["verification"]["resume"]
    assert resume["ok"] and len(resume["checks"]) == 4
    assert all(c["records_identical"] for c in resume["checks"])


def test_execution_report_accounts_for_every_match() -> None:
    report = _replay().report
    m = report["matches"]
    assert m["processed"] == m["updated"] + sum(m["skipped"].values()) + m["upcoming_predicted_only"]
    assert m["given_to_engine"] == sum(m["filtered"].values()) + sum(m["rejected"].values()) + m["processed"]
    assert report["teams"]["rated"] == report["outputs"]["team_seasons"]
    assert report["week_one_lookahead"]["note"] == WEEK_ONE_NOTE
    assert report["data_quality"]["reader_issues"] == {"placeholder_team_key (noted)": 1}
    assert report["prediction_sanity_check"]["all"]["matches"] > 0


def test_rendered_report_separates_execution_from_parity() -> None:
    text = render_execution_report(_replay().report)
    assert "does not measure agreement with Statbotics" in text
    assert "not a Statbotics comparison" in text
    assert "Week-1 look-ahead" in text


def test_artifact_bytes_are_deterministic_and_restorable() -> None:
    replay = _replay(2025)
    first, second = artifact_files(replay), artifact_files(_replay(2025))
    assert first == second  # gzip with mtime=0: identical content, identical bytes
    restored = SeasonInput.model_validate(json.loads(gzip.decompress(first["season_input.json.gz"])))
    assert season_input_fingerprint(restored) == season_input_fingerprint(replay.season_input)
    lines = gzip.decompress(first["match_records.jsonl.gz"]).decode().splitlines()
    assert len(lines) == len(replay.result.records)
    assert "reference_rounded" in json.loads(lines[0])


def test_artifacts_are_write_once(tmp_path: Path) -> None:
    replay = _replay()
    directory, written = write_artifacts(tmp_path, replay)
    assert written and (directory / "manifest.json").exists()
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["results_fingerprint"] == replay.result.results_fingerprint()
    assert set(manifest["files"]) == set(artifact_files(replay))
    assert write_artifacts(tmp_path, replay) == (directory, False)  # identical: recognised, not rewritten
    manifest["files"]["team_events.json"] = "tampered"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FileExistsError):
        write_artifacts(tmp_path, replay)


@requires_db
def test_real_event_replay_is_deterministic_and_resumable() -> None:
    from data.config import Settings
    from database.connection import Database, DatabaseConfig
    from ml.ratings.runner import replay_season

    database = Database(DatabaseConfig(Settings().database_url))
    replay = replay_season(database, 2024, event_keys=["2024casj"])
    if not replay.season_input.matches:
        pytest.skip("2024casj is not synced in this database")
    verification = replay.report["verification"]
    assert verification["determinism"]["ok"] and verification["resume"]["ok"]
    assert replay.report["matches"]["rejected"] == {"missing_time": 0, "missing_breakdown": 0, "malformed_breakdown": 0}
