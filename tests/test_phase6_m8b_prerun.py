"""P6-M8b pre-run preparation (2026-10-11): the draft record and Mr. Biery's agreement evidence. Reads committed
records and SYNTHETIC tmp copies only; nothing runs and no database is touched."""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from scripts.phase6_playoff_track import PX1B_TRACK, Blocked, _m8_config

DECISIONS = Path(".agent/phase6/decisions")
DRAFT_JSON = DECISIONS / "p6_m8b_pre_run_draft.json"
FROZEN_M8 = DECISIONS / "p6_m8_pre_run.json"
EVIDENCE = DECISIONS / "P6_M8B_MENTOR_AGREEMENT_2026-10-08.md"
CODES = ["post_selection_event", "unmeasured_role", "insufficient_preselection_data", "procedural_selection_event",
         "outcome_variance", "data_error"]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_reason_categories_are_the_frozen_ones_unaltered():
    draft, frozen = _json(DRAFT_JSON), _json(FROZEN_M8)
    assert [c["code"] for c in draft["reason_categories"]] == CODES
    assert draft["reason_categories"] == frozen["reason_categories"] and draft["review_rule"] == frozen["review_rule"]


def test_the_mentor_evidence_is_recorded_verbatim_and_dated():
    agreement = _json(DRAFT_JSON)["mentor_agreement"]
    assert agreement["confirmed"] is True and agreement["date"] == "2026-10-08"
    assert agreement["evidence"]["reply_verbatim"] == "Yes I'll do that"
    assert Path(agreement["evidence"]["record"]) == EVIDENCE and EVIDENCE.exists()
    text = EVIDENCE.read_text(encoding="utf-8")
    assert '"Yes I\'ll do that"' in text and "2026-10-08" in text and "has not been recovered" in text


def test_the_seed_and_count_are_still_proposals():
    draft = _json(DRAFT_JSON)
    assert "PROPOSED" in draft["seed_status"] and "PROPOSED" in draft["per_stratum_status"]
    assert any("seed" in m for m in draft["missing_before_adoption"])


def test_the_harness_ignores_the_draft():
    assert not PX1B_TRACK.m8_pre_run.exists() and not PX1B_TRACK.m8_pre_run_json.exists()
    with pytest.raises(Blocked):
        _m8_config(PX1B_TRACK)


def test_adopting_the_draft_would_satisfy_the_harness_agreement_check(tmp_path):
    """SYNTHETIC adoption into tmp paths: the fields M8b's harness checks are all present."""
    md, js = tmp_path / "P6_M8B_PRE_RUN.md", tmp_path / "p6_m8b_pre_run.json"
    md.write_text("SYNTHETIC adoption", encoding="utf-8")
    js.write_text(DRAFT_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    config = _m8_config(dataclasses.replace(PX1B_TRACK, m8_pre_run=md, m8_pre_run_json=js))
    assert config["mentor"] == "Mr. Biery" and config["mentor_agreement"]["date"] == "2026-10-08"
    stripped = {**_json(DRAFT_JSON), "mentor_agreement": {"confirmed": True, "date": "2026-10-08", "evidence": None}}
    js.write_text(json.dumps(stripped), encoding="utf-8")
    with pytest.raises(Blocked):
        _m8_config(dataclasses.replace(PX1B_TRACK, m8_pre_run=md, m8_pre_run_json=js))


def test_the_frozen_m8b_spec_and_the_m8_pre_run_record_are_unchanged():
    def blob_at(commit, path):
        return subprocess.run(["git", "rev-parse", f"{commit}:{path}"], capture_output=True, text=True,
                              check=True).stdout.strip()

    def blob_now(path):
        return subprocess.run(["git", "hash-object", path], capture_output=True, text=True, check=True).stdout.strip()
    spec = ".agent/phase6/P6_M8B_SPEC.md"
    assert blob_now(spec) == blob_at("021e6ea", spec)
    for path in (".agent/phase6/decisions/P6_M8_PRE_RUN.md", ".agent/phase6/decisions/p6_m8_pre_run.json"):
        assert blob_now(path) == blob_at("36b52c7", path)
