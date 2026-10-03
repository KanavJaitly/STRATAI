"""The EPA source boundary (data contract §7).

Consumers ask for EPA through this module and name the source:

* ``stratai`` -- STRATAI's own EPA engine (ml.ratings.epa), computed from the
  canonical database and read from a chained replay's write-once artifacts.
  This is the production source. It needs no Statbotics access at all.
* ``statbotics`` -- Statbotics' published values in team_event_stats. Kept as
  an optional external validation/reference source.

Two questions are answered:

* team_event_epa(team, event_key): a team's end-of-event EPA at one event.
* point_in_time_epa(team, target_event_key, as_of): the EPA Phase 4 may use to
  predict a match at ``target_event_key`` at time ``as_of``. Both sources apply
  the same selection rule, decision D13 (.agent/phase4/PHASE_STATUS.md):
  among the team's other events whose end_date is before as_of AND whose
  latest completed match for the team is before as_of, take the latest
  end_date, then the latest completed match, then event_key ascending.
  EPA_SOURCE_SQL is that rule over team_event_stats; StrataiPointInTimeEpa
  applies it to STRATAI results in Python, over the same canonical columns.
  STRATAI additionally knows when each value became knowable (available_at,
  ml.ratings.epa.aggregate) and removes any candidate not available strictly
  before as_of: a season-end team-event value, or a value whose season
  statistics still depended on unplayed week-1 matches. Like D13's own guard,
  this only ever removes candidates.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from database.connection import Database
from ml.ratings.epa.season import SeasonResult

logger = logging.getLogger(__name__)

EpaSource = Literal["statbotics", "stratai"]
# "d18_statbotics_primary" is the evaluated production configuration (D18): Statbotics primary,
# STRATAI fallback for 2026iscmp only (ml.ratings.statbotics_primary, ml.ratings.d18_source).
EPA_SOURCES: tuple[str, ...] = ("d18_statbotics_primary", "stratai", "statbotics", "p5_live_statbotics")

UNAVAILABLE_NOT_RUN = "season_not_run"
UNAVAILABLE_NO_TEAM_EVENT = "team_did_not_play_event"
# The single "nothing qualified" reason Phase 4's assembler has always used
# (see ml.features.assembler._point_in_time_epa's docstring).
EPA_WITHHELD_NO_PRIOR_EVENT = "no_prior_concluded_event_epa"

# Decision D13 over Statbotics' team_event_stats. "Completed" = the team's own
# alliance score is recorded, the same played test data.metrics.history applies.
EPA_SOURCE_SQL = """
SELECT tes.event_key, tes.epa_total, tes.epa_auto, tes.epa_teleop, tes.epa_endgame
FROM team_event_stats tes
JOIN events e ON e.event_key = tes.event_key
JOIN LATERAL (
    SELECT MAX(m.scheduled_time) AS last_completed_match
    FROM match_teams mt
    JOIN matches m ON m.match_key = mt.match_key
    WHERE mt.team_number = tes.team_number
      AND m.event_key = tes.event_key
      AND m.scheduled_time IS NOT NULL
      AND (CASE WHEN mt.alliance_color = 'red' THEN m.score_red ELSE m.score_blue END) IS NOT NULL
) lm ON lm.last_completed_match < %(as_of)s
WHERE tes.team_number = %(team)s
  AND tes.event_key != %(target)s
  AND e.end_date IS NOT NULL
  AND e.end_date::timestamptz < %(as_of)s
ORDER BY e.end_date DESC, lm.last_completed_match DESC, tes.event_key ASC
LIMIT 1
"""

# The same per-(team, event) canonical facts EPA_SOURCE_SQL filters on, for every pair at once.
TEAM_EVENT_FACTS_SQL = """
SELECT mt.team_number, m.event_key, e.end_date::timestamptz,
       MAX(m.scheduled_time) FILTER (
           WHERE m.scheduled_time IS NOT NULL
             AND (CASE WHEN mt.alliance_color = 'red' THEN m.score_red ELSE m.score_blue END) IS NOT NULL
       )
FROM match_teams mt
JOIN matches m ON m.match_key = mt.match_key
JOIN events e ON e.event_key = m.event_key
GROUP BY mt.team_number, m.event_key, e.end_date
"""


@dataclass(frozen=True)
class TeamEventEpa:
    """End-of-event EPA, the snapshot semantics Phase 4 reads from team_event_stats."""

    team: int
    event_key: str
    total: float
    auto: float
    teleop: float
    endgame: float
    source: EpaSource
    lookahead: bool  # True when the value is the team's season-end rating (aggregate.py)
    provenance: dict


@dataclass(frozen=True)
class Unavailable:
    reason: str
    detail: str


class EpaProvider(Protocol):
    source: EpaSource

    def team_event_epa(self, team: int, event_key: str) -> TeamEventEpa | Unavailable: ...


class PointInTimeEpaProvider(Protocol):
    """What Phase 4's assembler asks: the EPA usable to predict a match at as_of."""

    source: EpaSource

    def point_in_time_epa(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable: ...

    def provenance(self) -> dict[str, Any]: ...


class StrataiEpaProvider:
    """Serves team-event EPA from in-memory SeasonResults of the STRATAI engine."""

    source: EpaSource = "stratai"

    def __init__(self, results: list[SeasonResult]) -> None:
        self._results = {r.season: r for r in results}
        self._fingerprints = {r.season: r.results_fingerprint() for r in results}

    def team_event_epa(self, team: int, event_key: str) -> TeamEventEpa | Unavailable:
        season = int(event_key[:4]) if event_key[:4].isdigit() else None
        result = self._results.get(season) if season is not None else None
        if result is None:
            return Unavailable(UNAVAILABLE_NOT_RUN, f"no STRATAI EPA run for season of {event_key}")
        team_event = result.team_event(team, event_key)
        if team_event is None:
            return Unavailable(UNAVAILABLE_NO_TEAM_EVENT, f"team {team} has no retained match at {event_key}")
        components = team_event.components
        return TeamEventEpa(
            team=team,
            event_key=event_key,
            total=team_event.epa,
            auto=components["auto_epa"],
            teleop=components["teleop_epa"],
            endgame=components["endgame_epa"],
            source=self.source,
            lookahead=team_event.epa_is_season_end,
            provenance={
                "engine_version": result.manifest["engine_version"],
                "input_fingerprint": result.manifest["input_fingerprint"],
                "results_fingerprint": self._fingerprints[result.season],
                "initialization": result.initialization,
            },
        )


# --- Statbotics (reference) --------------------------------------------------------


class StatboticsPointInTimeEpa:
    """Decision D13 over team_event_stats, exactly as Phase 4 has always read it."""

    source: EpaSource = "statbotics"

    def __init__(self, database: Database) -> None:
        self._database = database

    def point_in_time_epa(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable:
        with self._database.cursor() as cursor:
            cursor.execute(EPA_SOURCE_SQL, {"team": team, "target": target_event_key, "as_of": as_of})
            row = cursor.fetchone()
        if row is None:
            return Unavailable(EPA_WITHHELD_NO_PRIOR_EVENT, "no qualifying prior event in team_event_stats")
        event_key, total, auto, teleop, endgame = row
        return TeamEventEpa(team, event_key, total, auto, teleop, endgame, self.source, False, {})

    def provenance(self) -> dict[str, Any]:
        return {"source": self.source, "table": "team_event_stats", "selection": "D13 EPA_SOURCE_SQL"}


# --- STRATAI (production) ----------------------------------------------------------


@dataclass(frozen=True)
class TeamEventFacts:
    """Canonical facts D13 filters on, for one (team, event)."""

    event_key: str
    end_instant: datetime | None  # events.end_date::timestamptz, as EPA_SOURCE_SQL casts it
    last_completed_match: datetime | None  # the team's latest completed match there


@dataclass(frozen=True)
class StrataiTeamEventValue:
    total: float
    auto: float
    teleop: float
    endgame: float
    available_at: int  # epoch seconds; usable only when strictly before as_of
    epa_is_season_end: bool


class StaleEpaArtifacts(RuntimeError):
    """The artifacts do not describe the database they are being used with."""


def read_team_event_facts(database: Database, teams: list[int] | None = None) -> dict[int, list[TeamEventFacts]]:
    """Every team's (event, end instant, last completed match), from canonical tables."""
    out: dict[int, list[TeamEventFacts]] = defaultdict(list)
    sql = TEAM_EVENT_FACTS_SQL
    if teams is not None:
        sql = sql.replace("GROUP BY", "WHERE mt.team_number = ANY(%(teams)s) GROUP BY")
    with database.cursor() as cursor:
        if teams is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, {"teams": teams})
        for team, event_key, end_instant, last_completed in cursor.fetchall():
            out[team].append(TeamEventFacts(event_key, end_instant, last_completed))
    return dict(out)


def _d13_order(facts: TeamEventFacts) -> tuple:
    # end_date DESC, last completed match DESC, event_key ASC; facts without both are never candidates
    return (-facts.end_instant.timestamp(), -facts.last_completed_match.timestamp(), facts.event_key)  # type: ignore[union-attr]


@dataclass
class StrataiPointInTimeEpa:
    """D13 selection over STRATAI team-event results, plus STRATAI availability."""

    values: dict[tuple[int, str], StrataiTeamEventValue]
    facts: dict[int, list[TeamEventFacts]]
    provenance_info: dict[str, Any]
    diagnostics: Counter = field(default_factory=Counter)
    source: EpaSource = "stratai"

    def __post_init__(self) -> None:
        self._ordered = {
            team: sorted((f for f in items if f.end_instant is not None and f.last_completed_match is not None),
                         key=_d13_order)
            for team, items in self.facts.items()
        }

    def point_in_time_epa(self, team: int, target_event_key: str, as_of: datetime) -> TeamEventEpa | Unavailable:
        as_of_epoch = as_of.timestamp()
        for facts in self._ordered.get(team, ()):
            if facts.event_key == target_event_key:
                continue
            if not (facts.end_instant < as_of and facts.last_completed_match < as_of):  # type: ignore[operator]
                continue
            value = self.values.get((team, facts.event_key))
            if value is None:
                continue  # like a missing team_event_stats row: not a candidate
            if not value.available_at < as_of_epoch:
                self.diagnostics["season_end" if value.epa_is_season_end else "week_one_statistics"] += 1
                continue
            self.diagnostics["served"] += 1
            return TeamEventEpa(team, facts.event_key, value.total, value.auto, value.teleop, value.endgame,
                                self.source, False, {"available_at": value.available_at})
        self.diagnostics["withheld"] += 1
        return Unavailable(EPA_WITHHELD_NO_PRIOR_EVENT, "no qualifying prior event with an available STRATAI EPA")

    def provenance(self) -> dict[str, Any]:
        return {"source": self.source, **self.provenance_info}

    @classmethod
    def from_results(cls, database: Database, results: list[SeasonResult],
                     provenance: dict[str, Any] | None = None) -> StrataiPointInTimeEpa:
        values = {
            (e.team, e.event_key): StrataiTeamEventValue(
                e.epa, e.components["auto_epa"], e.components["teleop_epa"], e.components["endgame_epa"],
                e.available_at, e.epa_is_season_end)
            for r in results for e in r.team_events
        }
        info = provenance or {"seasons": [{"season": r.season, "results_fingerprint": r.results_fingerprint()}
                                          for r in results]}
        return cls(values, read_team_event_facts(database), info)

    @classmethod
    def from_chain_manifest(cls, database: Database, chain_path: Path, *,
                            verify_snapshot: bool = True) -> StrataiPointInTimeEpa:
        """Load a chained replay's artifacts, checking file integrity and, by default,
        that each season's raw-payload snapshot still matches this database."""
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
        values: dict[tuple[int, str], StrataiTeamEventValue] = {}
        seasons = []
        for entry in chain["chain"]:
            directory = chain_path.parent / entry["directory"]
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest["results_fingerprint"] != entry["results_fingerprint"]:
                raise StaleEpaArtifacts(f"{directory} does not hold the chained result {entry['results_fingerprint']}")
            raw = (directory / "team_events.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != manifest["files"]["team_events.json"]:
                raise StaleEpaArtifacts(f"{directory}/team_events.json does not match its manifest digest")
            if verify_snapshot:
                _verify_snapshot(database, entry["season"], manifest["data_snapshot"])
            for e in json.loads(raw):
                values[(e["team"], e["event_key"])] = StrataiTeamEventValue(
                    e["epa"], e["components"]["auto_epa"], e["components"]["teleop_epa"],
                    e["components"]["endgame_epa"], e["available_at"], e["epa_is_season_end"])
            seasons.append({k: entry[k] for k in ("season", "results_fingerprint", "input_fingerprint", "prior_source")})
        info = {"chain_manifest": chain_path.name, "seasons": seasons, "snapshot_verified": verify_snapshot}
        return cls(values, read_team_event_facts(database), info)


def _verify_snapshot(database: Database, season: int, recorded: dict[str, Any]) -> None:
    from ml.ratings.reader import read_season_input  # the reader is the only database reader of STRATAI inputs

    current = read_season_input(database, season).snapshot
    if current["raw_payload_ids_sha256"] != recorded["raw_payload_ids_sha256"]:
        raise StaleEpaArtifacts(
            f"season {season}: the database's raw TBA payloads changed since the EPA replay "
            f"(recorded {recorded['raw_payload_ids_sha256'][:16]}, now {current['raw_payload_ids_sha256'][:16]}); "
            "re-run python -m scripts.run_epa_replay --chain"
        )


# --- configured default --------------------------------------------------------------

_DEFAULT_CACHE: dict[tuple, PointInTimeEpaProvider] = {}


class EpaSourceNotConfigured(RuntimeError):
    pass


def default_point_in_time_provider(database: Database, settings: Any | None = None) -> PointInTimeEpaProvider:
    """The provider Settings selects (epa_source, stratai_epa_chain), built once per process."""
    if settings is None:
        from data.config import Settings

        settings = Settings()
    source = settings.epa_source
    if source == "d18_statbotics_primary":
        from ml.ratings.d18_source import load_d18_provider

        if settings.statbotics_snapshot_dir is None or settings.stratai_epa_chain is None:
            raise EpaSourceNotConfigured(
                "epa_source is 'd18_statbotics_primary' (the evaluated D18 configuration) but "
                "STATBOTICS_SNAPSHOT_DIR and STRATAI_EPA_CHAIN are not both set: point them at the verified "
                "snapshot directory (scripts/sync_statbotics_snapshot.py) and the STRATAI chain_<hash>.json"
            )
        key: tuple = ("d18", str(Path(settings.statbotics_snapshot_dir).resolve()),
                      str(Path(settings.stratai_epa_chain).resolve()), id(database))
        if key not in _DEFAULT_CACHE:
            logger.info("loading D18 EPA source: snapshot %s, fallback chain %s",
                        settings.statbotics_snapshot_dir, settings.stratai_epa_chain)
            _DEFAULT_CACHE[key] = load_d18_provider(database, Path(settings.statbotics_snapshot_dir),
                                                    Path(settings.stratai_epa_chain))[0]
        return _DEFAULT_CACHE[key]
    if source == "p5_live_statbotics":
        from ml.ratings.live_snapshots import SnapshotLog
        from ml.ratings.live_source import load_live_provider

        missing = [name for name, value in (("LIVE_EPA_LOG_DIR", settings.live_epa_log_dir),
                                            ("STATBOTICS_SNAPSHOT_DIR", settings.statbotics_snapshot_dir),
                                            ("STRATAI_EPA_CHAIN", settings.stratai_epa_chain),
                                            ("LIVE_EPA_A1A2_POLICY", settings.live_epa_a1a2_policy)) if not value]
        if missing:
            raise EpaSourceNotConfigured(
                f"epa_source is 'p5_live_statbotics' (P5-M2, not the evaluated configuration) but {missing} are "
                "unset; LIVE_EPA_A1A2_POLICY is open decision Q1 (.agent/phase5/M02_DECISION_REQUIRED.md)")
        root = Path(settings.statbotics_snapshot_dir)  # type: ignore[arg-type]
        return load_live_provider(database, root_dir=root, chain=Path(settings.stratai_epa_chain),  # type: ignore[arg-type]
                                  a1a2_policy=settings.live_epa_a1a2_policy,  # type: ignore[arg-type]
                                  concluded_seasons=set(settings.live_epa_concluded_seasons),
                                  log=SnapshotLog(Path(settings.live_epa_log_dir), root))  # type: ignore[arg-type]
    if source == "statbotics":
        key = ("statbotics", id(database))
        if key not in _DEFAULT_CACHE:
            _DEFAULT_CACHE[key] = StatboticsPointInTimeEpa(database)
        return _DEFAULT_CACHE[key]
    if settings.stratai_epa_chain is None:
        raise EpaSourceNotConfigured(
            "epa_source is 'stratai' but STRATAI_EPA_CHAIN is not set: point it at the chain_<hash>.json "
            "written by `python -m scripts.run_epa_replay --chain`"
        )
    key = ("stratai", str(Path(settings.stratai_epa_chain).resolve()), id(database))
    if key not in _DEFAULT_CACHE:
        logger.info("loading STRATAI EPA chain %s", settings.stratai_epa_chain)
        _DEFAULT_CACHE[key] = StrataiPointInTimeEpa.from_chain_manifest(database, Path(settings.stratai_epa_chain))
    return _DEFAULT_CACHE[key]
