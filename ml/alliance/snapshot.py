"""P11A §14: the event snapshot, the one input to estimation, the plan and the profile, online and offline.

**Contents** (everything known before `as_of`):
- the event's qualification alliance rows, with their component points (P5-M7 adapter) and provenance;
- the qualification roster, and the final ranks when they are final;
- each robot's independent prior from its most recent earlier same-season event (A3.2 (i)), with the drift variance;
- shared scouting summaries (defense/feeding quality only, labelled `scouted`);
- the season scoring configuration and its GameSpec, when they exist (embedded, so an offline plan needs nothing
  else).

**Identity.** `snapshot_id` is the sha256 of the canonical content. Two snapshots with the same id hold the same
inputs.

**Leakage.** `validate()` refuses a snapshot with:
- a qualification row at or after `as_of`;
- a prior whose source event ended on or after the event's start date.

**Building it.**
- `build_event_snapshot(database, …)` reads the project database (read-only), using the existing ingestion: canonical
  matches and match_teams, the raw TBA breakdowns through the P5-M7 adapter, the rankings, the roster and
  team_metrics scouting.
- It never calls an external API.
- `save` and `load` write and read the file used offline; `snapshot_filename` and `latest_snapshot_path` define the
  snapshot folder the server reads (`P11A_SNAPSHOT_DIR`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml.alliance.estimator import ComponentFit, EstimatorError, EstimatorPolicy, drift_variance, fit_component

SNAPSHOT_VERSION = "p11a-snapshot-v1"
COMPONENTS = ("auto", "teleop", "endgame")


class SnapshotError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QualRow:
    match_key: str
    time: str  # ISO 8601, UTC
    color: str
    teams: tuple[int, int, int]
    auto: float
    teleop: float
    endgame: float
    fouls: float
    total: float


@dataclass
class EventSnapshot:
    event_key: str
    season: int
    start_date: str
    as_of: str
    qual_rows: list[QualRow]
    roster: list[int]
    ranks: dict[int, int] | None = None
    # team -> {source_event, end_date, auto: [m, v], ...}
    priors: dict[int, dict[str, Any]] = field(default_factory=dict)
    drift: dict[str, float | None] = field(default_factory=dict)
    scouting: dict[int, dict[str, Any]] = field(default_factory=dict)
    scoring_config: dict[str, Any] | None = None
    game_spec: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    version: str = SNAPSHOT_VERSION

    # --- identity and integrity --------------------------------------------------------------------------------

    def canonical(self) -> dict[str, Any]:
        data = asdict(self)
        data["qual_rows"] = [{**r, "teams": list(r["teams"])} for r in data["qual_rows"]]
        data["ranks"] = None if self.ranks is None else {str(k): v for k, v in sorted(self.ranks.items())}
        data["priors"] = {str(k): v for k, v in sorted(self.priors.items())}
        data["scouting"] = {str(k): v for k, v in sorted(self.scouting.items())}
        data["provenance"] = {k: v for k, v in data["provenance"].items() if k != "built_at"}
        return data

    def snapshot_id(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"),
                                         default=str).encode()).hexdigest()

    def validate(self) -> None:
        as_of = _parse_time(self.as_of)
        late = [r.match_key for r in self.qual_rows if _parse_time(r.time) >= as_of]
        if late:
            raise SnapshotError("leakage", f"{len(late)} qualification row(s) at or after as_of: {late[:3]}")
        bad = [t for t, p in self.priors.items() if str(p.get("end_date")) >= self.start_date]
        if bad:
            raise SnapshotError("leakage", f"priors from events that did not end before {self.start_date}: {bad[:3]}")
        for r in self.qual_rows:
            if len(set(r.teams)) != 3:
                raise SnapshotError("invalid_snapshot", f"{r.match_key} {r.color}: not three distinct robots")

    # --- file form (offline) ---------------------------------------------------------------------------------------

    def save(self, path: Path) -> str:
        self.validate()
        payload = {"snapshot_id": self.snapshot_id(), **self.canonical(),
                   "built_at": self.provenance.get("built_at")}
        path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        return payload["snapshot_id"]

    @classmethod
    def load(cls, path: Path) -> EventSnapshot:
        data = json.loads(path.read_text(encoding="utf-8"))
        claimed = data.pop("snapshot_id", None)
        built_at = data.pop("built_at", None)
        data["qual_rows"] = [QualRow(**{**r, "teams": tuple(r["teams"])}) for r in data["qual_rows"]]
        data["ranks"] = None if data["ranks"] is None else {int(k): v for k, v in data["ranks"].items()}
        data["priors"] = {int(k): v for k, v in data["priors"].items()}
        data["scouting"] = {int(k): v for k, v in data["scouting"].items()}
        snap = cls(**data)
        if built_at is not None:
            snap.provenance["built_at"] = built_at
        if claimed != snap.snapshot_id():
            raise SnapshotError("snapshot_integrity", "the file's content does not match its snapshot_id")
        snap.validate()
        return snap

    # --- estimation ------------------------------------------------------------------------------------------------

    def teams(self) -> list[int]:
        return sorted(set(self.roster) | {t for r in self.qual_rows for t in r.teams})

    def fit(self, policy: EstimatorPolicy = EstimatorPolicy()) -> dict[str, ComponentFit]:
        """Every component's A3 fit from this snapshot (deterministic)."""
        self.validate()
        teams = self.teams()
        rows = [list(r.teams) for r in self.qual_rows]
        out = {}
        for c in COMPONENTS:
            individual = {}
            drift = self.drift.get(c)
            if drift is not None:
                for t, p in self.priors.items():
                    if t in teams and c in p:
                        m, v = p[c]
                        individual[t] = (float(m), float(v) + float(drift))
            out[c] = fit_component(c, rows, [getattr(r, c) for r in self.qual_rows], teams, individual=individual,
                                   policy=policy)
        return out

    def mean_fouls(self) -> float | None:
        return (sum(r.fouls for r in self.qual_rows) / len(self.qual_rows)) if self.qual_rows else None


def _parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# --- the snapshot folder ---------------------------------------------------------------------------------------------


def snapshot_filename(snapshot: EventSnapshot) -> str:
    """`<event_key>__<as_of UTC, compact>__<snapshot_id[:12]>.json`: names sort by as_of within an event."""
    stamp = _parse_time(snapshot.as_of).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{snapshot.event_key}__{stamp}__{snapshot.snapshot_id()[:12]}.json"


def latest_snapshot_path(directory: str | Path, event_key: str) -> Path | None:
    """The event's newest snapshot file in `directory` (by as_of in its name), or None."""
    folder = Path(directory)
    if not folder.is_dir():
        return None
    paths = sorted(folder.glob(f"{event_key}__*.json"))
    return paths[-1] if paths else None


# --- building from the project database (read-only) ---------------------------------------------------------------

_QUAL_SQL = """
SELECT m.match_key, m.scheduled_time, r.payload_json->'score_breakdown', r.id, r.fetch_timestamp,
       r.payload_json->>'post_result_time', r.payload_json->>'actual_time'
FROM matches m
JOIN raw_source_payloads r ON r.source = 'tba' AND r.source_object_type = 'match' AND r.is_current
                          AND r.source_object_id = m.match_key
WHERE m.event_key = %s AND m.competition_level = 'qualification' AND m.scheduled_time IS NOT NULL
  AND m.scheduled_time < %s AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
ORDER BY m.scheduled_time, m.match_key
"""
_TEAMS_SQL = "SELECT match_key, alliance_color, team_number FROM match_teams WHERE match_key = ANY(%s)"
_EVENT_SQL = "SELECT season, start_date, end_date FROM events WHERE event_key = %s"
_PRIOR_EVENTS_SQL = """
SELECT DISTINCT e.event_key, e.end_date FROM events e
JOIN matches m ON m.event_key = e.event_key AND m.competition_level = 'qualification'
WHERE e.season = %s AND e.end_date < %s
"""


def result_known_at(scheduled: datetime, posted: Any, actual: Any) -> datetime:
    """When a match's result became known: TBA's post_result_time, else its actual_time (both epoch seconds in the
    raw payload), else the scheduled time. The cutoff uses this, so a delayed match never leaks into a snapshot."""
    for value in (posted, actual):
        try:
            if value not in (None, "", "null"):
                return datetime.fromtimestamp(int(float(value)), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
    return scheduled if scheduled.tzinfo else scheduled.replace(tzinfo=timezone.utc)


def qual_rows_from_database(database: Any, event_key: str, season: int, before: datetime
                            ) -> tuple[list[QualRow], list[dict[str, Any]], list[int]]:
    """(rows, exclusions, raw payload ids) for one event's qualification alliances before `before`."""
    from ml.features.score_breakdown import ScoreBreakdownSchemaError, UnsupportedSeasonError
    from ml.features.score_components import score_components

    with database.cursor() as cursor:
        cursor.execute(_QUAL_SQL, (event_key, before))
        matches = cursor.fetchall()
        cursor.execute(_TEAMS_SQL, ([m[0] for m in matches],))
        lineup: dict[tuple[str, str], list[int]] = {}
        for match_key, color, team in cursor.fetchall():
            lineup.setdefault((match_key, color), []).append(team)
    rows, exclusions, payload_ids = [], [], []
    for match_key, scheduled, breakdown, payload_id, _fetched, posted, actual in matches:
        known_at = result_known_at(scheduled, posted, actual)
        if known_at >= before:  # scheduled before the cutoff but played or posted after it (a delayed match)
            exclusions.append({"match_key": match_key, "reason": "result_posted_after_as_of",
                               "known_at": known_at.isoformat()})
            continue
        for color in ("red", "blue"):
            teams = sorted(lineup.get((match_key, color), []))
            reason = None
            if len(teams) != 3:
                reason = "not_three_robots"
            elif not isinstance(breakdown, Mapping) or color not in breakdown:
                reason = "breakdown_missing"
            if reason is None:
                try:
                    parts = score_components(season, breakdown[color])
                except (ScoreBreakdownSchemaError, UnsupportedSeasonError) as exc:
                    reason = f"breakdown_invalid: {exc}"
            if reason:
                exclusions.append({"match_key": match_key, "color": color, "reason": reason})
                continue
            rows.append(QualRow(match_key, scheduled.isoformat(), color, tuple(teams), parts.auto, parts.teleop,
                                parts.endgame, parts.fouls, parts.total))
            payload_ids.append(payload_id)
    return rows, exclusions, payload_ids


def build_event_snapshot(database: Any, event_key: str, as_of: datetime, *, policy: EstimatorPolicy = EstimatorPolicy(),
                         scoring_dir: Path | None = None) -> EventSnapshot:
    """The snapshot of one event at `as_of`, from the project database (read-only; no external call).
    UNVERIFIED on the build machine (no PostgreSQL there); see docs/phase11.md."""
    from data.human_inputs import approved_spec
    from data.rankings import read_event_ranks
    from ml.alliance.scoring_config import find_config
    from ml.playoffs.service import qualification_roster

    with database.cursor() as cursor:
        cursor.execute(_EVENT_SQL, (event_key,))
        row = cursor.fetchone()
    if row is None:
        raise SnapshotError("event_not_found", f"{event_key} is not known")
    season, start_date, _ = row
    rows, exclusions, payload_ids = qual_rows_from_database(database, event_key, season, as_of)
    landed = read_event_ranks(database, event_key)
    if landed is not None and not (isinstance(landed[1], datetime) and landed[1] <= as_of):
        exclusions.append({"what": "ranks", "reason": "the landed ranking was fetched after as_of (or its fetch time "
                                                      "is unknown), so it is left out (leakage)"})
        landed = None  # only a ranking fetched at or before as_of is in the snapshot
    priors, history = {}, []
    with database.cursor() as cursor:
        cursor.execute(_PRIOR_EVENTS_SQL, (season, start_date))
        earlier = sorted(cursor.fetchall(), key=lambda r: r[1])
    for prior_key, end_date in earlier:  # each earlier event's own qualification rows only
        prior_rows, _, _ = qual_rows_from_database(database, prior_key, season,
                                                   datetime.combine(end_date, datetime.max.time(), timezone.utc))
        if len(prior_rows) < 12:
            continue
        teams = sorted({t for r in prior_rows for t in r.teams})
        entry = {"event": prior_key, "end_date": end_date.isoformat()}
        for c in COMPONENTS:
            try:
                fit = fit_component(c, [list(r.teams) for r in prior_rows], [getattr(r, c) for r in prior_rows],
                                    teams, policy=policy)
            except EstimatorError:
                continue
            entry[c] = {t: (float(fit.mean[i]), float(fit.cov[i, i])) for i, t in enumerate(fit.teams)}
        history.append(entry)
    for entry in history:  # latest earlier event per team wins (history is in end-date order)
        for t in {t for c in COMPONENTS if c in entry for t in entry[c]}:
            priors[t] = {"source_event": entry["event"], "end_date": entry["end_date"],
                         **{c: list(entry[c][t]) for c in COMPONENTS if c in entry and t in entry[c]}}
    drift = {}
    for c in COMPONENTS:
        pairs, last = [], {}
        for entry in history:
            for t, est in entry.get(c, {}).items():
                if t in last:
                    pairs.append((*last[t], *est))
                last[t] = est
        drift[c] = drift_variance(pairs)
    scouting, scouting_excluded = _scouting(database, event_key, as_of)
    exclusions.extend(scouting_excluded)
    config = find_config(season, scoring_dir)
    spec = approved_spec(database, season)
    roster = qualification_roster(database, event_key)
    return EventSnapshot(
        event_key=event_key, season=season, start_date=start_date.isoformat(), as_of=as_of.isoformat(),
        qual_rows=rows, roster=roster, ranks=None if landed is None else dict(landed[0]),
        priors={t: p for t, p in priors.items() if t in set(roster) | {x for r in rows for x in r.teams}},
        drift=drift, scouting=scouting,
        scoring_config=None if config is None else config.model_dump(mode="json"),
        game_spec=None if spec is None else spec.model_dump(mode="json"),
        provenance={"source": "project database (canonical TBA ingestion; P5-M7 adapter)",
                    "raw_payload_ids": payload_ids, "ranking_fetched_at": None if landed is None else str(landed[1]),
                    "prior_events": [e["event"] for e in history], "built_at": datetime.now(timezone.utc).isoformat()},
        exclusions=exclusions)


def _scouting(database: Any, event_key: str, as_of: datetime) -> tuple[dict[int, dict[str, Any]], list[dict]]:
    """Shared scouting summaries from team_metrics (defense/feeding quality only; `scouted`), and exclusions.

    team_metrics is a current-state table, so a summary computed after `as_of` may include later observations; it is
    left out (leakage) and recorded. A database without them gives none, reported as absent, never invented."""
    import psycopg

    try:
        with database.cursor() as cursor:
            cursor.execute("SELECT team_number, defense_score, defense_observation_count, feeding_score, "
                           "feeding_observation_count, computed_at FROM team_metrics WHERE event_key = %s",
                           (event_key,))
            rows = cursor.fetchall()
    except psycopg.Error:
        return {}, []
    kept, exclusions = {}, []
    for t, d, dn, f, fn, computed_at in rows:
        if not (isinstance(computed_at, datetime) and computed_at <= as_of):
            exclusions.append({"what": "scouting", "team_number": t,
                               "reason": "the scouting summary was computed after as_of (or at an unknown time)"})
            continue
        kept[t] = {"defense": d, "defense_n": dn, "feeding": f, "feeding_n": fn, "kind": "scouted",
                   "computed_at": computed_at.isoformat()}
    return kept, exclusions


__all__ = ["COMPONENTS", "EventSnapshot", "QualRow", "SNAPSHOT_VERSION", "SnapshotError", "build_event_snapshot",
           "latest_snapshot_path", "qual_rows_from_database", "result_known_at", "snapshot_filename"]
