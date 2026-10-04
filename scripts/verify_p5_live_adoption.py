"""Verify the production API after the P5-D3 adoption of the live EPA source (read-only on the serving database).

    python -m scripts.verify_p5_live_adoption --frame FRAME_DIR [--sample 300]

Run with the production environment: `EPA_SOURCE=p5_live_statbotics`, `LIVE_EPA_LOG_DIR`,
`STATBOTICS_SNAPSHOT_DIR`, `STRATAI_EPA_CHAIN`, `LIVE_EPA_A1A2_POLICY=d18_skip`,
`LIVE_EPA_CONCLUDED_SEASONS=[2024,2025,2026]`, and the D18 model pins. The record is
`.agent/production/p5_live_adoption_check.json`, write-once.

**Checks:**
1. **Source.** The served EPA source is `p5_live_statbotics`, with the P5-D3 adoption status (historical acceptance
   passed; prospective validation pending) and `evaluated_configuration` false. The log's root is the D18 snapshot.
2. **History unchanged.**
   - For seeded held-out 2026 qualification matches (plus every 2026iscmp qualification match), the features the
     API builds at match time equal the D18 frame's, and the served value equals the frozen model on the frame
     row.
   - No live flag is attached: historical as_of are served by the root in frozen-D18 mode.
3. **"As of now".** An event ranking is served. A request D18 refused because a team's latest prior event is an
   unprocessed Israeli event (2026dal) is now answered, with those teams labelled `fallback_stratai` and the
   response flagged `live_refresh_not_yet_validated`.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECORD = Path(".agent/production/p5_live_adoption_check.json")
SEED = 20261004
FALLBACK_PROBE_EVENT = "2026dal"


def main(argv: list[str] | None = None) -> int:
    from fastapi.testclient import TestClient

    from api import create_app
    from api.routes.predictions import display_probability
    from data.config import Settings
    from ml.backtest.harness import _match_features
    from ml.features.assembler import build_match_feature_row
    from ml.features.scale import ScaleLookup
    from ml.ratings.live_epa import LIVE_REFRESH_NOT_YET_VALIDATED
    from scripts.phase5_records import provenance
    from scripts.run_phase4_stratai import load_frame_rows

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=300)
    args = parser.parse_args(argv)
    if RECORD.exists():
        raise SystemExit(f"{RECORD} exists: verification records are write-once")
    settings = Settings()
    if settings.epa_source != "p5_live_statbotics":
        raise SystemExit("run with the production environment: EPA_SOURCE=p5_live_statbotics")
    prov = provenance()
    started = datetime.now(timezone.utc)
    app = create_app(settings)
    checks: dict[str, Any] = {}
    with TestClient(app) as client:
        from api.dependencies import get_epa_source

        served = get_epa_source(type("R", (), {"app": app})())
        provider, win = served.provider, app.state.win_prob_model
        checks["1_source"] = {"epa_source": served.epa_source, "evaluated_configuration": served.evaluated_configuration,
                              "adoption": served.adoption, "root_snapshot": provider.retrieval.view(started).snapshot_id
                              if hasattr(provider.retrieval, "view") else None,
                              "historical_frozen_d18_until": provider.provenance_info.get("historical_frozen_d18_until")}
        checks["1_source"]["ok"] = (served.epa_source == "p5_live_statbotics" and served.adoption is not None
                                    and served.adoption["decision"] == "P5-D3" and not served.evaluated_configuration)

        rows = [r for r in load_frame_rows(args.frame) if r.season == 2026 and r.comp_level == "qualification"]
        rng = random.Random(SEED)
        sample = rng.sample([r for r in rows if r.event_key != "2026iscmp"], args.sample)
        sample += [r for r in rows if r.event_key == "2026iscmp"]
        scales = ScaleLookup(app.state.database)
        feature_mismatch, value_mismatch, flagged = [], [], []
        for row in sample:
            built = build_match_feature_row(app.state.database, row.match_key, row.scheduled_time,
                                            epa_provider=provider, scale_lookup=scales)
            expected = sorted((t.model_dump(exclude={"epa_source_state"}) for t in (*row.red_teams, *row.blue_teams)),
                              key=lambda t: t["team_number"])
            actual = sorted((t.model_dump(exclude={"epa_source_state"}) for t in (*built.red_teams, *built.blue_teams)),
                            key=lambda t: t["team_number"])
            if expected != actual:
                feature_mismatch.append(row.match_key)
            body = client.get(f"/predictions/matches/{row.match_key}/win-probability").json()
            shown = body.get("red_win_probability")
            shown = body.get("unvalidated_red_win_probability") if shown is None else shown
            if shown != display_probability(win.model.predict_win_prob(_match_features(row))):
                value_mismatch.append(row.match_key)
            if body["epa"]["validation_flags"]:
                flagged.append(row.match_key)
        checks["2_history_unchanged"] = {"matches": len(sample), "feature_mismatches": len(feature_mismatch),
                                         "value_mismatches": len(value_mismatch), "flagged": len(flagged),
                                         "examples": (feature_mismatch + value_mismatch + flagged)[:10]}
        checks["2_history_unchanged"]["ok"] = not (feature_mismatch or value_mismatch or flagged)

        ranking = client.get(f"/predictions/events/{FALLBACK_PROBE_EVENT}/ranking")
        body = ranking.json()
        sources = sorted({str(e.get("epa_value_source")) for e in body.get("rankings", [])})
        checks["3_as_of_now"] = {"event": FALLBACK_PROBE_EVENT, "status": ranking.status_code,
                                 "epa_value_sources": sources,
                                 "validation_flags": body.get("epa", {}).get("validation_flags")}
        checks["3_as_of_now"]["ok"] = (ranking.status_code == 200 and "stratai_fallback" in sources
                                       and LIVE_REFRESH_NOT_YET_VALIDATED in body["epa"]["validation_flags"])
    result = {"decision": "P5-D3", "checked_at": started.isoformat(),
              "minutes": round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1),
              "checks": checks, "passed": all(c["ok"] for c in checks.values()), "provenance": prov}
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "adoption"} for k, v in checks.items()},
                     indent=1, default=str))
    print("P5-D3 production adoption:", "VERIFIED" if result["passed"] else "FAILED", f"-> {RECORD}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
