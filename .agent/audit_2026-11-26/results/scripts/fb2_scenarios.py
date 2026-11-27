"""Live alliance selection scenarios through P11-FB2 (read-only, stratai_test; audit 2026-11-26).

For a sample of real events, at the selection moment:
  * first-pick lists for the captains of alliances 1, 4 and 8 (each before any pick);
  * for each of captain 1's top-6 first-pick candidates P: the second-pick ranking for {captain 1, P} (every other
    team still available, as a counterfactual draft state), to see whether the second pick is conditional on P;
  * how often gap filling reorders the list versus ranking by individual (reliability-adjusted) contribution alone.
"""
import json
import os
import statistics
import sys
from urllib.parse import urlparse

sys.path.insert(0, "C:/Dev/StratAI")
os.chdir("C:/Dev/StratAI")
from data.config import Settings  # noqa: E402

u = urlparse(str(Settings().database_url))
os.environ["DATABASE_URL"] = u._replace(path="/stratai_test").geturl()

from scipy.stats import kendalltau  # noqa: E402

from data.alliances import read_event_alliances  # noqa: E402
from database.connection import Database, DatabaseConfig  # noqa: E402
from ml.playoffs.service import event_selection_moment  # noqa: E402
from workspaces import draft_fb2 as fb2  # noqa: E402
from workspaces import draft_log as dl  # noqa: E402
from workspaces import draft_recommendations as rec  # noqa: E402
from workspaces.live_draft import build_setup  # noqa: E402

db = Database(DatabaseConfig(os.environ["DATABASE_URL"]))
EVENTS = ["2024txbel", "2025miket", "2026onwat", "2024njfla", "2025casd", "2026mibig"]
report = {}
for event_key in EVENTS:
    moment = event_selection_moment(db, event_key)
    est = fb2.estimate_event(fb2.load_rows(db, event_key, moment), switch_passed=True)
    try:
        setup = build_setup(db, event_key, manual_rules=None, actor="audit")
    except Exception as exc:  # rules not approved etc.
        report[event_key] = {"skipped": f"{type(exc).__name__}: {exc}"}
        continue
    if isinstance(setup, tuple):
        setup = setup[0]
    entries = [dl.LogEntry("c", 1, dl.CONFIGURE, setup.to_json())]
    view0 = dl.replay(entries)
    inputs = fb2.TeamInputs({})
    captains = {}
    seq = 2
    # Name the captains of alliance 1 (as the rules project) so it is alliance 1's turn.
    expected, _ = view0.expected_captain()
    entries.append(dl.LogEntry(f"a{seq}", seq, dl.CAPTAIN, {"seed": 1, "team": expected})); seq += 1
    view = dl.replay(entries)
    cap1 = expected
    out = {"mode": est.mode, "teams_estimated": len(est.values), "benchmark": {k: round(v, 2) for k, v in est.benchmark.items()}}
    lists = fb2.rank_for_alliance(view, 1, cap1, est, inputs, rec._excluded(view, 1, cap1))
    first = [c.team_number for c in lists.ranked]
    # Individual-contribution order (no fit term), for the reorder rate.
    indiv = sorted((c for c in lists.projections if c.rank_score is not None and not c.reasons[0].startswith("Not")),
                   key=lambda c: (-sum(f.effective for f in c.fits), c.team_number))
    out["captain1"] = cap1
    out["first_pick_list"] = first
    out["first_pick_gaps"] = {k: round(v, 2) for k, v in lists.gaps.items()}
    out["first_pick_same_as_individual_order"] = first == [c.team_number for c in indiv][:len(first)]
    # Captains 4 and 8 (projected), first pick: lists differ from captain 1's?
    projected = view.projected_captains()
    for seed in (4, 8):
        cap = projected.get(seed)
        if cap is None:
            continue
        l2 = fb2.rank_for_alliance(view, seed, cap, est, inputs, rec._excluded(view, seed, cap))
        out[f"captain{seed}"] = {"team": cap, "list": [c.team_number for c in l2.ranked],
                                 "gaps": {k: round(v, 2) for k, v in l2.gaps.items()}}
    # Conditional second pick: for each of captain 1's top-6 candidates P.
    second = {}
    top6 = [c.team_number for c in lists.projections if c.rank_score is not None][:6]
    for p in top6:
        e2 = entries + [dl.LogEntry(f"a{seq}", seq, dl.PICK, {"seed": 1, "team": p})]
        v2 = dl.replay(e2)
        l3 = fb2.rank_for_alliance(v2, 1, cap1, est, inputs, rec._excluded(v2, 1, cap1))
        ranked = [c for c in l3.projections if c.rank_score is not None and not c.reasons[0].startswith("Not")]
        second[p] = {"top5": [c.team_number for c in ranked[:5]], "gaps": {k: round(v, 2) for k, v in l3.gaps.items()},
                     "order": [c.team_number for c in ranked]}
    tops = {tuple(v["top5"]) for v in second.values()}
    common = None
    for v in second.values():
        common = set(v["order"]) if common is None else common & set(v["order"])
    taus = []
    keys = list(second)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a = [t for t in second[keys[i]]["order"] if t in common]
            b = [t for t in second[keys[j]]["order"] if t in common]
            pos = {t: k for k, t in enumerate(b)}
            taus.append(kendalltau(list(range(len(a))), [pos[t] for t in a]).statistic)
    out["second_pick_by_first_pick"] = {str(k): {"top5": v["top5"], "gaps": v["gaps"]} for k, v in second.items()}
    out["second_pick_distinct_top5_lists"] = len(tops)
    out["second_pick_order_kendall_tau_mean"] = round(statistics.fmean(taus), 4) if taus else None
    out["second_pick_gap_nonzero_share"] = round(sum(any(g > 0 for g in v["gaps"].values()) for v in second.values())
                                                 / max(1, len(second)), 3)
    actual = {a.seed: a.picks for a in read_event_alliances(db, int(event_key[:4])).get(event_key, []) if a.seed}
    out["actual_alliance_1"] = actual.get(1)
    report[event_key] = out
print(json.dumps(report, indent=1, default=str))
json.dump(report, open(sys.argv[1], "w"), indent=1, default=str)
