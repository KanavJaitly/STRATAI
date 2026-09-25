"""Run Phase 4 Milestone 4's two locked baselines through Milestone 3's
backtest harness on real synced season data, and print the results.

Phase 4 Milestone 4 (docs/P4Milestones.md). This script computes; it does
not conclude. It prints exactly what the harness reports and nothing else --
transcribing the printed numbers into RUNNING_NOTES.md as a dated, frozen
entry is a separate, deliberate human/assistant step, the same division
scripts/metrics_spot_check.py already draws between "compute and display"
and "a person judges it".

Requires a reachable database with the training and held-out seasons already
synced via `python -m data.orchestrator --season YEAR` (Statbotics EPA
included -- `--no-statbotics` alone is not sufficient for this script, since
both baselines are defined in terms of EPA). If Statbotics was down when the
data was synced, team_event_stats will be empty and this script refuses
loudly (via EpaWinProbBaseline.fit's own ValueError) rather than silently
reporting a result computed on no data.

Ranking evaluation additionally requires real final-event-ranking ground
truth, which this codebase does not yet ingest from anywhere (see
ml.backtest.harness's own module docstring for the full finding). Pass
--final-ranks-file pointing at a JSON file shaped
{"event_key": {"team_number": rank, ...}, ...} once such a source exists;
without it, this script explicitly skips the ranking baseline rather than
fabricating ground truth or silently omitting it without a trace.

Usage:

    python -m scripts.run_m4_baseline_backtest --train-season 2024 --train-season 2025 --held-out-season 2026
    python -m scripts.run_m4_baseline_backtest --train-season 2024 --held-out-season 2026 --final-ranks-file rankings.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data.config import Settings
from database.connection import Database, DatabaseConfig
from ml.backtest.harness import (
    Fold,
    hold_out_season_split,
    run_ranking_backtest,
    run_win_prob_backtest,
)
from ml.dataset.builder import TrainingRow, build_training_frame
from ml.models.baselines import EpaWinProbBaseline, RawEpaRankingBaseline


def _team_epa_complete(row: TrainingRow) -> bool:
    """Every team on both alliances has a present epa_total. Empty alliances
    (Milestone 1's documented frc0-placeholder case) count as incomplete --
    there is nothing to sum.

    Each alliance is checked for non-emptiness separately, not merely the
    concatenation of both -- concatenating first would let one completely
    empty alliance vanish from the check entirely as long as the other
    alliance's teams all have EPA, silently passing a row that
    _alliance_epa_sum (ml.models.baselines) would itself refuse.
    """
    if not row.red_teams or not row.blue_teams:
        return False
    return all(team.epa_total_present for team in (*row.red_teams, *row.blue_teams))


def _split_epa_complete(fold: Fold) -> tuple[Fold, int, int]:
    """A copy of fold with EPA-incomplete rows removed from both train and
    test, plus the excluded counts for each side -- reported, never silently
    dropped, per this module's own standing discipline (see ml.models.
    baselines' module docstring on why EPA is never imputed to 0).
    """
    train_eligible = [row for row in fold.train_rows if _team_epa_complete(row)]
    test_eligible = [row for row in fold.test_rows if _team_epa_complete(row)]
    eligible_fold = Fold(
        label=fold.label, train_rows=train_eligible, test_rows=test_eligible, split_strategy=fold.split_strategy,
    )
    return eligible_fold, len(fold.train_rows) - len(train_eligible), len(fold.test_rows) - len(test_eligible)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train-season", type=int, action="append", required=True, dest="train_seasons",
                         help="A season to train on. Repeatable, e.g. --train-season 2024 --train-season 2025.")
    parser.add_argument("--held-out-season", type=int, required=True,
                         help="The season to hold out and report results on. Must be chronologically "
                              "after every --train-season (Fold's own temporal-integrity check enforces this).")
    parser.add_argument("--final-ranks-file", type=Path, default=None,
                         help="JSON file of {event_key: {team_number: rank}}. Without it, the ranking "
                              "baseline is skipped explicitly rather than run against fabricated ground truth.")
    args = parser.parse_args(argv)

    settings = Settings()
    database = Database(DatabaseConfig(settings.database_url))
    all_seasons = [*args.train_seasons, args.held_out_season]

    print(f"Building training frame for seasons {all_seasons}...")
    frame = build_training_frame(database, all_seasons)
    print(
        f"{frame.manifest.row_count} rows built, {frame.manifest.excluded_count} excluded "
        f"(reasons: {frame.manifest.excluded_by_reason})"
    )
    if frame.manifest.row_count == 0:
        print("No rows to backtest -- have these seasons been synced? (python -m data.orchestrator --season YEAR)")
        return 1

    fold = hold_out_season_split(frame.rows, held_out_season=args.held_out_season)
    epa_fold, train_excluded, test_excluded = _split_epa_complete(fold)
    print(
        f"EPA-complete rows: {len(epa_fold.train_rows)} train (excluded {train_excluded} for missing/absent EPA), "
        f"{len(epa_fold.test_rows)} test (excluded {test_excluded})"
    )

    print("\n--- Win probability baseline (EpaWinProbBaseline) ---")
    win_prob_result = run_win_prob_backtest(EpaWinProbBaseline, [epa_fold])
    print(win_prob_result.summary())

    if args.final_ranks_file is None:
        print(
            "\n--- Ranking baseline: SKIPPED ---\n"
            "No --final-ranks-file given. This codebase does not yet ingest real final event "
            "rankings from anywhere (see ml.backtest.harness's module docstring) -- running the "
            "ranking baseline without real ground truth would either crash on empty final_ranks "
            "or silently produce a report with nothing meaningful in it. Neither is an acceptable "
            "substitute for the milestone's own required real, dated ranking result."
        )
    else:
        final_ranks_raw = json.loads(args.final_ranks_file.read_text(encoding="utf-8"))
        final_ranks = {
            event_key: {int(team): rank for team, rank in ranks.items()}
            for event_key, ranks in final_ranks_raw.items()
        }
        print("\n--- Ranking baseline (RawEpaRankingBaseline) ---")
        ranking_result = run_ranking_backtest(RawEpaRankingBaseline, [fold], final_ranks)
        print(ranking_result.summary())

    return 0


if __name__ == "__main__":
    sys.exit(main())
