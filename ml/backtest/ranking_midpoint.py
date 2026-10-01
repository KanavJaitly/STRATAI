"""M5 v2's primary ranking evaluation (decision D16 §1.5): a real in-season prediction.

For each held-out team-event, team i's retained qualification rows at event e
are taken in scheduled order (n_i of them). The decision snapshot is its k-th
row, with k = ceil(n_i / 2) for the primary evaluation. The team's features
in that row are what was known strictly before that match: its first k - 1
qualification matches at e, its D13 prior-event EPA, and the causal season
scale. No playoff or post-qualification snapshot can be selected, because
only qualification rows are considered.

The score is per event: Spearman(predicted rating, -final qualification rank)
over teams with both (at least 2), averaged over events. Top-k recall is the
secondary metric. Both use the same statistic and per-event averaging as
ml.backtest.harness.run_ranking_backtest; that accepted harness is not changed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ml.backtest.metrics import spearman_correlation, top_k_recall
from ml.dataset.builder import TrainingRow
from ml.features.assembler import TeamFeatures

QUALIFICATION = "qualification"
SnapshotRule = Callable[[int], int]  # n_i -> 1-based k

MIDPOINT: SnapshotRule = lambda n: math.ceil(n / 2)  # noqa: E731 - the primary rule (D16 §1.5)
FIRST: SnapshotRule = lambda n: 1  # noqa: E731 - secondary: pre-event information only
LAST: SnapshotRule = lambda n: n  # noqa: E731 - secondary: before the team's last qualification match


@dataclass(frozen=True)
class Snapshot:
    team: int
    event_key: str
    k: int
    n: int
    match_key: str
    features: TeamFeatures


def decision_snapshots(rows: Sequence[TrainingRow], rule: SnapshotRule) -> dict[str, dict[int, Snapshot]]:
    """event_key -> team -> the team's decision snapshot under ``rule``."""
    appearances: dict[tuple[str, int], list[tuple[TrainingRow, TeamFeatures]]] = defaultdict(list)
    for row in rows:
        if row.comp_level != QUALIFICATION:
            continue
        for tf in (*row.red_teams, *row.blue_teams):
            appearances[(row.event_key, tf.team_number)].append((row, tf))
    out: dict[str, dict[int, Snapshot]] = defaultdict(dict)
    for (event_key, team), items in appearances.items():
        items.sort(key=lambda it: (it[0].scheduled_time, it[0].match_key))
        n = len(items)
        k = rule(n)
        row, tf = items[k - 1]
        out[event_key][team] = Snapshot(team, event_key, k, n, row.match_key, tf)
    return dict(out)


@dataclass
class RankingEvaluation:
    spearman: float | None
    top_k_recall: float | None
    events_scored: int
    events_skipped: int
    teams_scored: int
    per_event: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def evaluate_ranking(predict: Callable[[TeamFeatures], float], snapshots: Mapping[str, Mapping[int, Snapshot]],
                     final_ranks: Mapping[str, Mapping[int, int]], *, top_k: int = 8) -> RankingEvaluation:
    rhos, recalls, per_event = [], [], {}
    scored = skipped = teams_scored = 0
    for event_key in sorted(snapshots):
        actual = final_ranks.get(event_key)
        teams = sorted(t for t in snapshots[event_key] if actual and t in actual)
        if len(teams) < 2:
            skipped += 1
            continue
        ratings = {t: predict(snapshots[event_key][t].features) for t in teams}
        rho = spearman_correlation([ratings[t] for t in teams], [-actual[t] for t in teams])
        recall = top_k_recall(sorted(teams, key=lambda t: ratings[t], reverse=True),
                              sorted(teams, key=lambda t: actual[t]), k=top_k)
        if rho is not None:
            rhos.append(rho)
        if recall is not None:
            recalls.append(recall)
        scored += 1
        teams_scored += len(teams)
        per_event[event_key] = {"teams": len(teams), "spearman": rho, "top_k_recall": recall}
    return RankingEvaluation(
        spearman=sum(rhos) / len(rhos) if rhos else None,
        top_k_recall=sum(recalls) / len(recalls) if recalls else None,
        events_scored=scored, events_skipped=skipped, teams_scored=teams_scored, per_event=per_event,
    )
