"""P5-D3 adoption plumbing: the adoption status, live_refresh_not_yet_validated flags, and the atomic swap.

Pure: a fake provider and a temporary snapshot log; no database. Synthetic, not evidence about any team.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

from api.dependencies import get_epa_source
from api.ml_loading import ServedEpaSource
from api.routes.common import epa_info
from ml.ratings.live_epa import ADOPTION, LIVE_REFRESH_NOT_YET_VALIDATED

AS_OF = datetime(2027, 3, 1, tzinfo=timezone.utc)


class _Provider:
    def __init__(self, is_root: bool) -> None:
        self.is_root = is_root

    def snapshot_view(self, as_of):
        return SimpleNamespace(is_root=self.is_root)


def _live(is_root: bool, stamp=(1, 1)) -> ServedEpaSource:
    return ServedEpaSource(_Provider(is_root), "p5_live_statbotics", False, {}, adoption=ADOPTION, log_stamp=stamp)


def test_adoption_is_operational_not_prospective_validation():
    assert ADOPTION["decision"] == "P5-D3" and ADOPTION["status"] == "adopted_for_production"
    assert "pending" in ADOPTION["prospective_validation"]
    assert "prospective 2027 validation remains pending" in ADOPTION["statement"]


def test_flags_follow_section_9():
    assert epa_info(_live(True), AS_OF, ["current"]).validation_flags == []  # root snapshot, no fallback
    assert epa_info(_live(False), AS_OF, ["current"]).validation_flags == [LIVE_REFRESH_NOT_YET_VALIDATED]
    assert epa_info(_live(True), AS_OF, ["current", "fallback_stratai"]).validation_flags == [
        LIVE_REFRESH_NOT_YET_VALIDATED]
    info = epa_info(_live(True), AS_OF, [])
    assert info.adoption == ADOPTION and info.evaluated_configuration is False


def test_the_frozen_d18_source_carries_no_live_flags():
    d18 = ServedEpaSource(_Provider(False), "d18_statbotics_primary", True, {})
    info = epa_info(d18, AS_OF, ["fallback_stratai"])
    assert info.validation_flags == [] and info.adoption is None and info.evaluated_configuration is True


def test_dependency_swaps_atomically_when_the_log_moves(tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    log.write_text("{}\n", encoding="utf-8")
    settings = SimpleNamespace(live_epa_log_dir=str(tmp_path))
    from api import ml_loading

    first = _live(True, stamp=ml_loading.live_log_stamp(settings))
    loads = []

    def fake_load(_settings, _database):
        loads.append(1)
        return _live(True, stamp=ml_loading.live_log_stamp(settings))

    monkeypatch.setattr("api.dependencies.load_epa_source", fake_load)
    state = SimpleNamespace(epa_source=first, epa_source_lock=threading.Lock(), settings=settings, database=None)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    assert get_epa_source(request) is first and not loads  # unchanged log: same instance
    log.write_text("{}\n{}\n", encoding="utf-8")  # a refresh appended an entry
    swapped = get_epa_source(request)
    assert swapped is not first and loads == [1]
    assert get_epa_source(request) is swapped  # and is then reused
