"""Reproducible ScoutRadioz import for 2026mrcmp, with the exact column mapping.

This event's first import (2026-08-07) was run ad hoc, which made the single
most important input -- the ScoutRadiozFieldMapping -- unrecorded. That mapping
is not incidental: it decides which raw column is a defense rating, which raw
values are not ratings at all, and what canonical scale they land on, so an
import whose mapping nobody wrote down cannot be reproduced, audited, or
compared against a later one. This script exists to fix that. The mapping below
IS the record.

Why these four settings, all of them 2026-specific and none of them defaults:

  * column="qDefenseQuality" -- the 2026 scouting form's defense-quality field.
    Named here, in a script, and deliberately nowhere in data/metrics/
    scoutradioz.py, which stays free of any FRC game's field names.
  * source_min=1, source_max=10 -- the form's own native scale for a team that
    defended. Confirmed by inspecting the real export, not assumed.
  * excluded_values=("0",) -- on this column 0 means "played no defense", not
    "defended badly". Established by cross-tabulating the zero-rated rows
    against on-field participation (they participated normally and out-scored
    the rated defenders roughly 2:1). Rescaling that as a rating would publish
    a confident defense_score of 0.0 for a team that never defended, which is
    the inference-from-absence CLAUDE.md's "directly measured, NOT inferred"
    constraint forbids.
  * target_min=1 -- so raw 1, a real "barely defended", maps to canonical 1
    rather than to 0. Without it, (1-1)/9 * 5 + 0 = 0.0 exactly, and a genuine
    weak rating becomes indistinguishable from the "no defense" value the line
    above exists to protect. See RUNNING_NOTES' target_min entry.

Together the last two leave canonical 0 unreachable for this event: a stored 0
would mean neither "no defense" (those rows produce no observation at all) nor
a weak rating (those are >= 1). That is the point.

No feeding_rating is mapped because the 2026 form has no feeding-quality
column. That is a real gap in the source data, not an omission here -- feeding
stays unvalidatable until a feeding question exists at collection time.

Usage:

    python -m scripts.import_2026mrcmp_scouting --dry-run   # map only, no writes
    python -m scripts.import_2026mrcmp_scouting

--dry-run reads the CSV and prints the rating distribution the mapping produces
without touching the database at all, so the mapping can be checked before it
lands anything.

NOT idempotent in the way re-running a TBA sync is. import_scoutradioz_csv is
idempotent for an *unchanged* file (checksum dedup plus the watermark mean a
byte-identical re-run lands and loads nothing), but that same mechanism is why
re-importing this CSV under a *changed* mapping requires deleting the event's
watermark row first -- otherwise every row whose canonical rating happens not
to change produces a byte-identical payload, lands nothing, and is skipped by
read_pending's `id > watermark` filter. See RUNNING_NOTES' M14 re-import note.
"""

from __future__ import annotations

import argparse
import collections
import logging
from pathlib import Path

from data.config import Settings
from data.metrics.scoutradioz import (
    ScoutRadiozFieldMapping,
    ScoutRadiozRatingMapping,
    import_scoutradioz_csv,
)
from database.connection import Database, DatabaseConfig

CSV_PATH = Path("data/imports/matchscouting_frc11_2026mrcmp_full.csv")
EVENT_KEY = "2026mrcmp"

FIELD_MAPPING = ScoutRadiozFieldMapping(
    defense_rating=ScoutRadiozRatingMapping(
        column="qDefenseQuality",
        source_min=1,
        source_max=10,
        excluded_values=("0",),
        target_min=1,
    ),
)


def print_mapping_preview(csv_path: Path) -> None:
    """Print the raw->canonical distribution this mapping produces, without writing.

    Imports are deferred to here rather than at module scope for the same
    reason data.orchestrator.main defers its own: data.metrics.scoutradioz
    reaches back into data.orchestrator, and the CSV reader is only needed on
    this path.
    """
    from data.clients.scoutradioz import ScoutRadiozCsvImporter
    from data.metrics.scoutradioz import _row_expresses_no_rating, map_scoutradioz_row_to_observation_payload

    with ScoutRadiozCsvImporter(csv_path) as importer:
        rows = list(importer.read_rows())

    column = FIELD_MAPPING.defense_rating.column
    raw_counts: collections.Counter[str] = collections.Counter()
    pairs: collections.Counter[tuple[str, int | None]] = collections.Counter()
    excluded = 0
    malformed = 0

    for response in rows:
        raw_value = response.raw[column]
        raw_counts[raw_value] += 1
        if _row_expresses_no_rating(response.raw, FIELD_MAPPING):
            excluded += 1
            continue
        try:
            payload = map_scoutradioz_row_to_observation_payload(response.raw, response.parsed, FIELD_MAPPING)
        except ValueError:
            malformed += 1
            continue
        pairs[(raw_value, payload["defense_rating"])] += 1

    print(f"  {csv_path}")
    print(f"  {len(rows)} data rows, column {column!r}\n")
    print(f"  {'raw':>5}  {'canonical':>9}  {'rows':>5}")
    for raw_value, canonical in sorted(pairs, key=lambda p: int(p[0])):
        print(f"  {raw_value:>5}  {str(canonical):>9}  {pairs[(raw_value, canonical)]:>5}")
    print(f"\n  excluded (no rating expressed): {excluded}")
    print(f"  rated:                          {len(rows) - excluded - malformed}")
    if malformed:
        print(f"  structurally malformed:         {malformed}")
    print("\n  Canonical 0 is unreachable above: that is the target_min=1 fix working.")
    print("  Rows that reach the database are further limited by referential")
    print("  integrity -- a row whose match/team/event is not canonical yet is")
    print("  reported in `skipped`, not loaded.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Import the {EVENT_KEY} ScoutRadioz match-scouting export with its recorded field mapping.",
    )
    parser.add_argument("--csv", type=Path, default=CSV_PATH,
                        help=f"CSV export to import (default {CSV_PATH}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the raw->canonical mapping distribution and exit. No database access.")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        parser.error(f"{args.csv} does not exist")

    if args.dry_run:
        print_mapping_preview(args.csv)
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    database = Database(DatabaseConfig(Settings().database_url))
    result = import_scoutradioz_csv(args.csv, FIELD_MAPPING, database=database)

    print(f"\n  run_id      {result.run_id}")
    print(f"  event_key   {result.event_key}")
    print(f"  rows_read   {result.rows_read}")
    print(f"  excluded    {result.excluded_rows}")
    print(f"  landed      {result.landed}")
    print(f"  loaded      {result.loaded}")
    print(f"  skipped     {len(result.skipped)}")
    print(f"  malformed   {len(result.malformed_rows)}")
    for row_number, reason in result.malformed_rows[:10]:
        print(f"    row {row_number}: {reason}")
    if len(result.malformed_rows) > 10:
        print(f"    ... and {len(result.malformed_rows) - 10} more")

    print("\n  Metrics are NOT recomputed by this script. Run the metrics compute")
    print(f"  stage for {result.event_key} before reading any team's defense score,")
    print("  or team_metrics will still hold pre-import values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
