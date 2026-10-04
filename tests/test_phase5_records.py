"""scripts.phase5_records: write-once, provenance-carrying result records."""

from __future__ import annotations

import json

import pytest

from scripts import phase5_records
from scripts.phase5_records import RecordError, write_once


def test_write_once_records_provenance_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(phase5_records, "provenance", lambda: {"commit": "abc", "python": "3", "recorded_at": "t"})
    path = write_once("r.json", {"metric": 1.5}, results_dir=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"metric": 1.5, "provenance": {"commit": "abc", "python": "3", "recorded_at": "t"}}
    with pytest.raises(RecordError, match="write-once"):
        write_once("r.json", {"metric": 2.0}, results_dir=tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["metric"] == 1.5


def test_provenance_refuses_uncommitted_tracked_changes(monkeypatch):
    monkeypatch.setattr(phase5_records, "_git", lambda *a: "ml/x.py\n.gitignore\n" if a[0] == "diff" else "sha\n")
    with pytest.raises(RecordError, match="ml/x.py"):
        phase5_records.provenance()


def test_provenance_ignores_only_the_users_gitignore(monkeypatch):
    monkeypatch.setattr(phase5_records, "_git", lambda *a: ".gitignore\n" if a[0] == "diff" else "deadbeef\n")
    assert phase5_records.provenance()["commit"] == "deadbeef"
