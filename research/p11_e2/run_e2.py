"""P11A E2 research: run every model of PROTOCOL.json on one season's population, at each event's selection moment.

    python -I research/p11_e2/run_e2.py --season 2024 --population research/p11_e2/cache/population \
        --out research/p11_e2/results [--budget-minutes 40]

Writes <out>/e2_records_<season>.json:
- one record per playoff alliance: actual component points and each model's mean, predictive SD and estimation SD;
- one record per playoff match: the expected red−blue differences;
- per-event hyperparameters.

Leakage rule (PROTOCOL.json information_set). A fit uses only this event's qualification rows, all of which precede
the selection moment. Cross-event inputs (M2, AS1_indep) use only same-season events whose end_date is strictly
before this event's start_date. Each pass-1 fit uses only its own event's qualification rows.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import ROBOTS, design, plain_opr, posterior, reml  # noqa: E402

COMPONENTS = ("auto", "teleop", "endgame", "no_foul")
MIN_DRIFT_PAIRS = 30


def fit_event(event: dict) -> dict:
    """Pass 1: everything that needs only this event's qualification rows."""
    teams = event["teams"]
    rows = [r["teams"] for r in event["quals"]]
    A = design(rows, teams)
    out = {"teams": teams, "A": A, "comp": {}}
    fouls = np.array([r["fouls"] for r in event["quals"]], dtype=float)
    out["fouls"] = (float(fouls.mean()), float(fouls.var(ddof=1)))
    for c in COMPONENTS:
        y = np.array([r[c] for r in event["quals"]], dtype=float)
        s2, t2 = reml(A, y)
        joint = posterior(A, y, teams, s2, t2)
        plug = posterior(A, y, teams, s2, t2, plugin=True)
        x_opr, G, s2_opr = plain_opr(A, y)
        team_avg = {t: float(y[A[:, i] > 0].mean()) for i, t in enumerate(teams)}
        m1_qual = np.array([np.mean([team_avg[t] for t in r]) for r in rows])
        out["comp"][c] = {"y": y, "sigma2": s2, "tau2": t2, "joint": joint, "plugin": plug, "opr": (x_opr, G, s2_opr),
                          "team_avg": team_avg, "m1_sd": float(np.std(y - m1_qual, ddof=1)),
                          "event_mean": float(y.mean()), "event_sd": float(y.std(ddof=1))}
    return out


def drift_variance(history: list[dict], component: str, before: str) -> tuple[float | None, int]:
    """Method-of-moments drift variance between a team's consecutive events, using only pairs whose later event
    ended strictly before `before`. Returns (tau_drift^2 or None, number of pairs)."""
    by_team: dict[int, list[dict]] = {}
    for h in history:
        if h["end_date"] < before:
            by_team.setdefault(h["team"], []).append(h)
    sq, var = [], []
    for entries in by_team.values():
        entries.sort(key=lambda h: h["end_date"])
        for e1, e2 in zip(entries, entries[1:]):
            if e1["end_date"] < e2["start_date"]:
                sq.append((e2[component][0] - e1[component][0]) ** 2)
                var.append(e2[component][1] + e1[component][1])
    if len(sq) < MIN_DRIFT_PAIRS:
        return None, len(sq)
    return max(float(np.mean(sq) - np.mean(var)), 1e-6), len(sq)


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
    population = json.loads((args.population / f"population_{args.season}.json").read_text())
    events = population["events"]

    fits, history, partial = {}, [], False
    for event in events:  # pass 1
        if time.monotonic() > deadline:
            partial = True
            break
        fit = fit_event(event)
        fits[event["key"]] = fit
        for i, t in enumerate(fit["teams"]):
            history.append({"team": t, "event": event["key"], "start_date": event["start_date"],
                            "end_date": event["end_date"],
                            **{c: (float(fit["comp"][c]["joint"].mean[i]), float(fit["comp"][c]["joint"].cov[i, i]))
                               for c in COMPONENTS}})

    alliances, pairs, hyper = [], [], []
    for event in events:  # pass 2
        if event["key"] not in fits:
            continue
        if time.monotonic() > deadline:
            partial = True
            break
        fit = fits[event["key"]]
        teams = fit["teams"]
        prior_hist = [h for h in history if h["end_date"] < event["start_date"]]
        latest: dict[int, dict] = {}
        for h in sorted(prior_hist, key=lambda h: h["end_date"]):
            latest[h["team"]] = h
        comp_out = {}
        for c in COMPONENTS:
            f = fit["comp"][c]
            tau_drift, n_pairs = drift_variance(history, c, event["start_date"])
            individual = ({t: (latest[t][c][0], latest[t][c][1] + tau_drift) for t in teams if t in latest}
                          if tau_drift is not None else {})
            indep = posterior(fit["A"], f["y"], teams, f["sigma2"], f["tau2"], individual=individual)
            m2_values = {t: (latest[t][c][0] if t in latest else f["event_mean"] / ROBOTS) for t in teams}
            m2_qual = np.array([sum(m2_values[t] for t in r["teams"]) for r in event["quals"]])
            comp_out[c] = {"indep": indep, "m2": m2_values, "m2_sd": float(np.std(f["y"] - m2_qual, ddof=1)),
                           "n_individual": len(individual), "tau_drift2": tau_drift, "drift_pairs": n_pairs}
            hyper.append({"event": event["key"], "component": c, "sigma2": f["sigma2"], "tau2": f["tau2"],
                          "tau_drift2": tau_drift, "drift_pairs": n_pairs, "n_individual_priors": len(individual),
                          "n_teams": len(teams), "n_qual_rows": len(f["y"]),
                          "robots_with_prior_event": sum(1 for t in teams if t in latest)})

        def predictions(alliance: list[int]) -> dict:
            out = {}
            for c in COMPONENTS:
                f, o = fit["comp"][c], comp_out[c]
                a = f["joint"].vector(alliance)
                jm, jv, jd = f["joint"].predict(alliance)
                pm, pv, _ = f["plugin"].predict(alliance)
                im, iv, _ = o["indep"].predict(alliance)
                x_opr, G, s2_opr = f["opr"]
                out[c] = {
                    "M0_event_mean": [f["event_mean"], f["event_sd"], None],
                    "M1_team_average": [float(np.mean([f["team_avg"][t] for t in alliance])), f["m1_sd"], None],
                    "M2_prior_event": [float(sum(o["m2"][t] for t in alliance)), o["m2_sd"], None],
                    "M3_plain_opr": [float(a @ x_opr), float(np.sqrt(s2_opr * (1 + a @ G @ a))),
                                     float(np.sqrt(s2_opr * (a @ G @ a)))],
                    "AS1_joint": [jm, float(np.sqrt(jv + f["sigma2"])), float(np.sqrt(jv))],
                    "AS1_joint_diag": [jm, float(np.sqrt(jd + f["sigma2"])), float(np.sqrt(jd))],
                    "AS1_indep_prior": [im, float(np.sqrt(iv + f["sigma2"])), float(np.sqrt(iv))],
                    "AS1_plugin": [pm, float(np.sqrt(pv + f["sigma2"])), float(np.sqrt(pv))],
                }
            fm, fv = fit["fouls"]
            out["total"] = {m: [v[0] + fm, float(np.sqrt(v[1] ** 2 + fv)), v[2]] for m, v in out["no_foul"].items()}
            return out

        by_match: dict[str, dict] = {}
        for row in event["elims"]:
            record = {"season": args.season, "event": event["key"], "event_type": event["type"], "week": event["week"],
                      "match": row["match"], "color": row["color"], "comp_level": row["comp_level"],
                      "time": row["time"], "teams": row["teams"],
                      "actual": {**{c: row[c] for c in COMPONENTS}, "total": row["score"]},
                      "pred": predictions(row["teams"]),
                      "robots_with_prior_event": sum(1 for t in row["teams"] if t in latest)}
            alliances.append(record)
            by_match.setdefault(row["match"], {})[row["color"]] = row
        for match, sides in by_match.items():
            if set(sides) != {"red", "blue"}:
                continue
            red, blue = sides["red"]["teams"], sides["blue"]["teams"]
            entry = {"season": args.season, "event": event["key"], "match": match,
                     "comp_level": sides["red"]["comp_level"], "red": red, "blue": blue,
                     "actual_diff": {c: sides["red"][c] - sides["blue"][c] for c in COMPONENTS}, "diff": {}}
            for c in COMPONENTS:
                f, o = fit["comp"][c], comp_out[c]
                for name, post in (("AS1_joint", f["joint"]), ("AS1_indep_prior", o["indep"]),
                                   ("AS1_plugin", f["plugin"])):
                    d = post.vector(red) - post.vector(blue)
                    entry["diff"].setdefault(c, {})[name] = [float(d @ post.mean), float(np.sqrt(d @ post.cov @ d))]
                f_joint = f["joint"]
                d = f_joint.vector(red) - f_joint.vector(blue)
                entry["diff"][c]["AS1_joint_diag"] = [float(d @ f_joint.mean),
                                                      float(np.sqrt((d * d) @ np.diag(f_joint.cov)))]
                x_opr, G, s2_opr = f["opr"]
                entry["diff"][c]["M3_plain_opr"] = [float(d @ x_opr), float(np.sqrt(s2_opr * (d @ G @ d)))]
                entry["diff"][c]["M1_team_average"] = [
                    float(np.mean([f["team_avg"][t] for t in red]) - np.mean([f["team_avg"][t] for t in blue])), None]
                entry["diff"][c]["M2_prior_event"] = [
                    float(sum(o["m2"][t] for t in red) - sum(o["m2"][t] for t in blue)), None]
            pairs.append(entry)

    args.out.mkdir(parents=True, exist_ok=True)
    meta = {"season": args.season, "partial": partial, "events_fitted": len(fits), "alliance_records": len(alliances),
            "pair_records": len(pairs), "seconds": round(time.monotonic() - started, 1)}
    (args.out / f"e2_records_{args.season}.json").write_text(json.dumps(
        {"meta": meta, "alliances": alliances, "pairs": pairs, "hyper": hyper}))
    print(json.dumps(meta))
    return 1 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
