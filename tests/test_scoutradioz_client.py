"""Phase 3 Milestone 9: the ScoutRadioz CSV-reading connector.

Uses a real captured ScoutRadioz match-scouting export (tests/fixtures/
scoutradioz_matchscouting_2026mrcmp.csv, 66 rows from a real 2026 event),
not an invented shape -- this project's established rule after being burned
once already by a hand-guessed Statbotics shape (see RUNNING_NOTES.md's
2026-07-25 decisions). The fixture deliberately includes the real edge cases
found while researching this milestone: a genuinely blank `scouter` cell, the
full observed 0-10 range of the game-specific `qDefenseQuality` column, and a
midnight ("12:00:00 AM") match time boundary.
"""

from __future__ import annotations

from pathlib import Path

from data.clients.schemas import ScoutRadiozMatchScoutingRow
from data.clients.scoutradioz import ScoutRadiozCsvImporter
from data.clients.source_connector import SourceConnector, SourceResponse

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "scoutradioz_matchscouting_2026mrcmp.csv"


def test_is_a_source_connector():
    importer = ScoutRadiozCsvImporter(FIXTURE_PATH)
    assert isinstance(importer, SourceConnector)
    assert importer.source_name == "scoutradioz"


def test_context_manager_close_is_a_no_op():
    # Unlike TBAClient/StatboticsClient, closing holds no httpx.Client to
    # release -- a CSV file has no connection. __enter__/__exit__ are
    # inherited from SourceConnector, not overridden (see the system-wide
    # audit's typing.Self fix in data/clients/source_connector.py).
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        assert isinstance(importer, ScoutRadiozCsvImporter)
    # No exception on double-close either.
    importer.close()
    importer.close()


def test_reads_every_row_as_a_source_response():
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        rows = list(importer.read_rows())

    assert len(rows) == 66
    for response in rows:
        assert isinstance(response, SourceResponse)
        assert isinstance(response.raw, dict)
        assert isinstance(response.parsed, ScoutRadiozMatchScoutingRow)


def test_raw_preserves_every_column_including_game_specific_ones():
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        first = next(iter(importer.read_rows()))

    # Metadata columns this connector explicitly models...
    assert first.raw["org_key"] == "frc11"
    assert first.raw["team_key"] == "frc1672"
    # ...and game-specific columns it deliberately does NOT model, but must
    # not drop -- exactly the "land raw, not a projection" principle
    # data/pipeline.py's own module docstring establishes for TBA/Statbotics.
    assert first.raw["qDefenseQuality"] == "0"
    assert first.raw["FuelPoints"] == "37"
    assert first.raw["superNotes"] == ""


def test_parsed_carries_only_the_stable_metadata_fields():
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        first = next(iter(importer.read_rows()))

    parsed = first.parsed
    assert parsed.org_key == "frc11"
    assert parsed.event_key == "2026mrcmp"
    assert parsed.match_key == "2026mrcmp_qm1"
    assert parsed.match_number == 1
    assert parsed.time == "4/16/2026 3:15:00 PM"
    assert parsed.alliance == "red"
    assert parsed.team_key == "frc1672"
    assert parsed.scouter == "Matthew Paccione"


def test_match_number_is_coerced_to_int_despite_csv_giving_strings():
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        rows = list(importer.read_rows())

    assert all(isinstance(r.parsed.match_number, int) for r in rows)


def test_blank_scouter_cell_parses_as_empty_string_not_an_error():
    # The real, captured gap in ScoutRadioz's own data (see this module's
    # docstring) -- must not crash the reader, only surface downstream as a
    # rejected observation (data.metrics.scoutradioz's own job).
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        rows = list(importer.read_rows())

    blank = [r for r in rows if r.parsed.scouter == ""]
    assert len(blank) == 1
    assert blank[0].parsed.match_key == "2026mrcmp_qm93"
    assert blank[0].parsed.team_key == "frc10918"


def test_full_observed_defense_quality_range_is_present_in_the_fixture():
    # Pins the premise every rescaling test in test_scoutradioz_import.py
    # relies on: the fixture genuinely spans the source scale's full range.
    with ScoutRadiozCsvImporter(FIXTURE_PATH) as importer:
        values = {r.raw["qDefenseQuality"] for r in importer.read_rows()}

    assert values == {str(n) for n in range(11)}
