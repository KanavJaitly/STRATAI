"""Phase 4 Milestone 11's generalization test on real data: train on 2024+2025,
evaluate on held-out 2026 (decision D7), and require "held-out-season metrics
above baseline and above chance" (docs/P4Milestones.md, M11).

Requires the historical-data readiness gate to be COMPLETE (Statbotics EPA
synced). Every evaluated number comes from the unmodified M3 harness, the M4
baselines and the M5/M6 models; this script adds only the comparisons. It
does not change any model, feature, split or metric, and a failed check is a
stop-and-escalate result (decision D9), not a prompt to iterate.

The comparisons, all strict ("above"):
- win probability (M6 model vs M4 EpaWinProbBaseline, on the same EPA-complete
  held-out rows the baseline can score): log-loss below both the baseline's
  and chance (ln 2); Brier below both the baseline's and chance (0.25).
- ranking (M5 model vs M4 RawEpaRankingBaseline, against real 2026 final
  ranks): Spearman above both the baseline's and chance (0).
- the M11 feature resolves in the unseen season: average_auto_points is
  present for some held-out team appearance.

Usage: python -m scripts.run_m11_generalization
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

from ml.backtest.harness import FoldMetrics

CHANCE_LOG_LOSS = math.log(2)
CHANCE_BRIER = 0.25
CHANCE_SPEARMAN = 0.0
TRAIN_SEASONS = (2024, 2025)
HELD_OUT_SEASON = 2026


@dataclass(frozen=True)
class Check:
    name: str
    value: float | None
    bars: dict[str, float | None]
    lower_is_better: bool

    @property
    def passed(self) -> bool:
        if self.value is None or any(bar is None for bar in self.bars.values()):
            return False  # an undefined metric is never evidence of generalization
        if self.lower_is_better:
            return all(self.value < bar for bar in self.bars.values())
        return all(self.value > bar for bar in self.bars.values())

    def line(self) -> str:
        bars = ", ".join(f"{k} {v:.4f}" if v is not None else f"{k} undefined" for k, v in self.bars.items())
        shown = f"{self.value:.4f}" if self.value is not None else "undefined"
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.name}: {shown} ({'<' if self.lower_is_better else '>'} {bars})"


def generalization_checks(
    *, model_win_prob: FoldMetrics, baseline_win_prob: FoldMetrics,
    model_ranking: FoldMetrics, baseline_ranking: FoldMetrics, held_out_auto_points_present: int,
) -> list[Check]:
    return [
        Check("held-out win-prob log-loss", model_win_prob.log_loss,
              {"baseline": baseline_win_prob.log_loss, "chance": CHANCE_LOG_LOSS}, lower_is_better=True),
        Check("held-out win-prob Brier", model_win_prob.brier_score,
              {"baseline": baseline_win_prob.brier_score, "chance": CHANCE_BRIER}, lower_is_better=True),
        Check("held-out ranking Spearman", model_ranking.spearman,
              {"baseline": baseline_ranking.spearman, "chance": CHANCE_SPEARMAN}, lower_is_better=False),
        Check("average_auto_points resolves in the held-out season", float(held_out_auto_points_present),
              {"none present": 0.0}, lower_is_better=False),
    ]


def main() -> int:
    from data.config import Settings
    from data.rankings import read_final_ranks_for_season
    from database.connection import Database, DatabaseConfig
    from automation.data_readiness import COMPLETE, assess_readiness
    from ml.backtest.harness import hold_out_season_split, run_ranking_backtest, run_win_prob_backtest
    from ml.dataset.builder import build_training_frame
    from ml.models.baselines import EpaWinProbBaseline, RawEpaRankingBaseline
    from ml.models.ranking_xgb import RankingXGBModel
    from ml.models.win_prob import WinProbXGBModel
    from scripts.run_m4_baseline_backtest import _split_epa_complete

    database = Database(DatabaseConfig(Settings().database_url))
    readiness = assess_readiness(database)
    if readiness.status != COMPLETE:
        print(f"REFUSED: historical data readiness is {readiness.status}: {readiness.reasons}")
        return 2

    frame = build_training_frame(database, [*TRAIN_SEASONS, HELD_OUT_SEASON])
    fold = hold_out_season_split(frame.rows, held_out_season=HELD_OUT_SEASON)
    epa_fold, train_excluded, test_excluded = _split_epa_complete(fold)
    final_ranks = read_final_ranks_for_season(database, HELD_OUT_SEASON)
    present = sum(team.average_auto_points_present for row in fold.test_rows
                  for team in (*row.red_teams, *row.blue_teams))
    print(f"rows: {len(fold.train_rows)} train / {len(fold.test_rows)} held-out; "
          f"EPA-complete {len(epa_fold.train_rows)} / {len(epa_fold.test_rows)} "
          f"(excluded {train_excluded} / {test_excluded}); frame exclusions {frame.manifest.excluded_by_reason}")

    checks = generalization_checks(
        model_win_prob=run_win_prob_backtest(WinProbXGBModel, [epa_fold]).aggregate,
        baseline_win_prob=run_win_prob_backtest(EpaWinProbBaseline, [epa_fold]).aggregate,
        model_ranking=run_ranking_backtest(RankingXGBModel, [fold], final_ranks).aggregate,
        baseline_ranking=run_ranking_backtest(RawEpaRankingBaseline, [fold], final_ranks).aggregate,
        held_out_auto_points_present=present,
    )
    for check in checks:
        print(check.line())
    passed = all(check.passed for check in checks)
    print("M11 generalization: " + ("PASS" if passed else "FAIL — stop and escalate (decision D9)"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
