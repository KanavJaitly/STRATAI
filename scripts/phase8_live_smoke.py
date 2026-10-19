"""P8-M7 (c): drive every dashboard operation against a running API, and optionally every page in a real browser.

    python -m scripts.phase8_live_smoke --api http://127.0.0.1:8765 --season 2026 [--out FILE]
        [--app http://127.0.0.1:5173 --chrome /path/to/chrome-headless-shell]

The API run calls each operation in frontend/src/api/dashboard.ts DASHBOARD_ENDPOINTS with real keys it discovers
(the season's first event, its first scheduled qualification match, and a team in that match). It records each
operation's HTTP status, error code and duration. A response is "ok" when it is a 2xx or a refusal the operation
declares in OpenAPI (e.g. model_not_loaded, not_approved): a declared refusal is the API working as specified, not a
failure. Undeclared codes, 5xx and transport errors fail the run.

The request bodies are this script's copy of what the dashboard sends (the dashboard is TypeScript); the frontend
tests check the dashboard's own requests. A 422 validation_error always fails the run, so a copy that drifts from
the contract is caught. The coach writes are called **without** a write token, so they must be refused (403) and nothing is stored. The
script never writes to the database it is pointed at.

The browser run loads each dashboard page in headless Chromium (--dump-dom after the page's requests settle). It
checks that the page rendered its main heading and no "Page not found", and that every API failure it shows is an
explained refusal rather than an unexplained error.

This verifies the dashboard against the API it is run against. Here that is the local isolated copy with the
reference EPA source; in the environment of record (P7-Q5) the same command shows the model-backed results.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "frontend" / "src" / "api" / "dashboard.ts"
ENTRY = re.compile(r"^\s*(\w+): \['(GET|POST|PUT)', '(/[^']+)'\],$", re.MULTILINE)
CODES = re.compile(r"`([a-z][a-z0-9_]*)`")


def dashboard_operations() -> dict[str, tuple[str, str]]:
    source = DASHBOARD.read_text(encoding="utf-8")
    block = source[source.index("export const DASHBOARD_ENDPOINTS = {"):source.index("} as const satisfies")]
    return {name: (method, path) for name, method, path in ENTRY.findall(block)}


def http(api: str, method: str, path: str, query: dict[str, Any] | None = None, body: Any = None,
         timeout: float = 120.0) -> tuple[int, Any, float]:
    url = api.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    elapsed = time.perf_counter() - started
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = {"_unparsed": raw[:200].decode(errors="replace")}
    return status, parsed, elapsed


def declared(openapi: dict[str, Any], method: str, path: str, status: int) -> set[str]:
    response = openapi["paths"].get(path, {}).get(method.lower(), {}).get("responses", {}).get(str(status))
    return set(CODES.findall(response.get("description", ""))) if response else set()


def discover(api: str, season: int) -> dict[str, Any]:
    _, events, _ = http(api, "GET", "/events", {"season": season})
    if not events or not events.get("events"):
        raise SystemExit(f"no events for season {season} at {api}")
    event = events["events"][0]["event_key"]
    _, matches, _ = http(api, "GET", f"/events/{event}/matches")
    qual = next((m for m in matches["matches"] if m["competition_level"] == "qualification"
                 and len(m["red_team_numbers"]) == 3 and len(m["blue_team_numbers"]) == 3), None)
    if qual is None:
        raise SystemExit(f"{event} has no complete qualification match")
    return {"event": event, "match": qual["match_key"], "red": qual["red_team_numbers"],
            "blue": qual["blue_team_numbers"], "team": qual["red_team_numbers"][0],
            "scheduled": qual["scheduled_time"]}


def calls(k: dict[str, Any]) -> dict[str, tuple[dict[str, Any] | None, Any]]:
    """The request the dashboard makes for each operation: (query, body)."""
    baseline = lambda teams: {"vocabulary": "p6-strategy-v1", "robots": [  # noqa: E731
        {"team_number": t, "role": "scoring", "components": ["auto", "teleop", "endgame"]} for t in teams]}
    hypo = {"event_key": k["event"], "red_team_numbers": k["red"], "blue_team_numbers": k["blue"],
            "match_context": "qualification"}
    n_alliances = 8
    return {
        "health": (None, None), "ready": (None, None),
        "events": ({"season": int(k["event"][:4])}, None),
        "eventTeams": (None, None), "eventMatches": (None, None), "eventAnalysis": (None, None),
        "qualificationForecast": (None, None), "teamMetrics": (None, None), "teamStrength": (None, None),
        "matchWinProbability": (None, None),
        "allianceWinProbability": (None, {**hypo, "match_context": "qualification"}),
        "allianceSynergy": (None, {"event_key": k["event"], "team_numbers": k["red"]}),
        "candidates": (None, None),
        "pickList": (None, {"seed": 1, "alliances": [[] for _ in range(n_alliances)], "declined": [], "turns_taken": 0}),
        "matchAssess": (None, {"side": "red", "strategy": baseline(k["red"])}),
        "matchRecommend": (None, {"side": "red"}),
        "matchCompare": (None, {"side": "red", "first": baseline(k["red"]), "second": baseline(k["red"])}),
        "hypotheticalAssess": (None, {**hypo, "side": "red", "strategy": baseline(k["red"])}),
        "hypotheticalRecommend": (None, {**hypo, "side": "red"}),
        "hypotheticalCompare": (None, {**hypo, "side": "red", "first": baseline(k["red"]), "second": baseline(k["red"])}),
        "coachStrategy": (None, {"event_key": k["event"], "match_key": k["match"], "author": "smoke", "strategy": baseline(k["red"])}),
        "coachObservation": (None, {"event_key": k["event"], "team_number": k["team"], "kind": "robot_unavailable",
                                    "observed_at": "2000-01-01T00:00:00Z", "observer": "smoke"}),
        "preMatchReport": (None, None),
    }


def run_api(api: str, season: int) -> dict[str, Any]:
    from api import create_app
    from data.config import Settings

    openapi = create_app(Settings(api_prefix="")).openapi()
    keys = discover(api, season)
    params = {"event_key": keys["event"], "match_key": keys["match"], "team_number": keys["team"]}
    results = []
    for name, (method, template) in dashboard_operations().items():
        query, body = calls(keys)[name]
        path = template.format(**{p: params[p] for p in re.findall(r"\{(\w+)\}", template)})
        status, payload, elapsed = http(api, method, path, query, body)
        code = (payload or {}).get("error", {}).get("code") if isinstance(payload, dict) and status >= 400 else None
        if name in ("coachStrategy", "coachObservation"):
            ok = status == 403  # no token sent: must be refused, and nothing stored
        elif 200 <= status < 300:
            ok = True
        elif status == 422 and code == "validation_error":
            ok = False  # the request body or parameters do not match the contract: a smoke defect, never "ok"
        else:
            ok = status < 500 and code in declared(openapi, method, template, status)
        results.append({"operation": name, "method": method, "path": path, "status": status, "code": code,
                        "seconds": round(elapsed, 2), "ok": ok})
    # The event analysis before the switch point is served without a model (raw EPA): time that real path too.
    start = keys["scheduled"][:10] + "T00:00:00Z"
    status, payload, elapsed = http(api, "GET", f"/events/{keys['event']}/analysis", {"as_of": start})
    results.append({"operation": "eventAnalysis (as_of before the switch point)", "method": "GET",
                    "path": f"/events/{keys['event']}/analysis?as_of={start}", "status": status,
                    "code": (payload or {}).get("error", {}).get("code") if status >= 400 else None,
                    "seconds": round(elapsed, 2), "ok": status == 200 or status == 404})
    return {"api": api, "keys": keys, "results": results, "all_ok": all(r["ok"] for r in results)}


PAGES = [
    ("events", "/?season={season}", "Events"),
    ("event", "/events/{event}", None),
    ("event_teams", "/events/{event}?tab=teams", None),
    ("event_matches", "/events/{event}?tab=matches", None),
    ("event_forecast", "/events/{event}?tab=forecast", None),
    ("team", "/events/{event}/teams/{team}", "Team {team}"),
    ("match", "/matches/{match}", None),
    ("strategy_lab", "/events/{event}/strategy-lab?red={red}&blue={blue}", "Strategy lab"),
    ("alliance", "/events/{event}/alliance-selection", "Alliance selection"),
    ("report", "/report/{match}", "Pre-match report"),
    ("status", "/status", "System status"),
]


def run_browser(app: str, chrome: str, keys: dict[str, Any], season: int) -> dict[str, Any]:
    fill = {**keys, "season": season, "red": ",".join(map(str, keys["red"])), "blue": ",".join(map(str, keys["blue"]))}
    results = []
    for name, template, heading in PAGES:
        url = app.rstrip("/") + template.format(**fill)
        started = time.perf_counter()
        dom = subprocess.run([chrome, "--no-sandbox", "--disable-gpu", "--virtual-time-budget=40000", "--dump-dom", url],
                             capture_output=True, text=True, timeout=180).stdout
        elapsed = time.perf_counter() - started
        text = re.sub(r"<[^>]+>", " ", dom)
        problems = []
        if "Page not found" in text:
            problems.append("not found")
        if heading and heading.format(**fill) not in text:
            problems.append(f"heading {heading.format(**fill)!r} missing")
        if "<h1" not in dom:
            problems.append("no h1")
        alerts = re.findall(r'class="notice notice-error[^"]*"', dom)
        if alerts:
            problems.append(f"{len(alerts)} unexplained error notice(s)")
        refusals = sorted(set(re.findall(r"<code>([a-z_]+)</code> \(\d{3}\)", dom)))
        results.append({"page": name, "url": url, "seconds": round(elapsed, 1), "refusals_shown": refusals,
                        "problems": problems, "ok": not problems})
    return {"app": app, "results": results, "all_ok": all(r["ok"] for r in results)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8765")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--app", help="the dashboard's base URL, for the browser run")
    parser.add_argument("--chrome", help="a headless Chromium executable, for the browser run")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report: dict[str, Any] = {"captured_at": datetime.now(timezone.utc).isoformat(), "season": args.season,
                              "api_run": run_api(args.api, args.season)}
    if args.app and args.chrome:
        report["browser_run"] = run_browser(args.app, args.chrome, report["api_run"]["keys"], args.season)
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    for r in report["api_run"]["results"]:
        print(f"{'ok ' if r['ok'] else 'BAD'} {r['method']:4} {r['path'][:62]:62} {r['status']} {r['code'] or ''} {r['seconds']}s")
    for r in report.get("browser_run", {}).get("results", []):
        print(f"{'ok ' if r['ok'] else 'BAD'} page {r['page']:15} {r['seconds']}s refusals={r['refusals_shown']} {r['problems']}")
    ok = report["api_run"]["all_ok"] and report.get("browser_run", {"all_ok": True})["all_ok"]
    print("ALL OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
