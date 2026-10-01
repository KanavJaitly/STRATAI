"""scripts/run_phase4_d18.py's pure helpers (D18 provenance counting and guards)."""

from __future__ import annotations

from types import SimpleNamespace

from scripts.run_phase4_d18 import METHODOLOGY_FILES, _find_key, _frame_provenance_counts


def _row(season, event_key, *sources):
    teams = [SimpleNamespace(epa_value_source=s) for s in sources]
    return SimpleNamespace(season=season, event_key=event_key, red_teams=teams[:3], blue_teams=teams[3:])


def test_frame_counts_label_every_appearance_and_flag_fallback_outside_scope():
    rows = [_row(2026, "2026iscmp", "stratai_fallback", None, "stratai_fallback", "stratai_fallback", None, None),
            _row(2026, "2026casj", "statbotics", "statbotics", None, "statbotics", "statbotics", "stratai_fallback")]
    counts = _frame_provenance_counts(rows)
    assert counts["d18_appearance_value_sources"]["2026"] == {"stratai_fallback": 4, "withheld": 4, "statbotics": 4}
    assert counts["d18_appearance_value_sources"]["target_2026iscmp"] == {"stratai_fallback": 3, "withheld": 3}
    assert counts["d18_fallback_outside_scope"] == 1


def test_methodology_freeze_covers_the_spec_gates_and_d15_evidence():
    for path in (".agent/phase4/D18_SOURCE_SPEC.md", ".agent/phase4/M05_M07_REDESIGN_SPEC.md",
                 "ml/calibration/gate.py", ".agent/phase4/results/m04_result.json"):
        assert path in METHODOLOGY_FILES


def test_find_key_searches_nested_reports():
    assert _find_key({"a": [{"b": {"week_one_complete_time": 5}}]}, "week_one_complete_time") == 5
