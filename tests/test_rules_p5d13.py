"""P5-D13 rules: similarity, candidate archetypes, expected ranges, dominant component, κ gate, reconciliation.

Pure. Every spec, codebook, coding and mapping here is a **synthetic test fixture**: not entered from any manual,
not human-authored, not evidence about any game.
"""

from __future__ import annotations

import pytest

from data.design_reference import (
    LABELS_AS_CATEGORIES,
    LABELS_PROVISIONAL,
    Codebook,
    Coding,
    agreement,
    label_status,
    reconcile_with_consensus,
)
from data.game_spec import GameSpec
from ml.gameanalysis import rules_p5d13 as rules
from ml.gameanalysis.analysis import analyze
from tests.test_game_analysis import _spec


def _game(season: int, *, auto_points: float = 4, climb: float = 10, element_type: str = "goal") -> GameSpec:
    spec = _spec(season)
    spec["scoring_actions"][0]["points"] = auto_points
    spec["scoring_actions"][2]["points"] = climb
    spec["field_elements"][0]["element_type"] = element_type
    return GameSpec.model_validate(spec)


BOOK = Codebook(version="fixture", authored_by="fixture",
                functions={"shooter": "scoring", "climber": "endgame", "intake": "acquisition"})
MAP = rules.ActionFunctionMap(version="fixture", authored_by="fixture", codebook_sha256=BOOK.sha256(),
                              mapping={"score_piece": ["shooter", "intake"], "climb": ["climber"], "unused": ["intake"]})


def test_period_shares_and_similarity():
    shares = rules.period_shares(_game(2026))
    assert sum(shares.values()) == pytest.approx(1.0)
    ranked = rules.similarity(_game(2026), [_game(2024, auto_points=40), _game(2025), _game(2023)])
    assert ranked[0]["season"] == 2025  # identical shares and types; the more recent of the tied pair
    assert ranked[0]["cosine_period_shares"] == pytest.approx(1.0) and ranked[0]["jaccard_field_element_types"] == 1.0
    assert ranked[0]["similarity"] == pytest.approx(2.0)
    other = rules.similarity(_game(2026), [_game(2025, element_type="hub")])[0]
    assert other["jaccard_field_element_types"] == 0.0


def test_candidate_archetypes_only_from_actions_in_the_spec():
    candidates = rules.candidate_archetypes(_game(2026), BOOK, MAP)
    assert {c["archetype"] for c in candidates} == {"shooter", "intake", "climber"}
    assert next(c for c in candidates if c["archetype"] == "climber")["family"] == "endgame"
    bad = MAP.model_copy(update={"codebook_sha256": "0" * 64})
    with pytest.raises(ValueError):
        rules.candidate_archetypes(_game(2026), BOOK, bad)


def _ranges() -> dict:
    component = {"p10": 10.0, "p25": 15.0, "p50": 20.0, "p75": 25.0, "p90": 30.0, "n": 100}
    return {"seasons": {"2025": {c: dict(component) for c in ("auto", "teleop", "endgame", "fouls")}}}


def test_expected_ranges_rescale_by_period_and_leave_fouls():
    expected = rules.expected_ranges(_game(2026, climb=20), [_game(2025, climb=10), _game(2023)], _ranges())
    assert expected["label"] == "not_validated" and expected["source_season"] == 2025
    assert expected["components"]["endgame"]["ratio"] == 2.0 and expected["components"]["endgame"]["high"] == 60.0
    assert expected["components"]["fouls"]["ratio"] == 1.0 and expected["components"]["auto"]["median"] == 20.0
    assert rules.dominant_components(expected)[0] == "endgame"


def test_the_decided_rules_run_through_analyze():
    consensus = Coding(coder="consensus", codebook_sha256=BOOK.sha256(), labels={1: ["shooter"]})
    rule_set = rules.build_rules([_game(2025)], BOOK, MAP, consensus)
    result = analyze(_game(2026), [_game(2025)], _ranges(), rule_set)
    assert result["similarity"]["rule_version"] == "P5-D13"
    assert result["predicted_dominant_components"]["components"]
    assert rule_set.reconcile_codings(None, None) is consensus


def test_kappa_gate_pooled_overall_and_per_function_provisional():
    a = Coding(coder="a", codebook_sha256=BOOK.sha256(), labels={1: ["shooter"], 2: ["climber"], 3: ["shooter"],
                                                                 4: ["intake"]})
    b = Coding(coder="b", codebook_sha256=BOOK.sha256(), labels={1: ["shooter"], 2: ["climber"], 3: ["shooter"],
                                                                 4: ["climber"]})
    status = label_status(agreement(BOOK, a, b))
    assert status["functions"]["shooter"] == LABELS_AS_CATEGORIES
    assert status["functions"]["intake"] == LABELS_PROVISIONAL  # its own κ is below 0.6, whatever the pooled κ
    poor = label_status({"pooled_kappa": 0.4, "per_function_kappa": {"shooter": 0.9}})
    assert poor == {"overall": LABELS_PROVISIONAL, "functions": {"shooter": LABELS_PROVISIONAL}}


def test_reconciliation_serves_the_consensus_never_the_first_coder():
    a = Coding(coder="a", codebook_sha256=BOOK.sha256(), labels={1: ["shooter"], 2: ["climber"]})
    b = Coding(coder="b", codebook_sha256=BOOK.sha256(), labels={1: ["intake"], 2: ["climber"]})
    consensus = Coding(coder="consensus", codebook_sha256=BOOK.sha256(), labels={1: ["shooter", "intake"], 2: ["climber"]})
    assert reconcile_with_consensus(BOOK, a, b, consensus) is consensus
    with pytest.raises(ValueError):
        reconcile_with_consensus(BOOK, a, b, a)  # a coder's own labels are not a consensus


def test_dm1_runner_wiring_end_to_end(tmp_path, monkeypatch):
    """Wiring only: synthetic fixtures through scripts/phase5_dm1_dry_run.run (nothing recorded, no database)."""
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from data.game_spec import write_catalog_manifest
    from ml.features.score_components import ScoreComponents
    from ml.meta.weekly import ComponentRow
    from scripts import phase5_dm1_dry_run as dm1
    from tests.test_game_analysis import _rubric

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    for season in (2024, 2025):
        (catalog / f"{season}.json").write_text(_game(season).model_dump_json(), encoding="utf-8")
    write_catalog_manifest(catalog)
    spec = _game(2026, climb=20).model_copy(update={"source": _game(2026).source.model_copy(
        update={"entry_started_at": datetime.now(timezone.utc), "entry_completed_at": datetime.now(timezone.utc)})})
    (tmp_path / "spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    rows = list(range(1, 78))  # every curated reference row must be coded
    files = {
        "codebook": BOOK.model_dump_json(),
        "a": Coding(coder="a", codebook_sha256=BOOK.sha256(), labels={r: ["shooter"] for r in rows}).model_dump_json(),
        "b": Coding(coder="b", codebook_sha256=BOOK.sha256(), labels={r: ["shooter"] for r in rows}).model_dump_json(),
        "consensus": Coding(coder="consensus", codebook_sha256=BOOK.sha256(),
                            labels={r: ["shooter"] for r in rows}).model_dump_json(),
        "map": MAP.model_dump_json(), "rubric": _rubric().model_dump_json(),
        "profiles": json.dumps([{"profile_id": f"p{i}", "budget_usd": 1000 * i, "manufacturing": i % 4,
                                 "programming": 2, "mentoring": 1, "submitted_at": "2026-01-01T00:00:00+00:00"}
                                for i in range(10)]),
    }
    for name, body in files.items():
        (tmp_path / f"{name}.json").write_text(body, encoding="utf-8")
    synthetic_rows = [ComponentRow(s, "e", 1, f"m{i}", "red", ScoreComponents(i, 2 * i, 3, 1, 0, 3 * i + 4), 3 * i + 4)
                      for s in (2024, 2025) for i in range(1, 11)]
    monkeypatch.setattr(dm1, "_component_rows", lambda seasons: [r for r in synthetic_rows if r.season in seasons])
    args = SimpleNamespace(spec=tmp_path / "spec.json", catalog=catalog, codebook=tmp_path / "codebook.json",
                           coding=[tmp_path / "a.json", tmp_path / "b.json"], consensus=tmp_path / "consensus.json",
                           action_map=tmp_path / "map.json", rubric=tmp_path / "rubric.json",
                           profiles=tmp_path / "profiles.json")
    record = dm1.run(args)
    assert record["inputs"]["rules_version"] == "P5-D13" and record["clock"]["within_5_days"]
    assert record["codebook_agreement"]["status"]["overall"] in ("categories", "provisional")
    assert len(record["recommendations"]) == 10
    examples = [e for a in record["analysis"]["candidate_archetypes"]["archetypes"]
                for e in a["historical_design_examples"]]
    assert examples and all(e["label"] == "curated_reference_unverified" and e["year"] < 2026 for e in examples)
    assert record["analysis"]["expected_scoring_ranges"]["label"] == "not_validated"
