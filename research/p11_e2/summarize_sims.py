"""P11A E2 research: markdown tables from the simulation outputs (SIMULATION OUTPUT; synthetic truths).

    python -I research/p11_e2/summarize_sims.py --results research/p11_e2/results
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RATIOS = (0.5, 1.0, 2.0, 3.0)
SCENARIOS = ("indep_individual", "indep_population", "current_event_joint", "current_event_plugin")


def merge(parts: list[dict]) -> dict:
    """Join the cap-split tasks of one sigma/tau: their cells are disjoint, and bins are merged count-weighted."""
    out = {"simulations": sum(p["simulations"] for p in parts), "partial": any(p["partial"] for p in parts),
           "seconds": round(sum(p["seconds"] for p in parts), 1), "cells": {}, "identifiability_bins": {},
           "split": [p.get("caps") for p in parts]}
    for p in parts:
        out["cells"].update(p["cells"])
    keys = {k for p in parts for k in p["identifiability_bins"]}
    for k in keys:
        bs = [p["identifiability_bins"][k] for p in parts if k in p["identifiability_bins"]]
        n = sum(b["n"] for b in bs)
        out["identifiability_bins"][k] = {
            "n": n, "cov80": sum(b["cov80"] * b["n"] for b in bs) / n,
            "rmse": (sum(b["rmse"] ** 2 * b["n"] for b in bs) / n) ** 0.5,
            "width80": sum(b["width80"] * b["n"] for b in bs) / n, "bias": sum(b["bias"] * b["n"] for b in bs) / n}
    out["identifiability_bins"] = dict(sorted(out["identifiability_bins"].items()))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args(argv)
    sims = {}
    for r in RATIOS:
        whole = args.results / f"sim_sigma_over_tau_{r}.json"
        splits = ([args.results / f"sim_sigma_over_tau_{r}_caps_{c}.json" for c in ("low", "high")],
                  [args.results / f"sim_sigma_over_tau_{r}_caps_{c}.json" for c in ("low", "cap9", "nocap")])
        if whole.exists():
            sims[r] = json.loads(whole.read_text())
        else:
            for parts in splits:
                if all(p.exists() for p in parts):
                    sims[r] = merge([json.loads(p.read_text()) for p in parts])
                    break
    f = lambda x, d=3: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
    lines = ["# Simulation tables (SIMULATION OUTPUT: synthetic truths on real schedules)\n"]
    lines.append("| σ/τ | Simulations | Partial | Seconds |\n|---|---|---|---|")
    for r, s in sims.items():
        lines.append(f"| {r} | {s['simulations']} | {s['partial']} | {s['seconds']} |")

    lines.append("\n## Per-robot coverage by prior scenario (all cells pooled within σ/τ; nominal 50/80/95)\n")
    lines.append("| σ/τ | Scenario | Robots | Cov50 | Cov80 | Cov95 | Width80 | Bias | RMSE | Alliance cov80 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r, s in sims.items():
        for name in SCENARIOS:
            agg = defaultdict(float)
            for cell in s["cells"].values():
                if name in cell:
                    c, n = cell[name], cell[name]["robots"]
                    agg["robots"] += n
                    for k in ("cov0.5", "cov0.8", "cov0.95", "width80", "bias", "alliance_cov80"):
                        agg[k] += c[k] * n
                    agg["sq"] += c["rmse"] ** 2 * n
            n = agg["robots"]
            if n:
                lines.append(f"| {r} | {name} | {int(n)} | {f(agg['cov0.5'] / n)} | {f(agg['cov0.8'] / n)} | "
                             f"{f(agg['cov0.95'] / n)} | {f(agg['width80'] / n, 2)} | {f(agg['bias'] / n, 2)} | "
                             f"{f((agg['sq'] / n) ** 0.5, 2)} | {f(agg['alliance_cov80'] / n)} |")

    lines.append("\n## Joint vs plug-in by matches-per-team cap (80% per-robot coverage; all noise and obs settings)\n")
    lines.append("| σ/τ | Cap | Joint cov80 | Plug-in cov80 | Joint width80 | Plug-in width80 |")
    lines.append("|---|---|---|---|---|---|")
    for r, s in sims.items():
        by_cap = defaultdict(lambda: defaultdict(float))
        for key, cell in s["cells"].items():
            cap = key.split("|")[0]
            for name in ("current_event_joint", "current_event_plugin"):
                if name in cell:
                    n = cell[name]["robots"]
                    by_cap[cap][f"{name}_n"] += n
                    by_cap[cap][f"{name}_cov"] += cell[name]["cov0.8"] * n
                    by_cap[cap][f"{name}_w"] += cell[name]["width80"] * n
        for cap, a in by_cap.items():
            j, p = "current_event_joint", "current_event_plugin"
            lines.append(f"| {r} | {cap} | {f(a[j + '_cov'] / a[j + '_n'])} | {f(a[p + '_cov'] / a[p + '_n'])} | "
                         f"{f(a[j + '_w'] / a[j + '_n'], 2)} | {f(a[p + '_w'] / a[p + '_n'], 2)} |")

    lines.append("\n## Noise robustness (joint model, 80% per-robot and alliance coverage)\n")
    lines.append("| σ/τ | Noise | Unequal obs | Robot cov80 | Alliance cov80 |")
    lines.append("|---|---|---|---|---|")
    for r, s in sims.items():
        agg = defaultdict(lambda: defaultdict(float))
        for key, cell in s["cells"].items():
            _, unequal, noise = key.split("|")
            c = cell.get("current_event_joint")
            if c:
                k = (noise.split("=")[1], unequal.split("=")[1])
                agg[k]["n"] += c["robots"]
                agg[k]["cov"] += c["cov0.8"] * c["robots"]
                agg[k]["acov"] += c["alliance_cov80"] * c["robots"]
        for (noise, unequal), a in sorted(agg.items()):
            lines.append(f"| {r} | {noise} | {unequal} | {f(a['cov'] / a['n'])} | {f(a['acov'] / a['n'])} |")

    lines.append("\n## Ignoring covariance (joint model; full vs diagonal)\n")
    lines.append("| σ/τ | Cap | Alliance cov80 full | diag | Width ratio diag/full | Pair-diff cov80 full | diag | "
                 "Class changed | Wrong rate full | diag | Decided full | diag |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r, s in sims.items():
        by_cap = defaultdict(lambda: defaultdict(list))
        for key, cell in s["cells"].items():
            if "covariance" in cell:
                for k, v in cell["covariance"].items():
                    by_cap[key.split("|")[0]][k].append(v)
        for cap, a in by_cap.items():
            m = {k: sum(v) / len(v) for k, v in a.items()}
            lines.append(f"| {r} | {cap} | {f(m['alliance_full_cov80'])} | {f(m['alliance_diag_cov80'])} | "
                         f"{f(m['alliance_width_ratio_diag_over_full'])} | {f(m['pair_full_cov80'])} | "
                         f"{f(m['pair_diag_cov80'])} | {f(m['pair_class_changed'])} | {f(m['pair_full_wrong_rate'])} | "
                         f"{f(m['pair_diag_wrong_rate'])} | {f(m['pair_full_decided_share'])} | "
                         f"{f(m['pair_diag_decided_share'])} |")

    lines.append("\n## Identifiability bins (per-robot, 80% coverage and RMSE; τ = 10)\n")
    lines.append("| σ/τ | Bin | n | Cov80 | RMSE | Width80 |")
    lines.append("|---|---|---|---|---|---|")
    for r, s in sims.items():
        for k, b in s["identifiability_bins"].items():
            lines.append(f"| {r} | {k} | {b['n']} | {f(b['cov80'])} | {f(b['rmse'], 2)} | {f(b['width80'], 2)} |")
    (args.results / "sim_tables.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {args.results / 'sim_tables.md'} ({len(sims)} sigma/tau tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
