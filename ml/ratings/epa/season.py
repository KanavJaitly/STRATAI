"""Run one season end to end, in memory: the engine core's public entry point.

    prepare (validation) -> week-1 statistics -> starting ratings
    -> the match loop -> team-event / team-season aggregation -> norm

No database, no network, no clock except the manifest's created_at. The
results (everything but the manifest) are a pure function of the SeasonInput
and the constants, serialized canonically so two runs can be compared byte
for byte (data contract §6.2).
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ml.ratings.epa import constants as c
from ml.ratings.epa.aggregate import (
    Availability,
    TeamEventResult,
    TeamSeasonResult,
    aggregate,
    season_availability,
    with_norm,
)
from ml.ratings.epa.engine import EpaEngine, MatchRecord
from ml.ratings.epa.exclusions import ExclusionReport
from ml.ratings.epa.initialization import initial_ratings
from ml.ratings.epa.inputs import SeasonInput, canonical_json, fingerprint, season_input_fingerprint
from ml.ratings.epa.normalization import epa_to_norm_epa_func, scipy_version
from ml.ratings.epa.validation import PreparedSeason, prepare_season
from ml.ratings.epa.year_stats import YearStats, compute_year_stats

NO_PRIOR_LABEL = "initialized without prior-season history"


@dataclass(frozen=True)
class SeasonResult:
    season: int
    stats: YearStats
    initialization: str
    records: tuple[MatchRecord, ...]
    team_seasons: tuple[TeamSeasonResult, ...]
    team_events: tuple[TeamEventResult, ...]
    report: ExclusionReport
    norm_computed: bool
    availability: Availability
    manifest: dict[str, Any] = field(compare=False)

    def results_payload(self) -> dict[str, Any]:
        """Everything the engine computed, with no environment facts."""
        return {
            "season": self.season,
            "initialization": self.initialization,
            "stats": self.stats.to_dict(),
            "availability": self.availability.to_dict(),
            "records": [r.to_dict() for r in self.records],
            "reference_rounded_records": [r.reference_rounded(self.season) for r in self.records],
            "team_seasons": [t.to_dict() for t in self.team_seasons],
            "team_events": [t.to_dict() for t in self.team_events],
            "report": self.report.to_dict(),
            "norm_computed": self.norm_computed,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.results_payload())

    def results_fingerprint(self) -> str:
        return fingerprint(self.results_payload())

    def team_event(self, team: int, event_key: str) -> TeamEventResult | None:
        for result in self.team_events:
            if result.team == team and result.event_key == event_key:
                return result
        return None


def start_engine(season_input: SeasonInput) -> tuple[PreparedSeason, EpaEngine]:
    """Validation, statistics and starting ratings: an engine ready for match 0."""
    prepared = prepare_season(season_input)
    stats = compute_year_stats(prepared.season, prepared.stream)
    ratings = initial_ratings(stats, prepared.teams, season_input.prior, season_input.team_districts)
    return prepared, EpaEngine(stats, ratings)


def run_season(
    season_input: SeasonInput,
    *,
    compute_norm: bool = True,
    data_snapshot: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> SeasonResult:
    """Process one season. Raises RunRejected for an unusable input."""
    prepared, engine = start_engine(season_input)
    start = engine.ratings()
    records = tuple(engine.process(match) for match in prepared.stream)
    final = engine.ratings()
    availability = season_availability(prepared.stream)
    seasons, events = aggregate(
        engine.stats, prepared.stream, records, start, final, {t: engine.qual_count(t) for t in prepared.teams},
        availability,
    )
    norm_computed = False
    if compute_norm:
        seasons, events = with_norm(seasons, events, epa_to_norm_epa_func([s.epa for s in seasons]))
        norm_computed = bool(seasons)
    report = prepared.collector.report()
    initialization = NO_PRIOR_LABEL if season_input.prior is None else f"prior supplied: {season_input.prior.source}"
    manifest = build_manifest(
        season_input, report, norm_computed=norm_computed, data_snapshot=data_snapshot, created_at=created_at
    )
    return SeasonResult(
        season=prepared.season,
        stats=engine.stats,
        initialization=initialization,
        records=records,
        team_seasons=tuple(seasons),
        team_events=tuple(events),
        report=report,
        norm_computed=norm_computed,
        availability=availability,
        manifest=manifest,
    )


def build_manifest(
    season_input: SeasonInput,
    report: ExclusionReport,
    *,
    norm_computed: bool,
    data_snapshot: dict[str, Any] | None,
    created_at: str | None,
) -> dict[str, Any]:
    """Provenance for one run (data contract §6.3)."""
    prior = season_input.prior
    return {
        "engine_version": c.ENGINE_VERSION,
        "spec_version": c.SPEC_VERSION,
        "reference": {"repo": c.REFERENCE_REPO, "commit": c.REFERENCE_COMMIT},
        "configuration": c.configuration(),
        "configuration_hash": c.configuration_hash(),
        "season": season_input.season,
        "input_fingerprint": season_input_fingerprint(season_input),
        "prior": "none supplied"
        if prior is None
        else {"source": prior.source, "fingerprint": fingerprint(prior.model_dump(mode="json"))},
        "data_snapshot": data_snapshot,
        "libraries": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy_version(),
            "scipy_used": norm_computed,
        },
        "exclusion_counts": dict(report.counts),
        "divergences": dict(report.divergences),
        "possible_divergences": dict(report.possible_divergences),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }

