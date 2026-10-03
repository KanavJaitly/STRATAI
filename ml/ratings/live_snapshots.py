"""P5-M2 live EPA snapshot log (.agent/phase5/LIVE_EPA_REFRESH_DESIGN.md §1, §2, §4).

A *snapshot* is a manifest: event_key -> (raw file, raw sha256, retrieved_at,
per-team processed flags). Each refresh writes a new manifest equal to its parent
plus the events it changed (copy-on-write). ``snapshot_id`` is the sha256 of the
canonical manifest. Manifests form an append-only log, each naming its parent, and
the frozen D18 snapshot (statbotics_snapshot_20261001T220423Z) is the log's root.
Nothing is deleted or overwritten.

Layout of a log directory:

    manifests/<snapshot_id>.json   one manifest per snapshot (write-once)
    raw/<event>_<sha16>.json.gz    each refresh fetch, canonical JSON, gzip
    log.jsonl                      append-only: snapshot and refresh entries

Raw files of the root stay in the D18 snapshot directory and are referenced as
``root:raw/<event>.json.gz``; files fetched by refreshes as ``log:raw/...``.

**Processed** (§1) is per team-event: the event's records all have status
"Completed" and the team's record exists. A team with no record (e.g. 4744 at
2026isde2) is unprocessed. Values are always read from the raw files, normalized
with the Phase 2 normalizer, never from the mutable ``team_event_stats`` table.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from data.staging.normalizer import normalize_statbotics_team_event_stats
from ml.ratings.statbotics_primary import StatboticsTeamEvent

MANIFEST_SCHEMA = "p5-live-epa-manifest-v1"
STATUS_COMPLETED = "Completed"
ROOT_PREFIX, LOG_PREFIX = "root:", "log:"


class SnapshotIntegrityError(RuntimeError):
    """A raw file, manifest or log entry does not match what was recorded."""


def canonical(value: Any) -> bytes:
    """The canonical JSON bytes every D18 and Phase 5 fingerprint uses (one implementation)."""
    from ml.ratings.d18_source import _canonical

    return _canonical(value)


def snapshot_id_of(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(manifest)).hexdigest()


@dataclass(frozen=True)
class LiveRecord:
    """One Statbotics team-event record as a snapshot holds it (normalized from raw)."""

    team: int
    event_key: str
    status: str
    week: int | None
    value: StatboticsTeamEvent  # D18's value type: validity (D8) and the A1/A2 rule
    processed: bool
    retrieved_at: datetime
    raw_sha256: str


def processed_flags(records: list[dict[str, Any]]) -> dict[str, bool]:
    """§1: every record's team is processed iff all of the event's records are Completed."""
    complete = bool(records) and all(r.get("status") == STATUS_COMPLETED for r in records)
    return {str(r["team"]): complete for r in records}


def _qual_count(record: dict[str, Any]) -> int | None:
    return ((record.get("record") or {}).get("qual") or {}).get("count")


def parse_records(raw_records: list[dict[str, Any]], *, retrieved_at: datetime, raw_sha256: str,
                  flags: dict[str, bool]) -> dict[int, LiveRecord]:
    """Normalize one event's raw records exactly as Phase 2 stages them (team_event_stats)."""
    out: dict[int, LiveRecord] = {}
    for record in raw_records:
        staged = normalize_statbotics_team_event_stats(record)
        value = StatboticsTeamEvent(staged.season, staged.epa_total, staged.epa_auto, staged.epa_teleop,
                                    staged.epa_endgame, staged.matches_played, _qual_count(record))
        out[staged.team_number] = LiveRecord(staged.team_number, staged.event_key, record.get("status"),
                                             record.get("week"), value, flags.get(str(staged.team_number), False),
                                             retrieved_at, raw_sha256)
    return out


class SnapshotLog:
    """The append-only manifest log rooted at the frozen D18 snapshot."""

    def __init__(self, log_dir: Path, root_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.root_dir = Path(root_dir)
        self._events_cache: dict[tuple[str, str], dict[int, LiveRecord]] = {}

    # --- creation -----------------------------------------------------------------------------

    @classmethod
    def create_from_root(cls, log_dir: Path, root_dir: Path) -> SnapshotLog:
        """Start a log whose first manifest is the frozen D18 snapshot, sha-verified."""
        log = cls(log_dir, root_dir)
        if (log.log_dir / "log.jsonl").exists():
            raise SnapshotIntegrityError(f"{log_dir} already holds a snapshot log")
        source = json.loads((root_dir / "manifest.json").read_text(encoding="utf-8"))
        if source["failures"] or source["events_fetched"] != source["events_requested"]:
            raise SnapshotIntegrityError(f"root snapshot {root_dir.name} recorded failures")
        events = {}
        for entry in source["events"]:
            data = log._read_raw(ROOT_PREFIX + entry["raw_file"], entry["raw_sha256"])
            events[entry["event_key"]] = {"raw_file": ROOT_PREFIX + entry["raw_file"],
                                          "raw_sha256": entry["raw_sha256"],
                                          "retrieved_at": entry["retrieved_at"],
                                          "processed": processed_flags(json.loads(data))}
        manifest = {"schema": MANIFEST_SCHEMA, "parent": None, "origin": "d18_root",
                    "root_snapshot": root_dir.name, "created_at": source["finished_at"], "events": events}
        (log.log_dir / "manifests").mkdir(parents=True, exist_ok=True)
        (log.log_dir / "raw").mkdir(exist_ok=True)
        snapshot_id = log._write_manifest(manifest)
        log.append_log({"kind": "snapshot", "snapshot_id": snapshot_id, "parent": None,
                        "created_at": manifest["created_at"], "origin": "d18_root"})
        return log

    def _write_manifest(self, manifest: dict[str, Any]) -> str:
        snapshot_id = snapshot_id_of(manifest)
        path = self.log_dir / "manifests" / f"{snapshot_id}.json"
        if path.exists():
            if snapshot_id_of(json.loads(path.read_text(encoding="utf-8"))) != snapshot_id:
                raise SnapshotIntegrityError(f"{path} does not hold snapshot {snapshot_id}")
            return snapshot_id
        path.write_text(json.dumps(manifest, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        return snapshot_id

    def append_log(self, entry: dict[str, Any]) -> None:
        with (self.log_dir / "log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def write_raw(self, event_key: str, body: Any) -> tuple[str, str]:
        """Write one fetch's canonical JSON (gzip, mtime 0); returns (raw_file ref, sha256)."""
        data = canonical(body if body is not None else [])
        sha = hashlib.sha256(data).hexdigest()
        name = f"raw/{event_key}_{sha[:16]}.json.gz"
        path = self.log_dir / name
        if not path.exists():
            path.write_bytes(gzip.compress(data, mtime=0))
        return LOG_PREFIX + name, sha

    def commit_snapshot(self, parent_id: str, changed: dict[str, dict[str, Any]], created_at: datetime) -> str:
        """Copy-on-write: the parent's manifest plus the changed events; appended to the log."""
        parent = self.manifest(parent_id)
        manifest = {"schema": MANIFEST_SCHEMA, "parent": parent_id, "origin": "refresh",
                    "root_snapshot": parent["root_snapshot"], "created_at": created_at.isoformat(),
                    "events": {**parent["events"], **changed}}
        snapshot_id = self._write_manifest(manifest)
        self.append_log({"kind": "snapshot", "snapshot_id": snapshot_id, "parent": parent_id,
                         "created_at": manifest["created_at"], "origin": "refresh",
                         "changed_events": sorted(changed)})
        return snapshot_id

    # --- reading ------------------------------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        path = self.log_dir / "log.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def snapshots(self) -> list[dict[str, Any]]:
        """Snapshot entries in log order, each verified to chain to its parent."""
        out, seen = [], set()
        for entry in self.entries():
            if entry["kind"] != "snapshot":
                continue
            if entry["parent"] is not None and entry["parent"] not in seen:
                raise SnapshotIntegrityError(f"snapshot {entry['snapshot_id']} names an unknown parent")
            seen.add(entry["snapshot_id"])
            out.append(entry)
        return out

    def head(self) -> str:
        snapshots = self.snapshots()
        if not snapshots:
            raise SnapshotIntegrityError(f"{self.log_dir} holds no snapshot")
        return snapshots[-1]["snapshot_id"]

    def manifest(self, snapshot_id: str) -> dict[str, Any]:
        path = self.log_dir / "manifests" / f"{snapshot_id}.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if snapshot_id_of(manifest) != snapshot_id:
            raise SnapshotIntegrityError(f"manifest {snapshot_id} does not hash to its id")
        return manifest

    def _read_raw(self, ref: str, sha256: str) -> bytes:
        if ref.startswith(ROOT_PREFIX):
            path = self.root_dir / ref[len(ROOT_PREFIX):]
        elif ref.startswith(LOG_PREFIX):
            path = self.log_dir / ref[len(LOG_PREFIX):]
        else:
            raise SnapshotIntegrityError(f"unknown raw file reference {ref!r}")
        data = gzip.decompress(path.read_bytes())
        if hashlib.sha256(data).hexdigest() != sha256:
            raise SnapshotIntegrityError(f"{ref} does not match its recorded sha256")
        return data

    def event_records(self, entry: dict[str, Any]) -> dict[int, LiveRecord]:
        """One manifest event entry's records (sha-verified, normalized, cached by sha)."""
        key = (entry["raw_file"], entry["raw_sha256"])
        if key not in self._events_cache:
            raw = json.loads(self._read_raw(entry["raw_file"], entry["raw_sha256"]))
            self._events_cache[key] = parse_records(raw, retrieved_at=datetime.fromisoformat(entry["retrieved_at"]),
                                                    raw_sha256=entry["raw_sha256"], flags=entry["processed"])
        return self._events_cache[key]

    def records(self, snapshot_id: str) -> dict[tuple[int, str], LiveRecord]:
        out: dict[tuple[int, str], LiveRecord] = {}
        for event_key, entry in self.manifest(snapshot_id)["events"].items():
            for team, record in self.event_records(entry).items():
                out[(team, event_key)] = record
        return out
