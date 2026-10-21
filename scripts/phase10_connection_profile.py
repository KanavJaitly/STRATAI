"""P10-M3: what the connection-per-query design costs, measured.

    python -m scripts.phase10_connection_profile --event 2024casj [--repeats 10] [--load-seconds 45]
        [--readers 1,3,6] [--out FILE]

It runs on a **disposable** database: created empty, migrated, loaded with one event's recorded public TBA payloads
read only from `stratai_test`, and dropped at the end, as in `scripts/phase10_live_sync_stress.py`. No sync runs
during the measurements, so the database state is fixed and every repetition sees the same data.

`psycopg.connect` and `psycopg.Cursor.execute` are wrapped in this process only, to count and time every connection
and every statement. Nothing in the application changes. Three parts:
1. **Microbenchmarks:**
   - a new connection plus close;
   - a new connection plus `SELECT 1`;
   - `SELECT 1` on one open connection.
2. **Per route, alone:** each route is called `--repeats` times, sequentially. For each call, its latency is split
   into connection setup, statement execution and the rest (Python), with its connection and statement counts.
3. **Under concurrent load:** for each reader count, readers call a mix of routes for `--load-seconds`. Recorded:
   - latency percentiles per route (median, p95, p99, max);
   - connections per second;
   - process CPU time against wall time (a ratio near 1.0 with several readers means the process is CPU-bound,
     i.e. serialised on the GIL);
   - sampled PostgreSQL session counts.

Limits:
- an in-process TestClient, not a network server (the stress harness's client);
- one machine and one event;
- the numbers are this machine's.

Correlation with the P10-M2 stall is not causation (`.agent/phase10/decisions/`).
"""

from __future__ import annotations

import argparse
import contextvars
import json
import os
import random
import resource
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from scripts.phase10_live_sync_stress import ISOLATED, Heartbeat, code_fingerprint, create_disposable, drop_disposable

PROFILE_VERSION = "P2"  # P2 (2026-10-21, before the P10-D1 experiment): heartbeat pauses, idle-session sample

_label: contextvars.ContextVar[str | None] = contextvars.ContextVar("p10_label", default=None)


class Probe:
    """Counts and times every psycopg connection and statement, per label (the call being measured)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.by_label: dict[str, dict[str, float]] = {}
        self.total_connects = 0
        self._connect = psycopg.connect
        self._execute = psycopg.Cursor.execute

    def _add(self, kind: str, seconds: float) -> None:
        """kind is "connect" or "statement"."""
        label = _label.get()
        with self.lock:
            if kind == "connect":
                self.total_connects += 1
            if label is None:
                return
            entry = self.by_label.setdefault(label, {"connects": 0, "connect_s": 0.0, "statements": 0,
                                                     "statement_s": 0.0})
            entry[f"{kind}s"] += 1
            entry[f"{kind}_s"] += seconds

    def install(self) -> None:
        probe = self
        real_connect, real_execute = self._connect, self._execute

        def connect(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                return real_connect(*args, **kwargs)
            finally:
                probe._add("connect", time.perf_counter() - started)

        def execute(self, *args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                return real_execute(self, *args, **kwargs)
            finally:
                probe._add("statement", time.perf_counter() - started)

        psycopg.connect = connect
        psycopg.Cursor.execute = execute

    def uninstall(self) -> None:
        psycopg.connect = self._connect
        psycopg.Cursor.execute = self._execute

    def take(self, label: str) -> dict[str, float]:
        with self.lock:
            return self.by_label.pop(label, {"connects": 0, "connect_s": 0.0, "statements": 0, "statement_s": 0.0})


def percentiles(values: list[float]) -> dict[str, float]:
    values = sorted(values)
    def at(q: float) -> float:
        return round(values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))], 4)
    return {"n": len(values), "median": round(statistics.median(values), 4), "p95": at(0.95), "p99": at(0.99),
            "max": round(values[-1], 4)}


def microbench(url: str, n: int) -> dict[str, Any]:
    connect_close, connect_query = [], []
    for _ in range(n):
        started = time.perf_counter()
        psycopg.connect(url, connect_timeout=10).close()
        connect_close.append(time.perf_counter() - started)
    for _ in range(n):
        started = time.perf_counter()
        with psycopg.connect(url, connect_timeout=10) as conn:
            conn.execute("SELECT 1").fetchone()
        connect_query.append(time.perf_counter() - started)
    reused = []
    with psycopg.connect(url, connect_timeout=10) as conn:
        for _ in range(n):
            started = time.perf_counter()
            conn.execute("SELECT 1").fetchone()
            reused.append(time.perf_counter() - started)
    return {"connect_close_s": percentiles(connect_close), "connect_select1_close_s": percentiles(connect_query),
            "select1_on_open_connection_s": percentiles(reused)}


def routes(event: str, teams: list[int], match: str) -> dict[str, str]:
    return {"metrics": f"/teams/{teams[0]}/events/{event}/metrics",
            "strength": f"/teams/{teams[0]}/events/{event}/strength",
            "event_matches": f"/events/{event}/matches", "event_teams": f"/events/{event}/teams",
            "analysis": f"/events/{event}/analysis",
            "report": f"/matches/{match}/pre-match-report", "briefing": f"/matches/{match}/briefing"}


def per_route(client, probe: Probe, paths: dict[str, str], repeats: int) -> dict[str, Any]:
    out = {}
    for name, path in paths.items():
        rows = []
        for i in range(repeats):
            label = f"{name}#{i}"
            token = _label.set(label)
            started = time.perf_counter()
            try:
                status = client.get(path).status_code
            finally:
                _label.reset(token)
            total = time.perf_counter() - started
            counts = probe.take(label)
            rows.append({"status": status, "total_s": total, **counts})
        out[name] = {
            "statuses": sorted({r["status"] for r in rows}),
            "total_s": percentiles([r["total_s"] for r in rows]),
            "connects_per_call": statistics.median(r["connects"] for r in rows),
            "statements_per_call": statistics.median(r["statements"] for r in rows),
            "connect_s_per_call": round(statistics.median(r["connect_s"] for r in rows), 4),
            "statement_s_per_call": round(statistics.median(r["statement_s"] for r in rows), 4),
            "other_s_per_call": round(statistics.median(r["total_s"] - r["connect_s"] - r["statement_s"]
                                                        for r in rows), 4),
        }
    return out


def under_load(client, probe: Probe, paths: dict[str, str], readers: int, seconds: float, url: str) -> dict:
    stop = threading.Event()
    lock = threading.Lock()
    latencies: dict[str, list[float]] = {name: [] for name in paths}
    statuses: dict[str, dict[str, int]] = {name: {} for name in paths}
    sessions: list[int] = []

    def reader(index: int) -> None:
        rng = random.Random(index)
        names = list(paths)
        while not stop.is_set():
            name = rng.choice(names)
            started = time.perf_counter()
            status = client.get(paths[name]).status_code
            with lock:
                latencies[name].append(time.perf_counter() - started)
                statuses[name][str(status)] = statuses[name].get(str(status), 0) + 1

    def sampler() -> None:
        with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
            while not stop.wait(1.0):
                sessions.append(conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = "
                                             "current_database()").fetchone()[0])

    connects_before = probe.total_connects
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    wall_started = time.perf_counter()
    threads = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(readers)]
    threads.append(threading.Thread(target=sampler, daemon=True))
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    stop.set()
    for thread in threads:
        thread.join(timeout=300)
    wall = time.perf_counter() - wall_started
    time.sleep(2.0)  # let closed connections end on the server, then count what is left (P10-D1 §5 criterion 4)
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        idle_after = conn.execute("SELECT count(*) - 1 FROM pg_stat_activity WHERE datname = current_database()"
                                  ).fetchone()[0]
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (cpu_after.ru_utime - cpu_before.ru_utime) + (cpu_after.ru_stime - cpu_before.ru_stime)
    connects = probe.total_connects - connects_before
    return {"readers": readers, "wall_s": round(wall, 1),
            "requests": sum(len(v) for v in latencies.values()),
            "latency_s": {name: percentiles(v) for name, v in latencies.items() if v},
            "statuses": statuses,
            "connections_per_s": round(connects / wall, 1),
            "process_cpu_over_wall": round(cpu / wall, 2),
            "pg_sessions_sampled": {"max": max(sessions) if sessions else None,
                                    "median": statistics.median(sessions) if sessions else None},
            "pg_sessions_after_load_excluding_probe": idle_after,
            "threads_still_alive": sum(t.is_alive() for t in threads)}


def profile(source_url: str, event: str, repeats: int, load_seconds: float, reader_counts: list[int]) -> dict:
    from fastapi.testclient import TestClient

    from api import create_app
    from data.config import Settings
    from data.orchestrator import after_watch_sync, sync_event
    from data.replay import ReplayTBAClient, load_recorded_event
    from database.connection import Database, DatabaseConfig
    from database.migrate import run_migrations
    from database.readonly import ReadOnlySessionDatabase

    source = ReadOnlySessionDatabase(DatabaseConfig(source_url))
    try:
        recorded = load_recorded_event(source, event)
    finally:
        source.close()
    teams = sorted({int(k[3:]) for m in recorded.matches.values() for a in (m.get("alliances") or {}).values()
                    for k in a.get("team_keys") or []})
    quals = sorted((m.get("time") or 0, k) for k, m in recorded.matches.items() if m.get("comp_level") == "qm")
    name, url = create_disposable(source_url)
    report: dict[str, Any] = {"profile_version": PROFILE_VERSION, "code_sha256": code_fingerprint(),
                              "disposable_database": name, "event": event, "teams": len(teams)}
    probe = Probe()
    heartbeat = Heartbeat()
    heartbeat.start()
    try:
        settings = Settings(database_url=url, api_prefix="")
        run_migrations(settings)
        database = Database(DatabaseConfig(url))
        tba = ReplayTBAClient({event: recorded})
        tba.complete(list(recorded.matches))  # the whole event, played: a fixed state for every measurement
        result = sync_event(event, database=database, tba=tba)
        after_watch_sync(database, event, result, settings=settings)
        report["microbench"] = microbench(url, 200)
        probe.install()
        match = quals[len(quals) // 2][1]
        paths = routes(event, teams, match)
        with TestClient(create_app(settings)) as client:
            for path in paths.values():  # warm-up: first-use loads (EPA source, scales) are not measured
                client.get(path)
            report["per_route_alone"] = per_route(client, probe, paths, repeats)
            report["under_load"] = [under_load(client, probe, paths, readers, load_seconds, url)
                                    for readers in reader_counts]
    finally:
        probe.uninstall()
        drop_disposable(source_url, name)
        report["disposable_dropped"] = True
        heartbeat.done.set()
    report["pauses"] = heartbeat.pauses
    report["environment_invalid"] = bool(heartbeat.pauses)  # a paused run is not evidence (P10-R1)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--event", default="2024casj")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--load-seconds", type=float, default=45)
    parser.add_argument("--readers", default="1,3,6")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    from data.config import Settings

    source_url = str(Settings().database_url)
    if not ISOLATED.search(source_url):
        raise SystemExit("refusing: DATABASE_URL must point at the isolated stratai_test database (the source)")
    started = time.monotonic()
    report = {"captured_at": datetime.now(timezone.utc).isoformat(), "epa_source": os.environ.get("EPA_SOURCE"),
              "cpus": os.cpu_count(),
              **profile(source_url, args.event, args.repeats, args.load_seconds,
                        [int(x) for x in args.readers.split(",")])}
    report["elapsed_s"] = round(time.monotonic() - started, 1)
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
