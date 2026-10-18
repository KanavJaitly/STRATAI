"""P7-M8: capture real request/response examples in a named environment (P7-Q4, P7-Q5).

    python -m scripts.phase7_capture_examples --plan PLAN.json --environment-name NAME --as-of 2026-03-08T18:00:00Z
        [--out docs/api_examples] [--allow-incomplete-environment]

Every planned request is sent in-process (FastAPI TestClient over `api.create_app`) with the deployment's own
Settings. Nothing is written unless every capture succeeded: each response must have the planned status and match
its operation's locked contract (`api.examples.validate_example`). Each written file records the environment it
came from:
- the environment's name, and whether it is the environment of record;
- the fixed `as_of` and the capture time;
- the git commit, and whether the tree was dirty;
- every served model's identity and sha256;
- the EPA source's identity and provenance;
- the database's name, its latest migration, and its table sizes.

**The environment of record (P7-Q5)** has the three pinned models (ranking M5 v2, win probability M6/M7, strategy
P6-M10), a loaded EPA source and migrations through 0011. Without it, the script refuses unless
`--allow-incomplete-environment` is given. A dry run with that flag writes elsewhere, never into docs/api_examples,
and records `environment_of_record: false`, so its "real" examples can never pass the contract test.

**The plan** is JSON: `{"examples": [{"operation": "GET /events/{event_key}/analysis", "name": "...", "kind":
"real" | "refusal_only", "summary": "...", "expect_status": 200, "request": {"path_params": {...}, "query": {...},
"body": ..., "headers": {...}}}]}`. The string `{as_of}` anywhere in a query or body is replaced by `--as-of`, and
`<<KEY>>` by `--set KEY=VALUE` (scripts/phase7_examples_plan.template.json covers the whole scope with placeholders).
Header values (the write token) are sent, but never recorded. The two coach-write successes store a row in the
environment's database copy. Synthetic examples are not captured here: they come from the tests (P7-Q1).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from api.examples import EXAMPLES_DIR, ApiExample, served_path, validate_example

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MIGRATION = "0011"
ENVIRONMENT_OF_RECORD_PROBLEM = "must come from the environment of record"


class CaptureError(Exception):
    """A capture that must not be written."""


def _substitute(value: Any, as_of: str, values: dict[str, str] | None = None) -> Any:
    """Replace `{as_of}` and every `<<KEY>>` placeholder. A string that is exactly one placeholder takes the value
    parsed as JSON when it parses (team numbers, `[[], [], ...]`), and the plain string otherwise."""
    values = values or {}
    if isinstance(value, str):
        for key, replacement in values.items():
            token = f"<<{key}>>"
            if value == token:
                try:
                    return json.loads(replacement)
                except ValueError:
                    return replacement
            value = value.replace(token, replacement)
        if "<<" in value:
            raise CaptureError(f"unfilled placeholder in {value!r} (pass --set KEY=VALUE)")
        return value.replace("{as_of}", as_of)
    if isinstance(value, list):
        return [_substitute(v, as_of, values) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, as_of, values) for k, v in value.items()}
    return value


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()

    return {"commit": run("rev-parse", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}


def _database(app: Any) -> dict[str, Any]:
    settings = app.state.settings
    info: dict[str, Any] = {"name": urlparse(str(settings.database_url)).path.lstrip("/") or None}
    with app.state.database.cursor() as cursor:
        cursor.execute("SELECT max(migration_file) FROM migrations_applied")
        info["latest_migration"] = cursor.fetchone()[0]
        counts = {}
        for table in ("events", "matches", "match_teams", "team_event_stats", "scouting_observations",
                      "raw_source_payloads"):
            cursor.execute(f"SELECT count(*) FROM {table}")  # fixed table names, no input
            counts[table] = cursor.fetchone()[0]
        info["row_counts"] = counts
    return info


def _models(app: Any) -> dict[str, Any]:
    state = app.state
    strategy = state.strategy_model
    playoff = state.playoff_models
    return {
        "ranking": None if state.ranking_model is None else state.ranking_model.identity(),
        "win_probability": None if state.win_prob_model is None else state.win_prob_model.identity(),
        "strategy": None if strategy is None else {"version_tag": strategy.version_tag,
                                                    "model_sha256": strategy.artifact_sha256,
                                                    "spec_sha256": strategy.spec_sha256},
        "playoff": None if playoff is None else {"px1_sha256": playoff.px1_sha256, "px2_sha256": playoff.px2_sha256},
    }


def _epa(app: Any) -> dict[str, Any] | None:
    from api.ml_loading import load_epa_source

    served = app.state.epa_source or load_epa_source(app.state.settings, app.state.database)
    if served is None:
        return None
    return json.loads(json.dumps({"epa_source": served.epa_source, "evaluated_configuration":
                                  served.evaluated_configuration, "provenance": served.provenance,
                                  "adoption": served.adoption}, default=str))


def environment_gaps(fingerprint: dict[str, Any]) -> list[str]:
    """What keeps an environment from being the environment of record (P7-Q5); empty when it is."""
    gaps = [f"model {kind} not loaded" for kind in ("ranking", "win_probability", "strategy")
            if fingerprint["models"][kind] is None]
    if fingerprint["epa"] is None:
        gaps.append("EPA source not loaded")
    latest = fingerprint["database"]["latest_migration"] or ""
    if latest[:4] < REQUIRED_MIGRATION:
        gaps.append(f"migrations only through {latest or 'none'} (needs {REQUIRED_MIGRATION})")
    return gaps


def capture(plan: dict[str, Any], *, environment_name: str, as_of: str, allow_incomplete: bool,
            settings: Any = None, values: dict[str, str] | None = None) -> list[ApiExample]:
    """Run every planned request and return the examples, or raise CaptureError (nothing is returned partially)."""
    from fastapi.testclient import TestClient

    from api import create_app
    from data.config import Settings

    app = create_app(settings or Settings())
    examples: list[ApiExample] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        fingerprint: dict[str, Any] = {"environment_name": environment_name, "as_of": as_of,
                                       "captured_at": datetime.now(timezone.utc).isoformat(), "git": _git(),
                                       "models": _models(app), "epa": _epa(app), "database": _database(app)}
        gaps = environment_gaps(fingerprint)
        if gaps and not allow_incomplete:
            raise CaptureError("not the environment of record (P7-Q5): " + "; ".join(gaps))
        fingerprint["environment_of_record"] = not gaps
        fingerprint["environment_gaps"] = gaps
        problems: list[str] = []
        for entry in plan["examples"]:
            request = _substitute(entry.get("request", {}), as_of, values)
            method, template = entry["operation"].split(" ", 1)
            path = served_path(app, template).format(**request.get("path_params", {}))  # under API_PREFIX
            response = client.request(method, path, params=request.get("query") or None,
                                      json=request.get("body"), headers=request.get("headers") or None)
            if response.status_code != entry["expect_status"]:
                problems.append(f"{entry['operation']} {entry['name']}: status {response.status_code}, planned "
                                f"{entry['expect_status']}: {response.text[:300]}")
                continue
            recorded = {k: v for k, v in request.items() if k != "headers"}  # never record a write token
            example = ApiExample(operation=entry["operation"], status=response.status_code, name=entry["name"],
                                 kind=entry["kind"], summary=entry["summary"], environment=fingerprint,
                                 request=recorded, response=response.json())
            found = validate_example(app, example)
            if allow_incomplete:  # a dry run: shape checks only; its examples stay outside docs/api_examples
                found = [p for p in found if ENVIRONMENT_OF_RECORD_PROBLEM not in p]
            problems.extend(found)
            examples.append(example)
        if problems:
            raise CaptureError("capture failed; nothing written:\n  " + "\n  ".join(problems))
    return examples


def file_name(example: ApiExample) -> str:
    slug = example.operation.lower().replace(" ", "_").replace("/", "_").replace("{", "").replace("}", "")
    return f"{slug.strip('_')}__{example.status}__{example.name}.json"


def write_examples(examples: list[ApiExample], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for example in examples:
        path = out / file_name(example)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(example.model_dump(mode="json"), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--as-of", required=True, help="ISO-8601 with an offset; substituted for {as_of}")
    parser.add_argument("--out", type=Path, default=EXAMPLES_DIR)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="fill a <<KEY>> placeholder in the plan (e.g. EVENT=2026casj)")
    parser.add_argument("--allow-incomplete-environment", action="store_true",
                        help="dry run outside the environment of record; never writes into docs/api_examples")
    args = parser.parse_args(argv)
    if datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).tzinfo is None:
        parser.error("--as-of needs an offset")
    if args.allow_incomplete_environment and args.out.resolve() == EXAMPLES_DIR.resolve():
        parser.error("a dry run (--allow-incomplete-environment) cannot write into docs/api_examples")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    values = dict(item.split("=", 1) for item in args.set)
    try:
        examples = capture(plan, environment_name=args.environment_name, as_of=args.as_of,
                           allow_incomplete=args.allow_incomplete_environment, values=values)
    except CaptureError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for path in write_examples(examples, args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
