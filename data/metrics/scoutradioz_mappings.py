"""The approved ScoutRadioz column mappings, one per season (audit 2026-11-26, workstream 8).

A mapping decides which raw column of a season's scouting form is a defense or feeding rating, on what native scale,
and which raw values are not ratings at all (data/metrics/scoutradioz.py's ScoutRadiozFieldMapping). It is a fact
about one season's form, established by inspecting a real export, so it is recorded here, not chosen at upload time.
The in-app uploader (data/metrics/scoutradioz_upload.py) imports only seasons listed here; any other season is refused
until its mapping is established and added.

2026: the mapping first recorded in scripts/import_2026mrcmp_scouting.py (its module docstring is the evidence for
each setting). That script now imports it from here, so there is one record.
- qDefenseQuality on its native 1-10 scale;
- "0" is "played no defense", not a rating (excluded, so no observation is produced);
- target_min=1, so a real "barely defended" (raw 1) never lands on the canonical 0;
- no feeding column: the 2026 form has none, so feeding stays unmeasured.
"""

from __future__ import annotations

from data.metrics.scoutradioz import ScoutRadiozFieldMapping, ScoutRadiozRatingMapping

MAPPING_2026 = ScoutRadiozFieldMapping(
    defense_rating=ScoutRadiozRatingMapping(
        column="qDefenseQuality",
        source_min=1,
        source_max=10,
        excluded_values=("0",),
        target_min=1,
    ),
)

APPROVED_FIELD_MAPPINGS: dict[int, ScoutRadiozFieldMapping] = {2026: MAPPING_2026}


def approved_mapping(season: int | None) -> ScoutRadiozFieldMapping | None:
    """The approved mapping for a season's scouting form, or None when none has been established."""
    return APPROVED_FIELD_MAPPINGS.get(season) if season is not None else None


def describe(mapping: ScoutRadiozFieldMapping) -> dict[str, object]:
    """What a mapping does, for showing before an import (column names and scales only)."""
    def rating(m: ScoutRadiozRatingMapping | None) -> dict[str, object] | None:
        if m is None:
            return None
        return {"column": m.column, "source_min": m.source_min, "source_max": m.source_max,
                "not_a_rating": list(m.excluded_values), "lowest_rating": m.target_min}

    return {"defense_rating": rating(mapping.defense_rating), "feeding_rating": rating(mapping.feeding_rating),
            "notes_columns": list(mapping.notes_columns)}


__all__ = ["APPROVED_FIELD_MAPPINGS", "MAPPING_2026", "approved_mapping", "describe"]
