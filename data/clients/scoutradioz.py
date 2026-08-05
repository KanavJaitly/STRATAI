"""ScoutRadioz CSV import connector.

Phase 3 Milestone 9. ScoutRadioz (github.com/FIRSTTeam102/scoutradioz) has no
public API -- confirmed 2026-08-05 by reading its real GitHub repo, wiki, and
TypeScript route source directly: every data-bearing route, including its own
CSV export (`/exportdata`), sits behind an authenticated per-team login. There
is nothing this client could poll the way TBAClient/StatboticsClient do.

A team exports match-scouting data from their own ScoutRadioz instance as a
CSV file and hands it to StratAI directly; this module reads that file. It
still implements SourceConnector/SourceResponse -- the identical contract
TBAClient/StatboticsClient implement -- specifically so that IF ScoutRadioz
ever publishes a real API, a future ScoutRadiozClient built against it could
return the same SourceResponse[ScoutRadiozMatchScoutingRow] shape this reader
does, and nothing downstream (data.metrics.scoutradioz, staging, landing,
canonical) would need to change. close() is a no-op: a CSV file holds no
connection to release, unlike TBA/Statbotics's httpx.Client.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterator

from data.clients.schemas import ScoutRadiozMatchScoutingRow
from data.clients.source_connector import SourceConnector, SourceResponse

__all__ = ["ScoutRadiozCsvImporter"]


@dataclass
class ScoutRadiozCsvImporter(SourceConnector):
    """Reads a ScoutRadioz match-scouting CSV export, one row at a time."""

    csv_path: Path
    source_name: ClassVar[str] = "scoutradioz"

    def close(self) -> None:
        """No-op: reading a CSV file holds no resource that needs releasing."""

    def read_rows(self) -> Iterator[SourceResponse[ScoutRadiozMatchScoutingRow]]:
        """Yield one SourceResponse per CSV row: the untouched row dict alongside
        the typed, platform-stable metadata view.

        `raw` keeps every column the export carries, including whichever
        game-specific fields one season's form happens to define -- exactly
        the same "land everything, drop nothing" principle that governs TBA
        and Statbotics's own SourceResponse.raw. `parsed` is deliberately
        built via model_validate rather than field-by-field: pydantic ignores
        the extra (game-specific) keys by default and coerces the numeric
        string columns (e.g. match_number) the csv module always hands back
        as strings, so this stays correct without needing to change when a
        new game's form adds columns this model doesn't know about.
        """
        with open(self.csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                parsed = ScoutRadiozMatchScoutingRow.model_validate(raw_row)
                yield SourceResponse(raw_row, parsed)
