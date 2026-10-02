"""Production loader for the D18 EPA source configuration (Statbotics primary, STRATAI fallback).

D18 (.agent/phase4/D18_SOURCE_SPEC.md, frozen at ec1b0af) is the EPA source every
Phase 4 result of record was evaluated on. ``load_d18_provider`` builds the same
``StatboticsPrimaryEpa`` provider, with the same snapshot-integrity (S1) checks,
that scripts/run_phase4_d18.load_source built for the evaluation. That function is
kept byte-identical as the evaluation record (its runner pins it by AST), so this is
the production copy; tests/test_d18_production_source.py asserts on the real
snapshot that both produce identical provider state and identical lookups.

It refuses to load -- never silently degrades -- if the snapshot's raw files do not
match their manifest checksums, if ``team_event_stats`` no longer matches the
snapshot fingerprint (for example after a live Statbotics sync), or if the STRATAI
fallback chain does not describe this database. A refreshed Statbotics snapshot is
taken with scripts/sync_statbotics_snapshot.py and configured explicitly.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from database.connection import Database
from ml.ratings.statbotics_primary import RULE_A1_SEASON_END, StatboticsPrimaryEpa, StatboticsTeamEvent

D18_EPA_SOURCE = "d18_statbotics_primary"

# The same table read and canonicalization scripts/sync_statbotics_snapshot.py fingerprints.
TEAM_EVENT_STATS_SQL = """
SELECT team_number, event_key, season, epa_total, epa_auto, epa_teleop, epa_endgame, matches_played
FROM team_event_stats WHERE season = ANY(%(seasons)s) ORDER BY event_key, team_number
"""
# The D18 runner's definition of a completed match for T_end / T_w1.
EVENT_LAST_MATCH_SQL = """
SELECT m.event_key, e.season, MAX(m.scheduled_time)
FROM matches m JOIN events e ON e.event_key = m.event_key
WHERE e.season = ANY(%(seasons)s) AND m.scheduled_time IS NOT NULL
  AND m.score_red IS NOT NULL AND m.score_blue IS NOT NULL
GROUP BY m.event_key, e.season
"""


class D18SourceIntegrityError(RuntimeError):
    """The configured snapshot, table or fallback chain is not the verified D18 source."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def table_fingerprint(database: Database, seasons: list[int]) -> tuple[list[list[Any]], str]:
    with database.cursor() as cursor:
        cursor.execute(TEAM_EVENT_STATS_SQL, {"seasons": seasons})
        rows = [[None if v is None else (float(v) if not isinstance(v, (int, str)) else v) for v in row]
                for row in cursor.fetchall()]
    return rows, hashlib.sha256(_canonical(rows)).hexdigest()


def _qual_count(record: dict[str, Any]) -> int | None:
    return ((record.get("record") or {}).get("qual") or {}).get("count")


def load_d18_provider(database: Database, snapshot: Path, chain: Path, *,
                      strict: bool = True) -> tuple[StatboticsPrimaryEpa, dict[str, Any]]:
    """The D18 provider over a verified Statbotics snapshot plus the STRATAI fallback chain."""
    from ml.ratings.provider import StrataiPointInTimeEpa, read_team_event_facts

    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest["failures"] or manifest["events_fetched"] != manifest["events_requested"]:
        raise D18SourceIntegrityError(f"snapshot {snapshot.name} recorded failures")
    raw: dict[tuple[int, str], dict[str, Any]] = {}
    event_meta: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for entry in manifest["events"]:
        data = gzip.decompress((snapshot / entry["raw_file"]).read_bytes())
        if hashlib.sha256(data).hexdigest() != entry["raw_sha256"]:
            raise D18SourceIntegrityError(f"{entry['raw_file']} does not match its manifest sha256")
        for record in json.loads(data):
            raw[(record["team"], record["event"])] = record
            event_meta[record["event"]].add((record["status"], record["week"]))
    rows, fingerprint = table_fingerprint(database, manifest["seasons"])
    if fingerprint != manifest["team_event_stats"]["sha256"]:
        raise D18SourceIntegrityError(f"team_event_stats does not match snapshot {snapshot.name}")
    mismatched, statbotics = [], {}
    for team, event_key, season, total, auto, teleop, endgame, played in rows:
        record = raw.get((team, event_key))
        published = None if record is None else (record.get("epa") or {}).get("total_points")
        if record is None or (published is None) != (total is None) or (
                total is not None and abs(float(published) - total) > 1e-9):
            mismatched.append([team, event_key, total, published])
            continue
        statbotics[(team, event_key)] = StatboticsTeamEvent(season, total, auto, teleop, endgame, played,
                                                            _qual_count(record))
    raw_only = sorted(set(raw) - set(statbotics) - {(m[0], m[1]) for m in mismatched})
    mixed = sorted(e for e, meta in event_meta.items() if len(meta) != 1)
    if mismatched or raw_only or mixed:
        raise D18SourceIntegrityError(
            f"S1 failed: {len(mismatched)} raw/table mismatches {mismatched[:5]}, "
            f"{len(raw_only)} raw records with no table row, events with mixed status/week {mixed}")

    with database.cursor() as cursor:
        cursor.execute(EVENT_LAST_MATCH_SQL, {"seasons": manifest["seasons"]})
        last_match = cursor.fetchall()
    season_end: dict[int, datetime] = {}
    week_one: dict[int, datetime] = {}
    for event_key, season, last in last_match:
        season_end[season] = max(season_end.get(season, last), last)
        if event_meta.get(event_key) == {("Completed", 1)}:
            week_one[season] = max(week_one.get(season, last), last)
    if set(week_one) != set(manifest["seasons"]) or set(season_end) != set(manifest["seasons"]):
        raise D18SourceIntegrityError(
            f"T_w1/T_end undefined for some season: {sorted(week_one)} / {sorted(season_end)}")

    fallback = StrataiPointInTimeEpa.from_chain_manifest(database, chain)
    integrity = {"raw_files_verified": len(manifest["events"]), "raw_records": len(raw), "table_rows": len(rows),
                 "team_event_stats_sha256": fingerprint, "raw_equals_table_epa_total": len(statbotics),
                 "a1_team_events": sum(v.rule == RULE_A1_SEASON_END for v in statbotics.values()),
                 "invalid_team_events": sum(not v.valid for v in statbotics.values()), "ok": True}
    info = {"snapshot": snapshot.name, "endpoint": manifest["base_url"] + manifest["endpoint"],
            "params_template": manifest["params_template"], "schema_version": manifest["schema_version"],
            "retrieved": [manifest["started_at"], manifest["finished_at"]],
            "snapshot_producing_commit": manifest["producing_commit"], "team_event_stats_sha256": fingerprint}
    provider = StatboticsPrimaryEpa(statbotics, read_team_event_facts(database), season_end, week_one, fallback,
                                    provenance_info=info, strict=strict)
    return provider, integrity
