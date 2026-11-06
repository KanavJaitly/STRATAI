"""P11A E2 research: audit TBA's per-robot score-breakdown fields for 2024-2026 against the E1b individual
ground-truth standard (docs/P11-RecommendationIntelligence.md section 20).

    python -I research/p11_e2/audit_fields.py --cache research/p11_e2/cache --out research/p11_e2/results

Source: TBA's public OpenAPI schema (no key needed). It is stored raw with its sha256 before parsing.

**What this can and cannot check.**
- Field names, types and allowed values come from the schema itself.
- Data-level checks (availability per record, missingness, and whether converted per-robot points reconcile with the
  alliance breakdown) need TBA match payloads. Those are unavailable here (no TBA key, no project database), so every
  data-level result is reported as `unverified`, never assumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

URL = "https://www.thebluealliance.com/swagger/api_v3.json"

# Meaning and classification of each per-robot field, against the E1b standard. Point values that a conversion would
# need come from the season's game manual. NO approved GameSpec exists in the project for any season, so no
# conversion is pre-registered or validated here.
ASSESSMENT = {
    (2024, "autoLineRobot"): {
        "meaning": "Whether the robot left its starting zone in auto (Yes/No)",
        "kind": "categorical", "component": "auto",
        "determines": "only the robot's auto-leave points, a sub-component of auto (autoLeavePoints). Auto note points are alliance-level only",
        "classification": "partial"},
    (2024, "endGameRobot"): {
        "meaning": "The robot's end state: None, Parked, CenterStage, StageLeft or StageRight",
        "kind": "categorical", "component": "endgame",
        "determines": "park and on-stage points per robot. Harmony and spotlight bonuses depend on other robots and the microphones (alliance-level), and trap points are recorded per stage, not per robot (trapCenterStage etc.)",
        "classification": "partial"},
    (2025, "autoLineRobot"): {
        "meaning": "Whether the robot left its starting line in auto (Yes/No)",
        "kind": "categorical", "component": "auto",
        "determines": "only the robot's auto-mobility points (autoMobilityPoints). Auto coral points are alliance-level only",
        "classification": "partial"},
    (2025, "endGameRobot"): {
        "meaning": "The robot's barge state: None, Parked, ShallowCage or DeepCage",
        "kind": "categorical", "component": "endgame",
        "determines": "plausibly the robot's entire barge points. The project's 2025 endgame component is endGameBargePoints (ml/features/score_components.py), so a fixed per-state point table would make the per-robot points sum to it exactly",
        "classification": "unverified",
        "why_unverified": "The strongest candidate to qualify for the whole 2025 endgame component. It needs: (a) the point table pre-registered under an approved 2025 GameSpec (none exists); (b) confirmation that no alliance-level term enters endGameBargePoints; (c) the parity check on every stored alliance row. None of these is possible here"},
    (2026, "autoTowerRobot"): {
        "meaning": "The robot's tower level reached in auto: None, Level1, Level2 or Level3",
        "kind": "categorical", "component": "auto",
        "determines": "at most the robot's auto tower points. 2026 auto points also include fuel scored (hubScore), which is alliance-level, so this cannot be the whole auto component",
        "classification": "partial",
        "note": "Whether the level fully determines the robot's auto tower points is itself unverified: no approved 2026 GameSpec, and no payloads to check against autoTowerPoints"},
    (2026, "endGameTowerRobot"): {
        "meaning": "The robot's tower level at the end of the match: None, Level1, Level2 or Level3",
        "kind": "categorical", "component": "endgame",
        "determines": "at most the robot's endgame tower points. The project's 2026 endgame component is hubScore.endgamePoints + endGameTowerPoints (ml/features/score_components.py); the fuel part is alliance-level, so this cannot be the whole endgame component",
        "classification": "partial",
        "note": "Whether it exactly determines the tower sub-component is unverified, for the same reasons as autoTowerRobot"},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    folder = args.cache / "tba_schema"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "api_v3.json"
    if not path.exists():
        body = httpx.get(URL, headers={"User-Agent": "stratai-research-benchmark"}, timeout=60.0).content
        path.write_bytes(body)
        (folder / "manifest.json").write_text(json.dumps({"url": URL, "fetched_at": datetime.now(timezone.utc).isoformat(),
                                                          "sha256": hashlib.sha256(body).hexdigest(),
                                                          "bytes": len(body)}, indent=1))
    schema = json.loads(path.read_bytes())["components"]["schemas"]
    manifest = json.loads((folder / "manifest.json").read_text())
    fields = []
    for season in (2024, 2025, 2026):
        props = schema[f"Match_Score_Breakdown_{season}_Alliance"]["properties"]
        for name, spec in props.items():
            match = re.fullmatch(r"([A-Za-z]+Robot)(\d)", name)
            if not match:
                continue
            ref = spec.get("$ref", "").split("/")[-1]
            enum = schema.get(ref, {}).get("enum", spec.get("enum"))
            assessment = ASSESSMENT[(season, match.group(1))]
            fields.append({
                "season": season, "field": name, "source": f"TBA API v3 schema {ref or 'inline'}",
                "data_type": schema.get(ref, {}).get("type", spec.get("type")), "allowed_values": enum,
                **assessment,
                "numerical_points": False,
                "directly_measures_complete_contribution": False,
                "exact_conversion_possible": "unverified (no approved GameSpec; no payloads to check)",
                "reconciles_with_alliance_breakdown": "unverified (no TBA match payloads available here)",
                "availability": "unverified (no TBA match payloads available here)"})
    qualifying = [f for f in fields if f["classification"] == "qualifies"]
    out = {"schema_source": manifest, "fields": fields,
           "counts": {c: sum(1 for f in fields if f["classification"] == c)
                      for c in ("qualifies", "partial", "does_not_qualify", "unverified")},
           "conclusion": ("No TBA per-robot field for 2024-2026 currently qualifies as individual numerical ground truth. "
                          "Every one is categorical. Most can determine only a sub-component. The 2025 endGameRobot fields "
                          "are the one candidate for a whole component (2025 endgame), and remain unverified until an "
                          "approved 2025 GameSpec, a pre-registered conversion, and a parity check on stored payloads "
                          "exist.") if not qualifying else "see fields"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "field_audit.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
