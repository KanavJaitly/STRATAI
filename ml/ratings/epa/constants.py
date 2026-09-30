"""Every constant the EPA engine uses, each cited to the pinned reference.

The reference is avgupta456/statbotics at REFERENCE_COMMIT (MIT licensed,
Copyright (c) 2020 Abhijit Gupta). Citations are paths under that repository's
backend/src/. docs/ratings/epa_specification.md is the normative description;
where it and a comment here disagree, the specification wins and this file is
the bug.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

ENGINE_VERSION = "0.1.0"
# Commit that introduced docs/ratings/epa_specification.md and data_contract.md.
SPEC_VERSION = "7d890d8"
REFERENCE_REPO = "avgupta456/statbotics"
REFERENCE_COMMIT = "a2cea5553e35693d423400f419bd770cb2143408"

SUPPORTED_SEASONS: tuple[int, ...] = (2024, 2025, 2026)

# models/epa/constants.py
NORM_MEAN = 1500
NORM_SD = 250
INIT_PENALTY = 0.2
YEAR_ONE_WEIGHT = 0.7
MEAN_REVERSION = 0.4
ELIM_WEIGHT = 1 / 3

# constants.py:42
EPS = 1e-6

# models/template.py:25 (2 only for seasons <= 2004)
NUM_TEAMS = 3

# models/epa/main.py:26-27 (k_func, seasons >= 2008)
WIN_PROB_K = -5 / 8

# models/epa/main.py:37 (percent_func); the 2/3 factor applies to seasons >= 2016
PERCENT_MAX = 0.5
PERCENT_MIN = 0.3
PERCENT_SLOPE = 0.2 / 6
PERCENT_PIVOT = 6
PERCENT_FACTOR = 2 / 3

# models/epa/main.py:59 (Y-1 .. Y-4) and init.py:39 (first two found)
PRIOR_LOOKBACK_SEASONS = 4

# models/epa/main.py:69-70: 2026 teams in district "isr" get no mean reversion
ISR_DISTRICT = "isr"
ISR_SEASON = 2026

# tba/constants.py:115
PLACEHOLDER_TEAMS: frozenset[int] = frozenset(range(9970, 10000))

# tba/constants.py:122-130; tba/read_tba.py:89 also drops any key containing "tempclone"
EVENT_BLACKLIST: frozenset[str] = frozenset(
    {"2004va", "2005va", "2007ga", "2022zhha", "2024nywz", "2025mnsp", "2025miwrc"}
)
TEMPCLONE_MARKER = "tempclone"

# TBA event_type integers (tba/read_tba.py:100-110)
TBA_REGIONAL = 0
TBA_DISTRICT = 1
TBA_DISTRICT_CMP = 2
TBA_CHAMPS_DIV = 3
TBA_EINSTEIN = 4
TBA_DISTRICT_CMP_DIVISION = 5
TBA_FESTIVAL_OF_CHAMPS = 6
TBA_OFFSEASON = 99
TBA_PRESEASON = 100
EXCLUDED_EVENT_TYPES: frozenset[int] = frozenset({TBA_OFFSEASON, TBA_PRESEASON})
# tba/constants.py:137-139, expressed as the TBA type it is treated as
EVENT_TYPE_OVERRIDES: dict[str, int] = {"2026isrtp": TBA_DISTRICT}
# Types the reference maps to REGIONAL / DISTRICT / DISTRICT_CMP (week + 1)
WEEK_SHIFTED_EVENT_TYPES: frozenset[int] = frozenset(
    {TBA_REGIONAL, TBA_DISTRICT, TBA_DISTRICT_CMP, TBA_DISTRICT_CMP_DIVISION}
)
# Types the reference maps to CHAMPS_DIV / EINSTEIN (week forced to 8)
CHAMPS_EVENT_TYPES: frozenset[int] = frozenset({TBA_CHAMPS_DIV, TBA_EINSTEIN, TBA_FESTIVAL_OF_CHAMPS})
CHAMPS_WEEK = 8
YEAR_STATS_WEEK = 1

# The 18-dimension rating vector (models/epa, src/breakdown.py all_keys)
VECTOR_LENGTH = 18
NO_FOUL = 0
AUTO = 1
TELEOP = 2
ENDGAME = 3
RP_1 = 4
RP_2 = 5
RP_3 = 6
TIEBREAKER = 7
COMP_0 = 8
COMPONENT_COUNT = 10
RP_INDICES: tuple[int, ...] = (RP_1, RP_2, RP_3)

# 2025 processor-algae indices (comp_6, comp_7, comp_8)
PROCESSOR_ALGAE_2025 = COMP_0 + 6
PROCESSOR_ALGAE_POINTS_2025 = COMP_0 + 7
NET_ALGAE_POINTS_2025 = COMP_0 + 8
PROCESSOR_ALGAE_REVALUE = 3

# Human-readable names of comp_0..comp_9 (src/breakdown.py:127-179); "empty" pads.
COMPONENT_NAMES: dict[int, tuple[str, ...]] = {
    2024: (
        "auto_leave_points", "auto_note_points", "teleop_note_points", "speaker_points",
        "amplified_notes", "endgame_park_points", "endgame_on_stage_points",
        "endgame_harmony_points", "endgame_trap_points", "endgame_spotlight_points",
    ),
    2025: (
        "auto_coral_points", "teleop_coral_points", "coral_l1", "coral_l2", "coral_l3",
        "coral_l4", "processor_algae", "processor_algae_points", "net_algae_points",
        "barge_points",
    ),
    2026: (
        "auto_fuel", "auto_tower", "transition_fuel", "first_shift_fuel",
        "second_shift_fuel", "endgame_fuel", "endgame_tower", "empty", "empty", "empty",
    ),
}

# Names of the reference's per-team EPA fields (models/epa/main.py:174-239), vector order.
EPA_FIELD_NAMES: tuple[str, ...] = (
    "epa", "auto_epa", "teleop_epa", "endgame_epa", "rp_1_epa", "rp_2_epa", "rp_3_epa",
    "tiebreaker_epa", *(f"comp_{i}_epa" for i in range(COMPONENT_COUNT)),
)


def configuration() -> dict[str, Any]:
    """Every constant that can change a numeric result, for the run manifest."""
    return {
        "reference_commit": REFERENCE_COMMIT,
        "norm_mean": NORM_MEAN,
        "norm_sd": NORM_SD,
        "init_penalty": INIT_PENALTY,
        "year_one_weight": YEAR_ONE_WEIGHT,
        "mean_reversion": MEAN_REVERSION,
        "elim_weight": ELIM_WEIGHT,
        "eps": EPS,
        "num_teams": NUM_TEAMS,
        "win_prob_k": WIN_PROB_K,
        "percent": [PERCENT_MAX, PERCENT_MIN, PERCENT_SLOPE, PERCENT_PIVOT, PERCENT_FACTOR],
        "prior_lookback_seasons": PRIOR_LOOKBACK_SEASONS,
        "isr": [ISR_SEASON, ISR_DISTRICT],
        "placeholder_teams": [min(PLACEHOLDER_TEAMS), max(PLACEHOLDER_TEAMS)],
        "event_blacklist": sorted(EVENT_BLACKLIST),
        "event_type_overrides": dict(sorted(EVENT_TYPE_OVERRIDES.items())),
        "year_stats_week": YEAR_STATS_WEEK,
        "processor_algae_revalue": PROCESSOR_ALGAE_REVALUE,
    }


def configuration_hash() -> str:
    """sha256 of the canonical JSON of configuration()."""
    text = json.dumps(configuration(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
