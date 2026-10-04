"""P5-M8/M9 infrastructure: spec schema, catalog integrity, curated reference, κ, analysis slots, rubric.

Pure. The game specs, codebook, codings, rubric, profiles and rules below are **synthetic test fixtures**. They are
not entered from any manual, not human-authored, and not evidence about any game; DM1's real inputs are
human-only (.agent/phase5/M08_DECISION_REQUIRED.md).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from data.design_reference import (
    CURATED_REFERENCE_UNVERIFIED,
    LABELS_AS_CATEGORIES,
    LABELS_PROVISIONAL,
    Codebook,
    Coding,
    ReferenceIntegrityError,
    agreement,
    before_reveal,
    cohens_kappa,
    examples_by_function,
    label_status,
    load_reference,
    validate_codings,
)
from data.game_spec import CatalogIntegrityError, GameSpec, load_catalog, write_catalog_manifest
from data.game_spec import before_reveal as specs_before
from ml.features.score_components import ScoreComponents
from ml.gameanalysis.analysis import RuleNotDecided, Rules, analyze, component_ranges, value_table
from ml.gameanalysis.capability import HEURISTIC, CapabilityIntake, Rubric, land_intake, recommend
from ml.meta.weekly import ComponentRow

T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def _spec(season: int = 2026, **overrides) -> dict:
    spec = {"season": season, "game_name": f"SYNTHETIC {season}",
            "match_length": {"auto_seconds": 15, "teleop_seconds": 135, "endgame_seconds": 20},
            "scoring_actions": [
                {"action_id": "a_piece", "name": "piece", "period": "auto", "points": 4, "unit": "piece",
                 "field_element_id": "goal", "action_type": "score_piece", "manual_section": "6.4"},
                {"action_id": "t_piece", "name": "piece", "period": "teleop", "points": 2, "unit": "piece",
                 "field_element_id": "goal", "action_type": "score_piece", "manual_section": "6.4"},
                {"action_id": "climb", "name": "climb", "period": "endgame", "points": 10, "unit": "robot",
                 "action_type": "climb", "manual_section": "6.5"}],
            "ranking_point_rules": [{"rule_id": "win", "description": "win", "ranking_points": 3,
                                     "manual_section": "11.6"}],
            "field_elements": [{"element_id": "goal", "name": "goal", "count": 1, "element_type": "goal",
                                "manual_section": "5.2"}],
            "source": {"manual_title": "synthetic", "manual_version": "0", "entered_by": "fixture",
                       "entry_started_at": T.isoformat(), "entry_completed_at": T.isoformat()}}
    spec.update(overrides)
    return spec


def test_spec_schema_rules():
    spec = GameSpec.model_validate(_spec())
    assert len(spec.sha256()) == 64 and spec.sha256() == GameSpec.model_validate(_spec()).sha256()
    bad = _spec()
    bad["scoring_actions"][1]["action_id"] = "a_piece"
    with pytest.raises(ValueError):
        GameSpec.model_validate(bad)
    with pytest.raises(ValueError):
        GameSpec.model_validate(_spec(field_elements=[]))  # an action references an unknown element
    with pytest.raises(ValueError):
        GameSpec.model_validate({**_spec(), "source": {**_spec()["source"], "llm_used": True}})
    with pytest.raises(ValueError):
        GameSpec.model_validate({**_spec(), "source": {**_spec()["source"], "entry_started_at": "2026-01-10T12:00:00"}})


def test_catalog_integrity_and_pre_reveal(tmp_path):
    for season in (2024, 2025):
        (tmp_path / f"{season}.json").write_text(json.dumps(_spec(season)), encoding="utf-8")
    write_catalog_manifest(tmp_path)
    catalog = load_catalog(tmp_path)
    assert [g.season for g in catalog] == [2024, 2025] and specs_before(catalog, 2025)[0].season == 2024
    (tmp_path / "2024.json").write_text(json.dumps(_spec(2024, game_name="EDITED")), encoding="utf-8")
    with pytest.raises(CatalogIntegrityError):
        load_catalog(tmp_path)
    (tmp_path / "2024.json").write_text(json.dumps(_spec(2024)), encoding="utf-8")
    (tmp_path / "2023.json").write_text(json.dumps(_spec(2023)), encoding="utf-8")
    with pytest.raises(CatalogIntegrityError):
        load_catalog(tmp_path)  # unlisted file


def test_reference_is_verified_verbatim_and_filtered():
    reference = load_reference()
    assert len(reference) == 77 and all(e.label == CURATED_REFERENCE_UNVERIFIED for e in reference)
    assert reference[0].micro_archetype == "Central Turret Vector Shooter"
    assert len(before_reveal(reference, 2026)) == 67  # the 10 REBUILT rows are excluded
    with pytest.raises(ReferenceIntegrityError):
        load_reference(expected_sha256="0" * 64)


def _codebook() -> Codebook:
    return Codebook(version="fixture", authored_by="fixture", functions={"shoot": "scoring", "climb": "endgame"})


def test_kappa_and_label_status():
    assert cohens_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cohens_kappa([True, True], [True, True]) is None
    assert cohens_kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0.0)
    book = _codebook()
    a = Coding(coder="a", codebook_sha256=book.sha256(), labels={1: ["shoot"], 2: ["climb"], 3: ["shoot", "climb"]})
    b = Coding(coder="b", codebook_sha256=book.sha256(), labels={1: ["shoot"], 2: ["climb"], 3: ["shoot"]})
    validate_codings(book, a, b, [1, 2, 3])
    result = agreement(book, a, b)
    assert result["per_function_kappa"]["shoot"] == 1.0
    status = label_status(result)  # P5-D13: pooled gate overall, per-function provisional below 0.6
    assert status["overall"] in (LABELS_AS_CATEGORIES, LABELS_PROVISIONAL)
    assert status["functions"]["climb"] == LABELS_PROVISIONAL
    with pytest.raises(ValueError):
        validate_codings(book, a, a, [1, 2, 3])  # one coder twice
    examples = examples_by_function(load_reference(), a, "climb")
    assert [e.row_id for e in examples] == [2, 3]


def _rows() -> list[ComponentRow]:
    return [ComponentRow(season, "e", 1, f"m{i}", "red", ScoreComponents(i, 2 * i, 3, 1, 0, 3 * i + 4), 3 * i + 4)
            for season in (2024, 2025, 2026) for i in range(1, 11)]


def test_value_table_and_ranges_respect_the_reveal():
    table = value_table(GameSpec.model_validate(_spec()))
    assert table["periods"]["endgame"] == {"actions": 1, "max_points_per_unit": 10, "period_seconds": 20}
    assert table["periods"]["teleop"]["period_seconds"] == 115
    ranges = component_ranges(_rows(), 2026)
    assert sorted(ranges["seasons"]) == ["2024", "2025"] and ranges["excluded_seasons_at_or_after_reveal"] == [2026]


def test_undecided_rules_refuse_and_catalog_leakage_is_refused():
    spec = GameSpec.model_validate(_spec())
    catalog = [GameSpec.model_validate(_spec(2025))]
    with pytest.raises(RuleNotDecided):
        analyze(spec, catalog, {}, Rules())
    synthetic = Rules(version="fixture-only", similarity=lambda s, c: [{"season": g.season} for g in c],
                      candidate_archetypes=lambda s, t: [{"archetype": "x", "functions": ["shoot"]}],
                      expected_ranges=lambda s, r: {}, dominant_components=lambda s, t: ["teleop"])
    result = analyze(spec, catalog, {}, synthetic)
    assert result["candidate_archetypes"]["label"] == "not_validated"
    with pytest.raises(ValueError):
        analyze(spec, [GameSpec.model_validate(_spec(2026))], {}, synthetic)


def _rubric() -> Rubric:
    return Rubric(version="fixture", authored_by="fixture", season=2026, archetypes=[
        {"archetype": "simple", "tier": 1, "priority": 2, "min_budget_usd": 0, "min_levels": {},
         "achievable_features": ["drive"]},
        {"archetype": "shooter", "tier": 2, "priority": 1, "min_budget_usd": 5000,
         "min_levels": {"manufacturing": 2, "programming": 2}, "achievable_features": ["shoot"]}])


def test_rubric_is_deterministic_and_explained():
    strong = CapabilityIntake(profile_id="p1", budget_usd=8000, manufacturing=3, programming=2, mentoring=1,
                              submitted_at=T)
    weak = strong.model_copy(update={"profile_id": "p2", "budget_usd": 1000})
    a = recommend(strong, _rubric(), ["simple", "shooter"])
    assert a == recommend(strong, _rubric(), ["simple", "shooter"])
    assert a["label"] == HEURISTIC and a["recommended_archetype"] == "shooter" and a["realistic_ceiling_tier"] == 2
    b = recommend(weak, _rubric(), ["simple", "shooter"])
    assert b["recommended_archetype"] == "simple"
    assert any("budget" in u for e in b["explanation"] for u in e["requirements_unmet"])


def test_intake_lands_raw_first_even_when_invalid():
    landed = []
    writer = type("W", (), {"write": lambda self, record: landed.append(record)})()
    with pytest.raises(ValueError):
        land_intake(writer, {"profile_id": "bad", "budget_usd": -1})
    assert landed[0].payload == {"profile_id": "bad", "budget_usd": -1}  # recorded before validation
