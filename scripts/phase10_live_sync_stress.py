"""P10-M2: a simulated live event under concurrent read load (P10-DM3: "the system survives a simulated event
without stale data or crashes").

    python -m scripts.phase10_live_sync_stress --event 2024casj [--matches-per-poll 6] [--readers 6]
        [--budget-minutes 20] [--out FILE]

The harness:
1. Reads one event's recorded TBA payloads, read-only, from the isolated `stratai_test` database in `DATABASE_URL`.
   These are public TBA data; the serving database is never read, and `scripts/phase5_isolated_db.py` (which clones
   it) is never used (P10-Q5).
2. Creates a **disposable, empty** database `stratai_test_p10_<pid>`, applies every migration, and drops it at the
   end, even on failure.
3. Plays the event: poll by poll, the next qualification matches (in schedule order) complete, then the playoff
   matches. Each poll runs the production `data.orchestrator.sync_event` with only HTTP replaced by
   `data.replay.ReplayTBAClient`, then `after_watch_sync`: exactly what `--watch` does after a poll.
4. Meanwhile N reader threads call the served views on the same database through the real API app, as fast as
   they can:
   - team metrics and strength;
   - event matches and teams;
   - event analysis;
   - the pre-match report and the briefing for the next match.
5. After every poll it checks, for every team at the event, that the served metrics and strength match **an
   independent recomputation from the recorded payloads**: the team's alliance scores in exactly the matches
   completed so far. A mismatch is stale data, or look-ahead if the served count exceeds the completed count.

It fails on any 5xx, any crash, any stale or look-ahead value, or any poll error. Model-backed routes answer their
declared `model_not_loaded` refusals here (no models locally), which counts as surviving, not as a success of the
model path. It stops, reporting partial results, when the time budget runs out (CLAUDE.md, 45 minutes at most).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

ISOLATED = re.compile(r"/stratai_test(?:_[a-z0-9_]+)?$")
DEFAULT_BUDGET_MINUTES = 20
DEFAULT_STALL_SECONDS = 120
# H4 (2026-10-21, after review P10-R1): pause detection, self-describing reports, error codes, a stricter verdict.
HARNESS_VERSION = "H4.1"  # H4.1: the summary is taken after the readers are joined; next match fix
PAUSE_GAP_SECONDS = 5.0  # a heartbeat late by more than this means the process (or its VM) was not running
VIEWS = ("metrics", "strength", "event_matches", "event_teams", "analysis", "report", "briefing")
FINGERPRINTED = ("scripts/phase10_live_sync_stress.py", "database/connection.py", "api/dependencies.py",
                 "ml/features/assembler.py",
                 "ml/views/strength.py", "ml/views/event_analysis.py", "ml/views/pre_match_report.py",
                 "data/orchestrator.py", "data/replay.py")


def code_fingerprint() -> str:
    """sha256 over the files that decide what a run measures, so each report says which code produced it."""
    import hashlib

    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in FINGERPRINTED:
        digest.update(name.encode() + b"\0" + (root / name).read_bytes())
    return digest.hexdigest()


class Heartbeat(threading.Thread):
    """Ticks once a second and records every gap. Review P10-R1 found the three 2026-10-20/21 "stalls" were the
    whole VM suspended (kernel log: maitred suspend/set-time). A suspended run is not evidence either way, so a gap
    marks the run `environment_invalid` instead of counting it as a pass or an application failure."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.done = threading.Event()
        self.pauses: list[dict[str, Any]] = []

    def run(self) -> None:
        wall, mono = time.time(), time.monotonic()
        while not self.done.wait(1.0):
            now_wall, now_mono = time.time(), time.monotonic()
            gap = max(now_wall - wall, now_mono - mono) - 1.0
            if gap > PAUSE_GAP_SECONDS:
                self.pauses.append({"from_utc": datetime.fromtimestamp(wall, timezone.utc).isoformat(),
                                    "to_utc": datetime.fromtimestamp(now_wall, timezone.utc).isoformat(),
                                    "wall_gap_s": round(now_wall - wall, 1), "monotonic_gap_s": round(now_mono - mono, 1)})
            wall, mono = now_wall, now_mono


class InFlight:
    """What each thread is doing and since when, for the stall watchdog."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: dict[int, tuple[str, float]] = {}

    def start(self, label: str) -> None:
        with self.lock:
            self.calls[threading.get_ident()] = (label, time.monotonic())

    def end(self) -> None:
        with self.lock:
            self.calls.pop(threading.get_ident(), None)

    def oldest(self) -> tuple[str, float] | None:
        with self.lock:
            if not self.calls:
                return None
            label, since = min(self.calls.values(), key=lambda c: c[1])
            return label, time.monotonic() - since


def stall_diagnostics(url: str) -> dict[str, Any]:
    """Every thread's Python stack (sys._current_frames: safe, unlike faulthandler's timer dump, which crashed the
    process twice on 2026-10-20) and the disposable database's sessions and ungranted locks."""
    stacks = {str(tid): traceback.format_stack(frame) for tid, frame in sys._current_frames().items()}  # full
    sessions: Any
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            sessions = [list(map(str, row)) for row in conn.execute(
                "SELECT pid, state, wait_event_type, wait_event, now() - xact_start, left(query, 160) "
                "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()").fetchall()]
            sessions.append(["ungranted locks"] + [str(r) for r in conn.execute(
                "SELECT pid, locktype, mode, relation::regclass FROM pg_locks WHERE NOT granted").fetchall()])
    except Exception as exc:
        sessions = f"unavailable: {type(exc).__name__}"
    return {"stacks": stacks, "database_sessions": sessions}


class Watchdog(threading.Thread):
    """Declares a stall when any request or poll has run longer than `stall_seconds`. It then records diagnostics
    and force-drops the disposable database, which breaks every stuck database wait, so the run ends and reports
    instead of hanging."""

    def __init__(self, inflight: InFlight, url: str, source_url: str, name: str, stall_seconds: float,
                 heartbeat: Heartbeat) -> None:
        super().__init__(daemon=True)
        self.inflight, self.url, self.source_url, self.name = inflight, url, source_url, name
        self.heartbeat = heartbeat
        self.stall_seconds = stall_seconds
        self.done = threading.Event()
        self.stall: dict[str, Any] | None = None

    def run(self) -> None:
        while not self.done.wait(5):
            oldest = self.inflight.oldest()
            if oldest and oldest[1] > self.stall_seconds:
                self.stall = {"call": oldest[0], "seconds": round(oldest[1], 1),
                              "at_utc": datetime.now(timezone.utc).isoformat(),
                              "pauses_so_far": list(self.heartbeat.pauses), **stall_diagnostics(self.url)}
                drop_disposable(self.source_url, self.name)
                return


def _with_db(url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", f"/{name}", url)


def create_disposable(source_url: str) -> tuple[str, str]:
    name = f"stratai_test_p10_{os.getpid()}"
    admin = _with_db(source_url, "postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name, _with_db(source_url, name)


def drop_disposable(source_url: str, name: str) -> None:
    if not name.startswith("stratai_test_p10_"):  # never anything else
        raise ValueError(name)
    admin = _with_db(source_url, "postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def expected_scoring(recorded, completed: set[str]) -> dict[int, list[int]]:
    """Independent of the pipeline: each team's own alliance scores in the completed matches, from the payloads."""
    scores: dict[int, list[int]] = {}
    for key in completed:
        payload = recorded.matches[key]
        for color, alliance in (payload.get("alliances") or {}).items():
            for team_key in alliance.get("team_keys") or []:
                scores.setdefault(int(team_key[3:]), []).append(int(alliance["score"]))
    return scores


def poll_order(recorded) -> list[str]:
    def key(item):
        match_key, payload = item
        return (payload.get("comp_level") != "qm", payload.get("time") or 0, match_key)
    return [k for k, _ in sorted(recorded.matches.items(), key=key)]


class Readers:
    """Reader threads hammering the served views; each response's status and latency is recorded."""

    def __init__(self, app, event: str, teams: list[int], count: int, inflight: InFlight) -> None:
        from fastapi.testclient import TestClient

        self.inflight = inflight
        self.client = TestClient(app)
        self.event, self.teams, self.count = event, teams, count
        self.next_match: str | None = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.results: list[tuple[str, int, str | None, float]] = []
        self.crashes: list[str] = []
        self.threads = [threading.Thread(target=self._run, args=(i,), daemon=True) for i in range(count)]

    def _urls(self, rng: random.Random) -> list[tuple[str, str]]:
        team = rng.choice(self.teams)
        urls = [("metrics", f"/teams/{team}/events/{self.event}/metrics"),
                ("strength", f"/teams/{team}/events/{self.event}/strength"),
                ("event_matches", f"/events/{self.event}/matches"),
                ("event_teams", f"/events/{self.event}/teams"),
                ("analysis", f"/events/{self.event}/analysis")]
        if self.next_match:
            urls += [("report", f"/matches/{self.next_match}/pre-match-report"),
                     ("briefing", f"/matches/{self.next_match}/briefing")]
        return urls

    def _run(self, index: int) -> None:
        rng = random.Random(index)
        while not self.stop.is_set():
            name, url = rng.choice(self._urls(rng))
            started = time.monotonic()
            self.inflight.start(name)
            try:
                response = self.client.get(url)
                status = response.status_code
                code = _error_code(response) if status >= 400 else None
            except Exception as exc:  # a crash in the app surfaces here
                with self.lock:
                    self.crashes.append(f"{name}: {type(exc).__name__}")
                continue
            finally:
                self.inflight.end()
            with self.lock:
                self.results.append((name, status, code, time.monotonic() - started))

    def __enter__(self) -> "Readers":
        self.client.__enter__()
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=120)
        self.still_alive = sum(thread.is_alive() for thread in self.threads)
        self.client.__exit__(*exc)

    def summary(self) -> dict[str, Any]:
        by_name: dict[str, dict[str, Any]] = {}
        for name, status, code, seconds in self.results:
            entry = by_name.setdefault(name, {"calls": 0, "statuses": {}, "seconds": [], "ok_seconds": []})
            entry["calls"] += 1
            label = f"{status} {code}" if code else str(status)  # a refusal is told apart from a wrong 404
            entry["statuses"][label] = entry["statuses"].get(label, 0) + 1
            entry["seconds"].append(seconds)
            if status == 200:
                entry["ok_seconds"].append(seconds)
        for entry in by_name.values():
            entry["latency_s"] = _percentiles(entry.pop("seconds"))
            entry["latency_s_200_only"] = _percentiles(entry.pop("ok_seconds"))  # real work, without refusals
        return {"calls": len(self.results), "by_view": by_name, "crashes": self.crashes,
                "server_errors": sum(1 for _, status, _, _ in self.results if status >= 500),
                "reader_threads_still_alive": getattr(self, "still_alive", None)}


def _percentiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    values = sorted(values)
    return {"n": len(values), "median": round(statistics.median(values), 3),
            "p95": round(values[int(0.95 * (len(values) - 1))], 3), "max": round(values[-1], 3)}


def _error_code(response) -> str | None:
    try:
        return response.json().get("error", {}).get("code")
    except Exception:
        return "unparseable"


def check_served(client, event: str, expected: dict[int, list[int]], teams: list[int]) -> list[str]:
    """Stale or look-ahead values: the served metrics and strength against the independent recomputation, read
    after the poll (while nothing writes). Any 5xx here is a problem too (it was not counted before H4)."""
    problems = []
    for team in teams:
        scores = expected.get(team, [])
        metrics = client.get(f"/teams/{team}/events/{event}/metrics")
        if metrics.status_code >= 500:
            problems.append(f"{team}: metrics {metrics.status_code}")
            continue
        if not scores:
            if metrics.status_code == 200 and metrics.json()["scoring"]["matches_used"]:
                problems.append(f"{team}: metrics count matches before any completed")
            continue
        if metrics.status_code != 200:
            problems.append(f"{team}: metrics {metrics.status_code}")
            continue
        scoring = metrics.json()["scoring"]
        if scoring["matches_used"] != len(scores):
            kind = "look-ahead" if scoring["matches_used"] > len(scores) else "stale"
            problems.append(f"{team}: metrics {kind} (served {scoring['matches_used']}, completed {len(scores)})")
        elif abs((scoring["average_score"] or 0) - statistics.mean(scores)) > 1e-9:
            problems.append(f"{team}: metrics average {scoring['average_score']} != {statistics.mean(scores)}")
        strength = client.get(f"/teams/{team}/events/{event}/strength")
        if strength.status_code == 200:
            # average_score.n is the matches used (played, scored); matches_considered deliberately counts every
            # match scheduled before as_of, played or not (it feeds reliability), so it is not compared.
            served = strength.json()["strength"]["scoring"]["average_score"]
            if served["n"] != len(scores):
                kind = "look-ahead" if served["n"] > len(scores) else "stale"
                problems.append(f"{team}: strength {kind} (uses {served['n']}, completed {len(scores)})")
            elif abs((served["value"] or 0) - statistics.mean(scores)) > 1e-9:
                problems.append(f"{team}: strength average {served['value']} != {statistics.mean(scores)}")
        else:  # the team has completed matches, so its strength view must be served
            problems.append(f"{team}: strength {strength.status_code} {_error_code(strength)}")
    return problems


def simulate(source_url: str, event: str, matches_per_poll: int, readers: int, budget_seconds: float,
             stall_seconds: float = DEFAULT_STALL_SECONDS) -> dict:
    from api import create_app
    from data.config import Settings
    from data.orchestrator import after_watch_sync, sync_event
    from data.replay import ReplayTBAClient, load_recorded_event
    from database.connection import Database, DatabaseConfig
    from database.migrate import run_migrations
    from database.readonly import ReadOnlySessionDatabase

    started = time.monotonic()
    source = ReadOnlySessionDatabase(DatabaseConfig(source_url))
    try:
        recorded = load_recorded_event(source, event)
    finally:
        source.close()
    order = poll_order(recorded)
    teams = sorted({int(k[3:]) for m in recorded.matches.values() for a in (m.get("alliances") or {}).values()
                    for k in a.get("team_keys") or []})
    name, url = create_disposable(source_url)
    report: dict[str, Any] = {"harness_version": HARNESS_VERSION, "code_sha256": code_fingerprint(),
                              "config": {"matches_per_poll": matches_per_poll, "readers": readers,
                                         "budget_s": budget_seconds, "stall_s": stall_seconds},
                              "disposable_database": name, "event": event, "matches": len(order), "teams": len(teams),
                              "matches_per_poll": matches_per_poll, "readers": readers, "polls": []}
    heartbeat = Heartbeat()
    heartbeat.start()
    try:
        settings = Settings(database_url=url, api_prefix="")
        run_migrations(settings)
        database = Database(DatabaseConfig(url))
        tba = ReplayTBAClient({event: recorded})
        app = create_app(settings)
        completed: set[str] = set()
        first = sync_event(event, database=database, tba=tba)  # the schedule, before any match is played
        after_watch_sync(database, event, first, settings=settings)
        inflight = InFlight()
        watchdog = Watchdog(inflight, url, source_url, name, stall_seconds, heartbeat)
        watchdog.start()
        with Readers(app, event, teams, readers, inflight) as load:
            for start in range(0, len(order), matches_per_poll):
                if time.monotonic() - started > budget_seconds:
                    report["stopped_by_time_budget"] = True
                    break
                if watchdog.stall is not None:
                    break
                batch = order[start:start + matches_per_poll]
                tba.complete(batch)
                completed.update(batch)
                # The report and briefing target the next scheduled qualification match. A playoff match does not
                # exist until it is played (its 404 is correct but tells nothing), so after the quals the last
                # completed match is used instead (H4.1).
                quals_left = [k for k in order if k not in completed and recorded.matches[k].get("comp_level") == "qm"]
                load.next_match = quals_left[0] if quals_left else batch[-1]
                poll_started = time.monotonic()
                inflight.start(f"poll {len(completed)}")
                try:
                    result = sync_event(event, database=database, tba=tba)
                    after_watch_sync(database, event, result, settings=settings)
                    error = None
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:300]
                finally:
                    inflight.end()
                poll_seconds = round(time.monotonic() - poll_started, 3)
                problems = [] if error else check_served(load.client, event, expected_scoring(recorded, completed),
                                                         teams)
                report["polls"].append({"completed": len(completed), "poll_seconds": poll_seconds, "error": error,
                                        "problems": problems[:20], "problem_count": len(problems),
                                        "ended_utc": datetime.now(timezone.utc).isoformat()})
            # an idle re-poll after the last match must load nothing and change nothing (no churn)
            if watchdog.stall is None:
                again = sync_event(event, database=database, tba=tba)
                report["idle_repoll_records_loaded"] = again.records_loaded
        report["load"] = load.summary()  # after the readers are joined (H4.1: before, still_alive was never set)
        watchdog.done.set()
        report["stall"] = watchdog.stall
    finally:
        drop_disposable(source_url, name)
        report["disposable_dropped"] = True
        heartbeat.done.set()
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    report["pauses"] = heartbeat.pauses
    report.update(verdict(report, len(order)))
    return report


def verdict(report: dict[str, Any], matches: int) -> dict[str, Any]:
    """`outcome` is pass, fail or environment_invalid; `ok` is outcome == pass. A run with any heartbeat gap is
    environment_invalid whatever else happened: it is not counted as a pass, and its failures (stall, budget, errors
    from the watchdog's forced drop) are not counted as application failures. `failures` names every reason."""
    polls, load = report["polls"], report.get("load") or {}
    failures = []
    if not polls or polls[-1]["completed"] != matches:
        failures.append("not every match completed")
    if report.get("stopped_by_time_budget"):
        failures.append("time budget")
    if report.get("stall"):
        failures.append(f"stall: {report['stall']['call']} {report['stall']['seconds']} s")
    if any(p["error"] for p in polls):
        failures.append("poll error")
    if any(p["problem_count"] for p in polls):
        failures.append("stale, look-ahead or 5xx in the post-poll check")
    if load.get("server_errors"):
        failures.append(f"{load['server_errors']} server errors under load")
    if load.get("crashes"):
        failures.append("reader crashes")
    if not load.get("calls"):
        failures.append("no reader call completed")
    missing = [view for view in VIEWS if view not in (load.get("by_view") or {})]
    if missing:
        failures.append(f"views never exercised: {missing}")
    if load.get("reader_threads_still_alive") is None:
        failures.append("reader threads not joined before the summary")
    elif load["reader_threads_still_alive"]:
        failures.append("reader threads did not stop")
    if report.get("idle_repoll_records_loaded") != 0:
        failures.append("idle re-poll loaded records")
    outcome = "environment_invalid" if report.get("pauses") else ("fail" if failures else "pass")
    return {"outcome": outcome, "failures": failures, "ok": outcome == "pass"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--event", default="2024casj")
    parser.add_argument("--matches-per-poll", type=int, default=6)
    parser.add_argument("--readers", type=int, default=6)
    parser.add_argument("--budget-minutes", type=float, default=DEFAULT_BUDGET_MINUTES)
    parser.add_argument("--stall-seconds", type=float, default=DEFAULT_STALL_SECONDS,
                        help="declare a stall when one request or poll runs longer than this")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    from data.config import Settings

    source_url = str(Settings().database_url)
    if not ISOLATED.search(source_url):
        raise SystemExit("refusing: DATABASE_URL must point at the isolated stratai_test database (the source)")
    if args.budget_minutes > 45:
        raise SystemExit("refusing: the budget may not exceed 45 minutes (CLAUDE.md)")
    report = {"captured_at": datetime.now(timezone.utc).isoformat(), "epa_source": os.environ.get("EPA_SOURCE"),
              **simulate(source_url, args.event, args.matches_per_poll, args.readers, args.budget_minutes * 60,
                         args.stall_seconds)}
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
