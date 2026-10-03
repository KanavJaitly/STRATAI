"""DM1: the pre-season pipeline's end-to-end dry run against the 2026 game reveal (P5-M9).

    python -m scripts.phase5_dm1_dry_run run --spec SPEC_2026.json --catalog CATALOG_DIR --codebook CODEBOOK.json \\
        --coding A.json --coding B.json --rubric RUBRIC.json --profiles PROFILES.json --rules RULES_MODULE
    python -m scripts.phase5_dm1_dry_run score            # once, after `run`: against 2026 weeks 1–3
    python -m scripts.phase5_dm1_dry_run mentor-review --review REVIEW.json

**`run`** is one end-to-end execution from spec entry to every documented output:
- the P5-M8 analysis: value table, similarity, candidate archetypes with historical design examples, and expected
  scoring ranges;
- P5-M9 recommendations for every sample profile.

It works as follows:
- it refuses if any human input is missing, or if a catalog game or reference row is from the reveal year or
  later;
- it reads 2024–2025 breakdown data only (the reveal is 2026);
- elapsed time runs from the spec's `entry_started_at` (the simulated reveal) to the moment the outputs are
  recorded, and it must be ≤ 5 days;
- predictions are recorded write-once (`dm1_dry_run.json`) before any 2026 match data is read.

**`score`** runs once. It reads 2026 weeks 1–3 and compares predicted with actual dominant components, and the
coverage of the expected ranges. Its output is labelled `not_validated` regardless of the score
(`dm1_score.json`).

**`mentor-review`** records the human mentor review (`dm1_mentor_review.json`).

The Q3 rules come from `--rules`: a module exposing `RULES` (ml.gameanalysis.analysis.Rules) with a decided
version. Until Q3 is decided, no such module exists and `run` refuses.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REVEAL = 2026
LIMIT = timedelta(days=5)
RUN_RECORD, SCORE_RECORD, REVIEW_RECORD = "dm1_dry_run.json", "dm1_score.json", "dm1_mentor_review.json"
MIN_PROFILES = 10


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _component_rows(seasons: list[int]):
    from data.config import Settings
    from database.connection import DatabaseConfig
    from database.readonly import ReadOnlySessionDatabase
    from scripts.phase5_m7_meta import load_rows

    database = ReadOnlySessionDatabase(DatabaseConfig(Settings().database_url))
    rows, _, failures = load_rows(database, seasons=seasons)
    if failures:
        raise SystemExit(f"{len(failures)} breakdown rows failed the P5-M7 adapters")
    return rows


def run(args) -> dict[str, Any]:
    from data.design_reference import (
        Codebook,
        Coding,
        agreement,
        before_reveal,
        examples_by_function,
        load_reference,
        validate_codings,
    )
    from data.game_spec import before_reveal as specs_before, load_catalog, load_spec
    from ml.gameanalysis.analysis import analyze, component_ranges
    from ml.gameanalysis.capability import CapabilityIntake, Rubric, recommend

    spec = load_spec(args.spec)
    if spec.season != REVEAL:
        raise SystemExit(f"the dry run reveals {REVEAL}; the spec is {spec.season}")
    catalog = load_catalog(args.catalog)
    if specs_before(catalog, REVEAL) != catalog:
        raise SystemExit("the catalog holds a game from the reveal year or later (DM1 leakage rule)")
    rules = importlib.import_module(args.rules).RULES
    codebook = Codebook.model_validate_json(Path(args.codebook).read_text(encoding="utf-8"))
    first, second = (Coding.model_validate_json(Path(p).read_text(encoding="utf-8")) for p in args.coding)
    reference = load_reference()
    validate_codings(codebook, first, second, [e.row_id for e in reference])
    examples = before_reveal(reference, REVEAL)  # the 10 REBUILT rows are excluded
    rubric = Rubric.model_validate_json(Path(args.rubric).read_text(encoding="utf-8"))
    profiles = [CapabilityIntake.model_validate(p) for p in json.loads(Path(args.profiles).read_text(encoding="utf-8"))]
    if len(profiles) < MIN_PROFILES:
        raise SystemExit(f"{len(profiles)} sample profiles; P5-M9 fixes at least {MIN_PROFILES} before the run")

    ranges = component_ranges(_component_rows([s for s in (2024, 2025) if s < REVEAL]), REVEAL)
    analysis = analyze(spec, catalog, ranges, rules)
    kappa = agreement(codebook, first, second)
    labels = rules.require("reconcile_codings")(first, second)
    archetypes = analysis["candidate_archetypes"]["archetypes"]
    for archetype in archetypes:
        archetype["historical_design_examples"] = [
            {"row_id": e.row_id, "year": e.year, "team": e.team, "micro_archetype": e.micro_archetype,
             "label": e.label}
            for function in archetype.get("functions", [])
            for e in examples_by_function(examples, labels, function)]
    names = [a["archetype"] for a in archetypes]
    recommendations = [recommend(p, rubric, names) for p in profiles]
    finished = datetime.now(timezone.utc)
    elapsed = finished - spec.source.entry_started_at
    return {"done_means": "DM1", "reveal_season": REVEAL,
            "clock": {"started": spec.source.entry_started_at.isoformat(), "outputs_recorded": finished.isoformat(),
                      "elapsed_hours": elapsed.total_seconds() / 3600, "within_5_days": elapsed <= LIMIT},
            "inputs": {"spec_sha256": spec.sha256(), "spec_entered_by": spec.source.entered_by,
                       "catalog": [{"season": g.season, "sha256": g.sha256()} for g in catalog],
                       "codebook_sha256": codebook.sha256(), "codings": [_sha(p) for p in args.coding],
                       "rubric_sha256": rubric.sha256(), "profiles_sha256": _sha(args.profiles),
                       "rules_version": rules.version, "reference_rows_used": len(examples)},
            "codebook_agreement": kappa, "analysis": analysis, "past_component_ranges": ranges,
            "recommendations": recommendations, "data_read": "breakdowns of 2024-2025 only; no 2026 match data"}


def score(run_record: dict[str, Any]) -> dict[str, Any]:
    """Scored once against 2026 weeks 1–3; not_validated regardless (one game cannot validate a predictive claim)."""
    from ml.features.score_components import COMPONENTS

    rows = [r for r in _component_rows([REVEAL]) if r.week is not None and 1 <= r.week <= 3]
    shares = {c: sum(r.parts.share(c) or 0 for r in rows) / len(rows) for c in COMPONENTS}
    actual = sorted(COMPONENTS, key=lambda c: -shares[c])
    predicted = run_record["analysis"]["predicted_dominant_components"]["components"]
    ranges = run_record["analysis"]["expected_scoring_ranges"]["ranges"]
    coverage = {}
    for component, bounds in ranges.items():
        values = [getattr(r.parts, component) for r in rows]
        inside = sum(bounds["low"] <= v <= bounds["high"] for v in values)
        coverage[component] = {"inside": inside, "n": len(values), "share": inside / len(values)}
    return {"label": "not_validated", "reason": "one game cannot validate a predictive claim",
            "alliance_rows": len(rows), "actual_mean_share": shares, "actual_order": actual,
            "predicted_order": predicted, "dominant_match": bool(predicted) and predicted[0] == actual[0],
            "range_coverage": coverage}


def main(argv: list[str] | None = None) -> int:
    from scripts.phase5_records import RESULTS_DIR, write_once

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    for name in ("--spec", "--catalog", "--codebook", "--rubric", "--profiles"):
        r.add_argument(name, type=Path, required=True)
    r.add_argument("--coding", type=Path, action="append", required=True)
    r.add_argument("--rules", required=True, help="module exposing RULES with the decided Q3 rule set")
    sub.add_parser("score")
    m = sub.add_parser("mentor-review")
    m.add_argument("--review", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        if len(args.coding) != 2:
            parser.error("double coding needs exactly two --coding files")
        path = write_once(RUN_RECORD, run(args))
    elif args.command == "score":
        recorded = RESULTS_DIR / RUN_RECORD
        if not recorded.exists():
            raise SystemExit("record the dry run first: predictions precede any 2026 match data")
        path = write_once(SCORE_RECORD, score(json.loads(recorded.read_text(encoding="utf-8"))))
    else:
        review = json.loads(Path(args.review).read_text(encoding="utf-8"))
        if not review.get("reviewer") or not review.get("reviewed_at"):
            raise SystemExit("a mentor review names its reviewer and date")
        path = write_once(REVIEW_RECORD, {"review": review, "review_sha256": _sha(args.review)})
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
