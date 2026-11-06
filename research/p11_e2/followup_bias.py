"""P11A E2 follow-up F1c (FOLLOWUP_PROTOCOL.json): the within-qualification trend refit, one season per task.

    python -I research/p11_e2/followup_bias.py --season 2024 --population research/p11_e2/cache/population \
        --out research/p11_e2/results [--budget-minutes 40]

For every event and component, AS1_joint (same REML method as run_e2.py) is refitted on the first two-thirds of the
event's qualification rows (by time). That fit then predicts:
- the last third of qualification rows ("late_qual", a held-out within-qualification check);
- the event's playoff rows ("playoff_from_early").

Both are compared with the original full-qualification fit in analyze_followup.py. Only qualification rows that
precede the predicted rows are used, so nothing leaks. MODEL PREDICTIONS against OBSERVED results.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import design, posterior, reml  # noqa: E402

COMPONENTS = ("auto", "teleop", "endgame", "no_foul")
EARLY_SHARE = 2 / 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True, choices=(2024, 2025, 2026))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget-minutes", type=float, default=40.0)
    args = parser.parse_args(argv)
    if not 0 < args.budget_minutes <= 45:
        parser.error("--budget-minutes must be in (0, 45]")
    started = time.monotonic()
    deadline = started + args.budget_minutes * 60
    events = json.loads((args.population / f"population_{args.season}.json").read_text())["events"]
    rows_out, partial, skipped = [], False, 0
    for event in events:
        if time.monotonic() > deadline:
            partial = True
            break
        quals = sorted(event["quals"], key=lambda r: (r["time"], r["match"], r["color"]))
        cut = int(round(len(quals) * EARLY_SHARE))
        # Keep both alliances of a match on the same side of the cut.
        while 0 < cut < len(quals) and quals[cut]["match"] == quals[cut - 1]["match"]:
            cut += 1
        early, late = quals[:cut], quals[cut:]
        if len(early) < 12 or not late:
            skipped += 1
            continue
        teams = event["teams"]
        A = design([r["teams"] for r in early], teams)
        for c in COMPONENTS:
            y = np.array([r[c] for r in early], dtype=float)
            s2, t2 = reml(A, y)
            post = posterior(A, y, teams, s2, t2)
            for kind, rows in (("late_qual", late), ("playoff_from_early", event["elims"])):
                for r in rows:
                    m, v, _ = post.predict(r["teams"])
                    rows_out.append({"season": args.season, "event": event["key"], "kind": kind, "component": c,
                                     "match": r["match"], "color": r["color"], "comp_level": r["comp_level"],
                                     "time": r["time"], "actual": r[c], "pred": m, "sd": float(np.sqrt(v + s2)),
                                     "est_sd": float(np.sqrt(v))})
    args.out.mkdir(parents=True, exist_ok=True)
    meta = {"season": args.season, "partial": partial, "events_skipped_too_small": skipped, "rows": len(rows_out),
            "seconds": round(time.monotonic() - started, 1)}
    (args.out / f"followup_f1c_{args.season}.json").write_text(json.dumps({"meta": meta, "rows": rows_out}))
    print(json.dumps(meta))
    return 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
