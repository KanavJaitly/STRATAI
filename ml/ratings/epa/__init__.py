"""The pure STRATAI EPA engine core.

A reproduction of the Statbotics EPA methodology as pinned in
docs/ratings/epa_specification.md, computed only from the canonical inputs of
docs/ratings/data_contract.md. It makes no database access, no network calls
and no Statbotics calls; initialization history is an explicit input.

Passing tests show only that this code matches the specification's
formulas. They are not evidence of numerical agreement with Statbotics'
published values; that is a separate validation step (spec §0, levels A-C).
"""

from ml.ratings.epa.exclusions import ExclusionReport, RunRejected
from ml.ratings.epa.inputs import (
    AllianceInput,
    EventInput,
    MatchInput,
    PriorSeasonInput,
    PriorTeamYear,
    SeasonInput,
)
from ml.ratings.epa.season import NO_PRIOR_LABEL, SeasonResult, run_season, start_engine

__all__ = [
    "AllianceInput",
    "EventInput",
    "ExclusionReport",
    "MatchInput",
    "NO_PRIOR_LABEL",
    "PriorSeasonInput",
    "PriorTeamYear",
    "RunRejected",
    "SeasonInput",
    "SeasonResult",
    "run_season",
    "start_engine",
]
