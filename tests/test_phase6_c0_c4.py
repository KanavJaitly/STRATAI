"""C0 (2027 P6-M1 check) and C4 (PX-1b harness pointers), approved 2026-10-08 (D9 v1 Part C).

Pure and SYNTHETIC: no database, no real 2027 data (none exists), not evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.alliances import Alliance
from data.rulesets import SeasonRuleset
from ml.playoffs.data import EventPlayoffs, RawPlayoffMatch
from tests.phase6_bracket_fixtures import ruleset

T = datetime(2027, 3, 6, 12, tzinfo=timezone.utc)
KEY = "2027synth"


def _alliance(seed: int) -> Alliance:
    picks = (100 * seed + 1, 100 * seed + 2, 100 * seed + 3)
    return Alliance(seed=seed, position=seed, name=f"Alliance {seed}", captain=picks[0], picks=picks, backup=None,
                    declines=())


def _team(seed: int) -> tuple[int, ...]:
    return (100 * seed + 1, 100 * seed + 2, 100 * seed + 3)


def synthetic_2027_event(*, last_qualification: datetime = T - timedelta(hours=2)) -> EventPlayoffs:
    """A 4-alliance, single-elimination SYNTHETIC event: seed 1 beats 4, 3 beats 2, then 1 beats 3 two-one."""
    def match(key, level, set_number, number, red, blue, winner, minutes):
        return RawPlayoffMatch(f"{KEY}_{key}", level, set_number, number, T + timedelta(minutes=minutes), winner,
                               _team(red), _team(blue))
    matches = (match("sf1m1", "semifinal", 1, 1, 1, 4, "red", 0), match("sf2m1", "semifinal", 2, 1, 2, 3, "blue", 10),
               match("f1m1", "final", 1, 1, 1, 3, "blue", 20), match("f1m2", "final", 1, 2, 1, 3, "red", 30),
               match("f1m3", "final", 1, 3, 1, 3, "red", 40))
    return EventPlayoffs(KEY, 2027, tuple(_alliance(s) for s in range(1, 5)), matches, last_qualification, 20)


# --- C0 -------------------------------------------------------------------------------------------------------


def test_c0_runs_the_frozen_m1_check_on_2027_only(monkeypatch):
    import data.rankings
    import ml.playoffs.data
    from scripts.phase6_playoff_track import run_m1

    def events(database, season):
        assert season == 2027, "C0 must read 2027 events only"
        return [synthetic_2027_event()]
    monkeypatch.setattr(ml.playoffs.data, "read_event_playoffs", events)
    ranks = {t: i for i, t in enumerate([101, 201, 301, 401, 102, 202, 302, 402, 103, 203, 303, 403], start=1)}
    monkeypatch.setattr(data.rankings, "read_final_ranks_for_season", lambda database, season: {KEY: ranks})
    result = run_m1(None, {2027: SeasonRuleset.model_validate(ruleset(2027))}, seasons=(2027,))
    assert list(result["seasons"]) == [2027]
    info = result["events"][KEY]
    assert info["status"] == "reproduced" and (info["winner_seed"], info["finalist_seed"]) == (1, 3)
    assert result["seasons"][2027]["selection_rule_violations"] == 0 and result["escalate"] is False


def test_c0_refuses_without_an_approved_2027_ruleset(monkeypatch):
    import data.rulesets
    from scripts.phase6_playoff_track import Blocked, require_rulesets

    monkeypatch.setattr(data.rulesets, "approved_seasons", lambda database: [2024, 2025, 2026])
    with pytest.raises(Blocked) as blocked:
        require_rulesets(None, (2027,))
    assert blocked.value.code == 2


def test_c0_refuses_without_2027_playoff_data(monkeypatch):
    import scripts.phase6_px1b as px1b_harness
    from scripts.phase6_playoff_track import Blocked, run_m1_2027

    monkeypatch.setattr(px1b_harness, "_playoff_matches", lambda database, season: 0)
    with pytest.raises(Blocked):
        run_m1_2027(None, {2027: SeasonRuleset.model_validate(ruleset(2027))})


def test_c0_has_its_own_record_and_needs_the_2027_ruleset():
    from scripts.phase6_playoff_track import RUN_SEASONS, RUNS

    assert RUNS["m1-2027"][0] == "p6_m1_ruleset_check_2027.json"
    assert RUNS["m1"][0] == "p6_m1_ruleset_check.json"  # the 2024-2026 record is untouched
    assert RUN_SEASONS["m1-2027"] == (2027,) and "m1" not in RUN_SEASONS


# --- C4: the PX-1b pointers ----------------------------------------------------------------------------------


def test_the_frozen_px1_chain_is_the_unchanged_default():
    from scripts import phase6_playoff_track as track

    t = track.PX1_TRACK
    assert (t.model_record, t.version_tag, t.calibration_season, t.holdout) == ("p6_m2_px1.json", "px1-v1", 2025, 2026)
    assert (t.px2_record, t.px4_record, t.m8_run_record, t.m8_record) == (
        "p6_m3_px2.json", "p6_m5_px4.json", "p6_m8_dm1_run.json", "p6_m8_dm1.json")
    assert t.calibrator_file == "px2_calibrator.json"
    assert t.sentinel_time == track.M8_FAR_FUTURE == "2026-12-31T00:00:00+00:00"
    assert t.confirmation is None and not t.exclude_playoffs_before_selection and not t.requires_mentor_agreement
    assert (t.epa_snapshot, t.epa_chain) == (track.SNAPSHOT, track.CHAIN) and t.specs is None
    assert track._track_info(t) == {}  # the PX-1 records keep their exact shape
    assert [track.RUNS[k][0] for k in ("m3", "m5", "m8", "m8-review")] == [
        "p6_m3_px2.json", "p6_m5_px4.json", "p6_m8_dm1_run.json", "p6_m8_dm1.json"]


def test_the_px1b_chain_points_at_its_own_records_models_and_2027():
    from scripts import phase6_playoff_track as track

    t = track.PX1B_TRACK
    assert (t.model_record, t.version_tag, t.calibration_season, t.holdout) == (
        "p6_px1b_gate_2027.json", "px1b-v1", 2026, 2027)
    assert [track.RUNS[k][0] for k in ("px2b", "px4b", "m8b", "m8b-review")] == [
        "p6_px2b.json", "p6_px4b.json", "p6_m8b_dm1_run.json", "p6_m8b_dm1.json"]
    assert t.calibrator_file == "px2b_calibrator.json" and t.sentinel_time > "2027-12-30"
    assert t.exclude_playoffs_before_selection and t.requires_mentor_agreement
    assert track.RUN_SEASONS["px2b"] == (2026, 2027) and track.RUN_SEASONS["m8b"] == (2027,)
    assert set(t.specs) == {"px2b", "px4b", "m8b"}


def test_models_load_from_the_tracks_registry_tag(monkeypatch):
    """The registry paths only. Pinning (G1) is switched off here and tested in tests/test_phase6_pins.py."""
    from dataclasses import replace

    from ml.playoffs import px1
    from scripts import phase6_playoff_track as track

    loaded = []
    monkeypatch.setattr(px1.PlayoffLogisticModel, "load", classmethod(lambda cls, path: loaded.append(path) or path))
    track._models()
    track._models(replace(track.PX1B_TRACK, pins_record=None))
    parts = [p.parts[-3:] for p in loaded]
    assert parts == [("playoff_px1", "px1-v1", "model.json"), ("playoff_seed_only", "px1-v1", "model.json"),
                     ("playoff_px1b", "px1b-v1", "model.json"), ("playoff_px1b_seed_only", "px1b-v1", "model.json")]


@pytest.fixture
def px1b_results(tmp_path, monkeypatch):
    """A tmp results dir and confirmation path for PX-1b's acceptance (SYNTHETIC records, never real ones)."""
    import json
    from dataclasses import replace

    import scripts.phase6_common as common
    from scripts import phase6_playoff_track as track

    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(common, "RESULTS_DIR", results)
    monkeypatch.setattr(track, "RESULTS_DIR", results)
    t = replace(track.PX1B_TRACK, confirmation=tmp_path / "confirmation.json")

    def write(name, value):
        (results / name).write_text(json.dumps(value), encoding="utf-8")
    return t, results, write


def _confirm(t, results, **overrides):
    import json

    from scripts.phase6_common import file_sha256

    value = {"confirmed": True, "confirmed_by": "SYNTHETIC", "date": "2099-01-01", "record": t.model_record,
             "record_sha256": file_sha256(results / t.model_record)}
    value.update(overrides)
    t.confirmation.write_text(json.dumps(value), encoding="utf-8")


def test_px1b_acceptance_needs_the_gate_pass_and_a_sha_matched_confirmation(px1b_results):
    from scripts.phase6_playoff_track import Blocked, _require_model

    t, results, write = px1b_results
    with pytest.raises(Blocked):
        _require_model(t)  # no FINAL-1 record
    write(t.model_record, {"passed": False})
    with pytest.raises(Blocked):
        _require_model(t)  # FINAL-1 failed
    write(t.model_record, {"passed": True})
    with pytest.raises(Blocked):
        _require_model(t)  # no confirmation
    _confirm(t, results, record_sha256="0" * 64)
    with pytest.raises(Blocked):
        _require_model(t)  # confirms some other record
    _confirm(t, results, confirmed=False)
    with pytest.raises(Blocked):
        _require_model(t)
    _confirm(t, results)
    assert _require_model(t) == {"passed": True}


def test_px2b_and_px4b_each_refuse_until_their_prerequisites_pass(px1b_results):
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    t, results, write = px1b_results
    with pytest.raises(Blocked):
        track.run_m3(None, None, t)  # PX-1b not accepted
    with pytest.raises(Blocked):
        track.run_m5(None, None, t)  # no p6_px2b.json
    write(t.px2_record, {"passed": False})
    with pytest.raises(Blocked):
        track.run_m5(None, None, t)  # PX-2b failed
    write(t.px2_record, {"passed": True})
    with pytest.raises(Blocked):
        track.run_m5(None, None, t)  # PX-2b passed, but PX-1b is still not accepted


def test_m8b_needs_its_pre_run_record_and_the_mentors_confirmed_agreement(px1b_results, tmp_path):
    import json
    from dataclasses import replace

    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    t, results, write = px1b_results
    t = replace(t, m8_pre_run=tmp_path / "PRE.md", m8_pre_run_json=tmp_path / "pre.json")
    with pytest.raises(Blocked):
        track.run_m8(None, None, t)  # no pre-run record
    t.m8_pre_run.write_text("synthetic", encoding="utf-8")
    base = {"seed": 1, "per_stratum": 1, "reason_categories": [{"code": "x"}], "mentor": "SYNTHETIC MENTOR"}
    for agreement in (None, {"confirmed": False, "date": "d", "evidence": "e"}, {"confirmed": True, "date": "d"}):
        t.m8_pre_run_json.write_text(json.dumps({**base, "mentor_agreement": agreement}), encoding="utf-8")
        with pytest.raises(Blocked):
            track._m8_config(t)  # agreement absent, unconfirmed, or without evidence
    confirmed = {"confirmed": True, "date": "d", "evidence": "e"}
    t.m8_pre_run_json.write_text(json.dumps({**base, "mentor_agreement": confirmed}), encoding="utf-8")
    assert track._m8_config(t)["mentor"] == "SYNTHETIC MENTOR"
    with pytest.raises(Blocked):
        track.run_m8(None, None, t)  # agreement confirmed, but PX-4b has not passed


def test_the_frozen_m8_config_does_not_require_the_new_agreement_field():
    from scripts import phase6_playoff_track as track

    assert track._m8_config()["mentor"] == "Mr. Biery"  # the committed P6-M8 pre-run record: unchanged behaviour


def test_the_real_m8b_pre_run_record_does_not_exist_yet():
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    assert not track.PX1B_TRACK.m8_pre_run_json.exists()  # written by people, never fabricated
    with pytest.raises(Blocked):
        track._m8_config(track.PX1B_TRACK)


def test_px1b_epa_source_must_be_configured_for_2027():
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    with pytest.raises(Blocked):
        track._epa_source(track.PX1B_TRACK)
    assert track._epa_source(track.PX1_TRACK) == (track.SNAPSHOT, track.CHAIN)


def test_the_leakage_exclusion_applies_to_the_px1b_population_only():
    from scripts.phase6_playoff_track import PLAYOFF_BEFORE_SELECTION, representable_events

    leaky = synthetic_2027_event(last_qualification=T + timedelta(hours=5))  # playoffs before the selection moment
    clean = synthetic_2027_event()
    rules = {2027: SeasonRuleset.model_validate(ruleset(2027))}
    m1 = {"events": {KEY: {"status": "reproduced"}}}
    result = representable_events(rules, m1, [leaky], exclude_playoffs_before_selection=True)
    assert result["validated_events"] == 0
    assert result["excluded_events"][KEY] == {"reason": PLAYOFF_BEFORE_SELECTION, "alliances": 4}
    assert representable_events(rules, m1, [leaky])["validated_events"] == 1  # PX-1's frozen population: unchanged
    assert representable_events(rules, m1, [clean], exclude_playoffs_before_selection=True)["validated_events"] == 1


def test_px2b_no_longer_has_the_v1_in_sample_path(px1b_results, tmp_path, monkeypatch):
    """PX-2b v2 governs (approved 2026-10-08): with PX-1b accepted (SYNTHETIC) but no calibration-base record, PX-2b
    refuses. It never falls back to v1's calibration on px1b-v1's own predictions. The v2 path is tested end to end
    in tests/test_phase6_px2b_v2.py."""
    from dataclasses import replace

    from ml.calibration.calibrator import SymmetricIsotonicCalibrator
    from ml.playoffs.px1 import PlayoffLogisticModel
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked
    from tests.test_phase6_px1 import synthetic_rows

    t, results, write = px1b_results
    write(t.model_record, {"passed": True})
    _confirm(t, results)
    base = synthetic_rows(500, 11)
    rows = ([replace(r, season=2026, scheduled_time=T - timedelta(days=200) + timedelta(minutes=i))
             for i, r in enumerate(base[:300])]
            + [replace(r, season=2027, scheduled_time=T + timedelta(minutes=i)) for i, r in enumerate(base[300:])])
    model = PlayoffLogisticModel.fit(rows[:300], normalized=True, model_type="playoff_px1b")
    monkeypatch.setattr(track, "_models", lambda tr=None: (model, model))
    monkeypatch.setattr(track, "_track_rows", lambda database, rulesets, tr: rows)
    monkeypatch.setattr(track, "ROWS_CACHE_DIR", tmp_path)
    fitted = []
    monkeypatch.setattr(SymmetricIsotonicCalibrator, "fit", lambda self, p, y: fitted.append(p))
    assert t.calibration_base_record == "p6_px2b_calbase.json" and t.specs["px2b"].endswith("_V2.md")
    with pytest.raises(Blocked):
        track.run_m3(None, None, t)  # no p6_px2b_calbase.json: refused
    assert fitted == [] and not (tmp_path / "px2b_calibrator.json").exists()


def test_the_frozen_px2_still_refuses_on_the_real_px1_record():
    from scripts import phase6_playoff_track as track
    from scripts.phase6_playoff_track import Blocked

    with pytest.raises(Blocked):
        track.run_m3(None, None)  # p6_m2_px1.json: passed false (D9)


def test_reliability_bins_cover_the_unit_interval():
    from scripts.phase6_playoff_track import reliability_bins

    bins = reliability_bins([0.05, 0.05, 0.95, 1.0], [False, True, True, True])
    assert len(bins) == 10 and sum(b["count"] for b in bins) == 4
    assert bins[0]["observed"] == 0.5 and bins[9]["count"] == 2 and bins[5]["mean_predicted"] is None
