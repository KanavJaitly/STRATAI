"""No scouting export with people's names is tracked (audit 2026-11-26, workstream 4).

The real exports were removed from history on 2026-11-26 and are ignored (.gitignore, data/imports/README.md). These
checks keep it that way: only the README and the synthetic example are tracked under data/imports, no spreadsheet is
tracked anywhere, and every scout in a tracked ScoutRadioz CSV is a pseudonym or an invented label.
"""

from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PSEUDONYM = re.compile(r"^(Scout \d{2}|Example Scout [A-Z]|Synthetic Scout( \w+)?)$")


def _tracked(*patterns: str) -> list[str]:
    result = subprocess.run(["git", "ls-files", "--", *patterns], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return result.stdout.split()


def test_only_the_readme_and_the_synthetic_example_are_tracked_in_data_imports():
    assert set(_tracked("data/imports")) <= {"data/imports/README.md", "data/imports/example_scoutradioz_export.csv"}


def test_no_spreadsheet_is_tracked():
    assert _tracked("*.xlsx", "*.xls") == []


def test_every_scout_in_a_tracked_scoutradioz_csv_is_a_pseudonym():
    files = [f for f in _tracked("*.csv") if (ROOT / f).is_file()]
    checked = 0
    for name in files:
        with open(ROOT / name, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "scouter" not in reader.fieldnames:
                continue
            checked += 1
            for row in reader:
                scout = (row.get("scouter") or "").strip()
                assert not scout or PSEUDONYM.match(scout), f"{name}: a scouter value is not a pseudonym"
    assert checked >= 2  # the test fixture and the synthetic example
