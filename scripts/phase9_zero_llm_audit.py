"""P9-M1: prove that every prediction, ranking, strategy and pick list works with zero LLM involvement.

    python -m scripts.phase9_zero_llm_audit [--routes --event 2026mrcmp] [--out FILE]

Three checks, each usable on its own (tests/test_phase9_zero_llm.py runs the first two):

1. **Static.** No module in the core packages (`ml`, `data`, `database`, `api`, `automation`, `scripts`):
   - imports an LLM SDK or the Phase 9 `briefing` package. `import x`, `from x import y` and `from x.y import z`
     are each checked against the dotted name, so `from google import genai` counts as `google.genai`;
   - imports code dynamically or runs code from strings (`importlib.import_module`, `__import__`, `exec`, `eval`,
     `compile`, or a reference to `import_module`). The core has none, so any one is a violation, literal or not:
     a computed module name cannot be checked;
   - names an LLM provider's API host in a string (a raw HTTP call to a provider bypasses any SDK).
   The only allowed places are the briefing package itself, its API route `api/routes/briefing.py`, and the Phase 9
   cost script `scripts/phase9_briefing_cost.py`. The scanner is a guard against accidents and evasions it knows,
   not a proof against a determined author (P9-R10).
2. **Import-time.** In a fresh interpreter where every LLM SDK and `briefing` are made unimportable, every core
   module imports and the API application builds. So no core path even reaches an LLM import lazily at import time.
3. **Runtime** (`--routes`). In that same blocked interpreter, every prediction, ranking, strategy, pick-list and
   report route is called against the database in `DATABASE_URL` (an isolated `stratai_test*` copy). Each must answer
   200 or a refusal it declares in OpenAPI, as the Phase 8 live smoke judges it. The route list is the
   **inventory**. Every operation in the OpenAPI document must be classified (OPERATION_CLASSES), so a new operation
   fails the check until someone decides whether it produces an output that must be LLM-free.

Nothing here calls an LLM or writes to a database.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGES = ("ml", "data", "database", "api", "automation", "scripts")
UNREACHABLE_DATABASE_URL = "postgresql://p9-import-check@127.0.0.1:1/unreachable"

# Module names of LLM SDKs, agent frameworks, model hubs and cloud AI clients. A prefix match on the dotted name catches
# subpackages; LLM_MODULE_PREFIXES also catch every top-level name that starts with them (langchain_community, ...).
LLM_MODULES = ("anthropic", "claude_agent_sdk", "openai", "google.generativeai", "google.genai", "google.ai",
               "google.cloud.aiplatform", "vertexai", "mistralai", "cohere", "ollama", "llama_index", "llama_cpp",
               "litellm", "transformers", "sentence_transformers", "huggingface_hub", "together", "groq", "replicate",
               "boto3", "botocore", "aiobotocore", "pydantic_ai", "instructor", "dspy", "guidance", "vllm",
               "azure.ai.inference", "azure.ai.openai", "azure.ai.ml", "fireworks", "ai21", "voyageai", "mcp",
               "haystack", "semantic_kernel", "autogen", "autogen_agentchat", "crewai", "smolagents", "llm", "gpt4all",
               "xai_sdk", "dashscope", "zhipuai", "aisuite", "deepinfra", "openrouter", "google.adk")
LLM_MODULE_PREFIXES = ("langchain", "langgraph", "llama_index", "openai_", "anthropic_sdk")
# LLM provider API hosts. A string naming one in the core is a violation (a raw HTTP call needs no SDK).
LLM_HOSTS = ("anthropic.com", "claude.ai", "openai.com", "openai.azure.com", "generativelanguage.googleapis.com",
             "aiplatform.googleapis.com", "bedrock-runtime", "mistral.ai", "cohere.ai", "cohere.com", "groq.com",
             "together.xyz", "together.ai", "replicate.com", "openrouter.ai", "huggingface.co", "fireworks.ai",
             "deepseek.com", "x.ai", "perplexity.ai")
# Loading code by a name or path the scan cannot read: by any name (a call, an attribute, an import, or a string).
DYNAMIC_IMPORT = {"import_module", "__import__", "exec_module", "spec_from_file_location", "module_from_spec",
                  "run_module", "run_path", "resolve_name", "locate", "load_module", "find_spec"}
DYNAMIC_CODE = DYNAMIC_IMPORT | {"exec", "eval", "compile"}  # the builtins (re.compile is an attribute, not these)
BRIEFING_PACKAGE = "briefing"
BRIEFING_ROUTE = "api.routes.briefing"  # importing the route reaches the LLM layer too (review R2 C6)
FORBIDDEN = LLM_MODULES + (BRIEFING_PACKAGE, BRIEFING_ROUTE)
# Blocked at import time: the SDKs and the package. (The route is not: it fails on its own when `briefing` is
# blocked, which is exactly the "LLM layer absent" state the app tolerates.)
BLOCKED = LLM_MODULES + (BRIEFING_PACKAGE,)
# The only places allowed to import them (P9-Q1): the formatter, its route, and the cost tool. This checker names
# them all (it is the list), so it is exempt from its own scan. The app may import the route, and nothing else of
# the LLM layer (its optional router).
ALLOWED_FILES = ("api/routes/briefing.py", "scripts/phase9_briefing_cost.py", "scripts/phase9_zero_llm_audit.py")
ALLOWED_IMPORTS = {"api/app.py": {BRIEFING_ROUTE}}

# Every API operation, classified (review R1 C9: a prefix allowlist silently missed new operations):
# - "output": produces or carries a prediction, ranking, strategy, pick list, recommendation or report. This is the
#   P9-M1 inventory: each one is called by the runtime check with every LLM SDK blocked.
# - "llm_layer": the Phase 9 briefing, the one place an LLM may be used (P9-M7 proves the outputs do not depend on it).
# - "not_output": data reads, health, and human-input writes or bookkeeping; none produces an engine output.
# A new operation is unclassified until added here, and the check fails (tests/test_phase9_zero_llm.py).
OUTPUT, LLM_LAYER, NOT_OUTPUT = "output", "llm_layer", "not_output"
OPERATION_CLASSES = {
    "GET /events/{event_key}/alliance-selection/candidates": OUTPUT,
    "POST /events/{event_key}/alliance-selection/pick-list": OUTPUT,
    "GET /events/{event_key}/analysis": OUTPUT,
    "GET /events/{event_key}/qualification-forecast": OUTPUT,
    "GET /matches/{match_key}/pre-match-report": OUTPUT,
    "GET /predictions/events/{event_key}/ranking": OUTPUT,
    "GET /predictions/matches/{match_key}/win-probability": OUTPUT,
    "POST /predictions/alliance-synergy": OUTPUT,
    "POST /predictions/win-probability": OUTPUT,
    "POST /strategy/hypothetical/assess": OUTPUT,
    "POST /strategy/hypothetical/compare": OUTPUT,
    "POST /strategy/hypothetical/recommend": OUTPUT,
    "POST /strategy/matches/{match_key}/assess": OUTPUT,
    "POST /strategy/matches/{match_key}/compare": OUTPUT,
    "POST /strategy/matches/{match_key}/recommend": OUTPUT,
    "GET /teams/{team_number}/events/{event_key}/metrics": OUTPUT,
    "GET /teams/{team_number}/events/{event_key}/strength": OUTPUT,
    "GET /human-inputs/capability-profiles/{profile_key}/recommendation": OUTPUT,  # the P5-M9 recommendation
    "GET /matches/{match_key}/briefing": LLM_LAYER,
    "GET /events": NOT_OUTPUT, "GET /events/{event_key}/matches": NOT_OUTPUT, "GET /events/{event_key}/teams": NOT_OUTPUT,
    "GET /health": NOT_OUTPUT, "GET /ready": NOT_OUTPUT,
    "POST /strategy/coach-observations": NOT_OUTPUT, "POST /strategy/coach-strategies": NOT_OUTPUT,  # inputs (P8-R7)
    "POST /human-inputs/artifacts/{artifact_id}/establish": NOT_OUTPUT,
    "GET /human-inputs/capability-profiles": NOT_OUTPUT, "POST /human-inputs/capability-profiles": NOT_OUTPUT,
    "PUT /human-inputs/capability-profiles/{profile_key}": NOT_OUTPUT,
    "POST /human-inputs/capability-profiles/{profile_key}/archive": NOT_OUTPUT,
    "POST /human-inputs/capability-profiles/{profile_key}/duplicate": NOT_OUTPUT,
    "GET /human-inputs/capability-profiles/{profile_key}/history": NOT_OUTPUT,
    "POST /human-inputs/game-manuals": NOT_OUTPUT, "GET /human-inputs/game-manuals": NOT_OUTPUT,
    "GET /human-inputs/game-manuals/{manual_id}/file": NOT_OUTPUT,
    "GET /human-inputs/reference/design-examples": NOT_OUTPUT,
    "GET /human-inputs/seasons/{season}/artifacts": NOT_OUTPUT, "POST /human-inputs/seasons/{season}/artifacts": NOT_OUTPUT,
    "GET /human-inputs/seasons/{season}/dm1-status": NOT_OUTPUT, "GET /human-inputs/seasons/{season}/kappa": NOT_OUTPUT,
    "GET /human-inputs/seasons/{season}/specs": NOT_OUTPUT, "POST /human-inputs/seasons/{season}/specs": NOT_OUTPUT,
    "GET /human-inputs/seasons/{season}/workflow": NOT_OUTPUT,
    "POST /human-inputs/specs/{spec_id}/review": NOT_OUTPUT, "POST /human-inputs/specs/{spec_id}/submit": NOT_OUTPUT,
    "GET /human-inputs/write-access": NOT_OUTPUT,
}


def _forbidden(name: str) -> bool:
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN) or \
        name.split(".")[0].startswith(LLM_MODULE_PREFIXES)


def _host(text: str) -> str | None:
    lowered = text.lower()
    return next((h for h in LLM_HOSTS if re.search(r"(?:^|[/.@\s])" + re.escape(h) + r"(?:$|[/:\s?#])", lowered)),
                None)


def forbidden_imports(source: str) -> list[str]:
    """What a Python source does that the core may not (module docstring, check 1): each forbidden module it imports
    (dotted), `dynamic:<name>` for each dynamic import or string execution, `host:<host>` for each provider host."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if _forbidden(node.module):
                found.append(node.module)
            else:
                found += [f"{node.module}.{a.name}" for a in node.names if _forbidden(f"{node.module}.{a.name}")]
            found += [f"dynamic:{a.name}" for a in node.names if a.name in DYNAMIC_IMPORT]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" \
                and node.args and isinstance(node.args[0], ast.Name) \
                and node.args[0].id in {"builtins", "__builtins__", "importlib", "runpy", "pkgutil", "pydoc"}:
            found.append(f"dynamic:getattr({node.args[0].id})")  # a computed attribute of a loader module
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_CODE:
            found.append(f"dynamic:{node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in DYNAMIC_IMPORT | {"exec", "eval"}:
            found.append(f"dynamic:{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in DYNAMIC_IMPORT:  # getattr(importlib, "import_module")
                found.append(f"dynamic:{node.value}")
            host = _host(node.value)
            if host:
                found.append(f"host:{host}")
    return found


def core_files(root: Path = ROOT) -> Iterable[Path]:
    for package in CORE_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def static_violations(root: Path = ROOT) -> list[str]:
    violations = []
    for path in core_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in ALLOWED_FILES:
            continue
        allowed = ALLOWED_IMPORTS.get(relative, set())
        for module in forbidden_imports(path.read_text(encoding="utf-8")):
            if module not in allowed:
                violations.append(f"{relative} imports {module}")
    return violations


def core_module_names(root: Path = ROOT) -> list[str]:
    names = []
    for path in core_files(root):
        relative = path.relative_to(root).with_suffix("")
        if relative.as_posix() in {p[:-3] for p in ALLOWED_FILES}:
            continue
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts[-1] == "__main__":
            continue  # entry points run a CLI on import
        names.append(".".join(parts))
    return names


# Installed first in the child interpreter: any attempt to import an LLM SDK or the briefing package fails.
BLOCKER = f"""
import importlib.abc, sys
FORBIDDEN = {BLOCKED!r}
PREFIXES = {LLM_MODULE_PREFIXES!r}
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if any(name == f or name.startswith(f + '.') for f in FORBIDDEN) or name.split('.')[0].startswith(PREFIXES):
            raise ModuleNotFoundError(f'P9-M1: {{name}} is blocked (zero-LLM check)', name=name)
        return None
sys.meta_path.insert(0, _Block())
for loaded in [m for m in sys.modules if any(m == f or m.startswith(f + '.') for f in FORBIDDEN)
               or m.split('.')[0].startswith(PREFIXES)]:
    del sys.modules[loaded]
"""

IMPORT_CHECK = BLOCKER + """
import importlib, json
failures = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except SystemExit:
        pass
    except Exception as exc:  # report every failure; a blocked LLM import shows up here
        failures[name] = f'{type(exc).__name__}: {exc}'
from api import create_app
from data.config import Settings
app = create_app(Settings(api_prefix=''))
print(json.dumps({'imported': len(json.loads(sys.argv[1])) - len(failures), 'failures': failures,
                  'operations': sum(len(m) for m in app.openapi()['paths'].values())}))
"""


def import_check(root: Path = ROOT) -> dict:
    names = core_module_names(root)
    # An unreachable database: importing the core must not connect anywhere, and if a module tried, it fails here
    # (reported) instead of reaching a real database (the serving one is the .env default).
    env = {**os.environ, "DATABASE_URL": UNREACHABLE_DATABASE_URL}
    done = subprocess.run([sys.executable, "-c", IMPORT_CHECK, json.dumps(names)], cwd=root, capture_output=True,
                          text=True, timeout=600, env=env)
    if done.returncode != 0:
        return {"ok": False, "error": done.stderr[-2000:]}
    result = json.loads(done.stdout.strip().splitlines()[-1])
    result["ok"] = not result["failures"]
    result["modules"] = len(names)
    return result


def operations(openapi: dict) -> list[str]:
    return sorted(f"{method.upper()} {path}" for path, methods in openapi["paths"].items() for method in methods)


def unclassified(openapi: dict) -> list[str]:
    """Operations served but not in OPERATION_CLASSES (each needs a decision), and classified ones no longer served."""
    served = set(operations(openapi))
    return sorted(served - set(OPERATION_CLASSES)) + sorted(f"stale: {o}" for o in set(OPERATION_CLASSES) - served
                                                           if o != "GET /matches/{match_key}/briefing")


def inventory(openapi: dict) -> list[tuple[str, str]]:
    """The P9-M1 inventory: every served operation classified as an output."""
    return sorted(tuple(o.split(" ", 1)) for o in operations(openapi) if OPERATION_CLASSES.get(o) == OUTPUT)


ROUTE_SCRIPT = r"""
import hashlib, json, re, sys
from fastapi.testclient import TestClient
from api import create_app
from data.config import Settings
args = json.loads(sys.argv[1])
app = create_app(Settings(api_prefix=''))
if args.get('stub'):  # the connected run: the LLM path runs end to end against a stub model (no network)
    from types import SimpleNamespace
    from api.routes.briefing import get_briefing_client_factory
    from scripts.phase9_briefing_cost import reference_arrangement
    def _create(**request):
        facts = [SimpleNamespace(**f) for f in json.loads(request['messages'][0]['content'])['facts']]
        text = reference_arrangement(facts)
        return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)], stop_reason='end_turn',
                               model='stub', usage=None)
    stub = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=_create)))
    app.dependency_overrides[get_briefing_client_factory] = lambda: (lambda: stub)
openapi = app.openapi()
CODES = re.compile(r"`([a-z][a-z0-9_]*)`")
def scrub(value):  # the request id differs per call by design; nothing else may
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k != 'request_id'}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value
def declared(method, path, status):
    resp = openapi['paths'].get(path, {}).get(method.lower(), {}).get('responses', {}).get(str(status))
    return set(CODES.findall(resp.get('description', ''))) if resp else set()
results = []
with TestClient(app) as client:
    for method, template, url, body in args['calls']:
        r = client.request(method, url, json=body)
        code = r.json().get('error', {}).get('code') if r.status_code >= 400 else None
        ok = 200 <= r.status_code < 300 or (r.status_code < 500 and r.status_code != 422 and code in declared(method, template, r.status_code))
        body = hashlib.sha256(json.dumps(scrub(r.json()), sort_keys=True).encode()).hexdigest()
        results.append({'operation': f'{method} {template}', 'status': r.status_code, 'code': code, 'ok': ok,
                        'body_sha256': body})
    for url in args.get('extra', []):  # calls reported as-is (the briefing, in the connected run)
        r = client.get(url)
        results.append({'url': url, 'status': r.status_code, 'mode': r.json().get('mode'),
                        'fallback_reason': r.json().get('fallback_reason')})
print(json.dumps(results))
"""
ROUTE_CHECK = BLOCKER + ROUTE_SCRIPT


def route_calls(event: str, database_url: str) -> list:
    """Real keys from the database: the event's first complete qualification match and one of its teams."""
    import psycopg

    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT m.match_key FROM matches m WHERE m.event_key = %s AND m.competition_level = 'qualification' "
            "AND (SELECT count(*) FROM match_teams t WHERE t.match_key = m.match_key) = 6 "
            "ORDER BY m.scheduled_time NULLS LAST, m.match_number LIMIT 1", (event,)).fetchone()
        match = row[0]
        teams = conn.execute("SELECT team_number, alliance_color FROM match_teams WHERE match_key = %s "
                             "ORDER BY alliance_color, station_position", (match,)).fetchall()
        profile = conn.execute("SELECT profile_key FROM capability_profiles ORDER BY profile_key LIMIT 1").fetchone()
    # No stored profile: the call still runs the route and must answer its declared not_found refusal.
    profile_key = profile[0] if profile else "p9-zero-llm-no-such-profile"
    season = int(event[:4])
    red = [t for t, c in teams if c == "red"]
    blue = [t for t, c in teams if c == "blue"]
    strategy = {"vocabulary": "p6-strategy-v1", "robots": [
        {"team_number": t, "role": "scoring", "components": ["auto", "teleop", "endgame"]} for t in red]}
    pair = {"event_key": event, "red_team_numbers": red, "blue_team_numbers": blue, "match_context": "qualification"}
    return [
        ("GET", "/events/{event_key}/analysis", f"/events/{event}/analysis", None),
        ("GET", "/events/{event_key}/qualification-forecast", f"/events/{event}/qualification-forecast", None),
        ("GET", "/events/{event_key}/alliance-selection/candidates", f"/events/{event}/alliance-selection/candidates", None),
        ("POST", "/events/{event_key}/alliance-selection/pick-list", f"/events/{event}/alliance-selection/pick-list",
         {"seed": 1, "alliances": [[] for _ in range(8)], "declined": [], "turns_taken": 0}),
        ("GET", "/predictions/events/{event_key}/ranking", f"/predictions/events/{event}/ranking", None),
        ("GET", "/predictions/matches/{match_key}/win-probability", f"/predictions/matches/{match}/win-probability", None),
        ("POST", "/predictions/win-probability", "/predictions/win-probability", pair),
        ("POST", "/predictions/alliance-synergy", "/predictions/alliance-synergy", {"event_key": event, "team_numbers": red}),
        ("POST", "/strategy/matches/{match_key}/assess", f"/strategy/matches/{match}/assess", {"side": "red", "strategy": strategy}),
        ("POST", "/strategy/matches/{match_key}/recommend", f"/strategy/matches/{match}/recommend", {"side": "red"}),
        ("POST", "/strategy/matches/{match_key}/compare", f"/strategy/matches/{match}/compare",
         {"side": "red", "first": strategy, "second": strategy}),
        ("POST", "/strategy/hypothetical/assess", "/strategy/hypothetical/assess", {**pair, "side": "red", "strategy": strategy}),
        ("POST", "/strategy/hypothetical/recommend", "/strategy/hypothetical/recommend", {**pair, "side": "red"}),
        ("POST", "/strategy/hypothetical/compare", "/strategy/hypothetical/compare",
         {**pair, "side": "red", "first": strategy, "second": strategy}),
        ("GET", "/matches/{match_key}/pre-match-report", f"/matches/{match}/pre-match-report", None),
        ("GET", "/teams/{team_number}/events/{event_key}/strength", f"/teams/{red[0]}/events/{event}/strength", None),
        ("GET", "/teams/{team_number}/events/{event_key}/metrics", f"/teams/{red[0]}/events/{event}/metrics", None),
        ("GET", "/human-inputs/capability-profiles/{profile_key}/recommendation",
         f"/human-inputs/capability-profiles/{profile_key}/recommendation?season={season}", None),
    ]


def route_check(event: str, database_url: str, root: Path = ROOT) -> dict:
    from api import create_app
    from data.config import Settings

    calls = route_calls(event, database_url)
    covered = {(m, t) for m, t, _, _ in calls}
    expected = set(inventory(create_app(Settings(api_prefix="")).openapi()))
    env = {**os.environ, "DATABASE_URL": database_url}  # the verified isolated copy, never the .env default
    done = subprocess.run([sys.executable, "-c", ROUTE_CHECK, json.dumps({"calls": calls})], cwd=root,
                          capture_output=True, text=True, timeout=1800, env=env)
    if done.returncode != 0:
        return {"ok": False, "error": done.stderr[-3000:]}
    results = json.loads(done.stdout.strip().splitlines()[-1])
    missing = sorted(f"{m} {t}" for m, t in expected - covered)
    return {"ok": all(r["ok"] for r in results) and not missing, "results": results,
            "inventory_missing_from_calls": missing}


PINNED_AS_OF = "2026-06-01T00:00:00Z"  # past, and after the 2026 events checked: a fixed, reproducible moment


def disconnection_check(event: str, database_url: str, root: Path = ROOT) -> dict:
    """P9-DM1: the same calls, (a) with every LLM SDK and the briefing package blocked, and (b) with the LLM layer
    enabled and approved (BRIEFING_LLM_ENABLED, BRIEFING_DATA_EGRESS_APPROVED) and a stub model behind it (the spec's
    "LLM enabled (stubbed)"). In (b) the briefing is called too, and must come back in `llm` mode, so the layer
    really ran. Credentials are removed from both runs' environments: no network call can be made. The verdict is
    `judge_disconnection`."""
    from api import create_app
    from data.config import Settings

    paths = create_app(Settings(api_prefix="")).openapi()["paths"]

    def pinned(method: str, template: str, url: str) -> str:
        """A fixed as_of wherever the operation takes one, so a 'now' default cannot differ between the two runs."""
        names = {p["name"] for p in paths[template][method.lower()].get("parameters", [])}
        if "as_of" not in names:
            return url
        return url + ("&" if "?" in url else "?") + "as_of=" + PINNED_AS_OF

    calls = [(m, t, pinned(m, t, url), body) for m, t, url, body in route_calls(event, database_url)]
    match = next(url for m, t, url, _ in calls if t == "/matches/{match_key}/pre-match-report").split("/")[2] \
        .split("?")[0]
    runs = {}
    for name, script, extra_env, extra in (
            ("disconnected", ROUTE_CHECK, {}, []),
            ("connected", ROUTE_SCRIPT, {"BRIEFING_LLM_ENABLED": "true", "BRIEFING_DATA_EGRESS_APPROVED": "true"},
             [f"/matches/{match}/briefing?as_of={PINNED_AS_OF}"])):
        # No credential can reach either run (the connected one uses a stub model): never a real API call.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("ANTHROPIC_") and k not in ("BRIEFING_LLM_ENABLED", "BRIEFING_DATA_EGRESS_APPROVED")}
        env.update({"DATABASE_URL": database_url, "ANTHROPIC_CONFIG_DIR": "/nonexistent/p9-no-credential", **extra_env})
        payload = {"calls": calls, "extra": extra, "stub": name == "connected"}
        done = subprocess.run([sys.executable, "-c", script, json.dumps(payload)],
                              cwd=root, capture_output=True, text=True, timeout=1800, env=env)
        if done.returncode != 0:
            return {"ok": False, "error": f"{name}: " + done.stderr[-3000:]}
        runs[name] = json.loads(done.stdout.strip().splitlines()[-1])
    return {**judge_disconnection(runs["disconnected"], runs["connected"]), "runs": runs}


def judge_disconnection(disconnected: list[dict], connected: list[dict]) -> dict:
    """P9-DM1's verdict on two runs, and never a vacuous pass (review R2 C5):
    - every operation answers the same status and body in both;
    - at least one full (2xx) output was compared, not only refusals;
    - the LLM layer really ran in the connected run (the briefing came back in `llm` mode)."""
    pairs = [r for r in connected if "operation" in r]
    same_operations = [a["operation"] for a in disconnected] == [b["operation"] for b in pairs]
    differing = [a["operation"] for a, b in zip(disconnected, pairs)
                 if (a["status"], a["body_sha256"]) != (b["status"], b["body_sha256"])]
    full = [a["operation"] for a in disconnected if 200 <= a["status"] < 300]
    briefing = [r for r in connected if "url" in r]
    llm_ran = bool(briefing) and all(r["status"] == 200 and r["mode"] == "llm" for r in briefing)
    return {"ok": same_operations and not differing and bool(full) and llm_ran,
            "operations_compared": len(pairs), "full_outputs_compared": full,
            "refusals_compared": [f"{a['operation']} ({a['status']} {a['code']})" for a in disconnected
                                  if not 200 <= a["status"] < 300],
            "differing": differing, "llm_layer_ran": llm_ran, "connected_briefing": briefing}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--routes", action="store_true", help="also run the runtime route check (needs DATABASE_URL)")
    parser.add_argument("--disconnection", action="store_true",
                        help="also run the P9-DM1 disconnection comparison (needs DATABASE_URL)")
    parser.add_argument("--event", default="2026mrcmp")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    from api import create_app
    from data.config import Settings

    report: dict = {"captured_at": datetime.now(timezone.utc).isoformat(),
                    "static_violations": static_violations(),
                    "import_check": import_check(),
                    "inventory": [f"{m} {p}" for m, p in inventory(create_app(Settings(api_prefix="")).openapi())],
                    "unclassified_operations": unclassified(create_app(Settings(api_prefix="")).openapi())}
    if args.routes or args.disconnection:
        url = str(Settings().database_url)
        if not re.search(r"/stratai_test(?:_[a-z0-9_]+)?$", url):
            raise SystemExit("refusing: --routes needs DATABASE_URL pointing at an isolated stratai_test* database")
    if args.routes:
        report["route_check"] = route_check(args.event, url)
        report["route_check"]["epa_source"] = os.environ.get("EPA_SOURCE")  # which EPA source the routes ran with
    if args.disconnection:
        report["disconnection_check"] = disconnection_check(args.event, url)
        report["disconnection_check"]["epa_source"] = os.environ.get("EPA_SOURCE")
    report["ok"] = (not report["static_violations"] and report["import_check"]["ok"]
                    and not report["unclassified_operations"]
                    and report.get("route_check", {"ok": True})["ok"]
                    and report.get("disconnection_check", {"ok": True})["ok"])
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
